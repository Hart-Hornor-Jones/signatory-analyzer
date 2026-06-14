#!/usr/bin/env python3
"""
Build data.json for the UC Student Success signatory visualization.

Reads the ordered signatory tables of BOTH ucstudentsuccess.org open letters
(STEM: signatures/ucstudentsuccess_table.csv; Social Sciences / Humanities /
Professional Schools: signatures/socscihum_table.csv), deduplicates signers
appearing in both letters (exact normalized name + campus), classifies each
signatory (campus, campus group, discipline/field group, broad field, rank /
title-status, faculty type, and signing-order bins) using the same scheme as
analyze_uc_signatories.py, then assembles campus-level faculty denominators from
the UC Information Center "campus headcounts" workbooks. Emits a single
public/data/data.json consumed by the React/Plotly app.

Important data-quality fix
--------------------------
The Information Center headcount export named "Los Angeles campus headcounts.xlsx"
actually contains the SYSTEMWIDE (all-UC) totals, and "Headcount table.xlsx"
contains the real UCLA numbers. This is verified by the identity
    all_UC[type, year] == sum(other 9 campuses)[type, year] + UCLA[type, year]
which holds exactly for ladder-rank faculty across every year. The mapping below
applies that correction; the build asserts the identity and records it in meta.

Usage
-----
python build_data.py                       # repo-relative defaults
python build_data.py \
    --table signatures/ucstudentsuccess_table.csv \
    --table-ssh signatures/socscihum_table.csv \
    --headcounts-dir headcounts \
    --out public/data/data.json

Letters in the output: every signatory carries letters (["stem"], ["ssh"] or
both), per-letter signing orders order_stem / order_ssh, and a combined
normalized-interleave order used as the "Both letters" time axis.
"""
from __future__ import annotations

import argparse
import csv
import io
import datetime as dt
import json
import math
import re
from pathlib import Path

import openpyxl

# ---------------------------------------------------------------------------
# Classification scheme (kept in sync with analyze_uc_signatories.py)
# ---------------------------------------------------------------------------

FIELD_RULES = [
    ("Mathematics & statistics", [r"\bmath\b", r"mathematics", r"statistics", r"statistical", r"probability", r"biostatistics"]),
    ("Computer/data/EECS", [r"computer science", r"\bcse\b", r"data science", r"informatics", r"information science", r"information systems", r"electrical engineering and computer", r"eecs", r"computational"]),
    ("Engineering", [r"engineering", r"bioengineering", r"biomedical engineering", r"mechanical", r"aerospace", r"civil", r"environmental engineering", r"structural", r"materials", r"nanoengineering", r"nuclear", r"chemical and biomolecular", r"robotics"]),
    ("Physical sciences", [r"physics", r"astronomy", r"chemistry", r"biochemistry", r"earth", r"planetary", r"geology", r"geoscience", r"oceanography", r"atmospheric", r"climate", r"scripps"]),
    ("Biological/life sciences", [r"biology", r"biological", r"molecular", r"cell", r"ecology", r"evolution", r"genetics", r"genomics", r"neurobiology", r"neuroscience", r"plant", r"botany", r"zoology", r"microbiology", r"physiology", r"immunology", r"developmental biology"]),
    ("Medical/health sciences", [r"medicine", r"medical", r"surgery", r"pediatrics", r"psychiatry", r"public health", r"epidemiology", r"anesthesia", r"radiology", r"pathology", r"pharmacy", r"nursing", r"neurology", r"otolaryngology", r"ophthalmology", r"orthop", r"urology", r"dermatology", r"dentistry"]),
    ("Economics/business/management", [r"economics", r"economy", r"management", r"business", r"finance", r"marketing", r"accounting", r"rady", r"haas", r"anderson", r"agricultural and resource economics"]),
    ("Social sciences", [r"sociology", r"anthropology", r"political science", r"psychology", r"cognitive science", r"communication", r"geography", r"demography", r"urban", r"criminology", r"international studies", r"global studies"]),
    ("Law/policy/education/professional", [r"law", r"legal", r"public policy", r"public affairs", r"education", r"school of education", r"social welfare", r"planning", r"architecture", r"library"]),
    ("Humanities/arts", [r"english", r"history", r"philosophy", r"classics", r"literature", r"language", r"french", r"german", r"spanish", r"rhetoric", r"writing", r"theater", r"theatre", r"dance", r"music", r"art", r"film", r"media studies", r"religion", r"religious", r"comparative", r"melc", r"middle eastern", r"gender", r"ethnic studies"]),
]

