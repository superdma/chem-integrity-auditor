# 04 — Image track playbook

Pixel-level evidence only. The image track answers: *do two (or more)
figures/panels come from the same source data or source image?* It never
answers "is this real chemistry" — that is the logic track.

## Prerequisites

- `$RUN/panels/` populated by poppler (Step 2). Record the count.
- For SI figures: poppler the SI PDF too, prefix `si-`.
- Multi-page figures: `pdfimages -all` gives one PNG per embedded raster;
  a figure spanning two PDF images (e.g., 4a+4b as separate rasters) is
  usually fine — the inventory maps each panel PNG to its figure label via
  page position.

## Pipeline

```bash
# 1) Split multi-panel figures (whole-figure hashing finds almost nothing)
python3 <skill>/scripts/panel_split.py panels/page-XXX-YYY.png workdir/panels_split/... \
    --json workdir/panels_split/figX.json --debug workdir/panels_split/figX_debug.png

# 1b) Stacked traces in ONE panel (Raman/XRD/XPS, black rule separators):
#     panel_split finds no white gutter here. Colour isolation matters —
#     otherwise ORB matches the legend text instead of the curve.
python3 <skill>/scripts/stack_split.py fig2.png workdir/bands_fig2/ --keep-color auto

# 2) Phash sweep over ALL panel PNGs (article + SI + splits)
python3 <skill>/scripts/image_dup.py workdir/panels_all/*.png \
    > workdir/image_sweep_phash.txt
# dHash hamming: <10 strong duplicate candidate · 10–60 escalate · >60 different

# 3) ORB escalation for 10–60 pairs AND for any same-technique pair the
#    inventory says "should be comparable" (ORB catches transform reuse that
#    phash misses: flip, rotate, crop, brightness)
python3 <skill>/scripts/image_dup_orb.py a.png b.png
# ≥30 matches strong · ≥12 weak/inconclusive

# 4) Spectral fingerprint for same-technique LINE-PLOT pairs
python3 <skill>/scripts/spectral_noise_fingerprint.py a.png b.png \
    --out workdir/fp_a_b.png.json --save-crops workdir/fp_a_b

# 5) Segment-level reuse: within one trace and between two traces
python3 <skill>/scripts/spectral_segment_dup.py --image fig2a.png \
    --out workdir/segment_fig2a.json --annotate workdir/segment_fig2a_marked.png
python3 <skill>/scripts/spectral_segment_dup.py --image fig2a.png \
    --image fig2b.png --out workdir/segment_fig2a_2b.json
```

Persist every pair's result file as you go (`fp_<A>_<B>.json`) — a sweep of
40 panels is ~800 pairs; run same-technique pairs only (the technique
inventory defines the pool), which for a typical chemistry paper is 30–120
pairs. Log the pair list in `workdir/image_sweep.json` (which pairs ran,
which were skipped as different-technique, which were inapplicable
(photo/2D)).

## Interpreting spectral_noise_fingerprint.py

| Report fields | Reading |
|---|---|
| `curve_r ≥ 0.995` | identical signal to the digit — copy |
| `curve_r 0.97–0.995` | same data within rendering noise — relabeled/re-plotted candidate |
| `curve_r 0.85–0.97` | same peak pattern — MAY be legitimate independent measurement of the same sample; the noise metrics decide |
| `curve_r < 0.85` | no reuse signal in the signal itself |
| `noise_corr` / `bg_line_corr` ≥ 0.6 | shared background texture — both panels from one source image (strongest pixel evidence) |
| both noise metrics < 0.15 AND curve_r ≥ 0.85 | `same_curve_independent_noise` — either independent measurement or a re-draw from shared raw data. For "independent replicate" claims, the re-draw IS the fraud scenario; for same-sample re-characterization, it can be legitimate. Resolve by context + vision. |
| `noise_incomparable` | flat white backgrounds (vector PDFs, lossless re-plots) — the fingerprint degenerates to curve_r only; ALWAYS add a vision pass on such pairs before concluding. |
| `brightness_delta` large, curve_r ~1 | white-point shifted copy (classic relabeling) |

