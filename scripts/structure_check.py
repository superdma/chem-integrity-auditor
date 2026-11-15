#!/usr/bin/env python3
"""Chemistry structure / identity verification against PubChem.

Answers a narrow, deterministic question: does the compound the paper says it
made match the identity the paper reports (formula, molecular weight, exact
mass / HRMS, CAS, elemental analysis), and is a "novel compound" actually
already registered?

The script produces leads, never verdicts. Every comparison carries a
candidate benign explanation. PubChem lookups are cached on disk so an audit
can be re-run offline and so the same compound is not queried twice.

Usage
-----
    # single compound
    structure_check.py --name aspirin --reported-formula C9H8O4 \\
        --reported-mw 180.16 --output out.json

    # HRMS + elemental analysis
    structure_check.py --smiles 'CC(=O)OC1=CC=CC=C1C(=O)O' \\
        --reported-mz '181.0495 [M+H]+' \\
        --reported-chn 'C=60.00,H=4.48' --output out.json

    # batch (JSON list; see --help-batch)
    structure_check.py --batch compounds.json --output out.json

Network: PubChem PUG REST (https://pubchem.ncbi.nlm.nih.gov/rest/pug).
No API key. Stdlib only; RDKit is used opportunistically when installed.

Python 3.8+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = "chem-integrity-auditor/1.0 (research integrity audit; contact: local)"

# IUPAC 2013 standard atomic weights (abridged, covers typical small molecules).
ATOMIC_WEIGHTS = {
    "H": 1.008, "D": 2.014, "B": 10.81, "C": 12.011, "N": 14.007,
    "O": 15.999, "F": 18.998, "Na": 22.990, "Mg": 24.305, "Al": 26.982,
    "Si": 28.085, "P": 30.974, "S": 32.06, "Cl": 35.45, "K": 39.098,
    "Ca": 40.078, "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693,
    "Cu": 63.546, "Zn": 65.38, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Mo": 95.95, "Ag": 107.868, "Cd": 112.414, "Sn": 118.710, "I": 126.904,
    "Cs": 132.905, "Ba": 137.327, "Pt": 195.084, "Au": 196.967,
    "Hg": 200.592, "Pb": 207.2,
}
MONOISOTOPIC = {
    "H": 1.007825032, "D": 2.014101778, "B": 11.009305, "C": 12.0,
    "N": 14.003074, "O": 15.994915, "F": 18.998403, "Na": 22.989770,
    "Mg": 23.985042, "Al": 26.981538, "Si": 27.976927, "P": 30.973762,
    "S": 31.972071, "Cl": 34.968853, "K": 38.963707, "Ca": 39.962591,
    "Mn": 54.938045, "Fe": 55.934938, "Co": 58.933195, "Ni": 57.935343,
    "Cu": 62.929598, "Zn": 63.929142, "As": 74.921597, "Se": 79.916522,
    "Br": 78.918337, "Mo": 97.905409, "Ag": 106.905093, "Cd": 113.903358,
    "Sn": 119.902195, "I": 126.904473, "Cs": 132.905447, "Ba": 137.905241,
    "Pt": 194.964791, "Au": 196.966569, "Hg": 201.970643, "Pb": 207.976652,
}
PROTON = 1.007276466
ELECTRON = 0.00054858
NEUTRON = 1.0033548

ADDUCTS = {
    "[M+H]+": PROTON,
    "[M-H]-": -PROTON,
    "[M]+": -ELECTRON,
    "[M]-": ELECTRON,
    "[M+Na]+": 22.989218,
    "[M+K]+": 38.963158,
    "[M+NH4]+": 18.033823,
    "[M+HCOO]-": 44.997655,
    "[M+CH3COO]-": 59.013304,
    "[M+Cl]-": 34.969402,
    "[M+Br]-": 78.918885,
    "[M+2H]2+": (2 * PROTON) / 2.0,
    "[M+2Na]2+": (2 * 22.989218) / 2.0,
    "[M+3H]3+": (3 * PROTON) / 3.0,
}

FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)")
NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
CHN_ELEMENTS = ("C", "H", "N", "O", "S")


# --------------------------------------------------------------------------
# formula / mass helpers
# --------------------------------------------------------------------------

def split_formula(formula: str):
    """Split 'C9H8O4.H2O' -> ['C9H8O4', 'H2O']; '·' treated as '.'."""
    if not formula:
        return []
    return [p.strip() for p in re.split(r"[·.]", formula.strip()) if p.strip()]


def parse_formula(formula: str):
    """Return (counts, charge, ok) for a plain formula string.

    Unknown elements become a key with weight None; the caller reports that
    instead of silently dropping the atom.
    """
    counts = {}
    charge = 0
    text = formula.strip()
    # trailing charge forms: C6H5O7-3, C6H5O7^3-, [Fe(CN)6]3-
    m = re.search(r"(?:\^)?(\d*)([+-])$", text)
    if m and not re.search(r"[A-Za-z]\d*$", text):
        n = int(m.group(1) or 1)
        charge = n if m.group(2) == "+" else -n
        text = text[: m.start()]
    text = text.replace("[", "").replace("]", "").replace(" ", "")
    pos = 0
    while pos < len(text):
        m = FORMULA_TOKEN.match(text, pos)
        if not m:
            return counts, charge, False
        el, num = m.group(1), m.group(2)
        counts[el] = counts.get(el, 0.0) + (float(num) if num else 1.0)
        pos = m.end()
    return counts, charge, True


def formula_mass(formula: str, table=None):
    """Molecular mass from a formula (sums hydrates); None if unknown element."""
    table = table or ATOMIC_WEIGHTS
    total = 0.0
    unknown = []
    for part in split_formula(formula):
        counts, _charge, ok = parse_formula(part)
        if not ok:
            return None, ["unparsed:" + part]
        for el, n in counts.items():
            if el not in table:
                unknown.append(el)
                continue
            total += table[el] * n
    return (total if not unknown else None), unknown


def monoisotopic_mass(formula: str):
    return formula_mass(formula, MONOISOTOPIC)


def hill_formula(counts):
    """Hill order: C first, H second, then alphabetical."""
    items = {k: v for k, v in counts.items() if v}
    order = []
    if "C" in items:
        order.append("C")
        if "H" in items:
            order.append("H")
        order += sorted(k for k in items if k not in ("C", "H"))
    else:
        order = sorted(items)
    out = []
    for el in order:
        n = items[el]
        out.append(el + ("" if abs(n - 1) < 1e-9 else
                         (str(int(n)) if abs(n - round(n)) < 1e-9 else f"{n:g}")))
    return "".join(out)


def normalize_formula(formula: str) -> str:
    """Canonical comparison key: element counts, hydrate parts sorted."""
    parts = []
    for part in split_formula(formula):
        counts, _c, ok = parse_formula(part)
        if not ok:
            return formula.strip()
        parts.append(hill_formula(counts))
    return ".".join(sorted(parts))


def formula_element_percent(formula: str, element: str):
    mass, unknown = formula_mass(formula)
    if mass is None:
        return None, unknown
    counts = {}
    for part in split_formula(formula):
        c, _ch, _ok = parse_formula(part)
        for el, n in c.items():
            counts[el] = counts.get(el, 0.0) + n
    if element not in counts or element not in ATOMIC_WEIGHTS:
        return 0.0, []
    return 100.0 * counts[element] * ATOMIC_WEIGHTS[element] / mass, []


def rdkit_identity(smiles: str):
    """Optional RDKit cross-check; returns None when RDKit is unavailable."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors
    except Exception:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"error": "RDKit could not parse the SMILES"}
    return {
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(Descriptors.MolWt(mol), 4),
        "exact_mass": round(Descriptors.ExactMolWt(mol), 6),
        "canonical_smiles": Chem.MolToSmiles(mol),
        "inchi_key": Chem.MolToInchiKey(mol),
    }


