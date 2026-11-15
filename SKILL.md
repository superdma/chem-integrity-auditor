---
name: chem-integrity-auditor
description: Use when auditing a CHEMISTRY / materials / electrochemistry / analytical chemistry paper for research-integrity issues — spectral or chromatogram reuse (NMR, XRD, HPLC/GC, UV-Vis, CV, EIS, Raman, IR, MS/HRMS), TEM/SEM image duplication, suspicious yields or mass balances, HRMS vs formula mismatches, CHN elemental analysis errors, compound identity/CAS/formula vs PubChem, spectra matching an SDBS/NMRShiftDB peak list, impossible units/ranges, identical replicates, or fabricated-looking kinetics — and producing a reviewable Chinese evidence report. Also use when the user asks 化学论文造假/诚信审计, 谱图重复, NMR/XRD/TEM 图片是否复用, 收率数据异常, or hands over a chemistry PDF (or DOI) asking whether the data/figures are trustworthy. Do NOT use for biology/Western-blot papers (use integrity-auditor) or generic non-chemistry PDF forensics (use paper-fraud-auditor).
---

# Chem Integrity Auditor

Chemistry-specific paper-integrity audit package. **Single stage, full quality
from the start.** The agent reads the relevant references, then carries out
three evidence tracks (numerical / image / logical) over the paper's data and
figures, adversarially tests every anomaly, and produces a structured Chinese
`audit_report.md` with Level 1–4 graded findings.

This skill ships no LLM SDK — it is the skill instructions, references,
templates, and single-purpose `scripts/` only.

## Non-negotiables

- **Findings are evidence, not verdicts.** Never write "造假" / "fraud" as a
  conclusion. Write "Level N 异常", "与撤稿通知指控 #k 一致", "需作者提供原始
  数据方可裁定". One signal never condemns a paper.
- **Every finding cites an evidence location**: markdown line or page, table
  id + row/column + original value, figure id + panel, image path, and the
  technique involved (NMR/XRD/HPLC/CV/…). A finding without a pointer is
  discarded at the quality gate.
- **Report language is Chinese** (technical terms and instrument names stay
  English: "NMR", "HRMS", "Level 2", "dHash"). Finding files and the report
  are 中文撰写.
- **Deterministic scripts first, judgment second.** All numeric and pixel
  checks run through `scripts/` before any agent interpretation. Agents add
  the *why* (benign explanation, pressure test), never re-derive the numbers.
- **Benford / digit checks are gated by applicability.** Small tables,
  bounded ranges, or derived quantities: say 不适用 and rely on the
  chemistry-specific checks instead.
- **Image thresholds are calibrated, not inherited.** dHash/ORB/curve
  cut-offs are defaults from a small case set; run
  `calibrate_image_thresholds.py` on a labelled manifest when available and
  record AUC/TPR/FPR. A threshold without a calibration note is a Level-1
  lead at best.
- **Tokens and API secrets are never written** into skill files, reports,
  manifests, or command examples. `MINERU_BASE_URL` / `MINERU_API_TOKEN` come
  from the environment.
- **Self-hosted MinerU returns md_content only** (no images). The image track
  ALWAYS depends on poppler (`pdftoppm` / `pdfimages`) — verify it works
  before starting; a run without panels cannot grade the image track.

## Required References

Read the relevant reference **before** executing its track, not after.

