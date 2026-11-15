#!/usr/bin/env python3
"""Fetch a PMC article as audit input: fulltext XML → full.md + figure JPGs.

Use this when the publisher site is unreachable (Cloudflare/paywall) but the
article is in PubMed Central. PMC's eutils endpoint and the figure-file
(``instance/<id>/bin/<file>.jpg``) endpoint are reachable from most networks
where the publisher and even the PMC PDF endpoint are not (the PDF endpoint
sits behind a JS proof-of-work gate; the figure files usually do not).

What it does:
1. GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<n>
   → NLM article XML (structured <table>, <fig>, <sec> — better table
   fidelity than MinerU for the numeric track).
2. Convert the XML to ``full.md`` in MinerU-compatible shape: markdown text
   with real HTML ``<table>`` blocks, ``[[FIG:<id> <label> <file> <caption>]]``
   anchors so the technique inventory and the image track can be built.
3. Read every ``<graphic xlink:href="...">`` filename and download each
   figure from https://pmc.ncbi.nlm.nih.gov/articles/instance/<n>/bin/<file>
   with pacing + retry (a 200 HTML response is the PoW/captcha page, not an
   image — detected and retried).

SI PDFs are NOT fetchable this way (they are PoW-gated); record them as
blocked in the manifest.

Stdlib only. Python 3.8+.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def elem_text(el) -> str:
    """All text under an element, inline markup flattened."""
    if el is None:
        return ""
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(elem_text(child))
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def inline_text(el) -> str:
    """Paragraph-level text: keep <i>/<b>/<sub> content, drop refs' URLs."""
    out = []
    def walk(node):
        if node.text:
            out.append(node.text)
        for child in node:
            t = strip_ns(child.tag)
            if t == "ext-link":
                out.append(elem_text(child) or child.get("xlink:href") or "")
            elif t in ("ref", "mixed-citation"):
                out.append(f"[{elem_text(child)}]")
            else:
                walk(child)
            if child.tail:
                out.append(child.tail)
    walk(el)
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def table_to_html(table_el) -> str:
    rows = table_el.findall(".//tr")
    out = ["<table>"]
    for row in rows:
        cells = [child for child in row if strip_ns(child.tag) in ("td", "th")]
        out.append("<tr>" + "".join(
            f"<td>{inline_text(c)}</td>" for c in cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def xml_to_markdown(root, pmcid: str) -> str:
    md = []
    title = elem_text(root.find(".//article-title"))
    if title:
        md += [f"# {title}", ""]
    md.append(f"<!-- source: PMC {pmcid} (NLM efetch XML) -->")
    md.append("")
    abs_el = root.find(".//abstract")
    if abs_el is not None:
        md += ["## Abstract", ""]
        for p in abs_el.findall(".//p"):
            t = inline_text(p)
            if t:
                md += [t, ""]
    body = root.find(".//body")
    if body is None:
        body = root

    # walk sections recursively for headings
    def walk_sec(sec, depth):
        nonlocal md
        st = sec.find("sec-title")
        if st is not None:
            md.append("#" * min(depth + 2, 5) + " " + elem_text(st))
            md.append("")
        for child in sec:
            ct = strip_ns(child.tag)
            if ct == "p":
                txt = inline_text(child)
                if txt:
                    md += [txt, ""]
            elif ct == "table-wrap":
                tw_id = child.get("id", "")
                label = elem_text(child.find("label"))
                cap = elem_text(child.find("caption"))
                tbl = child.find(".//table")
                if label or cap:
                    md.append(f"{label}. {cap}".strip() + f"  <!-- table-wrap id={tw_id} -->")
                    md.append("")
                if tbl is not None:
                    md.append(table_to_html(tbl))
                    md.append("")
            elif ct == "fig":
                fig_id = child.get("id", "")
                label = elem_text(child.find("label"))
                cap = elem_text(child.find("caption"))
                XH = "{http://www.w3.org/1999/xlink}href"
                hrefs = [(g.get(XH) or g.get("xlink:href"))
                         for g in child.findall(".//graphic")]
                hrefs = [h for h in hrefs if h]
                files = ", ".join(hrefs)
                md.append(f"[[FIG:{fig_id} | {label} | {files} | {cap}]]")
                md.append("")
            elif ct == "disp-quote":
                txt = inline_text(child)
                if txt:
                    md += [f"> {txt}", ""]
            elif ct == "list":
                for item in child:
                    txt = inline_text(item)
                    if txt:
                        md.append(f"- {txt}")
                md.append("")
            elif ct == "sec":
                walk_sec(child, depth + 1)
    # top-level non-sec children of body
    for child in body:
        ct = strip_ns(child.tag)
        if ct == "sec":
            walk_sec(child, 1)
        elif ct == "p":
            txt = inline_text(child)
            if txt:
                md += [txt, ""]
    return "\n".join(md)


def fetch_url(url: str, dest: Path, binary: bool, tries: int = 3,
              min_gap: float = 4.0) -> bool:
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urlopen(req, timeout=40) as resp:
                data = resp.read()
            if binary:
                head = data[:200]
                is_html = head.lstrip()[:1] in (b"<", b"\xef\xbb\xbf<") or b"<html" in head.lower()
                if is_html:
                    last = "PoW/HTML instead of binary"
                    time.sleep(min_gap * attempt + (attempt % 3))
                    continue
                dest.write_bytes(data)
                return True
            else:
                dest.write_bytes(data)
                return True
        except Exception as exc:
            last = str(exc)
            time.sleep(min_gap * attempt)
    print(f"  download failed after {tries} tries: {url} ({last})", file=sys.stderr)
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch a PMC article as audit input.")
    p.add_argument("--pmcid", required=True, help="e.g. PMC10835344")
    p.add_argument("--output", required=True, help="Run workdir ($RUN)")
    args = p.parse_args()

    pmcid = args.pmcid.upper()
    num = pmcid.replace("PMC", "")
    run = Path(args.output)
    run.mkdir(parents=True, exist_ok=True)
    fig_dir = run / "figures_pmc"
    fig_dir.mkdir(exist_ok=True)

    xml_path = run / "fulltext.xml"
    if not xml_path.exists():
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={num}"
        print(f"fetching XML: {url}", flush=True)
        if not fetch_url(url, xml_path, binary=False):
            return 1
    tree = ET.parse(xml_path)
    root = tree.getroot()

    md_text = xml_to_markdown(root, pmcid)
    (run / "full.md").write_text(md_text, encoding="utf-8")
    print(f"full.md: {len(md_text)} chars")

    # figure filenames from <graphic xlink:href>. The xlink namespace is
    # declared locally on each element, so ElementTree exposes the attribute
    # under its expanded name; check both forms.
    XH = "{http://www.w3.org/1999/xlink}href"
    hrefs = []
    pdf_candidate = None
    for g in root.iter():
        if strip_ns(g.tag) != "graphic":
            continue
        h = g.get(XH) or g.get("xlink:href")
        if h and h not in hrefs:
            hrefs.append(h)
        if g.get("content-type") == "pmc-pdf" and h and not pdf_candidate:
            pdf_candidate = h
    if pdf_candidate:
        # The article PDF at /articles/PMC<id>/pdf/<name> is behind PMC's JS
        # proof-of-work gate and is usually not curl-able from servers. The
        # figure files below are what the audit actually needs; record the
        # candidate name in the manifest so a human (or browser) can fetch
        # the PDF if higher fidelity is wanted.
        (run / "pdf_candidate.txt").write_text(
            f"{pdf_candidate}\nhttps://pmc.ncbi.nlm.nih.gov/articles/PMC{num}/pdf/{pdf_candidate}\n",
            encoding="utf-8")
        print(f"PDF candidate (PoW-gated, not fetched): {pdf_candidate}")
    print(f"figures declared in XML: {len(hrefs)}")
    ok = 0
    for h in hrefs:
        dest = fig_dir / h
        if dest.exists() and dest.stat().st_size > 1000:
            ok += 1
            continue
        url = f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{num}/bin/{h}"
        print(f"  {h}", flush=True)
        if fetch_url(url, dest, binary=True, min_gap=4.0):
            ok += 1
        else:
            print(f"  BLOCKED {h} — record in manifest", file=sys.stderr)
    print(f"figures downloaded: {ok}/{len(hrefs)}")
    print(f"workdir ready: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
