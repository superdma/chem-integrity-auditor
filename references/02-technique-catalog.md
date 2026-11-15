# 02 — Technique catalog

The triage step (SKILL.md Step 3) classifies every figure by technique; this
catalog is the reference table. For each technique it says: what a genuine
signal looks like, which value ranges are hard limits, **what should vary
between independent measurements** (the key to interpreting
`spectral_noise_fingerprint.py`), the characteristic fraud patterns, and
which checks apply.

Use it twice: (1) to build `technique_inventory.md`, (2) to decide which
same-technique panel pairs go through the fingerprint sweep — pairs of
different techniques are compared only when a figure reuses a panel across
techniques (itself a red flag).

---

## 1. 1H / 13C NMR

- **Format**: line plot, δ (ppm) on x (1H: ~0–15, 13C: ~0–250), intensity y.
  Peaks are multiplets (doublets, triplets…) with integrals; solvent
  residuals (CDCl3 7.26 ppm, DMSO-d6 2.50 ppm) are a fixed fingerprint.
- **Hard ranges**: 1H outside −5…30 ppm is impossible for a normal molecule;
  13C outside −10…260.
- **What should vary between repeats**: digital baseline noise, line width,
  multiplet fine structure. **Should not vary**: peak positions (δ),
  integral ratios, splitting patterns.
- **Fraud patterns**:
  1. *Re-labeled spectrum* — same peaks, different assignment table (classic;
     solvent residual peaks betray it: CDCl3 residual on a "DMSO-d6" label).
  2. *Peak deletion / smoothing* — impurity peaks removed by erasing or
     over-smoothing (baseline shows a flat dead zone unlike the surrounding
     noise).
  3. *Integral inconsistency* — integral values in the table don't match the
     H-count ratio of the claimed structure (logic track: manual check).
  4. *Copied spectrum across compounds* — Fig of "compound 3" is actually
     "compound 2" (fingerprint pair across figures).
- **Checks**: `spectral_noise_fingerprint` (same-technique pairs),
  `image_dup`/ORB (reproduced panels), `impossible_unit_ranges` (ppm),
  manual: integral ratio vs structure, solvent peak vs deuterated-solvent
  label, assignment table vs peak positions (logic track).

## 2. MS / HRMS (ESI, MALDI, GC-MS)

- **Format**: m/z vs relative intensity; HRMS reported as text
  ("calcd for CxHy… [M+H]+ XXX.XXXX, found XXX.XXXX") + stick spectra.
- **Hard ranges**: m/z > 3000 rare in organic papers; relative intensity 0–100.
- **What should vary**: relative intensities of isotope peaks are
  *deterministic* from composition (C13 pattern) — two HRMS sticks of the
  same compound must have the same isotope envelope; independent ionizations
  vary in absolute counts.
- **Fraud patterns**:
  1. *m/z typo* — found value inconsistent with formula MW (caught by
     `hrms_mw`; tolerance 20 mDa).
  2. *Adduct confusion* — [M+Na]+ reported as [M+H]+ (same check; the benign
     explanation list covers it).
  3. *Isotope envelope mismatch* — a "C18" compound whose stick spectrum
     shows a C12 isotope pattern (vision + agent knowledge; Level 2–3).
  4. *Copied MS spectrum* with different compound label (fingerprint pair).
- **Checks**: `hrms_mw` (document-level, article + SI), `area_percent_sum`
  (quantitative MS), fingerprint pairs, isotope-envelope vision check.

## 3. IR / Raman

- **Format**: transmittance % (y) vs wavenumber cm⁻¹ (x, 4000→400, axis
  decreasing left-to-right); Raman: intensity vs shift cm⁻¹.
- **Hard ranges**: cm⁻¹ outside 300–5000.
- **What should vary**: baseline offset, noise; **should not**: band
  positions for the same compound.
