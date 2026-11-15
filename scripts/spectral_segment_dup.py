#!/usr/bin/env python3
"""spectral_segment_dup.py — find copied segments inside/between line plots.

Retraction notices often say "a segment of the curve in Fig. 3a is identical
to a segment in Fig. 3b" or "the same stretch appears twice in one trace".
dHash/ORB compare whole panels and average that away; a per-pixel template
match does not.

Primary method (OpenCV available): slide a full-height patch across each
line-plot panel and template-match it against the same panel (within-trace
copy) or the other panel (between-trace copy) with TM_CCOEFF_NORMED.
Overlapping positions are masked out. A pixel-identical copy scores ~1.00;
independent curves normally stay well below 0.95.

Fallback (no OpenCV): 1D curve-profile windows with Pearson + Fisher z +
Benjamini-Hochberg correction. This is weaker but still useful for
re-rendered traces.

Usage:
    # within one trace
    spectral_segment_dup.py --image panel.png --out report.json
    # between two traces
    spectral_segment_dup.py --image a.png --image b.png --out report.json
    # annotate the best matches on the first image
    spectral_segment_dup.py --image panel.png --annotate marked.png

This is evidence, not a verdict. Periodic lattice fringes, a repeated
calibration pulse, a legitimately repeated reference peak, or a plotted fit
function can all match. Check the SI and raw data before grading.

Stdlib + Pillow + NumPy; OpenCV optional. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as exc:
    print(f"missing dependency: {exc}; install Pillow and numpy", file=sys.stderr)
    sys.exit(2)

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only on minimal installs
    cv2 = None

# Reuse the curve extraction / plot classification from the fingerprint tool.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spectral_noise_fingerprint import (  # noqa: E402
    classify, curve_profile, pearson, to_gray_array,
)


def _smooth(x: np.ndarray, k: int = 3) -> np.ndarray:
    if k <= 1 or len(x) < k:
        return x
    kernel = np.ones(k, dtype=float) / k
    return np.convolve(x, kernel, mode="same")


def highpass(x: np.ndarray, window: int) -> np.ndarray:
    """Remove slow baseline; keep local peak structure and noise."""
    if window < 3:
        window = 3
    baseline = _smooth(x, max(3, window | 1))
    y = _smooth(x, 3) - baseline
    y = y - y.mean()
    std = y.std()
    return y / std if std > 1e-9 else np.zeros_like(y)


def fisher_p(r: float, n: int) -> float:
    """Two-sided p-value for Pearson r via Fisher z (normal approximation)."""
    if r is None or n <= 3:
        return 1.0
    r = max(-0.999999, min(0.999999, r))
    z = math.atanh(r) * math.sqrt(n - 3)
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def bh_qvalues(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg q-values, order preserved."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        value = min(prev, pvalues[idx] * m / rank)
        q[idx] = value
        prev = value
    return q


def patch_matches(gray: np.ndarray, box, *, window: int, step: int,
                  min_score: float, max_matches: int):
    """Template-match a sliding full-height patch within one panel."""
    r0, r1, c0, c1 = box
    sub = np.ascontiguousarray(gray[r0:r1, c0:c1], dtype=np.float32)
    if sub.shape[1] <= window + 2:
        return [], 0
    best = []
    for sx in range(0, sub.shape[1] - window, max(1, step)):
        template = sub[:, sx:sx + window]
        # Flat baseline patches match their neighbours trivially; they carry
        # no copy evidence, so skip low-contrast templates.
        if template.std() < 5.0:
            continue
        result = cv2.matchTemplate(sub, template, cv2.TM_CCOEFF_NORMED)
        # Exclude the patch and a wide neighbourhood: adjacent windows of the
        # same smooth curve correlate by construction.
        left = max(0, sx - 2 * window)
        right = min(result.shape[1], sx + 2 * window)
        result[:, left:right] = -1.0
        _, score, _, loc = cv2.minMaxLoc(result)
        if score >= min_score:
            best.append({
                "start_a": int(c0 + sx),
                "start_b": int(c0 + loc[0]),
                "window_px": int(window),
                "score": round(float(score), 6),
            })
    best.sort(key=lambda m: -m["score"])
    return dedupe_nonoverlap(best, window)[:max_matches], len(range(0, sub.shape[1] - window, max(1, step)))


def patch_matches_between(gray_a: np.ndarray, box_a,
                          gray_b: np.ndarray, box_b, *,
                          window: int, step: int, min_score: float,
                          max_matches: int):
    """Template-match patches from panel A against panel B."""
    ra0, ra1, ca0, ca1 = box_a
    rb0, rb1, cb0, cb1 = box_b
    sub_a = np.ascontiguousarray(gray_a[ra0:ra1, ca0:ca1], dtype=np.float32)
    sub_b = np.ascontiguousarray(gray_b[rb0:rb1, cb0:cb1], dtype=np.float32)
    if sub_a.shape[1] <= window + 2 or sub_b.shape[1] <= window + 2:
        return [], 0
    best = []
    for sx in range(0, sub_a.shape[1] - window, max(1, step)):
        template = sub_a[:, sx:sx + window]
        if template.std() < 5.0:
            continue
        result = cv2.matchTemplate(sub_b, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score >= min_score:
            best.append({
                "start_a": int(ca0 + sx),
                "start_b": int(cb0 + loc[0]),
                "window_px": int(window),
                "score": round(float(score), 6),
            })
    best.sort(key=lambda m: -m["score"])
    return dedupe_nonoverlap(best, window)[:max_matches], len(range(0, sub_a.shape[1] - window, max(1, step)))


def dedupe_nonoverlap(matches: list[dict], window: int) -> list[dict]:
    """Keep one match per copied region (source and target must not overlap)."""
    kept = []
    for match in sorted(matches, key=lambda m: -m.get("score", 0)):
        a0 = match["start_a"]
        b0 = match["start_b"]
        a1, b1 = a0 + window, b0 + window
        if any(
            (not (a1 <= k["start_a"] or a0 >= k["start_a"] + window) or
             not (b1 <= k["start_b"] or b0 >= k["start_b"] + window))
            or (abs(a0 - k["start_b"]) < window and
                abs(b0 - k["start_a"]) < window)
            for k in kept
        ):
            continue
        kept.append(match)
    return kept


def profile_matches(profiles, *, window: int, step: int, min_r: float,
                    max_matches: int):
    """Fallback: Pearson over high-passed 1D profile windows."""
    windows = []
    for label, prof in profiles:
        for start in range(0, len(prof) - window + 1, step):
            windows.append((label, start, prof[start:start + window]))
    matches = []
    tests = 0
    for i in range(len(windows)):
        la, sa, wa = windows[i]
        for j in range(i + 1, len(windows)):
            lb, sb, wb = windows[j]
            if la == lb and abs(sa - sb) < window:
                continue
            tests += 1
            r = pearson(wa, wb)
            if r is None or r < min_r:
                continue
            matches.append({
                "panel_a": la, "panel_b": lb,
                "start_a": int(sa), "start_b": int(sb),
                "window": int(window), "r": round(float(r), 6),
                "p": fisher_p(r, window),
            })
    qs = bh_qvalues([m["p"] for m in matches])
    for m, q in zip(matches, qs):
        m["q"] = q
        m["p_bonferroni"] = min(1.0, m["p"] * max(tests, 1))
    matches.sort(key=lambda m: (-m["r"], m["p"]))
    return matches[:max_matches], tests


def draw_matches(img_path: str, box, matches, out_path: str) -> None:
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    colors = [(220, 0, 0), (0, 120, 220), (0, 150, 0), (180, 0, 180)]
    for i, match in enumerate(matches[:8]):
        color = colors[i % len(colors)]
        for start_key in ("start_a", "start_b"):
            x0 = int(match[start_key])
            x1 = x0 + int(match.get("window_px", match.get("window", 48)))
            draw.rectangle([x0, box[0], x1, box[1]], outline=color, width=2)
            label = f"score={match.get('score', match.get('r', 0)):.4f}"
            draw.text((x0 + 2, box[0] + 2), label, fill=color)
    img.save(out_path)


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--image", action="append", required=True,
                   help="line-plot panel image; repeat for two traces")
    p.add_argument("--out", help="write JSON report here")
    p.add_argument("--window-px", type=int, default=48,
                   help="patch width in pixels (default 48)")
    p.add_argument("--step", type=int, default=4,
                   help="sliding step in pixels (default 4)")
    p.add_argument("--min-score", type=float, default=0.985,
                   help="minimum normalized cross-correlation (default 0.985)")
    p.add_argument("--window", type=int, default=48,
                   help="fallback profile window in resampled points")
    p.add_argument("--min-r", type=float, default=0.99,
                   help="fallback profile Pearson threshold")
    p.add_argument("--max-matches", type=int, default=20)
    p.add_argument("--annotate", metavar="PNG",
                   help="draw the best matches on the first image")
    p.add_argument("--norm", type=int, default=320,
                   help="fallback resampled profile length")
    args = p.parse_args()

    panels = []
    for path in args.image:
        arr = to_gray_array(Path(path))
        kind, box = classify(arr)
        if kind != "line_plot" or box is None:
            print(json.dumps({
                "applicable": False,
                "reason": f"{path}: not a line plot ({kind})",
            }, ensure_ascii=False))
            return 0
        panels.append({"path": path, "label": Path(path).stem,
                       "gray": arr, "box": box})

    if len(panels) > 2:
        raise SystemExit("pass one or two --image panels")

    if cv2 is not None:
        matches = []
        n_templates = 0
        if len(panels) == 1:
            found, n_templates = patch_matches(
                panels[0]["gray"], panels[0]["box"],
                window=args.window_px, step=max(1, args.step),
                min_score=args.min_score, max_matches=args.max_matches,
            )
            for m in found:
                m.update({"panel_a": panels[0]["label"],
                          "panel_b": panels[0]["label"]})
            matches = found
        else:
            found, n_templates = patch_matches_between(
                panels[0]["gray"], panels[0]["box"],
                panels[1]["gray"], panels[1]["box"],
                window=args.window_px, step=max(1, args.step),
                min_score=args.min_score, max_matches=args.max_matches,
            )
            for m in found:
                m.update({"panel_a": panels[0]["label"],
                          "panel_b": panels[1]["label"]})
            matches = found
        method = "patch_ncc"
        method_note = (
            "Full-height patches of width --window-px are slid across each "
            "line-plot box and matched with TM_CCOEFF_NORMED. Overlapping "
            "positions are masked. A score >= --min-score is a copied-segment "
            "candidate. The method is sensitive to exact/near-exact reuse; it "
            "does not survive rotation, perspective, or strong rescaling — use "
            "image_dup_orb.py for those. Periodic fringes and repeated "
            "calibration pulses can match legitimately."
        )
        significant = matches
    else:
        profiles = []
        for panel in panels:
            prof = curve_profile(panel["gray"], panel["box"], norm=args.norm)
            profiles.append((panel["label"], highpass(prof, args.window)))
        matches, n_templates = profile_matches(
            profiles, window=args.window, step=max(1, args.step),
            min_r=args.min_r, max_matches=args.max_matches,
        )
        method = "profile_pearson"
        method_note = (
            "OpenCV is unavailable; fell back to high-passed 1D profile "
            "windows with Fisher-z p-values and Benjamini-Hochberg q-values. "
            "This is weaker than patch NCC and may miss small or re-rendered "
            "segments."
        )
        significant = matches

    report = {
        "applicable": True,
        "method": method,
        "images": [panel["path"] for panel in panels],
        "n_templates": n_templates,
        "threshold": args.min_score if method == "patch_ncc" else args.min_r,
        "significant_count": len(significant),
        "matches": matches,
        "verdict": (
            "copied_segment_candidate: a non-overlapping patch/window passed "
            "the threshold; inspect the annotated regions and raw data before "
            "grading"
            if significant else
            "no_copied_segment: no non-overlapping segment passed the "
            "threshold"
        ),
        "method_note": method_note,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    if args.annotate:
        draw_matches(panels[0]["path"], panels[0]["box"],
                     matches, args.annotate)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
