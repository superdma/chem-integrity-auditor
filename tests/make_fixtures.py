#!/usr/bin/env python3
"""Generate deterministic test fixtures for chem-integrity-auditor.

Run once (or after changing a fixture):  python3 tests/make_fixtures.py
Everything lands in tests/fixtures/ and is reproducible from the seeds here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"


def ensure(*parts):
    p = FIX.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------
# spectra
# --------------------------------------------------------------------------

def render_spectrum(path, peaks, seed, noise=0.02, width=800, height=400):
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([100, 40, 700, 340], outline=0, width=2)
    xs = np.arange(100, 701)
    ppm = 8.0 - (xs - 100) * 8.0 / 600.0
    y = np.zeros_like(ppm, dtype=float)
    for centre, amp, w in peaks:
        y += amp / (1 + ((ppm - centre) / w) ** 2)
    y += noise * np.random.RandomState(seed).normal(size=len(y)) + 0.03
    y = (y - y.min()) / (y.max() - y.min())
    for i in range(len(xs) - 1):
        d.line([(xs[i], 340 - y[i] * 280),
                (xs[i + 1], 340 - y[i + 1] * 280)], fill=0, width=2)
    img.save(path)


def make_spectra():
    d = ensure("spectra")
    render_spectrum(d / "spec_a.png",
                    [(7.26, 1.0, 0.012), (3.34, 0.55, 0.02),
                     (2.10, 0.35, 0.025), (1.23, 0.8, 0.015)], seed=0)
    render_spectrum(d / "spec_b.png",
                    [(7.25, 0.9, 0.014), (3.35, 0.6, 0.022),
                     (2.11, 0.3, 0.03), (1.24, 0.75, 0.018)], seed=7, noise=0.05)
    render_spectrum(d / "spec_c.png",
                    [(7.80, 0.9, 0.02), (4.10, 0.7, 0.02),
                     (2.50, 0.5, 0.02)], seed=3)
    refs = ensure("refs")
    (refs / "ref.csv").write_text(
        "shift,intensity\n7.26,1.0\n3.34,0.55\n2.10,0.35\n1.23,0.80\n",
        encoding="utf-8")
    (refs / "ref_other.csv").write_text(
        "shift,intensity\n7.80,0.9\n4.10,0.7\n2.50,0.5\n", encoding="utf-8")
    (refs / "ref_sdbs.txt").write_text(
        "SDBS-12345 1H NMR peak list\n"
        "7.26  2.0  s\n3.34  1.1  m\n2.10  0.7  m\n1.23  1.6  t\n",
        encoding="utf-8")
    (refs / "sample_peaks.txt").write_text(
        "7.27\n3.35\n2.11\n1.24\n", encoding="utf-8")
    (refs / "ref.json").write_text(json.dumps(
        {"peaks": [{"x": 7.26, "intensity": 1.0},
                   {"x": 3.34, "intensity": 0.55},
                   {"x": 2.10, "intensity": 0.35},
                   {"x": 1.23, "intensity": 0.8}]}), encoding="utf-8")


def render_segment_trace(path, *, duplicate: bool, seed: int = 11):
    """A line plot with (or without) a copied 70-point stretch."""
    width, height = 800, 400
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([100, 40, 700, 340], outline=0, width=2)
    rng = np.random.RandomState(seed)
    n = 600
    y = (0.25 * np.sin(np.arange(n) / 9.0)
         + 0.12 * np.sin(np.arange(n) / 3.1)
         + 0.05 * rng.normal(size=n))
    # Make the copied stretch distinctive so a clean trace cannot match it.
    copied = y[40:110].copy()
    if duplicate:
        y[260:330] = copied
    else:
        y[260:330] = (0.25 * np.sin(np.arange(70) / 8.0 + 1.7)
                      + 0.12 * np.sin(np.arange(70) / 3.1 + 0.4)
                      + 0.05 * rng.normal(size=70))
    y = (y - y.min()) / (y.max() - y.min())
    for i in range(n - 1):
        d.line([(100 + i, 340 - y[i] * 280),
                (101 + i, 340 - y[i + 1] * 280)], fill=0, width=2)
    img.save(path)


def make_segment_fixtures():
    d = ensure("spectra")
    render_segment_trace(d / "segment_dup.png", duplicate=True, seed=11)
    render_segment_trace(d / "segment_clean.png", duplicate=False, seed=11)


def make_calibration_manifest():
    d = ensure("calibration")
    pairs = [
        {"a": "../images/dup_a.png", "b": "../images/dup_b.png",
         "label": "duplicate", "technique": "photo"},
        {"a": "../images/dup_a.png", "b": "../images/diff.png",
         "label": "different", "technique": "photo"},
        {"a": "../spectra/spec_a.png", "b": "../spectra/spec_b.png",
         "label": "same_compound", "technique": "nmr"},
        {"a": "../spectra/spec_a.png", "b": "../spectra/spec_c.png",
         "label": "different_compound", "technique": "nmr"},
        {"a": "../spectra/spec_b.png", "b": "../spectra/spec_c.png",
         "label": "different_compound", "technique": "nmr"},
    ]
    (d / "manifest.json").write_text(json.dumps({"pairs": pairs}, indent=2),
                                     encoding="utf-8")


def make_nmr_fixtures():
    """Valid/invalid inline NMR + HRMS text for nmr_hrms_numeric.py."""
    valid = ensure("nmr")
    (valid / "full.md").write_text("""# Results

