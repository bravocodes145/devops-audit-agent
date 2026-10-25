import html
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"


def record(name, command):
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    transcript = f"Captured UTC: {datetime.now(UTC).isoformat()}\nCommand: {' '.join(command)}\nExit code: {completed.returncode}\n\n{completed.stdout}{completed.stderr}"
    (EVIDENCE / f"{name}.txt").write_text(transcript, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"Evidence command failed: {name}; inspect its saved transcript")
    return transcript


def browser_document(title, text):
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Recorded execution evidence</title><style>
body {margin:32px;background:white;color:#151515;font:16px Arial,sans-serif}
h1 {font-size:24px;margin-bottom:8px} p {color:#555;font-size:14px}
pre {padding:20px;border:1px solid #bbb;white-space:pre-wrap;overflow-wrap:anywhere;
font:14px/1.5 Consolas,monospace;background:#fafafa}
</style>"""
        + f"<h1>{html.escape(title)}</h1><p>Rayyan Qamar | 23i-0815 | Section A. Saved machine output displayed in Edge.</p><pre>{html.escape(text)}</pre></html>"
    )


def main():
    from playwright.sync_api import sync_playwright

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    commands = {
        "01-cli": ("Required command-line interface", [sys.executable, "agent.py", "--help"]),
        "02-tests": (
            "Offline regression tests",
            [sys.executable, "-m", "unittest", "discover", "-v"],
        ),
        "03-lint": ("Lint and security checks", [sys.executable, "-m", "ruff", "check", "."]),
    }
    documents = {}
    for name, (title, command) in commands.items():
        documents[name] = (title, record(name, command))
    record("format", [sys.executable, "-m", "ruff", "format", "--check", "."])
    summary = json.loads((ROOT / "docs/evaluation/latest/summary.json").read_text())
    lines = [
        "Live Gemini evaluation on LOCAL SYNTHETIC repositories.",
        "Not instructor hidden repositories. Scores are provisional file/line matches.",
        "",
    ]
    for run in summary["runs"]:
        lines.extend(
            [
                f"{run['fixture'].upper()} | model={run['model']}",
                f"Detected {run['reference_matches']}/{run['expected']} reference defects; reported {run['reported']} findings.",
                f"Target unchanged: {run['target_unchanged']} | time: {run['elapsed_seconds']} seconds",
                f"Missed: {', '.join(run['missed']) or 'none'}",
                "",
            ]
        )
    documents["04-evaluation"] = ("Measured live evaluation results", "\n".join(lines))
    trace = [
        json.loads(line) for line in (ROOT / "docs/sample.trace.jsonl").read_text().splitlines()
    ]
    report = json.loads((ROOT / "sample_report.json").read_text())
    lines = [
        "PUBLIC GITHUB AUDIT — recorded live model/tool interaction",
        json.dumps(trace[0], indent=2),
        "",
    ]
    for event in trace:
        if event["event"] == "tool":
            lines.append(
                f"Turn {event['step']}: {event['name']}({json.dumps(event['arguments']) if event['name'] != 'submit_report' else 'final JSON report'})"
            )
    lines.extend(
        [
            "",
            json.dumps(trace[-1], indent=2),
            "",
            "Actual CLI output artifact:",
            json.dumps(report, indent=2),
        ]
    )
    documents["05-live-audit"] = (
        "Public repository audit and dynamic tool trace",
        "\n".join(lines),
    )
    captures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 960}, device_scale_factor=1)
        for name, (title, text) in documents.items():
            document = EVIDENCE / f"{name}.html"
            document.write_text(browser_document(title, text), encoding="utf-8")
            page.goto(document.as_uri())
            content_height = page.evaluate(
                "Math.ceil(document.querySelector('pre').getBoundingClientRect().bottom + 32)"
            )
            page.set_viewport_size({"width": 1280, "height": content_height})
            screenshot = EVIDENCE / f"{name}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            captures.append(
                {
                    "file": screenshot.name,
                    "source": document.name,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "type": "real Edge browser capture of saved execution data",
                }
            )
        page.set_viewport_size({"width": 1280, "height": 960})
        response = page.goto(
            "https://github.com/bravocodes145/devops-audit-agent",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        if response is None or response.status != 200:
            raise RuntimeError("Public GitHub repository could not be captured")
        page.locator(
            'a[href="/bravocodes145/devops-audit-agent/blob/main/agent.py"]:visible'
        ).first.wait_for(timeout=20000)
        page.screenshot(path=str(EVIDENCE / "06-github.png"))
        captures.append(
            {
                "file": "06-github.png",
                "source": page.url,
                "captured_at": datetime.now(UTC).isoformat(),
                "type": "real screenshot of the public GitHub repository",
            }
        )
        browser.close()
    (EVIDENCE / "manifest.json").write_text(
        json.dumps({"captures": captures}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved {len(captures)} authentic browser screenshots to {EVIDENCE}")


if __name__ == "__main__":
    main()
