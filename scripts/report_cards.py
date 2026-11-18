#!/usr/bin/env python3
"""Parse the Chinese audit report into finding cards for HTML/PDF rendering.

The report template is intentionally human-readable Markdown. This module gives
the renderer a small structured view of it without asking the agent to emit a
second JSON file:

* paper metadata and the one-paragraph conclusion;
* one entry per ``#### <id>`` finding, with its Level and labelled fields;
* the evidence images and their captions;
* the remaining sections (track summary, author-data asks, limitations,
  self-check) as Markdown.

It is deliberately tolerant: an older report that does not follow every label
still renders, and the classic Markdown renderer remains available.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

LEVEL_RE = re.compile(r"^###\s+Level\s*([1-4])\b", re.I)
FINDING_RE = re.compile(r"^####\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*\s*[：:]\s*(.*)$")
IMAGE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$")
CAPTION_RE = re.compile(r"^\s*\*([^*].*?)\*\s*$")
RISK_RE = re.compile(r"总体风险定级[：:]\s*\**\s*([A-Za-z/]+)", re.I)
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.*)$")


def _strip_md(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _table_rows(lines):
    rows = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def _parse_info(lines):
    info = {}
    for row in _table_rows(lines):
        if len(row) >= 2:
            key = _strip_md(row[0])
            value = _strip_md(row[1])
            if key and key not in ("项", "字段"):
                info[key] = value
    return info


def _parse_images(block_lines):
    """Return (image list, lines with image blocks removed)."""
    images = []
    kept = []
    i = 0
    while i < len(block_lines):
        line = block_lines[i]
        m = IMAGE_RE.match(line)
        if not m:
            kept.append(line)
            i += 1
            continue
        alt, url = m.group(1), m.group(2).strip()
        caption = ""
        if i + 1 < len(block_lines):
            cm = CAPTION_RE.match(block_lines[i + 1])
            if cm:
                caption = _strip_md(cm.group(1))
                i += 1
        images.append({"alt": alt, "path": url, "caption": caption})
        i += 1
    return images, kept


def _parse_fields(block_lines):
    """Parse ``- **位置**：...`` fields, preserving nested tables/lists."""
    fields = []
    current = None
    for line in block_lines:
        m = FIELD_RE.match(line)
        if m:
            if current:
                fields.append(current)
            current = {"label": _strip_md(m.group(1)), "lines": [m.group(2)]}
        elif current is not None:
            current["lines"].append(line)
    if current:
        fields.append(current)
    for field in fields:
        field["text"] = "\n".join(field.pop("lines")).strip()
    return fields


def parse_report(text: str):
    lines = text.splitlines()
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = _strip_md(line[2:])
            break

    # Split into numbered sections.
    sections = {}
    current_no = None
    current = []
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            if current_no is not None:
                sections[current_no] = current
            current_no = int(m.group(1))
            current = []
        elif current_no is not None:
            current.append(line)
    if current_no is not None:
        sections[current_no] = current

    sec1 = sections.get(1, [])
    info = _parse_info(sec1)
    risk = ""
    for line in sec1:
        rm = RISK_RE.search(line)
        if rm:
            risk = rm.group(1)
            break
    summary_lines = []
    for line in sec1:
        if RISK_RE.search(line):
            continue
        if line.strip().startswith("|"):
            continue
        if line.strip():
            summary_lines.append(line.strip())
    summary = " ".join(summary_lines).strip()

    findings = []
    level = None
    block = None
    for line in sections.get(3, []):
        lm = LEVEL_RE.match(line.strip())
        if lm:
            # Finish the previous finding before changing Level; otherwise its
            # last block is attributed to the next Level heading.
            if block:
                findings.append(_finish_finding(block, level, len(findings) + 1))
                block = None
            level = int(lm.group(1))
            continue
        fm = FINDING_RE.match(line.strip())
        if fm:
            if block:
                findings.append(_finish_finding(block, level, len(findings) + 1))
            block = {"id": _strip_md(fm.group(1)), "lines": []}
        elif block is not None:
            block["lines"].append(line)
    if block:
        findings.append(_finish_finding(block, level, len(findings) + 1))

    return {
        "title": info.get("标题") or title or "化学论文科研诚信审计报告",
        "doc_title": title or "化学论文科研诚信审计报告",
        "info": info,
        "risk": risk,
        "summary": summary,
        "findings": findings,
        "sections": {k: "\n".join(v).strip()
                     for k, v in sections.items() if k >= 2},
        "raw": text,
    }


def _finish_finding(block, level, index):
    images, kept = _parse_images(block["lines"])
    fields = _parse_fields(kept)
    location = ""
    for field in fields:
        if "位置" in field["label"]:
            location = _strip_md(field["text"].splitlines()[0]
                                 if field["text"] else "")
            break
    return {
        "index": index,
        "id": block.get("id", f"finding-{index}"),
        "level": level or 0,
        "fields": fields,
        "images": images,
        "location": location,
    }


def render_cards(report: dict, base: Path, render_markdown, inline,
                 image_data_uri=None) -> str:
    """Render the parsed report as a paper header + index + finding cards."""
    info = report["info"]
    risk = report["risk"] or "—"
    findings = report["findings"]
    levels = [f["level"] for f in findings if f["level"]]
    level_counts = {n: levels.count(n) for n in sorted(set(levels), reverse=True)}

    badges = [f'<span class="badge risk risk-{html.escape(risk.lower())}">'
              f'总体风险 {html.escape(risk)}</span>']
    for n in sorted(level_counts, reverse=True):
        badges.append(f'<span class="badge level level-{n}">'
                      f'Level {n} × {level_counts[n]}</span>')
    badges.append(f'<span class="badge neutral">{len(findings)} 条发现</span>')

    meta_bits = []
    for key in ("期刊 / 年份", "DOI", "论文状态", "审计日期"):
        if info.get(key):
            meta_bits.append(
                f'<span><b>{html.escape(key)}</b> {html.escape(info[key])}</span>')
    meta = "".join(meta_bits)

    hero = (
        '<header class="hero">'
        '<div class="eyebrow">化学论文科研诚信审计 · 证据报告</div>'
        f'<h1>{html.escape(report["title"])}</h1>'
        f'<div class="badges">{"".join(badges)}</div>'
        f'<div class="meta">{meta}</div>'
        f'<div class="conclusion">{render_markdown(report["summary"], base)}</div>'
        '<div class="notice">Signal, not verdict：本报告陈述可复核的数据模式与'
        '证据位置，不判断作者意图；最终裁定需要原始数据、作者说明与期刊/机构复核。</div>'
        '</header>'
    )

    # Findings index: location / Level / evidence count.
    index_rows = []
    for f in findings:
        index_rows.append(
            "<tr>"
            f'<td class="num">{f["index"]}</td>'
            f'<td class="id">{html.escape(f["id"])}</td>'
            f'<td><span class="pill level-{f["level"]}">L{f["level"] or "—"}</span></td>'
            f'<td>{html.escape(f["location"])}</td>'
            f'<td class="num">{len(f["images"])}</td>'
            "</tr>")
    index = (
        '<section class="panel index-panel">'
        '<h2>发现索引</h2>'
        '<table class="findings-index"><thead><tr>'
        '<th>#</th><th>编号</th><th>Level</th><th>位置</th><th>证据图</th>'
        f'</tr></thead><tbody>{"".join(index_rows)}</tbody></table>'
        '</section>'
    ) if findings else ""

    cards = []
    for f in findings:
        field_html = []
        for field in f["fields"]:
            label = field["label"]
            if label in ("证据图", "Evidence"):
                continue
            value = render_markdown(field["text"], base) if field["text"].strip() else ""
            # The first two fields are metadata, not prose; keep them compact.
            if label in ("位置", "技术"):
                field_html.append(
                    f'<div class="kv"><div class="k">{html.escape(label)}</div>'
                    f'<div class="v">{value or "—"}</div></div>')
            else:
                field_html.append(
                    f'<div class="field"><div class="k">{html.escape(label)}</div>'
                    f'{value}</div>')

        figures = []
        for image in f["images"]:
            candidate = (base / image["path"]).resolve()
            src = image["path"]
            if candidate.is_file() and image_data_uri is not None:
                try:
                    src = image_data_uri(candidate)
                except Exception:
                    src = image["path"]
            cls = "ev-source" if ("原文" in image["alt"] or "原图" in image["alt"]) else "ev-crop"
            cap = (f'<figcaption>{inline(image["caption"], base)}</figcaption>'
                   if image["caption"] else "")
            figures.append(
                f'<figure class="{cls}"><img alt="{html.escape(image["alt"], quote=True)}" '
                f'src="{html.escape(src, quote=True)}">{cap}</figure>')
        evidence = (
            f'<div class="evidence"><div class="evidence-title">证据图'
            f'<span>{len(figures)} 幅</span></div>'
            f'<div class="evidence-grid">{"".join(figures)}</div></div>'
            if figures else
            '<div class="evidence empty">本条没有图像证据；见下方表格或说明。</div>'
        )

        cards.append(
            f'<section class="finding-card level-{f["level"]}'
            f'{(" first-finding" if f["index"] == 1 else "")}" '
            f'id="finding-{f["index"]}">'
            '<div class="finding-head">'
            f'<div class="finding-no">发现 {f["index"]}</div>'
            f'<h2>{html.escape(f["id"])}</h2>'
            f'<div class="badges"><span class="badge level level-{f["level"]}">'
            f'Level {f["level"] or "—"}</span></div>'
            '</div>'
            f'<div class="finding-body">{"".join(field_html)}</div>'
            f'{evidence}'
            '</section>'
        )

    # Remaining sections: keep their original Markdown but style them as panels.
    panel_titles = {
        2: "审计范围与方法",
        4: "各线小结",
        5: "需作者提供的原始数据",
        6: "局限性",
        7: "质量门自检",
    }
    panels = []
    for no in (2, 4, 5, 6, 7):
        body = report["sections"].get(no, "").strip()
        if not body:
            continue
        panels.append(
            f'<section class="panel section-{no}">'
            f'<h2>{panel_titles[no]}</h2>{render_markdown(body, base)}</section>')

    return hero + index + "".join(cards) + "".join(panels)


CARDS_CSS = r"""
:root {
  --ink:#172033; --muted:#5b677a; --line:#d8dee8; --paper:#ffffff;
  --soft:#f6f8fb; --accent:#1f4e8c; --l1:#64748b; --l2:#b45309;
  --l3:#c2410c; --l4:#b42318;
}
.hero { border-left: 4.2pt solid var(--accent); padding: 5mm 0 5mm 6mm;
        margin: 0 0 6mm; background: linear-gradient(90deg,#f5f8fd,#fff 70%); }
.eyebrow { color: var(--accent); font-size: 8.5pt; font-weight: 700;
           letter-spacing: .08em; text-transform: uppercase; margin-bottom: 2mm; }
.hero h1 { font-size: 20pt; line-height: 1.32; margin: 0 0 4mm;
           border: 0; padding: 0; }
.badges { display: flex; flex-wrap: wrap; gap: 1.6mm; margin: 2mm 0; }
.badge { display: inline-block; font-size: 8pt; font-weight: 700;
         padding: .7mm 2.2mm; border-radius: 10mm; border: .6pt solid var(--line);
         background: #fff; color: var(--ink); }
.badge.risk-high, .badge.risk-critical { color:#b42318; background:#fef3f2; border-color:#fecdca; }
.badge.risk-medium { color:#b45309; background:#fffaeb; border-color:#fedf89; }
.badge.risk-low { color:#067647; background:#ecfdf3; border-color:#abefc6; }
.badge.level-4 { color:#b42318; background:#fef3f2; border-color:#fecdca; }
.badge.level-3 { color:#c2410c; background:#fff7ed; border-color:#fed7aa; }
.badge.level-2 { color:#b45309; background:#fffaeb; border-color:#fedf89; }
.badge.level-1 { color:#475467; background:#f2f4f7; border-color:#d0d5dd; }
.badge.neutral { color: var(--muted); background: var(--soft); }
.meta { display:flex; flex-wrap:wrap; gap:2mm 6mm; color:var(--muted);
        font-size:8.6pt; margin: 2mm 0 3mm; }
.meta b { color: var(--ink); font-weight: 700; }
.conclusion { font-size: 10.4pt; line-height: 1.7; }
.conclusion p { margin: 2mm 0; }
.notice { margin-top: 4mm; padding: 2.6mm 3.4mm; border-radius: 2mm;
          background:#f8fafc; border:.6pt solid var(--line);
          color:var(--muted); font-size:8.5pt; line-height:1.55; }
.panel { margin: 5mm 0 0; padding: 4mm 5mm; border: .7pt solid var(--line);
         border-radius: 2.5mm; background: var(--paper); }
.panel h2 { border: 0; padding: 0; margin: 0 0 3mm; font-size: 13pt;
            break-before: auto; break-after: avoid; }
.index-panel { margin-top: 2mm; }
table.findings-index { margin: 1mm 0 0; font-size: 8.4pt; }
table.findings-index th { background: #eef2f7; }
table.findings-index td.num, table.findings-index th:first-child,
table.findings-index th:last-child { width: 9mm; text-align: center; }
table.findings-index td.id { font-weight: 700; white-space: nowrap; }
.pill { display:inline-block; min-width:8mm; text-align:center; font-size:7.6pt;
        font-weight:700; padding:.3mm 1.2mm; border-radius:1mm; }
.pill.level-4 { background:#fef3f2; color:#b42318; }
.pill.level-3 { background:#fff7ed; color:#c2410c; }
.pill.level-2 { background:#fffaeb; color:#b45309; }
.pill.level-1 { background:#f2f4f7; color:#475467; }
.finding-card { margin: 6mm 0 0; border: .7pt solid var(--line);
                border-top: 3.2pt solid var(--l2); border-radius: 2.5mm;
                background: var(--paper); overflow: hidden; }
.finding-card.level-4 { border-top-color: var(--l4); }
.finding-card.level-3 { border-top-color: var(--l3); }
.finding-card.level-2 { border-top-color: var(--l2); }
.finding-card.level-1 { border-top-color: var(--l1); }
.finding-card.first-finding { break-before: page; }
.finding-head { display:flex; align-items:center; gap:3mm; flex-wrap:wrap;
                padding: 3.4mm 4.5mm 2.6mm; background: var(--soft);
                border-bottom: .6pt solid var(--line); }
.finding-no { color: var(--muted); font-size: 8.2pt; font-weight: 700;
              letter-spacing:.04em; }
.finding-head h2 { margin:0; border:0; padding:0; font-size:13pt;
                   break-before:auto; break-after:avoid; flex:1; min-width:60mm; }
.finding-body { padding: 1mm 4.5mm 3mm; }
.finding-body .kv { display:grid; grid-template-columns: 22mm 1fr; gap:1.2mm 3mm;
                    padding: 2mm 0; border-bottom: .5pt dashed #e5e9f0; }
.finding-body .kv:last-child { border-bottom:0; }
.finding-body .k { color: var(--muted); font-size:8.4pt; font-weight:700; }
.finding-body .v { font-size:9.2pt; }
.finding-body .field { padding: 2.4mm 0; border-bottom: .5pt dashed #e5e9f0; }
.finding-body .field:last-child { border-bottom:0; }
.finding-body .field .k { color: var(--accent); font-size:8.6pt; font-weight:700;
                          margin-bottom:1mm; }
.finding-body .field p { margin: 1.2mm 0; }
.finding-body .field ul, .finding-body .field ol { margin:1.2mm 0; }
.finding-body .field table { margin:1.6mm 0; }
.evidence { margin: 1mm 4.5mm 4.5mm; padding-top: 2.6mm;
            border-top: .7pt solid var(--line); }
.evidence-title { font-size: 8.8pt; font-weight: 700; color: var(--ink);
                  margin-bottom: 2mm; break-after: avoid; }
.evidence-title span { color: var(--muted); font-weight: 400; margin-left: 2mm; }
.evidence-grid { display:grid; grid-template-columns: 1fr 1fr; gap: 3mm;
                 break-inside: auto; }
.evidence-grid figure { margin:0; break-inside: avoid; }
.evidence-grid figure img { max-width:100%; max-height: 62mm; width:auto;
                            border:.6pt solid #d8d8d8; border-radius:1mm; }
.evidence-grid figure.ev-source img { max-height: 50mm; }
.evidence-grid figure.ev-crop img { max-height: 64mm; }
.evidence-grid figcaption { font-size:7.8pt; text-align:left; }
.evidence.empty { color:var(--muted); font-size:8.4pt; padding:2mm 0; }
.section-5 ol, .section-6 ul, .section-7 ul { margin-top: 1mm; }
.section-7 ul { list-style: none; padding-left: 0; }
.section-7 li { font-size: 8.6pt; }
@media print {
  .hero { break-inside: avoid; }
  .finding-card { break-inside: auto; }
  .finding-head { break-after: avoid; }
  .evidence-grid { break-inside: auto; }
  .evidence-grid figure { break-inside: avoid; }
}
"""
