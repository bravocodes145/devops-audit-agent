import io
import json
import unittest

from auditor.contracts import validate_report
from auditor.loop import AuditAgent
from auditor.safety import AuditError
from tests.helpers import FixtureRepository, ScriptedProvider, call, finding

URL = "https://github.com/example/offline-fixture"


class AgentTests(unittest.TestCase):
    def test_malformed_provider_calls_fail_cleanly(self):
        for response in (
            {"parts": [None]},
            {"parts": [{"functionCall": []}]},
            {"parts": [{"functionCall": {"name": []}}]},
        ):
            with self.subTest(response=response), self.assertRaises(AuditError):
                AuditAgent(ScriptedProvider([response]), self.tools).run(URL)

    def setUp(self):
        self.repo = FixtureRepository(
            {"ci.yml": "steps:\n  run: pytest || true\n", "README.md": "# Test fixture\n"}
        )
        self.addCleanup(self.repo.close)
        self.tools = self.repo.tools

    def test_dynamic_follow_up_uses_observation_and_preserves_signatures(self):
        discover = call("list_files")
        discover["parts"][0]["thoughtSignature"] = "opaque-provider-signature"

        def inspect(contents):
            files = contents[-1]["parts"][0]["functionResponse"]["response"]["result"]["files"]
            target = next(f["path"] for f in files if f["path"].endswith(".yml"))
            self.assertEqual(
                contents[-2]["parts"][0]["thoughtSignature"], "opaque-provider-signature"
            )
            return call("read_file", path=target)

        def interpret(contents):
            observed = contents[-1]["parts"][0]["functionResponse"]["response"]["result"]
            self.assertIn("pytest || true", observed["lines"][1]["text"])
            return call("submit_report", violations=[finding()])

        provider = ScriptedProvider([discover, inspect, interpret])
        trace = io.StringIO()
        report = AuditAgent(provider, self.tools, trace=trace).run(URL)
        self.assertEqual(report["violations"][0]["rule_id"], "CI-001")
        self.assertEqual(len(provider.requests), 3)
        self.assertNotIn("opaque-provider-signature", trace.getvalue())
        self.assertEqual(json.loads(trace.getvalue().splitlines()[-1])["event"], "complete")

    def test_invalid_evidence_is_returned_for_correction(self):
        provider = ScriptedProvider(
            [
                call("list_files"),
                call("read_file", path="ci.yml"),
                call("submit_report", violations=[finding(evidence="invented evidence")]),
                call("submit_report", violations=[finding()]),
            ]
        )
        report = AuditAgent(provider, self.tools).run(URL)
        self.assertEqual(len(report["violations"]), 1)
        feedback = provider.requests[-1][-1]["parts"][0]["functionResponse"]["response"]["result"]
        self.assertIn("error", feedback)

    def test_healthy_empty_report_is_valid(self):
        provider = ScriptedProvider(
            [
                call("list_files"),
                call("read_file", path="README.md"),
                call("submit_report", violations=[]),
            ]
        )
        self.assertEqual(
            AuditAgent(provider, self.tools).run(URL), {"repository": URL, "violations": []}
        )

    def test_no_report_when_budget_exhausted(self):
        provider = ScriptedProvider([call("list_files"), call("git_log")])
        with self.assertRaisesRegex(AuditError, "budget exhausted"):
            AuditAgent(provider, self.tools, max_steps=2).run(URL)

    def test_unknown_tool_can_be_recovered(self):
        provider = ScriptedProvider(
            [
                call("execute_code"),
                call("list_files"),
                call("read_file", path="README.md"),
                call("submit_report", violations=[]),
            ]
        )
        self.assertEqual(AuditAgent(provider, self.tools).run(URL)["violations"], [])

    def test_submission_cannot_share_turn_with_uninterpreted_read(self):
        mixed = call("read_file", path="ci.yml")
        mixed["parts"].extend(call("submit_report", violations=[finding()])["parts"])
        provider = ScriptedProvider(
            [call("list_files"), mixed, call("submit_report", violations=[finding()])]
        )
        self.assertEqual(len(AuditAgent(provider, self.tools).run(URL)["violations"]), 1)
        error = provider.requests[-1][-1]["parts"][1]["functionResponse"]["response"]["result"]
        self.assertIn("error", error)

    def test_report_contract_and_citation_validation(self):
        self.tools.list_files()
        self.tools.read_file("ci.yml")
        mutations = [
            dict(severity="info"),
            dict(line=999),
            dict(line=True),
            dict(file="missing"),
            dict(file=None, line=2),
            dict(rule_id="bad"),
            dict(description=""),
            dict(evidence="fake"),
        ]
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_report({"violations": [finding(**changes)]}, URL, self.tools)
        extra = finding()
        extra["extra"] = "unexpected"
        with self.assertRaises(ValueError):
            validate_report({"violations": [extra]}, URL, self.tools)

    def test_missing_file_uses_null_and_duplicates_collapsed(self):
        self.tools.list_files()
        self.tools.read_file("ci.yml")
        absence = finding(
            file=None,
            line=None,
            evidence="Complete inventory contains no CI provider configuration",
        )
        report = validate_report({"violations": [absence, absence]}, URL, self.tools)
        self.assertEqual(len(report["violations"]), 1)
        self.assertIsNone(report["violations"][0]["file"])

    def test_absence_claim_needs_all_inventory_pages(self):
        self.tools.list_files(limit=1)
        self.tools.read_file("ci.yml")
        with self.assertRaisesRegex(ValueError, "all list_files pages"):
            validate_report({"violations": [finding(file=None, line=None)]}, URL, self.tools)

    def test_no_static_scanner_fallback_on_provider_failure(self):
        class FailingProvider:
            def generate(self, *args, **kwargs):
                raise AuditError("provider unavailable")

        with self.assertRaisesRegex(AuditError, "provider unavailable"):
            AuditAgent(FailingProvider(), self.tools).run(URL)