Compound 5a (C10H12O2).

1H NMR (400 MHz, CDCl3) δ 7.26 (d, J = 8.0 Hz, 2H), 6.85 (d, J = 8.0 Hz, 2H), 4.12 (q, J = 7.0 Hz, 2H), 2.35 (s, 3H), 1.25 (t, J = 7.0 Hz, 3H).
13C NMR (100 MHz, CDCl3) δ 170.2, 154.3, 130.1, 127.6, 114.2, 60.4, 20.8, 14.3.
HRMS (ESI) m/z calcd for C10H12O2 [M+H]+ 165.0910, found 165.0913.
""", encoding="utf-8")

    invalid = ensure("nmr_invalid")
    (invalid / "full.md").write_text("""# Results

Compound X (C8H8O2).

1H NMR (400 MHz, CDCl3) δ 7.26 (s, 2.37H), 3.34 (m, 3.34H), 1.08 (t, 1.08H).
13C NMR (100 MHz, CDCl3) δ 320.0, 170.2, 154.3, 130.1, 127.6, 114.2, 60.4, 20.8, 14.3, 10.1.
HRMS (ESI) m/z calcd for C2H10 [M+H]+ 31.0780, found 31.0783; M+1 = 35%.
""", encoding="utf-8")


# --------------------------------------------------------------------------
# generic images (phash / ORB / noise fingerprint)
# --------------------------------------------------------------------------

def make_images():
    d = ensure("images")
    rng = np.random.RandomState(42)
    base = Image.new("L", (400, 300), 245)
    dr = ImageDraw.Draw(base)
    for _ in range(18):
        x0, y0 = rng.randint(0, 360), rng.randint(0, 260)
        x1, y1 = x0 + rng.randint(12, 80), y0 + rng.randint(8, 50)
        shade = int(rng.randint(30, 170))
        dr.rectangle([x0, y0, x1, y1], outline=shade, width=2)
    for _ in range(8):
        dr.line([tuple(rng.randint(0, 400, 2)),
                 tuple(rng.randint(0, 300, 2))], fill=90, width=1)
    base.save(d / "dup_a.png")
    # brightness-shifted, slightly cropped copy
    crop = base.crop((3, 2, 397, 298)).resize((400, 300))
    arr = np.asarray(crop, dtype=float) * 0.92 + 12
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(d / "dup_b.png")
    # unrelated image
    other = Image.new("L", (400, 300), 250)
    do = ImageDraw.Draw(other)
    rr = np.random.RandomState(99)
    for _ in range(10):
        x, y = int(rr.randint(20, 340)), int(rr.randint(20, 240))
        do.ellipse([x, y, x + int(rr.randint(30, 90)),
                    y + int(rr.randint(30, 90))], outline=20, width=3)
    other.save(d / "diff.png")


def make_panel_figure():
    d = ensure("panels")
    img = Image.new("L", (700, 300), 255)
    a = Image.open(FIX / "spectra" / "spec_a.png").convert("L").resize((320, 260))
    b = Image.open(FIX / "spectra" / "spec_c.png").convert("L").resize((320, 260))
    # A continuous baseline keeps every column inked, so the panel splitter
    # cannot mistake a white stretch inside one spectrum for a panel gutter.
    for panel in (a, b):
        ImageDraw.Draw(panel).line([(4, 250), (315, 250)], fill=0, width=2)
    img.paste(a, (20, 20))
    img.paste(b, (370, 20))
    img.save(d / "figure_2panel.png")

    # stacked spectra separated by full-width black rules (Raman/XRD style)
    w, h = 600, 360
    stacked = Image.new("RGB", (w, h), (255, 255, 255))
    dr = ImageDraw.Draw(stacked)
    for y in (0, 119, 239, h - 1):
        dr.line([(0, y), (w - 1, y)], fill=(0, 0, 0), width=3)
    colours = [(210, 30, 30), (30, 60, 210), (30, 140, 60)]
    for band, colour in enumerate(colours):
        y0 = band * 120 + 10
        pts = []
        for x in range(20, w - 20):
            yy = y0 + 90 + 18 * np.sin(x / 13.0 + band)
            pts.append((x, yy))
        dr.line(pts, fill=colour, width=2)
    stacked.save(d / "stacked_3band.png")

    # offset-stacked traces with no separator rules (XRD/FTIR style)
    offset = Image.new("RGB", (600, 320), (255, 255, 255))
    od = ImageDraw.Draw(offset)
    od.rectangle([30, 10, 569, 309], outline=(0, 0, 0), width=2)
    for band, colour in enumerate([(210, 30, 30), (20, 90, 190)]):
        base = 90 + band * 120
        pts = [(x, base + 22 * np.sin(x / 17.0 + band * 2))
               for x in range(45, 555)]
        od.line(pts, fill=colour, width=2)
    offset.save(d / "offset_2trace.png")


# --------------------------------------------------------------------------
# numeric markdown
# --------------------------------------------------------------------------

NUMERIC_MD = """# Results