- **Fraud patterns**:
  1. *Generic spectrum reuse* — the most-copied figure in chemistry: an IR
     of a "different compound" that is actually a stock spectrum of the
     starting material (fingerprint pair across compounds; also: a band
     pattern inconsistent with the claimed functional groups — e.g., no
     C=O band at ~1700 for a claimed ketone, logic track).
  2. *Axis range clipping* — diagnostic bands deleted by rescaling the x
     window (vision: compare axis windows of reused-looking pairs).
- **Checks**: fingerprint pairs (IR vs IR), `impossible_unit_ranges` (cm⁻¹),
  manual band-assignment vs claimed structure (logic track).

## 4. UV-Vis / fluorescence

- **Format**: absorbance (AU) or intensity vs λ (nm); UV-Vis 190–800 nm
  typical; fluorescence has Ex/Em pairs (two related curves per sample).
- **Hard ranges**: λ 190–2500 nm; AU usually 0–2.
- **What should vary**: noise, baseline, exact peak intensity; **should
  not**: λmax for the same species.
- **Fraud patterns**:
  1. *λmax reuse* across supposedly different dyes/complexes.
  2. *Band gap inconsistency* — claimed Eg (Tauc plot) doesn't match the
     absorption edge in the UV-Vis figure (logic track, manual Tauc check if
     the plot is present).
  3. *Fluorescence Ex/Em pairs that are the same curve shifted* — an EEm
     spectrum should differ in shape from EEx; identical shapes = copy.
- **Checks**: fingerprint pairs (UV vs UV, Em vs Em), manual Eg vs edge
  (logic), `impossible_unit_ranges` (nm, AU).

## 5. XRD (powder)

- **Format**: intensity (a.u.) vs 2θ (°), typically 5–90° (Cu Kα); sharp
  peaks for crystalline, broad hump for amorphous.
