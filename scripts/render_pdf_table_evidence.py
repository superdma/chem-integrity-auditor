#!/usr/bin/env python3
"""Render a PDF table as an evidence card with highlighted rows and columns.

This is the PDF counterpart of ``render_evidence_tables.py`` (which reads
XLSX). It uses ``pdfplumber`` to extract a table and redraws the selected
window with the problem rows/columns highlighted, so the report carries a
readable cell-level evidence image without MinerU or a page screenshot.

Row/column numbers are 1-based and refer to the extracted table matrix,
including its header row. Example:

    python3 scripts/render_pdf_table_evidence.py paper.pdf \
      --page 7 --table 1 --rows 2-5 --cols 3,5 \
      --id TAB7-C --output-dir findings/image --run-dir output/run \
      --caption "PDF 第 7 页 Table 1；第 2–5 行、第 3/5 列高亮"

Writes ``<id>_table.png`` and ``<id>_manifest.json``. Exit 0 on success.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from render_evidence_tables import (FONT, PALETTE, draw_wrapped,
                                        load_font, text_size)
except ImportError:  # pragma: no cover - when imported as a package
    from .render_evidence_tables import (FONT, PALETTE, draw_wrapped,
                                         load_font, text_size)


def parse_indices(text: str):
    out = set()
    for part in re.split(r"[,，;；\s]+", text or ""):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"bad row/column selector: {part}")
        start = int(m.group(1))
        end = int(m.group(2) or start)
        if start < 1 or end < start:
            raise ValueError(f"bad row/column range: {part}")
        out.update(range(start, end + 1))
    return out


def _import_pdfplumber():
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pdfplumber is required: python3 -m pip install "
            "'pdfplumber>=0.11,<0.11.5'") from exc
    return pdfplumber


def _clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _table_at(pdf, page_no: int, table_no: int):
    page = pdf.pages[page_no - 1]
    tables = page.find_tables()
    if not tables:
        # Borderless tables are common in supplementary PDFs; let the caller
        # opt into text strategy through an environment-free second attempt.
        tables = page.find_tables(table_settings={
            "vertical_strategy": "text", "horizontal_strategy": "text"})
    if not tables:
        raise SystemExit(f"no table found on page {page_no}")
    if table_no < 1 or table_no > len(tables):
        raise SystemExit(
            f"page {page_no} has {len(tables)} table(s); --table {table_no} "
            "is out of range")
    table = tables[table_no - 1]
    rows = [[_clean(c) for c in row] for row in (table.extract() or [])]
    rows = [row for row in rows if any(row)]
    if not rows:
        raise SystemExit("extracted table is empty")
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return rows, table


def _wrapped_lines(draw, text, font, max_width):
    """Greedy wrap by measured width; keeps long numbers intact when possible."""
    words = str(text).split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        trial = current + " " + word
        if text_size(draw, trial, font)[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_table(rows, highlights, output: Path, *, title: str,
                 caption: str = "", context: int = 1, max_rows: int = 40,
                 max_cols: int = 12):
    n_rows = len(rows)
    n_cols = max(len(r) for r in rows)
    hi_rows = {r for r in highlights["rows"] if 1 <= r <= n_rows}
    hi_cols = {c for c in highlights["cols"] if 1 <= c <= n_cols}

    if hi_rows:
        first = max(1, min(hi_rows) - context)
        last = min(n_rows, max(hi_rows) + context)
    else:
        first, last = 1, min(n_rows, max_rows)
    if last - first + 1 > max_rows:
        last = first + max_rows - 1
    if hi_cols:
        c_first = max(1, min(hi_cols) - context)
        c_last = min(n_cols, max(hi_cols) + context)
    else:
        c_first, c_last = 1, min(n_cols, max_cols)
    if c_last - c_first + 1 > max_cols:
        c_last = c_first + max_cols - 1

    body = [[rows[r - 1][c - 1] for c in range(c_first, c_last + 1)]
            for r in range(first, last + 1)]
    header = [f"row {r}" for r in range(first, last + 1)]
    col_labels = [f"col {c}" for c in range(c_first, c_last + 1)]

    # Estimate widths from wrapped content, with a floor for readability.
    probe = Image.new("RGB", (10, 10), "white")
    pdraw = ImageDraw.Draw(probe)
    widths = []
    for ci in range(len(col_labels)):
        widest = text_size(pdraw, col_labels[ci], FONT["small"])[0]
        for row in body:
            for line in _wrapped_lines(pdraw, row[ci], FONT["small"], 260):
                widest = max(widest, text_size(pdraw, line, FONT["small"])[0])
        widths.append(max(48, min(190, widest + 18)))
    row_head_w = 48
    cell_h_min = 30
    margin = 34
    title_h = 92
    caption_h = 52 if caption else 18
    table_w = row_head_w + sum(widths)
    img_w = max(720, table_w + margin * 2)
    # Compute row heights from wrapped lines.
    row_heights = []
    for row in body:
        h = cell_h_min
        for ci, value in enumerate(row):
            lines = _wrapped_lines(pdraw, value, FONT["small"], widths[ci] - 12)
            h = max(h, 10 + len(lines) * 17)
        row_heights.append(h)
    img_h = title_h + 26 + sum(row_heights) + caption_h + margin

    img = Image.new("RGB", (img_w, img_h), PALETTE["bg"])
    draw = ImageDraw.Draw(img)
    draw.text((margin, 26), title, font=FONT["title"], fill=PALETTE["text"])
    subtitle = (f"rows {first}-{last} / {n_rows} · cols {c_first}-{c_last} / "
                f"{n_cols} · yellow = highlighted")
    draw.text((margin, 62), subtitle, font=FONT["small"], fill=PALETTE["muted"])

    x0 = margin
    y = title_h + 18
    # Column headers.
    x = x0 + row_head_w
    for ci, label in enumerate(col_labels):
        col = c_first + ci
        fill = "#fff7cc" if col in hi_cols else PALETTE["header"]
        draw.rectangle([x, y, x + widths[ci], y + 26], fill=fill,
                       outline=PALETTE["grid"])
        draw.text((x + 5, y + 5), label, font=FONT["small"],
                  fill=PALETTE["muted"])
        x += widths[ci]
    draw.rectangle([x0, y, x0 + row_head_w, y + 26], fill=PALETTE["header"],
                   outline=PALETTE["grid"])
    draw.text((x0 + 4, y + 5), "row", font=FONT["small"],
              fill=PALETTE["muted"])
    y += 26

    for ri, row in enumerate(body):
        row_no = first + ri
        h = row_heights[ri]
        x = x0
        row_fill = "#fff7cc" if row_no in hi_rows else PALETTE["paper"]
        draw.rectangle([x, y, x + row_head_w, y + h], fill=row_fill,
                       outline=PALETTE["grid"])
        draw.text((x + 4, y + 6), str(row_no), font=FONT["small"],
                  fill=PALETTE["muted"])
        x += row_head_w
        for ci, value in enumerate(row):
            col = c_first + ci
            hi = row_no in hi_rows or col in hi_cols
            fill = "#fef3c7" if hi else PALETTE["paper"]
            outline = PALETTE["danger"] if (row_no in hi_rows and
                                             col in hi_cols) else PALETTE["grid"]
            draw.rectangle([x, y, x + widths[ci], y + h], fill=fill,
                           outline=outline,
                           width=2 if outline == PALETTE["danger"] else 1)
            lines = _wrapped_lines(pdraw, value, FONT["small"], widths[ci] - 12)
            ty = y + 6
            for line in lines[:4]:
                draw.text((x + 5, ty), line, font=FONT["small"],
                          fill=PALETTE["text"])
                ty += 17
            x += widths[ci]
        y += h

    if caption:
        draw_wrapped(draw, caption, (margin, y + 12), img_w - margin * 2,
                     FONT["small"], PALETTE["muted"])
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, format="PNG")
    return {"rows": [first, last], "cols": [c_first, c_last],
            "highlight_rows": sorted(hi_rows), "highlight_cols": sorted(hi_cols),
            "image": str(output)}


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("pdf", help="source PDF")
    ap.add_argument("--page", type=int, required=True, help="1-based page")
    ap.add_argument("--table", type=int, default=1, help="1-based table on page")
    ap.add_argument("--rows", default="", help="1-based rows, e.g. 2-5,7")
    ap.add_argument("--cols", default="", help="1-based columns, e.g. 3,5")
    ap.add_argument("--context", type=int, default=1,
                    help="context rows/columns around highlights (default 1)")
    ap.add_argument("--id", default="PDF-TABLE", help="evidence id")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--run-dir", default="")
    ap.add_argument("--caption", default="")
    ap.add_argument("--md-out", action="store_true",
                    help="print a Markdown evidence block")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    try:
        row_sel = parse_indices(args.rows)
        col_sel = parse_indices(args.cols)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pdfplumber = _import_pdfplumber()
    with pdfplumber.open(str(pdf_path)) as pdf:
        if args.page < 1 or args.page > len(pdf.pages):
            print(f"--page out of range: 1..{len(pdf.pages)}", file=sys.stderr)
            return 2
        rows, table = _table_at(pdf, args.page, args.table)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output = output_dir / f"{args.id}_table.png"
    title = f"PDF table evidence · p{args.page}_t{args.table}"
    caption = args.caption or (
        f"PDF 第 {args.page} 页 / Table p{args.page}_t{args.table}；"
        "黄色为高亮行/列。")
    meta = render_table(rows, {"rows": row_sel, "cols": col_sel}, output,
                        title=title, caption=caption, context=max(0, args.context))
    manifest = {
        "id": args.id,
        "pdf": str(pdf_path),
        "page": args.page,
        "table": args.table,
        "bbox": [round(float(v), 2) for v in table.bbox],
        "rows_total": len(rows),
        "cols_total": max(len(r) for r in rows),
        **meta,
        "caption": caption,
    }
    (output_dir / f"{args.id}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    if args.md_out:
        print(f"\n![{args.id} 证据表]({output.name})\n*{caption}*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
