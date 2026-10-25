import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auditor.safety import AuditError, Redactor, load_env, repository_url


class SafetyTests(unittest.TestCase):
    def test_workflow_permissions_and_inherited_secrets_are_not_credentials(self):
        redact = Redactor()
        value = "id-token: write\nsecrets: inherit\ncontents: write"
        self.assertEqual(redact(value), value)
        self.assertEqual(redact("write permission"), "write permission")

    def test_public_url_normalization(self):
        self.assertEqual(
            repository_url("https://github.com/owner/project.git/"),
            "https://github.com/owner/project",
        )

    def test_rejects_credentials_other_hosts_and_ambiguous_paths(self):
        for value in (
            "http://github.com/a/b",
            "file:///tmp/repo",
            "https://github.com.evil/a/b",
            "https://user:pass@github.com/a/b",
            "https://github.com/a/b/tree/main",
            "https://github.com/a/b?ref=main",
            "https://github.com/a/..",
            "https://github.com:443/a/b",
            "https://github.com/a/b#readme",
        ):
            with self.subTest(value=value), self.assertRaises(AuditError):
                repository_url(value)

    def test_environment_secret_is_scrubbed_everywhere(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "unit-test-credential-only"}):
            self.assertEqual(Redactor()("unit-test-credential-only"), "[REDACTED]")

    def test_common_secret_formats_and_remembered_values(self):
        redact = Redactor()
        for name, value in (
            ("password", "do-not-print-me"),
            ("api_key", "fixture-only-abcdef"),
            ("token", "ghp_" + "A" * 30),
        ):
            self.assertNotIn(value, redact(f'{name} = "{value}"'))
            self.assertNotIn(value, redact("echo " + value))

    def test_environment_references_and_placeholders_preserved(self):
        for value in (
            "API_KEY=${API_KEY}",
            "token: ${{ secrets.TOKEN }}",
            "password = os.getenv('PW')",
            "API_KEY=your_key",
            "secret: null",
        ):
            self.assertEqual(Redactor()(value), value)

    def test_env_loader_does_not_execute_and_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                'GEMINI_API_KEY="from-file"\nGEMINI_MODEL=model-name\nEVIL=$(echo test)\n'
            )
            with patch.dict(os.environ, {"GEMINI_API_KEY": "from-environment"}, clear=True):
                load_env(path)
                self.assertEqual(os.environ["GEMINI_API_KEY"], "from-environment")
                self.assertEqual(os.environ["GEMINI_MODEL"], "model-name")
                self.assertNotIn("EVIL", os.environ)
