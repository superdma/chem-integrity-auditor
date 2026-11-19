# Changelog

## Unreleased

### Added

- `source_data_audit.py` — workbook-level screening for XLSX/CSV/TSV:
  duplicate rows/columns, constant difference/ratio, near-perfect correlation,
  arithmetic-progression runs, mixed precision, last-digit Mode A/B and
  repeated decimal tails, with file/sheet/row/column provenance.
- `image_copy_move.py` — within-one-image ORB self-matching plus RANSAC
  homography/affine, reporting source/target boxes, displacement, inliers and
  an optional annotated PNG.
- `audit_run_manifest.py` — run reproducibility inventory with input SHA-256,
  dependency versions, evidence counts, per-track coverage and explicit gaps.
- `report_cards.py` now renders an optional “审计材料与覆盖” panel from
  `audit_run_manifest.json`; missing tracks are shown as gaps, not clean
  results.
- Native PDF backend — `pdf_native_extract.py` uses `pdfplumber` for text and
  ruled tables and `pypdfium2` for figure crops, writing `full.md`,
  `tables.json`, `figures.json` and `native_manifest.json`. `mineru_convert.py
  --backend-mode auto` tries it first; scanned/complex PDFs fall through to
  MinerU. No MinerU service or token is needed for born-digital PDFs.
- `render_pdf_table_evidence.py` — PDF table to a PNG evidence card with
  row/column highlighting and a manifest, complementing the XLSX card
  renderer.
- Card-based report layout — `render_report_pdf.py --layout cards` (default)
  renders a paper header with risk badges, a findings index, per-finding cards
  and an evidence grid, while `--layout classic` keeps the old plain layout.
  `report_cards.py` parses the Markdown report into that structure.
- `report_figures.py` — builds an annotated source page/figure with a red
  problem box and an enlarged crop, plus a manifest and optional Markdown
  block. Supports PDF pages (normalized boxes) and PMC/figure images (pixel
  boxes).
- Report template now requires an `证据图` block for every Level ≥ 2 finding:
  source with red box, crop, and a page label (or “PMC 图件，无页码”).
  Level 1 findings carry an image or a result table; negative scans must not
  invent a red box.
- `report_gate.py` fails a Level ≥ 2 finding without `证据图` or without a
  resolving image path.
- Reports must reproduce the PDF's chemical typography with Unicode
  sub/superscripts (`MgCo₂O₄`, `2p₃/₂`, `Co³⁺`); the gate rejects compact
  spellings such as `MgCo2O4`, `2p3/2`, and `Co3+`.
- `render_report_pdf.py` — renders the Markdown audit report to an A4 PDF
  with inline evidence figures, intact tables and optional `N / M` page
  numbers, using headless Chrome/Chromium.
- `report_figures.py` red boxes now use a thinner 3–8 px stroke and target
  the complete problem panel (plot area, panel label, axis titles), so the
  crop matches the cited panel without body text or unrelated margins.
- Smoke section 28 covers the annotated source/crop outputs; section 27 now
  also rejects a report missing its evidence image or containing an
  unformatted chemical formula; section 29 verifies A4 PDF text and embedded
  images; sections 30–31 cover native PDF extraction and the report-card
  parser (84 checks; PDF check is SKIP without Chrome).

### Fixed

- `spectral_segment_dup.py` no longer crashes when two compared plot boxes
  have different heights; B is resized to A's plot height before the
  full-height template match.
- The PDF smoke check no longer assumes a Chinese title is extractable from
  Chrome's PDF on every runner; it normalizes whitespace and accepts a Latin
  marker (`XRD` / `DOI`) as evidence that text was embedded. Chrome also gets
  `--disable-dev-shm-usage`, and CI uploads `smoke.log` when the job fails.
- `calibrate_image_thresholds.py` computes ROC AUC with a local trapezoid
  loop instead of `np.trapz`, which NumPy 2.4 removed. GitHub Actions smoke
  now passes on Python 3.11 with the current NumPy release.

### Changed

- CI prints Python paths and annotates the failing smoke section, including
  the traceback, when the suite fails.
