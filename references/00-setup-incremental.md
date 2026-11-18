# 00 — Incremental execution (read first)

A full chemistry audit does not fit in one turn. The only execution mode
that completes is **batch → persist → resume**: do a bounded batch, write all
state to `$RUN/`, then continue. If context is compacted mid-run, everything
you need to resume lives in `$RUN/`, never in the conversation.

## Batch plan (typical 12–30 page chemistry paper)

| # | Batch | Output written |
|---|---|---|
| 1 | Input setup, acquisition (article + SI + figures + retraction notice) | `input_manifest.md`, `paper.pdf`, `supplementary/`, `figures_hires/` |
| 2 | Parsing: native PDF (or MinerU fallback) → poppler panels → ledger | `workdir/full.md`, `workdir/evidence_ledger.json`, `panels/`, manifest update |
| 3 | Triage: subfield class + technique inventory | `paper_class.txt`, `technique_inventory.md` |
| 4 | Numeric scripts (both) | `workdir/chem_numeric.json`, `workdir/numeric_forensics.json` |
| 5–7 | Numeric track: verify + write finding files | `findings/numerical/*.md` |
| 8 | Image tools: panel split + phash sweep + ORB escalations + fingerprint pairs + segment-duplication scan | `workdir/image_sweep.json` (pair results), `workdir/segment_*.json` |
| 9–13 | Image track: vision pass on candidates, scale bars, write findings | `findings/image/*.md` |
| 14–16 | Logic track | `findings/logical/*.md` |
| 17–19 | Adversarial defense on every Level ≥ 2 candidate | finding files updated with `## 压力测试` |
| 20–21 | Grading + report assembly + quality gate | `audit_report.md` |

Batch boundaries are guidance, not law — smaller batches are safer, larger
ones only when a step is trivial. The rule: **never start a batch whose
inputs are not yet on disk.**

`mineru_convert.py --backend-mode auto` tries the native PDF backend first
(pdfplumber + pypdfium2), then local MinerU 4.x v1, local legacy
`/file_parse`, and official cloud v4. Setup and fallback details are in
`09-mineru-setup.md`; Route B (PMC) skips both. Run
`mineru_convert.py --probe` once at the start of Route A and record the
result in the manifest.

## Persistence discipline

- Write `input_manifest.md` entries immediately after each acquisition
  (what was got, what was blocked, sizes, hashes of key files).
- Every script's JSON output goes under `$RUN/workdir/`; never in the
  conversation scratchpad only.
- Findings are written as individual files the moment they survive the first
  benign check — do not hold five findings in your head until the report step.
- After each batch, one short line in the manifest: `## progress` section,
  e.g. `- 2026-11-14T10:00Z batch 8 done: 42 panels, 3 phash hits, 6 fingerprint pairs`.
  This line is the resume breadcrumb.

## Resume procedure (new context, same `$RUN`)

1. Read `$RUN/input_manifest.md` (especially `## progress`).
2. `ls $RUN/findings/*/` — see which tracks already have files.
3. Check the script JSONs exist and are non-empty (`workdir/*.json`).
4. Continue from the first batch whose output is missing or incomplete.
5. Do NOT re-run steps whose outputs exist, unless a later step proves the
   output is stale (e.g., a re-download of the article PDF changes the hash).

## Anti-patterns that lose runs

- Holding parsed numbers in context instead of files → lost on compaction.
- Running all image pairs in one giant shell loop with unlogged output →
  crash mid-loop, no way to know which pairs finished. Write each pair's JSON
  to `workdir/fp_<figA>_<figB>.json` as you go.
- Starting the logic track before the numeric findings exist → logic
  findings often cite numeric anomalies; write numbers first.
- Trusting `panel_split.py`'s count without opening `--debug`: a seamless
  montage returns one panel and the image track silently loses sub-panels.
  Log the count and the debug image in the manifest.
- Reporting a segment/patch score without the calibration note: a score is
  a lead, not a verdict; record the threshold and whether it was calibrated.
