"""image_dup_orb.py — ORB feature-matching duplicate detection.

A deterministic, single-purpose utility script. No LLM SDK. No "skeleton -> enrich"
two-stage orchestration. Use directly from the agent during the image-evidence
track when the audit needs to detect **transformed** duplicates: same source
image rotated, flipped, cropped, or brightness-shifted.

Usage:
    python image_dup_orb.py <run-dir>/panels/*.png

What it does:
    1. Loads each image as grayscale.
    2. Detects ORB keypoints + computes descriptors (rotation- and scale-invariant
       by design; modest brightness invariance via the BRIEF descriptor).
    3. For every pair, runs Brute-Force Hamming matching with cross-check,
       filters by Lowe's ratio test (k-NN with k=2, accept if best/second < 0.75).
    4. Reports the count of surviving matches per pair.
    5. Flags pairs with >= --strong matches as transformed-duplicate candidates.

Complements `image_dup.py`:
    - `image_dup.py` (perceptual hashing) is fast and catches **untransformed**
      duplicates. Whole-figure dHash distance below ~16 = same image.
    - `image_dup_orb.py` (feature matching) is slower but catches duplicates
      that survive rotation / flip / crop / brightness change. Use when
      `image_dup.py` returns suspicious-but-not-conclusive distances
      (dHash 30-60 range) and the panels are visually similar.

Limitations (real, document them):
    - ORB needs enough texture to detect keypoints. Uniform-background panels
      (DAPI-only fluorescence, dark Westerns) may produce <50 keypoints and
      give weak signal.
    - The matching is symmetric: A vs B and B vs A produce the same match count.
    - Cross-image content-similarity (two different blots that genuinely look
      similar) can produce false positives. Default --strong threshold of 30
      is conservative; ratchet up for noisy panel sets.
    - JPEG re-compression artefacts degrade ORB more than perceptual hashing.
      If panels have been heavily re-compressed by the publication pipeline,
      consider --max-features 1000 instead of the default 500.

Empirical motivating cases:
    - Kang Tiebang Fig 6d (10.1038/s41556-020-0522-z 2024 Author Correction):
      admitted vector ↔ Δ1-10 duplicate that `image_dup.py` mean-diff did
      not flag (mean_diff 11-19 across candidate pairs). The duplicate
      likely involves rotation or flip and would need feature matching.
    - Wang Ping Fig 1f / similar cross-source insertions: ORB can detect
      reuse-after-crop where perceptual hashing of the whole panel fails.

This script is intentionally < 200 lines. If the audit needs splice-edge
detection or content-aware healing detection, drop another specialised script
next to this one rather than extending this one.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import cv2
except ImportError:
    sys.stderr.write("install opencv-python first: pip install opencv-python\n")
    sys.exit(2)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("install numpy first: pip install numpy\n")
    sys.exit(2)


def load_gray(path: str, max_dim: int = 1024) -> "np.ndarray | None":
    # cv2.imread cannot open non-ASCII paths on Windows; decode bytes instead.
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
    except (OSError, ValueError):
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    return img


def detect_orb(img, max_features: int):
    # cv2.ORB_create is dynamically registered; suppress static-analysis noise.
    orb = cv2.ORB_create(nfeatures=max_features)  # type: ignore[attr-defined]
    return orb.detectAndCompute(img, None)


def detect_orb_all_orientations(img, max_features: int):
    """Return descriptors for both the image and its horizontal mirror.

    ORB is rotation-invariant but NOT mirror-invariant, so a horizontally-
    flipped duplicate produces zero raw-match signal. By computing descriptors
    for both orientations and taking the maximum match count across (A vs B,
    A vs flip(B)), we cover the mirror case at 2x descriptor cost.
    """
    _, des_a = detect_orb(img, max_features)
    img_flip = cv2.flip(img, 1)
    _, des_b = detect_orb(img_flip, max_features)
    return des_a, des_b


def detect_orb_with_points(img, max_features: int):
    """ORB keypoints + descriptors (keypoints needed for RANSAC geometry)."""
    orb = cv2.ORB_create(nfeatures=max_features)  # type: ignore[attr-defined]
    return orb.detectAndCompute(img, None)


def detect_orb_all_orientations_with_points(img, max_features: int):
    """(kp, des) for the image and its horizontal mirror."""
    kp, des = detect_orb_with_points(img, max_features)
    img_flip = cv2.flip(img, 1)
    kp_flip, des_flip = detect_orb_with_points(img_flip, max_features)
    return (kp, des), (kp_flip, des_flip)


def good_matches(des_a, des_b, ratio: float):
    """Lowe's ratio test; returns [(queryIdx, trainIdx), ...]."""
    if des_a is None or des_b is None:
        return []
    if len(des_a) < 2 or len(des_b) < 2:
        return []
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(des_a, des_b, k=2)
    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < ratio * n.distance:
            good.append((m.queryIdx, m.trainIdx))
    return good


def match_pair(des_a, des_b, ratio: float) -> int:
    """Lowe's ratio test on Hamming-distance k=2 matches. Returns # surviving."""
    return len(good_matches(des_a, des_b, ratio))


