#!/usr/bin/env python3
"""summarize_run.py — condense one gold-run summary.json into review candidates.

Usage:
    python3 tests/gold/summarize_run.py gold/runs/PMC12169214

Prints, per figure, only the evidence an auditor should actually look at:
strong ORB pairs, fingerprint pairs with high curve/noise correlation, and
panels where the segment scan found a copied stretch. Raw JSON stays the
source of truth; this is a triage view.
"""

from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", help="gold run directory containing summary.json")
    args = ap.parse_args()
    summary = json.loads((pathlib.Path(args.run) / "summary.json").read_text(
        encoding="utf-8"))
    print(f"# {pathlib.Path(args.run).name}")
    for fig, data in summary.get("figures", {}).items():
        pairs = (data.get("orb") or {}).get("pairs", [])
        strong = [p for p in pairs if "★★★" in p.get("flag", "")]
        fp = data.get("fingerprint") or {}
        fp_hits = {k: v for k, v in fp.items()
                   if (v.get("curve_r") or 0) >= 0.80
                   or (v.get("noise_corr") or 0) >= 0.55}
        seg = {k: v for k, v in (data.get("segment") or {}).items()
               if v.get("significant_count")}
        if not (strong or fp_hits or seg):
            continue
        print(f"\n## {fig}  panels={data.get('panel_count')} "
              f"bands={sum(len(v) for v in (data.get('stack_bands') or {}).values())}")
        for p in strong:
            print(f"- ORB {p['matches']} matches / {p['inliers']} inliers "
                  f"({p['inlier_ratio']:.2f}) {p['orientation']}: "
                  f"{pathlib.Path(p['a']).name} ↔ {pathlib.Path(p['b']).name}")
        for key, value in fp_hits.items():
            print(f"- FP curve_r={value.get('curve_r'):.2f} "
                  f"noise={value.get('noise_corr'):.2f}: {key}")
        for key, value in seg.items():
            best = value.get("best") or {}
            print(f"- SEG n={value.get('significant_count')} "
                  f"score={best.get('score')} {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
