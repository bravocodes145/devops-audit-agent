import json
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]


def main():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    output = ROOT / "docs" / "Rayyan_Qamar_23i-0815_Report.pdf"
    evidence = ROOT / "docs" / "evidence"
    summary = json.loads((ROOT / "docs/evaluation/latest/summary.json").read_text())
    report = json.loads((ROOT / "sample_report.json").read_text())
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Cover", parent=styles["Title"], fontSize=23, leading=30, alignment=TA_CENTER
        )
    )
    styles.add(
        ParagraphStyle(
            name="Caption", parent=styles["BodyText"], fontSize=10, leading=15, spaceAfter=10
        )
    )
    story = []

    def paragraph(text, style="BodyText"):
        return Paragraph(escape(text), styles[style])

    story.extend(
        [
            Spacer(1, 2 * cm),
            paragraph("AI Agent for DevOps Repository Auditing", "Cover"),
            Spacer(1, cm),
            paragraph("Rayyan Qamar", "Title"),
            paragraph("Roll number: 23i-0815 | Section: A", "Heading2"),
            paragraph("MLOps & Production AI Engineering — Assignment 2"),
            Spacer(1, cm),
            paragraph("Implementation and results", "Heading2"),
            paragraph(
                "The project is an unattended Python auditing agent. Gemini selects read-only inspection tools, interprets their results, and chooses follow-up calls. The application validates evidence and writes the required JSON report. No agent framework is used."
            ),
            Spacer(1, 0.5 * cm),
            paragraph(
                "Tools: list_files, read_file, search_code and git_log. Targets are read through Git objects without checkout, dependency installation or execution of repository code."
            ),
            Spacer(1, 0.5 * cm),
            paragraph("Repository: https://github.com/bravocodes145/devops-audit-agent"),
            paragraph("Report generated (UTC): " + datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")),
            Spacer(1, cm),
            paragraph("Evidence note", "Heading2"),
            paragraph(
                "Screenshots are real Edge browser captures from this computer, displaying saved command output, recorded agent artifacts and GitHub directly. They are not native terminal captures. Captions explain each image. Raw sources and actual capture times are included in docs/evidence/."
            ),
            PageBreak(),
        ]
    )
    captions = [
        (
            "01-cli.png",
            "1. Command-line interface",
            "The actual --help output shows the required --repo and --output arguments. The CLI runs without interactive prompts and exits nonzero when required setup or inspection fails.",
        ),
        (
            "02-tests.png",
            "2. Automated verification",
            "This capture displays the saved unittest run. Tests cover Git inspection, paths and symlinks, redaction, dynamic follow-up calls, report validation, provider failures, healthy empty reports and CLI behavior. These are offline tests with fake model responses, separate from the live evaluation.",
        ),
        (
            "03-lint.png",
            "3. Code checks",
            "Ruff checks passed on the project source. Formatting was also checked and its raw transcript is included. GitHub Actions repeats lint, formatting and the offline suite on Python 3.11, 3.12, 3.13 and 3.14.",
        ),
        (
            "04-evaluation.png",
            "4. Live evaluation",
            "The real Gemini model inspected three local synthetic repositories. It detected both obvious defects and the privileged PR workflow defect, and reported no findings on the healthy repository. It missed the separate PR-title shell injection. These small local results do not estimate hidden-test performance.",
        ),
        (
            "05-live-audit.png",
            "5. Public GitHub audit",
            f"The required CLI audited psf/requests. The recorded trace shows model-selected follow-up reads and a completed JSON report with {len(report['violations'])} findings. The target commit and timing are saved in docs/sample.trace.jsonl. An earlier run produced an unsupported warning; the unedited baseline is preserved and explained in the README.",
        ),
        (
            "06-github.png",
            "6. Public submission repository",
            "This is a direct browser screenshot of the public GitHub repository. The executable agent, tests, installation instructions, authentic JSON example and this PDF are submitted together. Only the repository URL is needed in the course submission field.",
        ),
    ]
    available_width = A4[0] - 3.6 * cm
    for filename, title, caption in captions:
        story.append(paragraph(title, "Heading1"))
        image = Image(str(evidence / filename))
        scale = min(available_width / image.imageWidth, (19 * cm) / image.imageHeight)
        image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
        story.extend([image, Spacer(1, 0.3 * cm), paragraph(caption, "Caption")])
        if filename == "04-evaluation.png":
            rows = [["Fixture", "Matched / expected", "Findings", "Unchanged"]]
            for run in summary["runs"]:
                rows.append(
                    [
                        run["fixture"],
                        f"{run['reference_matches']} / {run['expected']}",
                        str(run["reported"]),
                        str(run["target_unchanged"]),
                    ]
                )
            table = Table(rows, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(table)
        if filename != captions[-1][0]:
            story.append(PageBreak())

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(1.8 * cm, 1.1 * cm, "Rayyan Qamar | 23i-0815 | Section A")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, str(doc.page))

    SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.7 * cm,
        title="DevOps Repository Auditing - Rayyan Qamar",
        author="Rayyan Qamar",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    print(output)


if __name__ == "__main__":
    main()
