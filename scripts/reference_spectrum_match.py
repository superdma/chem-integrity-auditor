#!/usr/bin/env python3
"""Compare a published spectrum panel against a reference peak table.

Semi-automatic by design. The hard, error-prone half — turning a raster
spectrum into peak positions — is deterministic; the judgement half —
whether a high match means the authors copied a database spectrum — stays
with the auditor. SDBS has no public API and its terms do not invite
scraping, so this tool consumes an exported peak table (CSV/TSV/JSON/text)
that the auditor obtains from SDBS, NMRShiftDB2, or the paper's SI.

Two entry modes
---------------
    # digitize peaks from a panel image (axis calibration required)
    reference_spectrum_match.py --sample-image fig2b.png \\
        --sample-x0 '120:8.0' --sample-x1 '980:0.0' \\
        --technique h1nmr --ref sdbs_12345.csv --output match.json

    # compare an already-digitized peak list
    reference_spectrum_match.py --sample-peaks digitized.csv \\
        --technique h1nmr --ref sdbs_12345.csv --output match.json

Reference file formats
----------------------
- CSV/TSV: one peak per row; first numeric cell = x, optional second =
  intensity. Header rows without a leading number are skipped.
- TXT: each line must START with the shift (e.g. "7.26  2.0  s"),
  which is how SDBS peak lists export. Lines not starting with a number
  are skipped (headers/notes).
- JSON: [7.26, 3.34, ...] or [{"x": 7.26, "intensity": 2.0}, ...] or
  {"peaks": [...]}.

What a high score means (and does not mean)
-------------------------------------------
A high match between a paper's "measured" spectrum and a database peak
list is consistent with two very different stories: (a) the authors
measured the same real compound and the data legitimately agree, or
(b) the spectrum was copied from the database. The tool reports the
numeric match; the finding file must state which story the paper's own
claims (original measurement? new compound? unique conditions?) support.
Never grade a database match as fraud on the match alone.

Python 3.8+; Pillow + NumPy required; SciPy optional (peak picking falls
back to local maxima).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    print(f"missing dependency: {exc}; install Pillow and numpy", file=sys.stderr)
    sys.exit(2)

NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# Absolute tolerance defaults per technique (x-axis units).
TECH_TOL = {
    "h1nmr": 0.03, "1hnmr": 0.03, "nmr": 0.05,
    "c13nmr": 0.2, "13cnmr": 0.2,
    "xrd": 0.2, "hplc": 0.05, "gc": 0.03,
    "ir": 4.0, "uv": 2.0, "ms": 0.02, "raman": 3.0,
}
TECH_UNIT = {
    "h1nmr": "ppm", "1hnmr": "ppm", "nmr": "ppm", "c13nmr": "ppm",
    "13cnmr": "ppm", "xrd": "°2θ", "hplc": "min", "gc": "min",
    "ir": "cm^-1", "uv": "nm", "ms": "m/z", "raman": "cm^-1",
}
VERDICTS = ((0.90, "very_high"), (0.75, "high"), (0.55, "partial"))


# --------------------------------------------------------------------------
# reference / sample peak parsing
# --------------------------------------------------------------------------

def _peaks_from_json(data):
    if isinstance(data, dict):
        data = data.get("peaks", [])
    out = []
    for item in data:
        if isinstance(item, (int, float)):
            out.append({"x": float(item), "intensity": None})
        elif isinstance(item, dict) and "x" in item:
            out.append({"x": float(item["x"]),
                        "intensity": item.get("intensity")})
        elif isinstance(item, (list, tuple)) and item:
            out.append({"x": float(item[0]),
                        "intensity": float(item[1]) if len(item) > 1 else None})
    return out


def load_peak_file(path: Path, fmt="auto"):
    """Load a reference or sample peak table. Returns [{x, intensity}]."""
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    fmt = fmt if fmt != "auto" else (
        "json" if suffix == ".json" else
        "tsv" if suffix in (".tsv", ".tab") else
        "csv" if suffix == ".csv" else "text")
    if fmt == "json":
        return _peaks_from_json(json.loads(text))
    peaks = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if fmt in ("csv", "tsv"):
            delim = "\t" if fmt == "tsv" or "\t" in line else ","
            cells = [c.strip().strip('"') for c in line.split(delim)]
            nums = [NUM.search(c) for c in cells]
            vals = [float(m.group(0)) for m in nums if m]
            if not vals:
                continue  # header
            x = vals[0]
            inten = vals[1] if len(vals) > 1 else None
        else:
            # TXT: shift must start the line (SDBS export style).
            m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\b(.*)$", line)
            if not m:
                continue
            x = float(m.group(1))
            rest = NUM.findall(m.group(2))
            inten = float(rest[0]) if rest else None
        peaks.append({"x": x, "intensity": inten})
    return peaks


# --------------------------------------------------------------------------
# image digitization
# --------------------------------------------------------------------------

def to_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float64)


def parse_px_value(text: str):
    """Parse '120:8.0' or '120,8.0' -> (120.0, 8.0)."""
    if not text:
        return None
    parts = re.split(r"[:=,]", text.strip())
    if len(parts) != 2:
        raise SystemExit(f"malformed calibration {text!r}; use PIXEL:VALUE")
    return float(parts[0]), float(parts[1])


def find_plot_box(a: np.ndarray, margin_frac=0.005):
    """Bounding box of dark content (plot frame + curve + labels)."""
    dark = a < 140
    rows = np.where(dark.any(axis=1))[0]
    cols = np.where(dark.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        raise SystemExit("image has no dark content")
    h, w = a.shape
    my = max(1, int(h * margin_frac))
    mx = max(1, int(w * margin_frac))
    return (max(rows[0], my), min(rows[-1], h - 1 - my),
            max(cols[0], mx), min(cols[-1], w - 1 - mx))


def trace_curve(a: np.ndarray, box, dark_thresh=140):
    """Topmost dark pixel per column within box -> (rows, coverage)."""
    r0, r1, c0, c1 = box
    sub = a[r0:r1 + 1, c0:c1 + 1]
    h, w = sub.shape
    ys = np.full(w, np.nan)
    for j in range(w):
        col = sub[:, j]
        idx = np.where(col < dark_thresh)[0]
        if len(idx):
            ys[j] = idx[0]
    coverage = float(np.isfinite(ys).mean())
    # interpolate gaps (antialiased columns, legend overlaps)
    if np.isfinite(ys).sum() >= 2:
        good = np.isfinite(ys)
        ys[~good] = np.interp(np.where(~good)[0], np.where(good)[0], ys[good])
    return ys, coverage


def smooth(y: np.ndarray, window=3):
    if window <= 1:
        return y
    kernel = np.ones(window) / window
    pad = window // 2
    ypad = np.pad(y, pad, mode="edge")
    return np.convolve(ypad, kernel, mode="valid")


def pick_peaks(xs, intensities, min_prominence=0.03, min_distance=2):
    """Return peak dicts; SciPy find_peaks when available, else local maxima."""
    if len(intensities) < 3:
        return []
    y = np.asarray(intensities, dtype=float)
    span = float(np.nanmax(y) - np.nanmin(y)) or 1.0
    prom = max(min_prominence * span, 1e-9)
    try:
        from scipy.signal import find_peaks
        idx, props = find_peaks(y, prominence=prom, distance=min_distance)
        proms = props.get("prominences", np.zeros(len(idx)))
    except Exception:
        idx = [i for i in range(1, len(y) - 1)
               if y[i] >= y[i - 1] and y[i] > y[i + 1]
               and y[i] - min(y[max(0, i - 3):i + 1]) >= prom]
        idx = np.asarray(idx, dtype=int)
        proms = np.array([y[i] - np.min(y[max(0, i - 3):i + 1]) for i in idx])
    raw = [(int(i), float(p)) for i, p in zip(idx, proms)]
    # Noise bumps in a rendered spectrum cluster at low prominence while real
    # peaks sit well above them. When the picker returns many candidates,
    # raise the threshold to 2.5x the median prominence (a robust noise-level
    # estimate). Few candidates -> keep the user's absolute threshold.
    if len(raw) > 8:
        med = float(np.median([p for _i, p in raw])) or 0.0
        raw = [(i, p) for i, p in raw if p >= max(prom, 2.5 * med)]
    peaks = []
    for i, p in raw:
        peaks.append({
            "x": round(float(xs[i]), 6),
            "intensity": round(float((y[i] - np.nanmin(y)) / span), 4),
            "prominence": round(float(p / span), 4),
            "px": int(i),
        })
    peaks.sort(key=lambda d: d["x"])
    return peaks


def digitize(image_path: Path, x0, x1, trace="top", smooth_window=3,
             min_prominence=0.03, min_distance=2, box_inset=3):
    if x0 is None or x1 is None or abs(x1[0] - x0[0]) < 1:
        raise SystemExit("image mode needs --sample-x0 PX:VALUE and "
                         "--sample-x1 PX:VALUE (two distinct pixels)")
    a = to_gray(image_path)
    box = find_plot_box(a)
    # The outermost dark pixels are the plot frame. Tracing the topmost dark
    # pixel without insetting returns the frame's top border for every column.
    r0, r1, c0, c1 = box
    box = (r0 + box_inset, r1 - box_inset, c0 + box_inset, c1 - box_inset)
    if box[0] >= box[1] or box[2] >= box[3]:
        raise SystemExit("plot box collapsed after inset; image too small")
    ys, coverage = trace_curve(a, box)
    if coverage < 0.5:
        raise SystemExit(f"only {coverage:.0%} of columns have a traced curve; "
                         "check the crop / threshold")
    # intensity: upward from the bottom of the traced curve
    r0, r1, c0, c1 = box
    ymax = np.nanmax(ys)
    ymin = np.nanmin(ys)
    span = (ymax - ymin) or 1.0
    inten = (ymax - ys) / span
    inten = smooth(inten, smooth_window)
    cols = np.arange(len(ys), dtype=float) + c0
    xs = x0[1] + (cols - x0[0]) * (x1[1] - x0[1]) / (x1[0] - x0[0])
    peaks = pick_peaks(xs, inten, min_prominence, min_distance)
    # drop peaks within 1.5% of either plot edge (axis frame artefacts)
    lo, hi = min(xs[0], xs[-1]), max(xs[0], xs[-1])
    edge = 0.015 * (hi - lo)
    peaks = [p for p in peaks if lo + edge < p["x"] < hi - edge]
    return peaks, {
        "image": str(image_path), "box": list(map(int, box)),
        "trace_coverage": round(coverage, 3),
        "x0": x0, "x1": x1,
    }


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def match_peaks(sample, ref, tol):
    """Greedy nearest pairing with a hard tolerance. Returns match dict."""
    pairs = []
    for i, s in enumerate(sample):
        for j, r in enumerate(ref):
            d = abs(s["x"] - r["x"])
            if d <= tol:
                pairs.append((d, i, j))
    pairs.sort()
    used_s, used_r, matched = set(), set(), []
    for d, i, j in pairs:
        if i in used_s or j in used_r:
            continue
        used_s.add(i)
        used_r.add(j)
        matched.append({
            "sample_x": round(sample[i]["x"], 5),
            "ref_x": round(ref[j]["x"], 5),
            "delta": round(sample[i]["x"] - ref[j]["x"], 5),
        })
    n_s, n_r = len(sample), len(ref)
    n_m = len(matched)
    precision = n_m / n_s if n_s else 0.0
    recall = n_m / n_r if n_r else 0.0
    jaccard = n_m / (n_s + n_r - n_m) if (n_s + n_r - n_m) else 0.0
    # Recall is weighted higher: published spectra legitimately carry solvent
    # and impurity peaks that a reference table does not. A copied database
    # spectrum shows ALL reference peaks; extra peaks are weak counter-
    # evidence, not a reason to call the match low.
    score = (0.75 * recall + 0.25 * precision) if n_m else 0.0
    rmsd = math.sqrt(sum(p["delta"] ** 2 for p in matched) / n_m) if n_m else None
    verdict = "low"
    for cut, name in VERDICTS:
        if score >= cut:
            verdict = name
            break
    return {
        "n_sample": n_s, "n_reference": n_r, "n_matched": n_m,
        "matched_fraction_sample": round(precision, 4),
        "matched_fraction_reference": round(recall, 4),
        "jaccard": round(jaccard, 4),
        "score": round(score, 4),
        "rmsd": round(rmsd, 6) if rmsd is not None else None,
        "verdict": verdict,
        "tolerance": tol,
        "matched": matched,
        "unmatched_sample": [p["x"] for k, p in enumerate(sample)
                             if k not in used_s][:50],
        "unmatched_reference": [p["x"] for k, p in enumerate(ref)
                                if k not in used_r][:50],
    }


# --------------------------------------------------------------------------
# evidence image
# --------------------------------------------------------------------------

def annotate(image_path, peaks, out_path):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for k, p in enumerate(peaks, 1):
        px = p.get("px")
        if px is None:
            continue
        draw.line([(px, 0), (px, img.height)], fill=(220, 30, 30), width=1)
        draw.text((min(px + 2, img.width - 12), 2), str(k), fill=(220, 30, 30))
    img.save(out_path)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Match a published spectrum against a reference peak table "
                    "(peak-table comparison; no database scraping).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="x-axis calibration: --sample-x0 '120:8.0' --sample-x1 '980:0.0' "
               "means pixel 120 = 8.0 ppm and pixel 980 = 0.0 ppm (NMR axes "
               "decrease left-to-right, so value1 < value0 is normal).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sample-image", help="spectrum panel PNG/JPG")
    src.add_argument("--sample-peaks", help="already-digitized peak table")
    ap.add_argument("--sample-x0", help="PIXEL:VALUE at left calibration point")
    ap.add_argument("--sample-x1", help="PIXEL:VALUE at right calibration point")
    ap.add_argument("--technique", default="h1nmr",
                    help="h1nmr|c13nmr|xrd|hplc|gc|ir|uv|ms|raman (default h1nmr)")
    ap.add_argument("--tol", type=float, help="override matching tolerance")
    ap.add_argument("--ref", action="append", default=[],
                    help="reference peak table (repeatable)")
    ap.add_argument("--ref-format", default="auto",
                    choices=["auto", "csv", "tsv", "json", "text"])
    ap.add_argument("--min-prominence", type=float, default=0.03,
                    help="fraction of y-range (default 0.03)")
    ap.add_argument("--min-distance", type=int, default=2)
    ap.add_argument("--box-inset", type=int, default=3,
                    help="pixels trimmed inside the content bbox to drop the "
                         "plot frame (default 3)")
    ap.add_argument("--smooth", type=int, default=3)
    ap.add_argument("--relabel", action="append", default=[],
                    help="LABEL=PATH override for a reference file name")
    ap.add_argument("--annotate", help="write an annotated evidence PNG")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    if not args.ref:
        raise SystemExit("at least one --ref peak table is required")

    tech = args.technique.lower()
    tol = args.tol if args.tol is not None else TECH_TOL.get(tech, 0.05)
    unit = TECH_UNIT.get(tech, "x")

    if args.sample_peaks:
        sample = load_peak_file(Path(args.sample_peaks), args.ref_format)
        sample_meta = {"source": args.sample_peaks, "mode": "peak-table",
                       "peaks": sample}
    else:
        sample, meta = digitize(
            Path(args.sample_image), parse_px_value(args.sample_x0),
            parse_px_value(args.sample_x1), smooth_window=args.smooth,
            min_prominence=args.min_prominence,
            min_distance=args.min_distance, box_inset=args.box_inset)
        sample_meta = {"source": args.sample_image, "mode": "digitized",
                       "calibration": meta, "peaks": sample}
        if args.annotate:
            annotate(Path(args.sample_image), sample, Path(args.annotate))

    labels = {}
    for item in args.relabel:
        if "=" in item:
            k, v = item.split("=", 1)
            labels[v] = k

    results = []
    for ref_path in args.ref:
        rp = Path(ref_path)
        try:
            ref = load_peak_file(rp, args.ref_format)
        except Exception as exc:  # noqa: BLE001
            results.append({"label": rp.name, "error": str(exc)})
            continue
        if not ref:
            results.append({"label": rp.name, "error": "no numeric peaks parsed"})
            continue
        label = labels.get(ref_path) or rp.stem
        results.append({"label": label, "path": ref_path, "n_reference": len(ref),
                        "match": match_peaks(sample, ref, tol)})

    valid = [r for r in results if "match" in r]
    best = max(valid, key=lambda r: r["match"]["score"]) if valid else None
    counts = {}
    for r in valid:
        counts[r["match"]["verdict"]] = counts.get(r["match"]["verdict"], 0) + 1

    report = {
        "meta": {
            "tool": "reference_spectrum_match.py", "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "technique": tech, "unit": unit, "tolerance": tol,
            "note": "A high match is consistent with BOTH a legitimate "
                    "measurement of the same compound and a copied database "
                    "spectrum. Grade only with the paper's own claims "
                    "(original measurement? new compound?) and a second "
                    "evidence line.",
            "limits": "Digitization depends on axis calibration and line "
                      "legibility; broad/multiplet peaks collapse to one "
                      "maximum, so compare peak COUNTS with care. Log axes, "
                      "truncated windows and hand-drawn spectra degrade the "
                      "trace.",
        },
        "sample": sample_meta,
        "references": results,
        "best": best,
        "summary": {"n_references": len(results), "verdict_counts": counts},
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    best_s = (f"best {best['label']} score={best['match']['score']:.2f} "
              f"({best['match']['verdict']})" if best else "no valid reference")
    print(f"wrote {out}: {len(sample)} sample peaks vs {len(results)} "
          f"reference(s); {best_s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
