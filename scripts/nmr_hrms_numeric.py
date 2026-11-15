#!/usr/bin/env python3
"""nmr_hrms_numeric.py — deterministic NMR / HRMS isotope checks.

Complements `chem_numeric.py` (yields, CHN, HRMS exact mass, Scherrer).
This script reads `full.md` and checks:

  1H NMR
    - integration values that are not near an integer or half-integer
      (0.5 H is allowed for exchangeable protons);
    - sum of integrals vs the H count of a formula stated on the same line
      or immediately above (soft: integrals may be normalized/partial).
  13C NMR
    - number of reported signals vs the formula carbon count (hard when
      signals > C count after removing common solvent peaks);
    - impossible chemical shifts (> 250 ppm or < -10 ppm);
    - duplicate shifts (soft: typo or unresolved overlap).
  HRMS
    - negative RDBE (rings + double bonds) from the formula;
    - nitrogen-rule parity inconsistency;
    - reported M+1 / M+2 isotope intensities vs the theoretical pattern
      computed from natural abundances (soft).

Every finding carries a markdown line and the raw text. Findings are leads,
not verdicts: exchangeable protons, paramagnetic shifts, solvent peaks,
isotope-labelled compounds, and normalization choices are benign
explanations that must be tested before grading.

Usage:
    python3 nmr_hrms_numeric.py <workdir> --output <workdir>/nmr_hrms.json

Stdlib only. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

FORMULA_RE = re.compile(r"\b(?:C\d{1,3})(?:H\d{1,3})?(?:[A-Z][a-z]?\d{0,3})*\b")
NMR_RE = re.compile(r"\b(1H|13C)\s*NMR\b", re.I)
SHIFT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)")
INTEGRAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*H\b", re.I)
ISOTOPE_RE = re.compile(r"M\s*\+\s*([12])\s*[:\-=]?\s*(\d+(?:\.\d+)?)\s*%", re.I)

# Common NMR solvent signals; excluded from "signals > C count".
SOLVENT_SHIFTS = {
    "1H": [7.26, 2.50, 3.31, 4.79, 1.94, 2.05, 2.09, 3.58],
    "13C": [77.0, 77.2, 77.4, 39.5, 49.0, 49.3, 206.0, 118.0, 1.3, 2.0],
}

ELEMENT_MASS = {
    "H": 1, "C": 12, "N": 14, "O": 16, "F": 19, "P": 31, "S": 32,
    "Cl": 35, "Br": 79, "I": 127, "Si": 28, "B": 11, "Na": 23, "K": 39,
    "Li": 7, "Mg": 24, "Ca": 40, "Fe": 56, "Zn": 65, "Cu": 63, "Ni": 58,
    "Co": 59, "Mn": 55, "Al": 27, "Ti": 48, "Sn": 120, "Se": 80,
}

# (mass number, abundance) — IUPAC representative abundances.
ISOTOPES = {
    "H": [(1, 0.999885), (2, 0.000115)],
    "C": [(12, 0.9893), (13, 0.0107)],
    "N": [(14, 0.99636), (15, 0.00364)],
    "O": [(16, 0.99757), (17, 0.00038), (18, 0.00205)],
    "S": [(32, 0.9499), (33, 0.0075), (34, 0.0425), (36, 0.0001)],
    "Cl": [(35, 0.7578), (37, 0.2422)],
    "Br": [(79, 0.5069), (81, 0.4931)],
    "Si": [(28, 0.9223), (29, 0.0467), (30, 0.0310)],
    "B": [(10, 0.199), (11, 0.801)],
    "F": [(19, 1.0)], "P": [(31, 1.0)], "I": [(127, 1.0)],
    "Na": [(23, 1.0)], "K": [(39, 1.0)],
}


def parse_formula(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element, number in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if not element:
            continue
        counts[element] = counts.get(element, 0) + (int(number) if number else 1)
    return counts


def rdbe(formula: str) -> float:
    """Rings + double-bond equivalents (neutral, ignoring O/S)."""
    c = parse_formula(formula)
    return (c.get("C", 0) - (c.get("H", 0) + c.get("F", 0) + c.get("Cl", 0)
                            + c.get("Br", 0) + c.get("I", 0)) / 2
            + c.get("N", 0) / 2 + 1)


def nominal_mass(formula: str) -> int:
    c = parse_formula(formula)
    return sum(ELEMENT_MASS.get(el, 0) * n for el, n in c.items())


def nitrogen_rule_ok(formula: str) -> bool:
    c = parse_formula(formula)
    return nominal_mass(formula) % 2 == c.get("N", 0) % 2


def isotope_pattern(formula: str, max_shift: int = 3) -> list[float]:
    """Relative M, M+1, ... intensities (M = 100)."""
    dist = {0: 1.0}
    for element, count in parse_formula(formula).items():
        iso = ISOTOPES.get(element)
        if not iso:
            continue
        base = iso[0][0]
        elem = {mass - base: abundance for mass, abundance in iso}
        for _ in range(count):
            new: dict[int, float] = {}
            for s1, p1 in dist.items():
                for s2, p2 in elem.items():
                    if s1 + s2 <= max_shift:
                        new[s1 + s2] = new.get(s1 + s2, 0.0) + p1 * p2
            dist = new
    base = dist.get(0, 1.0)
    return [100.0 * dist.get(i, 0.0) / base for i in range(max_shift + 1)]


def _line_text(lines: list[str], idx: int) -> str:
    text = lines[idx].strip()
    # A wrapped NMR line often continues on the next line without a heading.
    for j in range(idx + 1, min(idx + 3, len(lines))):
        nxt = lines[j].strip()
        if not nxt or NMR_RE.search(nxt) or re.match(r"^#{1,4}\s", nxt):
            break
        if text.rstrip().endswith((",", "δ", ";")) or nxt[:1].isdigit():
            text += " " + nxt
        else:
            break
    return text


def parse_nmr(lines: list[str]) -> list[dict]:
    blocks = []
    for idx, line in enumerate(lines):
        match = NMR_RE.search(line)
        if not match:
            continue
        kind = "1H" if match.group(1).lower() == "1h" else "13C"
        text = _line_text(lines, idx)
        formula = None
        for probe in (text, lines[idx - 1] if idx else "",
                      lines[idx + 1] if idx + 1 < len(lines) else ""):
            fm = FORMULA_RE.search(probe)
            if fm:
                formula = fm.group(0)
                break
        delta = text.find("δ")
        if delta < 0:
            delta = text.lower().find("delta")
        shift_text = text[delta + 1:] if delta >= 0 else text
        blocks.append({
            "kind": kind, "line": idx + 1, "text": text,
            "formula": formula,
            "integrals": [float(x) for x in INTEGRAL_RE.findall(text)],
            "shifts": [float(x) for x in SHIFT_RE.findall(shift_text)],
        })
    return blocks


def _fractional_distance(value: float) -> float:
    """Distance to nearest 0.5 (0.5 H is allowed for exchangeable protons)."""
    return abs(value - round(value * 2) / 2)


def analyse(lines: list[str]) -> dict:
    findings: list[dict] = []
    nmr = parse_nmr(lines)

    for block in nmr:
        if block["kind"] == "1H":
            for value in block["integrals"]:
                if value <= 0:
                    continue
                dist = _fractional_distance(value)
                if dist > 0.12:
                    findings.append({
                        "check": "nmr_integration_noninteger",
                        "severity": "soft",
                        "detail": (f"1H integration {value:g} H is {dist:.2f} H away "
                                   f"from the nearest 0.5 H; check the integration "
                                   f"and whether an exchangeable proton is involved."),
                        "line": block["line"], "evidence": block["text"],
                        "benign_explanation": "exchangeable proton, overlapping "
                                              "signal, or integration normalized to "
                                              "a subset/impurity.",
                    })
            if block["formula"] and block["integrals"]:
                h_count = parse_formula(block["formula"]).get("H", 0)
                total = sum(block["integrals"])
                if h_count and abs(total - h_count) > max(0.5, 0.10 * h_count):
                    findings.append({
                        "check": "nmr_integration_sum",
                        "severity": "soft",
                        "detail": (f"sum of 1H integrals = {total:g} H vs formula "
                                   f"{block['formula']} H{h_count}; difference "
                                   f"{total - h_count:+g} H."),
                        "line": block["line"], "evidence": block["text"],
                        "benign_explanation": "integrals may be normalized to a "
                                              "subset; exchangeable protons may be "
                                              "omitted or exchanged; solvent/impurity "
                                              "peaks may be integrated.",
                    })
        else:
            shifts = block["shifts"]
            if block["formula"]:
                c_count = parse_formula(block["formula"]).get("C", 0)
                cleaned = [s for s in shifts
                           if not any(abs(s - sol) < 0.15 for sol in SOLVENT_SHIFTS["13C"])]
                if c_count and len(cleaned) > c_count:
                    findings.append({
                        "check": "nmr_13c_count_exceeds_formula",
                        "severity": "hard",
                        "detail": (f"13C NMR lists {len(cleaned)} signals (after "
                                   f"solvent-peak removal) but formula "
                                   f"{block['formula']} has only {c_count} carbons."),
                        "line": block["line"], "evidence": block["text"],
                        "benign_explanation": "impurity/solvent peaks not in the "
                                              "exclusion list, or a formula typo.",
                    })
            for shift in shifts:
                if shift > 250 or shift < -10:
                    findings.append({
                        "check": "nmr_13c_impossible_shift",
                        "severity": "hard",
                        "detail": f"13C shift {shift:g} ppm is outside the normal "
                                  f"organic range (-10 to 250 ppm).",
                        "line": block["line"], "evidence": block["text"],
                        "benign_explanation": "paramagnetic complex, or a typo / "
                                              "different nucleus mislabeled as 13C.",
                    })
            seen = set()
            for shift in shifts:
                key = round(shift, 1)
                if key in seen:
                    findings.append({
                        "check": "nmr_13c_duplicate_shift",
                        "severity": "soft",
                        "detail": f"13C shift {shift:g} ppm appears more than once.",
                        "line": block["line"], "evidence": block["text"],
                        "benign_explanation": "two carbons may genuinely overlap; "
                                              "also a common copy/typo.",
                    })
                seen.add(key)

    # HRMS lines: formula + m/z + optional isotope percentages.
    for idx, line in enumerate(lines):
        if not re.search(r"\bHRMS\b|\bESI\b|\[M\s*[+-]", line, re.I):
            continue
        formula_match = FORMULA_RE.search(line)
        if not formula_match:
            continue
        formula = formula_match.group(0)
        if rdbe(formula) < -0.1:
            findings.append({
                "check": "hrms_rdbe_negative",
                "severity": "hard",
                "detail": f"RDBE of {formula} is {rdbe(formula):.1f} (< 0); "
                          f"the formula cannot be a neutral closed-shell molecule.",
                "line": idx + 1, "evidence": line.strip(),
                "benign_explanation": "formula typo, ion/radical, or a salt "
                                      "component written without its counter-ion.",
            })
        if not nitrogen_rule_ok(formula):
            findings.append({
                "check": "hrms_nitrogen_rule",
                "severity": "soft",
                "detail": (f"{formula} has nominal mass {nominal_mass(formula)} "
                           f"and N count {parse_formula(formula).get('N', 0)}; "
                           f"the nitrogen-rule parity does not match."),
                "line": idx + 1, "evidence": line.strip(),
                "benign_explanation": "salt/ion, isotope label, or formula typo.",
            })
        pattern = isotope_pattern(formula)
        reported = {int(m.group(1)): float(m.group(2))
                    for m in ISOTOPE_RE.finditer(line)}
        for shift in (1, 2):
            if shift not in reported:
                continue
            expected = pattern[shift]
            observed = reported[shift]
            diff = abs(observed - expected)
            rel = diff / expected if expected > 0 else 0.0
            if diff > 10.0 and rel > 0.50:
                findings.append({
                    "check": "hrms_isotope_intensity",
                    "severity": "soft",
                    "detail": (f"{formula}: reported M+{shift} = {observed:g}% "
                               f"but the natural-abundance pattern predicts "
                               f"{expected:.1f}% (relative difference {rel:.0%})."),
                    "line": idx + 1, "evidence": line.strip(),
                    "benign_explanation": "isotope-labelled compound, different "
                                          "adduct/charge state, or a peak-picking "
                                          "artifact; verify the raw spectrum.",
                })

    # Deduplicate identical (check, line, detail).
    unique = []
    seen = set()
    for finding in findings:
        key = (finding["check"], finding["line"], finding["detail"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return {
        "applicable": bool(nmr) or any(
            re.search(r"\bHRMS\b|\[M\s*[+-]", line, re.I) for line in lines),
        "findings_count": len(unique),
        "findings": unique,
        "nmr_blocks": [
            {"kind": b["kind"], "line": b["line"], "formula": b["formula"],
             "integrals": b["integrals"], "shifts": b["shifts"][:40]}
            for b in nmr
        ],
        "method_note": ("NMR parsing is line-based and tolerant, not a full "
                        "structure elucidation. Integrals are allowed to be "
                        "half-integers; 13C solvent peaks are excluded from the "
                        "count. Isotope patterns use IUPAC representative "
                        "abundances and ignore isotope labels. Every finding "
                        "needs a benign-explanation pressure test."),
    }


def find_full_md(root: pathlib.Path) -> pathlib.Path | None:
    direct = root / "full.md"
    if direct.exists():
        return direct
    candidates = sorted(root.rglob("full.md"))
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("input", help="workdir containing full.md")
    parser.add_argument("--output", required=True, help="JSON output path")
    args = parser.parse_args()
    root = pathlib.Path(args.input).expanduser().resolve()
    md = find_full_md(root)
    if md is None:
        print(f"no full.md under {root}", file=sys.stderr)
        return 1
    lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
    report = analyse(lines)
    report["source"] = str(md)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"output": str(output),
                      "applicable": report["applicable"],
                      "findings_count": report["findings_count"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
