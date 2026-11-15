#!/usr/bin/env python3
"""corpus_match.py — compare figures/panels against a local reference corpus.

Retraction notices often say a figure was “first published in ref. 1”. That
is a cross-publication claim; the pipeline needs a local corpus of manually
exported reference figures. `corpus_add.py` registers entries, this script
matches a query figure/panel directory against all of them.

It reports two independent cues:

* dHash Hamming distance — cheap, catches untransformed whole-figure reuse;
* ORB + Lowe ratio + RANSAC — catches cropped / rescaled / mirrored reuse.

A hit is a lead, not a verdict: the same phase, instrument screenshot, or a
legitimately reproduced schematic can match. Inspect the bbox and read the
reference legend before grading.

Usage:
    corpus_match.py --query run/panels --corpus corpus --json matches.json
    corpus_match.py --query run/figures_pmc --corpus corpus --md matches.md

No network access. No scraping. Python 3.8+; needs Pillow, NumPy, OpenCV.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image  # noqa: F401  (imported for the dHash helper)
except ImportError as exc:
    sys.stderr.write(f"missing dependency: {exc}\n")
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from image_dup import dhash, hamming  # noqa: E402
from image_dup_orb import (  # noqa: E402
    detect_orb_all_orientations_with_points,
    geometry_from_matches,
    good_matches,
    load_gray,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def images_in(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def load_corpus(root: Path):
    """Return [{key, doi, title, meta, path, dhash, orb}] for every entry."""
    entries = []
    if not root.is_dir():
        return entries
    meta_files = sorted(root.glob("*/meta.json"))
    seen = set()
    for meta_path in meta_files:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry_dir = meta_path.parent
        key = meta.get("key") or entry_dir.name
        for item in meta.get("figures", []):
            path = (entry_dir / item["file"]).resolve()
            if path.exists():
                entries.append({"key": key, "doi": meta.get("doi", ""),
                                "title": meta.get("title", ""),
                                "meta": meta, "path": path})
                seen.add(path)
    # Loose images under the corpus (no meta.json) are still usable.
    for path in images_in(root):
        if path in seen or path.name == "meta.json":
            continue
        entries.append({"key": path.parent.name, "doi": "", "title": "",
                        "meta": {}, "path": path})
    return entries


def describe(entry, max_dim: int, max_features: int):
    img = load_gray(str(entry["path"]), max_dim)
    if img is None:
        return None
    (kp, des), (kp_flip, des_flip) = detect_orb_all_orientations_with_points(
        img, max_features)
    return {
        **entry,
        "image": img,
        "kp": kp,
        "des": des,
        "kp_flip": kp_flip,
        "des_flip": des_flip,
        "dhash": dhash(str(entry["path"])),
    }


def compare(query, reference, *, ratio: float, min_inliers: int,
            strong: int, weak: int):
    raw = good_matches(query["des"], reference["des"], ratio)
    mirror = good_matches(query["des"], reference["des_flip"], ratio)
    flipped = len(mirror) > len(raw)
    matches = mirror if flipped else raw
    width = reference["image"].shape[1]
    geo = geometry_from_matches(
        query["kp"], reference["kp_flip"] if flipped else reference["kp"],
        matches, flip_b=flipped, width_b=width)
    distance = hamming(query["dhash"], reference["dhash"])
    is_strong = (geo["inliers"] >= min_inliers and len(matches) >= strong) \
        or distance < 12
    is_weak = len(matches) >= weak or distance < 28
    if is_strong:
        flag = "★★★ cross-paper reuse candidate"
    elif is_weak:
        flag = "★ weak match"
    else:
        flag = ""
    return {
        "query": str(query["path"]),
        "reference": str(reference["path"]),
        "key": reference["key"],
        "doi": reference.get("doi", ""),
        "title": reference.get("title", ""),
        "dhash": int(distance),
        "matches": len(matches),
        "inliers": geo["inliers"],
        "inlier_ratio": geo["inlier_ratio"],
        "bbox": geo["bbox"],
        "orientation": "mirror" if flipped else "same",
        "flag": flag,
        "strong": bool(is_strong),
        "weak": bool(is_weak),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--query", required=True,
                    help="query image or directory (recursive)")
    ap.add_argument("--corpus", required=True, help="corpus root")
    ap.add_argument("--json", metavar="PATH", help="write full JSON report")
    ap.add_argument("--md", metavar="PATH", help="write a markdown table")
    ap.add_argument("--max-features", type=int, default=500)
    ap.add_argument("--max-dim", type=int, default=1200)
    ap.add_argument("--ratio", type=float, default=0.75)
    ap.add_argument("--strong", type=int, default=30,
                    help="minimum ORB matches for a strong flag")
    ap.add_argument("--weak", type=int, default=12)
    ap.add_argument("--min-inliers", type=int, default=12,
                    help="minimum RANSAC inliers for a strong flag")
    ap.add_argument("--max-candidates", type=int, default=200)
    args = ap.parse_args()

    query_path = Path(args.query).expanduser().resolve()
    corpus_root = Path(args.corpus).expanduser().resolve()
    queries = images_in(query_path)
    if not queries:
        sys.stderr.write(f"no images under {query_path}\n")
        return 2
    entries = load_corpus(corpus_root)
    if not entries:
        sys.stderr.write(f"empty corpus: {corpus_root}\n")
        return 2

    refs = []
    for entry in entries:
        try:
            described = describe(entry, args.max_dim, args.max_features)
        except Exception as exc:  # unreadable image should not kill the run
            sys.stderr.write(f"skip {entry['path']}: {exc}\n")
            continue
        if described is not None:
            refs.append(described)

    candidates = []
    skipped_self = 0
    for qpath in queries:
        if not qpath.is_file():
            continue
        if any(qpath.resolve() == r["path"] for r in refs):
            skipped_self += 1
            continue
        try:
            qimg = load_gray(str(qpath), args.max_dim)
            if qimg is None:
                continue
            (qkp, qdes), (qkp_flip, qdes_flip) = \
                detect_orb_all_orientations_with_points(
                    qimg, args.max_features)
            query = {"path": qpath, "image": qimg, "kp": qkp, "des": qdes,
                     "kp_flip": qkp_flip, "des_flip": qdes_flip,
                     "dhash": dhash(str(qpath))}
        except Exception as exc:
            sys.stderr.write(f"skip query {qpath}: {exc}\n")
            continue
        for ref in refs:
            result = compare(query, ref, ratio=args.ratio,
                             min_inliers=args.min_inliers,
                             strong=args.strong, weak=args.weak)
            if result["weak"]:
                candidates.append(result)

    candidates.sort(key=lambda c: (-c["inliers"], -c["matches"], c["dhash"]))
    candidates = candidates[:args.max_candidates]
    report = {
        "query": str(query_path),
        "corpus": str(corpus_root),
        "queries": len(queries),
        "references": len(refs),
        "skipped_self": skipped_self,
        "thresholds": {
            "max_features": args.max_features,
            "max_dim": args.max_dim,
            "ratio": args.ratio,
            "strong_matches": args.strong,
            "weak_matches": args.weak,
            "min_inliers": args.min_inliers,
        },
        "strong_count": sum(1 for c in candidates if c["strong"]),
        "candidates": candidates,
        "method_note": (
            "ORB+Lowe+RANSAC plus dHash. A hit means the same pixels/feature "
            "geometry recur; inspect the bbox, the reference legend, and the "
            "experimental description before grading. Same-phase spectra and "
            "legitimately reproduced schematics can match."
        ),
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
    if args.md:
        lines = ["| query | reference | dHash | ORB matches | inliers | "
                 "ratio | flag |", "|---|---|---|---|---|---|---|"]
        for c in candidates:
            lines.append(
                f"| {Path(c['query']).name} | {Path(c['reference']).name} "
                f"| {c['dhash']} | {c['matches']} | {c['inliers']} "
                f"| {c['inlier_ratio']:.2f} | {c['flag']} |")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(queries), "references": len(refs),
                      "candidates": len(candidates),
                      "strong": report["strong_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
