# UC Open-Letter Signatory Explorer

An interactive visualization of the faculty signatories of the two
ucstudentsuccess.org open letters on admissions / standardized testing — the
**STEM letter** and the **Social Sciences, Humanities & Professional Schools
letter**. It lets you:

- **Pick a letter** (or both combined): signers of both letters are
  deduplicated (exact normalized name + campus, plus the hand-adjudicated
  pairs in `signatures/cross_letter_merges.csv`).
- **Compare categories of signers** by campus, campus group, discipline (field
  group), broad field, rank / title-status, department, and campus × department.
- **See variation over time** — the published lists have no timestamps, so signing
  **order** (1 → N) is used as the time axis. Each letter has its own order; the
  combined view interleaves the letters by normalized progress (order/N within
  each letter — synthetic, since the letters launched at different times). A
  trajectory panel shows how each category accumulates, a decile panel shows how
  composition shifts from early to late signers, and an "as of signature #T"
  slider (with a play button) drives the whole view.
- **Choose how amounts are qualified**: raw count, % of all signatures, % of
  signatures so far, or **% of the relevant UC faculty** (penetration), with
  selectable faculty base (ladder-rank; ladder + lecturers; all instructional)
  and headcount year (Oct 2021–2025).

Faculty denominators come from the UC Information Center campus headcount tables
and are available at the campus, campus-group, and rank levels. Discipline,
department, and campus × department offer share-of-signatures framings only
(clean department-level faculty counts are not available in the source data).

## Develop

```bash
npm install
npm run dev      # http://localhost:5173
```

## Build

```bash
npm run build    # outputs static site to docs/ (ready for GitHub Pages)
npm run preview  # serve the production build locally
```

## Deploy to GitHub Pages

The build outputs to **`docs/`** (with a `.nojekyll`), which is what you publish.

1. `npm run build`
2. Push this folder to a GitHub repo.
3. **Settings -> Pages -> Deploy from a branch -> `main` / `/docs` -> Save.**
4. Site goes live at `https://<user>.github.io/<repo>/`.

`base: './'` makes the relative paths work in that subfolder. See `DEPLOY.md` for
the full walk-through and the update workflow.


## Updating the data

Everything lives in this repo: the signature CSVs and scrapers in
`signatures/`, the UC Information Center headcount workbooks in `headcounts/`.
`update.ps1` does the whole cycle (scrape → build → bake → publish). By hand:

```bash
python signatures/scrape_letters.py   # refresh both letters' CSVs (no browser needed)
python build_data.py                  # repo-relative defaults; writes public/data/data.json
```

`build_data.py` reads both letter CSVs, deduplicates signers across letters
(near-misses are reported to `signatures/cross_letter_review.csv`; confirmed
same-person pairs belong in `signatures/cross_letter_merges.csv`), re-classifies
every signatory (campus, discipline, rank, signing-order bins), rebuilds the
campus faculty denominators, and **asserts the systemwide headcount identity**
(All-UC = sum of the nine campuses + UCLA) across every year before writing the
file.

### Note on the headcount source files

The UC Information Center export named `Los Angeles campus headcounts.xlsx`
(in `headcounts/`) actually contains the **systemwide (All-UC)** totals, and
`Headcount table.xlsx` contains the real **UCLA** numbers. `build_data.py`
corrects this and verifies it arithmetically. See `build_data.py` for details.