- **Hard ranges**: 2θ 0–180; peaks at positions determined by lattice
  parameters (d-spacing via Bragg's law).
- **What should vary**: peak intensities shift with preferred orientation /
  instrument; **should not**: 2θ positions for the same phase.
- **Fraud patterns**:
  1. *Phase swap* — "crystalline product X" whose pattern matches reference
     data of starting material / a different polymorph (agent knowledge:
     compare quoted 2θ values against known phase patterns; SI patterns are
     pixel-checkable against the main text).
  2. *Scherrer inconsistency* — reported crystallite size contradicts the
     FWHM of the quoted peak (`scherrer`, 40% tolerance).
  3. *Pattern reuse* — "before/after" or "sample A/B" patterns that are the
     same data (fingerprint pair).
  4. *Impossibly sharp / noiseless data* — real powder patterns have
     background rise at low angle and counting noise (vision: noise texture
     compared with other panels).
- **Checks**: `scherrer`, fingerprint pairs (XRD vs XRD),
  `impossible_unit_ranges` (2θ), manual 2θ-vs-phase (logic track).

## 6. HPLC / GC / LC-MS chromatograms

- **Format**: UV/area response vs retention time (min) or volume (mL);
  chromatograms for purity often show one dominant peak.
- **Hard ranges**: tR 0–~1000 min; area% per component 0–100, row sums ≈100.
- **What should vary**: noise, small shifts in tR (column aging, temperature
  drift — a few % is normal), impurity peak heights; **should not**: the
  tR pattern of a well-defined separation under identical method.
- **Fraud patterns**:
  1. *Reused chromatogram* for different compounds/batches — identical tR
     pattern AND identical noise = copy (`area_percent_sum` + fingerprint).
  2. *Area sum ≠ 100* — component table rows summing far from 100%
     (`area_percent_sum`; tolerance 90–105, outside = finding).
  3. *Purity claim vs chromatogram* — "99.5% pure" text but a visible 3%
     impurity peak in the figure (logic track, vision).
  4. *Too-clean chromatograms* — flat digital white baseline with zero noise
     (vision; real detectors always show baseline noise).
- **Checks**: `area_percent_sum`, fingerprint pairs (HPLC vs HPLC),
  `identical_replicates` (repeated injections with tR to the 0.01 min),
  manual purity-vs-peak (logic).

## 7. Cyclic voltammetry (CV) / LSV / i-t

- **Format**: current (mA or mA/cm²) vs potential (V); CV = closed-loop
  curve, anodic/cathodic branches.
- **Hard ranges**: potentials within the electrolyte stability window (agent
  knowledge: water ~−1.2…+1.2 V vs RHE; acetonitrile ~−2.5…+1.5 V vs
  Ag/AgCl); scan rates 1–1000 mV/s.
- **What should vary**: noise, exact loop area (faradaic charge varies with
  surface coverage); **should not**: peak potentials (Ep) for the same redox
  couple, or the shape family.
- **Fraud patterns**:
  1. *CV reuse across electrodes* — different catalysts with identical Ep and
     loop shape (fingerprint pair).
  2. *Peak shift inconsistency* — text claims Ep shifted by X mV, figure
     shows no shift (logic track, manual).
  3. *Scan-rate study that is the same curve scaled* — in a legitimate
     log(i) vs log(v) study the curves at different rates share shape but
     their peak separation changes predictably (ΔEp ≈ 59/n mV reversible);
     identical shapes at all rates with unchanged ΔEp can indicate scaling
     (vision + agent knowledge).
  4. *iR-corrected / non-corrected mix* — tables and figures mixing corrected
     and raw currents (logic track).
- **Checks**: fingerprint pairs (CV vs CV), `impossible_unit_ranges`
  (V, mV/s, mA/cm²), manual Ep/ΔEp consistency (logic).

## 8. EIS (Nyquist / Bode)

- **Format**: −Z″ vs Z′ (Nyquist); arcs + inductive/RC elements.
- **What should vary**: noise at high frequency, absolute impedance (series
  resistance varies with cell assembly); **should not**: the arc structure
  family for the same interface — and Rct values quoted in the text must be
  readable off the arc intercept.
- **Fraud patterns**:
  1. *Rct inconsistency* — text "Rct = 12.3 Ω" but the arc intercept on the
     figure is ~40 Ω (logic track, manual reading).
  2. *EIS reuse across samples* — same arc, different labels (fingerprint).
  3. *Impossible frequencies* — frequency axis spanning 6–7 decades with
     data on all of them at uniform quality (vision: real EIS degrades at
     extremes).
- **Checks**: fingerprint pairs (EIS vs EIS), manual Rct vs arc (logic).

## 9. TGA / DSC

- **Format**: mass % or heat flow vs temperature (°C); TGA often with dTGA
  derivative on a twin axis.
- **Hard ranges**: temperature −273…~1500 °C for common furnaces.
- **What should vary**: noise, onset temperature (±few °C between runs is
  normal — a TGA "reproducibility" table with identical onsets to 0.1 °C is
  itself a finding via `identical_replicates`); **should not**: the
  decomposition pattern family for the same material.
- **Fraud patterns**: reused TGA across compositions; mass-loss % in text vs
  figure mismatch (logic).
- **Checks**: fingerprint pairs (TGA vs TGA), `identical_replicates`,
  manual mass-loss consistency (logic).

## 10. TEM / SEM / AFM (microscopy images)

- **Format**: photographs — 2D gray images with a **scale bar**. These are
  NOT line plots: `spectral_noise_fingerprint` reports them inapplicable;
  use phash/ORB + vision.
- **What should vary**: particle arrangement in a new micrograph (even of the
  same material) is a *different field of view*; the same FOV legitimately
  re-shown twice (e.g., bright-field + dark-field of one area) is fine when
  labeled as such.
- **Fraud patterns**:
  1. *Scale-bar / magnification mismatch* — "50 nm" bar on one image, "200
     nm" bar on a visually identical image with different stated
     magnification (vision measurement: bar pixel length / labeled length;
     same stated magnification ⇒ bars must be same length; >15% off =
     finding).
  2. *Cross-sample reuse* — image of sample A labeled sample B (ORB catches
     transformed reuse).
  3. *Local copy-paste* — one particle region cloned to fill a sparse field
     (ORB on sub-regions / vision: repeated local texture).
  4. *Size distribution claims* — text "monodisperse, 20 ± 2 nm" vs a visibly
     polydisperse image (logic track, vision).
- **Checks**: `panel_split` → `image_dup` → `image_dup_orb`, vision scale-bar
  measurement (recipe in 04), size-claim vs image (logic).

## 11. XPS

- **Format**: counts/s vs binding energy (eV); survey + high-resolution
  (C 1s, N 1s…) with deconvolution fits.
- **Hard ranges**: BE 0–1000 eV; C 1s must sit at ~284.6–284.8 eV after
  charge neutralization — a C 1s peak at 281 eV is a calibration finding
  (manual check, Level 1–2).
- **Fraud patterns**: reused high-res fits across samples (fingerprint on the
  raw peaks, not the fitted curves); fitting "components" that correspond to
  chemically impossible assignments (agent knowledge, logic).
- **Checks**: fingerprint pairs (XPS vs XPS), C 1s position (manual).

## 12. BET / porosimetry

- **Format**: adsorption/desorption isotherm (V vs P/P0) + pore-size
  distribution (BJH).
- **Hard ranges**: P/P0 0–1; S_BET 0.1–5000 m²/g.
- **Fraud patterns**: isotherm reuse across compositions (fingerprint);
  S_BET in table vs isotherm knee inconsistent (logic, manual).
- **Checks**: fingerprint pairs, `impossible_unit_ranges` (m²/g).

## 13. Electrochemical energy storage (GCD / rate capability)

- **Format**: capacity (mAh/g) vs time (h); rate: capacity vs current
  density (A/g); cycling: capacity vs cycle number.
- **What should vary**: cycle-to-cycle fluctuation (real cells show ±1–3%
  jitter; a perfectly smooth cycling curve over 2000 cycles is a Level 1
  finding — `neat_decimals` + vision).
- **Fraud patterns**:
  1. *Cycling reuse* — different materials with identical capacity decay
     profiles (fingerprint pair).
  2. *Capacity inconsistency* — initial capacity in GCD figure ≠ value in the
     summary table (manual cross-check; logic track).
  3. *Rate capability arithmetic* — recovered capacity after rate test ≠
     capacity at the same current in the rate table (manual).
- **Checks**: fingerprint pairs (GCD vs GCD), `identical_replicates`,
  manual cross-figure/table consistency (logic).

## 14. Kinetics / reaction profiles

- **Format**: conversion or product fraction vs time; ln(k) vs 1/T (Arrhenius).
- **Fraud patterns**:
  1. *Conversion profiles that are the same curve rescaled in time* — three
     "different catalysts" whose profiles are identical after x-axis stretch
     (fingerprint absorbs only linear rescaling — flag `near_identical_curve`
     and verify the axis labels visually).
  2. *Impossible rates* — TOF values implying more turnovers than there are
     active sites given the stated loading (manual arithmetic; logic track).
  3. *Selectivity > conversion* or yield ≠ conv×sel (`chem_numeric` checks
     1–2).
- **Checks**: `conversion_selectivity`, `area_percent_sum`, fingerprint
  pairs, manual TOF arithmetic (logic).

---

## Triage shortcut

If the technique is uncertain from the caption alone, the axis units decide:
ppm → NMR/MS-offset; cm⁻¹ → IR/Raman; 2θ → XRD; V/mA → electrochemistry;
min/mL → chromatography; °C → thermal; eV → XPS; nm bar → microscopy;
mAh/g → energy storage. When still uncertain, mark the figure
`unclassified` in the inventory and let the vision pass resolve it — an
unclassified figure that later proves to be a spectrum must be added to the
fingerprint pool (note the correction in the manifest).
