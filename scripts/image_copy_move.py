#!/usr/bin/env python3
"""image_copy_move.py — find duplicated regions inside one image.

Pairwise tools (``image_dup.py`` / ``image_dup_orb.py``) compare different
panels. This script answers the other question: does one panel contain a region
pasted somewhere else in the *same* panel? That is the classic copy-move
signature in gels, microscopy plates, photographs and figure panels.

Method:
    1. ORB keypoints + descriptors on the grayscale image.
    2. Self-matching with Lowe's ratio test, excluding near-identical positions.
    3. RANSAC homography (and affine fallback) to keep only geometrically
       consistent match clusters.
    4. Report the source/target bounding boxes, displacement, inlier count and
       reprojection residual. Repeat on the remaining matches to find more than
       one copied region.

Usage:
    python3 scripts/image_copy_move.py panel.png --out copy_move.json
    python3 scripts/image_copy_move.py panel.png --annotate marked.png
    python3 scripts/image_copy_move.py panel.png --min-inliers 14 --json

This is a screening lead, not a verdict. A repeated calibration mark, a
legitimately repeated scale bar, a tiled background or a symmetric object can
produce a geometric match. Confirm the region visually and request the
uncropped original before grading it.

Dependencies: OpenCV + NumPy (same as ``image_dup_orb.py``). Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - dependency path
    sys.stderr.write("install opencv-python-headless first\n")
    raise SystemExit(2)
try:
    import numpy as np
except ImportError:  # pragma: no cover - dependency path
    sys.stderr.write("install numpy first\n")
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from image_dup_orb import detect_orb_with_points, load_gray  # noqa: E402


def self_matches(des, ratio: float):
    """Ratio test against the same descriptor set, excluding self-matches.

    The usual k=2 ratio test fails for an exact copy: the nearest and second
    nearest descriptors are both distance 0 (the keypoint itself and its copy),
    so ``best < ratio * second`` is false. Ask for k=3 and drop the self-match
    before applying the ratio.
    """
    if des is None or len(des) < 3:
        return []
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(des, des, k=3)
    out = []
    for neighbours in knn:
        candidates = [m for m in neighbours if m.queryIdx != m.trainIdx]
        if not candidates:
            continue
        best = candidates[0]
        if len(candidates) >= 2 and best.distance < ratio * candidates[1].distance:
            out.append((best.queryIdx, best.trainIdx))
        elif len(candidates) == 1 and best.distance <= 32:
            out.append((best.queryIdx, best.trainIdx))
    return out


def bbox(points: np.ndarray) -> list[int]:
    return [int(points[:, 0].min()), int(points[:, 1].min()),
            int(points[:, 0].max()), int(points[:, 1].max())]


def bbox_area(box: list[int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def iou(a: list[int], b: list[int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union else 0.0


def _fit(src: np.ndarray, dst: np.ndarray):
    """Return (model, mask, kind, projected source points)."""
    candidates = []
    homography, hmask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if homography is not None and hmask is not None:
        projected = cv2.perspectiveTransform(
            src.reshape(-1, 1, 2), homography).reshape(-1, 2)
        candidates.append((int(hmask.ravel().sum()), homography, hmask,
                           "homography", projected))
    affine, amask = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    if affine is not None and amask is not None:
        projected = cv2.transform(src.reshape(-1, 1, 2), affine).reshape(-1, 2)
        candidates.append((int(amask.ravel().sum()), affine, amask,
                           "affine", projected))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def verify_region(img: np.ndarray, model, kind: str,
                  box: list[int]) -> tuple[float | None, float | None]:
    """Warp the target back onto the source and compare the pixels.

    ORB matching alone also fires on repeated axes, labels and similar-looking
    panels. A genuine copy-move survives this check: after the geometric
    transform, the copied region is nearly pixel-identical.
    """
    height, width = img.shape[:2]
    try:
        if kind == "homography":
            inverse = np.linalg.inv(model)
            warped = cv2.warpPerspective(img, inverse, (width, height))
        else:
            inverse = cv2.invertAffineTransform(model)
            warped = cv2.warpAffine(img, inverse, (width, height))
    except (cv2.error, np.linalg.LinAlgError):
        return None, None
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None, None
    a = img[y0:y1, x0:x1].astype(np.float32).ravel()
    b = warped[y0:y1, x0:x1].astype(np.float32).ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return None, None
    ncc = float(np.corrcoef(a, b)[0, 1])
    mad = float(np.mean(np.abs(a - b)))
    return ncc, mad


def detect_regions(img: np.ndarray, *, max_features: int = 2000,
                   ratio: float = 0.75, min_inliers: int = 12,
                   min_source_distance: float = 10.0,
                   min_area_frac: float = 0.002,
                   max_regions: int = 5,
                   min_ncc: float = 0.90,
                   max_mad: float = 18.0) -> list[dict]:
    kp, des = detect_orb_with_points(img, max_features)
    if des is None or len(kp) < min_inliers * 2:
        return []

    matches = self_matches(des, ratio)
    filtered = []
    for query, train in matches:
        if query == train:
            continue
        p = np.array(kp[query].pt)
        q = np.array(kp[train].pt)
        if np.linalg.norm(p - q) >= min_source_distance:
            filtered.append((query, train))
    if len(filtered) < min_inliers:
        return []

    height, width = img.shape[:2]
    image_area = float(height * width)
    regions = []
    remaining = list(filtered)

    for _ in range(max_regions):
        if len(remaining) < min_inliers:
            break
        src = np.float32([kp[i].pt for i, _ in remaining])
        dst = np.float32([kp[j].pt for _, j in remaining])
        fitted = _fit(src, dst)
        if fitted is None:
            break
        count, model, mask, kind, projected = fitted
        inlier_mask = mask.ravel().astype(bool)
        if count < min_inliers:
            break

        inlier_src = src[inlier_mask]
        inlier_dst = dst[inlier_mask]
        projected_in = projected[inlier_mask]
        residual = float(np.linalg.norm(projected_in - inlier_dst, axis=1).mean())
        displacement = inlier_dst.mean(axis=0) - inlier_src.mean(axis=0)

        src_box = bbox(inlier_src)
        dst_box = bbox(inlier_dst)
        area = min(bbox_area(src_box), bbox_area(dst_box))
        if area < min_area_frac * image_area:
            break
        width_box = src_box[2] - src_box[0]
        height_box = src_box[3] - src_box[1]
        if min(width_box, height_box) < 20:
            break
        if max(width_box, height_box) / max(1, min(width_box, height_box)) > 6.0:
            break
        hull = cv2.convexHull(inlier_src.astype(np.int32))
        fill = cv2.contourArea(hull) / max(1, bbox_area(src_box))
        if fill < 0.08:
            remaining = [(i, j) for (i, j), keep in
                         zip(remaining, ~inlier_mask) if keep]
            continue
        ncc, mad = verify_region(img, model, kind, src_box)
        if ncc is None or ncc < min_ncc or mad is None or mad > max_mad:
            remaining = [(i, j) for (i, j), keep in
                         zip(remaining, ~inlier_mask) if keep]
            continue
        if iou(src_box, dst_box) > 0.30:
            # Same region, not a moved copy.
            src, dst = src[~inlier_mask], dst[~inlier_mask]
            remaining = [(i, j) for (i, j), keep in zip(remaining, ~inlier_mask) if keep]
            continue
        if any((iou(src_box, item["source_bbox"]) > 0.30 or
                iou(dst_box, item["target_bbox"]) > 0.30) or
               (iou(src_box, item["target_bbox"]) > 0.30 and
                iou(dst_box, item["source_bbox"]) > 0.30) for item in regions):
            src, dst = src[~inlier_mask], dst[~inlier_mask]
            remaining = [(i, j) for (i, j), keep in zip(remaining, ~inlier_mask) if keep]
            continue

        regions.append({
            "source_bbox": src_box,
            "target_bbox": dst_box,
            "source_center": [round(float(v), 1) for v in inlier_src.mean(axis=0)],
            "target_center": [round(float(v), 1) for v in inlier_dst.mean(axis=0)],
            "displacement": [round(float(displacement[0]), 1),
                             round(float(displacement[1]), 1)],
            "inliers": int(count),
            "inlier_ratio": round(float(count) / len(remaining), 4),
            "model": kind,
            "mean_residual_px": round(residual, 2),
            "ncc": round(ncc, 4),
            "mean_abs_diff": round(mad, 2),
            "inlier_fill": round(fill, 4),
            "area_px": int(area),
            "source_area_frac": round(bbox_area(src_box) / image_area, 5),
            "target_area_frac": round(bbox_area(dst_box) / image_area, 5),
        })
        remaining = [(i, j) for (i, j), keep in zip(remaining, ~inlier_mask) if keep]

    return regions


def annotate(path: Path, regions: list[dict], out_path: Path,
             scale: float) -> None:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                         cv2.IMREAD_COLOR)
    if image is None:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not load {path}")
    original_width = image.shape[1]
    if scale != 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
    for index, region in enumerate(regions, start=1):
        s = region["source_bbox"]
        t = region["target_bbox"]
        cv2.rectangle(image, (s[0], s[1]), (s[2], s[3]), (40, 160, 40), 3)
        cv2.rectangle(image, (t[0], t[1]), (t[2], t[3]), (30, 30, 220), 3)
        cv2.line(image, tuple(s[:2]), tuple(t[:2]), (30, 30, 220), 2)
        cv2.putText(image, f"copy {index}", (s[0], max(18, s[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 160, 40), 2,
                    cv2.LINE_AA)
    # Keep the original size in the annotation; rescale boxes back.
    if scale != 1.0:
        image = cv2.resize(image, (original_width,
                                   int(round(image.shape[0] / scale))),
                           interpolation=cv2.INTER_AREA)
        for region in regions:
            for key in ("source_bbox", "target_bbox"):
                region[key] = [int(round(v / scale)) for v in region[key]]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(out_path.suffix or ".png", image)
    if not ok:
        raise RuntimeError("could not encode annotation")
    encoded.tofile(str(out_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect copy-move regions inside one image with ORB + RANSAC.")
    parser.add_argument("image", help="image file to screen")
    parser.add_argument("--out", help="write JSON report path")
    parser.add_argument("--annotate", metavar="PATH",
                        help="write an annotated PNG with source/target boxes")
    parser.add_argument("--max-features", type=int, default=2000)
    parser.add_argument("--ratio", type=float, default=0.75)
    parser.add_argument("--min-inliers", type=int, default=12)
    parser.add_argument("--min-distance", type=float, default=10.0,
                        help="ignore matches closer than this in pixels")
    parser.add_argument("--min-area-frac", type=float, default=0.002,
                        help="minimum copied-region area as a fraction of the image")
    parser.add_argument("--max-regions", type=int, default=5)
    parser.add_argument("--min-ncc", type=float, default=0.90,
                        help="pixel NCC after warping (default 0.90)")
    parser.add_argument("--max-mad", type=float, default=18.0,
                        help="mean absolute pixel difference after warping (default 18)")
    parser.add_argument("--max-dim", type=int, default=1600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.image).expanduser()
    if not path.is_file():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    img = load_gray(str(path), args.max_dim)
    if img is None:
        print(f"could not load image: {path}", file=sys.stderr)
        return 1
    original = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                            cv2.IMREAD_GRAYSCALE)
    if original is None:
        original = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    scale = (max(img.shape[:2]) / max(1, max(original.shape[:2]))
             if original is not None else 1.0)
    regions = detect_regions(
        img, max_features=args.max_features, ratio=args.ratio,
        min_inliers=args.min_inliers,
        min_source_distance=args.min_distance,
        min_area_frac=args.min_area_frac,
        max_regions=args.max_regions,
        min_ncc=args.min_ncc, max_mad=args.max_mad)

    payload = {
        "tool": "image-copy-move",
        "image": str(path),
        "image_size": [int(img.shape[1]), int(img.shape[0])],
        "scale": round(scale, 4),
        "regions": regions,
        "note": "Screening lead only; confirm visually and request the original.",
    }
    if args.out:
        output = Path(args.out).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    if args.annotate:
        annotate(path, regions, Path(args.annotate).expanduser(), scale)

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
