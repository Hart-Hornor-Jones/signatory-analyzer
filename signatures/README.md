# Signature lists + scrapers

Everything the app needs about the ucstudentsuccess.org open-letter signatures
lives here (moved 2026-06-12 from `OneDrive\...\Regents\06_scripts`).

| file | what |
|---|---|
| `scrape_letters.py` | Refreshes both CSVs from the letters' embedded published Google Sheets. No browser needed. Run by `update.ps1` step 0, or by hand: `python signatures/scrape_letters.py` |
| `ucstudentsuccess_table.csv` | STEM letter signatories (ucstudentsuccess.org), signing order |
| `socscihum_table.csv` | Social Sciences / Humanities / Professional Schools letter signatories (ucstudentsuccess.org/socscihum), signing order |
| `cross_letter_review.csv` | Written by `build_data.py`: near-miss name pairs across the two letters (same campus + surname + first initial but not an exact match) for manual dedup review |
| `extract_ucstudentsuccess_table.py` | Legacy Playwright scraper the STEM CSV originally came from; kept for reference/fallback |
| `ucstudentsuccess_table_raw_rows.csv` | Raw-row artifact of the legacy extractor's last run |

`build_data.py` reads both letter CSVs, deduplicates signers who appear in both
(exact match on normalized name + campus → `letters: ["stem","ssh"]` in
data.json), and emits per-letter signing orders plus a combined
normalized-interleave order used by the explorer's "Both letters" view.
