#!/usr/bin/env python3
"""audit_run_manifest.py — record what an audit run actually inspected.

An integrity report is only reviewable if a reader can see which files were
present, which checks produced output, and whether a whole evidence track is
missing. This script inventories an audit run directory and writes
``audit_run_manifest.json``:

* input artefacts (PDF, full.md, tables/figures JSON, source-data workbooks)
  with sizes and SHA-256;
* tool/dependency versions;
* counts for pages, tables, figure assets, evidence images and findings;
* a coverage map showing which tracks produced a report and which are absent.

It does not judge the paper. A missing track is reported as a gap, not as
"clean". Run it after the audit tracks and before rendering the report; the
card report picks the manifest up automatically when it sits next to the
Markdown report.

Usage:
    python3 scripts/audit_run_manifest.py output/paper/audit
    python3 scripts/audit_run_manifest.py output/paper/audit --text
    python3 scripts/audit_run_manifest.py output/paper/audit --out manifest.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SOURCE_EXTENSIONS = {".xlsx", ".xlsm", ".csv", ".tsv"}
REPORT_NAMES = {
    "numeric": ("numeric_forensics.json", "chem_numeric.json",
                "nmr_hrms.json"),
    "image": ("image_dup.json", "image_dup_orb.json", "copy_move.json",
              "spectral_segment_dup.json", "spectral_noise.json"),
    "source_data": ("source_data_audit.json",),
    "structure": ("structure_check.json", "pubchem_check.json"),
    "spectrum": ("reference_spectrum_match.json", "spectrum_match.json"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def file_record(path: Path, root: Path) -> dict:
    return {
        "path": display_path(path, root),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def first_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.rglob(pattern))
    return matches[0] if matches else None


def pick_pdf(root: Path) -> Path | None:
    preferred = root / "paper.pdf"
    if preferred.is_file():
        return preferred
    candidates = [path for path in sorted(root.rglob("*.pdf"))
                  if not any(token in path.name.lower()
                             for token in ("audit_report", "report_gate",
                                           "retraction", "supplement"))]
    return candidates[0] if candidates else None


def pick_page_manifest(root: Path) -> Path | None:
    for name in ("native_manifest.json", "mineru_manifest.json"):
        matches = sorted(root.rglob(name))
        if matches:
            return matches[0]
    return None


def load_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def dependency_versions() -> dict:
    versions = {"python": platform.python_version()}
    for module in ("PIL", "numpy", "cv2", "pdfplumber", "pypdfium2",
                   "openpyxl", "scipy"):
        try:
            imported = __import__(module)
            versions[module] = str(getattr(imported, "__version__", "unknown"))
        except Exception:  # noqa: BLE001 - optional dependency
            versions[module] = None
    return versions


def discover_reports(root: Path) -> dict:
    found = {}
    all_json = sorted(root.rglob("*.json"))
    for track, names in REPORT_NAMES.items():
        hits = [path for path in all_json if path.name in names]
        found[track] = [str(path.relative_to(root)) for path in hits]
    return found


def build_manifest(root: Path, workdir: Path | None = None) -> dict:
    data_root = workdir or root
    pdf = pick_pdf(data_root)
    full_md = first_file(data_root, "full.md")
    tables_json = first_file(data_root, "*tables.json")
    figures_json = first_file(data_root, "*figures.json")
    native_manifest = pick_page_manifest(data_root)

    source_files = sorted(
        (path for path in data_root.rglob("*")
         if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS),
        key=str)
    if data_root != root:
        source_files += sorted(
            path for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS)
    image_files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    evidence_images = [path for path in image_files
                       if "findings" in path.relative_to(root).parts or
                       "figures" in path.relative_to(root).parts]
    findings_md = [path for path in root.rglob("*.md")
                   if "findings" in path.relative_to(root).parts]

    page_manifest = load_json(native_manifest)
    tables_data = load_json(tables_json)
    figures_data = load_json(figures_json)
    reports = discover_reports(root)
    coverage = {
        "pdf": pdf is not None,
        "text": full_md is not None,
        "tables": bool(tables_json and tables_data.get("tables")),
        "figures": bool(figures_json and figures_data.get("figures")),
        "evidence_images": bool(evidence_images),
        "source_data": bool(source_files),
        "numeric_report": bool(reports.get("numeric")),
        "image_report": bool(reports.get("image")),
        "source_data_report": bool(reports.get("source_data")),
        "spectrum_report": bool(reports.get("spectrum")),
    }

    inputs = []
    for path in (pdf, full_md, tables_json, figures_json, native_manifest):
        if path is not None:
            inputs.append(file_record(path, root))
    for path in source_files:
        inputs.append(file_record(path, root))

    return {
        "schema_version": "1.0",
        "tool": "audit-run-manifest",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(root),
        "inputs": inputs,
        "counts": {
            "pdf": int(pdf is not None),
            "full_md": int(full_md is not None),
            "source_data_files": len(source_files),
            "image_assets": len(image_files),
            "evidence_images": len(evidence_images),
            "findings": len(findings_md),
            "pages": page_manifest.get("pages"),
            "tables": len(tables_data.get("tables", [])),
            "figures": len(figures_data.get("figures", [])),
        },
        "reports": reports,
        "coverage": coverage,
        "gaps": [name for name, present in coverage.items() if not present],
        "environment": dependency_versions(),
        "notes": [
            "A gap means the run directory has no artefact for that track; it "
            "does not mean the track was checked and found clean.",
            "Compare input SHA-256 values when re-running to confirm the same "
            "paper and supplements were audited.",
        ],
    }


def text_summary(manifest: dict) -> str:
    lines = [f"audit run: {manifest['run_dir']}"]
    for key, value in manifest["counts"].items():
        lines.append(f"  {key}: {value}")
    lines.append("  coverage: " + ", ".join(
        f"{name}={'yes' if present else 'NO'}"
        for name, present in manifest["coverage"].items()))
    if manifest["gaps"]:
        lines.append("  gaps: " + ", ".join(manifest["gaps"]))
    for item in manifest["inputs"][:8]:
        lines.append(f"  input: {item['path']} ({item['bytes']} B, "
                     f"sha256 {item['sha256'][:16]}…)")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory an audit run and write a reproducibility manifest.")
    parser.add_argument("run_dir", help="audit run directory")
    parser.add_argument("--out", help="output JSON (default: RUN/audit_run_manifest.json)")
    parser.add_argument("--workdir", help="parsing work directory containing "
                                          "full.md/tables.json/figures.json")
    parser.add_argument("--text", action="store_true", help="print a summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.run_dir).expanduser().resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    workdir = (Path(args.workdir).expanduser().resolve()
               if args.workdir else None)
    manifest = build_manifest(root, workdir)
    output = (Path(args.out).expanduser() if args.out
              else root / "audit_run_manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    if args.text:
        print(text_summary(manifest))
    else:
        print(json.dumps({"out": str(output), "counts": manifest["counts"],
                          "gaps": manifest["gaps"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
