import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import atomic_json, main
from auditor.safety import AuditError
from tests.helpers import FixtureRepository, ScriptedProvider, call


class CLITests(unittest.TestCase):
    def test_invalid_url_nonzero_and_no_output(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            path = Path(directory) / "report.json"
            self.assertEqual(main(["--repo", "https://evil.test/a/b", "--output", str(path)]), 1)
            self.assertFalse(path.exists())

    def test_missing_key_nonzero_without_clone(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
            patch("agent.clone_repository") as clone,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(["--repo", "https://github.com/example/repo", "--output", "unused.json"]), 1
            )
            clone.assert_not_called()

    def test_atomic_report_and_non_ascii(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.json"
            expected = {"repository": "https://github.com/a/b", "violations": []}
            atomic_json(path, expected)
            self.assertEqual(json.loads(path.read_text()), expected)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_complete_cli_flow_with_real_git_tools_and_fake_provider(self):
        repo = FixtureRepository({"README.md": "# Healthy fixture\n"})
        self.addCleanup(repo.close)
        provider = ScriptedProvider(
            [
                call("list_files"),
                call("read_file", path="README.md"),
                call("submit_report", violations=[]),
            ]
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("agent.GeminiProvider", return_value=provider),
            patch("agent.clone_repository") as clone,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            clone.return_value.__enter__.return_value = repo.tools
            output, trace = Path(directory) / "report.json", Path(directory) / "trace.jsonl"
            result = main(
                [
                    "--repo",
                    "https://github.com/example/repo",
                    "--output",
                    str(output),
                    "--trace",
                    str(trace),
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.read_text())["violations"], [])
            self.assertTrue(trace.exists())

    def test_fatal_error_preserves_previous_report(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("agent.GeminiProvider", side_effect=AuditError("provider failed")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            output = Path(directory) / "report.json"
            output.write_text("previous completed report")
            self.assertEqual(
                main(["--repo", "https://github.com/example/repo", "--output", str(output)]), 1
            )
            self.assertEqual(output.read_text(), "previous completed report")

    def test_same_output_and_trace_rejected(self):
        with patch("agent.GeminiProvider"), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "--repo",
                        "https://github.com/example/repo",
                        "--output",
                        "same.json",
                        "--trace",
                        "same.json",
                    ]
                ),
                1,
            )
