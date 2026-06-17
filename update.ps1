# update.ps1 - refresh the explorer from the live signature lists and publish it.
#   .\update.ps1            normal site refresh (scrapes both letters first)
#   .\update.ps1 -NoScrape  skip the scrape; rebuild from the CSVs already in signatures\
#   .\update.ps1 -Census    ALSO rebuild the faculty census (re-matches
#                           signatories against rosters - run after the letters
#                           gain signatures or roster sources change; ~minutes)
param([switch]$Census, [switch]$NoScrape)
# Everything lives in this repo now: signature CSVs + scrapers in signatures\,
# UC Information Center headcount xlsx in headcounts\.
# (If PowerShell says scripts are disabled, run:  powershell -ExecutionPolicy Bypass -File .\update.ps1 )

Set-Location -Path $PSScriptRoot

if (-not $NoScrape) {
    Write-Host "0/4  Scraping both letters' signature tables (ucstudentsuccess.org)..." -ForegroundColor Cyan
    python signatures\scrape_letters.py
    if ($LASTEXITCODE -ne 0) { Write-Host "      scrape failed - continuing with the CSVs already in signatures\." -ForegroundColor Yellow }
}

Write-Host "1/4  Rebuilding data.json from the letter CSVs (dedup across letters)..." -ForegroundColor Cyan
python build_data.py
if ($LASTEXITCODE -ne 0) { Write-Host "build_data.py failed - see the error above. Stopping." -ForegroundColor Red; exit 1 }
# cross-letter near-misses land in signatures\cross_letter_review.csv;
# confirmed same-person pairs go in signatures\cross_letter_merges.csv

# Regression guard: print prev -> new signatory total; pause if the count DROPPED.
# (Makes the true current total visible every run, so a stale copy can't look like a regression.)
python check_data_regression.py
if ($LASTEXITCODE -eq 3) {
    $ans = Read-Host "      ^ signatory total DROPPED vs the last commit. Continue and publish anyway? (y/N)"
    if ($ans -ne 'y') { Write-Host "Stopping - nothing committed or pushed." -ForegroundColor Red; exit 1 }
}

if ($Census) {
    Write-Host "1a/4  Rebuilding the faculty census (harvest + signatory re-match)..." -ForegroundColor Cyan
    Push-Location ..
    $env:PYTHONPATH = "."
    python -m census.build_master --person-info-dir "C:\Users\harth\faculty census project\Person Info"
    if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Host "census build failed - see above. Stopping." -ForegroundColor Red; exit 1 }
    python -m census.review_unmatched   # refresh unmatched_review.csv classification
    Copy-Item census\output\master_persons.csv, census\output\master_persons.xlsx, census\output\match_report.json, census\output\unmatched_review.csv "C:\Users\harth\faculty census project\" -Force
    Pop-Location
    Write-Host "      outputs copied to C:\Users\harth\faculty census project\ (if master_persons.xlsx is open in Excel, close and reopen it)" -ForegroundColor DarkGray
}

if (-not (Test-Path ..\ucsd_rosters.json)) {
    Write-Host "1a/4  Fetching UCSD catalog name rosters (one-time; ~30 pages)..." -ForegroundColor Cyan
    python ..\ucsd_rosters.py   # delete ..\ucsd_rosters.json and rerun to refresh rosters
}

Write-Host "1b/4  Re-baking the UCSD saturation pages..." -ForegroundColor Cyan
python ..\build_ucsd_viz.py   # refresh UCSD pages from the new data.json (no fetching)

Write-Host "1c/4  Re-baking the all-campus saturation page (faculty census)..." -ForegroundColor Cyan
python ..\build_campus_saturation.py   # reads C:\Users\harth\faculty census project\master_persons.csv
# (The Senate-service / prior-letter splits read ..\ucsd_groups.json. Re-run
#  "python ..\ucsd_groups.py" only if the committee, payroll, or prior-letter CSVs change.)

Write-Host "2/4  Building the website..." -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE -ne 0) { Write-Host "npm run build failed - see the error above. Stopping." -ForegroundColor Red; exit 1 }

Write-Host "3/4  Saving changes to git..." -ForegroundColor Cyan
git add -A
git commit -m ("Update data " + (Get-Date -Format "yyyy-MM-dd HH:mm"))   # 'nothing to commit' here is fine

Write-Host "4/4  Publishing to GitHub..." -ForegroundColor Cyan
git push

Write-Host ""
Write-Host "Done. Wait ~1 minute, then hard-refresh the site (Ctrl+F5):" -ForegroundColor Green
Write-Host "   https://hart-hornor-jones.github.io/signatory-analyzer/" -ForegroundColor Green
