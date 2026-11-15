# Gold set — five retracted OA chemistry papers

Purpose: measure whether the pipeline reproduces the **specific charges** in
each retraction notice, not whether it can produce a long list of anomalies.

## Protocol

For each paper:

1. Fetch the original article with `pmc_fetch.py` (PMC route) and the notice
   text from `notice_pmcid`.
2. Write `claim_checklist.md`: one testable hypothesis per notice charge.
3. Run the full pipeline: ledger, numeric, NMR/HRMS, structure, panel split,
   phash/ORB, fingerprint, segment duplication.
4. For each charge: `reproduced` / `not reproduced at available resolution`
   / `not applicable`. A charge that cannot be tested is Level 3, not clean.
5. Record the per-charge outcome in `gold_summary.md` and aggregate recall.

Run outputs (`gold/raw/`, reports, figures) are **not committed**: the figures
remain publisher copyright and the run directories are large. Commit only
the manifest, checklists, and aggregate summary.

## Files

- `manifest.json` — five papers and their notice charges.
- `run_paper.py` — deterministic sweep (ledger, numeric, NMR/HRMS, panel
  split, stack split, phash/ORB, fingerprint, segment scan, summary.json).
- `summarize_run.py` — triage view: only strong ORB, high fingerprint and
  segment hits, so the auditor knows what to inspect.
- `checklists/<paper-id>.md` — per-charge outcome and level.
- `gold_summary.md` — aggregate recall and the pipeline changes the gold set
  forced.

## Known issue (resolved)

The first `d5ra01695a` run directory was deleted by an accidental
`rsync --delete-excluded`. It was regenerated from PMC on 2026-11-15; the
checklist and aggregate summary use the regenerated run. Never use
`--delete-excluded` when syncing the repository into a skill directory.
