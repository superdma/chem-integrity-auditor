#!/usr/bin/env python3
"""Extract a born-digital PDF without MinerU.

This is the native backend for the PDF/DOI route. It uses ``pdfplumber`` for
text and ruled tables, and ``pypdfium2`` only when figure crops are requested.
The output is deliberately the same contract the rest of the pipeline already
uses:

* ``full.md`` — page text plus HTML ``<table>`` blocks and figure captions.
* ``tables.json`` — page, bbox, caption and cell matrix for every table.
* ``figures.json`` — page, bbox, caption and crop path for every raster image.
* ``native_manifest.json`` — backend, versions, page/table/figure counts and
  warnings.

It does not OCR scanned pages and does not digitize chart pixels. When the PDF
is image-only or its tables are not ruled, the caller should fall back to
MinerU instead of treating an empty extraction as a clean paper.

Usage:
    python3 scripts/pdf_native_extract.py paper.pdf --output workdir
    python3 scripts/pdf_native_extract.py paper.pdf --output workdir --no-figures
    python3 scripts/pdf_native_extract.py paper.pdf --output workdir --dpi 300
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

FIGURE_RE = re.compile(r"\b(?:fig(?:ure)?\.?|图)\s*([0-9A-Za-z][0-9A-Za-z_.-]*)", re.I)
TABLE_RE = re.compile(r"\b(?:table|表)\s*([0-9A-Za-z][0-9A-Za-z_.-]*)", re.I)


def _import_pdfplumber():
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - message path
        raise RuntimeError(
            "pdfplumber is required for the native PDF backend: "
            "python3 -m pip install 'pdfplumber>=0.11,<0.11.5'"
        ) from exc
    return pdfplumber


def _clean_cell(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _table_html(rows, table_id: str) -> str:
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(_clean_cell(c))}</td>" for c in row)
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<table id="{html.escape(table_id)}">'
        f"<thead><tr><th colspan=\"{max((len(r) for r in rows), default=1)}\">"
        f"{html.escape(table_id)}</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _caption_near(lines, y: float, pattern, max_distance: float = 140.0):
    """Return the closest caption line above/below a bbox top coordinate."""
    best = None
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text or not pattern.search(text):
            continue
        distance = abs(float(line.get("top", 0)) - y)
        if distance <= max_distance and (best is None or distance < best[0]):
            best = (distance, text)
    return best[1] if best else ""


def _page_lines(page):
    """Word boxes grouped into visually ordered lines (top, then x0)."""
    words = page.extract_words(x_tolerance=1, y_tolerance=3,
                               keep_blank_chars=False) or []
    lines = {}
    for word in words:
        key = round(float(word.get("top", 0)) / 3.0)
        lines.setdefault(key, []).append(word)
    out = []
    for key in sorted(lines):
        group = sorted(lines[key], key=lambda w: float(w.get("x0", 0)))
        text = " ".join(str(w.get("text", "")) for w in group).strip()
        if not text:
            continue
        out.append({
            "top": min(float(w.get("top", 0)) for w in group),
            "x0": min(float(w.get("x0", 0)) for w in group),
            "text": text,
        })
    return out


def _find_tables(page, strategy: str):
    """Return table objects, trying ruled lines first unless told otherwise."""
    if strategy == "text":
        return page.find_tables(table_settings={
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
        })
    return page.find_tables()


def _crop_page(pdf_path: Path, page_index: int, bbox, dpi: int, target: Path):
    """Render one page with pypdfium2 and crop a PDF-point bbox to PNG."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError(
            "pypdfium2 is required for figure crops: "
            "python3 -m pip install pypdfium2"
        ) from exc
    from PIL import Image

    # Passing a file object avoids pypdfium2's Windows non-ASCII path issues.
    handle = open(pdf_path, "rb")
    doc = pdfium.PdfDocument(handle)
    try:
        page = doc[page_index]
        scale = dpi / 72.0
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
        finally:
            bitmap.close()
            page.close()
        x0, top, x1, bottom = bbox
        left = max(0, int(round(float(x0) * scale)))
        upper = max(0, int(round(float(top) * scale)))
        right = min(image.width, int(round(float(x1) * scale)))
        lower = min(image.height, int(round(float(bottom) * scale)))
        if right <= left or lower <= upper:
            raise ValueError(f"empty crop box: {bbox}")
        target.parent.mkdir(parents=True, exist_ok=True)
        crop = image.crop((left, upper, right, lower))
        try:
            crop.save(target, format="PNG")
        finally:
            crop.close()
            image.close()
        return {"width": right - left, "height": lower - upper,
                "pixel_box": [left, upper, right, lower]}
    finally:
        doc.close()
        handle.close()