Empirical anchors from a completed audit (Dasari 2010, gels): reused
panels r = 0.82–0.93, independent controls r ≤ 0.38. Chemistry line plots
are cleaner than gels — expect the independent end to be lower, but treat
0.85+ with shared noise as the practical reuse line.

**Same-source crops are not independent evidence.** Traces cut from ONE
published image (e.g. `stack_split.py` bands of Fig. 2) share that image's
JPEG blocks and rendering texture by construction. `noise_corr ≥ 0.6` on
such a pair is expected and must NOT be cited as reuse evidence; use ORB
feature matches and the curve shape instead. Noise correlation is only
informative between panels that came from *different* source images
(different figures, article vs SI, two papers).

**Method limits (always in the finding file)**: linear axis rescaling is
absorbed; log axes, truncated windows, smoothing filters, re-digitization
(JPEG), and hand-redrawing are NOT. A negative fingerprint result therefore
means "no pixel-level reuse detected", never "independently measured".

## Segment-level duplication (spectral_segment_dup.py)

Whole-panel hashing/ORB cannot see a copied 30–80 px stretch of one curve.
The script slides a full-height patch across the plot box and computes
`TM_CCOEFF_NORMED` against the same panel (within-trace) or the other panel
(between-trace). Overlapping positions are masked; matches are deduplicated
by non-overlap, so a copied region yields one row, not 20 adjacent ones.

| Score | Reading |
|---|---|
| `score ≥ 0.995` | pixel-level identical stretch — strongest segment evidence |
| `0.985–0.995` | near-identical after JPEG/render — candidate; inspect the crop |
| `< 0.985` | below the default gate; do not report as a finding |

Benign explanations to test before grading: a periodic lattice/fringe
pattern (XRD, HRTEM), a repeated calibration pulse (CV/EIS), a reference
peak deliberately plotted twice, or a fit/residual curve that shares the
data curve's shape. Annotate the two regions and compare them visually; a
copied segment usually also breaks the surrounding noise continuity.

The fallback (no OpenCV) uses high-passed 1D profiles with Fisher-z p-values
and Benjamini-Hochberg q-values. It is weaker; if OpenCV is missing, install
it before relying on a negative segment result.



## Copy-move inside one panel (`image_copy_move.py`)

Phash and pairwise ORB compare different panels. A region pasted elsewhere in
the *same* panel needs self-matching:

```bash
python3 <skill>/scripts/image_copy_move.py panels/fig4a.png \
    --out workdir/copy_move_fig4a.json \
    --annotate workdir/copy_move_fig4a_marked.png
```

The script matches ORB descriptors against the same image (excluding the
keypoint itself), keeps geometrically consistent clusters with a RANSAC
homography/affine model, then warps the target back onto the source and
requires pixel agreement (`ncc ≥0.90`, `mean_abs_diff ≤18`). That last check
is what suppresses repeated axes, labels and similar-looking panels. Output:
`source_bbox`, `target_bbox`, `displacement`, `inliers`, `mean_residual_px`,
`ncc`, `mean_abs_diff` and `inlier_fill`. It returns one region per copied
area, not the same pair twice in both directions.

Reading guide:

| Signal | Reading |
|---|---|
| ≥12 inliers, residual ≤2 px, area ≥0.2%, NCC ≥0.90 | candidate copied region; inspect the annotation |
| inliers 6–11, residual >3 px, or NCC <0.90 | weak/inconclusive; the pixels did not survive warping |
| `mean_abs_diff` >18 | reject; similar-looking panels and repeated axes are not copies |
| boxes overlap (IoU >0.30) | same region, not a moved copy — suppressed |
| repeated scale bar, calibration pulse, tiled background | benign explanation; test before grading |

