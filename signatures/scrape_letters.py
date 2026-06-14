#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scrape the signatory tables of BOTH ucstudentsuccess.org open letters.

The letters embed their signature lists as published Google Sheets, so no
browser is needed (this replaces the Playwright-based
extract_ucstudentsuccess_table.py, kept in this folder for reference).
For each letter this script:

  1. fetches the letter page and discovers the embedded pubhtml sheet URL
     (falls back to the last known URL if the page layout changes),
  2. fetches the published sheet and parses the grid,
  3. writes a CSV in the same shape the legacy extractor produced
     (column_1 = sheet row number; row "Number of signatories"; header row
     Name / Title / Dept. / Campus; then one row per signatory in signing
     order).

Usage (from signatory_viz/):
    python signatures/scrape_letters.py            # both letters
    python signatures/scrape_letters.py --letter stem
    python signatures/scrape_letters.py --letter ssh

Requires: beautifulsoup4  (pip install beautifulsoup4)
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("beautifulsoup4 is required:  pip install beautifulsoup4")

HERE = Path(__file__).resolve().parent

LETTERS = {
    "stem": {
        "label": "STEM letter",
        "page_url": "https://ucstudentsuccess.org/",
        # last-known published sheet (re-discovered from the page each run)
        "pubhtml": "https://docs.google.com/spreadsheets/d/e/2PACX-1vT4ldtmve2Y3v-ux4cLu1HXnIITvQmFkdJoHyAZ2XQ_0vS_xiwyroPmXvOTnXve476psLTwGxvGZyLV/pubhtml?gid=2068506710&single=true",
        "out": HERE / "ucstudentsuccess_table.csv",
    },
    "ssh": {
        "label": "Social Sciences, Humanities & Professional Schools letter",
        "page_url": "https://ucstudentsuccess.org/socscihum/",
        "pubhtml": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQO_IwWVITNa_d1yoHCf0Mlwo6o05XaNXJdHpeVd-d5YuObs5bsDOIyrOskH3CmyeFu_TtJKutKwXPJ/pubhtml?gid=170239816&single=true",
        "out": HERE / "socscihum_table.csv",
    },
}

UA = {"User-Agent": "Mozilla/5.0 (signatory-analyzer data refresh)"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def discover_pubhtml(page_html: str) -> str | None:
    """Find the embedded published-sheet URL on a letter page."""
    m = re.search(
        r"https://docs\.google\.com/spreadsheets/d/e/[A-Za-z0-9_-]+/pubhtml[^\"'\s<>]*",
        page_html.replace("&amp;", "&"),
    )
    return m.group(0) if m else None


def pub_csv_url(pubhtml_url: str) -> str:
    """pubhtml grid URL -> the published-sheet CSV export for the same gid.

    Google began serving pubhtml as a JS shell (no <table> in the static
    HTML) for the SSH sheet on 2026-06-12; the /pub?output=csv endpoint
    still returns the raw grid and is the more stable machine route.
    """
    u = pubhtml_url.replace("/pubhtml", "/pub")
    u = re.sub(r"[?&](widget|headers)=[^&]*", "", u)
    return u + ("&" if "?" in u else "?") + "output=csv"


def parse_pub_csv(text: str) -> list[list[str]]:
    """CSV export -> same rows shape parse_sheet produces ([rownum, cells...])."""
    if text.lstrip()[:1] == "<":
        raise RuntimeError("csv export returned HTML, not CSV")
    rows: list[list[str]] = []
    for rec in csv.reader(io.StringIO(text)):
        if not any(c.strip() for c in rec):
            continue
        rows.append([str(len(rows) + 1)] + [re.sub(r"\s+", " ", c).strip() for c in rec])
    if len(rows) < 2:
        raise RuntimeError("csv export came back empty")
    return rows


def parse_sheet(html: str) -> list[list[str]]:
    """Published-sheet grid -> rows of [row_number, cell, cell, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    table = max(soup.find_all("table"), key=lambda t: len(t.find_all("tr")), default=None)
    if table is None:
        raise RuntimeError("no <table> found in published sheet")
    out = []
    for tr in table.find_all("tr"):
        rownum = tr.find("th")
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not any(cells):
            continue
        label = rownum.get_text(strip=True) if rownum else str(len(out) + 1)
        out.append([label] + [re.sub(r"\s+", " ", c) for c in cells])
    return out


def write_csv(rows: list[list[str]], out: Path) -> None:
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([f"column_{i+1}" for i in range(width)])
        w.writerows(rows)


def declared_count(rows: list[list[str]]) -> int | None:
    for r in rows[:3]:
        joined = " ".join(r).lower()
        if "number of signatories" in joined:
            m = re.search(r"(\d[\d,]*)", joined.split("signatories", 1)[1])
            if m:
                return int(m.group(1).replace(",", ""))
    return None


def data_row_count(rows: list[list[str]]) -> int:
    n, started = 0, False
    for r in rows:
        cells = [c.strip().lower() for c in r[1:5]] + ["", "", "", ""]
        if cells[0] == "name" and cells[1] == "title":
            started = True
            continue
        if started and any(c.strip() for c in r[1:]):
            n += 1
    return n


def scrape(letter_id: str) -> bool:
    cfg = LETTERS[letter_id]
    print(f"[{letter_id}] {cfg['label']}")
    pub = cfg["pubhtml"]
    try:
        found = discover_pubhtml(fetch(cfg["page_url"]))
        if found:
            pub = found
    except Exception as e:
        print(f"  page fetch failed ({e}); using last-known sheet URL")
    rows, src = None, None
    try:
        rows, src = parse_pub_csv(fetch(pub_csv_url(pub))), "csv export"
    except Exception as e:
        print(f"  csv export failed ({e}); falling back to the pubhtml table")
        try:
            rows, src = parse_sheet(fetch(pub)), "pubhtml table"
        except Exception as e2:
            print(f"  ERROR: could not fetch/parse published sheet: {e2}")
            return False
    n_data, n_decl = data_row_count(rows), declared_count(rows)
    write_csv(rows, cfg["out"])
    print(f"  wrote {cfg['out'].name}: {n_data} signatories via {src}"
          + (f" (sheet declares {n_decl})" if n_decl is not None else ""))
    if n_decl is not None and n_decl != n_data:
        print(f"  WARNING: declared count {n_decl} != parsed rows {n_data}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--letter", choices=[*LETTERS, "all"], default="all")
    args = ap.parse_args()
    ids = list(LETTERS) if args.letter == "all" else [args.letter]
    ok = all([scrape(i) for i in ids])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