- Report template asks for a parsing backend plus reviewed/unresolved image
  coverage; the report gate now attributes the last finding to its own Level
  heading, and accepts Windows drive-letter evidence paths.
- `requirements.txt` and `check_env.py` include `pdfplumber` (native PDF) and
  `pypdfium2` (figure crops); native text/tables work without poppler.
- Windows support: `check_env.py` and `render_report_pdf.py` discover Chrome
  and Edge in their standard `Program Files` / `%LOCALAPPDATA%` locations,
  `render_evidence_tables.py` falls back to Windows CJK fonts,
  `image_dup_orb.py` loads images through `np.fromfile` + `cv2.imdecode` so
  non-ASCII paths work, `mineru_convert.py` rejects ZIP members that escape
  the output directory, and `report_gate.py` accepts `.\`-prefixed evidence
  paths. README, SKILL, and the MinerU reference now document PowerShell
  commands and the WSL2 recommendation. `tests/smoketest.sh` honours
  `PYTHON` and falls back to `python`.

## 0.5.1 — 2026-11-15

Follow-up to the comparison with
`cylqwe7855-alt/research-integrity-auditor`.

### Changed

- `render_evidence_tables.py` imports `openpyxl` lazily with an actionable
  install message, falls back across Linux CJK / macOS / DejaVu fonts instead
  of macOS-only paths, and uses Pillow < 8 text/box fallbacks. Verified under
  Pillow 7.0 and Pillow 10.4.
- `check_env.py` reports `openpyxl` as optional; README documents it for
  XLSX table evidence cards.
- `ACKNOWLEDGEMENTS.md` records that `numeric_forensics.py` and
  `render_evidence_tables.py` also exist byte-for-byte in the public
  comparison project, from the shared `paper-fraud-auditor` lineage.

## 0.5.0 — 2026-11-15

Packaging and methodology ideas from the public
`cylqwe7855-alt/research-integrity-auditor` project.

### Added

- `package.json` + `bin/install.js` — one-command install
  (`npx github:superdma/chem-integrity-auditor`), with `--project`,
  `--skills-dir`, and `--target`. The installer copies the skill payload only;
  it never installs Python dependencies or writes tokens.
- `agents/openai.yaml` — display name, short description, and default prompt
  for generic Agent clients.
- `references/11-methodology-and-chains.md` — one-page audit order and
  “anomaly network”: image identity conflicts, reverse-generated values,
  terminal digits, template trends, author-response pressure tests, and a
  strong-evidence-chain table. Adapted to chemistry; explicitly attributed.
- README install method A (npm), structure, and acknowledgement updates.

### Changed

- SKILL Step 7 now asks for an independent second evidence line before
  escalating above Level 2.

## 0.4.0 — 2026-11-15

Closes the three gaps recorded in the 0.3.0 gold summary.

### Added

- `scripts/corpus_add.py` + `scripts/corpus_match.py` — local, manually
  exported reference-figure corpus; query figures/panels against it with
  dHash + ORB + RANSAC for “first published in ref. 1” charges. No scraping.
- `scripts/offset_stack_split.py` — semi-automatic split of offset-stacked
  traces without separator rules: `--propose`, `--traces N`, `--cuts`.
- `scripts/report_gate.py` — executable report quality gate: sections 1–7,
  five fields per Level ≥ 2 finding, resolvable paths, placeholders, verdict
  words, track statuses, section-7 checklist.
- `references/10-corpus-and-gate.md`; README/SKILL integration.
- Smoke sections 25–27 (70 checks total).

### Changed

- README status no longer lists the three gaps; it names corpus seed data as
  the remaining manual step.
- `tests/make_fixtures.py` adds an offset two-trace fixture and valid/invalid
  report fixtures.

## 0.3.0 — 2026-11-15

Gold-set batch: five real retraction notices, NMR/HRMS checks, and stacked-trace
support.

### Added

- `scripts/nmr_hrms_numeric.py` — 1H integration, 13C signal count vs formula,
  impossible/duplicate shifts, RDBE, nitrogen rule, and natural-abundance
  M+1/M+2 isotope comparison.
- `tests/gold/` — manifest, `run_paper.py`, `summarize_run.py`, per-paper
  checklists and `gold_summary.md`; five retracted OA papers, 13 notice
  charges, per-charge outcomes.
- `README.md` installation-by-link section (agent prompt, Claude Code,
  Cherry Studio, ZIP) and `ACKNOWLEDGEMENTS.md`; MIT `LICENSE`.
- Smoke coverage for NMR/HRMS (59 checks total).

### Changed

- `panel_split.py` recognises a full-width equally spaced stack as one panel,
  so stacked Raman/XRD traces are no longer miscounted as separate panels.
- `run_paper.py` splits each panel with `stack_split.py --keep-color auto`,
  compares isolated traces, and never compares a band with its parent panel.
- `spectral_segment_dup.py` skips low-contrast patches and a wider overlap
  neighbourhood; this removed flat-baseline false positives while keeping
  genuine periodic hits.

### Measured

- Gold-set recall: 2/13 charges fully reproduced, 3/13 partial, 3/13 not
  reproduced, 5/13 untestable cross-publication claims. Details in
  `tests/gold/gold_summary.md`.
- Real MinerU cloud v4 (`pipeline`) run on the 1-page mock PDF succeeded;
  token came from a temporary 0600 env file and was deleted afterwards.
- Smoke suite: 59 pass, 0 fail.

## 0.2.0 — 2026-11-15

Optimization batch after the `d5ra01695a` end-to-end audit.

### Added

- `scripts/spectral_segment_dup.py` — within-trace / between-trace copied
  segment detection with full-height patch NCC, non-overlap dedupe, optional
  annotation; profile-Pearson + Fisher-z + BH fallback when OpenCV is absent.
- `scripts/calibrate_image_thresholds.py` — labelled-pair manifest →
  ROC/AUC/Youden-J thresholds for dHash, ORB, curve_r, noise.
- `scripts/check_env.py` — Python/package/poppler/MinerU environment check.
- `requirements.txt`, `.github/workflows/smoke.yml`, this changelog.
- `panel_split.py --json` and `--debug` evidence; multi-cue splitter combining
  plot-frame rules with ink/white/flat gutters.
- `build_evidence_ledger.py` indexes HTML `<table>` blocks from MinerU / PMC
  `full.md` at cell level.
- `image_dup_orb.py` reports RANSAC inliers, inlier ratio, target bbox, and
  writes `--json`.
- Smoke coverage for the above (56 checks).

### Changed

- `panel_split.py` defaults: `ink_thresh=0.005`, `min_gutter_px=2`,
  `min_panel_frac=0.15` for rows and `col_min_panel_frac=0.28` for columns.
  Verified on `d5ra01695a` Fig. 4 (6 panels), Fig. 5 (4), Fig. 6 (5).
- `image_dup_orb.py` strong flag now also requires `--min-inliers`
  (default 10) in addition to raw match count; "strong matches, weak
  geometry" is reported separately.
- Evidence-ledger tests now require `tables >= 3` and `cells > 0` on the
  HTML-table fixture.
- Quality gate adds panel-count reconciliation, segment-scan evidence,
  HTML-table provenance, and threshold-calibration disclosure.

### Fixed

- PMC Route B ledger reported `tables: 0` although `full.md` contained HTML
  tables; numeric findings had no cell-level provenance.
- Real multi-panel figures returned one panel under the old 18 px/98 % white
  rule, silently disabling panel-level ORB.
- ORB "81 matches" had no geometric support; it now carries RANSAC inliers
  and a bbox, making the evidence reviewable.

### Known gaps

- Calibration manifest is synthetic (5 pairs). A 30–50 pair per-technique
  set with hard negatives is still needed.
- Gold set is still one retracted paper; 5–10 are needed to estimate recall.
- Segment NCC does not survive rotation/perspective/strong rescaling.
- MinerU cloud is mock-tested; local real test used `flash` on a 1-page PDF.