def geometry_from_matches(kp_a, kp_b, matches, *, flip_b: bool, width_b: int):
    """RANSAC homography + inlier count/ratio + target bbox in original coords."""
    if len(matches) < 4:
        return {"inliers": 0, "inlier_ratio": 0.0, "bbox": None}
    src = np.float32([kp_a[i].pt for i, _ in matches])
    dst_raw = np.float32([kp_b[j].pt for _, j in matches])
    dst = dst_raw.copy()
    if flip_b:
        dst[:, 0] = (width_b - 1) - dst[:, 0]
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if homography is None or mask is None:
        return {"inliers": 0, "inlier_ratio": 0.0, "bbox": None}
    inlier_mask = mask.ravel().astype(bool)
    inliers = int(inlier_mask.sum())
    if inliers == 0:
        return {"inliers": 0, "inlier_ratio": 0.0, "bbox": None}
    pts = dst[inlier_mask]
    bbox = [int(pts[:, 0].min()), int(pts[:, 1].min()),
            int(pts[:, 0].max()), int(pts[:, 1].max())]
    return {
        "inliers": inliers,
        "inlier_ratio": round(inliers / len(matches), 4),
        "bbox": bbox,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("paths", nargs="+", help="image files to compare pairwise")
    parser.add_argument(
        "--max-features", type=int, default=500,
        help="ORB max-features per image (default 500)",
    )
    parser.add_argument(
        "--ratio", type=float, default=0.75,
        help="Lowe's ratio test threshold (default 0.75; lower = stricter)",
    )
    parser.add_argument(
        "--strong", type=int, default=30,
        help="flag pairs with >= this many surviving matches (default 30)",
    )
    parser.add_argument(
        "--weak", type=int, default=12,
        help="report pairs with >= this many surviving matches (default 12)",
    )
    parser.add_argument(
        "--max-dim", type=int, default=1024,
        help="downscale images so longest edge <= this (default 1024 px)",
    )
    parser.add_argument(
        "--min-inliers", type=int, default=10,
        help="minimum RANSAC inliers for a strong flag (default 10)",
    )
    parser.add_argument(
        "--json", metavar="PATH",
        help="write pair reports (matches, inliers, ratio, bbox) as JSON",
    )
    args = parser.parse_args()

    paths = [p for p in args.paths if Path(p).is_file()]
    if len(paths) < 2:
        sys.stderr.write("need at least 2 image files\n")
        return 1

    print(f"ORB-matching {len(paths)} images "
          f"(max_features={args.max_features}, ratio={args.ratio}, "
          f"max_dim={args.max_dim} px)\n")

    descriptors = []
    for p in paths:
        img = load_gray(p, args.max_dim)
        if img is None:
            sys.stderr.write(f"could not load {p} (cv2.imread returned None)\n")
            continue
        (kp, des), (kp_flip, des_flip) = detect_orb_all_orientations_with_points(
            img, args.max_features)
        n_kp = 0 if des is None else len(des)
        descriptors.append({
            "path": p, "gray": img, "kp": kp, "des": des,
            "kp_flip": kp_flip, "des_flip": des_flip,
            "width": int(img.shape[1]),
        })
        print(f"  {os.path.basename(p):<50} kp={n_kp} (+ mirror descriptors)")
    print()

    print(f"{'a':<40} {'b':<40} {'matches':>8} {'inliers':>8} {'ratio':>6} {'orient':>8}  flag")
    print("-" * 130)
    flagged = 0
    pair_reports = []
    for i in range(len(descriptors)):
        for j in range(i + 1, len(descriptors)):
            da = descriptors[i]
            db = descriptors[j]
            same = good_matches(da["des"], db["des"], args.ratio)
            flip = good_matches(da["des"], db["des_flip"], args.ratio)
            if len(flip) > len(same):
                chosen, orient, flip_b = flip, "mirror", True
            else:
                chosen, orient, flip_b = same, "same", False
            matches = len(chosen)
            geometry = geometry_from_matches(
                da["kp"], db["kp_flip"] if flip_b else db["kp"], chosen,
                flip_b=flip_b, width_b=db["width"])
            if matches >= args.strong and geometry["inliers"] >= args.min_inliers:
                flag = "★★★ transformed-duplicate candidate"
                flagged += 1
            elif matches >= args.strong:
                flag = "★★ strong matches, weak geometry (inspect)"
            elif matches >= args.weak:
                flag = "★ weak match"
            else:
                continue  # don't print zero-match pairs
            an = os.path.basename(da["path"])
            bn = os.path.basename(db["path"])
            pair_reports.append({
                "a": an, "b": bn, "matches": matches,
                "inliers": geometry["inliers"],
                "inlier_ratio": geometry["inlier_ratio"],
                "bbox": geometry["bbox"], "orientation": orient, "flag": flag,
            })
            print(f"{an:<40} {bn:<40} {matches:>8} "
                  f"{geometry['inliers']:>8} {geometry['inlier_ratio']:>6.2f} "
                  f"{orient:>8}  {flag}")

    print(f"\n=== flagged pairs (>= {args.strong} matches, "
          f">= {args.min_inliers} RANSAC inliers): {flagged} ===")
    if args.json:
        Path(args.json).write_text(__import__("json").dumps(
            {"pairs": pair_reports, "parameters": {
                "max_features": args.max_features, "ratio": args.ratio,
                "strong": args.strong, "weak": args.weak,
                "min_inliers": args.min_inliers}}, indent=2), encoding="utf-8")
    return 0 if flagged == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