| Reference | Topic |
|---|---|
| `references/00-setup-incremental.md` | run persistence, batching, resume — **read first** |
| `references/01-acquisition.md` | input modes (PDF/DOI/URL), chemistry SI + hi-res figure routes, retraction/correction notices as audit checklists |
| `references/09-mineru-setup.md` | MinerU backends: local 4.x v1 task API, local 2.x/3.x legacy `/file_parse`, official cloud v4; CPU tiers, API keys, troubleshooting |
| `references/02-technique-catalog.md` | per-technique catalog (NMR/MS/IR/UV-Vis/XRD/TEM/HPLC/CV/EIS/TGA/XPS/BET…): expected format, value ranges, what should vary between replicates, characteristic fraud patterns, which checks apply |
| `references/03-numeric-track.md` | numeric playbook: `chem_numeric.py` + `numeric_forensics.py` interpretation, tolerances (CHN ±0.4%, HRMS 20 mDa, Scherrer 40%), benign explanations, escalation |
| `references/07-structure-identity.md` | structure/identity playbook: `structure_check.py` → PubChem; formula/MW/exact mass/CHN/CAS/novelty comparison; salt-hydrate and average-vs-monoisotopic traps |
| `references/04-image-track.md` | image playbook: panel split → phash → ORB → spectral noise fingerprint; thresholds; scale-bar & axis checks; vision usage; Western-blot-free (chemistry) reuse modes |
| `references/08-reference-spectrum.md` | copied-database-spectrum playbook: digitize peak positions → match SDBS/NMRShiftDB peak table; score bands; what turns a match into a finding; export (no scraping) rules |
| `references/05-logic-track.md` | logical playbook: chemistry claim chains (synthesis→purity→structure→performance), missing controls, characterization-vs-claim mismatches, domain plausibility |
| `references/06-grading-report.md` | Level 1–4 grading, finding file format, quality gate, Chinese report assembly |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/mineru_convert.py` | PDF → `full.md`; local MinerU 4.x v1 task API → local 2.x/3.x legacy `/file_parse` → official cloud v4 (`MINERU_API_TOKEN`); `--probe` checks availability. See `references/09-mineru-setup.md` |
| `scripts/pmc_fetch.py` | **PMC fallback route** (publisher blocked): NLM eutils fulltext XML → `full.md` (real HTML tables, `[[FIG:…]]` anchors) + original figure files from PMC's `instance/<id>/bin/` endpoint with pacing/retry. Use when the publisher site is Cloudflare-gated but the article is in PubMed Central. |
| `scripts/build_evidence_ledger.py` | MinerU workdir → `evidence_ledger.json` (text/table/figure/caption provenance index) |
| `scripts/numeric_forensics.py` | generic numeric leads: exact duplicates, repeated decimals, terminal digits, Benford (applicability-gated) |
| `scripts/chem_numeric.py` | chemistry-specific numeric leads: yield roundness, conversion×selectivity, area% sums, CHN vs formula, HRMS vs formula MW, Scherrer consistency, identical replicates, impossible unit ranges, neat decimals, fixed-offset rows — each with line-level provenance + candidate benign explanation |
| `scripts/nmr_hrms_numeric.py` | NMR/HRMS-specific leads: 1H integration non-integer/sum vs formula H, 13C signal count vs formula C, impossible/duplicate 13C shifts, RDBE, nitrogen rule, reported M+1/M+2 vs natural-abundance isotope pattern |
| `scripts/structure_check.py` | PubChem identity check: name/SMILES/CAS/InChIKey/formula → CID, then formula / MW / exact mass (HRMS adducts) / CHN Calcd+Found / CAS / novelty comparisons; cached, offline-capable, RDKit cross-check |
| `scripts/panel_split.py` | split multi-panel figure PNGs into individual panel PNGs |
| `scripts/stack_split.py` | split **stacked traces** (2–4 spectra separated by full-width black rules) into one image per trace, with optional colour isolation (red/blue/green) so ORB/fingerprint compare curves, not legends |
| `scripts/image_dup.py` | dHash/aHash perceptual duplicate detection (untransformed reuse) |
| `scripts/image_dup_orb.py` | ORB feature matching (transformed reuse: rotation/flip/crop/brightness) + RANSAC inliers, inlier ratio, target bbox, `--json` evidence |
| `scripts/spectral_noise_fingerprint.py` | curve-profile + background-noise correlation between two line-plot panels — catches re-plotted / re-labeled / white-point-shifted reuse that hashing misses |
| `scripts/spectral_segment_dup.py` | **within-trace / between-trace segment reuse**: sliding full-height patch NCC for the retraction charge "a segment of the curve is identical", plus a profile-Pearson fallback |
| `scripts/calibrate_image_thresholds.py` | labelled pair manifest → ROC/AUC/Youden threshold per metric (dHash, ORB, curve_r, noise); replaces inherited one-case thresholds with a measured calibration |
| `scripts/check_env.py` | pre-run environment check: Python, Pillow/numpy/cv2/scipy/RDKit, poppler, MinerU env vars (presence only) |
| `scripts/reference_spectrum_match.py` | digitize a spectrum panel (2-point axis calibration) or read a peak table, then match against SDBS/NMRShiftDB peak lists with tolerance + recall/precision scoring; semi-automatic copied-database-spectrum check |
| `scripts/render_evidence_tables.py` | deterministic annotated PNG evidence cards for high-risk table findings |

All scripts are stdlib, Pillow/NumPy/OpenCV, with SciPy optional. The only
network access is PubChem PUG REST in `structure_check.py` (cached,
`--offline` supported); there is no LLM SDK anywhere. Python 3.8+.

## Pipeline

### Step 1 — Identify input and set up the run

Detect input mode:

| Mode | Trigger | Acquisition |
|---|---|---|
| **PDF path** | local `*.pdf` argument | use directly |
| **DOI / URL** | `10.xxxx/...` or article URL | `references/01-acquisition.md` — landing HTML, SI/figure CDN routes, retraction/correction notices, then article PDF if open |
| **Batch** | several papers | one `$RUN` per paper, sequential |

Compute the run directory and persist everything there:

```bash
TITLE_OR_ID="<input identifier>"
SLUG=$(python3 -c "import re,hashlib,sys; t=sys.argv[1]; n=re.sub(r'[\\s_]+','-',re.sub(r'[^\\w\\s-]','',t.lower().strip())).strip('-')[:40].rstrip('-'); h=hashlib.sha1(t.encode()).hexdigest()[:8]; print(f'{n}-{h}')" "$TITLE_OR_ID")
TS=$(date +%Y-%m-%d_%H%M%S)
RUN=output/chem-integrity-auditor/$SLUG/$TS
mkdir -p "$RUN"/{findings/numerical,findings/image,findings/logical,panels,figures_hires,supplementary,workdir}
ln -sfn "$TS" "output/chem-integrity-auditor/$SLUG/latest"
```

Write `$RUN/input_manifest.md` as you go: every artifact acquired, every
attempt that was blocked (paywall, missing SI, dead endpoint), MinerU
version/source, panel counts. The manifest is the audit's own audit trail.

### Step 2 — Parse

**Route A (article PDF available)** — the documented pipeline:

```bash
# 1) Markdown (tables, captions, all numeric claims) — local MinerU first
# backend auto: local 4.x v1 → local 2.x/3.x legacy → cloud (if token set)
python3 <skill>/scripts/mineru_convert.py "$RUN/paper.pdf" --output "$RUN/workdir"
# CPU-only local server: add --tier flash (or basic); see 09-mineru-setup.md

