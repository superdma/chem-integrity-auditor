#!/usr/bin/env python3
"""run_paper.py — deterministic evidence sweep for one gold-set paper.

Usage:
    python3 tests/gold/run_paper.py \
        --workdir gold/raw/PMC10015629 \
        --output gold/runs/PMC10015629 \
        --skill .

Runs the deterministic tracks only (ledger, numeric, NMR/HRMS, panel split,
phash, ORB within each figure, segment duplication, fingerprint for small
figures). The agent still has to read the notice, inspect the candidates, and
write the graded report; this script just makes the evidence reproducible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], log: Path, timeout: int = 600) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        try:
            return subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            handle.write("\nTIMEOUT\n")
            return 124


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--workdir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--skill", default=".", help="repository root")
    args = p.parse_args()

    work = Path(args.workdir).resolve()
    out = Path(args.output).resolve()
    skill = Path(args.skill).resolve()
    scripts = skill / "scripts"
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"workdir": str(work), "output": str(out), "figures": {}}

    ledger = out / "evidence_ledger.json"
    run([sys.executable, str(scripts / "build_evidence_ledger.py"),
         str(work), "--output", str(ledger)], out / "ledger.log")
    summary["ledger"] = load_json(ledger)

    chem = out / "chem_numeric.json"
    run([sys.executable, str(scripts / "chem_numeric.py"),
         str(work), "--output", str(chem)], out / "chem_numeric.log")
    summary["chem_numeric"] = load_json(chem)

    nmr = out / "nmr_hrms.json"
    run([sys.executable, str(scripts / "nmr_hrms_numeric.py"),
         str(work), "--output", str(nmr)], out / "nmr_hrms.log")
    summary["nmr_hrms"] = load_json(nmr)

    forensics = out / "numeric_forensics.json"
    run([sys.executable, str(scripts / "numeric_forensics.py"),
         str(work), "--output", str(forensics)], out / "numeric_forensics.log")
    summary["numeric_forensics"] = load_json(forensics)

    fig_dir = work / "figures_pmc"
    panels_root = out / "panels"
    all_panels = []
    for fig in sorted(fig_dir.glob("*.jpg")):
        stem = fig.stem
        fig_out = panels_root / stem
        fig_json = panels_root / f"{stem}.json"
        run([sys.executable, str(scripts / "panel_split.py"),
             str(fig), str(fig_out), "--json", str(fig_json),
             "--debug", str(panels_root / f"{stem}_debug.png")],
            out / f"panel_{stem}.log")
        data = load_json(fig_json) or {}
        panels = [Path(item["path"]) for item in data.get("panels", [])
                  if Path(item["path"]).exists()]
        all_panels.extend(panels)

        # Stacked traces (Raman/XRD/XPS) sit inside one panel with black
        # dividers. Split them and colour-isolate each trace so the pairwise
        # tools compare curves instead of legends; otherwise the between-trace
        # duplication that notices often cite is invisible to dHash/ORB.
        bands: list[Path] = []
        stack_map: dict[str, list[str]] = {}
        for panel in panels:
            band_dir = out / "stacks" / stem / panel.stem
            run([sys.executable, str(scripts / "stack_split.py"),
                 str(panel), str(band_dir), "--keep-color", "auto",
                 "--min-size", "30"], out / f"stack_{stem}_{panel.stem}.log",
                timeout=120)
            found = sorted(band_dir.glob("*.png"))
            if len(found) >= 2:
                stack_map[panel.name] = [str(x) for x in found]
                bands.extend(found)
        analysis = bands + panels

        def related(a: Path, b: Path) -> bool:
            """True when one image is a crop of the other (a band vs its panel).

            Comparing a band with its own parent always yields a duplicate and
            would be reported as a false hit, so those pairs are skipped.
            """
            return (a.stem.startswith(b.stem + "_band_")
                    or b.stem.startswith(a.stem + "_band_"))

        figure = {"image": str(fig), "panel_count": len(panels),
                  "panels": [str(x) for x in panels],
                  "stack_bands": stack_map,
                  "analysis_count": len(analysis),
                  "analysis_images": [str(x) for x in analysis]}
        if panels:
            # Compare panels among themselves and bands among themselves; a
            # band is never compared with the panel it was cut from.
            groups = [g for g in (bands, panels) if len(g) >= 2]
            phash_chunks = []
            for gi, group in enumerate(groups):
                log = out / f"phash_{stem}_{gi}.log"
                run([sys.executable, str(scripts / "image_dup.py")]
                    + [str(x) for x in group], log)
                phash_chunks.append(log.read_text(encoding="utf-8",
                                                  errors="replace")[-4000:])
            figure["phash"] = "\n".join(phash_chunks)
            orb_pairs = []
            for gi, group in enumerate(groups):
                orb_json = out / f"orb_{stem}_{gi}.json"
                run([sys.executable, str(scripts / "image_dup_orb.py")]
                    + [str(x) for x in group]
                    + ["--json", str(orb_json), "--max-features", "400",
                       "--max-dim", "800"], out / f"orb_{stem}_{gi}.log")
                orb_pairs.extend((load_json(orb_json) or {}).get("pairs", []))
            figure["orb"] = {"pairs": orb_pairs}
            # Segment scan is cheap and works on a single panel. Bands come
            # first: a copied stretch is more visible in an isolated trace.
            segment = {}
            for panel in analysis[:16]:
                seg_json = out / f"segment_{stem}_{panel.stem}.json"
                run([sys.executable, str(scripts / "spectral_segment_dup.py"),
                     "--image", str(panel), "--out", str(seg_json),
                     "--window-px", "40", "--step", "6"],
                    out / f"segment_{stem}_{panel.stem}.log", timeout=120)
                seg = load_json(seg_json)
                if seg and seg.get("applicable"):
                    segment[panel.name] = {
                        "significant_count": seg.get("significant_count"),
                        "best": (seg.get("matches") or [{}])[0],
                    }
            figure["segment"] = segment
            # Fingerprint only for small figures; O(n^2) and slow otherwise.
            if 2 <= len(analysis) <= 8:
                fp = {}
                for i in range(len(analysis)):
                    for j in range(i + 1, len(analysis)):
                        if related(analysis[i], analysis[j]):
                            continue
                        fp_json = out / f"fp_{stem}_{i}_{j}.json"
                        run([sys.executable,
                             str(scripts / "spectral_noise_fingerprint.py"),
                             str(analysis[i]), str(analysis[j]),
                             "--out", str(fp_json)],
                            out / f"fp_{stem}_{i}_{j}.log", timeout=120)
                        data = load_json(fp_json)
                        if data and data.get("applicable"):
                            fp[f"{analysis[i].name}|{analysis[j].name}"] = {
                                "curve_r": data.get("curve_r"),
                                "noise_corr": data.get("noise_corr"),
                                "bg_line_corr": data.get("bg_line_corr"),
                                "verdict": data.get("verdict"),
                            }
                figure["fingerprint"] = fp
        summary["figures"][stem] = figure

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(out),
        "figures": len(summary["figures"]),
        "panels": len(all_panels),
        "numeric_findings": (summary.get("chem_numeric") or {}).get("findings_count"),
        "nmr_findings": (summary.get("nmr_hrms") or {}).get("findings_count"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
