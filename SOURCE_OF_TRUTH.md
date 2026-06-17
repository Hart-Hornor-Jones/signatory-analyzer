# Source of truth — UC signatory analyzer

**This folder is the one and only canonical project.**

- Repo: `C:\Users\harth\repos\signatory-analyzer\signatory_viz`
- Current data (source): `public/data/data.json`
- Published data (served by GitHub Pages): `docs/data/data.json`
- Live site: https://hart-hornor-jones.github.io/signatory-analyzer/
- Refresh + publish: `.\update.ps1`  (add `-Census` to also rebuild the faculty census)

## How to confirm you're looking at CURRENT data

Open `data.json` and check the `meta` block:

- `meta.generated` — timestamp of the build (should be recent)
- `meta.total_signatories` — the signatory count

The total only grows over time. As of **2026-06-16 it is 1890**. If a file shows
markedly fewer (e.g. 1256 or 1227) or an old `generated` date, it is a **stale copy** —
do not trust it.

## Do not trust data.json copies outside this repo

These are NOT the source of truth and will be out of date:

- any `dist/` build output (the build now targets `docs/`; `dist/` is gitignored)
- any copy of `signatory_viz` living under another folder

On 2026-06-16 a stale duplicate clone under
`OneDrive\Courses\Research\Senate Documents\Regents\signatory_viz` (frozen ~2026-06-02,
~1256 signers) was removed because reading it produced a false "the data regressed" alarm.
A backup zip is kept at
`OneDrive\Documents\Claude\Projects\Open letter analysis\signatory_viz_Regents_clone_backup_2026-06-16.zip`.

## Regression guard

`update.ps1` runs `check_data_regression.py` right after `build_data.py`. Every run prints
`signatories: <prev> -> <new> (<delta>)`, and if the total dropped versus the last commit it
warns and pauses before publishing.