# 2) Panels (image track ground truth) — poppler, NOT MinerU
pdftotext -layout "$RUN/paper.pdf" "$RUN/workdir/paper.txt"
mkdir -p "$RUN/panels"
pdfimages -all "$RUN/paper.pdf" "$RUN/panels/page"
N_RASTER=$(ls "$RUN/panels" 2>/dev/null | wc -l)
if [ "$N_RASTER" -eq 0 ]; then
  pdftoppm -r 150 "$RUN/paper.pdf" "$RUN/panels/page" -png
fi

# 3) Evidence ledger (provenance index over full.md)
python3 <skill>/scripts/build_evidence_ledger.py "$RUN/workdir" --output "$RUN/workdir/evidence_ledger.json"
```

**Route B (publisher blocked, article in PubMed Central)** — see
`references/01-acquisition.md` §PMC route. PMC's figure endpoint serves the
publisher's ORIGINAL figure files (often 600 DPI — higher fidelity than
PDF rasterization), so the image track is NOT degraded:

```bash
python3 <skill>/scripts/pmc_fetch.py --pmcid PMC<id> --output "$RUN/workdir"
# → $RUN/workdir/full.md (XML-derived, real <table> blocks, [[FIG:…]] anchors)
# → $RUN/workdir/figures_pmc/*.jpg (panels for the image track)
# → $RUN/workdir/pdf_candidate.txt (PDF name for a human/browser fetch)
```

Then skip steps 1–2 above; step 3 (ledger) still runs on `$RUN/workdir`.
The figure panels for Route B are `$RUN/workdir/figures_pmc/*` (use them
directly in place of `panels/page-*`).

Record route taken, `N_RASTER` (or figure count) and ledger stats in the
manifest. If `full.md` is missing or < 2 KB, stop and diagnose the converter
before anything else — the whole pipeline reads from it.

### Step 3 — Triage: subfield + technique inventory

Open `references/02-technique-catalog.md`. Two artifacts, both persisted:

1. **Subfield class** → `$RUN/paper_class.txt`:
   `organic-synthesis` / `electrochemistry` / `materials` / `analytical` /
   `catalysis` / `polymer` / `crystallography` / `other`. Picks which numeric
   checks and logic patterns get deep treatment.
2. **Technique inventory** → `$RUN/technique_inventory.md`: every figure,
   classified by technique (NMR-1H, XRD, HPLC, CV, TEM, …) using caption +
   axis labels + section context. One line per figure:
   `Fig 4b — CV — line plot — p.6 — panels/page-006-012.png`.
   Line plots (spectra/chromatograms/curves) are the pool for
   `spectral_noise_fingerprint.py`; photos/2D maps go to phash/ORB;
   schematics are excluded from pixel forensics (record the exclusion).

### Step 4 — Numeric track

Open `references/03-numeric-track.md`. Run both scripts:

```bash
python3 <skill>/scripts/chem_numeric.py "$RUN/workdir" --output "$RUN/workdir/chem_numeric.json"
python3 <skill>/scripts/nmr_hrms_numeric.py "$RUN/workdir" --output "$RUN/workdir/nmr_hrms.json"
python3 <skill>/scripts/numeric_forensics.py "$RUN/workdir" --output "$RUN/workdir/numeric_forensics.json"
```

**Structure/identity sub-track** (discrete compounds only): build a batch
JSON from the paper's compound table and run:

```bash
python3 <skill>/scripts/structure_check.py --batch "$RUN/workdir/compounds.json" \
    --output "$RUN/workdir/structure_check.json"
```

`compounds.json` keys: `label,name,smiles,cas,inchikey,formula,reported_formula,
reported_mw,reported_chn,reported_chn_calcd,reported_mz,adduct,reported_cas,
claim_novel`. Read `references/07-structure-identity.md` before grading —
salt/hydrate forms, average-vs-monoisotopic mass and wrong adducts are the
dominant false positives. No discrete compounds → record why this sub-track
is inapplicable.

Treat every output as **leads, not verdicts**. For each lead: open the cited
table/line in `full.md`, confirm the values, then write a finding file
`$RUN/findings/numerical/<short-id>.md` **only if the anomaly survives a
first benign check** (see the per-check benign explanations in the reference).
No anomaly in a track → `_clean.md`; the track does not apply to this paper
class → `_inapplicable.md` (never conflate the two).

### Step 5 — Image track

Open `references/04-image-track.md`. For the figure pool from Step 3.
Thresholds are defaults, not laws: when a labelled pair set exists, run
`calibrate_image_thresholds.py` and cite the ROC/Youden result in the
manifest; otherwise state that the thresholds are uncalibrated defaults.

1. `panel_split.py` on multi-panel figures (whole-figure hashing finds
   almost nothing — panels first). The splitter combines plot-frame rules
   with white/flat gutters and emits `--json` evidence + `--debug` overlay;
   inspect the count against the caption before trusting it.
1b. **Stacked traces in one panel** (Raman/XRD/XPS separated by full-width
   black rules): `panel_split.py` finds no white gutter. Run
   `stack_split.py fig.png bands/ --keep-color auto`; the colour isolation
   makes ORB compare the curve, not the legend text. Bands cut from ONE
   image share its JPEG texture — never cite `noise_corr` for them.
2. `image_dup.py` over all panel PNGs; dHash distance < 10 = strong candidate,
   10–60 = escalate to `image_dup_orb.py`. ORB ≥30 matches is only a
   candidate: control it against a different-material pair and, for spectra,
   against the shared-peak windows (see `references/04-image-track.md`).
3. **Line-plot pool**: run `spectral_noise_fingerprint.py` on all
   same-technique pairs (NMR vs NMR, XRD vs XRD, HPLC vs HPLC, CV vs CV…) —
   the technique inventory tells you which pairs to compare. Pairs with
   `curve_r ≥ 0.95` or `shared_noise_texture` become findings candidates.
   Noise correlation is meaningful only between panels from DIFFERENT
   source images.

3b. **Segment-level reuse** (the common notice charge "a stretch of the
   curve is identical"): run `spectral_segment_dup.py` on every line-plot
   panel. It slides a full-height patch and reports non-overlapping matches;
   `score ≥ 0.985` is a candidate, not a verdict. Run it both within one
   trace (`--image panel.png`) and between the two traces being compared
   (`--image a.png --image b.png`). Periodic fringes / calibration pulses
   are benign explanations to test.
4. **Reference-spectrum check** (when a reference peak table is available):
   `reference_spectrum_match.py` digitizes the paper's peak positions (two
   calibration points) and scores them against an SDBS / NMRShiftDB / SI
   peak list. Read `references/08-reference-spectrum.md` first. Export
   reference tables by hand — never scrape SDBS. A high score is only a lead;
   pair it with a novelty claim, a duplicated spectrum, or impossible noise.
5. **Vision pass** on every candidate: ask for concrete visual identity
   (peak positions, noise texture, scale bar, axis ticks, labels) — never
   "is this fraud". Also the standing scale-bar check for TEM/SEM: does the
   bar length match the stated magnification across figures of the same
   sample?
6. Each confirmed anomaly → `$RUN/findings/image/<short-id>.md`.

### Step 6 — Logical track

Open `references/05-logic-track.md`. Compress each headline claim into
"A through B gives C with performance D"; check the paper actually exercises
A, B, and the A→B link with the right controls (blank, positive control,
repeats, reference standard, leaching/stability where claimed). Check
characterization vs claim (does the XRD/TEM/NMR actually support "crystalline
nanoparticles"?). Each gap → `$RUN/findings/logical/<short-id>.md`.

### Step 7 — Adversarial defense (REQUIRED for every Level ≥ 2 candidate)

For each candidate finding, construct the **strongest plausible benign
explanation** (rounding convention, instrument precision, legitimate
re-characterization, shared reference sample, author typo) and TEST it:
recompute, re-extract at higher DPI, check the SI. An explanation that
survives → downgrade or drop; one that breaks → keep, and record the
pressure test in the finding file (the report's credibility comes from
having tried to kill the finding).

### Step 8 — Grade, report, quality gate

Open `references/06-grading-report.md`. Assign Level 1–4 to every surviving
finding, copy `templates/audit_report.md` to `$RUN/audit_report.md`, fill it
section by section (Chinese), and run the quality gate checklist before
delivering. Deliver the manifest, the findings tree, and the report.

## Grading

| Level | Meaning (evidence stance) |
|---|---|
| **1** | 可疑 — anomaly observed, benign explanation plausible |
| **2** | 明显异常 — anomaly confirmed, benign explanation weak |
| **3** | 需原始数据裁定 — cannot resolve from the published material (name exactly what the author must supply) |
| **4** | 高度疑似失实 — multiple independent evidence lines agree, or a retraction notice's specific charge is reproduced pixel-for-pixel / value-for-value |

Final risk in the report header: Low / Medium / High / Critical mapped from
the Level mix (≥1 Level 4 with a surviving independent line → High or
Critical; see `references/06-grading-report.md`).

## Important rules

- **No LLM SDK in this skill.** No `import anthropic` / `import openai`.
  The skill is instructions + references + template + deterministic scripts.
- **`_clean.md` vs `_inapplicable.md` are not interchangeable.** Clean = the
  checks were applicable and were run. Inapplicable = the tool does not fit
  this paper class; record what was checked instead.
- **A neat number is not proof; a Benford failure is not proof.** The
  strongest evidence is a *network*: reused spectrum + impossible yield +
  failed benign explanation, each independently located.
- **A database match is not fraud.** A spectrum that matches an SDBS /
  NMRShiftDB peak list is expected for any real compound. Grade it only
  when the paper's own claim (novel compound, original measurement) plus a
  second independent line make the match incriminating. Same for a PubChem
  hit: registry presence is not evidence of misconduct.
- **Never modify the audited paper or another skill's outputs.** The run
  directory is the only writable place.
- **Paywall honesty**: if the SI is blocked and the article body is thin,
  the report says so explicitly — "无法审计" is a finding about the audit,
  not about the paper.

## Self-test

Run before changing a script or a threshold:

```bash
bash tests/smoketest.sh    # compile + --help + positive/negative fixtures
```

The suite covers `chem_numeric`, `structure_check` (offline PubChem cache),
`reference_spectrum_match` (image + SDBS-style peak table), `image_dup`,
`spectral_noise_fingerprint`, `spectral_segment_dup`, `panel_split`,
`stack_split`, `calibrate_image_thresholds`, the evidence ledger (including
HTML tables), and all three MinerU backends. It must stay at 0 failures.