BROAD_FIELD_MAP = {
    "Mathematics & statistics": "Core quantitative STEM",
    "Computer/data/EECS": "Core quantitative STEM",
    "Engineering": "Applied STEM/engineering",
    "Physical sciences": "Core physical STEM",
    "Biological/life sciences": "Life/biomedical STEM",
    "Medical/health sciences": "Medical/health professional",
    "Economics/business/management": "Quantitative social/professional",
    "Social sciences": "Social sciences",
    "Law/policy/education/professional": "Professional/policy/law/education",
    "Humanities/arts": "Humanities/arts",
    "Other/unclear": "Other/unclear",
}

CANONICAL_CAMPUSES = {
    "uc berkeley": "UC Berkeley", "berkeley": "UC Berkeley",
    "ucla": "UCLA", "uc los angeles": "UCLA",
    "uc san diego": "UC San Diego", "ucsd": "UC San Diego",
    "uc davis": "UC Davis",
    "uc irvine": "UC Irvine", "uci": "UC Irvine",
    "uc santa barbara": "UC Santa Barbara", "ucsb": "UC Santa Barbara",
    "uc santa cruz": "UC Santa Cruz", "ucsc": "UC Santa Cruz",
    "uc riverside": "UC Riverside", "ucr": "UC Riverside",
    "uc merced": "UC Merced", "ucm": "UC Merced",
    "uc san francisco": "UC San Francisco", "ucsf": "UC San Francisco",
}

CAMPUS_GROUPS = {
    "UC Berkeley": "Flagship (Berkeley/UCLA)",
    "UCLA": "Flagship (Berkeley/UCLA)",
    "UC San Diego": "Large established research",
    "UC Davis": "Large established research",
    "UC Irvine": "Large established research",
    "UC Santa Barbara": "Large established research",
    "UC Santa Cruz": "Smaller/newer/general",
    "UC Riverside": "Smaller/newer/general",
    "UC Merced": "Smaller/newer/general",
    "UC San Francisco": "Health-sciences",
}

# Title-status -> active faculty headcount type, for rank-based "penetration".
TITLE_TO_FACULTY_TYPE = {
    "Full professor": "ladder",
    "Associate professor": "ladder",
    "Assistant professor": "ladder",
    "Senior distinguished professor": "ladder",
    "Teaching professor / lecturer": "lecturers",
    "Teaching/lecturer, retired/emeritus": "emeritus",
    "Emeritus/retired professor": "emeritus",
    "Research/adjunct/specialist": "clinical_adjunct",
    "Administrative title": "other",
    "Other/unclear title": "unknown",
    "Unknown/unclear title": "unknown",
}

PHASE_BINS = [(1, 50, "001-050"), (51, 100, "051-100"), (101, 250, "101-250"),
              (251, 500, "251-500"), (501, 750, "501-750"), (751, math.inf, "751-end")]


def norm(x):
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).strip())


def clean_for_match(x):
    s = norm(x).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_field(dept):
    s = clean_for_match(dept)
    if not s:
        return "Other/unclear"
    for label, pats in FIELD_RULES:
        for p in pats:
            if re.search(p, s):
                return label
    return "Other/unclear"


def classify_campus(campus):
    s = clean_for_match(campus)
    if not s:
        return "Unknown campus"
    if s in CANONICAL_CAMPUSES:
        return CANONICAL_CAMPUSES[s]
    for k, v in CANONICAL_CAMPUSES.items():
        if k in s:
            return v
    return norm(campus)


