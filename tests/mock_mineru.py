#!/usr/bin/env python3
"""Offline mock of all three MinerU backends, for smoketest.sh.

Implements just enough of:
  - local v1:  POST /v1/tasks, PUT upload, GET /v1/tasks/{id},
               GET /v1/files/{id}/content, GET /v1/health
  - local legacy: POST /file_parse
  - cloud v4: POST /api/v4/file-urls/batch, PUT /upload/{batch},
              GET /api/v4/extract-results/batch/{batch},
              POST /api/v4/extract/task, GET /api/v4/extract/task/{id},
              GET /result.zip

No real parsing: every successful response yields a fixed markdown payload.
Usage: python3 tests/mock_mineru.py <port>
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MD = """# Mock MinerU output

## Table 1. Isolated yields.

<table>
<tr><th>Entry</th><th>Yield (%)</th></tr>
<tr><td>1</td><td>95.0</td></tr>
</table>

Mock paragraph for the evidence ledger. The quick brown fox jumps over the
lazy dog, and the chemistry text is long enough to pass the 50-byte gate.
"""


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("markdown.md", MD)
        zf.writestr("middle_json.json", json.dumps({"pdf_info": []}))
        zf.writestr("structured_content.json", json.dumps({"blocks": []}))
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _base(self):
        return f"http://{self.headers.get('Host', '127.0.0.1')}"

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_PUT(self):
        self._read_body()
        self._json(200, {"ok": True})

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/v1/health":
            self._json(200, {"status": "ok", "version": "mock-4.1.6"})
        elif path.startswith("/v1/tasks/"):
            self._json(200, {
                "task_id": "job_mock", "status": "completed",
                "created_at": "2026-01-01T00:00:00Z",
                "output_formats": ["default"],
                "progress": {"completed": 1, "failed": 0, "total": 1},
                "files": [{
                    "file_id": "file-mock", "file_name": "mock.pdf",
                    "status": "completed",
                    "parse": {"tier": "flash", "duration_ms": 1,
                              "parser_version": "mock"},
                    "result_url": self._base() + "/v1/files/file-mock/content",
                }],
            })
        elif path == "/v1/files/file-mock/content":
            self._send(200, zip_bytes(), "application/zip")
        elif path.startswith("/api/v4/extract-results/batch/"):
            self._json(200, {"code": 0, "data": {"extract_result": [{
                "state": "done", "full_zip_url": self._base() + "/result.zip",
            }]}})
        elif path.startswith("/api/v4/extract/task/"):
            self._json(200, {"code": 0, "data": {
                "state": "done", "full_zip_url": self._base() + "/result.zip",
            }})
        elif path == "/result.zip":
            self._send(200, zip_bytes(), "application/zip")
        else:
            self._json(404, {"detail": "Not Found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        payload = self._read_body()
        if path == "/v1/tasks":
            self._json(202, {
                "task_id": "job_mock", "status": "waiting-file",
                "files": [{
                    "file_id": "file-mock", "file_name": "mock.pdf",
                    "status": "waiting-file",
                    "upload": {
                        "url": self._base() + "/v1/tasks/job_mock/uploads/file-mock",
                        "headers": {"Content-Type": "application/octet-stream"},
                        "expires_at": 4102444800,
                    },
                }],
            })
        elif path == "/file_parse":
            self._json(200, {
                "status": "success", "task_id": "legacy-mock",
                "md_content": MD,
                "content_list": [{"type": "text", "text": "mock"}],
                "middle_json": {"pdf_info": []},
            })
        elif path == "/api/v4/file-urls/batch":
            self._json(200, {"code": 0, "data": {
                "batch_id": "batch-mock",
                "file_urls": [self._base() + "/upload/batch-mock"],
            }})
        elif path == "/api/v4/extract/task":
            self._json(200, {"code": 0, "data": {"task_id": "task-mock"}})
        else:
            self._json(404, {"detail": "Not Found"})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"MOCK_READY {server.server_address[1]}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
