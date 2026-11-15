#!/usr/bin/env python3
"""corpus_add.py — register a manually exported reference figure set.

The auditor never scrapes databases or publishers. When a retraction notice
says "first published in ref. 1", the auditor (or the user) exports the
reference figures by hand and registers them here. `corpus_match.py` then
compares a paper's figures/panels against this local corpus.

Layout:

    <corpus>/<key>/meta.json
    <corpus>/<key>/figures/<original-name>.png

Usage:
    python3 corpus_add.py --corpus corpus --key 10.1016/j.matchemphys.2023.127793 \
        --doi 10.1016/j.matchemphys.2023.127793 \
        --title "FeSe2/TiO2 heterostructure ..." \
        --figure ref1-fig1.png --figure ref1-fig2.png \
        --source-url https://doi.org/10.1016/j.matchemphys.2023.127793 \
        --license "publisher copyright; local audit use only"

No network access. No LLM SDK. Python 3.8+.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def safe_key(key: str) -> str:
    key = key.strip().lower()
    key = re.sub(r"[^a-z0-9._-]+", "-", key).strip("-._")
    if not key:
        raise SystemExit("--key is empty after sanitisation")
    return key[:120]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--corpus", required=True, help="corpus root directory")
    ap.add_argument("--key", required=True, help="stable key, e.g. the DOI")
    ap.add_argument("--doi", default="", help="reference DOI")
    ap.add_argument("--title", default="", help="reference title")
    ap.add_argument("--figure", action="append", required=True,
                    help="reference figure file; repeat for each figure")
    ap.add_argument("--source-url", default="", help="where the figure came from")
    ap.add_argument("--license", default="",
                    help="usage terms for the local copy")
    ap.add_argument("--note", default="", help="free-text provenance note")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing entry with the same key")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan without writing")
    args = ap.parse_args()

    root = Path(args.corpus).expanduser().resolve()
    key = safe_key(args.key)
    entry = root / key
    meta_path = entry / "meta.json"
    if meta_path.exists() and not args.force and not args.dry_run:
        sys.stderr.write(f"{meta_path} exists; use --force to replace\n")
        return 2

    figures = []
    for raw in args.figure:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            sys.stderr.write(f"missing figure: {path}\n")
            return 2
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            sys.stderr.write(f"unsupported image suffix: {path}\n")
            return 2
        figures.append(path)
    if not figures:
        sys.stderr.write("no figures supplied\n")
        return 2

    plan = []
    used = set()
    for path in figures:
        name = path.name
        stem, suffix = path.stem, path.suffix.lower()
        i = 2
        while name.lower() in used:
            name = f"{stem}_{i}{suffix}"
            i += 1
        used.add(name.lower())
        plan.append((path, entry / "figures" / name))

    meta = {
        "key": key,
        "doi": args.doi.strip(),
        "title": args.title.strip(),
        "source_url": args.source_url.strip(),
        "license": args.license.strip(),
        "note": args.note.strip(),
        "added": _dt.date.today().isoformat(),
        "figures": [],
    }
    for src, dst in plan:
        meta["figures"].append({
            "file": str(dst.relative_to(entry)),
            "sha256": sha256(src),
            "bytes": src.stat().st_size,
        })

    if args.dry_run:
        print(json.dumps({"entry": str(entry), "meta": meta}, indent=1))
        return 0

    if entry.exists() and args.force:
        shutil.rmtree(entry)
    (entry / "figures").mkdir(parents=True, exist_ok=True)
    for src, dst in plan:
        shutil.copy2(src, dst)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(json.dumps({"entry": str(entry), "figures": len(plan),
                      "key": key}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
