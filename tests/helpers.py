import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from tools import RepositoryTools


class FixtureRepository:
    def __init__(self, files=None, fixture=None):
        self.directory = tempfile.TemporaryDirectory(prefix="audit-test-")
        self.root = Path(self.directory.name)
        self.work = self.root / "source"
        self.work.mkdir()
        if fixture:
            shutil.copytree(
                Path(__file__).parent / "fixtures" / fixture, self.work, dirs_exist_ok=True
            )
        for name, content in (files or {}).items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode() if isinstance(content, str) else content)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Offline Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", "fixture snapshot")
        self.tools = RepositoryTools(self.work / ".git")

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.work,
            capture_output=True,
            check=True,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
        ).stdout

    def close(self):
        self.directory.cleanup()


def call(name, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def generate(self, contents, declarations, system, **kwargs):
        self.requests.append(list(contents))
        response = next(self.responses)
        return response(contents) if callable(response) else response


def finding(**changes):
    item = {
        "rule_id": "CI-001",
        "category": "ci",
        "severity": "high",
        "file": "ci.yml",
        "line": 2,
        "description": "Test failures are ignored by the CI command",
        "evidence": "run: pytest || true",
        "recommendation": "Remove || true to propagate the failing test exit code",
    }
    item.update(changes)
    return item
