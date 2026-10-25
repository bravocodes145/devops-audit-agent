import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from auditor.loop import AuditAgent
from auditor.provider import GeminiProvider
from auditor.safety import AuditError, Redactor, load_env, repository_url
from tools import clone_repository


def atomic_json(path, report):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Evidence-based, read-only DevOps GitHub auditing agent"
    )
    parser.add_argument("--repo", required=True, help="Public HTTPS GitHub repository URL")
    parser.add_argument("--output", required=True, type=Path, help="Destination JSON report")
    parser.add_argument("--trace", type=Path, help="Optional sanitized JSONL tool-call evidence")
    parser.add_argument(
        "--max-steps", type=int, default=32, help="Model/tool turns (default 32; maximum 100)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1200,
        help="Investigation seconds, excluding clone (default 1200)",
    )
    args = parser.parse_args(argv)
    trace = None
    try:
        if not 2 <= args.max_steps <= 100 or not 30 <= args.timeout <= 3600:
            raise AuditError("Use --max-steps between 2 and 100 and --timeout between 30 and 3600")
        url = repository_url(args.repo)
        load_env(Path(__file__).resolve().parent / ".env")
        provider = GeminiProvider(
            os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        )
        if args.trace:
            if args.trace.resolve() == args.output.resolve():
                raise AuditError("--trace and --output must use different paths")
            args.trace.parent.mkdir(parents=True, exist_ok=True)
            trace = args.trace.open("w", encoding="utf-8")
        print(f"Inspecting {url} (read-only)...", file=sys.stderr)
        with clone_repository(url) as inspection:
            report = AuditAgent(
                provider, inspection, max_steps=args.max_steps, timeout=args.timeout, trace=trace
            ).run(url)
            atomic_json(args.output, report)
        print(
            f"Completed: {len(report['violations'])} findings. Report: {args.output}",
            file=sys.stderr,
        )
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print("Audit failed: " + Redactor()(str(exc)), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Audit interrupted; no completed report was written", file=sys.stderr)
        return 130
    finally:
        if trace is not None:
            trace.close()


if __name__ == "__main__":
    raise SystemExit(main())