## Table 1. Isolated yields of 5a-5e.

<table>
<tr><th>Entry</th><th>Catalyst</th><th>Yield (%)</th></tr>
<tr><td>1</td><td>A</td><td>102.0</td></tr>
<tr><td>2</td><td>B</td><td>100.0</td></tr>
<tr><td>3</td><td>C</td><td>95.0</td></tr>
<tr><td>4</td><td>D</td><td>90.0</td></tr>
<tr><td>5</td><td>E</td><td>85.0</td></tr>
</table>

## Table 2. Elemental analysis of C22H25NO3 (5a).

<table>
<tr><th>Compound</th><th>C</th><th>H</th><th>N</th></tr>
<tr><td>5a Calcd</td><td>78.30</td><td>7.47</td><td>4.15</td></tr>
<tr><td>5a Found</td><td>77.10</td><td>7.49</td><td>4.12</td></tr>
</table>

## Table 3. HRMS data.

<table>
<tr><th>Compound</th><th>Formula</th><th>m/z</th></tr>
<tr><td>5a</td><td>C22H25NO3</td><td>352.1907</td></tr>
</table>

HRMS (ESI) m/z calcd for C22H25NO3 [M+H]+ 352.1907, found 352.1650.
"""


CLEAN_MD = """# Results

## Table 1. Isolated yields of 5a-5e.

<table>
<tr><th>Entry</th><th>Catalyst</th><th>Yield (%)</th></tr>
<tr><td>1</td><td>A</td><td>87.4</td></tr>
<tr><td>2</td><td>B</td><td>91.2</td></tr>
<tr><td>3</td><td>C</td><td>78.9</td></tr>
<tr><td>4</td><td>D</td><td>83.5</td></tr>
<tr><td>5</td><td>E</td><td>89.1</td></tr>
</table>

## Table 2. Elemental analysis of C22H25NO3 (5a).

