# Gold-set recall — five retracted OA chemistry papers

Measured 2026-11-15 with `tests/gold/run_paper.py` on the five manifest
papers. Outcomes are per **notice charge**, not per paper. “Reproduced” means
the deterministic pipeline produced evidence that supports the specific
charge at the stated level; it is not a fraud verdict.

## Aggregate

| Outcome | Count | Charges |
|---|---|---|
| **Reproduced (Level 3 lead)** | 2 / 13 | d5ra01695a between-spectra duplication; d4na00372a EDX Fig. 4a↔c shared noise |
| **Partially reproduced (Level 2)** | 3 / 13 | d2ra07661f idealised XRD trace; d0ra09390d Fig. 2 and Fig. 8b XRD similarity |
| **Not reproduced at available resolution** | 3 / 13 | d5ra01695a within-spectrum copy; d4na00372a Fig. 4b repeating pattern and Fig. 4b↔c similarity |
| **Not testable** | 5 / 13 | all four “first published in ref. 1” claims + the d2ra07661f raw-data claim |

- 2/13 (15 %) fully reproduced, 5/13 (38 %) reproduced or partially reproduced.
- 5/13 are **cross-publication** claims. The pipeline has no prior-paper
  corpus and the cited references are paywalled; these are recorded as
  Level 3 (untested), not as clean.
- 0 false “fraud” verdicts: every strong hash/ORB/fingerprint hit was either
  matched to a notice charge or explained as benign (same phase, same sample
  at another magnification, CV family, periodic lattice, repeated icon).

## Per paper

| Paper | Charge | Track that decided it | Outcome |
|---|---|---|---|
| d5ra01695a | Raman Fig. 2 duplications within spectra | patch-NCC on isolated bands | not reproduced |
| d5ra01695a | Raman Fig. 2 duplication **between** red/blue | ORB 63/51 + noise 0.60 | **reproduced** |
| d2ra07661f | XRD Fig. 1 inconsistent with genuine measurement | trace geometry (3–6 px FWHM, 0.52 px baseline σ) | partial L2 |
| d2ra07661f | “raw data” explanation rejected | raw counts not in article | not testable |
| d2na00842d | Fig. 1/3 first published in ref. 1 | cross-paper corpus | not testable |
| d2na00842d | Fig. 2b SEM prior + edited | within-figure ORB/phash | not testable / not reproduced |
| d4na00372a | Fig. 3e FESEM prior publication | cross-paper corpus | not testable |
| d4na00372a | Fig. 4b repeating patterns | segment scan | not reproduced (resolution) |
| d4na00372a | Fig. 4a↔c similarity | fingerprint noise 0.81 | **reproduced** |
| d4na00372a | Fig. 4b↔c similarity | fingerprint noise 0.28 | not reproduced |
| d0ra09390d | Fig. 5 FTIR prior publication | cross-paper corpus | not testable |
| d0ra09390d | Fig. 2 XRD partially identical | trace profile r ≈ 0.90 | partial L2 |
| d0ra09390d | Fig. 8b before/after identical | ORB 35/29 + curve_r 0.67 | partial L2 |

Per-charge detail: `checklists/<paper-id>.md`.

## What the gold set changed in the pipeline

1. **Stacked traces are now first-class.** `panel_split.py` recognises a
   full-width, equally spaced stack as *one* panel instead of counting its
   divider rules as panels; `run_paper.py` then runs `stack_split.py
   --keep-color auto` per panel and compares the isolated traces. This is what
   exposed the d5ra01695a red↔blue duplication and removed the previous
   undercount on its Fig. 1/2.
2. **Parent/band pairs are excluded.** A colour-isolated band is never
   compared with the panel it was cut from, which previously produced
   guaranteed false “duplicates”.
3. **Segment scan is quieter.** Flat low-contrast patches and adjacent windows
   are skipped (two FTIR/EDX false positives disappeared), while genuine
   periodic hits (crystal lattice, repeated K⁺ icon, repeated 4/3 symbols)
   remain and are explained as benign in the checklists.
4. **New triage view.** `tests/gold/summarize_run.py` prints only the pairs an
   auditor should inspect; the raw JSON stays the source of truth.

Smoke suite after these changes: **59 passed, 0 failed**.

## Known limits

- No cross-paper figure corpus → prior-publication charges cannot be tested.
  A future extension is a local corpus of reference figures/peak tables keyed
  by DOI, with manual export only.
- Offset-stacked traces without separator rules (d0ra09390d Fig. 2/5/8b,
  d2na00842d Fig. 1) are not isolated by the current splitter; those checks
  used manual colour-mask profiles or coarse crops.
- Raw-count authenticity (d2ra07661f) is outside an image/PDF pipeline.
- The initial d5ra01695a run was lost to an accidental `rsync
  --delete-excluded`; it was regenerated from PMC, and the destructive
  rsync pattern is no longer used.
