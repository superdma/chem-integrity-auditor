# Changelog

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
