# 09 — MinerU backends (local + official cloud)

MinerU is needed **only for the PDF/DOI article route (Route A)** and for
SI PDFs. The PMC route (Route B, `pmc_fetch.py`) bypasses MinerU entirely:
PMC's XML already has real tables and figure anchors.

`mineru_convert.py` supports three backends, tried in this order under
`--backend-mode auto`:

1. **Local MinerU 4.x** — v1 async task API (`POST /v1/tasks`).
2. **Local MinerU 2.x/3.x** — legacy synchronous `POST /file_parse`.
3. **Official cloud** — `https://mineru.net` API v4, token required.

Only the cloud needs a token. Local parsing works offline.

## Quick check

```bash
# is a local server up? is a cloud token present?
python3 <skill>/scripts/mineru_convert.py --probe
```

## Local MinerU 4.x (recommended)

The 4.x `mineru-api` no longer exposes `/file_parse` (it returns 404). The
v1 flow is: create task → PUT the returned upload URL → poll the task →
download the result ZIP.

Start a server (Docker example; use your own image if different):

```bash
docker run -d --name mineru-api \
  -p 127.0.0.1:8000:8000 \
  -e MINERU_MODEL_SOURCE=local \
  -e MINERU_DEVICE_MODE=cpu \
  mineru:4.1.6 \
  mineru-api --host 0.0.0.0 --port 8000
```

- **Port**: if 8000 is occupied (common), map to another host port, e.g.
  `-p 127.0.0.1:18000:8000`, and set
  `export MINERU_BASE_URL=http://127.0.0.1:18000`.
- **GPU**: the 4.1.6 image needs CUDA 13 / a matching driver for `--gpus all`.
  On older drivers (e.g. 535) run CPU mode with `MINERU_DEVICE_MODE=cpu`.
- **Tier**: `tier=auto` may pick a VLM tier that needs a GPU; on CPU pass
  `--tier flash` (fast text) or `--tier basic`. A CPU run that picked the
  VLM tier fails with `Device string must not be empty`.
- **API key**: if the server was started with `--api-key`, set
  `MINERU_API_KEY`; anonymous local servers need nothing.

Convert:

```bash
python3 <skill>/scripts/mineru_convert.py paper.pdf \
    --output "$RUN/workdir" \
    --backend-mode local \
    --base-url "${MINERU_BASE_URL:-http://127.0.0.1:8000}" \
    --tier flash \
    --interval 2
```

The result ZIP ships `markdown.md`, `middle_json.json`,
`structured_content.json` and `images/`. The script copies `markdown.md` to
`full.md` (the pipeline's contract) and keeps the JSON files.

## Local MinerU 2.x/3.x (legacy)

Older deployments expose a synchronous `POST /file_parse` that returns
`md_content` directly (sometimes a ZIP). Force it with:

```bash
python3 <skill>/scripts/mineru_convert.py paper.pdf \
    --output "$RUN/workdir" --backend-mode local --local-api legacy
```

`auto` tries v1 first and falls back to legacy on 404/405, so normally you
do not need this flag.

## Official cloud (mineru.net v4)

1. Create a token at <https://mineru.net> (account → API).
2. Export it **in the environment only** — never in a skill file or report:

```bash
export MINERU_API_TOKEN="..."
```

   Optional persistent location (outside the repository, mode `600`):

   ```bash
   mkdir -p ~/.config/chem-integrity-auditor
   chmod 700 ~/.config/chem-integrity-auditor
   printf 'MINERU_API_TOKEN=%s\n' 'your-token' \
     > ~/.config/chem-integrity-auditor/mineru.env
   chmod 600 ~/.config/chem-integrity-auditor/mineru.env
   set -a; . ~/.config/chem-integrity-auditor/mineru.env; set +a
   ```

   The scripts do not read this file automatically; source it in the shell
   (or add the three lines to `~/.bashrc`).

3. Convert (local file → batch upload → poll → ZIP):

```bash
python3 <skill>/scripts/mineru_convert.py paper.pdf \
    --output "$RUN/workdir" --backend-mode cloud \
    --model-version vlm --interval 5
```

Options:

| Flag | Meaning |
|---|---|
| `--model-version pipeline\|vlm\|MinerU-HTML` | cloud parsing model (default vlm) |
| `--lang en\|ch` | document language hint |
| `--ocr` | force OCR (`is_ocr=true`) |
| `--page-ranges "1-5,8"` | restrict pages |
| `--timeout`, `--interval` | polling budget / cadence |

`MINERU_API_BASE` overrides the cloud base URL (default
`https://mineru.net`). It exists for testing against a mock or a private
proxy; leave it unset in normal use.

## Backend selection

| Mode | Behaviour |
|---|---|
| `--backend-mode auto` (default) | local v1 → local legacy → cloud (only if token set) |
| `--backend-mode local` | local v1 → local legacy; never cloud |
| `--backend-mode cloud` | cloud only |
| `--local-api v1\|legacy` | restrict the local flavour |

URL inputs (`https://…/paper.pdf`) go to the cloud backend; local backends
need a local PDF path.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `HTTP 404: {"detail":"Not Found"}` on `/file_parse` | server is MinerU 4.x — use v1 (auto handles it) |
| `Device string must not be empty` | CPU host + VLM tier — `--tier flash` or `--tier basic` |
| `Connection refused` | server not running / wrong `MINERU_BASE_URL` / port mapping |
| cloud `HTTP 401` / `A0202` | token missing, invalid or expired |
| cloud `code != 0` | API error; the message is printed verbatim |
| result ZIP has `markdown.md`, no `full.md` | normal for 4.x; the script normalises it |
| `Local legacy MinerU returned no markdown` | 2.x server returned no `md_content`; check its logs / model files |

## What the rest of the pipeline expects

- `workdir/full.md` — markdown with HTML `<table>` blocks and figure
  captions (the numeric and reference-spectrum tracks read this).
- `workdir/mineru_manifest.json` — backend, task id, tier, extracted files;
  cite it in `input_manifest.md`.
- Images for the image track still come from **poppler**, not MinerU
  (`pdfimages` / `pdftoppm`), so a text-only `md_content` response is fine.
