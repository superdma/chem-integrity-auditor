#!/usr/bin/env python3
"""Render a Markdown audit report to a print-ready A4 PDF.

The report keeps its Chinese typography and evidence figures: images are
embedded as data URIs, tables stay tables, and each Level ≥ 2 finding keeps
its 证据图 block next to the finding. Rendering uses headless Chrome/Chromium
(no extra Python dependency); poppler is only used to report the page count.

Usage:
    python3 render_report_pdf.py audit_report.md
    python3 render_report_pdf.py audit_report.md --output audit_report.pdf
    python3 render_report_pdf.py audit_report.md --keep-html --chrome chromium

Exit 0 = PDF written, 1 = render failure, 2 = unreadable input.
No LLM SDK. Python 3.8+.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "headless_shell",
]


def find_chrome(explicit: str = "") -> str:
    if explicit:
        path = shutil.which(explicit) or (explicit if Path(explicit).is_file() else "")
        if not path:
            raise SystemExit(f"chrome executable not found: {explicit}")
        return path
    env = os.environ.get("CHROME") or os.environ.get("CHROME_BIN")
    if env:
        path = shutil.which(env) or (env if Path(env).is_file() else "")
        if path:
            return path
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(
        "headless Chrome/Chromium not found; install google-chrome or chromium, "
        "or pass --chrome /path/to/chrome")


def image_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def inline(text: str, base: Path) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )
    return text


def render_markdown(text: str, base: Path) -> str:
    lines = text.splitlines()
    blocks = []
    first_h2 = True
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        fence = re.match(r"^\s*```", line)
        if fence:
            buf = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*```", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            kind = f"h{level}"
            cls = ""
            if level == 2 and first_h2:
                cls = ' class="first"'
                first_h2 = False
            blocks.append(f"<{kind}{cls}>{inline(m.group(2), base)}</{kind}>")
            i += 1
            continue

        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            body = []
            for ri, row in enumerate(cells):
                if ri == 1 and all(re.fullmatch(r":?-{2,}:?", c) for c in row):
                    continue
                tag = "th" if ri == 0 else "td"
                body.append("<tr>" + "".join(
                    f"<{tag}>{inline(c, base)}</{tag}>" for c in row) + "</tr>")
            blocks.append("<table>" + "".join(body) + "</table>")
            continue

        img = re.match(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if img:
            alt, url = img.group(1), img.group(2).strip()
            caption = ""
            if i + 1 < len(lines) and re.match(r"^\s*\*[^*].*\*\s*$", lines[i + 1]):
                caption = lines[i + 1].strip().strip("*")
                i += 1
            src = url
            candidate = (base / url).resolve()
            if candidate.is_file():
                src = image_data_uri(candidate)
            cls = "ev-source" if ("原文" in alt or "原图" in alt) else "ev-crop"
            blocks.append(
                f'<figure class="{cls}"><img alt="{html.escape(alt, quote=True)}" '
                f'src="{src}">' +
                (f"<figcaption>{inline(caption, base)}</figcaption>" if caption else "") +
                "</figure>")
            i += 1
            continue

        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            blocks.append("<ul>" + "".join(
                f"<li>{inline(x, base)}</li>" for x in items) + "</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            blocks.append("<ol>" + "".join(
                f"<li>{inline(x, base)}</li>" for x in items) + "</ol>")
            continue

        if line.lstrip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            blocks.append("<blockquote>" + inline(" ".join(buf), base) + "</blockquote>")
            continue

        if re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", line):
            blocks.append("<hr>")
            i += 1
            continue

        buf = []
        while i < len(lines) and lines[i].strip() and not (
                re.match(r"^(#{1,4})\s|^\s*\||^\s*!\[|^\s*[-*]\s|^>|^\s*\d+\.\s", lines[i])):
            buf.append(lines[i].strip())
            i += 1
        blocks.append("<p>" + inline(" ".join(buf), base) + "</p>")
    return "\n".join(blocks)


CSS = """
@page { size: A4; margin: 17mm 15mm 16mm 15mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  margin: 0; color: #1b1b1b; background: #fff;
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
               "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 10.2pt; line-height: 1.62;
}
h1 { font-size: 21pt; line-height: 1.3; margin: 0 0 7mm;
     padding-bottom: 3mm; border-bottom: 2.2pt solid #1b1b1b; }
h2 { font-size: 14.5pt; margin: 0 0 4mm; padding-bottom: 1.6mm;
     border-bottom: 0.8pt solid #cfcfcf; break-before: page; }
h2.first { break-before: auto; margin-top: 2mm; }
h3 { font-size: 12pt; margin: 6mm 0 2.5mm; color: #8a1f18; break-after: avoid; }
h4 { font-size: 10.8pt; margin: 5mm 0 2mm; color: #b3261e; break-after: avoid; }
p { margin: 2.2mm 0; orphans: 3; widows: 3; }
ul, ol { margin: 2mm 0; padding-left: 6mm; }
li { margin: 1.2mm 0; orphans: 3; widows: 3; }
strong { color: #000; }
code { background: #f1f1ee; padding: 0.2mm 1mm; border-radius: 1mm;
       font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 0.88em; }
blockquote { margin: 3mm 0; padding: 2.5mm 4mm; border-left: 2.2pt solid #b3261e;
             background: #fbf6f5; color: #333; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0; font-size: 8.7pt;
        break-inside: avoid; }
th, td { border: 0.6pt solid #cfcfcf; padding: 1.4mm 2mm; text-align: left;
         vertical-align: top; }
th { background: #efefec; font-weight: 700; }
table th:first-child, table td:first-child { width: 21%; }
tr { break-inside: avoid; }
figure { margin: 3mm 0 4mm; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; border: 0.6pt solid #d8d8d8; border-radius: 1mm; }
figure.ev-source img { max-height: 90mm; width: auto; }
figure.ev-crop img { max-height: 120mm; }
figcaption { font-size: 8.2pt; color: #666; margin-top: 1.6mm; line-height: 1.45; }
hr { border: 0; border-top: 0.6pt solid #ddd; margin: 5mm 0; }
a { color: #0b57d0; text-decoration: none; }
pre { background: #f6f6f3; padding: 3mm; border: 0.6pt solid #e2e2dd;
      white-space: pre-wrap; font-size: 8.5pt; }
"""



def stamp_page_numbers(pdf: Path) -> bool:
    """Stamp ``N / M`` in the bottom margin when pypdf + reportlab exist."""
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return False
    try:
        reader = PdfReader(str(pdf))
        total = len(reader.pages)
        writer = PdfWriter()
        for index, page in enumerate(reader.pages, 1):
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            c.setFillGray(0.45)
            c.setFont("Helvetica", 8)
            c.drawCentredString(A4[0] / 2, 18, f"{index} / {total}")
            c.save()
            buf.seek(0)
            overlay = PdfReader(buf).pages[0]
            page.merge_page(overlay)
            writer.add_page(page)
        tmp = pdf.with_suffix(".numbered.pdf")
        with tmp.open("wb") as fh:
            writer.write(fh)
        tmp.replace(pdf)
        return True
    except Exception:
        return False


def build_html(markdown_text: str, base: Path, title: str) -> str:
    body = render_markdown(markdown_text, base)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def pdf_pages(pdf: Path):
    info = shutil.which("pdfinfo")
    if not info:
        return None
    try:
        out = subprocess.run([info, str(pdf)], check=True, capture_output=True,
                             text=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("report", help="Markdown audit report")
    ap.add_argument("--output", help="output PDF (default: report stem + .pdf)")
    ap.add_argument("--chrome", default="", help="Chrome/Chromium executable")
    ap.add_argument("--title", default="化学论文科研诚信审计报告")
    ap.add_argument("--keep-html", action="store_true",
                    help="keep the intermediate HTML next to the PDF")
    ap.add_argument("--timeout", type=int, default=120,
                    help="Chrome timeout in seconds (default: 120)")
    ap.add_argument("--no-page-numbers", action="store_true",
                    help="do not stamp N / M page numbers")
    args = ap.parse_args()

    report = Path(args.report).expanduser().resolve()
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        sys.stderr.write(f"cannot read report: {exc}\n")
        return 2
    if not text.strip():
        sys.stderr.write("report is empty\n")
        return 2

    output = Path(args.output).expanduser().resolve() if args.output \
        else report.with_suffix(".pdf")
    chrome = find_chrome(args.chrome)
    doc = build_html(text, report.parent, args.title)

    with tempfile.TemporaryDirectory(prefix="report-pdf-") as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(doc, encoding="utf-8")
        if args.keep_html:
            kept = output.with_suffix(".html")
            kept.write_text(doc, encoding="utf-8")
        cmd = [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=15000", f"--print-to-pdf={output}",
            html_path.as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=args.timeout)
        except subprocess.TimeoutExpired:
            sys.stderr.write("Chrome timed out while printing the PDF\n")
            return 1
        if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            err = (proc.stderr or proc.stdout or "").strip()
            sys.stderr.write(f"PDF render failed (exit {proc.returncode}): {err[-800:]}\n")
            return 1

    numbered = False
    if not args.no_page_numbers:
        numbered = stamp_page_numbers(output)

    result = {
        "report": str(report),
        "pdf": str(output),
        "pages": pdf_pages(output),
        "bytes": output.stat().st_size,
        "page_numbers": numbered,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
