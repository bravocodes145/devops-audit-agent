import json
import unittest
from pathlib import Path

from tests.helpers import FixtureRepository
from tools import MAX_BLOB, RepositoryTools


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepository(
            {
                "README.md": "# Example\n",
                "ci.yml": "steps:\n  run: pytest || true\n",
                ".env": 'API_KEY="definitely-not-a-live-credential"\n',
                "binary.bin": b"binary\0value",
                "huge.txt": b"x" * (MAX_BLOB + 1),
                "odd name.txt": "hello unicode \u2713\n",
                "inject.py": "raise RuntimeError('NEVER EXECUTE')\n",
            }
        )
        self.addCleanup(self.repo.close)
        self.tools = self.repo.tools

    def test_inventory_hidden_paths_and_pagination(self):
        first = self.tools.list_files(limit=2)
        self.assertEqual(first["next_offset"], 2)
        names = [f["path"] for f in self.tools.list_files()["files"]]
        self.assertIn(".env", names)
        self.assertIn("odd name.txt", names)
        self.assertEqual(len(names), first["total"])

    def test_numbered_read_and_evidence_ledger(self):
        result = self.tools.read_file("ci.yml", 2, 2)
        self.assertEqual(result["lines"], [{"line": 2, "text": "  run: pytest || true"}])
        self.assertEqual(self.tools.observed[("ci.yml", 2)], "  run: pytest || true")

    def test_secret_removed_before_tools_return(self):
        result = self.tools.dispatch("read_file", {"path": ".env"})
        self.assertNotIn("definitely-not-a-live-credential", json.dumps(result))
        self.assertIn("[REDACTED]", json.dumps(result))

    def test_multiline_private_key_preserves_line_numbers(self):
        path = self.repo.work / "private.txt"
        path.write_text(
            "before\n-----BEGIN PRIVATE KEY-----\nTESTKEYMATERIAL\n-----END PRIVATE KEY-----\nafter\n"
        )
        self.repo.git("add", "private.txt")
        self.repo.git("commit", "-m", "multiline redaction fixture")
        tools = RepositoryTools(self.repo.work / ".git")
        output = tools.read_file("private.txt")
        self.assertNotIn("TESTKEYMATERIAL", json.dumps(output))
        self.assertEqual(output["lines"][-1], {"line": 5, "text": "after"})

    def test_literal_search_and_skips_are_explicit(self):
        result = self.tools.search_code("PYTEST || TRUE")
        self.assertEqual(result["matches"][0]["path"], "ci.yml")
        self.assertFalse(result["complete"])
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual(self.tools.search_code(".*")["total_matches"], 0)

    def test_invalid_paths_and_oversized_reads_are_tool_errors(self):
        for path in ("../.env", "/etc/passwd", "D:\\secret", "missing", "binary.bin", "huge.txt"):
            with self.subTest(path=path):
                self.assertIn("error", self.tools.dispatch("read_file", {"path": path}))

    def test_symlinks_are_not_followed(self):
        link = self.repo.work / "link"
        link.write_text("../../outside.env")
        oid = self.repo.git("hash-object", "-w", "link").decode().strip()
        self.repo.git("update-index", "--add", "--cacheinfo", f"120000,{oid},link")
        self.repo.git("commit", "-m", "symlink fixture")
        tools = RepositoryTools(self.repo.work / ".git")
        self.assertIn("Symlinks", tools.dispatch("read_file", {"path": "link"})["error"])

    def test_git_log_and_target_unchanged(self):
        before = self.repo.git("status", "--porcelain")
        self.assertIn("fixture snapshot", self.tools.git_log()["history"])
        self.tools.read_file("inject.py")
        self.tools.search_code("NEVER EXECUTE")
        self.assertEqual(before, self.repo.git("status", "--porcelain"))

    def test_unknown_tools_and_argument_types(self):
        self.assertIn("error", self.tools.dispatch("run_shell", {"command": "anything"}))
        self.assertIn("error", self.tools.dispatch("list_files", {"limit": True}))
        self.assertIn("error", self.tools.dispatch("read_file", ["README.md"]))
        self.assertIn("error", self.tools.dispatch("git_log", {"limit": 61}))

    def test_read_pagination(self):
        output = self.tools.read_file("ci.yml", 1, 1)
        self.assertEqual(output["next_line"], 2)
        self.assertTrue(Path(self.repo.work / "ci.yml").exists())
