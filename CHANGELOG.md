# Changelog

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
