#!/usr/bin/env python3
"""check_env.py — verify the chemistry audit toolchain before a run.

Checks Python, Python packages, poppler binaries, MinerU environment
variables (presence only — never prints secrets), and optional RDKit.

Usage:
    python3 scripts/check_env.py
    python3 scripts/check_env.py --json

Exit code 0 when all required items are present, 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys


REQUIRED_PY = (3, 8)
REQUIRED_PACKAGES = ("PIL", "numpy")
RECOMMENDED_PACKAGES = ("cv2", "scipy")
OPTIONAL_PACKAGES = ("rdkit", "openpyxl")
REQUIRED_BINARIES = ("pdftoppm", "pdfimages", "pdftotext")


def module_status(name: str) -> dict:
    found = importlib.util.find_spec(name) is not None
    version = None
    if found:
        try:
            mod = __import__(name)
            version = getattr(mod, "__version__", None)
        except Exception:
            pass
    return {"name": name, "found": found, "version": version}


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    checks = {
        "python": {
            "version": ".".join(str(x) for x in sys.version_info[:3]),
            "required": ".".join(str(x) for x in REQUIRED_PY),
            "ok": sys.version_info[:2] >= REQUIRED_PY,
        },
        "packages": {
            "required": [module_status(name) for name in REQUIRED_PACKAGES],
            "recommended": [module_status(name) for name in RECOMMENDED_PACKAGES],
            "optional": [module_status(name) for name in OPTIONAL_PACKAGES],
        },
        "binaries": {
            name: {"path": shutil.which(name), "ok": shutil.which(name) is not None}
            for name in REQUIRED_BINARIES
        },
        "mineru": {
            "base_url_set": bool(os.environ.get("MINERU_BASE_URL")),
            "api_key_set": bool(os.environ.get("MINERU_API_KEY")),
            "cloud_token_set": bool(os.environ.get("MINERU_API_TOKEN")),
        },
        "pubchem_cache": {
            "path": os.path.expanduser("~/.cache/chem-integrity-auditor/pubchem"),
            "exists": os.path.isdir(os.path.expanduser(
                "~/.cache/chem-integrity-auditor/pubchem")),
        },
    }

    required_ok = (
        checks["python"]["ok"]
        and all(item["found"] for item in checks["packages"]["required"])
        and all(item["ok"] for item in checks["binaries"].values())
    )
    report = {"ok": required_ok, "checks": checks}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Python {checks['python']['version']} "
              f"(requires >= {checks['python']['required']}): "
              f"{'OK' if checks['python']['ok'] else 'FAIL'}")
        for group in ("required", "recommended", "optional"):
            for item in checks["packages"][group]:
                state = "OK" if item["found"] else "MISSING"
                print(f"  {group:<11} {item['name']:<8} {state} "
                      f"{item['version'] or ''}".rstrip())
        for name, item in checks["binaries"].items():
            print(f"  poppler     {name:<10} "
                  f"{'OK' if item['ok'] else 'MISSING'} {item['path'] or ''}")
        print("MinerU env: "
              f"MINERU_BASE_URL={'set' if checks['mineru']['base_url_set'] else 'unset'}, "
              f"MINERU_API_KEY={'set' if checks['mineru']['api_key_set'] else 'unset'}, "
              f"MINERU_API_TOKEN={'set' if checks['mineru']['cloud_token_set'] else 'unset'}")
        print("Overall:", "OK" if required_ok else "MISSING REQUIRED ITEMS")
        if not checks["packages"]["recommended"][0]["found"]:
            print("note: OpenCV (cv2) is required for ORB and patch segment matching")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
