#!/usr/bin/env python3
"""Generate PDF from the Import Task Document Specification Markdown."""

import argparse
import sys
from pathlib import Path

import markdown
from weasyprint import HTML


_CSS = """
@page {
  size: A4;
  margin: 2cm 2.5cm;
  @bottom-center {
    content: counter(page);
    font-size: 9pt;
    color: #888;
  }
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  font-size: 11pt;
  line-height: 1.6;
  color: #1a1a1a;
}

h1 { font-size: 18pt; color: #1a1a2e; border-bottom: 2px solid #e0e0e0; padding-bottom: 4pt; margin-top: 24pt; }
h2 { font-size: 14pt; color: #16213e; margin-top: 18pt; }
h3 { font-size: 12pt; color: #0f3460; margin-top: 14pt; }

code {
  font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 9pt;
  background: #f4f4f4;
  padding: 1pt 3pt;
  border-radius: 3pt;
}

pre {
  background: #f8f8f8;
  border: 1px solid #ddd;
  border-radius: 4pt;
  padding: 8pt 10pt;
  font-size: 8.5pt;
  overflow-x: auto;
  line-height: 1.4;
}

pre code { background: none; padding: 0; }

table {
  border-collapse: collapse;
  width: 100%;
  margin: 10pt 0;
  font-size: 10pt;
}

th, td {
  border: 1px solid #ccc;
  padding: 4pt 8pt;
  text-align: left;
}

th { background: #f0f0f0; font-weight: 600; }

blockquote {
  border-left: 4px solid #ddd;
  margin: 10pt 0;
  padding: 4pt 10pt;
  color: #555;
}

ul, ol { margin: 6pt 0; padding-left: 20pt; }
li { margin: 2pt 0; }

hr { border: none; border-top: 1px solid #ddd; margin: 16pt 0; }

strong { font-weight: 600; }
em { font-style: italic; }

/* Title page */
h1:first-of-type {
  font-size: 24pt;
  text-align: center;
  margin-top: 80pt;
  border: none;
}

p:first-of-type {
  text-align: center;
  color: #555;
  font-size: 11pt;
}
"""


def markdown_to_pdf(md_path: Path, pdf_path: Path) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["fenced_code", "tables", "codehilite", "toc"],
    )
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>{_CSS}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    HTML(string=html_doc).write_pdf(str(pdf_path))
    print(f"PDF generated: {pdf_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate PDF from ITD specification Markdown",
    )
    parser.add_argument(
        "--input",
        default="docs/import-task-spec.md",
        help="Input Markdown file (default: docs/import-task-spec.md)",
    )
    parser.add_argument(
        "--output",
        default="docs/import-task-spec.pdf",
        help="Output PDF file (default: docs/import-task-spec.pdf)",
    )
    args = parser.parse_args()

    md_path = Path(args.input)
    if not md_path.exists():
        print(f"Error: {md_path} not found", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(args.output)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_to_pdf(md_path, pdf_path)


if __name__ == "__main__":
    main()