False positives rise on symmetric objects, regular grids, and images with one
dominant texture. Always open the annotated PNG and compare the surroundings:
a real paste usually breaks the local noise/background continuity at the box
edge. This is pixel evidence, not proof of intent.

## Threshold calibration (calibrate_image_thresholds.py)

The dHash/ORB/curve thresholds are defaults. To calibrate:

```bash
python3 <skill>/scripts/calibrate_image_thresholds.py \
    --manifest tests/fixtures/calibration/manifest.json \
    --output workdir/calibration.json
```

Manifest rows: `{"a": "...", "b": "...", "label": "duplicate|different|same_compound|different_compound", "technique": "raman"}`.
The report gives ROC/AUC and the Youden-J threshold per metric. A useful set
is 30–50 pairs per technique, with **hard negatives**: same compound measured
independently, same phase different sample, same technique different peak
window. Record the calibration file in `input_manifest.md`; when no set
exists, say "阈值未标定（默认值）" in the finding and keep it Level 1 unless
a second independent line exists.

## Phash/ORB interpretation

- dHash <10: same pixels (possibly cropped/offset). Level 2 candidate
  minimum; check labels — same sample re-shown legitimately (caption says
  "same as Fig X") dies to a note; different labels = Level 2–3.
- ORB ≥30 with phash in the 10–60 zone: transform reuse (flip/rotate/crop/
  brightness). Level 2 candidate; describe the transform in the finding
  (ORB matches give correspondence — note the dominant shift/flip).
- ORB 12–29: inconclusive — vision pass decides.
- Schematics and diagrams: exclude from pixel forensics (record in the
  inventory); they ARE checked for figure-vs-text consistency in the logic
  track.

## Scale-bar measurement (TEM/SEM/AFM) — vision recipe

For every microscopy figure with a scale bar:

1. Read the stated magnification or bar length from the caption
   (e.g., "scale bar, 50 nm").
2. Ask vision: "Measure the scale bar in pixels (report length and its y
   position). Describe the bar's appearance." Do this for the bar in each
   panel.
3. Cross-check: two panels with the **same stated magnification** must have
   bars of equal pixel length (±15%). Same sample shown at "different"
   magnifications: bar length ratio should match magnification ratio.
4. A 50 nm bar on an image whose caption says 200 nm elsewhere for the same
   FOV, or bars of different pixel length at identical magnification →
   Level 2 candidate (scale-bar tampering is a named retraction charge in
   microscopy papers).

## Vision pass on candidates (standing rules)

- Prompt for **concrete identity**: peak positions and heights, noise
  texture, baseline shape, axis ticks and their values, labels, scale bar,
  any text embedded in the image. Then: "what differs between these two?"
- Never ask vision "is this fraudulent?" — it will confabulate a verdict.
- Ask for differences, not conclusions: two "identical" spectra where the
  labels differ in ONE digit (compound 3 vs compound 8) is the finding; the
  digit, not the guilt.
- Re-extract the suspect figure at higher DPI before concluding
  (`pdftoppm -r 300 -f <p> -l <p>`): a phash hit at 150 dpi must survive at
  300 dpi. A hit that dissolves at higher resolution is a rendering
  artifact, not reuse.

## Track output

- Confirmed anomalies → `findings/image/<short-id>.md` (format in 06),
  short-id like `fig4b-vs-fig7a-xrd`, `tem-scalebar-fig5`,
  `si-nmr-solvent-mismatch`.
- Every finding must name: figure ids + panel file paths + page, the tool
  that found it + its numeric output (dHash distance / ORB matches /
  curve_r / noise values), the labels of both panels, and the transform
  (if any).
- No anomalies → `findings/image/_clean.md` with sweep stats (panels,
  pairs run, threshold crossings, all below threshold).
- Paper with no pixel-forensicable figures (pure schematics + tables) →
  `findings/image/_inapplicable.md` naming the excluded figure types and
  the substitute check (figure-vs-text consistency in the logic track).
