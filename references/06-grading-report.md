# 06 — Grading, report, quality gate

## Level definitions (evidence stance, not guilt)

| Level | 中文标签 | Criterion | Raw-data ask |
|---|---|---|---|
| **1** | 可疑线索 | anomaly observed; a benign explanation is plausible and untested or partially tested | none required (record the candidate explanation) |
| **2** | 明显异常 | anomaly confirmed in the published material; the benign explanation was constructed and failed | name what would resolve it (original instrument files, raw spectra, unrounded data) |
| **3** | 需原始数据裁定 | cannot resolve from published material at available resolution/data | **mandatory**: the exact file/instrument export needed, one bullet per finding |
| **4** | 高度疑似失实 | multiple independent evidence lines converge (e.g., reused spectrum + its labels contradict the text + the retraction-notice charge reproduces pixel-for-pixel) | what remains unverified, if anything |

Rules:

- Level ≥ 2 requires the adversarial defense (SKILL.md Step 7) recorded in
  the finding file under `## 压力测试`: the benign explanation, the test,
  the outcome. A Level 2 without a failed pressure test gets demoted to 1.
- Level 4 requires ≥ 2 independent lines agreeing. One line, however
  ugly, is Level 2–3.
- Retraction-notice charges: a charge you reproduce in the published
  material (same pixels / same values) is Level 4 for that charge. A charge
  you cannot test at 150–300 dpi is Level 3 with the resolution stated.
- Never assign a Level to a claim the paper does not make.

## Finding file format (exact template)

```markdown
# <short-id>

- **Line**: numerical / image / logical
- **Level (current)**: N
- **Location**: Fig X panel Y (panels/page-XXX-YYY.png, p.ZZ); Table N row R
  column C (full.md line L); SI file S p.P
- **Technique**: XRD / NMR / HPLC / CV / TEM / …
- **Observation**: what the tool/vision/arithmetic found, with the raw
  numbers (dHash distance / curve_r / noise_corr / the two values and their
  units)
- **Why suspicious**: one or two sentences — the integrity reading
- **Benign explanation (candidate)**: the strongest innocent account
- **Pressure test**: what was run to test it; outcome (survived / failed)
- **Needed to resolve**: exact raw data (Level ≥ 2) or "none — resolves from
  published material"
```

Every field filled — "Why suspicious" and "Pressure test" empty means the
finding is not ready; either fill it or drop it to a track-summary note.

## Final risk mapping (report header)

| Condition | 总体风险 |
|---|---|
| no findings, all tracks clean | Low |
| only Level 1 findings | Low–Medium |
| ≥ 1 Level 2, no convergence | Medium |
| Level 3 with a retraction-charge context, or several Level 2 on one figure | High |
| ≥ 1 Level 4 (independent lines converge), or notice charges reproduced | High / Critical (Critical only when the converged lines include both a pixel-level reuse AND a numeric inconsistency on the SAME data) |

The mapping is a starting point — the agent adjusts within one notch with a
one-line justification in the report.

## Report assembly (Chinese)

Copy `templates/audit_report.md` to `$RUN/audit_report.md` and fill in order.
Section discipline:

1. **报告头部** — paper identity (title, authors, journal, year, DOI),
   status (正常/撤稿/勘误 — with the notice URL if any), audit date, run dir,
   overall risk + one-paragraph summary of the strongest evidence chain.
2. **审计范围与方法** — what was acquired (manifest summary), parsing backend
   (native PDF via pdfplumber/pypdfium2, or MinerU local/cloud), table count,
   panel/image-asset counts, subfield class, which tracks ran fully /
   partially / not at all and why. Add a **覆盖与可复现性** line with
   reviewed / unresolved / unreadable / deferred image counts and the tool
   versions. If the retraction-notice checklist applies: one row per charge
   with 复现/无法复现/Level.
