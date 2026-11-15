# Acknowledgements and third-party notices

chem-integrity-auditor is a thin, deterministic pipeline. Nearly all of the
heavy lifting is done by open-source projects and public scientific
databases. This file records what is used, why, and under which terms.

If you maintain one of these projects and believe an attribution is missing
or inaccurate, please open an issue.

## Runtime dependencies

| Project | Used for | License | Link |
|---|---|---|---|
| **Python** | runtime | PSF License | <https://www.python.org/> |
| **Pillow (PIL)** | image I/O, drawing, annotation | HPND | <https://python-pillow.org/> |
| **NumPy** | arrays, projections, correlations, ROC math | BSD-3-Clause | <https://numpy.org/> |
| **OpenCV** | ORB features, template matching, RANSAC homography | Apache-2.0 | <https://opencv.org/> |
| **SciPy** | optional statistical/signal helpers | BSD-3-Clause | <https://scipy.org/> |
| **RDKit** | optional structure/formula cross-check | BSD-3-Clause | <https://www.rdkit.org/> |
| **openpyxl** | optional XLSX cell-level evidence cards | MIT | <https://openpyxl.readthedocs.io/> |

No source code from these projects is vendored into this repository; they are
imported as libraries. Their licenses apply to their own code.

## External binaries

| Project | Used for | License | Notes |
|---|---|---|---|
| **Poppler** (`pdftoppm`, `pdfimages`, `pdftotext`) | PDF page rasterization and image extraction | GPL-2.0 | Invoked as separate executables; not linked into this project. |
| **MinerU** (OpenDataLab) | optional PDF → Markdown parsing (local 4.x / 2.x–3.x and official cloud v4) | AGPL-3.0 (check the upstream repository) | Optional. Used as an external service/container; no MinerU code is vendored. If you deploy a modified MinerU as a network service, AGPL obligations are yours to review. |

## Public scientific databases and services

| Source | Used for | Terms |
|---|---|---|
| **PubChem PUG REST** (NCBI) | compound identity: formula, MW, exact mass, InChIKey, CAS, synonyms | NCBI data usage policy; cite PubChem. <https://pubchem.ncbi.nlm.nih.gov/> |
| **SDBS** (AIST) | reference NMR/IR/MS peak tables, exported manually by the auditor | SDBS terms of use. This project does **not** scrape or bulk-download SDBS. <https://sdbs.db.aist.go.jp/> |
| **NMRShiftDB** | reference NMR peak tables, exported manually | Check upstream license/terms. This project does **not** scrape the database. <https://nmrshiftdb.nmr.uni-koeln.de/> |
| **Europe PMC / PubMed Central** | open-access full text, figure files, retraction notices | NLM terms; PMC figure files remain the publisher's copyright. <https://europepmc.org/> |
| **Retraction Watch / publisher notices** | audit checklists, not redistributed | Cited per paper; notices remain publisher content. |

## Algorithms and ideas

These are implemented from the published descriptions, not copied from a
specific codebase:

- **dHash / aHash perceptual hashing** — the approach popularized by the
  `imagehash` project (<https://github.com/JohannesBuchner/imagehash>) and
  the broader image-forensics community. Our implementation is independent
  and uses Pillow only.
- **ORB** — Rublee, Rabaud, Konolige, Bradski, “ORB: An efficient alternative
  to SIFT or SURF”, ICCV 2011.
- **Lowe ratio test** — Lowe, “Distinctive Image Features from
  Scale-Invariant Keypoints”, IJCV 2004.
- **RANSAC** — Fischler & Bolles, “Random Sample Consensus”, 1981.
- **Benjamini–Hochberg FDR** — Benjamini & Hochberg, JRSS-B 1995.
- **Fisher z transform** — Fisher, 1921; used for the profile-correlation
  fallback.
- **Scherrer equation** — used in the XRD crystallite-size check.
- **Bragg / lattice-plane and XPS spin-orbit conventions** — standard
  textbook relations used in the domain checks.

## Conceptual lineage

The audit workflow (numeric / image / logical tracks, adversarial benign
explanation, evidence-not-verdict grading) was informed by public
research-integrity practice, retraction notices, PubPeer discussions, and
the authors' earlier `integrity-auditor` and `paper-fraud-auditor` skill
designs. Those are conceptual references, not code dependencies.

The npm one-command installer, the `agents/` manifest, and the one-page
“anomaly network” checklist were informed by the public
[research-integrity-auditor](https://github.com/cylqwe7855-alt/research-integrity-auditor)
project. The installer and the chemistry-specific checklist here were written
independently.

Two scripts, `scripts/numeric_forensics.py` and
`scripts/render_evidence_tables.py`, also exist byte-for-byte in that public
project. They come from the authors' shared `paper-fraud-auditor` lineage
rather than from the 0.5.0 comparison; both repositories are MIT-licensed.
They are recorded here for transparency.

## No LLM SDK

This repository contains **no** `anthropic`, `openai`, or other LLM SDK
import. The agent client supplies the reasoning; the scripts supply
deterministic measurements.

## License of this repository

MIT — see [LICENSE](LICENSE). Third-party components, databases, and optional
services remain under their own licenses/terms listed above.
