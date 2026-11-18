# 03 — Numeric track playbook

Two scripts produce the leads; the agent verifies and grades them.
**The scripts never condemn** — a lead becomes a finding only after you open
the cited line/table in `full.md`, confirm the values with your own eyes,
and record the first benign check.

```bash
python3 <skill>/scripts/chem_numeric.py "$RUN/workdir" --output "$RUN/workdir/chem_numeric.json"
python3 <skill>/scripts/numeric_forensics.py "$RUN/workdir" --output "$RUN/workdir/numeric_forensics.json"
# SI workdir gets the same two runs (SI is where CHN/HRMS tables usually live)
python3 <skill>/scripts/chem_numeric.py "$RUN/workdir_si" --output "$RUN/workdir_si/chem_numeric.json" 2>/dev/null || true
```

Read `chem_numeric.json`: `findings[]` each carry `check`, `severity`
(hard/soft/info), `table`, `location` (row/column or md_line), `values`,
`detail`, `benign_explanation`. `info`-severity leads are recorded, not
graded, unless they corroborate another line.

## Per-check interpretation

### 1. yield_roundness
- **hard** (>100%, exactly 100%): >100% is impossible for an isolated yield
  — but first confirm the column really is an isolated yield (a "% yield vs
  theoretical" ratio can exceed 100 legitimately when the product was
  isolated with inclusions — verify from the header wording). Exactly 100.0%
  as a *measured* isolated yield: Level 1; if the table has several exact
  100s: Level 2 candidate (defense: rounding from 99.6–100.4 is real but
  repeated exact 100.0 across rows is not how rounding behaves — different
  starting masses round differently).
- **soft** (≥50% multiples of 5): one or two neat values are author
  rounding; a whole column at 5-step precision with no decimals is a
  Level 1 lead, Level 2 candidate when combined with identical replicates
  or a perfect mass balance. Always check the SI for unrounded values — if
  the SI shows 94.7/91.3 and the main table shows 95/90, that is legitimate
  rounding and the lead dies.

### 2. conversion_selectivity
- Definitions differ across subfields (selectivity = product/conversion is
  standard; some papers use product/feed). The script flags when yield ≠
  conv×sel/100 by >3pp — before grading, test BOTH definitions plus
  yield=sel (when conversion is 100% by design). If neither reproduces the
  reported yield, the row is internally inconsistent: Level 1–2 depending
  on magnitude (Δ<10pp → 1, Δ≥10pp → 2 candidate).
- conv or sel >100% (hard): verify the column is not a *ratio* or *relative*
  value mislabeled. Genuine >100% conversion is impossible → Level 2
  candidate if it survives the header check.

### 3. area_percent_sum
- Row sums outside 90–105: the usual benign cause is "minor peaks not
  integrated" — check the caption ("major components" wording). A table
  labeled as a full composition that sums to 75 or 130: Level 2 candidate.
  Sums drifting consistently in one direction (all rows 88–92) can be a
  detection limit — record, don't grade up.
- Remember the script excludes metric-% columns (yield/conversion/…); if you
  see a partition you want summed that the script skipped, note it and do
  the arithmetic manually in the finding (cite the row).

### 4. chn_elemental
- **Calcd vs theoretical >0.15pp** (hard): the authors' own Calcd line is
  wrong for the stated formula. Level 2 candidate if the formula is
  unambiguous (compound named in caption); Level 1 if the table serves
  several compounds and the formula was taken from context (re-run with the
  right formula before grading — this is the main false-positive source).
- **|Found − Calcd| >0.4pp** (soft): 0.4% is standard CHN analyzer
  precision — a deviation of 0.5pp on one element is within lab reality;
  ≥0.8pp or multiple elements deviating: Level 1–2. Note that a *wrong
  Calcd* (above) makes the Found comparison meaningless — grade the Calcd
  error, not the Found error, and say so.