<table>
<tr><th>Compound</th><th>C</th><th>H</th><th>N</th></tr>
<tr><td>5a Calcd</td><td>75.19</td><td>7.17</td><td>3.99</td></tr>
<tr><td>5a Found</td><td>75.02</td><td>7.24</td><td>3.91</td></tr>
</table>

HRMS (ESI) m/z calcd for C22H25NO3 [M+H]+ 352.1907, found 352.1910.
"""


def make_numeric():
    d = ensure("numeric")
    (d / "full.md").write_text(NUMERIC_MD, encoding="utf-8")
    c = ensure("numeric_clean")
    (c / "full.md").write_text(CLEAN_MD, encoding="utf-8")


# --------------------------------------------------------------------------
# PubChem offline cache (aspirin)
# --------------------------------------------------------------------------

ASPRIN = {
    "PropertyTable": {"Properties": [{
        "CID": 2244,
        "MolecularFormula": "C9H8O4",
        "MolecularWeight": "180.16",
        "ExactMass": "180.04225873",
        "MonoisotopicMass": "180.04225873",
        "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "IUPACName": "2-acetyloxybenzoic acid",
        "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
    }]},
    "_cache_key": "name:aspirin",
    "_fetched_at": "2026-01-01T00:00:00+00:00",
}


def make_mineru_fixture():
    d = ensure("mineru")
    # A minimal one-page PDF; the mock backend does not parse it, but a real
    # MinerU server will accept it.
    pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 12 Tf 20 100 Td (Mock paper) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""
    (d / "mock.pdf").write_bytes(pdf)


def make_pubchem_cache():
    d = ensure("pubchem_cache")
    key = hashlib.sha1("name:aspirin".encode()).hexdigest()[:20]
    (d / f"{key}.json").write_text(json.dumps(ASPRIN), encoding="utf-8")


def make_report_fixtures():
    d = ensure("report")
    (d / "evidence.json").write_text(json.dumps({"check": "fixture"}),
                                     encoding="utf-8")
    valid = """# 审计报告（fixture）

## 1. 论文信息

| DOI | 10.0000/fixture |

## 2. 审计范围与方法

- 图像线：panel_split + ORB。

## 3. 发现

### Level 2 — 明显异常

#### X1
- **位置**：`evidence.json`；Fig. 1 panel a
- **技术**：XRD
- **观察**：两个谱图共享背景纹理，noise_corr=0.81。
- **良性解释（候选）**：同一仪器背景。
- **压力测试**：独立样品应无共享纹理，故解释不成立。
- **证据图**：

  ![X1 原文页面](../images/dup_a.png)
  *PDF 第 1 页；红框为问题区域。*

  ![X1 局部放大](../images/dup_b.png)
  *红框区域 2× 放大。*

## 4. 各线小结

| 线 | 状态 | 运行内容 |
|---|---|---|
| 数值线 | clean | chem_numeric |
| 图像线 | 有发现 | ORB + fingerprint |
| 逻辑线 | 部分不适用 | claim chain |

## 5. 需作者提供的原始数据

1. XRD 原始计数（X1）。

## 6. 局限性

- 分辨率限制。

## 7. 质量门自检

- [x] 位置可解析
- [x] 压力测试完成
- [x] 未下造假结论
- [x] 三条线有状态
- [x] 通知指控已核对
"""
    (d / "valid.md").write_text(valid, encoding="utf-8")

    invalid = """# 审计报告（fixture）

## 1. 论文信息

<title>

## 2. 审计范围与方法

## 3. 发现

### Level 3 — 需原始数据裁定

#### BAD
- **技术**：XRD
- **观察**：数据造假。

## 4. 各线小结

| 数值线 | 未检查 |

## 5. 需作者提供的原始数据

## 6. 局限性

## 7. 质量门自检

- [ ] 位置可解析
"""
    (d / "invalid.md").write_text(invalid, encoding="utf-8")


def main():
    make_spectra()
    make_segment_fixtures()
    make_images()
    make_calibration_manifest()
    make_nmr_fixtures()
    make_panel_figure()
    make_numeric()
    make_mineru_fixture()
    make_pubchem_cache()
    make_report_fixtures()
    print(f"fixtures written under {FIX}")


if __name__ == "__main__":
    main()
