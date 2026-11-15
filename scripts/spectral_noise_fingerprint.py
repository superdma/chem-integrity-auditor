#!/usr/bin/env python3
"""Spectral curve + background-noise fingerprint comparison for two panels.

Answer one question: do two supposedly independent spectra (NMR 1D, XRD,
UV-Vis, HPLC/GC, CV, Raman, IR, EIS-Nyquist …) come from the same underlying
measurement? Two metrics, each robust to a different kind of reuse:

  curve_r    Pearson correlation of the (axis-normalized) signal profile —
             each column's topmost dark pixel. Independent measurements of
             the same sample can have identical PEAK POSITIONS but must
             differ in intensities/noise; identical curves to r >= 0.95 are
             the same data.
  noise_corr Pearson correlation of the background gray-level field on a
             coarse grid. The background of a rendered spectrum carries the
             rendering + digitization noise of its SOURCE. A copied-and-
             relabeled spectrum keeps that noise even if the curve is
             rescaled; an independent one does not.

This catches the reuse modes that perceptual hashing misses: same data with
changed axis range, re-plotted from CSV, white point shifted, or lightly
smoothed. It does NOT catch: a fully hand-redrawn copy (both metrics drop),
or two independent measurements that happen to correlate (verify with the
Defense agent's baseline test before grading).

Usage:
    spectral_noise_fingerprint.py panel_a.png panel_b.png \
        [--out pair_report.json] [--grid 16] [--save-crops out_prefix]

Stdlib + Pillow + numpy. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as exc:
    print(f"missing dependency: {exc}; install Pillow and numpy", file=sys.stderr)
    sys.exit(2)


def to_gray_array(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float64)


def find_plot_box(a: np.ndarray, shrink: float = 0.05):
    """Bounding box of dark content, shrunk inward to drop axis labels.

    Axis tick text lives just outside the curve area; shrinking the content
    bbox by `shrink` fraction (each side) removes most of it while keeping
    the plotted signal. Returns (r0, r1, c0, c1) or None.
    """
    dark = a < 128
    rows = np.where(dark.any(axis=1))[0]
    cols = np.where(dark.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    r0, r1 = int(rows.min()), int(rows.max())
    c0, c1 = int(cols.min()), int(cols.max())
    h, w = r1 - r0, c1 - c0
    if h < 40 or w < 40:
        return None
    dr, dc = int(h * shrink), int(w * shrink)
    return r0 + dr, max(r0 + dr + 10, r1 - dr), c0 + dc, max(c0 + dc + 10, c1 - dc)


def curve_profile(a: np.ndarray, box, norm: int = 320):
    """Topmost dark pixel per column over the normalized box → length-norm array.

    Columns with no dark pixel (flat baseline region) are filled with the
    box bottom so the profile stays continuous.
    """
    r0, r1, c0, c1 = box
    sub = a[r0:r1, c0:c1]
    h, w = sub.shape
    prof = np.full(norm, float(h))
    dark_rows = np.where(sub < 128)[0]
    for x in range(norm):
        col = int(round(x * w / norm))
        if col >= w:
            col = w - 1
        col_dark = sub[:, col] < 128
        idx = np.where(col_dark)[0]
        prof[x] = int(idx.min()) if len(idx) else float(h)
    # normalize profile to [0,1] with top = signal max
    hi = prof.max()
    lo = prof.min()
    if hi - lo < 1e-9:
        return np.zeros(norm)
    return (hi - prof) / (hi - lo)


def noise_field(a: np.ndarray, box, grid: int = 16):
    """Grid of mean BACKGROUND (light) gray levels, centered.

    Returns (field, range) where range = max-min of the field (0 → perfectly
    flat white → incomparable). Cell means average pixel noise down hard
    (var ~1e-3 even for a textured background), so a min/max spread — not a
    variance threshold — is the right flatness test.
    """
    r0, r1, c0, c1 = box
    sub = a[r0:r1, c0:c1]
    bg_mask = sub >= 128
    cells = np.empty(grid * grid, dtype=np.float64)
    for gi, (gr, gc) in enumerate(
            (i // grid, i % grid) for i in range(grid * grid)):
        rr0 = int(gr * (r1 - r0) / grid)
        rr1 = max(rr0 + 1, int((gr + 1) * (r1 - r0) / grid))
        cc0 = int(gc * (c1 - c0) / grid)
        cc1 = max(cc0 + 1, int((gc + 1) * (c1 - c0) / grid))
        patch = sub[rr0:rr1, cc0:cc1]
        mask = bg_mask[rr0:rr1, cc0:cc1]
        cells[gi] = patch[mask].mean() if mask.sum() >= 10 else patch.mean()
    return cells - cells.mean(), float(cells.max() - cells.min())


def noise_lines_struct(a: np.ndarray, box, n_lines: int = 3, resample: int = 256):
    """Raw background gray values along horizontal scan lines, resampled.

    Complementary to the coarse field: scan lines keep pixel-level noise
    alive (no cell averaging), so a copied image's line patterns correlate
    near 1.0 while independent measurements correlate near 0. Returns one
    dict per line: {vals: resampled values, mask: background positions}.
    Correlation is computed in main() on the INTERSECTION of the two masks,
    so curve coverage differences cannot break the comparison.
    """
    r0, r1, c0, c1 = box
    h, w = r1 - r0, c1 - c0
    out = []
    for k in range(1, n_lines + 1):
        rr = r0 + int(h * k / (n_lines + 1))
        line = a[rr, c0:c1]
        xs = np.linspace(0, w, resample).astype(int)
        vals = line[np.clip(xs, 0, w - 1)]
        mask = vals >= 128
        if mask.sum() < resample // 4:
            continue  # mostly curve on this line; skip
        out.append({"vals": vals, "mask": mask})
    return out


def bg_line_corr(struct_a, struct_b):
    """Mean Pearson over lines, on positions where BOTH panels are background."""
    corrs = []
    for la, lb in zip(struct_a, struct_b):
        common = la["mask"] & lb["mask"]
        if int(common.sum()) >= 16:
            c = pearson(la["vals"][common], lb["vals"][common])
            if c is not None:
                corrs.append(c)
    return float(np.mean(corrs)) if corrs else None


def pearson(x: np.ndarray, y: np.ndarray):
    if x.std() < 1e-9 or y.std() < 1e-9:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def classify(a: np.ndarray):
    """Is this a line-plot spectrum (vs photo/2D map)? Dark-pixel ratio.

    The returned box is shrunk inward: a raw content bbox includes the plot
    frame, and "topmost dark pixel per column" would then return the frame's
    top border for every column (a flat profile → curve_r = None). The dark
    ratio is still measured on the raw box so photo detection is unaffected.
    """
    raw = find_plot_box(a, shrink=0.0)
    if raw is None:
        return "unknown", None
    r0, r1, c0, c1 = raw
    sub = a[r0:r1, c0:c1]
    ratio = float((sub < 128).mean())
    if ratio > 0.45:
        return "photo_or_2d", raw
    box = find_plot_box(a, shrink=0.05) or raw
    return "line_plot", box


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compare spectral curve + background noise of two panels.")
    p.add_argument("img1", help="first panel PNG")
    p.add_argument("img2", help="second panel PNG")
    p.add_argument("--out", help="write JSON report here")
    p.add_argument("--grid", type=int, default=16,
                   help="noise-field grid resolution (default 16)")
    p.add_argument("--save-crops", metavar="PREFIX",
                   help="save side-by-side normalized crops as PREFIX.png")
    args = p.parse_args()

    a = to_gray_array(Path(args.img1))
    b = to_gray_array(Path(args.img2))
    kind_a, box_a = classify(a)
    kind_b, box_b = classify(b)

    report = {
        "pair": [str(args.img1), str(args.img2)],
        "size": [[int(a.shape[0]), int(a.shape[1])],
                 [int(b.shape[0]), int(b.shape[1])]],
        "kind": [kind_a, kind_b],
    }
    if kind_a != "line_plot" or kind_b != "line_plot":
        report["applicable"] = False
        report["reason"] = ("one or both panels are photos/2D maps (or have no "
                            "plot box); use image_dup.py / image_dup_orb.py "
                            "for those instead")
        finish(report, args)
        return 0

    prof_a, prof_b = curve_profile(a, box_a), curve_profile(b, box_b)
    noise_a, spread_a = noise_field(a, box_a, args.grid)
    noise_b, spread_b = noise_field(b, box_b, args.grid)
    curve_r = pearson(prof_a, prof_b)
    noise_corr = (pearson(noise_a, noise_b)
                  if min(spread_a, spread_b) > 0.05 else None)
    struct_a = noise_lines_struct(a, box_a)
    struct_b = noise_lines_struct(b, box_b)
    line_corr = bg_line_corr(struct_a, struct_b)
    # brightness delta of background means (white-point shift detector)
    r0, r1, c0, c1 = box_a
    bg_a = a[r0:r1, c0:c1]
    bg_b = b[box_b[0]:box_b[1], box_b[2]:box_b[3]]
    brightness_delta = float(bg_b[bg_b >= 128].mean() - bg_a[bg_a >= 128].mean())

    report.update({
        "applicable": True,
        "curve_r": curve_r,
        "noise_corr": noise_corr,
        "bg_line_corr": line_corr,
        "noise_field_spread": [round(spread_a, 4), round(spread_b, 4)],
        "brightness_delta": brightness_delta,
        "box": [list(box_a), list(box_b)],
    })

    noise_vals = [v for v in (noise_corr, line_corr) if v is not None]
    noise_max = max(noise_vals) if noise_vals else None

    verdicts = []
    if curve_r is None:
        verdicts.append("curve_incomparable: flat profile on at least one panel")
    elif curve_r >= 0.995:
        verdicts.append("identical_curve: same signal to the digit — copy")
    elif curve_r >= 0.97:
        verdicts.append("near_identical_curve: same data within rendering noise")
    elif curve_r >= 0.85:
        verdicts.append("highly_similar_curve: same peak pattern — may be a "
                        "legitimate independent measurement; the noise metrics "
                        "decide")
    else:
        verdicts.append("independent_curves: no reuse signal in the signal itself")

    if noise_max is None:
        verdicts.append("noise_incomparable: flat white background(s) (vector "
                        "re-render or lossless re-plot); fall back to curve_r "
                        "plus vision review")
    elif noise_max >= 0.6:
        verdicts.append("shared_noise_texture: background noise correlates "
                        "strongly — both panels almost certainly come from one "
                        "source image")
    elif noise_max < 0.15:
        if curve_r is not None and curve_r >= 0.85:
            verdicts.append("same_curve_independent_noise: signal matches but "
                            "backgrounds do not — either a legitimate "
                            "independent measurement, or a re-draw from shared "
                            "raw data (the fraud scenario for 'independent "
                            "replicate' claims); resolve with vision + Defense "
                            "agent")
        else:
            verdicts.append("independent_noise: no shared texture")
    else:
        verdicts.append("inconclusive_noise: weak background correlation — "
                        "inspect the crops visually")
    report["verdict"] = verdicts
    report["method_note"] = ("curve_r: Pearson of axis-normalized topmost-dark "
                             "profiles; noise_corr: Pearson of centered "
                             f"{args.grid}x{args.grid} background-gray cell "
                             "means; bg_line_corr: Pearson of raw background "
                             "pixels along 3 scan lines (common positions). "
                             "Absorbs linear axis rescaling and white-point "
                             "shift; does NOT absorb log axes, truncated "
                             "ranges, smoothing filters, or hand-redrawing. "
                             "Empirical anchors (Dasari 2010 audit): reused "
                             "gels r=0.82-0.93, independent controls r<=0.38. "
                             "Verify with vision + Defense agent before grading.")

    if args.save_crops:
        pa = Image.fromarray((prof_a * 255).astype(np.uint8))
        pb = Image.fromarray((prof_b * 255).astype(np.uint8))
        combo = Image.new("L", (pa.width, pa.height * 2 + 8), 255)
        combo.paste(pa, (0, 0))
        combo.paste(pb, (0, pa.height + 8))
        combo.save(Path(args.save_crops) + ".png")
        report["crop_image"] = str(Path(args.save_crops) + ".png")

    finish(report, args)
    return 0


def finish(report: dict, args) -> None:
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "box"},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    raise SystemExit(main())
