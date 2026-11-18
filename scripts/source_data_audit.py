#!/usr/bin/env python3
"""source_data_audit.py — deterministic screening of paper source-data tables.

This is the workbook-level counterpart to ``numeric_forensics.py``. The latter
reads numbers from the parsed paper Markdown; this script reads the actual
XLSX/CSV/TSV supplementary tables and looks for patterns that independent
measurements rarely produce:

* duplicate rows and duplicate numeric columns;
* constant-difference and constant-ratio column pairs;
* near-perfect column correlations (affine copies);
* arithmetic-progression runs inside one column;
* mixed displayed precision within one column;
* last-digit skew, both after stripping trailing zeros (Mode A) and at the
  column's maximum displayed precision (Mode B);
* repeated trailing-decimal classes across otherwise distinct values.

The output is a set of reviewable *leads*, not a verdict. Every hit records the
file, sheet, column/row, the exact values or support counts, and the benign
explanations the agent must rule out (shared calibrator, derived column,
technical replicate, unit conversion) before grading it in the report.

Usage:
    python3 scripts/source_data_audit.py supplementary/ --out source_audit.json
    python3 scripts/source_data_audit.py data.xlsx --out audit.json --text
    python3 scripts/source_data_audit.py data.csv --out audit.json --header-row 2

Dependencies: stdlib for CSV; ``openpyxl`` for XLSX. No pandas, no R, no LLM.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
CHI2_DF8_P001 = 26.124  # chi-square critical value, df=8, alpha=0.001


def parse_decimal(raw) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"na", "n/a", "nan", "none", "-", "—"}:
        return None
    text = text.replace(",", "").replace("−", "-")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not NUMBER_RE.match(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def decimal_places(raw) -> int:
    text = str(raw).strip().replace(",", "")
    if "e" in text.lower():
        try:
            value = Decimal(text)
        except InvalidOperation:
            return 0
        text = format(value, "f")
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip())


def cell_from_raw(raw: str, row: int) -> dict | None:
    value = parse_decimal(raw)
    if value is None:
        return None
    return {
        "row": row,
        "raw": str(raw).strip(),
        "value": value,
        "dp": decimal_places(raw),
    }


def cell_from_xlsx(cell, row: int) -> dict | None:
    value = cell.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    fmt = str(getattr(cell, "number_format", "") or "")
    match = re.search(r"0\.(0+)", fmt)
    if match:
        dp = len(match.group(1))
        raw = f"{float(value):.{dp}f}"
    else:
        raw = format(value, ".15g")
        dp = decimal_places(raw)
    return {"row": row, "raw": raw, "value": number, "dp": dp}


def read_delimited(path: Path) -> list[list[str]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return [row for row in csv.reader(handle, delimiter=delimiter)]


def _value(raw):
    """Return a display value for a CSV string or an openpyxl cell."""
    return getattr(raw, "value", raw)


def read_xlsx(path: Path) -> list[tuple[str, list[list[object]]]]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency path
        raise RuntimeError(
            "openpyxl is required for .xlsx source data: "
            "python3 -m pip install openpyxl"
        ) from exc
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        return [(sheet.title, [list(row) for row in sheet.iter_rows()])
                for sheet in workbook.worksheets]
    finally:
        workbook.close()


def build_sheet(path: Path, sheet_name: str, rows: list[list[object]],
                header_row: int, min_numeric_ratio: float) -> dict:
    if not rows:
        return {"file": str(path), "sheet": sheet_name, "rows": 0,
                "columns": [], "findings": []}
    header_index = max(0, header_row - 1)
    header = ["" if _value(value) is None else str(_value(value)).strip()
              for value in rows[header_index]]
    while header and header[-1] == "":
        header.pop()
    width = max(len(row) for row in rows[header_index:])
    columns = []
    for col in range(width):
        cells = []
        non_empty = 0
        for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
            if col >= len(row):
                continue
            raw = row[col]
            value = _value(raw)
            if value is None or str(value).strip() == "":
                continue
            non_empty += 1
            cell = (cell_from_xlsx(raw, offset) if not isinstance(raw, str)
                    else cell_from_raw(raw, offset))
            if cell is not None:
                cells.append(cell)
        ratio = len(cells) / non_empty if non_empty else 0.0
        label = header[col] if col < len(header) and header[col] else f"col{col + 1}"
        columns.append({
            "index": col + 1,
            "header": label,
            "non_empty": non_empty,
            "numeric": len(cells),
            "numeric_ratio": round(ratio, 4),
            "selected": len(cells) >= 3 and ratio >= min_numeric_ratio,
            "cells": cells,
        })
    return {"file": str(path), "sheet": sheet_name,
            "header_row": header_index + 1,
            "rows": len(rows) - header_index - 1,
            "columns": columns}


def _numeric_columns(sheet: dict) -> list[dict]:
    return [col for col in sheet["columns"] if col["selected"]]


def _tol(values: list[Decimal], rel: float = 1e-9) -> float:
    scale = max((abs(float(value)) for value in values), default=1.0)
    return max(1e-12, rel * scale)


def _finding(sheet: dict, check: str, severity: str, location: str,
             detail: str, **extra) -> dict:
    finding = {
        "file": sheet["file"],
        "sheet": sheet["sheet"],
        "check": check,
        "severity": severity,
        "location": location,
        "detail": detail,
    }
    finding.update(extra)
    return finding


def check_duplicate_rows(sheet: dict) -> list[dict]:
    cols = _numeric_columns(sheet)
    if len(cols) < 4:
        return []
    by_row = collections.defaultdict(dict)
    for col in cols:
        for cell in col["cells"]:
            by_row[cell["row"]][col["index"]] = cell["value"]
    seen = {}
    findings = []
    for row, values in sorted(by_row.items()):
        if len(values) < 4:
            continue
        key = tuple(sorted(values.items()))
        if key in seen:
            findings.append(_finding(
                sheet, "duplicate_numeric_row", "lead",
                f"rows {seen[key]} and {row}",
                f"{len(values)} numeric cells are identical across two rows",
                rows=[seen[key], row], matched_cells=len(values)))
        else:
            seen[key] = row
    return findings


def check_duplicate_columns(sheet: dict) -> list[dict]:
    cols = _numeric_columns(sheet)
    findings = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a = {c["row"]: c["value"] for c in cols[i]["cells"]}
            b = {c["row"]: c["value"] for c in cols[j]["cells"]}
            common = sorted(set(a) & set(b))
            if len(common) < 4:
                continue
            if len({a[row] for row in common}) <= 1:
                continue
            if all(a[row] == b[row] for row in common):
                findings.append(_finding(
                    sheet, "duplicate_numeric_column", "lead",
                    f"{cols[i]['header']} vs {cols[j]['header']}",
                    f"{len(common)} paired numeric values are identical",
                    columns=[cols[i]["header"], cols[j]["header"]],
                    matched_cells=len(common)))
    return findings


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    if sx2 <= 1e-18 or sy2 <= 1e-18:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sx2 * sy2)


def check_column_pairs(sheet: dict, min_n: int) -> list[dict]:
    cols = _numeric_columns(sheet)
    findings = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a = {c["row"]: c["value"] for c in cols[i]["cells"]}
            b = {c["row"]: c["value"] for c in cols[j]["cells"]}
            common = sorted(set(a) & set(b))
            if len(common) < max(8, min_n):
                continue
            av = [a[row] for row in common]
            bv = [b[row] for row in common]
            diffs = [x - y for x, y in zip(av, bv)]
            tolerance = _tol(av + bv)
            described = False
            if max(float(d) for d in diffs) - min(float(d) for d in diffs) <= tolerance:
                if any(abs(d) > tolerance for d in diffs):
                    described = True
                    findings.append(_finding(
                        sheet, "constant_difference", "lead",
                        f"{cols[i]['header']} − {cols[j]['header']}",
                        f"{len(common)} rows have a constant difference "
                        f"{diffs[0]} (range {min(diffs)}…{max(diffs)})",
                        columns=[cols[i]["header"], cols[j]["header"]],
                        constant=str(diffs[0]), support=f"{len(common)}/{len(common)}"))
            if all(y != 0 for y in bv):
                ratios = [x / y for x, y in zip(av, bv)]
                if max(ratios) - min(ratios) <= Decimal("1e-9"):
                    described = True
                    findings.append(_finding(
                        sheet, "constant_ratio", "lead",
                        f"{cols[i]['header']} / {cols[j]['header']}",
                        f"{len(common)} rows have a constant ratio {ratios[0]}",
                        columns=[cols[i]["header"], cols[j]["header"]],
                        constant=str(ratios[0]), support=f"{len(common)}/{len(common)}"))
            r = pearson([float(x) for x in av], [float(x) for x in bv])
            if not described and r is not None and abs(r) >= 0.99999:
                findings.append(_finding(
                    sheet, "near_perfect_correlation", "lead",
                    f"{cols[i]['header']} vs {cols[j]['header']}",
                    f"Pearson r={r:.10f} over {len(common)} paired rows",
                    columns=[cols[i]["header"], cols[j]["header"]],
                    r=round(r, 10), support=f"{len(common)}/{len(common)}"))
    return findings


def check_arithmetic_runs(sheet: dict, min_run: int = 4) -> list[dict]:
    findings = []
    for col in _numeric_columns(sheet):
        cells = sorted(col["cells"], key=lambda c: c["row"])
        values = [c["value"] for c in cells]
        if len(values) < min_run:
            continue
        diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
        start = 0
        while start < len(diffs):
            step = diffs[start]
            end = start + 1
            while end < len(diffs):
                tol = _tol([step, diffs[end]])
                if abs(diffs[end] - step) > tol:
                    break
                end += 1
            run_values = end - start + 2
            if run_values >= min_run and abs(step) > tol:
                findings.append(_finding(
                    sheet, "arithmetic_progression", "lead",
                    f"{col['header']} rows {cells[start]['row']}–{cells[end]['row']}",
                    f"{run_values} consecutive values form an arithmetic run "
                    f"(step {step})",
                    column=col["header"], step=str(step), run=run_values,
                    values=[c["raw"] for c in cells[start:end + 1]][:12]))
            start = end
    return findings


def check_precision_and_digits(sheet: dict, min_n_a: int = 50,
                               min_n_b: int = 30) -> list[dict]:
    findings = []
    for col in _numeric_columns(sheet):
        cells = col["cells"]
        n = len(cells)
        dp_counts = collections.Counter(cell["dp"] for cell in cells)
        if n >= 20:
            shares = [(dp, count / n) for dp, count in dp_counts.items()]
            mixed = [item for item in shares if item[1] >= 0.10]
            if len(mixed) >= 2:
                findings.append(_finding(
                    sheet, "mixed_precision", "info",
                    col["header"],
                    "column mixes displayed precisions: " +
                    ", ".join(f"{dp}dp={share:.0%}" for dp, share in sorted(mixed)),
                    column=col["header"], precision=dict(sorted(dp_counts.items()))))

        # Mode A: last non-zero fractional digit, trailing zeros stripped.
        digits_a = []
        for cell in cells:
            if cell["dp"] < 1:
                continue
            text = format(abs(cell["value"]), "f")
            if "." not in text:
                continue
            fraction = text.split(".", 1)[1].rstrip("0")
            if fraction:
                digits_a.append(int(fraction[-1]))
        if len(digits_a) >= min_n_a:
            counts = collections.Counter(digits_a)
            expected = len(digits_a) / 9
            chi2 = sum((counts.get(d, 0) - expected) ** 2 / expected
                       for d in range(1, 10))
            dominant, count = counts.most_common(1)[0]
            if count / len(digits_a) >= 0.20 and chi2 >= CHI2_DF8_P001:
                findings.append(_finding(
                    sheet, "last_digit_mode_a", "lead",
                    col["header"],
                    f"last non-zero digit {dominant} appears {count}/{len(digits_a)} "
                    f"({count / len(digits_a):.1%}); chi2={chi2:.1f} (df=8)",
                    column=col["header"], digit=dominant,
                    count=count, n=len(digits_a), chi2=round(chi2, 2)))

        # Mode B: last digit at the column's maximum displayed precision.
        max_dp = max((cell["dp"] for cell in cells), default=0)
        if max_dp >= 2 and n >= min_n_b:
            coarse = sum(1 for cell in cells if cell["dp"] < max_dp)
            digits_b = [int(format(cell["value"], f".{max_dp}f")[-1])
                        for cell in cells]
            counts_b = collections.Counter(digits_b)
            zero_share = counts_b.get(0, 0) / n
            top_digit, top_count = counts_b.most_common(1)[0]
            if coarse / n >= 0.50 or zero_share >= 0.50 or top_count / n >= 0.35:
                findings.append(_finding(
                    sheet, "last_digit_mode_b", "lead",
                    col["header"],
                    f"at {max_dp}dp: digit 0={zero_share:.0%}, "
                    f"top digit {top_digit}={top_count / n:.0%}, "
                    f"coarser-than-max={coarse / n:.0%} (n={n})",
                    column=col["header"], max_dp=max_dp, n=n,
                    zero_share=round(zero_share, 4),
                    top_digit=top_digit, top_share=round(top_count / n, 4),
                    coarse_share=round(coarse / n, 4)))
    return findings


def check_decimal_tails(sheet: dict, digits_options=(2, 3),
                        min_class: int = 8, min_distinct: int = 6) -> list[dict]:
    findings = []
    for col in _numeric_columns(sheet):
        for digits in digits_options:
            groups = collections.defaultdict(list)
            for cell in col["cells"]:
                if cell["dp"] < digits:
                    continue
                tail = format(abs(cell["value"]), f".{digits}f")[-digits:]
                groups[tail].append(cell)
            for tail, members in sorted(
                    groups.items(), key=lambda item: -len(item[1])):
                distinct = len({cell["value"] for cell in members})
                if len(members) >= min_class and distinct >= min_distinct:
                    findings.append(_finding(
                        sheet, f"decimal_tail_{digits}dp", "lead",
                        f"{col['header']} tail .{tail}",
                        f"{len(members)} values spanning {distinct} distinct "
                        f"numbers share the last {digits} decimals",
                        column=col["header"], tail=tail,
                        count=len(members), distinct=distinct,
                        examples=[cell["raw"] for cell in members[:8]]))
    return findings


def audit_sheet(path: Path, sheet_name: str, rows: list[list[object]],
                header_row: int, min_numeric_ratio: float,
                min_n: int) -> tuple[dict, list[dict]]:
    sheet = build_sheet(path, sheet_name, rows, header_row, min_numeric_ratio)
    findings = []
    findings += check_duplicate_rows(sheet)
    findings += check_duplicate_columns(sheet)
    findings += check_column_pairs(sheet, min_n)
    findings += check_arithmetic_runs(sheet)
    findings += check_precision_and_digits(sheet)
    findings += check_decimal_tails(sheet)
    for col in sheet["columns"]:
        col.pop("cells", None)
    sheet["findings"] = findings
    return sheet, findings


def discover(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(
                child for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".xlsx", ".csv", ".tsv"}))
        elif path.is_file():
            files.append(path)
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Screen XLSX/CSV/TSV source-data tables for numeric "
                    "patterns that warrant manual review.")
    parser.add_argument("paths", nargs="+", help="workbook, csv/tsv, or directory")
    parser.add_argument("--out", required=True, help="JSON output path")
    parser.add_argument("--text", action="store_true", help="print a text summary")
    parser.add_argument("--header-row", type=int, default=1,
                        help="1-based header row (default 1)")
    parser.add_argument("--min-numeric-ratio", type=float, default=0.80,
                        help="treat a column as numeric at this ratio (default 0.80)")
    parser.add_argument("--min-n", type=int, default=8,
                        help="minimum paired rows for column-pair checks (default 8)")
    parser.add_argument("--max-findings", type=int, default=300,
                        help="cap the JSON finding list (default 300)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = discover([Path(item).expanduser() for item in args.paths])
    if not files:
        print("no .xlsx/.csv/.tsv files found", file=sys.stderr)
        return 2

    sheets = []
    all_findings = []
    try:
        for path in files:
            if path.suffix.lower() == ".xlsx":
                for sheet_name, rows in read_xlsx(path):
                    sheet, findings = audit_sheet(
                        path, sheet_name, rows, args.header_row,
                        args.min_numeric_ratio, args.min_n)
                    sheets.append(sheet)
                    all_findings.extend(findings)
            else:
                rows = read_delimited(path)
                sheet, findings = audit_sheet(
                    path, path.stem, rows, args.header_row,
                    args.min_numeric_ratio, args.min_n)
                sheets.append(sheet)
                all_findings.extend(findings)
    except Exception as exc:  # noqa: BLE001
        print(f"source-data audit failed: {exc}", file=sys.stderr)
        return 1

    all_findings = all_findings[:args.max_findings]
    summary = collections.Counter(finding["check"] for finding in all_findings)
    payload = {
        "tool": "source-data-audit",
        "inputs": [str(path) for path in files],
        "sheets": sheets,
        "summary": dict(sorted(summary.items())),
        "findings": all_findings,
        "notes": [
            "Leads only. A constant ratio can be a documented unit conversion or "
            "normalization; identical rows can be technical replicates.",
            "Confirm the column headers, sub-table layout and benign explanations "
            "before assigning a report level.",
        ],
    }
    output = Path(args.out).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    if args.text:
        print(f"source-data audit: {len(files)} file(s), "
              f"{len(sheets)} sheet(s), {len(all_findings)} lead(s)")
        for finding in all_findings:
            print(f"  [{finding['check']}] {finding['location']}: "
                  f"{finding['detail']}")
    else:
        print(json.dumps({"out": str(output), "sheets": len(sheets),
                          "findings": len(all_findings),
                          "summary": dict(sorted(summary.items()))},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