### 5. hrms_mw
- **calcd-vs-found >20 mDa** (soft): modern ESI-TOF/Q-TOF resolves single
  mDa; >20 mDa gap means either a low-resolution instrument mislabeled, a
  transcription error, or tampering. Level 1 if it's a single occurrence in
  an otherwise clean SI; Level 2 candidate if the same ion's found value
  appears in the main text with a *different* number than the SI (cross-line
  inconsistency — grep both workdirs for the m/z).
- **m/z vs formula >20 mDa** (soft): usually adduct misidentification or
  wrong formula in context — the script says so in `benign_explanation`.
  Verify the adduct notation on the line yourself before grading.
- A found value that is *impossibly close* to calcd (same digits, e.g.,
  calcd 513.2411 found 513.2411 — zero measurement error): Level 1 lead;
  real HRMS measurements always differ in the last digits. (`identical`
  values also trip `numeric_forensics` duplicates — cross-reference.)

### 6. scherrer
- >40% deviation (soft): K constants 0.6–1.0 vary by convention, β may be
  instrument-corrected, or a different peak was used. All legitimate — but
  a *consistent* >40% deviation across every row of the table is not
  convention, it's arithmetic fabrication: single row → Level 1, whole
  table → Level 2 candidate.

### 7. identical_replicates
- Same value across repeated runs: precision decides. Integer % identical
  across 3 runs: benign (coarse measurement). 2+ decimals identical across
  "independent" runs: Level 2 candidate — independent measurements share
  systematic error, not all digits. Cycling data with zero jitter over
  hundreds of cycles: Level 2 candidate (real cells fluctuate).
- Identical *rows* across all numeric columns: check whether the rows are
  the same experimental condition shown twice (legitimate, caption will say
  "representative") or different runs (not legitimate).

### 8. impossible_unit_ranges
- **hard** violations: verify the unit was parsed correctly (a "°C" that is
  really a figure label number; a ppm that is an MS tolerance). After
  verification, a hard range violation is a Level 2 candidate by itself.
- **soft** violations: context-dependent (a "250 eV" might be an X-ray
  source energy, perfectly real). Grade only if the context confirms the
  quantity the range assumes.

### 9. neat_decimals (info)
- Corroboration only: a whole table at uniform 1-decimal precision with
  values clustering at .0/.5 strengthens other leads; alone it is author
  style.

### 10. fixed_offset_rows
- Constant shift across all numeric columns of two rows: often a designed
  comparison (with/without additive, same feedstock) — the caption usually
  explains it. Unexplained + the offset looks "convenient" (rounds to a
  clean per-column delta): Level 1 lead.

## Generic leads (numeric_forensics.py)

- `duplicates.repeated_values`: exact-equal numbers in different table
  contexts. Chemistry-specific reading: two *different samples'* yields
  identical to 2 decimals = Level 1; two different *technique measurements*
  sharing a value = Level 2 candidate. Ignore duplicates within the same
  legitimate row/column family (e.g., repeated standards).
- `duplicates.repeated_fractional_parts`: shared decimal tails across
  values — fabrication signature; Level 1–2 candidate after checking the
  values aren't from one arithmetic family (e.g., all = 100/x).
- `digits.terminal_0_or_5_rate`: >0.5 sustained = Level 1 lead (measured
  chemical quantities rarely terminate in 0/5 more than ~1/3 of the time).
- `benford.*`: **gated**. Apply only to large heterogeneous value pools
  (n ≥ 80, ≥3 orders of magnitude, not bounded by definition). Yields
  (bounded 0–100), retention times (narrow range), and small tables:
  mark 不适用 and say so in the track summary — a failed Benford on a
  yield table is noise, not evidence.



## Source-data workbook sub-track (`source_data_audit.py`)

The Markdown path sees the rendered table; the workbook path sees the cell
matrix. When the SI ships `.xlsx/.csv/.tsv`, run both:

