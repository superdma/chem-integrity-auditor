#!/usr/bin/env python3
"""Chemistry-specific numeric forensics for paper-integrity audits.

Complements ``numeric_forensics.py`` (generic duplicate / terminal-digit /
Benford checks) with domain checks that only make sense for chemistry:

  1.  yield_roundness        — isolated yields that are multiples of 5, == 100%, or > 100%
  2.  conversion_selectivity — internal consistency: product yield ≈ conv × sel / 100
  3.  area_percent_sum       — GC/HPLC composition rows should sum to ≈100%
  4.  chn_elemental          — Calcd/Found vs theoretical % from the molecular formula
  5.  hrms_mw                — reported m/z vs formula MONOISOTOPIC mass + adduct (±20 mDa)
  6.  scherrer               — reported crystallite size vs D = Kλ/(β·cosθ) from table 2θ/FWHM
  7.  identical_replicates   — repeated-run rows that are numerically identical
  8.  impossible_unit_ranges — hard physical range violations (ppm, eV, °C, %, 2θ, …)
  9.  neat_decimals          — columns with suspiciously uniform precision
  10. fixed_offset_rows      — row pairs where every numeric column differs by a constant

Input: an audit workdir containing ``full.md`` (MinerU markdown; HTML tables are
parsed directly — self-hosted MinerU returns md_content only, so the evidence
ledger usually has no table index for local runs). Each finding carries
line-level provenance into full.md.

Output: ``chem_numeric.json`` — findings are LEADS, not verdicts. Every
finding includes a candidate benign explanation; the audit agent must
pressure-test it before grading.

Stdlib only. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATOMIC_WEIGHTS = {
    "H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998,
    "P": 30.974, "S": 32.06, "Cl": 35.45, "Br": 79.904, "I": 126.904,
    "B": 10.81, "Li": 6.94, "Na": 22.990, "K": 39.098, "Mg": 24.305,
    "Al": 26.982, "Si": 28.085, "Ca": 40.078, "Ti": 47.867, "Fe": 55.845,
    "Cu": 63.546, "Zn": 65.38, "Mn": 54.938, "Co": 58.933, "Ni": 58.693,
    "Sr": 87.62, "Ba": 137.327, "La": 138.905, "Ce": 140.116, "Zr": 91.224,
    "V": 50.942, "Cr": 51.996, "W": 183.84, "Mo": 95.95, "Ag": 107.868,
    "Au": 196.967, "Pt": 195.084, "Pd": 106.42, "Rh": 102.906,
}

# Monoisotopic masses: HRMS compares the lightest isotope, never the average
# atomic weight (using average mass throws every [M+H]+ off by ~0.2 Da).
MONOISOTOPIC = {
    "H": 1.007825032, "D": 2.014101778, "B": 11.009305, "C": 12.0,
    "N": 14.003074, "O": 15.994915, "F": 18.998403, "Na": 22.989770,
    "Mg": 23.985042, "Al": 26.981538, "Si": 27.976927, "P": 30.973762,
    "S": 31.972071, "Cl": 34.968853, "K": 38.963707, "Ca": 39.962591,
    "Ti": 47.947942, "V": 50.943959, "Cr": 51.940508, "Mn": 54.938045,
    "Fe": 55.934938, "Co": 58.933195, "Ni": 57.935343, "Cu": 62.929598,
    "Zn": 63.929142, "Sr": 87.905612, "Zr": 89.904704, "Mo": 97.905409,
    "Rh": 102.905504, "Pd": 105.903486, "Ag": 106.905093, "Cd": 113.903358,
    "Sn": 119.902195, "I": 126.904473, "Ba": 137.905241, "La": 138.906353,
    "Ce": 139.905439, "W": 183.950931, "Pt": 194.964791, "Au": 196.966569,
    "Hg": 201.970643, "Pb": 207.976652,
}
PROTON = 1.007276466

# (hard_min, hard_max, soft_note): hard = physically impossible outside this
# range for the unit; soft = unusual, needs context. None bound = unbounded.
UNIT_RANGES = {
    "ppm": (-5.0, 300.0, "NMR/MS chemical shifts: 1H ~0-15, 13C 0-250, MS m/z offset in ppm 10s-100s"),
    "°C": (-273.2, 3000.0, "decompose above ~2000°C; below -273°C impossible"),
    "eV": (0.0, 2000.0, "XPS/UV ranges; >100 eV in a paper context is unusual"),
    "nm": (None, 1.0e7, "negative size impossible"),
    "min": (None, 1.0e4, "retention > ~1000 min is unusual for HPLC/GC"),
    "cm⁻¹": (300.0, 5000.0, "IR/Raman reported window is ~4000-400 cm⁻¹"),
    "°2θ": (0.0, 180.0, "XRD 2θ beyond 180° is impossible"),
    "2θ": (0.0, 180.0, "XRD 2θ beyond 180° is impossible"),
    "V": (-100.0, 100.0, "cell voltages in lab chemistry are well within ±100 V"),
    "mV": (-1.0e5, 1.0e5, "EIS/CV offsets; beyond ±100 V unrealistic"),
    "mV/s": (None, 1.0e5, "CV scan rates are typically 1-1000 mV/s"),
    "mA/cm²": (None, 1.0e5, "current densities; sign depends on convention"),
    "Wh/kg": (None, 20000.0, "energy densities above ~10 kWh/kg are exotic"),
    "S/cm": (None, 1.0e5, "conductivities"),
    "g": (None, 1.0e8, "masses in a lab paper"),
    "mg": (None, 1.0e8, "masses in a lab paper"),
    "%": (None, 100.0, "percentages above 100 are impossible for yields/areas/conversions"),
}

SUBSCRIPT_MAP = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}

# Organic molecular formulas: Hill order (C first, then H, then others).
# Requiring C or N followed by a digit filters out protein/kinase names
# (PI3K, MAPK) and lone symbols.
MOLFORMULA_RE = re.compile(
    r"\b([CN]\d{1,4}(?:[A-Z][a-z]?\d{0,4}){1,25})\b")

# Column-header heuristics (case-insensitive, substring)
YIELD_HEADERS = ("yield", "收率", "% yield", "yield %")
CONV_HEADERS = ("conversion", "转化率", "conv")
SEL_HEADERS = ("selectivity", "选择性", "sel", "yield of", "% yield of")
AREA_PCT_HEADERS = ("area", "peak", "含量", "组分", "%", "content", "composition")
REPEAT_ROW_KEYWORDS = ("run 1", "run 2", "run 3", "trial 1", "trial 2",
                       "replicate 1", "replicate 2", "n = 1", "no. 1", "1st", "2nd")

# ---------------------------------------------------------------------------
# Formula parsing
# ---------------------------------------------------------------------------

def normalize_formula(s: str) -> str:
    return "".join(SUBSCRIPT_MAP.get(ch, ch) for ch in s)


def parse_formula_mw(text: str):
    """Find the first plausible organic molecular formula and its MW.

    Returns (formula_str, mw) or (None, None). Handles C28H36O4, Unicode
    subscripts. Adduct/charge notation ([M+H]+ etc.) is the caller's concern.
    The first match is preferred because in captions/HRMS lines the relevant
    formula follows the compound name; later formulas in the same string are
    usually fragments or byproducts.
    """
    for m in MOLFORMULA_RE.finditer(text):
        cand = normalize_formula(m.group(1))
        tokens = re.findall(r"([A-Z][a-z]?)(\d*)", cand)
        mw = 0.0
        count_sum = 0
        known = 0
        for el, cnt in tokens:
            n = int(cnt) if cnt else 1
            count_sum += n
            if el in ATOMIC_WEIGHTS:
                mw += ATOMIC_WEIGHTS[el] * n
                known += 1
        # reject degenerate matches (need several atoms, real mass, mostly
        # known elements)
        if count_sum < 4 or mw < 50 or known < max(2, len(tokens) - 1):
            continue
        return cand, mw
    return None, None


def formula_monoisotopic_mass(formula: str):
    """Monoisotopic (exact) mass; None when an element is not tabulated."""
    tokens = re.findall(r"([A-Z][a-z]?)(\d*)", formula)
    total = 0.0
    for el, cnt in tokens:
        n = int(cnt) if cnt else 1
        if el not in MONOISOTOPIC:
            return None
        total += MONOISOTOPIC[el] * n
    return total if total > 0 else None


def formula_element_pct(formula: str, elements):
    """Theoretical weight percent of given elements in a formula."""
    tokens = re.findall(r"([A-Z][a-z]?)(\d*)", formula)
    mw = 0.0
    for el, cnt in tokens:
        n = int(cnt) if cnt else 1
        if el in ATOMIC_WEIGHTS:
            mw += ATOMIC_WEIGHTS[el] * n
    if mw == 0:
        return None
    out = {}
    for el in elements:
        n = 0
        for elem, cnt in tokens:
            if elem == el:
                n = int(cnt) if cnt else 1
        if el in ATOMIC_WEIGHTS:
            out[el] = 100.0 * ATOMIC_WEIGHTS[el] * n / mw
    return out


# ---------------------------------------------------------------------------
# Table extraction from markdown (HTML tables + pipe tables)
# ---------------------------------------------------------------------------

def extract_tables(md_text: str):
    """Return list of dicts: {line_start, line_end, rows, caption, section}.

    MinerU markdown embeds tables as well-formed HTML, so a regex pass over
    <table>/<tr>/<t[dh]> is reliable here; pipe tables are handled as a
    fallback for other markdown sources.
    """
    lines = md_text.splitlines()
    tables = []
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", md_text, re.S | re.I):
        start_line = md_text.count("\n", 0, m.start()) + 1
        end_line = md_text.count("\n", 0, m.end()) + 1
        rows = []
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr.group(1), re.S | re.I)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"line_start": start_line, "line_end": end_line,
                           "rows": rows, "raw_span": (m.start(), m.end())})
    # Pipe tables
    block_re = re.compile(r"(?:^\|.*\|\s*$\n?){3,}", re.M)
    for m in block_re.finditer(md_text):
        block = m.group(0)
        rows = []
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row
            rows.append(cells)
        if len(rows) >= 2:
            start_line = md_text.count("\n", 0, m.start()) + 1
            tables.append({"line_start": start_line, "line_end": start_line + len(rows) - 1,
                           "rows": rows, "raw_span": (m.start(), m.end())})
    # Deduplicate by span
    seen = set()
    unique = []
    for t in tables:
        key = t["raw_span"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    unique.sort(key=lambda t: t["line_start"])

    # Attach caption (nearest line above containing 'Table' or '图' or a number label)
    for t in unique:
        t["caption"] = ""
        t["section"] = ""
        for back in range(t["line_start"] - 1, max(t["line_start"] - 6, 0), -1):
            line = lines[back - 1].strip() if back >= 1 else ""
            if not line:
                continue
            if re.search(r"\btable\s*\d+|表\s*\d+", line, re.I):
                t["caption"] = line
                break
            t["caption"] = t["caption"] or line[:120]
        for i in range(t["line_start"] - 1, -1, -1):
            line = lines[i].strip()
            if re.match(r"^#{1,4}\s", line):
                t["section"] = line.lstrip("#").strip()
                break
    return unique


def to_number(cell: str):
    """Parse a cell to float; None if not numeric."""
    if cell is None:
        return None
    s = normalize_formula(str(cell)).strip()
    s = s.replace(",", "").replace("±", " ").replace("≈", "")
    # split off a trailing unit
    m = re.match(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$", s)
    if not m:
        # try leading unit-stripped value
        m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", s)
        if not m:
            return None
        unit = ""
    else:
        unit = m.group(2).strip()
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    return val, unit


def cell_number(cell: str):
    r = to_number(cell)
    return (r[0], r[1]) if r else (None, "")


def cell_number_strict(cell: str):
    """Numeric only when the cell STARTS with a number.

    to_number() falls back to the first number anywhere in the string, which
    turns material names such as "NiCo2O4/rGO nanosheets" into the value 2.
    That is useful for unit scanning but poisons column-level statistics.
    """
    s = normalize_formula(str(cell)).strip()
    if not re.match(r"^[-+]?\d", s):
        return (None, "")
    return cell_number(cell)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def find_findings(checks):
    """Run all checks; return (tables, findings)."""
    findings = []

    def add(check, severity, table, location, values, detail, benign):
        findings.append({
            "check": check, "severity": severity,
            "table": table.get("caption") or f"line {table.get('line_start')}",
            "location": location, "values": values,
            "detail": detail, "benign_explanation": benign,
        })

    for ti, table in enumerate(checks["tables"]):
        rows = table["rows"]
        header = rows[0] if rows else []
        body = rows[1:] if len(rows) > 1 else []
        caption = table.get('caption') or ("line " + str(table['line_start']))
        tname = "T%d (%s)" % (ti + 1, caption)

        def kw_match(kw: str, hl: str) -> bool:
            # word-boundary match for pure alpha/num keywords (so "d" does
            # not match "Deg"); substring for keywords with symbols (2θ, %).
            if re.fullmatch(r"[0-9a-z]+", kw):
                return re.search(r"\b" + re.escape(kw) + r"\b", hl) is not None
            return kw in hl

        def col_idx(*keywords):
            for j, h in enumerate(header):
                hl = h.lower()
                for kw in keywords:
                    if kw_match(kw.lower(), hl):
                        return j
            return None

        def col_values(j):
            out = []
            for i, row in enumerate(body):
                if j < len(row):
                    val, unit = cell_number(row[j])
                    out.append((i, val, unit))
            return out

        # --- 1. yield roundness ------------------------------------------------
        jy = col_idx(*YIELD_HEADERS)
        if jy is not None:
            vals = [(i, v, u) for (i, v, u) in col_values(jy) if v is not None]
            if vals:
                bad = [(i, v) for (i, v, u) in vals if v > 100.0]
                for (i, v) in bad:
                    add("yield_roundness", "hard", table,
                        {"row": i + 1, "column": header[jy]}, [v],
                        f"yield {v:g}% > 100% — physically impossible",
                        "column is not an isolated yield (e.g., a ratio or "
                        "normalized value); verify header semantics")
                exact100 = [(i, v) for (i, v, u) in vals if v == 100.0]
                for (i, v) in exact100:
                    add("yield_roundness", "soft", table,
                        {"row": i + 1, "column": header[jy]}, [v],
                        f"yield exactly 100.0% — isolated yields above 99.5% "
                        f"are rare",
                        "GC-area yield with internal standard at rounding, or "
                        "theoretical yield column misread as isolated")
                mult5 = [v for (i, v, u) in vals
                         if abs(v - round(v / 5.0) * 5) < 1e-9 and v < 100]
                if len(vals) >= 5 and len(mult5) / len(vals) >= 0.5:
                    add("yield_roundness", "soft", table,
                        {"column": header[jy], "rows": f"{len(mult5)}/{len(vals)}"},
                        mult5[:10],
                        f"{len(mult5)}/{len(vals)} yields are multiples of 5 — "
                        f"measured GC/yield values rarely align this neatly",
                        "author rounded to one significant digit for the table; "
                        "check SI/raw data for unrounded values")

        # --- 2. conversion × selectivity vs product yield ----------------------
        jc, js = col_idx("conversion", "转化率", "conv"), col_idx("selectivity", "选择性")
        if jc is not None and js is not None:
            jy2 = jy if jy is not None else col_idx("product yield", "% yield", "yield")
            if jy2 is not None and jy2 not in (jc, js):
                for i in range(len(body)):
                    cv = cell_number(body[i][jc])[0] if jc < len(body[i]) else None
                    sl = cell_number(body[i][js])[0] if js < len(body[i]) else None
                    py = cell_number(body[i][jy2])[0] if jy2 < len(body[i]) else None
                    if None in (cv, sl, py):
                        continue
                    if sl > 100.0 or cv > 100.0:
                        add("conversion_selectivity", "hard", table,
                            {"row": i + 1, "columns": [header[jc], header[js]]},
                            [cv, sl],
                            f"conversion/selectivity > 100% ({cv:g}, {sl:g})",
                            "different normalization basis; verify definitions")
                        continue
                    expected = cv * sl / 100.0
                    if abs(py - expected) > 3.0:
                        add("conversion_selectivity", "soft", table,
                            {"row": i + 1,
                             "columns": [header[jc], header[js], header[jy2]]},
                            [cv, sl, py, round(expected, 2)],
                            f"product yield {py:g}% ≠ conv×sel/100 = {expected:.2f}% "
                            f"(Δ {abs(py - expected):.1f}pp)",
                            "selectivity defined per feedstock rather than per "
                            "conversion, or yield measured on a different basis "
                            "(wet vs dry); both definitions exist in the literature")

        # --- 3. area percent sum ------------------------------------------------
        # Only composition columns (fractions of a whole). Per-metric columns
        # like Yield (%) / Conversion (%) / Efficiency (%) are not a partition
        # and must not be summed together.
        # \bpurity\b excludes "impurity" — an impurity column in a GC table
        # IS a fraction of the whole and must be summed.
        METRIC_PCT_RE = re.compile(
            r"yield|conversion|selectivity|efficiency|recovery|ratio|loading|"
            r"\bpurity\b|收率|转化率|选择性|效率|纯度", re.I)
        pct_cols = [j for j, h in enumerate(header)
                    if any(k in h.lower() for k in AREA_PCT_HEADERS)
                    and h.lower().strip() not in ("no.", "sample", "t/min")
                    and not METRIC_PCT_RE.search(h)]
        if len(pct_cols) >= 2:
            sums = []
            for i, row in enumerate(body):
                vals = [cell_number(row[j])[0] for j in pct_cols if j < len(row)]
                vals = [v for v in vals if v is not None]
                if len(vals) >= len(pct_cols) * 0.8:
                    s = sum(vals)
                    sums.append((i, s))
            for (i, s) in sums:
                if s > 105 or s < 90:
                    add("area_percent_sum", "soft", table,
                        {"row": i + 1, "columns": [header[j] for j in pct_cols]},
                        [round(s, 2)],
                        f"area% sum = {s:.1f} (expected ≈100)",
                        "undetected minor components omitted, or columns are "
                        "mass fractions of a subset, not a full composition")

        # --- 4. CHN elemental ----------------------------------------------------
        text_near = " ".join(" ".join(r) for r in rows[:4])
        caption_ctx = f" {table.get('caption', '')} {table.get('section', '')} {text_near}"
        if re.search(r"elemental|CHN|C, H, N|元素分析", caption_ctx, re.I):
            # Element header row: first row whose normalized cells contain >=2
            # of C/H/N (labels are usually bare letters, sometimes "C (wt%)").
            hdr2 = None
            for row in rows[:4]:
                norm = [re.sub(r"[^\w]", "", c).lower() for c in row]
                if len([x for x in norm if x in ("c", "h", "n", "o", "s")]) >= 2:
                    hdr2 = row
                    break
            if hdr2 is None:
                hdr2 = header
            jmap = {}
            for j, h in enumerate(hdr2):
                hl = re.sub(r"[^\w]", "", h).lower()
                if hl in ("c", "carbon"):
                    jmap.setdefault("C", j)
                elif hl in ("h", "hydrogen"):
                    jmap.setdefault("H", j)
                elif hl in ("n", "nitrogen"):
                    jmap.setdefault("N", j)
            if len(jmap) >= 2:
                # locate calcd / found rows (labels in the first 1-2 cells)
                calcd_row = found_row = None
                for i, row in enumerate(rows):
                    label = " ".join(row[:2]).lower()
                    if re.search(r"\bcalcd|calc\.|theoretical|calculated", label):
                        calcd_row = (i, row)
                    elif re.search(r"\bfound|\bexp|observed", label):
                        found_row = (i, row)
                formula, mw = parse_formula_mw(caption_ctx)
                if formula and calcd_row:
                    pct = formula_element_pct(formula, list(jmap.keys()))
                    if pct:
                        _, crow = calcd_row
                        for el, j in jmap.items():
                            if el not in pct or j >= len(crow):
                                continue
                            v, _ = cell_number(crow[j])
                            if v is None:
                                continue
                            if abs(v - pct[el]) > 0.15:
                                add("chn_elemental", "hard", table,
                                    {"row": calcd_row[0] + 1, "element": el,
                                     "formula": formula},
                                    [v, round(pct[el], 2)],
                                    f"Calcd {el} = {v:g}% vs theoretical {pct[el]:.2f}% "
                                    f"(formula {formula})",
                                    "formula in the caption differs from the "
                                    "actual compound (solvate/impurity) — check "
                                    "which formula the table header names")
                if calcd_row and found_row:
                    _, crow = calcd_row
                    _, frow = found_row
                    for el, j in jmap.items():
                        if j >= len(crow) or j >= len(frow):
                            continue
                        vc, vf = cell_number(crow[j])[0], cell_number(frow[j])[0]
                        if vc is None or vf is None:
                            continue
                        if abs(vf - vc) > 0.4:
                            add("chn_elemental", "soft", table,
                                {"row": found_row[0] + 1, "element": el},
                                [vf, vc],
                                f"Found {el} = {vf:g}% deviates {abs(vf - vc):.2f}% "
                                f"from Calcd {vc:g}% (CHN precision ~±0.4%)",
                                "instrument drift or sample heterogeneity; "
                                "deviation up to 0.4% is normal, larger is not")

        # --- 5. HRMS vs formula MW: handled at document level ---------------
        # (see hrms_document_scan below — HRMS lines live in body text, not
        # just in tables)

        # --- 6. Scherrer ------------------------------------------------------------
        j2t = col_idx("2θ", "2 theta", "2theta", "deg")
        jfw = col_idx("fwhm", "β", "beta", "hwhm")
        jsize = col_idx("crystallite", "size", "nm", "d")
        if j2t is not None and jfw is not None and jsize is not None:
            for i, row in enumerate(body):
                if j2t >= len(row) or jfw >= len(row) or jsize >= len(row):
                    continue
                t2 = cell_number(row[j2t])[0]
                beta = cell_number(row[jfw])[0]
                size = cell_number(row[jsize])[0]
                if None in (t2, beta, size) or beta <= 0 or t2 <= 0:
                    continue
                if not (20 <= t2 <= 90):
                    continue  # not the main XRD peak range
                # FWHM sanity: real XRD peak widths are ~0.05-10 degrees.
                # Outside that, the column is not an FWHM (misaligned or
                # different units) and the Scherrer result is garbage.
                if not (0.05 <= beta <= 10.0):
                    continue
                theta_rad = math.radians(t2 / 2.0)
                beta_rad = math.radians(beta)
                d_calc = 0.9 * 1.5406 / (beta_rad * max(math.cos(theta_rad), 1e-9))
                # Realistic crystallite size window; outside it the three
                # columns do not describe one measurement (comparison table
                # rows, unit mixups). Skip rather than flag a false positive.
                if 0.5 <= d_calc <= 1000.0:
                    rel = abs(size - d_calc) / d_calc
                    if rel > 0.4:
                        add("scherrer", "soft", table,
                            {"row": i + 1,
                             "columns": [header[j2t], header[jfw], header[jsize]]},
                            [t2, beta, size, round(d_calc, 2)],
                            f"reported size {size:g} nm vs Scherrer {d_calc:.2f} nm "
                            f"(K=0.9, Cu Kα) — Δ {rel * 100:.0f}%",
                            "different K constant, instrumental broadening "
                            "subtracted, or a different peak was used; all of "
                            "these are legitimate but should be stated")

        # --- 7. identical replicate rows ---------------------------------------------
        first_col = body[0][0] if body and body[0] else ""
        looks_repeat = any(k in " ".join(str(r[0]) for r in body[:6]).lower()
                           for k in REPEAT_ROW_KEYWORDS)
        if len(body) >= 2:
            num_cols = [j for j in range(len(header))
                        if sum(1 for r in body if j < len(r) and
                               cell_number_strict(r[j])[0] is not None)
                        >= max(2, len(body) * 0.6)]
            for j in num_cols:
                colvals = [cell_number_strict(r[j])[0] for r in body if j < len(r)]
                colvals = [v for v in colvals if v is not None]
                if len(colvals) >= 3 and len(set(colvals)) == 1:
                    add("identical_replicates", "soft", table,
                        {"column": header[j]}, colvals[:5],
                        f"column '{header[j]}': {len(colvals)} identical values "
                        f"({colvals[0]:g}) across repeated runs",
                        "repeated measurements can coincide at low precision "
                        "(e.g., integer percentages); check the precision "
                        "actually used — 2+ decimals identical is not benign")
            if looks_repeat and len(num_cols) >= 2:
                for a in range(len(body)):
                    for b in range(a + 1, len(body)):
                        ra, rb = body[a], body[b]
                        diffs = []
                        same = True
                        for j in num_cols:
                            va = cell_number_strict(ra[j])[0] if j < len(ra) else None
                            vb = cell_number_strict(rb[j])[0] if j < len(rb) else None
                            if va is None or vb is None:
                                same = False
                                break
                            diffs.append(va - vb)
                        if same and diffs and all(abs(d) < 1e-12 for d in diffs):
                            add("identical_replicates", "soft", table,
                                {"rows": [a + 1, b + 1],
                                 "columns": [header[j] for j in num_cols]},
                                [ra[j] for j in num_cols],
                                f"rows {a + 1} and {b + 1} are numerically "
                                f"identical across all {len(num_cols)} numeric "
                                f"columns",
                                "the rows may be the same condition measured "
                                "once and duplicated for a statistics display; "
                                "check captions")

        # --- 8. impossible unit ranges --------------------------------------------------
        for i, row in enumerate(body):
            for j, cell in enumerate(row):
                if j >= len(header):
                    break
                val, unit = cell_number(cell)
                if val is None:
                    continue
                u = unit.lower()
                for key, (lo, hi, note) in UNIT_RANGES.items():
                    if key in u or (key == "%" and "%" in cell) or \
                       (key == "ppm" and "ppm" in header[j].lower()):
                        if lo is not None and val < lo:
                            add("impossible_unit_ranges", "hard", table,
                                {"row": i + 1, "column": header[j], "cell": cell},
                                [val],
                                f"{cell!r} below hard minimum {lo:g} for {key!r}",
                                note)
                        elif hi is not None and val > hi:
                            # skip % for columns that are clearly not percents
                            if key == "%" and val <= 1000:
                                continue
                            add("impossible_unit_ranges", "soft", table,
                                {"row": i + 1, "column": header[j], "cell": cell},
                                [val],
                                f"{cell!r} above typical maximum {hi:g} for {key!r}",
                                note)
                        break

        # --- 9. neat decimals -------------------------------------------------------------
        IDENT_HEADER_RE = re.compile(
            r"^\s*(entry|no\.?|№|#|sample|run|lot|peak|proton|condition|"
            r"compound|comp\.?|substrate|reagent|reference|ref\.?)\s*$", re.I)
        for j in range(len(header)):
            if IDENT_HEADER_RE.search(header[j]):
                continue
            vals = []
            for r in body:
                if j < len(r):
                    raw = r[j]
                    val, _ = cell_number(raw)
                    if val is not None and re.fullmatch(r"[-+]?\d+\.?\d*", str(raw).strip()):
                        dec = len(str(raw).strip().split(".")[1]) if "." in str(raw) else 0
                        vals.append((val, dec))
            if len(vals) >= 5:
                # row-number columns (1..n) are identifiers, not measurements
                if [v for v, _ in vals] == list(range(1, len(vals) + 1)):
                    continue
                decs = set(d for _, d in vals)
                if decs == {0}:
                    add("neat_decimals", "info", table,
                        {"column": header[j]}, [v for v, _ in vals][:8],
                        f"column '{header[j]}': all {len(vals)} values are "
                        f"integers",
                        "coarse instrument precision (e.g., a balance to 1 g, "
                        "temperature to 1°C) legitimately gives integers")

        # --- 10. fixed offset rows -----------------------------------------------------------
        for a in range(len(body)):
            for b in range(a + 1, len(body)):
                ra, rb = body[a], body[b]
                diffs, ok = [], True
                for j in range(len(header)):
                    if j >= len(ra) or j >= len(rb):
                        ok = False
                        break
                    va, _ = cell_number(ra[j])
                    vb, _ = cell_number(rb[j])
                    if va is None or vb is None:
                        continue
                    diffs.append(vb - va)
                if ok and len(diffs) >= 3:
                    if all(abs(d - diffs[0]) < 1e-9 for d in diffs):
                        # non-zero constant offset across >=3 numeric columns
                        if abs(diffs[0]) > 1e-9:
                            add("fixed_offset_rows", "soft", table,
                                {"rows": [a + 1, b + 1],
                                 "offset": round(diffs[0], 4)},
                                [ra[j] for j in range(len(diffs))],
                                f"rows {a + 1}→{b + 1}: every numeric column "
                                f"shifted by exactly {diffs[0]:g}",
                                "a deliberate control comparison (e.g., with/without "
                                "catalyst at the same feedstock) can produce "
                                "constant offsets by construction; check the "
                                "experimental design")

    return findings


# ---------------------------------------------------------------------------
# Document-level HRMS scan
# ---------------------------------------------------------------------------

def parse_adduct(line):
    """Parse '[M+H]+' / '[M+2H]2+' / '[M-H]-' -> (delta, charge, sign).

    delta is the summed monoisotopic mass of the adduct atoms (proton masses,
    electron correction applied by the caller). None when no bracket form is
    present or an adduct fragment is not tabulated.
    """
    m = re.search(r"\[\s*M\s*([^\]]*?)\s*\]\s*(\d*)\s*([+\-−])", line)
    if not m:
        return None
    inner = m.group(1).replace("−", "-")
    charge = int(m.group(2) or 1)
    sign = 1 if m.group(3) == "+" else -1
    delta = 0.0
    for op, part in re.findall(r"([+\-])([A-Za-z0-9]*)", inner):
        if not part:
            continue
        n = 1
        mm = re.match(r"^(\d+)(.*)$", part)
        if mm:
            n, part = int(mm.group(1)), mm.group(2)
        if not part:
            continue
        mass = formula_monoisotopic_mass(part)
        if mass is None:
            return None
        delta += (1 if op == "+" else -1) * n * mass
    return delta, charge, sign


def hrms_document_scan(md_lines, findings):
    """Scan every markdown line for HRMS statements.

    HRMS data sits in body text and SI text, not only in tables, so this
    runs over the whole document. A line must contain BOTH a molecular
    formula and a high-precision m/z to be checked — that co-location is
    what makes the comparison meaningful.

    Masses are MONOISOTOPIC. Using average atomic weights would put every
    [M+H]+ ~0.2 Da off and flag correct calcd values as errors.
    """
    seen = set()
    for lineno, line in enumerate(md_lines, 1):
        if len(line) > 2000:
            continue
        # 1) calcd-vs-found pair on the same line: modern HRMS resolves far
        #    better than 20 mDa; a wider gap is itself a finding.
        for x, y in re.findall(
                r"calcd\s*(?:for\s*\S+\s*)?(?:\[M[^\]]*\])?\s*(\d{2,4}\.\d{2,5})"
                r"\s*[,;]?\s*(?:found|obs(?:erved)?)\s*[:=]?\s*(\d{2,4}\.\d{2,5})",
                line, re.I):
            gap = abs(float(x) - float(y))
            if gap > 0.02 and (x, y) not in seen:
                seen.add((x, y))
                findings.append({
                    "check": "hrms_mw", "severity": "soft",
                    "table": "body text",
                    "location": {"md_line": lineno},
                    "values": [float(x), float(y)],
                    "detail": (f"line {lineno}: calcd {x} vs found {y} "
                               f"differ by {gap * 1000:.0f} mDa (> 20 mDa)"),
                    "benign_explanation": ("low-resolution instrument "
                                           "mislabeled as HRMS, or a "
                                           "transcription slip; check the SI "
                                           "spectrum image"),
                })
        formula, _avg_mw = parse_formula_mw(line)
        if not formula:
            continue
        exact = formula_monoisotopic_mass(formula)
        if exact is None:
            continue
        adduct = parse_adduct(line)
        m_ad = re.search(r"\[\s*M[^\]]*\]\s*\d*\s*[+\-−]", line)
        key = (m_ad.group(0).replace(" ", "") if m_ad else "m")
        if adduct:
            delta, charge, sign = adduct
            expect = (exact + delta - sign * charge * 0.00054858) / charge
        else:
            expect = exact
        mz_vals = re.findall(r"(\d{2,4}\.\d{3,5})\b", line)
        if not mz_vals:
            continue
        for mz_s in mz_vals:
            try:
                mz = float(mz_s)
            except ValueError:
                continue
            if mz < 10 or mz > 3000:
                continue
            # only compare m/z values in the right ballpark — a number on the
            # line may be a retention time, a mass fraction, or an impurity ion
            if abs(mz - expect) > 1.0:
                continue
            if abs(mz - expect) > 0.02:
                dedup = (formula, key, mz_s, lineno)
                if dedup in seen:
                    continue
                seen.add(dedup)
                findings.append({
                    "check": "hrms_mw", "severity": "soft",
                    "table": "body text",
                    "location": {"md_line": lineno, "formula": formula,
                                 "adduct": key},
                    "values": [mz, round(expect, 4)],
                    "detail": (f"line {lineno}: m/z {mz} vs expected "
                               f"{expect:.4f} (formula {formula}, adduct {key})"),
                    "benign_explanation": ("adduct misidentified or the "
                                           "formula on the line belongs to a "
                                           "different species; verify against "
                                           "the SI spectrum"),
                })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chemistry-specific numeric forensics on a MinerU markdown workdir.")
    parser.add_argument("workdir", help="Audit workdir containing full.md")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    md_path = workdir / "full.md"
    if not md_path.exists():
        print(f"missing {md_path}", file=sys.stderr)
        return 2
    md_text = md_path.read_text(encoding="utf-8")
    md_lines = md_text.splitlines()
    tables = extract_tables(md_text)
    findings = find_findings({"tables": tables, "md_lines": md_lines})
    hrms_document_scan(md_lines, findings)

    out = {
        "schema": "chem-numeric/v1",
        "source_markdown": str(md_path),
        "tables_found": len(tables),
        "table_list": [
            {"index": i + 1, "line_start": t["line_start"], "line_end": t["line_end"],
             "caption": t.get("caption", ""), "section": t.get("section", ""),
             "rows": len(t["rows"])}
            for i, t in enumerate(tables)
        ],
        "findings_count": len(findings),
        "findings": findings,
        "note": "leads, not verdicts; pressure-test each benign explanation",
    }
    Path(args.output).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    by_sev = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    print(json.dumps({"tables": len(tables), "findings": len(findings),
                      "by_severity": by_sev,
                      "output": str(Path(args.output).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