# --------------------------------------------------------------------------
# PubChem client (cached, rate-limited, offline-capable)
# --------------------------------------------------------------------------

class PubChemError(RuntimeError):
    pass


class PubChemClient:
    def __init__(self, cache_dir: Path, offline=False, refresh=False,
                 timeout=25.0, sleep=0.25, retries=2):
        self.cache_dir = cache_dir
        self.offline = offline
        self.refresh = refresh
        self.timeout = timeout
        self.sleep = sleep
        self.retries = retries
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_request = 0.0

    def _cache_path(self, key):
        return self.cache_dir / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")

    def _read_cache(self, key):
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, key, payload):
        p = self._cache_path(key)
        payload = dict(payload)
        payload["_cache_key"] = key
        payload["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def _get(self, url):
        delay = self.sleep - (time.time() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        last = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self.last_request = time.time()
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code == 404:
                    raise PubChemError("not-found")
                if exc.code in (429, 503) and attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise PubChemError(f"HTTP {exc.code}")
            except Exception as exc:  # noqa: BLE001 - network errors are broad
                last = exc
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise PubChemError(str(exc))
        raise PubChemError(str(last))

    def _cached_get(self, key, url):
        cached = None if self.refresh else self._read_cache(key)
        if cached is not None:
            cached["_source"] = "cache"
            return cached
        if self.offline:
            raise PubChemError("offline-and-not-cached")
        payload = self._get(url)
        self._write_cache(key, payload)
        payload["_source"] = "network"
        return payload

    def by_identifier(self, kind, value):
        props = ("MolecularFormula,MolecularWeight,ExactMass,MonoisotopicMass,"
                 "InChIKey,IUPACName,CanonicalSMILES")
        if kind == "formula":
            key = f"formula:{value}"
            cid_url = f"{PUBCHEM}/compound/fastformula/{urllib.parse.quote(value, safe='')}/cids/JSON?MaxRecords=6"
            cids = self._cached_get(key + ":cids", cid_url)
            ids = cids.get("IdentifierList", {}).get("CID", [])
            if not ids:
                raise PubChemError("not-found")
            cid_str = ",".join(str(c) for c in ids[:6])
            prop_url = f"{PUBCHEM}/compound/cid/{cid_str}/property/{props}/JSON"
            data = self._cached_get(key + ":props", prop_url)
            props_list = data.get("PropertyTable", {}).get("Properties", [])
            if not props_list:
                raise PubChemError("not-found")
            entry = dict(props_list[0])
            entry["_ambiguous_cids"] = [p.get("CID") for p in props_list]
            return entry
        endpoint = {"name": "name", "smiles": "smiles", "inchikey": "inchikey",
                    "cas": "name"}[kind]
        q = urllib.parse.quote(value, safe="")
        url = f"{PUBCHEM}/compound/{endpoint}/{q}/property/{props}/JSON"
        data = self._cached_get(f"{kind}:{value}", url)
        props_list = data.get("PropertyTable", {}).get("Properties", [])
        if not props_list:
            raise PubChemError("not-found")
        return dict(props_list[0])

    def synonyms(self, cid):
        url = f"{PUBCHEM}/compound/cid/{cid}/synonyms/JSON"
        data = self._cached_get(f"synonyms:{cid}", url)
        info = data.get("InformationList", {}).get("Information", [])
        if not info:
            return []
        return info[0].get("Synonym", [])


# --------------------------------------------------------------------------
# reported-value parsing
# --------------------------------------------------------------------------

def parse_chn(text):
    """Parse 'C=60.00,H=4.48' / 'C, 60.00; H, 4.48' / 'C 60.00 H 4.48'."""
    out = {}
    if not text:
        return out
    # "C, 60.02; H, 4.51; N, 7.75" or "C 60.02 H 4.51"
    for m in re.finditer(r"([A-Z][a-z]?)\s*[,:=]?\s*(\d+(?:\.\d+)?)\s*%?", text):
        el, val = m.group(1), float(m.group(2))
        if el in CHN_ELEMENTS:
            out[el] = val
    return out


def parse_reported_mz(text, adduct=None):
    """Parse '181.0495 [M+H]+' or 'm/z 181.0495 ([M+H]+)' -> (mz, adduct)."""
    if text is None:
        return None, adduct
    if isinstance(text, (int, float)):
        return float(text), adduct
    mz_m = NUM.search(str(text))
    if not mz_m:
        return None, adduct
    ad_m = re.search(r"\[M[^\]]*\]\s*[0-9]*[+-]?", str(text))
    return float(mz_m.group(0)), (ad_m.group(0).replace(" ", "") if ad_m else adduct)


def adduct_delta(adduct):
    if not adduct:
        return None
    key = adduct.replace(" ", "")
    return ADDUCTS.get(key)


def compare_values(check, reported, expected, severity, detail,
                   benign, delta=None):
    return {
        "check": check, "severity": severity,
        "reported": reported, "expected": expected,
        "delta": (round(delta, 6) if isinstance(delta, (int, float)) else delta),
        "detail": detail, "benign_explanation": benign,
    }


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def run_checks(spec, entry, client):
    """Compare one compound spec against one PubChem entry."""
    comps = []
    formula = entry.get("MolecularFormula")
    mw = entry.get("MolecularWeight")
    exact = entry.get("MonoisotopicMass") or entry.get("ExactMass")
    inchikey = entry.get("InChIKey")
    cid = entry.get("CID")

    comps.append(compare_values(
        "pubchem_lookup", spec.get("queried_as"), f"CID {cid}", "pass",
        f"PubChem 命中 CID {cid}（{formula}, {mw}）", "—"))

    if spec.get("claim_novel") and cid:
        comps.append(compare_values(
            "novelty", "论文声称新化合物", f"PubChem 已有 CID {cid}",
            "soft",
            "论文声称该结构为新化合物，但 PubChem 已收录同一结构（见 InChIKey）",
            "可能仅骨架/片段相似而非同一物质；也可能论文中的“新”指新衍生物。"
            "须用 InChIKey 前 14 位（骨架层）与论文结构逐原子核对后再定级"))

    rep_formula = spec.get("reported_formula")
    if rep_formula and formula:
        a, b = normalize_formula(rep_formula), normalize_formula(formula)
        if a == b:
            sev = "pass"
            detail = "报告分子式与 PubChem 一致"
        elif a.split(".")[0] == b.split(".")[0]:
            sev = "info"
            detail = "主分子式一致，水合物/盐形式不同"
        else:
            sev = "hard"
            detail = "报告分子式与 PubChem 不一致"
        comps.append(compare_values(
            "formula", rep_formula, formula, sev, detail,
            "可能查询命中了盐/水合物/互变异构体的另一条记录；先核对 InChIKey "
            "与论文结构，再判断是否为报告错误"))

    rep_mw = spec.get("reported_mw")
    if rep_mw is not None and mw is not None:
        d = float(rep_mw) - float(mw)
        tol = spec.get("mw_tol", 0.5)
        if abs(d) <= tol:
            sev, detail = "pass", f"报告 MW 与 PubChem 相差 {d:+.2f} Da（容差 {tol}）"
        elif abs(d) <= 2.0:
            sev, detail = "info", f"报告 MW 与 PubChem 相差 {d:+.2f} Da"
        else:
            sev, detail = "soft", f"报告 MW 与 PubChem 相差 {d:+.2f} Da（>{tol}）"
        comps.append(compare_values(
            "mw", rep_mw, mw, sev, detail,
            "论文可能报告的是盐/水合物/溶剂化形式的分子量，或使用名义质量；"
            "核对分子式后再定级"))

    # Elemental analysis: reported Calcd vs theory, then Found vs theory.
    chn_calcd = parse_chn(spec.get("reported_chn_calcd") or "")
    chn_found = parse_chn(spec.get("reported_chn") or "")
    if formula and (chn_calcd or chn_found):
        for el in sorted(set(chn_calcd) | set(chn_found)):
            theory, unknown = formula_element_percent(formula, el)
            if theory is None:
                comps.append(compare_values(
                    "chn_elemental", el, None, "info",
                    f"无法从 PubChem 分子式计算 {el} 理论百分含量（{unknown}）",
                    "公式含脚本未收录的元素"))
                continue
            if el in chn_calcd:
                d = chn_calcd[el] - theory
                if abs(d) <= 0.15:
                    sev, detail = "pass", f"Calcd {el} 与理论值相差 {d:+.2f} pp"
                else:
                    sev = "hard"
                    detail = (f"作者给出的 Calcd {el} = {chn_calcd[el]:.2f}%，"
                              f"但按分子式 {formula} 计算为 {theory:.2f}%"
                              f"（Δ {d:+.2f} pp）")
                comps.append(compare_values(
                    "chn_calcd", chn_calcd[el], round(theory, 3), sev, detail,
                    "分子式可能对应盐/水合物而我们未采用同一形式；先确认 "
                    "caption 中的分子式，再判断 Calcd 是否真的算错"))
            if el in chn_found:
                d = chn_found[el] - theory
                if abs(d) <= 0.4:
                    sev, detail = "pass", f"Found {el} 与理论值相差 {d:+.2f} pp"
                elif abs(d) <= 0.8:
                    sev, detail = "info", f"Found {el} 与理论值相差 {d:+.2f} pp"
                else:
                    sev = "soft"
                    detail = (f"Found {el} = {chn_found[el]:.2f}%，理论值 "
                              f"{theory:.2f}%（Δ {d:+.2f} pp）")
                comps.append(compare_values(
                    "chn_found", chn_found[el], round(theory, 3), sev, detail,
                    "元素分析仪对吸湿/溶剂化样品常偏低 0.4–0.8 pp；"
                    "只有多个元素同向大幅偏离，或 Found 与 Calcd 精确到 0.01 "
                    "完全相等，才构成独立线索"))

    # HRMS / exact mass.
    rep_mz, adduct = parse_reported_mz(spec.get("reported_mz"), spec.get("adduct"))
    if rep_mz is not None and exact is not None:
        delta_ad = adduct_delta(adduct)
        if delta_ad is None:
            comps.append(compare_values(
                "hrms", rep_mz, None, "info",
                f"未给出可识别的加合物（adduct={adduct!r}），仅报告 m/z",
                "adduct 缺失无法计算理论值；在论文行内查找 [M+H]+ 等标注"))
        else:
            expected = float(exact) + delta_ad
            d_da = rep_mz - expected
            d_mda = d_da * 1000.0
            tol_mda = spec.get("hrms_tol_mda", 20.0)
            if abs(d_mda) <= tol_mda:
                sev = "pass"
                detail = f"报告 m/z 与理论值相差 {d_mda:+.1f} mDa（容差 {tol_mda}）"
            elif abs(d_mda) <= 50:
                sev = "info"
                detail = f"报告 m/z 与理论值相差 {d_mda:+.1f} mDa"
            else:
                sev = "soft"
                detail = (f"报告 m/z = {rep_mz:.4f}（{adduct}），按 "
                          f"{formula} 计算应为 {expected:.4f}，"
                          f"相差 {d_mda:+.1f} mDa")
            comps.append(compare_values(
                "hrms", rep_mz, round(expected, 5), sev, detail,
                "加合物/电荷态标注可能不同（[M+H]+ vs [M+Na]+），或报告的是 "
                "低分辨名义质量；先核对行内 adduct 与是否使用平均质量"))

    # CAS membership.
    rep_cas = spec.get("reported_cas")
    if rep_cas and cid is not None:
        try:
            syn = client.synonyms(cid)
        except PubChemError:
            syn = []
        norm = {s.replace(" ", "").upper() for s in syn}
        cas_key = str(rep_cas).replace(" ", "").upper()
        if cas_key in norm:
            comps.append(compare_values(
                "cas", rep_cas, f"CID {cid}", "pass",
                "报告 CAS 号在 PubChem 同义词中命中", "—"))
        else:
            comps.append(compare_values(
                "cas", rep_cas, f"CID {cid}", "info",
                "报告 CAS 号未在 PubChem 同义词中命中",
                "新化合物/新登记号可能尚未进入 PubChem；CAS 号也可能印刷错误"))

    # RDKit cross-check of a supplied SMILES (structure <-> formula/MW).
    if spec.get("smiles"):
        rd = rdkit_identity(spec["smiles"])
        if rd and not rd.get("error"):
            comps.append(compare_values(
                "rdkit", rd["formula"], formula, "info",
                f"RDKit 从 SMILES 重算：{rd['formula']}, MW {rd['mw']:.2f}, "
                f"exact {rd['exact_mass']:.4f}",
                "用于交叉验证 SMILES 与 PubChem 命中是否为同一结构；"
                "若 InChIKey 与 PubChem 不一致，说明 SMILES 画错或命中了不同记录"))
            if spec.get("reported_formula"):
                a = normalize_formula(spec["reported_formula"])
                b = normalize_formula(rd["formula"])
                if a != b:
                    comps.append(compare_values(
                        "rdkit_formula", spec["reported_formula"], rd["formula"],
                        "soft", "论文报告分子式与所给 SMILES 重算结果不一致",
                        "SMILES 可能只表示骨架/省略了盐；核对结构图后再定级"))
        elif rd and rd.get("error"):
            comps.append(compare_values(
                "rdkit", spec["smiles"], None, "info", rd["error"],
                "SMILES 语法错误，无法交叉验证"))

    return comps


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------

def load_specs(args):
    specs = []
    if args.batch:
        data = json.loads(Path(args.batch).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("compounds", [])
        if not isinstance(data, list):
            raise SystemExit("batch file must be a JSON list or {'compounds': [...]}")
        specs.extend(data)
    base = {
        "name": args.name, "smiles": args.smiles, "inchikey": args.inchikey,
        "cas": args.cas, "formula": args.formula, "label": args.label,
        "reported_formula": args.reported_formula,
        "reported_mw": args.reported_mw,
        "reported_chn": args.reported_chn,
        "reported_chn_calcd": args.reported_chn_calcd,
        "reported_mz": args.reported_mz, "adduct": args.adduct,
        "reported_cas": args.reported_cas, "claim_novel": args.claim_novel,
        "mw_tol": args.mw_tol, "hrms_tol_mda": args.hrms_tol_mda,
    }
    input_keys = ("name", "smiles", "inchikey", "cas", "formula",
                  "reported_formula", "reported_mw", "reported_chn",
                  "reported_chn_calcd", "reported_mz", "reported_cas")
    if any(base.get(k) is not None for k in input_keys):
        specs.append({k: v for k, v in base.items() if v is not None})
    if not specs:
        raise SystemExit("no compound given; use --name/--smiles/--cas/--formula/--batch")
    return specs


def pick_identity(spec):
    for kind in ("name", "smiles", "inchikey", "cas", "formula"):
        if spec.get(kind):
            return kind, spec[kind]
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify a paper's compound identity / formula / MW / CHN / "
                    "HRMS against PubChem (deterministic, cached).",
        epilog="Batch JSON keys: label,name,smiles,cas,inchikey,formula,"
               "reported_formula,reported_mw,reported_chn,reported_chn_calcd,"
               "reported_mz,adduct,reported_cas,claim_novel",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("compound identity (one of)")
    src.add_argument("--name")
    src.add_argument("--smiles")
    src.add_argument("--inchikey")
    src.add_argument("--cas")
    src.add_argument("--formula")
    src.add_argument("--batch", help="JSON list of compound specs")
    src.add_argument("--label", help="label used in the report")
    rep = ap.add_argument_group("reported values from the paper")
    rep.add_argument("--reported-formula")
    rep.add_argument("--reported-mw", type=float)
    rep.add_argument("--reported-chn", help="Found %%: 'C=60.00,H=4.48'")
    rep.add_argument("--reported-chn-calcd", help="paper's Calcd %%")
    rep.add_argument("--reported-mz", help="'181.0495 [M+H]+'")
    rep.add_argument("--adduct", help="override adduct, e.g. '[M+H]+'")
    rep.add_argument("--reported-cas")
    rep.add_argument("--claim-novel", action="store_true",
                     help="paper claims this is a new compound")
    rep.add_argument("--mw-tol", type=float, default=0.5)
    rep.add_argument("--hrms-tol-mda", type=float, default=20.0)
    net = ap.add_argument_group("network / cache")
    net.add_argument("--output", required=True)
    net.add_argument("--cache", default=str(Path.home() / ".cache" /
                                            "chem-integrity-auditor" / "pubchem"))
    net.add_argument("--offline", action="store_true")
    net.add_argument("--refresh", action="store_true")
    net.add_argument("--timeout", type=float, default=25.0)
    net.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    specs = load_specs(args)
    client = PubChemClient(Path(args.cache), offline=args.offline,
                           refresh=args.refresh, timeout=args.timeout,
                           sleep=args.sleep)
    queries = []
    for spec in specs:
        label = spec.get("label") or spec.get("name") or spec.get("smiles") or \
            spec.get("inchikey") or spec.get("formula") or "compound"
        kind, value = pick_identity(spec)
        q = {"label": label, "identity": {"kind": kind, "value": value},
             "pubchem": None, "comparisons": []}
        if kind is None:
            q["comparisons"].append(compare_values(
                "pubchem_lookup", None, None, "info",
                "未提供可用标识（name/SMILES/InChIKey/CAS/formula）",
                "补充标识后重跑"))
            queries.append(q)
            continue
        try:
            entry = client.by_identifier(kind, value)
            q["pubchem"] = {
                "cid": entry.get("CID"),
                "formula": entry.get("MolecularFormula"),
                "mw": entry.get("MolecularWeight"),
                "exact_mass": entry.get("MonoisotopicMass") or entry.get("ExactMass"),
                "inchi_key": entry.get("InChIKey"),
                "iupac_name": entry.get("IUPACName"),
                "canonical_smiles": entry.get("CanonicalSMILES"),
                "source": entry.get("_source", "network"),
                "ambiguous_cids": entry.get("_ambiguous_cids"),
            }
            spec = dict(spec)
            spec["queried_as"] = f"{kind}:{value}"
            q["comparisons"] = run_checks(spec, entry, client)
        except PubChemError as exc:
            msg = str(exc)
            sev = "info"
            detail = f"PubChem 查询失败：{msg}"
            if msg == "not-found":
                sev = "soft"
                detail = ("PubChem 未命中该标识；若论文声称是已知化合物，"
                          "这是一个身份线索")
            q["comparisons"].append(compare_values(
                "pubchem_lookup", value, None, sev, detail,
                "离线缓存缺失、标识拼写错误、或该结构确未收录；"
                "检查缓存/网络后重跑，勿据此单独定级"))
        queries.append(q)

    counts = {"pass": 0, "info": 0, "soft": 0, "hard": 0}
    for q in queries:
        for c in q["comparisons"]:
            counts[c["severity"]] = counts.get(c["severity"], 0) + 1
    report = {
        "meta": {
            "tool": "structure_check.py",
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pubchem_endpoint": PUBCHEM,
            "offline": args.offline,
            "cache_dir": str(Path(args.cache)),
            "note": "Leads, not verdicts. Every comparison names a benign "
                    "explanation; grade only after checking the paper's own "
                    "formula/adduct context.",
        },
        "summary": {"n_compounds": len(queries), **counts},
        "queries": queries,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}: {len(queries)} compound(s), "
          f"{counts['hard']} hard / {counts['soft']} soft / "
          f"{counts['info']} info / {counts['pass']} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