def classify_title_status(title):
    t = clean_for_match(title)
    if not t:
        return "Unknown/unclear title"
    teaching = bool(re.search(r"professor of teaching|teaching professor|lecturer|lsoe|soe", t))
    emeritus = bool(re.search(r"emerit|retired", t))
    senior = bool(re.search(r"distinguished|chancellor|university professor|professor of the graduate school", t))
    if teaching:
        return "Teaching/lecturer, retired/emeritus" if emeritus else "Teaching professor / lecturer"
    if emeritus:
        return "Emeritus/retired professor"
    if senior:
        return "Senior distinguished professor"
    if re.search(r"\bassistant professor\b", t):
        return "Assistant professor"
    if re.search(r"\bassociate professor\b", t):
        return "Associate professor"
    if re.search(r"\bprofessor\b", t):
        return "Full professor"
    if re.search(r"research|scientist|specialist|scholar|adjunct", t):
        return "Research/adjunct/specialist"
    if re.search(r"dean|chair|director|provost|chancellor|president|head", t):
        return "Administrative title"
    return "Other/unclear title"


def phase_label(order, n):
    for lo, hi, lab in PHASE_BINS:
        if lo <= order <= hi:
            return f"{lo:03d}-{n:03d}" if math.isinf(hi) else lab
    return "unknown"


# ---------------------------------------------------------------------------
# Read signatories
# ---------------------------------------------------------------------------

def read_signatories(path: Path):
    rows = []
    for row in csv.reader(io.StringIO(_read_text_clean(path))):
        rows.append(row)
    started = False
    recs = []
    for row in rows:
        cells = [norm(c) for c in row]
        if len(cells) >= 5 and cells[1].lower() == "name" and cells[2].lower() == "title":
            started = True
            continue
        if not started:
            continue
        name = cells[1] if len(cells) > 1 else ""
        title = cells[2] if len(cells) > 2 else ""
        dept = cells[3] if len(cells) > 3 else ""
        campus = cells[4] if len(cells) > 4 else ""
        if name.lower() == "name":
            continue
        if any([name, title, dept, campus]):
            recs.append({"name": name, "title": title, "dept": dept, "campus_raw": campus})
    return recs


def _xn(s):
    """Crosswalk match key: clean_for_match, then drop the word 'and'."""
    return re.sub(r"\s+", " ", re.sub(r"\band\b", " ", clean_for_match(s))).strip()


def _read_text_clean(p):
    """Read a text file, tolerating stray NUL bytes from sync corruption."""
    return open(p, "rb").read().replace(b"\x00", b"").decode("utf-8-sig", errors="replace")


def load_crosswalk(path):
    """Load department_crosswalk.csv -> (by_campus, by_label) lookup indexes."""
    by_campus, by_label = {}, {}
    p = Path(path)
    if not p.exists():
        return by_campus, by_label
    for row in csv.DictReader(io.StringIO(_read_text_clean(p))):
        if not (row.get("raw_label") or "").strip():
            continue
        key = _xn(row["raw_label"])
        val = ((row.get("field_group") or "").strip(), (row.get("canonical_department") or "").strip())
        by_campus[((row.get("campus") or "").strip(), key)] = val
        by_label.setdefault(key, val)
    return by_campus, by_label


def load_overrides(path):
    """User-owned variant overrides (TOP priority, never auto-generated).
    Columns: raw_label, campus (blank=any), canonical_department, field_group (blank=auto)."""
    by_campus, by_any = {}, {}
    p = Path(path)
    if not p.exists():
        return by_campus, by_any
    for row in csv.DictReader(io.StringIO(_read_text_clean(p))):
        raw = (row.get("raw_label") or "").strip()
        if not raw or raw.startswith("#"):
            continue
        key = _xn(raw)
        canon = (row.get("canonical_department") or "").strip() or raw
        fg = (row.get("field_group") or "").strip() or classify_field(canon)
        campus = (row.get("campus") or "").strip()
        if campus:
            by_campus[(campus, key)] = (fg, canon)
        else:
            by_any[key] = (fg, canon)
    return by_campus, by_any


