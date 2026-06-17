#!/usr/bin/env python3
"""Guard against an accidental signatory-count regression.

Compares the freshly-built public/data/data.json against the version in the
last git commit (HEAD) and prints  prev -> new (delta).  This makes the true
current signatory total visible on every run, so a stale/duplicate copy can
never be mistaken for "the data shrank."

Exit codes:
    0  new total >= previous total  (or no prior commit / no data file)
    3  new total < previous total   -> update.ps1 pauses for confirmation

Run from the repo root (update.ps1 does this for you):
    python check_data_regression.py
"""
import json
import pathlib
import subprocess
import sys

DATA = pathlib.Path("public/data/data.json")


def total(text: str) -> int:
    d = json.loads(text)
    n = d.get("meta", {}).get("total_signatories")
    return n if isinstance(n, int) else len(d.get("signatories", []))


def main() -> int:
    if not DATA.exists():
        print("  [regression-check] public/data/data.json not found - skipping")
        return 0

    new_total = total(DATA.read_text(encoding="utf-8"))

    # Read the previous committed copy as BYTES and decode utf-8 ourselves.
    # (subprocess text mode would decode with the Windows locale / cp1252 and crash
    #  on the UTF-8 content in data.json -- em dashes, accented names, etc.)
    try:
        result = subprocess.run(
            ["git", "show", "HEAD:public/data/data.json"],
            capture_output=True, check=True,
        )
        old_total = total(result.stdout.decode("utf-8", errors="replace"))
    except subprocess.CalledProcessError:
        print(f"  [regression-check] no prior committed data.json; new total = {new_total}")
        return 0
    except Exception as e:
        print(f"  [regression-check] could not read prior total ({e!r}); new total = {new_total}")
        return 0

    delta = new_total - old_total
    sign = "+" if delta >= 0 else ""
    print(f"  [regression-check] signatories: {old_total} -> {new_total} ({sign}{delta})")

    if new_total < old_total:
        print(f"  [regression-check] WARNING: total DROPPED by {old_total - new_total}.")
        print("  [regression-check] Likely causes: the scrape failed, a CSV was truncated,")
        print("  [regression-check] or you are looking at a stale/duplicate copy. Verify before pushing.")
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
