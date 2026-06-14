#!/usr/bin/env python3
"""
Extract the large embedded table from https://ucstudentsuccess.org/.

Usage:
    python extract_ucstudentsuccess_table.py

Custom output path:
    python extract_ucstudentsuccess_table.py --out ucstudentsuccess_table.csv

Also save Excel:
    python extract_ucstudentsuccess_table.py --out ucstudentsuccess_table.csv --xlsx ucstudentsuccess_table.xlsx

Debug mode:
    python extract_ucstudentsuccess_table.py --debug
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


DEFAULT_URL = "https://ucstudentsuccess.org/"


def clean_cell(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    return text.strip()


def unique_rows(rows: list[list[str]]) -> list[list[str]]:
    seen = set()
    out = []

    for row in rows:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            out.append(row)

    return out


def rectangularize(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return rows

    width = max(len(row) for row in rows)

    return [row + [""] * (width - len(row)) for row in rows]


def table_rows_from_html_table(locator) -> list[list[str]]:
    """
    Extract rows from a normal <table>.
    """
    rows = locator.evaluate(
        """
        table => Array.from(table.querySelectorAll("tr")).map(tr =>
            Array.from(tr.querySelectorAll("th,td")).map(td => td.innerText)
        )
        """
    )

    cleaned = []
    for row in rows:
        cleaned_row = [clean_cell(str(cell)) for cell in row]
        if any(cleaned_row):
            cleaned.append(cleaned_row)

    return cleaned


def rows_from_aria_table(locator) -> list[list[str]]:
    """
    Extract rows from ARIA grids/tables, often used by JavaScript table widgets.
    """
    rows = locator.evaluate(
        """
        root => {
            const rowEls = Array.from(root.querySelectorAll('[role="row"]'));
            return rowEls.map(row => {
                const cells = Array.from(
                    row.querySelectorAll('[role="cell"],[role="gridcell"],[role="columnheader"],[role="rowheader"]')
                );
                return cells.map(cell => cell.innerText);
            });
        }
        """
    )

    cleaned = []
    for row in rows:
        cleaned_row = [clean_cell(str(cell)) for cell in row]
        if any(cleaned_row):
            cleaned.append(cleaned_row)

    return cleaned


def extract_all_tables_from_frame(frame, debug: bool = False) -> list[dict[str, Any]]:
    """
    Return candidate tables from one frame.
    """
    candidates = []

    html_tables = frame.locator("table")
    table_count = html_tables.count()

    if debug:
        print(f"Frame {frame.url}: found {table_count} <table> elements")

    for i in range(table_count):
        table = html_tables.nth(i)
        try:
            rows = table_rows_from_html_table(table)
        except Exception as e:
            if debug:
                print(f"  Failed table {i}: {e}")
            continue

        if rows:
            candidates.append({
                "kind": "html_table",
                "frame_url": frame.url,
                "index": i,
                "rows": rows,
                "row_count": len(rows),
                "col_count": max(len(r) for r in rows),
            })

    aria_roots = frame.locator('[role="table"], [role="grid"]')
    aria_count = aria_roots.count()

    if debug:
        print(f"Frame {frame.url}: found {aria_count} ARIA table/grid elements")

    for i in range(aria_count):
        root = aria_roots.nth(i)
        try:
            rows = rows_from_aria_table(root)
        except Exception as e:
            if debug:
                print(f"  Failed ARIA table/grid {i}: {e}")
            continue

        if rows:
            candidates.append({
                "kind": "aria_table",
                "frame_url": frame.url,
                "index": i,
                "rows": rows,
                "row_count": len(rows),
                "col_count": max(len(r) for r in rows),
            })

    return candidates


def try_set_table_length_to_all(frame, debug: bool = False) -> None:
    """
    Many WordPress/JavaScript tables use DataTables. If a page-length selector exists,
    try to switch it to 'All' or the largest available option.
    """
    selectors = [
        'select[name$="_length"]',
        'select[aria-controls]',
        'select',
    ]

    for selector in selectors:
        loc = frame.locator(selector)
        count = loc.count()

        for i in range(count):
            select = loc.nth(i)

            try:
                options = select.evaluate(
                    """
                    sel => Array.from(sel.options).map(o => ({
                        value: o.value,
                        text: o.textContent.trim()
                    }))
                    """
                )
            except Exception:
                continue

            if not options:
                continue

            # Prefer explicit "All", then -1, then largest numeric value.
            chosen = None

            for opt in options:
                if opt["text"].lower() == "all" or opt["value"] == "-1":
                    chosen = opt["value"]
                    break

            if chosen is None:
                numeric_options = []
                for opt in options:
                    try:
                        numeric_options.append((int(opt["value"]), opt["value"]))
                    except Exception:
                        pass

                if numeric_options:
                    chosen = max(numeric_options)[1]

            if chosen is not None:
                try:
                    select.select_option(chosen)
                    frame.wait_for_timeout(1000)
                    if debug:
                        print(f"Set table length selector {selector} to {chosen} in frame {frame.url}")
                    return
                except Exception as e:
                    if debug:
                        print(f"Could not set selector {selector}: {e}")


def collect_paginated_datatable_rows(frame, debug: bool = False) -> list[list[str]]:
    """
    If the table is paginated and only visible rows are in the DOM, click 'Next'
    repeatedly and collect rows from the largest table on each page.
    """
    all_rows = []

    for _ in range(1000):
        candidates = extract_all_tables_from_frame(frame, debug=False)
        if not candidates:
            break

        best = max(candidates, key=lambda c: (c["row_count"], c["col_count"]))
        all_rows.extend(best["rows"])

        next_buttons = [
            'a.paginate_button.next:not(.disabled)',
            'button[aria-label="Next"]:not([disabled])',
            'button:has-text("Next"):not([disabled])',
            'a:has-text("Next")',
        ]

        clicked = False

        for selector in next_buttons:
            loc = frame.locator(selector)
            if loc.count() == 0:
                continue

            btn = loc.first

            try:
                class_name = btn.get_attribute("class") or ""
                aria_disabled = btn.get_attribute("aria-disabled") or ""

                if "disabled" in class_name.lower() or aria_disabled.lower() == "true":
                    continue

                btn.click()
                frame.wait_for_timeout(750)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            break

    all_rows = unique_rows(all_rows)

    if debug and all_rows:
        print(f"Collected {len(all_rows)} unique rows by pagination from frame {frame.url}")

    return all_rows


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    # Prefer the table with most rows, then most columns.
    return max(candidates, key=lambda c: (c["row_count"], c["col_count"]))


def rows_to_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    rows = rectangularize(rows)

    if not rows:
        return pd.DataFrame()

    # Guess whether first row is a header.
    first = rows[0]
    rest = rows[1:]

    first_nonempty = sum(bool(x) for x in first)
    repeated_first = any(row == first for row in rest[:10])

    use_header = (
        first_nonempty >= 2
        and not repeated_first
        and len(set(first)) == len(first)
    )

    if use_header:
        columns = [col or f"column_{i+1}" for i, col in enumerate(first)]
        data = rest
    else:
        columns = [f"column_{i+1}" for i in range(len(first))]
        data = rows

    return pd.DataFrame(data, columns=columns)


def save_raw_rows(rows: list[list[str]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default="ucstudentsuccess_table.csv")
    parser.add_argument("--xlsx", default=None)
    parser.add_argument("--raw", default="ucstudentsuccess_table_raw_rows.csv")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--headed", action="store_true", help="Show browser window while running.")
    args = parser.parse_args()

    out_path = Path(args.out)
    raw_path = Path(args.raw)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})

        print(f"Loading {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            print("Network did not become fully idle; continuing anyway.")

        # Give late-rendering widgets a little extra time.
        page.wait_for_timeout(5000)

        # Try expanding DataTables-style widgets before extraction.
        for frame in page.frames:
            try_set_table_length_to_all(frame, debug=args.debug)

        page.wait_for_timeout(1000)

        candidates = []

        for frame in page.frames:
            candidates.extend(extract_all_tables_from_frame(frame, debug=args.debug))

        best = choose_best_candidate(candidates)

        paginated_rows = []

        # If the largest rendered table is suspiciously small, try pagination collection.
        for frame in page.frames:
            rows = collect_paginated_datatable_rows(frame, debug=args.debug)
            if len(rows) > len(paginated_rows):
                paginated_rows = rows

        if paginated_rows and (best is None or len(paginated_rows) > best["row_count"]):
            rows = paginated_rows
            source = "paginated table traversal"
            source_frame = "unknown"
        elif best is not None:
            rows = best["rows"]
            source = best["kind"]
            source_frame = best["frame_url"]
        else:
            browser.close()
            print("No table-like structure found.")
            print("Try running with --headed --debug to inspect the rendered page.")
            sys.exit(1)

        rows = unique_rows(rows)
        rows = [row for row in rows if any(cell.strip() for cell in row)]

        browser.close()

    if not rows:
        print("Found a table-like object, but it had no rows.")
        sys.exit(1)

    save_raw_rows(rows, raw_path)

    df = rows_to_dataframe(rows)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    if args.xlsx:
        xlsx_path = Path(args.xlsx)
        df.to_excel(xlsx_path, index=False)
        print(f"Saved Excel file: {xlsx_path.resolve()}")

    print()
    print(f"Extraction source: {source}")
    print(f"Source frame: {source_frame}")
    print(f"Rows extracted, including possible header row: {len(rows):,}")
    print(f"Columns detected: {df.shape[1]:,}")
    print(f"Saved CSV: {out_path.resolve()}")
    print(f"Saved raw rows CSV: {raw_path.resolve()}")

    print()
    print("Preview:")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()