def build_signatory_records(recs, crosswalk=None, overrides=None):
    by_campus, by_label = crosswalk if crosswalk else ({}, {})
    ov_campus, ov_any = overrides if overrides else ({}, {})
    n = len(recs)
    out = []
    for i, r in enumerate(recs, start=1):
        ts = classify_title_status(r["title"])
        campus = classify_campus(r["campus_raw"])
        key = _xn(r["dept"])
        hit = (ov_campus.get((campus, key)) or ov_any.get(key)
               or by_campus.get((campus, key)) or by_label.get(key))
        if hit:
            fg, canon = hit
        else:
            fg, canon = classify_field(r["dept"]), (r["dept"] or "(none given)")
        dept_display = canon or (r["dept"] or "(none given)")
        decile = min(10, ((i - 1) * 10) // n + 1)
        out.append({
            "order": i,
            "name": r["name"],
            "title": r["title"],
            "dept": dept_display,
            "dept_raw": r["dept"] or "(none given)",
            "campus": campus,
            "campus_group": CAMPUS_GROUPS.get(campus, "Other/unknown"),
            "field_group": fg,
            "broad_field_group": BROAD_FIELD_MAP.get(fg, "Other/unclear"),
            "title_status": ts,
            "faculty_type": TITLE_TO_FACULTY_TYPE.get(ts, "unknown"),
            "campus_dept": (campus + " — " + dept_display) if campus not in ("Unknown campus",) else dept_display,
            "decile": decile,
            "phase": phase_label(i, n),
            "window100": f"{((i - 1) // 100) * 100 + 1:04d}-{min(((i - 1) // 100 + 1) * 100, n):04d}",
            "order_pct": round(i / n, 6),
        })
    return out


LETTER_META = {
    "stem": {"label": "STEM letter", "source_url": "https://ucstudentsuccess.org/"},
    "ssh": {"label": "Social Sciences, Humanities & Professional Schools letter",
            "source_url": "https://ucstudentsuccess.org/socscihum/"},
}


def merge_letter_records(stem_sigs, ssh_sigs, review_out=None, merges_csv=None):
    """Union of the two letters' signatories.

    Dedup rule: exact match on (clean_for_match(name), canonical campus).
    Each record keeps per-letter orders (order_stem / order_ssh, 1..N within
    that letter) and gains:
      letters - ["stem"], ["ssh"] or ["stem","ssh"]
      order   - combined 1..N_union rank by NORMALIZED INTERLEAVE: progress
                through a letter is order/N_letter; dual signers use their
                earliest progress. Synthetic (the letters launched at different
                times and both still accumulate) but keeps the combined
                timeline usable. decile/phase/window100/order_pct are
                recomputed on this combined order; single-letter views
                recompute deciles client-side.
    Near-misses (same campus + surname + first initial but not exact) are
    written to review_out for manual adjudication; confirmed pairs belong in
    merges_csv (cross_letter_merges.csv: campus, ssh_name, stem_name, note),
    which is applied as forced merges before exact matching.
    """
    n_stem, n_ssh = max(len(stem_sigs), 1), max(len(ssh_sigs), 1)

    def key(s):
        return (clean_for_match(s["name"]), s["campus"])

    def loose(s):
        toks = clean_for_match(s["name"]).split()
        return ((toks[-1] if toks else ""), (toks[0][:1] if toks else ""), s["campus"])

    merge_map = {}
    if merges_csv is not None and Path(merges_csv).exists():
        for row in csv.DictReader(io.StringIO(_read_text_clean(merges_csv))):
            campus = classify_campus(row.get("campus", ""))
            merge_map[(clean_for_match(row.get("ssh_name", "")), campus)] = \
                (clean_for_match(row.get("stem_name", "")), campus)

    out, by_key, stem_loose = [], {}, {}
    for s in stem_sigs:
        r = dict(s)
        r["letters"], r["order_stem"], r["order_ssh"] = ["stem"], s["order"], None
        by_key[key(s)] = r
        stem_loose.setdefault(loose(s), []).append(s)
        out.append(r)

    near, n_both = [], 0
    for s in ssh_sigs:
        k = key(s)
        hit = by_key.get(merge_map.get(k, k))
        if hit is not None:
            hit["letters"] = ["stem", "ssh"]
            hit["order_ssh"] = s["order"]
            if s["title"] and s["title"] != hit["title"]:
                hit["title_ssh"] = s["title"]
            if s["dept_raw"] != hit["dept_raw"]:
                hit["dept_ssh"] = s["dept_raw"]
            n_both += 1
            continue
        for cand in stem_loose.get(loose(s), []):
            if key(cand) != key(s):
                near.append({
                    "campus": s["campus"],
                    "ssh_name": s["name"], "ssh_title": s["title"], "ssh_dept": s["dept_raw"],
                    "stem_name": cand["name"], "stem_title": cand["title"], "stem_dept": cand["dept_raw"],
                    "stem_order": cand["order"], "ssh_order": s["order"],
                })
        r = dict(s)
        r["letters"], r["order_stem"], r["order_ssh"] = ["ssh"], None, s["order"]
        out.append(r)

    def prog(r):
        ps = []
        if r["order_stem"]:
            ps.append(r["order_stem"] / n_stem)
        if r["order_ssh"]:
            ps.append(r["order_ssh"] / n_ssh)
        return min(ps)

    out.sort(key=lambda r: (prog(r), 0 if "stem" in r["letters"] else 1,
                            r["order_stem"] or r["order_ssh"] or 0))
    n = len(out)
    for i, r in enumerate(out, start=1):
        r["order"] = i
        r["decile"] = min(10, ((i - 1) * 10) // n + 1)
        r["phase"] = phase_label(i, n)
        r["window100"] = f"{((i - 1) // 100) * 100 + 1:04d}-{min(((i - 1) // 100 + 1) * 100, n):04d}"
        r["order_pct"] = round(i / n, 6)

    if review_out is not None:
        if near:
            with open(review_out, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(near[0].keys()))
                w.writeheader()
                w.writerows(near)
        elif Path(review_out).exists():
            try:
                Path(review_out).unlink()
            except OSError:   # sandbox mounts may forbid unlink: blank it instead
                Path(review_out).write_text(
                    "campus,ssh_name,ssh_title,ssh_dept,stem_name,stem_title,stem_dept,stem_order,ssh_order\n"
                    "# (no pending near-miss pairs)\n", encoding="utf-8-sig")
    return out, n_both, near


# ---------------------------------------------------------------------------
# Read campus faculty denominators
# ---------------------------------------------------------------------------

CAMPUS_FILE_MAP = {
    "Berkeley campus headcounts.xlsx": "UC Berkeley",
    "Davis campus headcounts.xlsx": "UC Davis",
    "Irvine campus headcounts.xlsx": "UC Irvine",
    "Merced campus headcounts.xlsx": "UC Merced",
    "Riverside campus headcounts.xlsx": "UC Riverside",
    "San Diego campus headcounts.xlsx": "UC San Diego",
    "San Francisco campus headcounts.xlsx": "UC San Francisco",
    "Santa Barbara campus headcounts.xlsx": "UC Santa Barbara",
    "Santa Cruz campus headcounts.xlsx": "UC Santa Cruz",
    "Headcount table.xlsx": "UCLA",            # mislabeled default export = UCLA
    "Los Angeles campus headcounts.xlsx": "All UC",  # mislabeled = systemwide total
}


def map_label(lbl):
    l = lbl.lower()
    if "ladder" in l:
        return "ladder"
    if "clinical" in l or "in-residence" in l or "in residence" in l or "adjunct" in l:
        return "clinical_adjunct"
    if "lecturer" in l:
        return "lecturers"
    if "other academic" in l:
        return "other_academic"
    if "postdoc" in l:
        return "postdocs"
    if "intern" in l or "resident" in l:
        return "med_residents"
    if "student" in l and ("teaching" in l or "research" in l):
        return "student_assistants"
    if l == "total":
        return "total_all_academic"
    return None


def read_headcounts(hc_dir: Path):
    denom = {}
    for fname, campus in CAMPUS_FILE_MAP.items():
        fp = hc_dir / fname
        if not fp.exists():
            print(f"  WARNING: missing headcount file {fname}")
            continue
        wb = openpyxl.load_workbook(fp, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        header = rows[0]
        year_cols = {}
        for j, v in enumerate(header):
            if isinstance(v, str) and re.search(r"20\d{2}", v):
                year_cols[j] = re.search(r"(20\d{2})", v).group(1)
        denom.setdefault(campus, {y: {} for y in year_cols.values()})
        # Each workbook has an "Academic" block, a "Non-academic" block, and a
        # "Grand Total". We only want the Academic faculty block, otherwise the
        # non-academic "Total" row would overwrite the academic "Total".
        section = None
        for r in rows[1:]:
            c0 = norm(r[0]).lower()
            if c0 in ("academic", "non-academic", "nonacademic", "grand total"):
                section = c0
            if section != "academic":
                continue
            label = norm(r[1]) or norm(r[0])
            key = map_label(label)
            if not key:
                continue
            for j, y in year_cols.items():
                v = r[j] if j < len(r) else None
                if isinstance(v, (int, float)):
                    denom[campus][y][key] = int(v)
    # Derived faculty bases.
    for campus, byyear in denom.items():
        for y, d in byyear.items():
            ladder = d.get("ladder", 0)
            clin = d.get("clinical_adjunct", 0)
            lect = d.get("lecturers", 0)
            d["faculty_ladder"] = ladder
            d["faculty_ladder_lecturers"] = ladder + lect
            d["faculty_all_instructional"] = ladder + clin + lect
    return denom


def verify_systemwide_identity(denom, years, keys=("ladder", "clinical_adjunct", "lecturers", "total_all_academic")):
    """all_UC == sum(9 individual campuses) + UCLA, for each key, every year."""
    individual = [c for c in denom if c not in ("All UC",)]
    results = {}
    ok = True
    for y in years:
        per_key = {}
        for k in keys:
            all_uc = denom.get("All UC", {}).get(y, {}).get(k)
            parts = sum(denom.get(c, {}).get(y, {}).get(k, 0) for c in individual)
            match = (all_uc is not None and all_uc == parts)
            per_key[k] = {"all_uc_file": all_uc, "sum_of_campuses": parts, "match": match}
            if not match:
                ok = False
        results[y] = per_key
    return ok, results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _dnorm(s):
    s = re.sub(r"\bscripps institution of\b", " ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load_dept_faculty(path, sigs):
    """verified_department_faculty.csv -> {campus_dept_label: faculty_count}."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    fac = {}
    for row in csv.DictReader(open(p, encoding="utf-8-sig")):
        cnt = (row.get("core_faculty") or row.get("active_core") or row.get("all_listed") or "").strip()
        if not cnt:
            continue
        try:
            fac[(_dnorm(row["campus"]), _dnorm(row["department"]))] = int(cnt)
        except ValueError:
            continue
    seen = set()
    for s in sigs:
        cd = s["campus_dept"]
        if cd in seen:
            continue
        seen.add(cd)
        key = (_dnorm(s["campus"]), _dnorm(s["dept"]))
        if key in fac:
            out[cd] = fac[key]
    return out


# Tiers counted as "core" department faculty, matching the default base of
# the campus saturation page (Senate ladder + teaching professors + emeriti).
# Quarantine rules below are a sync copy of build_campus_saturation.py's --
# see the comments there for the per-cell evidence.
CENSUS_CORE_TIERS = {"ladder", "teaching", "emeritus"}
_CENSUS_DEPT_SUFFIX = re.compile(r",?\s+(emerit(us|a|i)|emeriti faculty)\s*$", re.I)
_CENSUS_DECEASED = re.compile(r"\(\s*\d{4}\s*[-\u2013]\s*\d{4}\s*\)")
_CENSUS_RUNON = re.compile(r"([A-Z][a-z]+ [A-Z][a-z]+.*){3,}")
_CENSUS_DROP_RUNON_CELLS = {
    ("UCLA", "Economics"), ("UCLA", "Geography"),
    ("UC Berkeley", "Environmental Science, Policy and Management"),
}
_CENSUS_EXCLUDE_CELLS = {
    ("UC Berkeley", "Ethnic Studies"), ("UC Berkeley", "Art Practice"), ("UC Berkeley", "German"),
}


def _census_key_norm(s):
    return re.sub(r"\s+", " ", re.sub(r"\band\b", " ", _dnorm(s))).strip()


def load_census_dept_faculty(path, sigs):
    """master_persons.csv (faculty census) -> {campus_dept: core_faculty}.

    Counts core-tier people per (campus, canonical dept). Where a unit's rank
    extraction failed (>=70% tier 'other'), its full roster is used instead,
    mirroring the saturation page. Rows injected from the signatory list are
    excluded so a never-harvested department can't appear with a signers-only
    roster; known-polluted cells are quarantined.
    """
    p = Path(path)
    if not p.exists():
        return {}
    total, core, other = {}, {}, {}
    for row in csv.DictReader(io.StringIO(_read_text_clean(p))):
        if (row.get("campus") or "") == "UC San Francisco":
            continue  # names-only catalog: no departments
        if (row.get("source") or "") == "signatories":
            continue
        if _CENSUS_DECEASED.search(row.get("name") or ""):
            continue
        dept = _CENSUS_DEPT_SUFFIX.sub("", (row.get("dept_canonical") or row.get("department") or "").strip())
        if not dept:
            continue
        if dept == "(non-academic unit)":
            continue   # crosswalk sentinel for minors/admin offices
        cell = (row["campus"], dept)
        if cell in _CENSUS_EXCLUDE_CELLS:
            continue
        if cell in _CENSUS_DROP_RUNON_CELLS and len(row.get("rank_raw") or "") > 100 \
                and _CENSUS_RUNON.search(row["rank_raw"]):
            continue
        key = (_census_key_norm(row["campus"]), _census_key_norm(dept))
        total[key] = total.get(key, 0) + 1
        tier = row.get("rank_tier") or ""
        if tier in CENSUS_CORE_TIERS:
            core[key] = core.get(key, 0) + 1
        elif tier == "other":
            other[key] = other.get(key, 0) + 1
    fac = {}
    for key, n in total.items():
        fac[key] = n if (other.get(key, 0) / n >= 0.7) else core.get(key, 0)
    out, seen = {}, set()
    for s in sigs:
        cd = s["campus_dept"]
        if cd in seen:
            continue
        seen.add(cd)
        n = fac.get((_census_key_norm(s["campus"]), _census_key_norm(s["dept"])))
        if n and n >= 5:   # tiny cells are roster fragments, not departments
            out[cd] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--table", type=Path, default=here / "signatures" / "ucstudentsuccess_table.csv",
                    help="STEM-letter signatory CSV")
    ap.add_argument("--table-ssh", type=Path, default=here / "signatures" / "socscihum_table.csv",
                    help="SocSci/Hum/Professional-letter signatory CSV")
    ap.add_argument("--headcounts-dir", type=Path, default=here / "headcounts")
    ap.add_argument("--out", type=Path, default=here / "public" / "data" / "data.json")
    ap.add_argument("--crosswalk", type=Path, default=here / "department_crosswalk.csv")
    ap.add_argument("--overrides", type=Path, default=here / "crosswalk_overrides.csv")
    ap.add_argument("--dept-faculty", type=Path, default=here.parent / "faculty_out" / "verified_department_faculty.csv")
    ap.add_argument("--census-persons", type=Path,
                    default=Path(r"C:\Users\harth\faculty census project\master_persons.csv"))
    args = ap.parse_args()

    crosswalk = load_crosswalk(args.crosswalk)
    overrides = load_overrides(args.overrides)
    print(f"  crosswalk: {len(crosswalk[0])} entries | overrides: {len(overrides[0])+len(overrides[1])} from {args.overrides.name}")
    print(f"Reading STEM-letter signatories from: {args.table}")
    sig_stem = build_signatory_records(read_signatories(args.table), crosswalk, overrides)
    print(f"  -> {len(sig_stem)} STEM-letter signatories")
    print(f"Reading SocSci/Hum-letter signatories from: {args.table_ssh}")
    sig_ssh = build_signatory_records(read_signatories(args.table_ssh), crosswalk, overrides)
    print(f"  -> {len(sig_ssh)} SocSci/Hum-letter signatories")
    review_out = args.table_ssh.parent / "cross_letter_review.csv"
    merges_csv = args.table_ssh.parent / "cross_letter_merges.csv"
    sigs, n_both, near = merge_letter_records(sig_stem, sig_ssh, review_out, merges_csv)
    print(f"  union: {len(sigs)} unique signers | signed both letters: {n_both}"
          + (f" | near-miss pairs for review: {len(near)} -> {review_out.name}" if near else ""))
    verified_denom = load_dept_faculty(args.dept_faculty, sigs)
    census_denom = load_census_dept_faculty(args.census_persons, sigs)
    dept_denom = dict(verified_denom)
    dept_denom.update(census_denom)   # census wins: uniform definition across cells
    n_vonly = sum(1 for k in verified_denom if k not in census_denom)
    print(f"  department faculty denominators: {len(dept_denom)} cells "
          f"({len(census_denom)} from faculty census + {n_vonly} verified-only)")
    n = len(sigs)
    print(f"  -> {n} signatories")

    print(f"Reading headcounts from: {args.headcounts_dir}")
    denom = read_headcounts(args.headcounts_dir)
    years = sorted({y for c in denom.values() for y in c})
    ok, ident = verify_systemwide_identity(denom, years)
    print(f"  Systemwide identity (All UC == sum campuses + UCLA):")
    for y in years:
        flags = "  ".join(f"{k}:{'OK' if ident[y][k]['match'] else 'MISMATCH'}" for k in ident[y])
        print(f"    {y}: {flags}")
    if not ok:
        print("  WARNING: systemwide identity did not hold; review the relabel mapping.")

    default_year = years[-1] if years else None

    # Distinct category orderings (by descending overall count) for the app.
    def counts(field):
        c = {}
        for s in sigs:
            c[s[field]] = c.get(s[field], 0) + 1
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    dimensions = {
        "campus": {"label": "Campus", "field": "campus", "supports_faculty_denominator": True},
        "field_group": {"label": "Discipline (field group)", "field": "field_group", "supports_faculty_denominator": False},
        "broad_field_group": {"label": "Broad field", "field": "broad_field_group", "supports_faculty_denominator": False},
        "title_status": {"label": "Rank / title-status", "field": "title_status", "supports_faculty_denominator": True},
        "dept": {"label": "Department", "field": "dept", "supports_faculty_denominator": False},
        "campus_dept": {"label": "Campus × department", "field": "campus_dept", "supports_faculty_denominator": True},
    }
    category_order = {dim: list(counts(meta["field"]).keys()) for dim, meta in dimensions.items()}

    data = {
        "meta": {
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "letter": "UC faculty open letters on admissions / standardized testing (ucstudentsuccess.org)",
            "letters": {
                "stem": dict(LETTER_META["stem"], n=len(sig_stem)),
                "ssh": dict(LETTER_META["ssh"], n=len(sig_ssh)),
            },
            "n_both_letters": n_both,
            "total_signatories": n,
            "order_is_time_proxy": True,
            "order_note": "The signatory lists are published in signing order with no timestamps. Signing ORDER (1..N) is used as the time axis. Each letter has its own order; the combined view interleaves the two letters by normalized progress (order/N within each letter), which is synthetic.",
            "denominator_years": years,
            "default_year": default_year,
            "faculty_bases": {
                "faculty_ladder": "Ladder-rank & equivalent faculty",
                "faculty_ladder_lecturers": "Ladder-rank + lecturers",
                "faculty_all_instructional": "All instructional faculty (ladder + clinical/adjunct + lecturers)",
            },
            "denominator_source": "UC Information Center campus headcount tables (October snapshots, 2021-2025).",
            "denominator_fix": {
                "applied": True,
                "explanation": "Export 'Los Angeles campus headcounts.xlsx' actually held the SYSTEMWIDE (All-UC) totals and 'Headcount table.xlsx' held the real UCLA numbers. Verified by all_UC == sum(9 campuses)+UCLA for ladder-rank across all years.",
                "verification": ident,
                "verified": ok,
            },
            "denominator_scope_note": "Only campus-level (and campus x rank) faculty denominators exist in the harvested data. Discipline, department, and campus x department offer share-of-signatures framings only.",
            "title_to_faculty_type": TITLE_TO_FACULTY_TYPE,
            "campus_groups": CAMPUS_GROUPS,
            "department_faculty_note": "Department faculty counts: all-UC faculty census (harvested catalogs/dept pages; ladder + teaching + emeriti), hand-verified rosters filling cells the census lacks. UCSF has no department-level counts (names-only catalog).",
            "headcount_keys": ["ladder", "clinical_adjunct", "lecturers", "other_academic", "postdocs", "med_residents", "student_assistants", "total_all_academic"],
        },
        "dimensions": dimensions,
        "category_order": category_order,
        "denominators": {"campus": denom, "department": dept_denom},
        "signatories": sigs,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out}  ({size_kb:.0f} KB)")
    print("\nCampus counts:")
    for k, v in list(counts("campus").items()):
        print(f"  {v:5d}  {k}")
    print("\nDiscipline counts:")
    for k, v in list(counts("field_group").items()):
        print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
