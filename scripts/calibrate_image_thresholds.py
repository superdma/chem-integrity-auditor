#!/usr/bin/env python3
"""calibrate_image_thresholds.py — ROC-calibrate image-reuse thresholds.

The audit thresholds (dHash < 10 strong, ORB >= 30, curve_r >= 0.95) were
inherited from a small number of cases. That is not a calibration. This
script takes a labelled pair manifest, computes the three deterministic
scores, and reports ROC/AUC plus the Youden-J threshold for each metric.

Manifest format (JSON):
    {
      "pairs": [
        {"a": "panels/a.png", "b": "panels/b.png",
         "label": "duplicate", "technique": "raman"},
        {"a": "panels/a.png", "b": "panels/c.png",
         "label": "different", "technique": "raman"}
      ]
    }

Labels: duplicate / different. For line plots, `same_compound` and
`different_compound` are treated as duplicate / different for the curve
fingerprint. Paths are resolved relative to the manifest file.

Metrics:
    dhash_score = -Hamming(dHash(a), dHash(b))     (higher = more similar)
    orb_score   = surviving ORB matches             (higher = more similar)
    curve_score = curve_r from spectral fingerprint (higher = more similar)
    noise_score = max(noise_corr, bg_line_corr)     (higher = more similar)

Usage:
    calibrate_image_thresholds.py --manifest tests/fixtures/calibration/manifest.json \
        --output workdir/calibration.json

A 10-pair synthetic manifest ships as a smoke fixture. For real use, replace
it with 30–50 labelled pairs per technique, including same-compound
independent measurements (hard negatives).

Stdlib + Pillow + NumPy; OpenCV required for the ORB metric. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("install numpy first: pip install numpy", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_dup  # noqa: E402
import image_dup_orb  # noqa: E402
import spectral_noise_fingerprint as fp  # noqa: E402


def roc_curve(scores: list[float], labels: list[int]):
    """Return thresholds, TPR, FPR, AUC for higher-is-positive scores."""
    pairs = sorted(zip(scores, labels), key=lambda item: -item[0])
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return [], [], [], None
    thresholds, tpr, fpr = [], [], []
    tp = fp_count = 0
    for score, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp_count += 1
        thresholds.append(float(score))
        tpr.append(tp / positives)
        fpr.append(fp_count / negatives)
    # AUC via trapezoid on the ROC points (including origin). Implement it
    # directly: np.trapz was renamed to np.trapezoid in newer NumPy.
    xs = [0.0] + fpr
    ys = [0.0] + tpr
    auc = 0.0
    for i in range(1, len(xs)):
        auc += (xs[i] - xs[i - 1]) * (ys[i] + ys[i - 1]) / 2.0
    return thresholds, tpr, fpr, float(auc)


def best_threshold(scores, labels):
    thresholds, tpr, fpr, auc = roc_curve(scores, labels)
    if not thresholds:
        return None
    best = max(range(len(thresholds)),
               key=lambda i: (tpr[i] - fpr[i], tpr[i], -fpr[i]))
    return {
        "threshold": thresholds[best],
        "tpr": round(tpr[best], 4),
        "fpr": round(fpr[best], 4),
        "youden_j": round(tpr[best] - fpr[best], 4),
        "auc": round(auc, 4) if auc is not None else None,
        "n_pos": sum(labels),
        "n_neg": len(labels) - sum(labels),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ratio", type=float, default=0.75,
                   help="ORB Lowe ratio (default 0.75)")
    p.add_argument("--max-features", type=int, default=500)
    args = p.parse_args()

    manifest_path = Path(args.manifest).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for item in data.get("pairs", []):
        a = str((manifest_path.parent / item["a"]).resolve())
        b = str((manifest_path.parent / item["b"]).resolve())
        label = 1 if item["label"] in {"duplicate", "same_compound"} else 0
        row = {"a": item["a"], "b": item["b"], "label": item["label"],
               "technique": item.get("technique", "unknown"), "y": label}

        row["dhash_distance"] = image_dup.hamming(
            image_dup.dhash(a), image_dup.dhash(b))
        row["dhash_score"] = -row["dhash_distance"]

        img_a = image_dup_orb.load_gray(a)
        img_b = image_dup_orb.load_gray(b)
        if img_a is not None and img_b is not None:
            des_a, des_a_flip = image_dup_orb.detect_orb_all_orientations(
                img_a, args.max_features)
            des_b, des_b_flip = image_dup_orb.detect_orb_all_orientations(
                img_b, args.max_features)
            row["orb_matches"] = max(
                image_dup_orb.match_pair(des_a, des_b, args.ratio),
                image_dup_orb.match_pair(des_a, des_b_flip, args.ratio),
            )
            row["orb_score"] = row["orb_matches"]
        else:
            row["orb_matches"] = None
            row["orb_score"] = None

        arr_a = fp.to_gray_array(Path(a))
        arr_b = fp.to_gray_array(Path(b))
        kind_a, box_a = fp.classify(arr_a)
        kind_b, box_b = fp.classify(arr_b)
        if kind_a == "line_plot" and kind_b == "line_plot":
            prof_a = fp.curve_profile(arr_a, box_a)
            prof_b = fp.curve_profile(arr_b, box_b)
            curve_r = fp.pearson(prof_a, prof_b)
            row["curve_r"] = round(curve_r, 6) if curve_r is not None else None
            row["curve_score"] = curve_r
            noise_a, spread_a = fp.noise_field(arr_a, box_a)
            noise_b, spread_b = fp.noise_field(arr_b, box_b)
            noise_corr = (fp.pearson(noise_a, noise_b)
                          if min(spread_a, spread_b) > 0.05 else None)
            line_corr = fp.bg_line_corr(
                fp.noise_lines_struct(arr_a, box_a),
                fp.noise_lines_struct(arr_b, box_b),
            )
            vals = [v for v in (noise_corr, line_corr) if v is not None]
            row["noise_score"] = max(vals) if vals else None
        else:
            row["curve_r"] = None
            row["curve_score"] = None
            row["noise_score"] = None
        rows.append(row)

    metrics = {}
    for name in ("dhash_score", "orb_score", "curve_score", "noise_score"):
        vals = [(row[name], row["y"]) for row in rows if row.get(name) is not None]
        if len(vals) >= 2:
            scores = [float(v) for v, _ in vals]
            labels = [int(y) for _, y in vals]
            metrics[name] = best_threshold(scores, labels)

    report = {
        "manifest": str(manifest_path),
        "n_pairs": len(rows),
        "pairs": rows,
        "metrics": metrics,
        "method_note": (
            "Scores are higher-is-more-similar. dhash_score = -Hamming; "
            "orb_score = surviving Lowe-ratio matches (best of normal/mirror); "
            "curve_score = topmost-dark profile Pearson; noise_score = max "
            "background-field, background-line correlation. AUC and Youden-J "
            "thresholds are reported per metric. The shipped manifest is a "
            "small synthetic smoke set, not a substitute for 30–50 labelled "
            "pairs per technique."
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"output": str(output), "n_pairs": len(rows),
                      "metrics": metrics}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