3. **发现（按 Level 降序）** — each finding: location, observation, why,
  pressure test, needed data. Cite the finding file path. Chemical formulas,
  oxidation states and level labels keep their PDF typography as Unicode:
  MgCo₂O₄, MgCo₂O₄@ZnS, 2p₃/₂, Co³⁺ — never MgCo2O4, 2p3/2 or Co3+.
  Every Level ≥ 2 finding also gets an `**证据图**` block with two images:

   ```markdown
   ![D5-F2 原文页面](findings/image/D5-F2_source.png)
   *PDF 第 7 页 / 原文 Fig. 2；红框为问题区域。*

   ![D5-F2 局部放大](findings/image/D5-F2_crop.png)
   *红框区域 2× 放大。*
   ```

   Generate them with `report_figures.py` (PDF page or figure image). The red
   box must tightly enclose the complete problem panel — plot area, panel
   label and axis titles — not body text, page headers or unrelated white
   space; adjacent duplicated panels may share one box. For a PDF source,
   use normalized coordinates and state the page. For a PMC figure, state
   "PMC 图件，无页码" — do not invent a page number. Table findings use
   `render_evidence_tables.py` for XLSX or
   `render_pdf_table_evidence.py --rows … --cols …` for a PDF table; otherwise
   keep the Markdown table and say the cell image is unavailable. Level 1
   findings carry an image or a table too; a negative scan (0 copied
   segments) uses a result table, never an invented red box.
4. **各线小结** — numerical / image / logical: what ran, lead counts,
   clean vs inapplicable status.
5. **需作者提供的原始数据** — the union of all findings' "needed to
   resolve", deduplicated, one numbered list. This section is what makes the
   report usable by an integrity office.
6. **局限性** — MinerU extraction quality (tables parsed from markdown HTML;
   SI text coverage), PDF raster resolution (150/300 dpi), fingerprint
   method limits (log axes, smoothing, re-digitization), sample-size limits
  (Benford gating), anything blocked by paywall.
7. **质量门自检** — the checklist below, checked.

## Quality gate (run before delivery — all must be true)

- [ ] every Level ≥ 2 finding has a location pointer that resolves to a
      real file/line in `$RUN/`
- [ ] every Level ≥ 2 finding has a completed 压力测试 (failed) section
- [ ] every Level ≥ 2 finding has a 证据图 block whose source/crop paths
      resolve; PDF sources name the page, PMC figures say "PMC 图件，无页码"
- [ ] chemical formulas and level labels use Unicode sub/superscripts
      (MgCo₂O₄, 2p₃/₂, Co³⁺), matching the PDF; no MgCo2O4 / 2p3/2 / Co3+
- [ ] `audit_report.pdf` was rendered (A4) and its evidence images resolve
- [ ] no finding asserts "造假"/"fraud" as conclusion (grep the report for
      造假|fraud|fabricat — allowed only in quoted notice text or in
      "高度疑似失实" Level-4 framing)
- [ ] `_clean.md` / `_inapplicable.md` present for ALL THREE tracks (no
      silent empty directories)
- [ ] §2 states the parsing backend, table count, and reviewed/unresolved
      image-asset coverage
- [ ] manifest lists every artifact examined; nothing graded from a file
      not in the manifest
- [ ] retraction-notice charges (if any) each have a row in §2
- [ ] the 需作者提供的原始数据 list is the deduplicated union of finding
      asks — no asks appear only in the report
- [ ] numbers in the report were copied from the tool JSONs / finding files,
      not retyped from memory (spot-check 3 random values against
      `chem_numeric.json` / fingerprint JSONs)
- [ ] every multi-panel figure has a panel count from `panel_split.py`
      (with `--json`/`--debug`) and the count is reconciled with the caption;
      unsplit montages are listed as a coverage gap in 局限性
- [ ] every line-plot figure was run through `spectral_segment_dup.py`
      (within-trace and, where relevant, between-trace), and the result file
      is in `workdir/`
- [ ] `evidence_ledger.json` reports `tables > 0` when `full.md` contains
      HTML tables; numeric findings cite table id + row + column + original
      value, not just a line number
- [ ] image-threshold calibration is recorded (`calibrate_image_thresholds.py`
      report) or the report states "阈值未标定（默认值）"
- [ ] report renders (tables intact, no placeholder text left, no English
      sentence where Chinese is required — technical terms excepted)

Delivery: the four paths (manifest, findings tree, `audit_report.md`,
`audit_report.pdf`) + one-paragraph summary in the chat, starting with the
overall risk and the single strongest evidence chain.
