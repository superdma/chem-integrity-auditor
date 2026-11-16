#!/usr/bin/env python3
"""Build illustrated evidence figures for an audit report.

For each finding, produce two PNGs:

* ``<id>_source.png`` — the source figure or PDF page with the problem
  region outlined in red;
* ``<id>_crop.png`` — the outlined region enlarged for reading.

The source can be a figure image (``--image``) or a PDF page
(``--pdf`` + ``--page``). For a PDF page, coordinates are normalized
(``--box-norm``) so the same numbers work at any render DPI. For an image,
coordinates are pixels (``--box``). Multiple boxes are allowed; the crop is
the union of all boxes plus padding.

Examples:
    report_figures.py --id D5-F2 --image figures_pmc/fig2.jpg \
        --box 60,90,380,395 --output-dir findings/image --run-dir . \
        --caption "Fig. 2 红/蓝 Raman trace 的共享噪声区"

    report_figures.py --id D5-F2 --pdf paper.pdf --page 7 \
        --box-norm 0.08,0.12,0.52,0.55 --output-dir findings/image \
        --run-dir . --caption "原文 PDF 第 7 页，红框为 Fig. 2 问题区域"

No LLM SDK. Pillow + poppler (only for PDF pages).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("install Pillow first: pip install Pillow", file=sys.stderr)
    sys.exit(2)


def parse_box(text: str):
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("box must be x0,y0,x1,y1")
    try:
        x0, y0, x1, y1 = (float(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("box values must be numbers")
    if x1 <= x0 or y1 <= y0:
        raise argparse.ArgumentTypeError("box must have x1>x0 and y1>y0")
    return x0, y0, x1, y1


def box_pixels(box, width, height, normalized):
    x0, y0, x1, y1 = box
    if normalized:
        x0, x1 = x0 * width, x1 * width
        y0, y1 = y0 * height, y1 * height
    x0 = max(0, min(width - 1, int(round(x0))))
    y0 = max(0, min(height - 1, int(round(y0))))
    x1 = max(x0 + 1, min(width, int(round(x1))))
    y1 = max(y0 + 1, min(height, int(round(y1))))
    return x0, y0, x1, y1


def render_pdf_page(pdf: Path, page: int, dpi: int) -> Image.Image:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise SystemExit("pdftoppm not found; install poppler-utils")
    with tempfile.TemporaryDirectory(prefix="report-fig-") as tmp:
        prefix = Path(tmp) / "page"
        cmd = [pdftoppm, "-f", str(page), "-l", str(page), "-r", str(dpi),
               "-singlefile", "-png", str(pdf), str(prefix)]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            msg = exc.stderr.decode("utf-8", "replace").strip()
            raise SystemExit(f"pdftoppm failed: {msg or exc}")
        path = prefix.with_suffix(".png")
        if not path.exists():
            raise SystemExit(f"pdftoppm produced no page image for page {page}")
        return Image.open(path).convert("RGB")


def union_box(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--id", required=True, help="short finding id")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--run-dir", default="",
                   help="run root; write report-relative paths in the manifest")
    p.add_argument("--image", help="source figure image")
    p.add_argument("--pdf", help="source PDF")
    p.add_argument("--page", type=int, help="PDF page number (1-based)")
    p.add_argument("--box", action="append", type=parse_box, default=[],
                   help="pixel box x0,y0,x1,y1; repeatable")
    p.add_argument("--box-norm", action="append", type=parse_box, default=[],
                   help="normalized box 0-1 x0,y0,x1,y1; repeatable")
    p.add_argument("--padding", type=int, default=16,
                   help="crop padding in source pixels (default: 16)")
    p.add_argument("--zoom", type=float, default=2.0,
                   help="crop enlargement factor (default: 2.0)")
    p.add_argument("--dpi", type=int, default=150,
                   help="PDF render DPI (default: 150)")
    p.add_argument("--caption", default="", help="caption stored in the manifest")
    p.add_argument("--md-out", help="optional Markdown snippet path")
    args = p.parse_args()

    if bool(args.image) == bool(args.pdf):
        p.error("use exactly one of --image or --pdf")
    if args.pdf and not args.page:
        p.error("--pdf requires --page")
    if args.image and args.box_norm:
        p.error("--box-norm is for PDF pages; use --box with --image")
    if args.pdf and args.box:
        p.error("--box is for images; use --box-norm with --pdf")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.image:
        source_path = Path(args.image)
        if not source_path.exists():
            raise SystemExit(f"image not found: {source_path}")
        img = Image.open(source_path).convert("RGB")
        source_kind = "figure"
        page = None
        boxes_raw = args.box
        normalized = False
    else:
        source_path = Path(args.pdf)
        if not source_path.exists():
            raise SystemExit(f"PDF not found: {source_path}")
        img = render_pdf_page(source_path, args.page, args.dpi)
        source_kind = "pdf_page"
        page = args.page
        boxes_raw = args.box_norm
        normalized = True

    width, height = img.size
    if not boxes_raw:
        boxes_raw = [(0.0, 0.0, float(width), float(height))]
        normalized = False
    boxes = [box_pixels(b, width, height, normalized) for b in boxes_raw]
    union = union_box(boxes)

    # Annotated source: red rectangles, no text (captions stay in Markdown).
    # A white underlay keeps the box visible when it crosses a red curve.
    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)
    stroke = max(3, min(8, int(round(min(width, height) * 0.002))))
    for b in boxes:
        draw.rectangle(b, outline=(255, 255, 255), width=stroke + 4)
        draw.rectangle(b, outline=(210, 30, 30), width=stroke)

    source_out = output_dir / f"{args.id}_source.png"
    annotated.save(source_out)

    # Enlarged crop of the union, with padding and a white border.
    x0, y0, x1, y1 = union
    x0 = max(0, x0 - args.padding)
    y0 = max(0, y0 - args.padding)
    x1 = min(width, x1 + args.padding)
    y1 = min(height, y1 + args.padding)
    crop = img.crop((x0, y0, x1, y1))
    if args.zoom and args.zoom != 1.0:
        new_size = (max(1, int(crop.width * args.zoom)),
                    max(1, int(crop.height * args.zoom)))
        # Keep the long side readable without producing huge files.
        long_side = max(new_size)
        if long_side > 2400:
            scale = 2400.0 / long_side
            new_size = (max(1, int(new_size[0] * scale)),
                        max(1, int(new_size[1] * scale)))
        crop = crop.resize(new_size, Image.LANCZOS)
    crop_out = output_dir / f"{args.id}_crop.png"
    crop.save(crop_out)

    def report_path(path: Path) -> str:
        if args.run_dir:
            return os.path.relpath(path.resolve(), Path(args.run_dir).resolve())
        return str(path)

    manifest = {
        "id": args.id,
        "source_kind": source_kind,
        "source": str(source_path),
        "page": page,
        "dpi": args.dpi if args.pdf else None,
        "boxes": boxes,
        "crop": [x0, y0, x1, y1],
        "source_image": report_path(source_out),
        "crop_image": report_path(crop_out),
        "caption": args.caption,
    }
    (output_dir / f"{args.id}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.md_out:
        page_text = f"PDF 第 {page} 页" if page else "原文图件"
        source_rel = report_path(source_out)
        crop_rel = report_path(crop_out)
        lines = [
            f"![{args.id} 原页]({source_rel})",
            f"*{page_text}；红框为问题区域。{args.caption}*",
            "",
            f"![{args.id} 局部放大]({crop_rel})",
            f"*红框区域 {args.zoom:g}× 放大。*",
            "",
        ]
        Path(args.md_out).write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"id": args.id, "source": str(source_out),
                      "crop": str(crop_out), "page": page},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
