# 05 — Logical track playbook

The logic track checks whether the paper's *claims* are exercised by its
*experiments* — the line the other two tracks cannot see. It uses no pixel
or arithmetic forensics beyond what the numeric track already produced; it
uses the claim structure, the control set, and domain plausibility.

## Claim-chain compression

Write each headline claim as:

```
Route/synthesis A gives species B (purity P, structure S)
that performs D in application E, attributed to mechanism M.
```

Then ask, per link:

1. **Is A actually done?** (procedure present, conditions stated, repro
   count given?)
2. **Is B actually characterized?** (structure assignment supported by
   which data — NMR? HRMS? XRD? crystal structure? Each claim type needs
   its characteristic evidence; "we confirmed the structure" with only a
   melting point is a gap.)
3. **Does P follow from the data?** (purity claim vs chromatogram/NMR —
   the visible impurity problem)
4. **Does D follow from the measured data?** (performance claim vs the
   table/figure that should show it — numbers that appear only in the
   text with no underlying data are Level 1–2 leads)
5. **Is M tested, or only asserted?** (mechanism claims need the
   mechanistic experiment: isotope labeling, intermediate trapping,
   control reactions — "presumably/likely" language without data)

Each unmet link → one `findings/logical/<short-id>.md`.

## Control checklist by subfield

Read the paper's subfield class (`paper_class.txt`) and apply the relevant
rows. A missing control is a Level 1 lead *only if the paper makes the
claim the control would support*; absent claim, absent control is a
weakness, not an anomaly.

| Subfield | Required controls for the typical claims |
|---|---|
| **catalysis** | blank (no catalyst, same conditions); catalyst loading comparison (if "turnover" is claimed, the loading must be stated and low); leaching / hot-filtration (if "homogeneous/true catalytic" claimed); TON = converted mol / catalyst mol must be recomputable from stated values; recyclability claims need the activity-loss data |
| **electrochemistry** | reference electrode stated + calibration; control electrode (no catalyst) in the same figure or table; iR correction stated; sweep-rate dependence for CV claims; electroactive species identified (CV of the pure compound) |
| **materials / nano** | amorphous vs crystalline claim ↔ XRD (a "crystalline" claim with a broad-hump XRD is Level 2); size claim ↔ TEM (distribution, not just one micrograph); "monodisperse" ↔ the visible polydispersity; surface area claim ↔ BET isotherm present |
| **analytical** | calibration curve with R² and range; standard-addition or matrix-match if samples are complex; LOD/LOQ derivation (3σ/S, 10σ/S) recomputable; spiked recovery |
| **synthesis (organic)** | reproducibility (n, or "three batches"); crude vs purified characterization; starting-material recovery or absence check; reference comparison (literature data for the same compound) |
| **energy storage** | initial capacity consistency across figures/tables (GCD fig vs summary table); rate-recovery test; control cell without active material for electrolyte-only baseline if capacity is high |
| **crystallography** | CIF deposited (a crystal-structure claim without deposited data = Level 2 candidate in the integrity world); R-factors / refinement stats present and plausible |

## Cross-figure / cross-table consistency (manual arithmetic)

These are the checks `chem_numeric.py` cannot reach (they need two distant
places in the paper). Grep both, recompute, cite both locations:

- Text vs table: "crystallite size ~20 nm" in the results paragraph vs the
  XRD table row (the `scherrer` check covers table-internal; this covers
  text-vs-table).
- Figure vs figure: initial capacity in the GCD figure vs the summary table
  vs the rate-capability table (three places, one number).
- Figure vs SI: the main-text HRMS found value vs the SI spectrum's stated
  value.
- Reaction stoichiometry: stated equivalents vs the procedure masses
  (mmol from mass + MW must match the claimed equiv; recompute — this is
  the single most common *honest* inconsistency, so grade it Level 1
  unless it recurs).
- Yield chain: "95% yield" → mass isolated vs theoretical from stated
  limiting reagent (recompute the theoretical; if the paper's own yield %
  and its masses disagree by >10%, one of them is wrong).

## Data availability

Chemistry papers must supply raw spectra (NMR, MS, XRD) — at minimum in the
SI. Absence patterns:

- SI exists but has NO spectra for characterized compounds → Level 2
  candidate (characterization is unverifiable; the journal's own policy is
  the benchmark).
- "Spectra available from authors on request" without SI deposition →
  Level 1 (policy violation at most, but recorded).
- CIF / raw EIS / raw cycling data promised but absent → Level 1.

## Domain plausibility (last resort, weakest line)

Things that are *chemically weird* but not locally inconsistent: a
"highly selective" reaction at harsh conditions; a photocatalyst with no
light-dependence control; a battery that cycles 5000 times at 10 C with no
decay. These are Level 1 leads at best and MUST be paired with something
concrete (the missing control) — pure plausibility is not a finding.

## Track output

- `findings/logical/<short-id>.md`, short-id like `crystalline-claim-vs-xrd`,
  `ton-arithmetic`, `no-leaching-control`, `si-no-nmr`.
- `_clean.md` = all claim links exercised, all required controls present for
  the claims made, cross-figure arithmetic consistent (list what was
  checked).
- `_inapplicable.md` = no experimental claims to check (pure review/theory)
  — list what that means for coverage.
