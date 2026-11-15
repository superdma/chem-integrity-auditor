# 07 — Structure / identity track (PubChem)

The chemistry-specific answer to "is the compound the paper says it made
actually the compound it describes?" It is deterministic arithmetic plus a
registry lookup — no judgement until the auditor reads the paper's own
formula/adduct context.

## When this track applies

Run it for every paper that names discrete compounds and reports at least
one of: molecular formula, molecular weight, exact mass / HRMS, elemental
analysis (CHN), CAS number, or a claim of novelty. It does **not** apply to
materials papers that only report a nominal composition (e.g.
`LiNi0.8Co0.1Mn0.1O2`) — record `_inapplicable.md` with the reason and use
the numeric track's stoichiometry checks instead.

## Run

```bash
# one compound
python3 <skill>/scripts/structure_check.py \
    --name "compound 5a" --reported-formula C22H25NO3 \
    --reported-mw 351.44 \
    --reported-chn "C=75.19,H=7.17,N=3.99" \
    --reported-chn-calcd "C=75.21,H=7.19,N=3.98" \
    --reported-mz "352.1907 [M+H]+" \
    --reported-cas 123456-78-9 \
    --output "$RUN/workdir/structure_check.json"

# batch: one JSON object per compound (keys below)
python3 <skill>/scripts/structure_check.py --batch compounds.json \
    --output "$RUN/workdir/structure_check.json"
```

Batch keys: `label`, `name`, `smiles`, `cas`, `inchikey`, `formula`,
`reported_formula`, `reported_mw`, `reported_chn`, `reported_chn_calcd`,
`reported_mz`, `adduct`, `reported_cas`, `claim_novel`.

Useful flags: `--offline` (cache only), `--refresh`, `--mw-tol` (default
0.5 Da), `--hrms-tol-mda` (default 20 mDa), `--cache DIR`.

## Output

`queries[].comparisons[]` each have `check`, `severity`
(`pass|info|soft|hard`), `reported`, `expected`, `delta`, `detail`, and a
mandatory `benign_explanation`. `severity` is a **lead strength**, not a
Level. Nothing here is gradeable without opening the paper.

## Per-check interpretation

### pubchem_lookup
- `pass` + one CID: identity resolved. `ambiguous_cids` > 1 means the
  identifier matched several records (common for names and formulas) — pick
  the CID whose InChIKey matches the paper's structure before trusting any
  downstream comparison.
- `soft` + not-found: a genuine identity lead **only if** the paper claims a
  known compound. New compounds legitimately return nothing.

### formula
- `hard` mismatch: recompute by hand from the paper's structure drawing or
  SMILES before grading. The most common false positive is a salt/hydrate
  written differently in the table vs the PubChem record.
- Main formula equal but hydrate/salt differs → `info`; check whether the
  paper reports the free base and the SI the salt.

### mw
- PubChem `MolecularWeight` is the **average** mass. Papers sometimes report
  exact/monoisotopic mass in a column labelled "MW" — that is a labelling
  issue, not fabrication. Compare against `ExactMass` before grading.
- A difference that equals a small integer number of water molecules
  (18.015) or HCl (36.461) is a salt/hydrate form, not an error.

### chn_calcd / chn_found
- `chn_calcd` (paper's own Calcd vs theory from the formula) is the stronger
  check: if the authors' arithmetic is wrong by >0.15 pp, the formula or the
  calculation is wrong. Level 2 candidate when the formula is unambiguous.
- `chn_found` (Found vs theory): the analyzer's practical window is
  ±0.4 pp. 0.4–0.8 pp is `info`; >0.8 pp or several elements deviating in
  the same direction is `soft`. Hygroscopic/solvated samples routinely read
  low — always state that benign explanation first.
- **Fabrication fingerprint**: Found values identical to Calcd to 0.01 pp
  across several elements. The script does not flag this directly; when you
  see it, add a numeric-track `identical` finding and cross-reference. Real
  combustion analysis always has scatter.
- Formula with F, P, B, metals: the script computes from standard atomic
  weights; if an element is missing it says so rather than guessing.

### hrms
- Uses `MonoisotopicMass` + the parsed adduct. `[M+H]+`, `[M-H]-`,
  `[M+Na]+`, `[M+K]+`, `[M+NH4]+`, `[M+Cl]-`, `[M+HCOO]-`, `[M+CH3COO]-`,
  `[M+2H]2+`, `[M+3H]3+` are recognized. Unknown adduct → `info`, no
  comparison (fix the `--adduct` and rerun).
- ≤20 mDa: `pass`. 20–50 mDa: `info`. >50 mDa: `soft`.
- Common benign causes, in order: wrong adduct assignment; the reported
  number is a nominal mass; the formula in the table belongs to a different
  compound in a multi-compound SI. Check the line and the SI header first.
- **Fabrication fingerprint**: found value reproduces calcd to the last
  reported digit (e.g. calcd 513.2411, found 513.2411). Real HRMS always
  differs in the last digits. This is a Level 1 lead; pair it with the
  duplicate-value check in `numeric_forensics.py`.

### cas
- `info` when the reported CAS is absent from PubChem synonyms. New
  compounds have no CAS; old compounds can have several. Only escalate when
  the paper cites a CAS that belongs to a *different* compound (search the
  CAS itself and compare InChIKey).

### novelty
- `--claim-novel` + a PubChem hit is a **soft** lead, not proof: the hit may
  be a close analogue, and PubChem contains many automatically registered
  structures. Compare InChIKey first block (skeleton) and the paper's
  structure drawing before grading. A full InChIKey match plus an explicit
  "new compound" claim is a Level 2 candidate.

### rdkit
- Cross-check only. When a SMILES is supplied it recomputes formula, MW and
  exact mass locally. If RDKit's InChIKey and PubChem's disagree, the SMILES
  and the registry record are different structures — fix the query before
  using any comparison.

## Track output

- Surviving anomaly → `findings/numerical/<short-id>.md`, e.g.
  `chn-calcd-c22h25no3`, `hrms-352-found-calcd`, `novelty-5a-pubchem`.
  Quote the check, both values, the PubChem CID/InChIKey and the retrieval
  date (cache file timestamp).
- All compounds resolve and agree → `findings/numerical/_clean.md` with the
  query count, CIDs, and the tolerances used.
- No discrete compounds → `findings/numerical/_inapplicable.md` naming what
  was checked instead.

## Limits (state these in the finding)

- PubChem is a registry, not an authority: absence of a record is not proof
  of novelty, and presence is not proof of identity.
- Average vs monoisotopic mass, salt/hydrate forms, and tautomers are the
  three dominant false-positive sources.
- The lookup is only as good as the identifier supplied. A wrong name in the
  paper yields a wrong CID; confirm the InChIKey against the drawn structure.
- Cache files record `_fetched_at`; cite that timestamp, not the audit date.
