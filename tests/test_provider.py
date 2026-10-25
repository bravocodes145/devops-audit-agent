import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from auditor.provider import GeminiProvider
from auditor.safety import AuditError


class ProviderTests(unittest.TestCase):
    def test_rate_limit_honors_bounded_retry_after(self):
        error = urllib.error.HTTPError(
            "https://provider.invalid", 429, "rate limit", {"Retry-After": "45"}, io.BytesIO(b"")
        )
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[error, self.response({"candidates": [{"content": {"parts": []}}]})],
            ),
            patch("time.sleep") as sleep,
        ):
            GeminiProvider("fake-only").generate([], [], "system")
            sleep.assert_called_once_with(45.0)

    def response(self, value):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(value).encode()
        return response

    def test_native_tool_call_is_passed_through_with_signature(self):
        content = {
            "role": "model",
            "parts": [
                {"thoughtSignature": "opaque", "functionCall": {"name": "list_files", "args": {}}}
            ],
        }
        with patch(
            "urllib.request.urlopen",
            return_value=self.response(
                {"candidates": [{"finishReason": "STOP", "content": content}]}
            ),
        ) as network:
            result = GeminiProvider("fake-only").generate([], [], "system")
            self.assertEqual(result, content)
            request = network.call_args.args[0]
            self.assertEqual(request.get_header("X-goog-api-key"), "fake-only")
            self.assertNotIn("fake-only", request.full_url)
            self.assertEqual(
                json.loads(request.data)["toolConfig"]["functionCallingConfig"]["mode"], "ANY"
            )

    def test_transient_error_retried(self):
        error = urllib.error.HTTPError(
            "https://provider.invalid", 503, "unavailable", {}, io.BytesIO(b"private body")
        )
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[error, self.response({"candidates": [{"content": {"parts": []}}]})],
            ) as network,
            patch("time.sleep"),
        ):
            GeminiProvider("fake-only").generate([], [], "system")
            self.assertEqual(network.call_count, 2)

    def test_authentication_error_never_prints_provider_body(self):
        error = urllib.error.HTTPError(
            "https://provider.invalid",
            403,
            "unsafe-details",
            {},
            io.BytesIO(b"sensitive-raw-token"),
        )
        with (
            patch("urllib.request.urlopen", side_effect=error),
            self.assertRaises(AuditError) as raised,
        ):
            GeminiProvider("fake-only").generate([], [], "system")
        self.assertIn("HTTP 403", str(raised.exception))
        self.assertNotIn("sensitive-raw-token", str(raised.exception))

    def test_network_errors_and_malformed_payloads(self):
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError),
            self.assertRaisesRegex(AuditError, "timed out"),
        ):
            GeminiProvider("fake-only", retries=0).generate([], [], "system")
        with (
            patch("urllib.request.urlopen", return_value=self.response({})),
            self.assertRaisesRegex(AuditError, "no usable candidate"),
        ):
            GeminiProvider("fake-only").generate([], [], "system")

    def test_truncated_response_is_fatal(self):
        with (
            patch(
                "urllib.request.urlopen",
                return_value=self.response(
                    {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
                ),
            ),
            self.assertRaisesRegex(AuditError, "truncated"),
        ):
            GeminiProvider("fake-only").generate([], [], "system")

    def test_missing_key_and_model_url_injection_rejected(self):
        for key, model in (("", "gemini-flash"), ("fake-only", "bad/model?key=anything")):
            with self.assertRaises(AuditError):
                GeminiProvider(key, model)
