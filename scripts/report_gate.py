#!/usr/bin/env python3
"""report_gate.py — executable quality gate for a Chinese audit report.

Checks the contract that a human reviewer would otherwise have to remember:

* required sections 1–7;
* every Level ≥ 2 finding has 位置 / 技术 / 观察 / 良性解释 / 压力测试;
* a locator that resolves to a real artifact (path, figure+panel, table+cell);
* no unresolved placeholders (`<title>`, `<N>`, …);
* no verdict words (“造假/fraud/…”) outside a quoted notice or an explicit
  “not writing fraud” caveat;
* all three tracks carry a status;
* the section-7 checklist has no unchecked boxes.

Usage:
    python3 report_gate.py audit_report.md --run-dir output/.../workdir
    python3 report_gate.py audit_report.md --json gate.json --strict

Exit 0 = pass, 1 = errors (or warnings with --strict), 2 = unreadable input.
No LLM SDK. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    "## 1. 论文信息",
    "## 2. 审计范围与方法",
    "## 3. 发现",
    "## 4. 各线小结",
    "## 5. 需作者提供的原始数据",
    "## 6. 局限性",
    "## 7. 质量门自检",
]
FINDING_FIELDS = ["位置", "技术", "观察", "良性解释", "压力测试"]
TRACKS = ["数值线", "图像线", "逻辑线"]
STATUS_WORDS = ["clean", "有发现", "部分不适用", "不适用"]
PATH_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:json|png|jpg|jpeg|md|csv|txt|xlsx?|pdf)")
PLACEHOLDER_RE = re.compile(r"<(?!https?://|mailto:)[A-Za-z][^<>\n]{0,60}>")
LEVEL_RE = re.compile(r"^###\s+Level\s+([1-4])\b", re.I | re.M)
FORBIDDEN = ["造假", "伪造", "篡改", "fraud", "fabricat"]
BENIGN_CONTEXT = ["通知", "原文", "retract", "不写", "不是", "未", "不能", "不应"]


def split_findings(text: str):
    """Return [(level, title, block, line_no)] for each #### block."""
    lines = text.splitlines()
    out = []
    level = None
    i = 0
    while i < len(lines):
        m = LEVEL_RE.match(lines[i].strip())
        if m:
            level = int(m.group(1))
        if lines[i].startswith("#### ") and level is not None:
            title = lines[i][5:].strip()
            start = i
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("### ", "#### ", "## ")):
                j += 1
            out.append((level, title, "\n".join(lines[start:j]), start + 1))
            i = j
        else:
            i += 1
    return out


def resolve_path(token: str, roots):
    token = token.strip("`'\"()[]<>，。；;:")
    candidates = [token, token.lstrip("./")]
    for root in roots:
        for cand in candidates:
            path = (root / cand).resolve()
            if path.exists():
                return path
    return None


def has_structured_locator(block: str) -> bool:
    low = block.lower()
    figure = ("fig" in low or "图" in block) and ("panel" in low or "子图" in block)
    table = ("table" in low or "表" in block) and (
        "row" in low or "col" in low or "行" in block or "列" in block)
    return figure or table


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("report", help="markdown audit report")
    ap.add_argument("--run-dir", default="",
                    help="run/workdir root for resolving evidence paths")
    ap.add_argument("--json", metavar="PATH", help="write gate JSON")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as failures")
    args = ap.parse_args()

    path = Path(args.report).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        sys.stderr.write(f"cannot read report: {exc}\n")
        return 2
    roots = [path.parent]
    if args.run_dir:
        roots.append(Path(args.run_dir).expanduser().resolve())

    errors = []
    warnings = []

    def err(msg, line=0):
        errors.append({"line": line, "message": msg})

    def warn(msg, line=0):
        warnings.append({"line": line, "message": msg})

    for section in REQUIRED_SECTIONS:
        if section not in text:
            err(f"missing section: {section}")

    for i, line in enumerate(text.splitlines(), 1):
        if PLACEHOLDER_RE.search(line):
            err(f"unresolved placeholder: {PLACEHOLDER_RE.search(line).group(0)}", i)
        for word in FORBIDDEN:
            if word in line and not any(ctx in line for ctx in BENIGN_CONTEXT):
                err(f"verdict word '{word}' outside a quoted notice/caveat", i)

    findings = split_findings(text)
    levels = [f[0] for f in findings]
    if levels != sorted(levels, reverse=True):
        warn("findings are not ordered from Level 4 to Level 1")
    for level, title, block, line in findings:
        for field in FINDING_FIELDS:
            if field not in block:
                err(f"{title}: missing field '{field}'", line)
        if level >= 2:
            paths = PATH_RE.findall(block)
            resolved = [p for p in paths if resolve_path(p, roots)]
            if paths and not resolved:
                err(f"{title}: no evidence path resolves", line)
            if not paths and not has_structured_locator(block):
                err(f"{title}: Level {level} has no path or figure/table locator",
                    line)
            if not paths:
                warn(f"{title}: locator is structured text only; add a file path",
                     line)

    for track in TRACKS:
        if track not in text:
            err(f"track summary missing: {track}")
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if track in line and "|" in line:
                if not any(word in line for word in STATUS_WORDS):
                    err(f"{track}: row has no clean/有发现/不适用 status", line_no)
                break

    gate_start = text.find("## 7. 质量门自检")
    if gate_start >= 0:
        gate = text[gate_start:]
        unchecked = [i for i, line in enumerate(gate.splitlines(), 1)
                     if re.match(r"\s*-\s*\[\s\]", line)]
        if unchecked:
            err(f"quality-gate checklist has {len(unchecked)} unchecked item(s)")
        checked = len(re.findall(r"-\s*\[[xX]\]", gate))
        if checked < 5:
            warn(f"only {checked} checked quality-gate items")

    result = {
        "report": str(path),
        "run_dir": args.run_dir,
        "pass": not errors and not (args.strict and warnings),
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "sections": sum(1 for s in REQUIRED_SECTIONS if s in text),
            "findings": len(findings),
            "levels": {str(n): levels.count(n) for n in (1, 2, 3, 4)},
        },
    }
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
    print(json.dumps({"pass": result["pass"], "errors": len(errors),
                      "warnings": len(warnings)}, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
