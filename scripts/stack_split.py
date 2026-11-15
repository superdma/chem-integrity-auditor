#!/usr/bin/env python3
"""Split a stacked-spectra figure into one image per trace.

Many chemistry figures stack 2–4 spectra in a single panel, separated by
full-width black rules (Raman/XRD/XPS/UV-Vis). `panel_split.py` looks for
WHITE gutters between panels, so it returns one panel for these figures and
the per-trace comparison tools have nothing to compare. This script finds
full-width dark separator rows (or columns) and crops the regions between
them. `--keep-color` additionally isolates one coloured trace (red/blue/
green) by whitening every other pixel, which makes ORB/phash compare the
curve rather than the legend text and axis labels.

Usage
-----
    stack_split.py fig2.png out/ --axis horizontal
    # auto-detect the dominant colour in each band and whiten the rest
    stack_split.py fig2.png out/ --keep-color auto

Output names: <stem>_band_<NN>_y<start>-<end>.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    print(f"missing dependency: {exc}; install Pillow and numpy", file=sys.stderr)
    sys.exit(2)


def group_runs(indices, gap=1):
    """Group sorted indices into [start, end] runs."""
    runs = []
    for i in indices:
        if runs and i - runs[-1][1] <= gap:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return runs


def separator_bands(gray, axis, line_frac, dark):
    """Return (bands, separators) for the chosen axis."""
    h, w = gray.shape
    if axis == "horizontal":
        frac = (gray < dark).mean(axis=1)
        sep = np.where(frac >= line_frac)[0]
        runs = group_runs(sep.tolist())
        bands = []
        for a, b in zip(runs, runs[1:]):
            start, end = a[1] + 1, b[0] - 1
            if end - start + 1 > 0:
                bands.append((start, end, 0, w - 1))
        return bands, runs
    frac = (gray < dark).mean(axis=0)
    sep = np.where(frac >= line_frac)[0]
    runs = group_runs(sep.tolist())
    bands = []
    for a, b in zip(runs, runs[1:]):
        start, end = a[1] + 1, b[0] - 1
        if end - start + 1 > 0:
            bands.append((0, h - 1, start, end))
    return bands, runs


def colour_mask(rgb, name):
    r, g, b = rgb[:, :, 0].astype(int), rgb[:, :, 1].astype(int), \
        rgb[:, :, 2].astype(int)
    if name == "red":
        return (r > 130) & (g < 120) & (b < 120) & (r - np.maximum(g, b) > 40)
    if name == "blue":
        return (b > 110) & (r < 120) & (g < 150) & (b - np.maximum(r, g) > 30)
    if name == "green":
        return (g > 80) & (r < 120) & (b < 120) & (g - np.maximum(r, b) > 25)
    raise ValueError(name)


def dominant_colour(rgb):
    counts = {name: int(colour_mask(rgb, name).sum())
              for name in ("red", "blue", "green")}
    name, n = max(counts.items(), key=lambda kv: kv[1])
    return name if n >= 80 else None


def whiten_except(rgb, name):
    mask = colour_mask(rgb, name)
    out = np.full_like(rgb, 255)
    out[mask] = rgb[mask]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Split stacked spectra on full-width separator lines.")
    ap.add_argument("input", help="figure image (PNG/JPG)")
    ap.add_argument("out_dir", help="output directory")
    ap.add_argument("--axis", choices=["horizontal", "vertical"],
                    default="horizontal",
                    help="stacking direction (default horizontal = rows)")
    ap.add_argument("--line-frac", type=float, default=0.80,
                    help="fraction of the content width that must be dark to "
                         "count as a separator (default 0.80)")
    ap.add_argument("--dark", type=int, default=100,
                    help="gray threshold for separator pixels (default 100)")
    ap.add_argument("--min-size", type=int, default=40,
                    help="minimum band height/width in pixels (default 40)")
    ap.add_argument("--keep-color", choices=["auto", "red", "blue", "green",
                                             "none"], default="none",
                    help="whiten every pixel not belonging to this colour")
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGB")
    rgb = np.asarray(img)
    gray = np.asarray(img.convert("L"))
    bands, runs = separator_bands(gray, args.axis, args.line_frac, args.dark)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    written = 0
    for i, (r0, r1, c0, c1) in enumerate(bands):
        size = (r1 - r0 + 1) if args.axis == "horizontal" else (c1 - c0 + 1)
        if size < args.min_size:
            continue
        crop = rgb[r0:r1 + 1, c0:c1 + 1]
        colour = args.keep_color
        if colour == "auto":
            colour = dominant_colour(crop)
        if colour and colour != "none":
            crop = whiten_except(crop, colour)
        suffix = f"_y{r0}-{r1}" if args.axis == "horizontal" else f"_x{c0}-{c1}"
        out = out_dir / f"{stem}_band_{i:02d}{suffix}.png"
        Image.fromarray(crop).save(out)
        written += 1
        print(f"  -> {out.name}  ({crop.shape[1]}x{crop.shape[0]}, "
              f"colour={colour or 'original'})")
    print(f"{args.input}: {len(runs)} separator rule(s), {written} band(s) "
          f"written to {out_dir}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