def extract(pdf_path: Path, output_dir: Path, *, dpi: int = 200,
            figures: bool = True, table_strategy: str = "lines") -> dict:
    pdfplumber = _import_pdfplumber()
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    md_parts = [f"# {pdf_path.stem}", ""]
    tables = []
    figure_items = []
    warnings = []
    pages_meta = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_no = page_index + 1
            lines = _page_lines(page)
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            pages_meta.append({
                "page": page_no,
                "width": round(float(page.width), 2),
                "height": round(float(page.height), 2),
                "chars": len(page.chars),
                "images": len(page.images),
            })
            md_parts.append(f"## Page {page_no}")
            md_parts.append("")
            if text.strip():
                md_parts.append(text.strip())
                md_parts.append("")

            page_tables = _find_tables(page, table_strategy)
            for table_index, table in enumerate(page_tables, start=1):
                table_id = f"p{page_no}_t{table_index}"
                try:
                    rows = table.extract() or []
                except Exception as exc:  # pragma: no cover - pdfplumber edge
                    warnings.append(f"{table_id}: table extraction failed: {exc}")
                    continue
                rows = [[_clean_cell(c) for c in row] for row in rows]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                caption = _caption_near(lines, float(table.bbox[1]), TABLE_RE)
                item = {
                    "id": table_id,
                    "page": page_no,
                    "bbox": [round(float(v), 2) for v in table.bbox],
                    "caption": caption,
                    "rows": rows,
                }
                tables.append(item)
                if caption:
                    md_parts.append(f"**{caption}**")
                    md_parts.append("")
                md_parts.append(_table_html(rows, table_id))
                md_parts.append("")

            if figures:
                seen_boxes = set()
                for fig_index, image in enumerate(page.images, start=1):
                    bbox = [float(image.get(k, 0)) for k in ("x0", "top", "x1", "bottom")]
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    if width < 40 or height < 40:
                        continue
                    if (bbox[0] < -1 or bbox[1] < -1
                            or bbox[2] > float(page.width) + 1
                            or bbox[3] > float(page.height) + 1):
                        warnings.append(
                            f"page {page_no}: skipped off-page image bbox {bbox}")
                        continue
                    box_key = tuple(round(v) for v in bbox)
                    if box_key in seen_boxes:
                        continue
                    seen_boxes.add(box_key)
                    figure_id = f"p{page_no}_f{fig_index}"
                    crop_name = f"{figure_id}.png"
                    caption = _caption_near(lines, bbox[1], FIGURE_RE)
                    try:
                        meta = _crop_page(pdf_path, page_index, bbox, dpi,
                                          figures_dir / crop_name)
                    except Exception as exc:  # pragma: no cover - renderer edge
                        warnings.append(f"{figure_id}: crop failed: {exc}")
                        continue
                    item = {
                        "id": figure_id,
                        "page": page_no,
                        "bbox": [round(v, 2) for v in bbox],
                        "caption": caption,
                        "crop": str((figures_dir / crop_name).relative_to(output_dir)),
                        **meta,
                    }
                    figure_items.append(item)
                    md_parts.append(f"![{figure_id}]({item['crop']})")
                    if caption:
                        md_parts.append(f"*{caption}*")
                    md_parts.append("")

    # A born-digital PDF normally has extractable text. An image-only PDF
    # yields zero characters; say so instead of writing a misleading clean
    # full.md.
    total_chars = sum(p["chars"] for p in pages_meta)
    if total_chars == 0:
        warnings.append("no extractable text: this PDF is probably scanned; "
                        "use MinerU or an OCR pipeline")

    full_md = "\n".join(md_parts).strip() + "\n"
    (output_dir / "full.md").write_text(full_md, encoding="utf-8")
    (output_dir / "tables.json").write_text(
        json.dumps({"tool": "native-pdf", "pages": pages_meta,
                    "tables": tables}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (output_dir / "figures.json").write_text(
        json.dumps({"tool": "native-pdf", "figures": figure_items},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    manifest = {
        "backend": "native-pdf",
        "input": str(pdf_path),
        "output_dir": str(output_dir),
        "pages": len(pages_meta),
        "text_chars": total_chars,
        "tables": len(tables),
        "figures": len(figure_items),
        "dpi": dpi,
        "table_strategy": table_strategy,
        "full_md": str(output_dir / "full.md"),
        "full_md_bytes": (output_dir / "full.md").stat().st_size,
        "warnings": warnings,
    }
    (output_dir / "native_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text, ruled tables and raster figure crops from a "
                    "born-digital PDF without MinerU.")
    parser.add_argument("pdf", help="input PDF path")
    parser.add_argument("--output", required=True, help="work directory")
    parser.add_argument("--dpi", type=int, default=200,
                        help="page render DPI for figure crops (default 200)")
    parser.add_argument("--no-figures", action="store_true",
                        help="skip page rendering and figure crops")
    parser.add_argument("--table-strategy", default="lines",
                        choices=["lines", "text"],
                        help="pdfplumber table strategy (default lines; falls "
                             "back to text when no ruled table is found)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    try:
        manifest = extract(
            pdf_path,
            Path(args.output).expanduser().resolve(),
            dpi=max(72, args.dpi),
            figures=not args.no_figures,
            table_strategy=args.table_strategy,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"native extraction failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
