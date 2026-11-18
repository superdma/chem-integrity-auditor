#!/usr/bin/env python3
"""Convert a paper PDF to ``full.md`` — native, local MinerU and cloud.

Backends, tried in this order by ``--backend-mode auto``:

0. **Native PDF** — ``pdfplumber`` text/ruled tables + optional
   ``pypdfium2`` figure crops. No MinerU service or token is needed. This is
   the default for born-digital PDFs; image-only/scanned PDFs fall through.
1. **Local MinerU 4.x** — ``mineru-api`` v1 task API:
   ``POST /v1/tasks`` → PUT the upload link → poll ``GET /v1/tasks/{id}``
   → download the result ZIP. Configured by ``MINERU_BASE_URL``
   (default ``http://127.0.0.1:8000``). Anonymous local servers need no key;
   if the server was started with ``--api-key``, set ``MINERU_API_KEY``.
2. **Local MinerU 2.x/3.x (legacy)** — synchronous ``POST /file_parse``.
   Used automatically when ``/v1/tasks`` is 404/405.
3. **Official cloud** — ``https://mineru.net`` API v4
   (``/api/v4/file-urls/batch`` for local files, ``/api/v4/extract/task``
   for URLs), token in ``MINERU_API_TOKEN``. The base URL can be overridden
   with ``MINERU_API_BASE`` for testing.

Only the official cloud needs a token. Native and local parsing work offline.

CPU-only local deployments: MinerU 4.x ``tier=auto`` may select a VLM tier
that needs a GPU. Use ``--tier flash`` (fast text extraction) or
``--tier basic`` on CPU; the failure message in that case is
"Device string must not be empty".

Outputs are normalised to ``full.md`` in the output directory. MinerU 4.x
ZIPs ship ``markdown.md``; the script also copies it to ``full.md`` and keeps
``middle_json.json`` / ``structured_content.json`` when present.

Python 3.8+. Stdlib only. No token is ever printed or written to disk.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

LOCAL_DEFAULT = "http://127.0.0.1:8000"
CLOUD_DEFAULT = "https://mineru.net"
TERMINAL_OK = {"done", "completed", "partial", "success"}
TERMINAL_BAD = {"failed", "canceled", "error"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def is_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"}


def auth_headers(token: str = None) -> dict:
    headers = {"Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def write_manifest(output_dir: pathlib.Path, manifest: dict) -> None:
    (output_dir / "mineru_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def find_md_content(obj) -> str:
    """Recursively find an ``md_content`` / ``markdown`` string in a JSON tree."""
    if isinstance(obj, dict):
        for key in ("md_content", "markdown", "md"):
            val = obj.get(key)
            if isinstance(val, str) and len(val) > 50:
                return val
        for val in obj.values():
            found = find_md_content(val)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_md_content(item)
            if found:
                return found
    return ""


def save_extra_json_fields(obj, output_dir: pathlib.Path, prefix: str) -> list:
    saved = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("content_list", "middle_json", "structured_content",
                       "middle_json.json") and isinstance(val, (list, dict)):
                path = output_dir / f"{prefix}_{key}.json"
                path.write_text(json.dumps(val, ensure_ascii=False),
                                encoding="utf-8")
                saved.append(str(path))
            elif isinstance(val, (dict, list)):
                saved.extend(save_extra_json_fields(val, output_dir, prefix))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            saved.extend(save_extra_json_fields(item, output_dir,
                                                f"{prefix}_{i}"))
    return saved


def unpack_zip(zip_path: pathlib.Path, output_dir: pathlib.Path) -> list:
    """Extract a MinerU ZIP with path-traversal protection."""
    extracted = []
    root = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (root / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                raise RuntimeError(f"Unsafe zip path: {member.filename}")
            zf.extract(member, output_dir)
            extracted.append(member.filename)
    return extracted


def ensure_full_md(output_dir: pathlib.Path) -> str:
    """Return the markdown text and guarantee ``full.md`` exists."""
    for name in ("full.md", "markdown.md", "paper.md"):
        candidate = output_dir / name
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if len(text) > 50:
                if name != "full.md":
                    (output_dir / "full.md").write_text(text,
                                                        encoding="utf-8")
                return text
    for candidate in sorted(output_dir.rglob("*.md")):
        text = candidate.read_text(encoding="utf-8", errors="replace")
        if len(text) > 200:
            (output_dir / "full.md").write_text(text, encoding="utf-8")
            return text
    return ""


def native_convert(file_path: pathlib.Path, output_dir: pathlib.Path,
                   dpi: int = 200, figures: bool = True,
                   table_strategy: str = "lines") -> dict:
    """Try the no-MinerU backend; return a manifest or raise."""
    try:
        import pdf_native_extract
    except ImportError as exc:
        raise RuntimeError(
            "native backend needs pdfplumber: "
            "python3 -m pip install 'pdfplumber>=0.11,<0.11.5'"
        ) from exc
    native = pdf_native_extract.extract(
        file_path, output_dir, dpi=dpi, figures=figures,
        table_strategy=table_strategy)
    if not native.get("text_chars"):
        raise RuntimeError(
            "native backend found no extractable text (scanned PDF); "
            "use MinerU or OCR")
    manifest = dict(native)
    manifest.update({
        "backend": "native-pdf",
        "input": str(file_path),
        "output_dir": str(output_dir),
        "full_md": str(output_dir / "full.md"),
        "full_md_bytes": (output_dir / "full.md").stat().st_size,
        "native_manifest": str(output_dir / "native_manifest.json"),
    })
    return manifest


def download_file(url: str, target: pathlib.Path, headers: dict = None,
                  attempts: int = 4) -> None:
    headers = headers or {"Accept": "*/*"}
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as response:
                with target.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            return
                        handle.write(chunk)
        except Exception as exc:  # noqa: BLE001 - network errors are broad
            last_error = exc
            if target.exists():
                target.unlink()
            if attempt < attempts:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Download failed after {attempts} attempts: "
                       f"{last_error}")


def download_and_unpack(result_url: str, output_dir: pathlib.Path,
                        headers: dict, stem: str) -> list:
    """Download a result URL (ZIP or JSON), unpack it, normalise full.md."""
    target = output_dir / f"{stem}.bin"
    download_file(result_url, target, headers)
    extracted = []
    if target.read_bytes()[:2] == b"PK":
        zip_path = output_dir / f"{stem}.zip"
        target.replace(zip_path)
        extracted = unpack_zip(zip_path, output_dir)
    else:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            md = find_md_content(payload)
            if md:
                (output_dir / "full.md").write_text(md, encoding="utf-8")
            save_extra_json_fields(payload, output_dir, stem)
        except Exception:
            pass
    ensure_full_md(output_dir)
    return extracted


# ---------------------------------------------------------------------------
# Local MinerU 4.x — v1 async task API
# ---------------------------------------------------------------------------

def request_json(method: str, url: str, token: str = None,
                 payload: dict = None, timeout: int = 60) -> dict:
    headers = auth_headers(token)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MinerU HTTP {exc.code}: {body[:500]}") from exc
    result = json.loads(body)
    if result.get("code") not in (None, 0) and result.get("success") is False:
        raise RuntimeError(f"MinerU API error {result.get('code')}: "
                           f"{result.get('msg') or result.get('message')}")
    return result


def put_bytes(url: str, file_path: pathlib.Path, headers: dict) -> None:
    """PUT a file to a presigned/upload URL without adding a Content-Type."""
    parsed = urllib.parse.urlparse(url)
    body = file_path.read_bytes()
    path = urllib.parse.urlunparse(("", "", parsed.path, parsed.params,
                                    parsed.query, ""))
    cls = (http.client.HTTPSConnection if parsed.scheme == "https"
           else http.client.HTTPConnection)
    conn = cls(parsed.netloc, timeout=300)
    try:
        conn.putrequest("PUT", path)
        conn.putheader("Host", parsed.netloc)
        for key, value in (headers or {}).items():
            if key.lower() not in ("host", "content-length"):
                conn.putheader(key, value)
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        status = response.status
        response_body = response.read().decode("utf-8", errors="replace")
    finally:
        conn.close()
    if status < 200 or status >= 300:
        raise RuntimeError(f"Upload failed with HTTP {status}: "
                           f"{response_body[:300]}")


def local_v1_convert(file_path: pathlib.Path, output_dir: pathlib.Path,
                     base_url: str, tier: str, ocr_mode: str,
                     page_range: str, timeout: int, interval: int,
                     token: str = None) -> dict:
    """MinerU 4.x local API: create task, upload, poll, download ZIP."""
    base = base_url.rstrip("/")
    payload = {
        "files": [{"file_name": file_path.name,
                   "bytes": file_path.stat().st_size}],
        "output_formats": ["default"],
        "ocr_mode": ocr_mode,
    }
    if tier and tier != "auto":
        payload["tier"] = tier
    if page_range:
        payload["page_range"] = page_range
        payload["files"][0]["page_range"] = page_range
    print(f"[local-v1] POST {base}/v1/tasks ({file_path.stat().st_size / 1e6:.1f} MB)",
          flush=True)
    created = request_json("POST", f"{base}/v1/tasks", token, payload)
    task_id = created.get("task_id")
    files = created.get("files") or []
    if not task_id or not files:
        raise RuntimeError(f"create-task response missing task/files: {created}")
    upload = files[0].get("upload") or {}
    upload_url = urllib.parse.urljoin(base + "/", upload.get("url", ""))
    if not upload_url:
        raise RuntimeError("create-task response has no upload URL")
    upload_headers = dict(upload.get("headers") or {})
    put_bytes(upload_url, file_path, upload_headers)

    deadline = time.time() + timeout
    detail = None
    while time.time() < deadline:
        detail = request_json("GET", f"{base}/v1/tasks/{task_id}", token)
        state = detail.get("status")
        print(f"[local-v1] state={state}", flush=True)
        if state in TERMINAL_OK | TERMINAL_BAD:
            break
        time.sleep(interval)
    if detail is None or detail.get("status") not in TERMINAL_OK:
        err = (detail or {}).get("error") or {}
        raise TimeoutError(f"local task {task_id} did not complete: "
                           f"{detail.get('status') if detail else 'no response'}"
                           f" {err}")

    file_detail = (detail.get("files") or [{}])[0]
    result_url = file_detail.get("result_url")
    if not result_url:
        raise RuntimeError(f"task completed without result_url: {file_detail}")
    result_url = urllib.parse.urljoin(base + "/", result_url)
    extracted = download_and_unpack(result_url, output_dir,
                                    auth_headers(token), f"mineru_{task_id}")
    if not (output_dir / "full.md").exists():
        raise RuntimeError("MinerU result contained no markdown")
    return {
        "source": f"local MinerU 4.x v1 API, tier={tier}, {base}/v1/tasks",
        "input_pdf": str(file_path),
        "task_id": task_id,
        "tier": (file_detail.get("parse") or {}).get("tier", tier),
        "extracted_files": extracted[:100],
        "markdown_bytes": (output_dir / "full.md").stat().st_size,
    }


# ---------------------------------------------------------------------------
# Local MinerU 2.x/3.x — legacy synchronous /file_parse
# ---------------------------------------------------------------------------

def local_legacy_convert(file_path: pathlib.Path, output_dir: pathlib.Path,
                         base_url: str, backend: str, lang: str,
                         timeout: int) -> dict:
    url = base_url.rstrip("/") + "/file_parse"
    boundary = uuid.uuid4().hex
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    add_field("backend", backend)
    add_field("parse_method", "auto")
    add_field("lang_list", lang)
    add_field("formula_enable", "true")
    add_field("table_enable", "true")
    add_field("return_md", "true")
    add_field("return_content_list", "true")
    add_field("return_middle_json", "true")
    add_field("return_images", "false")
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"files\"; filename=\"{file_path.name}\"\r\n".encode())
    body.extend(b"Content-Type: application/pdf\r\n\r\n")
    body.extend(file_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        url, data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Accept": "*/*"},
        method="POST")
    print(f"[local-legacy] POST {url} "
          f"({file_path.stat().st_size / 1e6:.1f} MB)", flush=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if raw[:2] == b"PK":
        zip_path = output_dir / "mineru_legacy.zip"
        zip_path.write_bytes(raw)
        extracted = unpack_zip(zip_path, output_dir)
        ensure_full_md(output_dir)
        return {"source": f"local MinerU legacy /file_parse, {url}",
                "input_pdf": str(file_path), "extracted_files": extracted}
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    md = find_md_content(payload)
    if not md:
        result_url = payload.get("result_url")
        if result_url:
            download_and_unpack(result_url, output_dir, {"Accept": "*/*"},
                                "mineru_legacy")
            md = ensure_full_md(output_dir)
    if not md:
        raise RuntimeError(
            f"Local legacy MinerU returned no markdown. "
            f"status={payload.get('status')} keys={list(payload.keys())}")
    (output_dir / "full.md").write_text(md, encoding="utf-8")
    extra = save_extra_json_fields(payload, output_dir, "mineru_legacy")
    return {"source": f"local MinerU legacy /file_parse, {url}",
            "input_pdf": str(file_path), "task_id": payload.get("task_id"),
            "status": payload.get("status"),
            "markdown_bytes": len(md.encode("utf-8")),
            "extra_files": extra}


# ---------------------------------------------------------------------------
# Official cloud — mineru.net API v4
# ---------------------------------------------------------------------------

def cloud_base() -> str:
    return os.environ.get("MINERU_API_BASE", CLOUD_DEFAULT).rstrip("/")


def cloud_convert(input_value: str, output_dir: pathlib.Path,
                  model_version: str, language: str, ocr: bool,
                  page_ranges, timeout: int, interval: int) -> dict:
    token = os.environ.get("MINERU_API_TOKEN")
    if not token:
        raise RuntimeError("cloud backend requires MINERU_API_TOKEN")
    base = cloud_base()

    common = {
        "model_version": model_version,
        "enable_table": True,
        "enable_formula": True,
        "language": language,
        "is_ocr": bool(ocr),
    }
    if page_ranges:
        common["page_ranges"] = page_ranges

    if is_url(input_value):
        payload = dict(common)
        payload["url"] = input_value
        created = request_json("POST", f"{base}/api/v4/extract/task",
                               token, payload)
        task_id = created["data"]["task_id"]
        url = f"{base}/api/v4/extract/task/{task_id}"
        deadline = time.time() + timeout
        task_data = None
        while time.time() < deadline:
            data = request_json("GET", url, token)["data"]
            state = data.get("state")
            print(f"[cloud] state={state}", flush=True)
            if state == "done":
                task_data = data
                break
            if state == "failed":
                raise RuntimeError(f"MinerU task failed: {data.get('err_msg')}")
            time.sleep(interval)
        if task_data is None:
            raise TimeoutError(f"Timed out waiting for task {task_id}")
        source = {"kind": "url", "value": input_value, "task_id": task_id}
    else:
        file_path = pathlib.Path(input_value).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        payload = dict(common)
        payload["files"] = [{"name": file_path.name,
                             "data_id": file_path.stem}]
        created = request_json("POST", f"{base}/api/v4/file-urls/batch",
                               token, payload)
        batch_id = created["data"]["batch_id"]
        upload_urls = created["data"]["file_urls"]
        if not upload_urls:
            raise RuntimeError("MinerU returned no upload URL")
        put_bytes(upload_urls[0], file_path, {})
        url = f"{base}/api/v4/extract-results/batch/{batch_id}"
        deadline = time.time() + timeout
        task_data = None
        while time.time() < deadline:
            items = request_json("GET", url, token)["data"].get(
                "extract_result", [])
            if items:
                state = items[0].get("state")
                print(f"[cloud] state={state}", flush=True)
                if state == "done":
                    task_data = items[0]
                    break
                if state == "failed":
                    raise RuntimeError(
                        f"MinerU task failed: {items[0].get('err_msg')}")
            time.sleep(interval)
        if task_data is None:
            raise TimeoutError(f"Timed out waiting for batch {batch_id}")
        source = {"kind": "local_file", "file_name": file_path.name,
                  "batch_id": batch_id}

    zip_url = task_data.get("full_zip_url")
    if not zip_url:
        raise RuntimeError("MinerU completed but did not return full_zip_url")
    extracted = download_and_unpack(zip_url, output_dir,
                                    {"Accept": "*/*"}, "mineru_cloud")
    if not (output_dir / "full.md").exists():
        raise RuntimeError("cloud result contained no markdown")
    return {
        "source": f"cloud mineru.net v4, {base}",
        "input": source,
        "model_version": model_version,
        "language": language,
        "extracted_files": extracted[:100],
        "markdown_bytes": (output_dir / "full.md").stat().st_size,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a paper PDF (native → local MinerU v1 → legacy "
                    "→ official cloud).")
    parser.add_argument("input", nargs="?",
                        help="Local PDF path or a public URL (omit with --probe).")
    parser.add_argument("--output", help="Output working directory.")
    parser.add_argument("--backend-mode", default="auto",
                        choices=["auto", "native", "local", "cloud"],
                        help="auto: native → local v1 → local legacy → cloud.")
    parser.add_argument("--native-dpi", type=int, default=200,
                        help="Native figure-crop DPI (default 200).")
    parser.add_argument("--native-no-figures", action="store_true",
                        help="Native backend: skip page rendering/figure crops.")
    parser.add_argument("--no-native", action="store_true",
                        help="Skip the native backend even under auto "
                             "(force MinerU/local/cloud).")
    parser.add_argument("--native-table-strategy", default="lines",
                        choices=["lines", "text"],
                        help="Native pdfplumber table strategy (default lines).")
    parser.add_argument("--local-api", default="auto",
                        choices=["auto", "v1", "legacy"],
                        help="Local API flavour (default auto: v1 then legacy).")
    parser.add_argument("--base-url",
                        default=os.environ.get("MINERU_BASE_URL", LOCAL_DEFAULT),
                        help=f"Self-hosted MinerU base URL "
                             f"(default {LOCAL_DEFAULT}).")
    parser.add_argument("--api-key",
                        default=os.environ.get("MINERU_API_KEY"),
                        help="Local API key when mineru-api used --api-key.")
    parser.add_argument("--tier", default="auto",
                        choices=["auto", "flash", "basic", "standard",
                                 "advanced"],
                        help="Local MinerU 4.x tier. CPU-only deployments "
                             "usually need flash or basic (default auto).")
    parser.add_argument("--ocr-mode", default="auto",
                        choices=["auto", "txt", "ocr"],
                        help="Local 4.x OCR mode (default auto).")
    parser.add_argument("--parse-backend", default="pipeline",
                        choices=["pipeline", "vlm", "vlm-client"],
                        help="Legacy local backend (default pipeline).")
    parser.add_argument("--lang", default="en", choices=["en", "ch"],
                        help="Document language hint (default en).")
    parser.add_argument("--ocr", action="store_true",
                        help="Cloud: force OCR (is_ocr=true).")
    parser.add_argument("--page-ranges", default="",
                        help="Cloud/local 4.x page range, e.g. '1-5,8'.")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--model-version", default="vlm",
                        choices=["pipeline", "vlm", "MinerU-HTML"],
                        help="Cloud model version (cloud only).")
    parser.add_argument("--probe", action="store_true",
                        help="Check local/cloud availability and exit.")
    return parser.parse_args()


def probe(base_url: str) -> int:
    base = base_url.rstrip("/")
    result = {"local": {}, "cloud": {}, "native": {}}
    for module in ("pdfplumber", "pypdfium2"):
        try:
            import importlib.util
            found = importlib.util.find_spec(module) is not None
        except Exception:  # noqa: BLE001
            found = False
        result["native"][module] = found
    for path in ("/v1/health", "/docs", "/openapi.json"):
        try:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                result["local"] = {"url": base + path, "http": response.status}
                break
        except Exception as exc:  # noqa: BLE001
            result["local"] = {"url": base + path, "error": str(exc)}
    token = os.environ.get("MINERU_API_TOKEN")
    result["cloud"] = {
        "base": cloud_base(),
        "token_present": bool(token),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    local_ok = "http" in result["local"]
    native_ok = result["native"].get("pdfplumber", False)
    return 0 if (native_ok or local_ok or token) else 1


def main() -> int:
    args = parse_args()
    if args.probe:
        return probe(args.base_url)
    if not args.input or not args.output:
        print("input and --output are required (or use --probe)",
              file=sys.stderr)
        return 2
    if args.no_native and args.backend_mode == "native":
        print("--no-native conflicts with --backend-mode native",
              file=sys.stderr)
        return 2
    output_dir = pathlib.Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    input_value = args.input

    if not is_url(input_value):
        file_path = pathlib.Path(input_value).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(file_path)
    else:
        file_path = None

    if is_url(input_value) and args.backend_mode in ("local", "auto", "native"):
        print("[local/native] URL input needs cloud backend; a local PDF path "
              "is required for local or native parsing.", file=sys.stderr)
        if args.backend_mode in ("local", "native"):
            return 1

    manifest = None
    errors = []
    if file_path and not args.no_native and args.backend_mode in ("auto", "native"):
        try:
            manifest = native_convert(
                file_path, output_dir, dpi=args.native_dpi,
                figures=not args.native_no_figures,
                table_strategy=args.native_table_strategy)
            print("[native] extracted text/tables without MinerU",
                  file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"native: {exc}")
            print(f"[native] unavailable ({exc})", file=sys.stderr)
        if manifest is None and args.backend_mode == "native":
            print("Native PDF extraction failed.", file=sys.stderr)
            (output_dir / "mineru_manifest.json").write_text(
                json.dumps({"error": "native conversion failed",
                            "details": errors}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return 1

    if manifest is None and file_path and args.backend_mode in ("auto", "local"):
        order = ([args.local_api] if args.local_api != "auto"
                 else ["v1", "legacy"])
        for flavour in order:
            try:
                if flavour == "v1":
                    manifest = local_v1_convert(
                        file_path, output_dir, args.base_url, args.tier,
                        args.ocr_mode, args.page_ranges, args.timeout,
                        args.interval, args.api_key)
                else:
                    manifest = local_legacy_convert(
                        file_path, output_dir, args.base_url,
                        args.parse_backend, args.lang, args.timeout)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local-{flavour}: {exc}")
                print(f"[local-{flavour}] unavailable ({exc})", file=sys.stderr)
        if manifest is None and args.backend_mode == "local":
            print("Local MinerU failed in all API flavours.", file=sys.stderr)
            (output_dir / "mineru_manifest.json").write_text(
                json.dumps({"error": "local conversion failed",
                            "details": errors}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return 1

    if manifest is None and args.backend_mode in ("auto", "cloud"):
        if not os.environ.get("MINERU_API_TOKEN"):
            print("[cloud] skipped: MINERU_API_TOKEN not set.", file=sys.stderr)
        else:
            try:
                manifest = cloud_convert(
                    input_value, output_dir, args.model_version, args.lang,
                    args.ocr, args.page_ranges, args.timeout, args.interval)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cloud: {exc}")
                print(f"[cloud] failed: {exc}", file=sys.stderr)

    if manifest is None:
        print("All MinerU backends failed:\n" + "\n".join(errors),
              file=sys.stderr)
        (output_dir / "mineru_manifest.json").write_text(
            json.dumps({"error": "conversion failed", "details": errors},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    if errors:
        manifest["warnings"] = errors
    manifest["output_dir"] = str(output_dir)
    manifest["backend_mode"] = args.backend_mode
    manifest["full_md"] = str(output_dir / "full.md")
    manifest["full_md_bytes"] = (output_dir / "full.md").stat().st_size
    write_manifest(output_dir, manifest)
    print(json.dumps({"output_dir": str(output_dir),
                      "manifest": str(output_dir / "mineru_manifest.json"),
                      "full_md": str(output_dir / "full.md")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
