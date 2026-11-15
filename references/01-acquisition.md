# 01 — Acquisition

What you acquire decides what you can audit. In chemistry, **the Supplementary
Information is where the substantive evidence lives**: full NMR spectra, XRD
patterns, HRMS data, HPLC/GC chromatograms, CV/EIS raw curves, kinetic plots.
A main-text-only audit of a chemistry paper is usually an audit of
summarized numbers — still valuable, but report the limitation explicitly.

## Input modes

| Mode | Detection | First action |
|---|---|---|
| PDF path | local `*.pdf` | copy to `$RUN/paper.pdf`, `file` it, start Step 2 |
| DOI | `10.xxxx/...` | resolve via doi.org → publisher landing page → HTML first |
| Article URL | any journal page | fetch HTML first |
| Retraction-notice audit | user names a retracted paper | fetch the **retraction notice** too (see below) |

Once a PDF is in hand, parsing is done by `mineru_convert.py`. It supports a
local MinerU 4.x v1 API, a local 2.x/3.x legacy `/file_parse`, and the
official cloud v4 — the backend choice, CPU tier caveats and troubleshooting
are in `09-mineru-setup.md`. If the article is in PMC (Route B), skip MinerU
and use `pmc_fetch.py`.

## Acquisition order (try every step, do not stop early)

1. **Landing HTML** — usually open even when the PDF is gated.
   ```bash
   curl -sL -A "Mozilla/5.0" "<article URL>" -o $RUN/paper.html
   ```
   This page carries: abstract, all figure captions, direct links to every
   supplementary file, and high-resolution figure images.
2. **Harvest CDN links from the HTML**:
   ```bash
   grep -oE 'https?://[^"]+[^">]' $RUN/paper.html | grep -iE \
     '(supplementary|supporting|SI|figure|fig|media|cdn|\.pdf|\.xlsx|\.docx|\.zip|\.png)' \
     | sort -u
   ```
   Download every distinct supplementary file to `$RUN/supplementary/`,
   every hi-res figure to `$RUN/figures_hires/`. Chemistry SI is most often
   one or two PDFs (spectrum collections) plus occasional XLSX (data tables).
3. **Publisher SI/figure routes** (canonical examples — adapt per publisher):
   - ACS: `<article>.pdf` → SI at `/doi/suppl/10.xxx/si/<doi>_si_01.pdf`
   - RSC: SI PDF linked directly on the article page (`/article/<id>/scsi-<id>.pdf`)
   - Wiley: SI at `onlinelibrary.wiley.com/doi/<doi>/supinfo` (HTML) + PDF
   - Elsevier: SI PDF via article page "Supplementary Material" link
   - Springer/Nature: `MOESM*` files on open CDN endpoints
   - PLoS ONE / open journals: SI PDFs always open
   Never conclude "paywalled, audit blocked" before trying these routes.
4. **Retraction / correction notices** — CRITICAL when auditing a known
   retracted or corrected paper. Fetch the notice itself (usually a short
   HTML/PDF on the article page). Extract every specific charge it makes
   ("Fig 3A and 3B are duplicates", "the NMR data do not support the
   assignment") and write them to `$RUN/claim_checklist.md` — one testable
   hypothesis per line. Each audit track then has a second job: try to
   reproduce or refute each notice charge at the pixel/value level. A notice
   charge you **cannot** reproduce at the available resolution is a Level 3
   ("需原始数据裁定"), not a clean bill for that figure.
5. **Article PDF** — `curl -sL -A "Mozilla/5.0" "<url>.pdf" -o $RUN/paper.pdf`
   then `file $RUN/paper.pdf` (confirm it is a real PDF, not an HTML auth
   wall). If gated and HTML gave nothing: record the block and continue with
   whatever was acquired.

## PMC route (when the publisher is unreachable)

Server/datacenter networks are often Cloudflare-gated out of publisher sites
(RSC, Wiley, ACS) while PubMed Central remains reachable. When Step 2 of the
acquisition order fails with 403/challenge pages **and** the article is in
PMC (check: Europe PMC REST `search?query=DOI:"<doi>"` — no key needed):

```bash
# 1) confirm PMC id
curl -s "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:%22<doi>%22&format=json" \
  | python3 -c "import json,sys; [print(r.get('pmcid'), r.get('hasPDF'), r.get('title','')[:60]) for r in json.load(sys.stdin)['resultList']['result'][:3]]"

# 2) fetch fulltext XML + original figure files
python3 <skill>/scripts/pmc_fetch.py --pmcid PMC<id> --output $RUN/workdir
```

Facts learned the hard way (2026-11-14 eval runs):

- The eutils `efetch.fcgi?db=pmc&id=<n>` endpoint is NOT bot-gated and
  returns the full NLM article XML with structured `<table>` elements
  (better table fidelity than MinerU markdown for the numeric track).
- `pmc_fetch.py` converts the XML to a MinerU-compatible `full.md`
  (real HTML `<table>` blocks + `[[FIG:id | label | files | caption]]`
  anchors — the anchors are the technique-inventory input for Step 3).
- Figure files at
  `https://pmc.ncbi.nlm.nih.gov/articles/instance/<n>/bin/<file>` are the
  PUBLISHER'S ORIGINALS (600 DPI for RSC) and are curl-able — **pace the
  requests** (≥4 s gap) and retry: a 200 whose body is HTML is the PoW/
  captcha page, not the image; the script detects and retries that.
- The article PDF (`/articles/PMC<id>/pdf/<name>`) sits behind a JS
  proof-of-work gate and is NOT curl-able; `pmc_fetch.py` writes
  `pdf_candidate.txt` with the name (read from the XML's
  `content-type="pmc-pdf"` graphic) for a human or real-browser fetch.
  Record the PDF as blocked in the manifest and proceed on Route B —
  the figure files plus XML text cover both tracks.
- SI PDFs are likewise PoW-gated. If SI data (HRMS found values, extra
  spectra) is needed and unavailable, say so in the report's 局限性 section;
  the numeric HRMS check simply runs on main-text data only.

Retraction status is visible in the XML itself (`related-article-type=
"retraction-forward"` link) and on the PMC page header — capture the
retraction notice (usually a separate PMC id, linked from the article) via
the same efetch route and build `claim_checklist.md` from it.

## SI processing

Treat the SI PDF as a **second input to the same pipeline**:

```bash
python3 <skill>/scripts/mineru_convert.py $RUN/supplementary/si.pdf \
    --output $RUN/workdir_si --backend-mode auto
python3 <skill>/scripts/chem_numeric.py $RUN/workdir_si --output $RUN/workdir_si/chem_numeric.json
```

If the local server is CPU-only, add `--tier flash` (or `basic`); see
`09-mineru-setup.md` for the tier/GPU matrix.

SI spectra are line-plot figures — extract their panels with poppler the
same way as the article, prefix `si-` to panel names, and include them in the
technique inventory and the image-track pair pool. HRMS "found" values and
CHN tables almost always live in the SI text — the document-level
`chem_numeric.py` scan of `workdir_si/full.md` catches formula/m/z pairs
there.

## Manifest

`$RUN/input_manifest.md` must list, at minimum:

- every file acquired (path, size, sha256 for PDFs)
- every attempted-but-blocked source (publisher, URL, HTTP status)
- MinerU source (local version / cloud) and `full.md` size
- panel counts (article + SI), raster vs page-render
- `paper_class.txt` value (written later, listed here for completeness)
- a `## progress` section appended after each batch (see 00)

Paywall honesty: if the article body is thin and the SI is blocked, the
report opens by saying exactly which lines could and could not be audited.
