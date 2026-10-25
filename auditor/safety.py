import os
import re
from pathlib import Path
from urllib.parse import urlsplit


class AuditError(Exception):
    pass


def repository_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise AuditError("Use an HTTPS public GitHub URL: https://github.com/owner/repository")
    parts = parsed.path.rstrip("/").split("/")
    if len(parts) != 3 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts[1:]):
        raise AuditError("Repository URL must contain exactly an owner and repository name")
    owner, name = parts[1:]
    name = name.removesuffix(".git")
    if owner in {".", ".."} or name in {"", ".", ".."}:
        raise AuditError("Invalid repository name")
    return f"https://github.com/{owner}/{name}"


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in {"GEMINI_API_KEY", "GEMINI_MODEL"}:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


class Redactor:
    patterns = (
        re.compile(
            r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----", re.S
        ),
        re.compile(
            r"\b(?:AIza[\w-]{25,}|gh[pousr]_[\w]{20,}|github_pat_[\w]{20,}|AKIA[A-Z0-9]{16}|sk-[\w-]{20,}|AQ\.[\w-]{25,})\b"
        ),
        re.compile(r"(?i)(?:https?|postgres(?:ql)?|mysql|redis)://[^\s/:]+:[^\s/@]+@"),
    )
    assignment = re.compile(
        r"(?i)([\w.-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\w.-]*[\"']?\s*[:=]\s*)([\"']?)([^\s\"'#,;]+)([\"']?)"
    )

    def __init__(self):
        self.values = {v for k, v in os.environ.items() if k == "GEMINI_API_KEY" and v}

    def __call__(self, text: str) -> str:
        for pattern in self.patterns:
            for match in pattern.finditer(text):
                self.values.add(match.group())
            text = pattern.sub("[REDACTED]", text)

        def replace(match):
            value = match.group(3)
            key = match.group(1).strip().rstrip(":= ").strip("\"'").lower()
            if key in {"id-token", "secrets"} and value in {"read", "write", "none", "inherit"}:
                return match.group()
            if value.startswith(
                ("$", "os.", "process.", "env.", "[REDACTED]")
            ) or value.lower() in {
                "none",
                "null",
                "true",
                "false",
                "example",
                "placeholder",
                "your_key",
                "",
            }:
                return match.group()
            self.values.add(value)
            return match.group(1) + match.group(2) + "[REDACTED]" + match.group(4)

        text = self.assignment.sub(replace, text)
        for value in sorted(self.values, key=len, reverse=True):
            if value != "[REDACTED]":
                text = text.replace(value, "[REDACTED]")
        return text
