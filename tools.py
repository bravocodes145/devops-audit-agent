import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from auditor.safety import AuditError, Redactor, repository_url

MAX_BLOB = 256 * 1024
MAX_FILES = 20_000
MAX_SEARCH_BYTES = 16 * 1024 * 1024


def git_env():
    env = os.environ.copy()

    for name in tuple(env):
        if name.startswith("GIT_"):
            env.pop(name)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="Never",
        GIT_LFS_SKIP_SMUDGE="1",
    )
    return env


def git(args, *, timeout=30):
    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.https.allow=always",
                *args,
            ],
            capture_output=True,
            timeout=timeout,
            env=git_env(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise AuditError("Git is required; install it and ensure it is on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise AuditError(
            "Git operation timed out; try a smaller repository or check connectivity"
        ) from exc
    if proc.returncode:
        raise AuditError(
            "Git operation failed; verify the repository is public, nonempty, and reachable"
        )
    return proc.stdout


@contextmanager
def clone_repository(url: str):
    url = repository_url(url)
    with tempfile.TemporaryDirectory(prefix="devops-audit-") as directory:
        target = Path(directory) / "objects.git"
        git(
            [
                "clone",
                "--bare",
                "--depth=60",
                "--single-branch",
                "--no-local",
                "--",
                url,
                str(target),
            ],
            timeout=120,
        )
        yield RepositoryTools(target)


class RepositoryTools:
    def __init__(self, git_dir: Path, redactor=None):
        self.git_dir = Path(git_dir).resolve()
        self.redact = redactor or Redactor()
        self.commit = self._git(["rev-parse", "HEAD"]).decode().strip()
        raw = self._git(["ls-tree", "-r", "-z", "-l", "HEAD"])
        self.files = {}
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, oid, size = metadata.decode().split()
            self.files[path.decode("utf-8", errors="replace")] = {
                "mode": mode,
                "kind": kind,
                "oid": oid,
                "size": int(size) if size != "-" else 0,
            }
            if len(self.files) > MAX_FILES:
                raise AuditError(f"Repository exceeds the {MAX_FILES:,}-file inspection limit")
        self.observed = {}
        self.inventory_observed = False
        self.inventory_seen = set()

    def _git(self, args):
        return git(["--git-dir=" + str(self.git_dir), *args])

    def _path(self, path):
        if not isinstance(path, str) or "\\" in path or "\0" in path:
            raise ValueError("Use a repository-relative POSIX path")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or path not in self.files:
            raise ValueError("Path is absent from the tracked repository snapshot")
        info = self.files[path]
        if info["mode"] == "120000" or info["kind"] != "blob":
            raise ValueError("Symlinks and submodules are not followed")
        return info

    def _lines(self, path):
        info = self._path(path)
        if info["size"] > MAX_BLOB:
            raise ValueError(f"File exceeds the {MAX_BLOB}-byte read limit")
        raw = self._git(["cat-file", "blob", info["oid"]])
        if b"\0" in raw:
            raise ValueError("Binary file cannot be inspected as text")

        text = self.redact(raw.decode("utf-8", errors="replace"))

        if text.count("\n") != raw.count(b"\n"):
            decoded = raw.decode("utf-8", errors="replace")
            for pattern in self.redact.patterns[:1]:
                decoded = pattern.sub(
                    lambda m: "[REDACTED]" + "\n" * m.group().count("\n"), decoded
                )
            text = self.redact(decoded)
        return text.splitlines()

    @staticmethod
    def _integer(value, lower, upper):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"Expected an integer between {lower} and {upper}")

    def list_files(self, offset=0, limit=300):
        self._integer(offset, 0, MAX_FILES)
        self._integer(limit, 1, 1000)
        names = sorted(self.files)
        selected = names[offset : offset + limit]
        self.inventory_observed = True
        self.inventory_seen.update(selected)
        return {
            "commit": self.commit,
            "total": len(names),
            "files": [
                {"path": p, "size": self.files[p]["size"], "mode": self.files[p]["mode"]}
                for p in selected
            ],
            "next_offset": offset + limit if offset + limit < len(names) else None,
        }

    def read_file(self, path, start_line=1, end_line=180):
        self._integer(start_line, 1, 1_000_000)
        self._integer(end_line, start_line, start_line + 299)
        lines = self._lines(path)
        selected = []
        budget = 24_000
        for number in range(start_line, min(end_line, len(lines)) + 1):
            text = lines[number - 1]
            if len(text) > budget:
                break
            budget -= len(text)
            self.observed[(path, number)] = text
            selected.append({"line": number, "text": text})
        last = selected[-1]["line"] if selected else start_line - 1
        return {
            "path": path,
            "total_lines": len(lines),
            "lines": selected,
            "next_line": last + 1 if last < len(lines) else None,
            "note": "A very long line may require search_code; text output is capped at 24,000 characters.",
        }

    def search_code(self, pattern, offset=0, limit=60):
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 200:
            raise ValueError("Search pattern must contain 1–200 characters")
        self._integer(offset, 0, 100_000)
        self._integer(limit, 1, 100)
        matches, skipped, total_bytes = [], [], 0
        entries = sorted(self.files.items())
        deadline = time.monotonic() + 25
        for index, (path, info) in enumerate(entries):
            if time.monotonic() >= deadline:
                skipped.extend(
                    {"path": remaining, "reason": "search time budget"}
                    for remaining, _ in entries[index:]
                )
                break
            if total_bytes + info["size"] > MAX_SEARCH_BYTES:
                skipped.append({"path": path, "reason": "search byte budget"})
                continue
            try:
                lines = self._lines(path)
            except ValueError as exc:
                skipped.append({"path": path, "reason": str(exc)})
                continue
            total_bytes += info["size"]
            for number, line in enumerate(lines, 1):
                if pattern.casefold() in line.casefold():
                    matches.append({"path": path, "line": number, "text": line[:2000]})
        selected = matches[offset : offset + limit]
        for item in selected:
            self.observed[(item["path"], item["line"])] = item["text"]
        return {
            "matches": selected,
            "total_matches": len(matches),
            "skipped": skipped[:100],
            "skipped_count": len(skipped),
            "complete": not skipped,
            "next_offset": offset + limit if offset + limit < len(matches) else None,
        }

    def git_log(self, limit=20):
        self._integer(limit, 1, 60)
        raw = self._git(["log", f"-n{limit}", "--format=%h%x09%ad%x09%s", "--date=iso-strict"])
        return {
            "history": self.redact(raw.decode("utf-8", errors="replace"))[:16_000],
            "scope": "Default branch only; clone depth 60. No remote protection or CI-run state is available.",
        }

    def dispatch(self, name, arguments):
        if name not in {"list_files", "read_file", "search_code", "git_log"}:
            return {"error": "Unknown tool; use a declared inspection tool"}
        if not isinstance(arguments, dict):
            return {"error": "Tool arguments must be an object"}
        try:
            result = getattr(self, name)(**arguments)

            from auditor.loop import sanitize

            return sanitize(result, self.redact)
        except (TypeError, ValueError) as exc:
            return {"error": self.redact(str(exc))}
