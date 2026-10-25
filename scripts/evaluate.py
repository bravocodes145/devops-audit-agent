import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from agent import atomic_json
from auditor.loop import AuditAgent
from auditor.provider import GeminiProvider
from auditor.safety import AuditError, Redactor, load_env
from tests.helpers import FixtureRepository

EXPECTED = {
    "obvious": [
        {"name": "CI ignores failing tests", "file": ".github/workflows/ci.yml", "lines": [13]},
        {"name": "User-specific absolute runtime path", "file": "main.py", "lines": [3]},
    ],
    "subtle": [
        {
            "name": "Untrusted PR code executes in privileged target workflow",
            "file": ".github/workflows/review.yml",
            "lines": [3, 6, 13, 14, 16, 18],
        },
        {
            "name": "PR title is interpolated directly into shell code",
            "file": ".github/workflows/review.yml",
            "lines": [20],
        },
    ],
    "healthy": [],
}


def score(violations, expected):
    matched = set()
    correct = 0
    for violation in violations:
        candidates = [
            i
            for i, rule in enumerate(expected)
            if i not in matched
            and violation["file"] == rule["file"]
            and violation["line"] in rule["lines"]
        ]
        if candidates:
            matched.add(candidates[0])
            correct += 1
    return {
        "reference_matches": correct,
        "reported": len(violations),
        "expected": len(expected),
        "precision": correct / len(violations) if violations else (1.0 if not expected else None),
        "recall": correct / len(expected) if expected else None,
        "missed": [r["name"] for i, r in enumerate(expected) if i not in matched],
        "method": "Provisional exact-file/accepted-line matching; extra findings need human review. Not hidden-test performance.",
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate audit results on local fixtures")
    parser.add_argument(
        "--live", action="store_true", required=True, help="Explicit consent to spend Gemini quota"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("docs/evaluation"))
    parser.add_argument("--fixture", choices=list(EXPECTED), action="append")
    args = parser.parse_args()
    load_env(Path(__file__).resolve().parents[1] / ".env")
    provider = GeminiProvider(
        os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in args.fixture or EXPECTED:
        repo = FixtureRepository(fixture=name)
        try:
            before = repo.git("status", "--porcelain")
            started = time.monotonic()
            with (args.output_dir / f"{name}.trace.jsonl").open("w", encoding="utf-8") as trace:
                report = AuditAgent(
                    provider, repo.tools, max_steps=20, timeout=600, trace=trace
                ).run("fixture://" + name)
            unchanged = repo.git("status", "--porcelain") == before
            atomic_json(args.output_dir / f"{name}.json", report)
            result = {
                "fixture": name,
                "model": provider.model,
                "target_unchanged": unchanged,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "timestamp": datetime.now(UTC).isoformat(),
                **score(report["violations"], EXPECTED[name]),
            }
            results.append(result)
            print(json.dumps(result), flush=True)
            atomic_json(args.output_dir / "summary.json", {"runs": results})
        finally:
            repo.close()


if __name__ == "__main__":
    try:
        main()
    except (AuditError, OSError, ValueError) as exc:
        print("Evaluation failed: " + Redactor()(str(exc)), file=sys.stderr)
        raise SystemExit(1) from None