```bash
python3 <skill>/scripts/source_data_audit.py "$RUN/supplementary" \
    --out "$RUN/workdir/source_data_audit.json" --text
```

| Check | Pattern | First benign test |
|---|---|---|
| `duplicate_numeric_row` | two rows share ≥4 numeric cells | same condition shown twice? technical-replicate average? |
| `duplicate_numeric_column` | two columns hold the same values | one is a derived/copy column, or a unit conversion |
| `constant_difference` | `A − B` is constant across ≥8 rows | designed additive series, baseline subtraction, shared calibrator |
| `constant_ratio` | `A / B` is constant | normalization, unit conversion, same quantity in two units |
| `near_perfect_correlation` | Pearson `|r| ≥ 0.99999` | affine-derived column; a real linear calibration can do this |
| `arithmetic_progression` | ≥4 consecutive values with a fixed step | designed concentration series, time ramp, a generated index |
| `mixed_precision` | two displayed precisions each ≥10% | instrument exports with mixed formats; otherwise a re-typed column |
| `last_digit_mode_a` | one non-zero trailing digit ≥20%, χ²≥26.1, n≥50 | bounded-range artefact, rounding to a preferred digit |
| `last_digit_mode_b` | at max displayed dp: 0-share ≥50%, top digit ≥35%, or ≥50% coarser values, n≥30 | uniformly 1-dp column (then Mode B is inapplicable) |
| `decimal_tail_2dp/3dp` | ≥8 values spanning ≥6 distinct numbers share a tail | values generated from one formula (e.g. all `100/x`) |

Every output is a **lead**. Open the cited sheet and rows, confirm the header
and sub-table layout, and write down which benign explanation survived or
failed. A fixed difference in two *independent measurement* columns with no
documented derivation is a Level 2 candidate; a single duplicate row can be a
technical replicate. Do not apply Mode B to a column that is uniformly 1 dp.

## Track output

- Every surviving anomaly → `findings/numerical/<short-id>.md` (format in
  06), short-id like `table1-yield-102`, `hrms-found-calcd-513`,
  `scherrer-xrd-tab3`.
- No survivors after benign checks → `findings/numerical/_clean.md` listing
  both scripts' run stats (n tables, n leads, how many died and why).
- Paper class with no quantitative tables (e.g., pure theory/crystal
  structure paper) → `findings/numerical/_inapplicable.md` listing what was
  checked instead (e.g., lattice parameters vs bond lengths consistency).
- Cross-track notes: numeric findings that reference a figure (e.g., "text
  Rct ≠ figure arc") belong here with the figure pointer, not in the image
  track — the image track is for *pixel-level* evidence only.


## NMR / HRMS isotope sub-track (`nmr_hrms_numeric.py`)

Run alongside `chem_numeric.py`:

```bash
python3 <skill>/scripts/nmr_hrms_numeric.py "$RUN/workdir" \
    --output "$RUN/workdir/nmr_hrms.json"
```

Checks:

| Check | Severity | Benign explanation to test |
|---|---|---|
| 1H integration not near integer/0.5 H | soft | exchangeable proton, overlap, integration normalized to a subset |
| sum of 1H integrals ≠ formula H | soft | partial/subset normalization, omitted exchangeable H, solvent/impurity |
| 13C signals > formula C (solvent peaks removed) | hard | unlisted impurity/solvent, formula typo |
| 13C shift > 250 or < -10 ppm | hard | paramagnetic complex, wrong nucleus label, typo |
| duplicate 13C shift | soft | genuine overlap or copy/typo |
| RDBE < 0 | hard | formula typo, ion/radical, salt component |
| nitrogen-rule parity mismatch | soft | salt/ion, isotope label, formula typo |
| reported M+1/M+2 vs natural abundance | soft | isotope label, different adduct/charge, peak-picking artifact |

The parser is line-based and tolerant; it is not a structure elucidation
engine. Always open the cited line and check whether the formula belongs to
the same compound before grading.
