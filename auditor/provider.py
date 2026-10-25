import json
import re
import time
import urllib.error
import urllib.request

from auditor.safety import AuditError


class GeminiProvider:
    def __init__(self, api_key, model="gemini-3.1-flash-lite", *, timeout=60, retries=3):
        if not api_key:
            raise AuditError(
                "GEMINI_API_KEY is missing. Set it in your environment or local .env file"
            )
        if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            raise AuditError("GEMINI_MODEL must be a model ID, without slashes or URL parameters")
        self.api_key, self.model = api_key, model
        self.timeout, self.retries = timeout, retries

    def generate(self, contents, declarations, system, *, timeout=None):
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": declarations}],
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
        }
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        deadline = time.monotonic() + (timeout if timeout is not None else 240)
        for attempt in range(self.retries + 1):
            delay = 2**attempt
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuditError("Gemini request deadline exceeded")
            try:
                with urllib.request.urlopen(
                    request, timeout=min(self.timeout, remaining)
                ) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise AuditError("Gemini response exceeded the response size limit")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise AuditError("Gemini returned a non-object response")
                candidates = data.get("candidates", [])
                if (
                    not isinstance(candidates, list)
                    or not candidates
                    or not isinstance(candidates[0], dict)
                    or "content" not in candidates[0]
                ):
                    raise AuditError(
                        "Gemini returned no usable candidate; check safety settings and quota"
                    )
                if candidates[0].get("finishReason") not in {None, "STOP"}:
                    raise AuditError(
                        "Gemini response was blocked or truncated; reduce the inspection scope"
                    )
                return candidates[0]["content"]
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                if status == 429:
                    delay = (
                        min(60, float(retry_after))
                        if re.fullmatch(r"\d{1,4}(?:\.\d{1,3})?", retry_after)
                        else 15
                    )
                exc.close()
                if status not in {429, 500, 502, 503, 504} or attempt == self.retries:
                    advice = {
                        400: "check your API key, model, and request compatibility",
                        401: "check GEMINI_API_KEY",
                        403: "check API access and key restrictions",
                        404: "set GEMINI_MODEL to an available function-calling model",
                        429: "free-tier quota or rate limit reached; wait and retry",
                    }.get(status, "retry later or check provider availability")
                    raise AuditError(f"Gemini API HTTP {status}: {advice}") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == self.retries:
                    raise AuditError(
                        "Gemini network request failed or timed out; check connectivity"
                    ) from None
            except (ValueError, KeyError, TypeError):
                raise AuditError("Gemini returned an invalid response") from None
            delay = min(delay, max(0, deadline - time.monotonic()))
            time.sleep(delay)
        raise AuditError("Gemini request failed")
