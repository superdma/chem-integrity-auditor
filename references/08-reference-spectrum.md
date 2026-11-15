# 08 — Reference-spectrum track (copied database spectra)

One named retraction pattern in chemistry: a paper's "measured" NMR (or IR,
MS) spectrum is a **database spectrum** — SDBS, NMRShiftDB, a vendor library
— re-plotted with new labels. The tell is not that the peaks match a real
compound (they should); it is that the peak list matches a *reference
recording* far more closely than an independent measurement of the same
compound can, or that the paper claims originality while the data are
verbatim library output.

This track is **semi-automatic**: the script digitizes the paper's peak
positions and scores them against a reference peak table; the auditor
decides what the score means in the paper's own context.

## 0. Before you run — obtain a reference peak table

- **SDBS** (AIST): free web search by compound name/CAS/formula; each record
  shows a peak list. **Do not scrape the site** — its terms do not invite
  automated access. Export/paste the peak list into a CSV or a text file
  (one shift per line, shift first). Record the SDBS serial number and the
  retrieval date in `input_manifest.md`.
- **NMRShiftDB2**: record pages expose predicted/experimental shifts; copy
  the experimental shift list into a file. The public RPC endpoint is not a
  stable machine API — treat it as a manual export too.
- **Paper's SI / a genuine standard run**: a peak table from the SI of a
  *different* paper for the same compound is also usable, provided you note
  the source and that it is an independent measurement.
- Reference files must be one peak per line. Accepted formats:
  - CSV/TSV: `shift,intensity` (header rows without a leading number are
    skipped)
  - TXT: line starts with the shift (`7.26  2.0  s`), SDBS export style
  - JSON: `[7.26, ...]`, `[{"x":7.26,"intensity":2.0}]`, or `{"peaks":[...]}`

## 1. Digitize the published spectrum

The tool traces the topmost dark pixel per column inside the plot frame and
converts pixels to axis units using two calibration points you supply.

```bash
python3 <skill>/scripts/reference_spectrum_match.py \
    --sample-image "$RUN/panels/fig2b.png" \
    --sample-x0 '120:8.0' --sample-x1 '980:0.0' \
    --technique h1nmr \
    --ref "$RUN/reference/sdbs_12345.csv" \
    --annotate "$RUN/workdir/fig2b_peaks.png" \
    --output "$RUN/workdir/refmatch_fig2b.json"
```

Calibration: `PIXEL:VALUE` at the left and right ends of the **plotted
axis** (not the whole image). NMR x-axes decrease left→right, so
`--sample-x1` value < `--sample-x0` value is normal. Read the two pixel
positions off the axis ticks (or with an image viewer) — a 1 % calibration
error moves a 7 ppm peak by ~0.07 ppm, which matters at the default
tolerance.

If the paper already prints a peak list (common in SI), skip digitization:

```bash
python3 <skill>/scripts/reference_spectrum_match.py \
    --sample-peaks si_compound5a_peaks.csv --technique h1nmr \
    --ref sdbs_12345.txt --ref-format text --output ...
```

## 2. Read the score

`score = 0.75 × recall + 0.25 × precision`, where recall = fraction of
reference peaks found in the sample. Recall dominates because a real
spectrum legitimately carries solvent/impurity peaks absent from a
reference table.

| score | verdict | reading |
|---|---|---|
| ≥ 0.90 | `very_high` | every reference peak present at the right position — consistent with a copied library spectrum **or** a clean measurement of the same compound |
| 0.75–0.90 | `high` | most reference peaks present; a few at the tolerance edge |
| 0.55–0.75 | `partial` | same compound plausible, but conditions/purity differ — weak evidence either way |
| < 0.55 | `low` | not the reference compound, or calibration/digitization failed |

Always report alongside the score: `n_matched / n_reference`, `rmsd` of
matched peaks, tolerance, technique/unit, and the reference source + serial
number.

## 3. What turns a match into a finding

A database match alone is **not** a finding. Build the finding only when a
second, independent line points the same way:

- The paper calls the compound **new** (or the spectrum "representative of
  our synthesis") and the reference is a published spectrum of a known
  compound — novelty claim + verbatim peak list.
- The same "measured" spectrum appears in **two papers** by different
  groups, or in the paper and the SI with different compound labels.
- The plot has **noise/texture inconsistent with a real acquisition**:
  perfectly smooth baseline, no solvent peak where one must appear,
  axis tick spacing that drifts (scanned-and-rescaled), identical noise to
  another panel (run `spectral_noise_fingerprint.py` on the pair).
- The peak list contains **more precision than the plotted spectrum can
  support** (e.g. 0.001 ppm values read off a low-resolution raster).
- The paper reports a **different solvent/temperature** than the reference
  record, yet every peak including solvent-sensitive ones is identical.

## 4. Benign explanations to kill first

- Same real compound measured on the same instrument model → peak positions
  legitimately agree to <0.01 ppm; a `very_high` score is expected and
  meaningless on its own.
- Reference and sample both processed with the same software/baseline
  correction → shared minor artifacts.
- The paper reused its **own** earlier published spectrum and cites it
  ("as previously reported") — legitimate; check the citation.
- Broad multiplets collapse to one maximum in raster digitization, so
  `n_sample < n_reference` is normal for 1H NMR; do not read missing
  multiplet components as mismatch.
- Calibration error moves all peaks coherently: if `rmsd` is large but the
  offset is nearly constant, recalibrate instead of grading (the script
  reports per-peak `delta`; a constant delta = calibration bug).

## 5. Track output

- Surviving anomaly → `findings/image/<short-id>.md` (the evidence is the
  figure/peak list; the match JSON is the numeric support), e.g.
  `fig2b-nmr-vs-sdbs-12345`, `si-5a-spectrum-copied`. Name both sources,
  the score and the second evidence line.
- All matches explainable → `findings/image/_clean.md` listing the pairs
  compared, scores, and why each died.
- No reference table obtainable → record the attempt in the manifest and
  say "参考谱不可得，本项未审计" — never substitute a guessed reference.

## Limits

- Digitization is only as good as the raster: overlapping multiplets,
  truncated axes, log scales and hand-drawn spectra break the trace.
- A **low** score never proves independence: the authors may have
  re-drawn/rescaled the database spectrum (use the noise fingerprint),
  or the reference table may be from different conditions.
- SDBS/NMRShiftDB coverage is uneven; absence of a matching record proves
  nothing.
- This track checks peak *positions*. It does not check integrals, coupling
  constants, or line shapes — those need a vision pass on the panel.
