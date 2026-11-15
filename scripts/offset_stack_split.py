#!/usr/bin/env python3
"""offset_stack_split.py — semi-automatic split of offset-stacked traces.

`stack_split.py` needs full-width separator rules. Many XRD/FTIR figures stack
traces by vertical offset with no rules; the traces are only separated by
white space. This script proposes cut rows from a row-ink profile and can
crop exact bands once the auditor confirms the cuts.

It is deliberately **semi-automatic**: a faint trace, a broad hump, or a label
in the gap can move a proposed cut by several pixels, and a wrong cut silently
changes the comparison. The workflow is:

1. `--propose` (default) prints candidate cuts with their profile values.
2. Inspect the figure / annotated proposal.
3. Re-run with `--cuts 130,265,350,480` to write the bands.

Usage:
    offset_stack_split.py fig.png out/ --propose
    offset_stack_split.py fig.png out/ --cuts 130,265,350,480
    offset_stack_split.py fig.png out/ --traces 5     # auto proposal + crop

No network. Python 3.8+; Pillow, NumPy, OpenCV.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as exc:
    sys.stderr.write(f"missing dependency: {exc}\n")
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack_split import dominant_colour, whiten_except  # noqa: E402
from spectral_noise_fingerprint import classify  # noqa: E402

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def row_profile(gray: np.ndarray, box, *, dilate_px: int = 11):
    """Ink fraction per row, robust to labels on one side.

    The plot box is split into three vertical thirds; the per-row minimum is
    used, so a legend or axis label occupying one third cannot fill a gap.
    Vertical dilation turns a thin curve into a solid band.
    """
    y0, y1, x0, x1 = box
    sub = gray[y0:y1, x0:x1]
    ink = (sub < 215).astype(np.uint8)
    if dilate_px > 1:
        ink = cv2.dilate(ink, np.ones((dilate_px, 1), np.uint8))
    width = ink.shape[1]
    step = max(1, width // 3)
    thirds = [ink[:, i * step:min(width, (i + 1) * step)].mean(axis=1)
              for i in range(3)]
    profile = np.minimum(np.minimum(thirds[0], thirds[1]), thirds[2])
    return np.convolve(profile, np.ones(3) / 3.0, mode="same")


def candidate_cuts(profile: np.ndarray, *, min_band: int, edge: int = 6):
    """Local minima with a small prominence; returns [(row, prominence)]."""
    try:
        from scipy.signal import find_peaks
    except ImportError:
        # Numpy-only fallback: every local minimum with a lower neighbour.
        peaks = []
        for i in range(edge + 1, len(profile) - edge - 1):
            if profile[i] <= profile[i - 1] and profile[i] <= profile[i + 1]:
                peaks.append((i, float(profile[max(0, i - 3):i + 4].max()
                                        - profile[i])))
        return peaks
    peaks, props = find_peaks(-profile, distance=max(5, min_band // 2),
                              prominence=0.003)
    return [(int(p), float(prom)) for p, prom in
            zip(peaks, props["prominences"])]


def pick_cuts(profile, cuts, count: int, min_band: int):
    """Pick `count` cuts from candidates, keeping min_band between them."""
    ranked = sorted(cuts, key=lambda c: -c[1])
    chosen = []
    for row, _ in ranked:
        if row < min_band or row > len(profile) - min_band:
            continue
        if any(abs(row - other) < min_band for other in chosen):
            continue
        chosen.append(row)
        if len(chosen) == count:
            break
    return sorted(chosen[:count])


def annotated(path: Path, cuts, out_path: Path):
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for i, (row, score) in enumerate(cuts):
        draw.line([(0, row), (img.width - 1, row)], fill=(220, 0, 0), width=1)
        draw.text((4, max(0, row - 12)), f"{i}: y={row} p={score:.3f}",
                  fill=(220, 0, 0))
    img.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("image", help="figure/panel image")
    ap.add_argument("out_dir", nargs="?", default="",
                    help="output directory (required with --cuts/--traces)")
    ap.add_argument("--propose", action="store_true",
                    help="print candidate cuts only (default when no --cuts)")
    ap.add_argument("--traces", type=int, default=0,
                    help="expected trace count; auto-pick N-1 cuts and crop")
    ap.add_argument("--cuts", default="",
                    help="comma-separated y cut rows, e.g. 130,265,350")
    ap.add_argument("--min-band-px", type=int, default=20)
    ap.add_argument("--pad", type=int, default=2,
                    help="pixels of padding above/below each band")
    ap.add_argument("--dilate-px", type=int, default=11)
    ap.add_argument("--keep-color", choices=["auto", "red", "blue", "green",
                                             "none"], default="none")
    ap.add_argument("--json", metavar="PATH", help="write proposal/crop JSON")
    ap.add_argument("--debug", metavar="PNG",
                    help="annotate proposed/accepted cuts")
    args = ap.parse_args()

    path = Path(args.image).expanduser().resolve()
    if not path.is_file():
        sys.stderr.write(f"missing image: {path}\n")
        return 2
    rgb = np.asarray(Image.open(path).convert("RGB"))
    gray = np.asarray(Image.open(path).convert("L"))
    kind, box = classify(gray)
    if kind != "line_plot" or box is None:
        sys.stderr.write(f"not a line plot ({kind}); crop the plot area first\n")
        return 2
    profile = row_profile(gray, box, dilate_px=args.dilate_px)
    cuts = candidate_cuts(profile, min_band=args.min_band_px)

    explicit = [int(x) for x in args.cuts.split(",") if x.strip()]
    chosen_abs = []
    chosen_rel = []
    if explicit:
        if any(b <= a for a, b in zip(explicit, explicit[1:])):
            sys.stderr.write("--cuts must be strictly ascending\n")
            return 2
        chosen_abs = explicit
        chosen_rel = [c - box[0] for c in explicit]
    elif args.traces >= 2:
        chosen_rel = pick_cuts(profile, cuts, args.traces - 1, args.min_band_px)
        chosen_abs = [c + box[0] for c in chosen_rel]
    elif not args.propose:
        args.propose = True

    report = {
        "image": str(path),
        "plot_box": [int(v) for v in box],
        "profile_length": int(len(profile)),
        "candidates": [{"row": int(row) + box[0],
                        "profile": round(float(profile[row]), 5),
                        "prominence": round(float(prom), 5)}
                       for row, prom in cuts],
        "requested_traces": args.traces,
        "cuts": [int(c) for c in chosen_abs],
        "method_note": (
            "Cuts are chosen from a vertically dilated row-ink profile with a "
            "per-third minimum to suppress legends. Semi-automatic: confirm "
            "the proposal visually; a faint trace or a label in a gap can "
            "shift a cut and silently change the comparison."
        ),
    }

    if args.propose and not chosen_abs:
        for row, prom in cuts:
            print(f"  y={row + box[0]:4d}  profile={profile[row]:.3f}  "
                  f"prominence={prom:.3f}")
        if args.debug:
            annotated(path, [(r + box[0], float(profile[r]))
                             for r, _ in cuts], Path(args.debug))
        if args.json:
            Path(args.json).write_text(json.dumps(report, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")
        print(json.dumps({"candidates": len(cuts), "cuts": []},
                         ensure_ascii=False))
        return 0

    if not args.out_dir:
        sys.stderr.write("out_dir is required with --cuts/--traces\n")
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    edges = [0] + chosen_abs + [gray.shape[0]]
    written = []
    for i, (a, b) in enumerate(zip(edges, edges[1:])):
        if b - a < args.min_band_px:
            sys.stderr.write(f"band {i} is only {b - a}px; skipped\n")
            continue
        y0 = max(0, a - args.pad)
        y1 = min(gray.shape[0], b + args.pad)
        crop = rgb[y0:y1, :]
        colour = args.keep_color
        if colour == "auto":
            colour = dominant_colour(crop)
        if colour and colour != "none":
            crop = whiten_except(crop, colour)
        out = out_dir / f"{path.stem}_offset_band_{i:02d}_y{y0}-{y1}.png"
        Image.fromarray(crop).save(out)
        written.append(str(out))
    report["bands"] = written
    if args.debug:
        annotated(path, [(c, float(profile[c - box[0]]))
                         for c in chosen_abs if 0 <= c - box[0] < len(profile)],
                  Path(args.debug))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
    print(json.dumps({"bands": len(written), "cuts": report["cuts"]},
                     ensure_ascii=False))
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
