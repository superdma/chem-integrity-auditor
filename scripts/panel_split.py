"""panel_split.py — split a multi-panel figure image into individual panels.

Real journal figures are not white boxes separated by 18 px of pure white.
Microscopy panels touch, JPEG paper is off-white, and a plot has dozens of
internally-white columns. The first version of this script used a single
"98 % white for >= 18 px" rule and returned one panel for most real figures,
which silently disabled panel-level image forensics.

This version combines two detectors:

1. **Plot-frame detector** (for line plots): long horizontal rules are found
   from dark-pixel runs, clustered, and paired into row bands. This is what
   keeps a white gap *inside* a spectrum from being mistaken for a panel
   boundary.
2. **Gutter detector** (for photos/microscopy and frameless figures): row and
   column projections are classified as separator lines by three cues —
   almost no ink, almost pure white, or almost perfectly flat. Candidate runs
   must leave at least `--min-panel-frac` of the axis on each side, which
   suppresses runs inside a single chart.

The result is a row-band × column-band grid, which is the layout of virtually
all chemistry figures (1×N, 2×2, 2×3, 3×2, with one full-width bottom panel).

Usage:
    python panel_split.py <figure.png> <out_dir> [options]

Output:
    <out_dir>/<stem>_panel_<NNN>_y<y0>-<y1>_x<x0>-<x1>.png

Useful audit options:
    --json report.json     bboxes + separator evidence
    --debug debug.png      draw accepted separators and panel boxes
    --trim                 trim uniform outer margin from each panel
    --min-gutter-px 2      allow very tight journal gutters
    --min-panel-frac 0.10  reject blocks smaller than 10 % of the axis

If the tool still returns one panel, the image is likely a seamless montage;
it prints a warning instead of pretending the split succeeded.

Stdlib + Pillow + NumPy. OpenCV is not required. No LLM SDK. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.stderr.write("install Pillow first: pip install Pillow\n")
    sys.exit(2)
try:
    import numpy as np
except ImportError:
    sys.stderr.write("install numpy first: pip install numpy\n")
    sys.exit(2)


def _runs(mask, min_len: int):
    """Contiguous True runs at least min_len long."""
    out = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if j - i >= min_len:
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _merge_runs(runs, gap: int):
    """Merge runs separated by <= gap pixels (a gutter split by one label)."""
    if not runs:
        return []
    merged = [list(runs[0])]
    for s, e in runs[1:]:
        if s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(int(s), int(e)) for s, e in merged]


def _profiles(gray: np.ndarray, axis: int, dark_thresh: int, white_thresh: int):
    """Projection profiles along `axis`.

    axis=0 → one value per row (project across columns).
    axis=1 → one value per column (project across rows).
    """
    perp = 1 - axis
    ink = (gray < dark_thresh).mean(axis=perp)
    white = (gray >= white_thresh).mean(axis=perp)
    med = np.median(gray, axis=perp, keepdims=True)
    flat = (np.abs(gray - med) <= 12).mean(axis=perp)
    return ink, white, flat


def _gutter_blocks(
    gray: np.ndarray,
    axis: int,
    *,
    dark_thresh: int,
    white_thresh: int,
    ink_thresh: float,
    white_frac: float,
    flat_frac: float,
    min_gutter_px: int,
    max_gutter_px: int,
    min_panel_px: int,
    min_panel_frac: float,
):
    """Return (blocks, accepted_separators) from gutter cues on one axis."""
    n = gray.shape[axis]
    min_panel = max(min_panel_px, int(round(min_panel_frac * n)))
    ink, white, flat = _profiles(gray, axis, dark_thresh, white_thresh)
    mask = (ink <= ink_thresh) | (white >= white_frac) | (flat >= flat_frac)
    runs = [
        (s, e)
        for s, e in _runs(mask, min_gutter_px)
        if (e - s) <= max_gutter_px
    ]
    runs = _merge_runs(runs, gap=3)

    accepted = []
    last = 0
    for s, e in runs:
        # Both sides of a real panel boundary must be big enough. This single
        # rule rejects outer margins (left side 0) and white gaps inside one
        # chart (the block before the gap is shorter than min_panel).
        if s >= min_panel and (n - e) >= min_panel and (s - last) >= min_panel:
            accepted.append((s, e))
            last = e

    if not accepted:
        return [(0, n)], []

    blocks = []
    last = 0
    for s, e in accepted:
        blocks.append((last, s))
        last = e
    if n - last >= min_panel:
        blocks.append((last, n))
    else:
        blocks[-1] = (blocks[-1][0], n)
    return (blocks if len(blocks) > 1 else [(0, n)]), accepted


def _longest_dark_run(values: np.ndarray, max_gap: int = 3) -> int:
    """Longest run of True allowing short gaps (anti-aliased frame lines)."""
    idx = np.where(values)[0]
    if len(idx) == 0:
        return 0
    splits = np.where(np.diff(idx) > max_gap)[0]
    segs = np.split(idx, splits + 1)
    return int(max(len(seg) for seg in segs))


def _frame_lines(gray: np.ndarray, axis: int, *, dark_thresh: int,
                 min_len_frac: float, cluster_px: int = 10):
    """Positions of long dark rules along `axis` (axis=0 → horizontal rules)."""
    n = gray.shape[1 - axis]
    hits = []
    for i in range(gray.shape[axis]):
        values = (gray[i, :] if axis == 0 else gray[:, i]) < dark_thresh
        if values.sum() < 0.15 * n:
            continue
        run = _longest_dark_run(values)
        if run >= min_len_frac * n:
            hits.append((i, run))
    clusters = []
    for pos, run in hits:
        if clusters and pos - clusters[-1][-1][0] <= cluster_px:
            clusters[-1].append((pos, run))
        else:
            clusters.append([(pos, run)])
    return [
        {
            "pos": int(round(float(np.mean([p for p, _ in cluster])))),
            "run": int(max(r for _, r in cluster)),
            "run_frac": float(max(r for _, r in cluster) / n),
        }
        for cluster in clusters
    ]


def _frame_row_bands(gray: np.ndarray, *, dark_thresh: int,
                     min_len_frac: float, min_panel_px: int,
                     min_panel_frac: float, frame_dark_thresh: int = 160):
    """Pair horizontal frame rules into row bands.

    Returns [{"y0", "y1", "full_width"}] or [] when the image is not a plot.
    A band whose top rule spans >= 60 % of the image is a single full-width
    panel (e.g. a bottom GCD/cycling panel) and must not be column-split.
    """
    # A photograph (SEM/TEM) has a high dark ratio and no meaningful frames.
    if float((gray < dark_thresh).mean()) >= 0.45:
        return []
    lines = _frame_lines(gray, 0, dark_thresh=frame_dark_thresh,
                         min_len_frac=min_len_frac)
    lines = [line for line in lines if line["run_frac"] >= min_len_frac]
    if len(lines) < 2 or len(lines) % 2 != 0:
        return []
    min_panel = max(min_panel_px, int(round(min_panel_frac * gray.shape[0])))
    bands = []
    for i in range(0, len(lines) - 1, 2):
        top, bottom = lines[i], lines[i + 1]
        if bottom["pos"] - top["pos"] >= min_panel:
            bands.append({
                "y0": top["pos"],
                "y1": bottom["pos"],
                "full_width": max(top["run_frac"], bottom["run_frac"]) >= 0.60,
            })
    return bands


def _frame_col_blocks(strip: np.ndarray, *, frame_dark_thresh: int,
                      min_panel_px: int, min_panel_frac: float):
    """Use vertical frame rules to split one row band into panels.

    Vertical rules are clustered, then an even subset is paired consecutively
    to maximise total panel width. This drops internal full-height gridlines:
    for lines [56, 95, 360, 435, 734] the best pairing is (56,360),(435,734),
    not (56,95),(360,435).
    """
    lines = _frame_lines(strip, 1, dark_thresh=frame_dark_thresh,
                         min_len_frac=0.50)
    positions = sorted({line["pos"] for line in lines})
    if len(positions) < 2:
        return [], []
    n = strip.shape[1]
    min_panel = max(min_panel_px, int(round(min_panel_frac * n)))

    best = None
    for mask in range(1, 1 << len(positions)):
        chosen = [positions[i] for i in range(len(positions)) if mask & (1 << i)]
        if len(chosen) < 2 or len(chosen) % 2 != 0:
            continue
        pairs = [(chosen[i], chosen[i + 1]) for i in range(0, len(chosen), 2)]
        if any(b - a < min_panel for a, b in pairs):
            continue
        if any(pairs[i + 1][0] - pairs[i][1] < 3 for i in range(len(pairs) - 1)):
            continue
        width = sum(b - a for a, b in pairs)
        # Prefer wide panels, more than one panel, and few leftovers.
        score = width + min_panel * (len(pairs) - 1) - 0.25 * (n - (pairs[-1][1] - pairs[0][0]))
        if best is None or score > best[0]:
            best = (score, pairs)
    if best is None:
        return [], []
    return list(best[1]), []


def split_figure(
    arr: np.ndarray,
    *,
    dark_thresh: int = 100,
    white_thresh: int = 245,
    ink_thresh: float = 0.005,
    white_frac: float = 0.995,
    flat_frac: float = 0.999,
    min_gutter_px: int = 2,
    max_gutter_px: int = 200,
    min_panel_px: int = 60,
    min_panel_frac: float = 0.15,
    col_min_panel_frac: float = 0.28,
    frame_min_len_frac: float = 0.35,
    frame_dark_thresh: int = 160,
):
    """Return (bboxes, evidence)."""
    out: list[tuple[int, int, int, int]] = []
    evidence: list[dict] = []

    # Prefer frame-derived row bands for plots; fall back to gutters.
    frame_bands = _frame_row_bands(
        arr, dark_thresh=dark_thresh, min_len_frac=frame_min_len_frac,
        min_panel_px=min_panel_px, min_panel_frac=min_panel_frac,
        frame_dark_thresh=frame_dark_thresh,
    )
    if frame_bands:
        row_bands = [(band["y0"], band["y1"], band["full_width"])
                     for band in frame_bands]
        row_source = "frame"
    else:
        gutter_bands, row_seps = _gutter_blocks(
            arr, 0,
            dark_thresh=dark_thresh, white_thresh=white_thresh,
            ink_thresh=ink_thresh, white_frac=white_frac, flat_frac=flat_frac,
            min_gutter_px=min_gutter_px, max_gutter_px=max_gutter_px,
            min_panel_px=min_panel_px, min_panel_frac=min_panel_frac,
        )
        row_bands = [(y0, y1, False) for y0, y1 in gutter_bands]
        row_source = "gutter"
        for s, e in row_seps:
            evidence.append({"axis": "row", "start": s, "end": e,
                             "offset": 0, "source": "gutter"})

    for y0, y1, full_width in row_bands:
        strip = arr[y0:y1, :]
        if full_width:
            col_blocks, col_seps = [(0, strip.shape[1])], []
        elif row_source == "frame":
            col_blocks, col_seps = _frame_col_blocks(
                strip, frame_dark_thresh=frame_dark_thresh,
                min_panel_px=min_panel_px, min_panel_frac=col_min_panel_frac,
            )
        else:
            col_blocks, col_seps = [(0, strip.shape[1])], []
        if not full_width and len(col_blocks) <= 1:
            col_blocks, col_seps = _gutter_blocks(
                    strip, 1,
                    dark_thresh=dark_thresh, white_thresh=white_thresh,
                    ink_thresh=ink_thresh, white_frac=white_frac, flat_frac=flat_frac,
                    min_gutter_px=min_gutter_px, max_gutter_px=max_gutter_px,
                    min_panel_px=min_panel_px,
                    min_panel_frac=col_min_panel_frac,
                )
        for s, e in col_seps:
            evidence.append({"axis": "col", "start": s, "end": e,
                             "offset": int(y0), "source": "gutter"})
        for x0, x1 in col_blocks:
            out.append((int(y0), int(y1), int(x0), int(x1)))
        if row_source == "frame":
            evidence.append({"axis": "row", "start": int(y0), "end": int(y1),
                             "offset": 0, "source": "frame"})

    uniq = list(dict.fromkeys(out))
    uniq.sort(key=lambda b: (b[0], b[2], b[1], b[3]))
    return uniq, evidence


def _trim_panel(img: Image.Image, tolerance: int = 2) -> Image.Image:
    """Trim a uniform outer margin (usually the white gutter remainder)."""
    arr = np.asarray(img.convert("L"))
    if arr.size == 0:
        return img
    border = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]])
    bg = int(np.median(border))
    mask = np.abs(arr.astype(np.int16) - bg) > tolerance
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    box = (int(cols.min()), int(rows.min()),
           int(cols.max()) + 1, int(rows.max()) + 1)
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return img
    return img.crop(box)


def _draw_debug(arr: np.ndarray, bboxes, evidence, out_path: Path) -> None:
    img = Image.fromarray(arr).convert("RGB")
    draw = ImageDraw.Draw(img)
    for b in bboxes:
        draw.rectangle([b[2], b[0], b[3] - 1, b[1] - 1],
                       outline=(0, 160, 0), width=2)
    for ev in evidence:
        if ev["axis"] == "row" and ev.get("source") == "gutter":
            y0, y1 = ev["offset"] + ev["start"], ev["offset"] + ev["end"]
            draw.line([(0, y0), (img.width - 1, y0)], fill=(220, 0, 0), width=1)
            draw.line([(0, y1), (img.width - 1, y1)], fill=(220, 0, 0), width=1)
        elif ev["axis"] == "col":
            x0, x1 = ev["offset"] + ev["start"], ev["offset"] + ev["end"]
            draw.line([(x0, 0), (x0, img.height - 1)], fill=(220, 0, 0), width=1)
            draw.line([(x1, 0), (x1, img.height - 1)], fill=(220, 0, 0), width=1)
    img.save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("input", help="figure image (PNG / JPG)")
    parser.add_argument("out_dir", help="output directory for panel PNGs")
    parser.add_argument("--dark-thresh", type=int, default=100,
                        help="pixels below this are ink (default 100)")
    parser.add_argument("--white-thresh", type=int, default=245,
                        help="pixels at/above this are white (default 245)")
    parser.add_argument("--ink-thresh", type=float, default=0.005,
                        help="max ink fraction on a separator line (default 0.01)")
    parser.add_argument("--white-frac", type=float, default=0.995,
                        help="min white fraction on a separator line")
    parser.add_argument("--flat-frac", type=float, default=0.999,
                        help="min fraction within 12 gray levels of line median")
    parser.add_argument("--min-gutter-px", type=int, default=2,
                        help="minimum separator width (default 3 px)")
    parser.add_argument("--max-gutter-px", type=int, default=200,
                        help="ignore separator runs wider than this")
    parser.add_argument("--min-panel-px", type=int, default=60,
                        help="absolute minimum panel width/height (default 60 px)")
    parser.add_argument("--min-panel-frac", type=float, default=0.10,
                        help="minimum row-band size as a fraction of height")
    parser.add_argument("--col-min-panel-frac", type=float, default=0.28,
                        help="minimum column-block width as a fraction of width")
    parser.add_argument("--frame-min-len-frac", type=float, default=0.35,
                        help="min length of a plot-frame rule as a fraction of width")
    parser.add_argument("--max-depth", type=int, default=2,
                        help="accepted for compatibility; grid split is two-level")
    parser.add_argument("--trim", action="store_true",
                        help="trim uniform outer margin from each panel")
    parser.add_argument("--json", metavar="PATH",
                        help="write bboxes and separator evidence as JSON")
    parser.add_argument("--debug", metavar="PATH",
                        help="write an annotated PNG with separators and boxes")
    args = parser.parse_args()

    img = Image.open(args.input).convert("RGB")
    arr = np.array(img.convert("L"))
    bboxes, evidence = split_figure(
        arr,
        dark_thresh=args.dark_thresh,
        white_thresh=args.white_thresh,
        ink_thresh=args.ink_thresh,
        white_frac=args.white_frac,
        flat_frac=args.flat_frac,
        min_gutter_px=args.min_gutter_px,
        max_gutter_px=args.max_gutter_px,
        min_panel_px=args.min_panel_px,
        min_panel_frac=args.min_panel_frac,
        col_min_panel_frac=args.col_min_panel_frac,
        frame_min_len_frac=args.frame_min_len_frac,
    )
    print(f"{args.input}: image {img.size}, found {len(bboxes)} panels")
    if len(bboxes) == 1:
        print("  warning: one panel only — the image may be a seamless montage "
              "(manual crop) or the gutter is below --min-gutter-px")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    written = []
    for i, (y0, y1, x0, x1) in enumerate(bboxes):
        panel = img.crop((x0, y0, x1, y1))
        if args.trim:
            panel = _trim_panel(panel)
        if panel.size[0] < args.min_panel_px or panel.size[1] < args.min_panel_px:
            continue
        out = out_dir / f"{stem}_panel_{i:03d}_y{y0}-{y1}_x{x0}-{x1}.png"
        panel.save(out)
        written.append({"path": str(out), "bbox": [int(y0), int(y1), int(x0), int(x1)],
                        "size": [int(panel.size[0]), int(panel.size[1])]})
        print(f"  -> {out.name}  ({panel.size[0]}x{panel.size[1]})")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "input": str(args.input),
            "image_size": [int(img.size[0]), int(img.size[1])],
            "panel_count": len(written),
            "panels": written,
            "separators": evidence,
            "params": {
                "dark_thresh": args.dark_thresh,
                "white_thresh": args.white_thresh,
                "ink_thresh": args.ink_thresh,
                "white_frac": args.white_frac,
                "flat_frac": args.flat_frac,
                "min_gutter_px": args.min_gutter_px,
                "max_gutter_px": args.max_gutter_px,
                "min_panel_px": args.min_panel_px,
                "min_panel_frac": args.min_panel_frac,
                "col_min_panel_frac": args.col_min_panel_frac,
                "frame_min_len_frac": args.frame_min_len_frac,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.debug:
        _draw_debug(arr, [tuple(p["bbox"]) for p in written] or bboxes,
                    evidence, Path(args.debug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
