// Pure data helpers for the signatory explorer.
// All "as of #T" measures are computed consistently: a measure is evaluated on
// the signatories whose signing order is <= T (the cutoff). At T = N this is
// the full dataset.

export const MEASURES = [
  { id: 'count',        label: 'Count (signatures)',        pct: false, needsFaculty: false,
    help: 'Number of signatures in the category, counting signers up to the as-of cutoff.' },
  { id: 'share_all',    label: '% of all signatures',       pct: true,  needsFaculty: false,
    help: "Category signatures (up to the cutoff) divided by the full signature total N. At the full cutoff this is the category's overall share." },
  { id: 'share_so_far', label: '% of signatures so far',    pct: true,  needsFaculty: false,
    help: 'Category signatures divided by the number of signers up to the cutoff — i.e. the composition of the cohort that has signed so far.' },
  { id: 'faculty',      label: '% of faculty (penetration)',pct: true,  needsFaculty: true,
    help: 'Category signatures (up to the cutoff) divided by the relevant UC faculty headcount — what fraction of that faculty population has signed. Campus, campus-group, and rank dimensions only.' },
]

// Map a rank/title-status faculty_type to a campus-headcount key (or null).
const FACULTY_TYPE_TO_KEY = { ladder: 'ladder', lecturers: 'lecturers', clinical_adjunct: 'clinical_adjunct' }

// Count signatories per category among order <= T.
export function countsAtT(sigs, field, T) {
  const m = new Map()
  for (const s of sigs) {
    if (s.order <= T) m.set(s[field], (m.get(s[field]) || 0) + 1)
  }
  return m
}

// Faculty denominator for one category of a dimension (or null when undefined).
export function facultyDenominator(data, dim, cat, base, year) {
  const D = data.denominators.campus
  if (dim === 'campus') {
    return D[cat]?.[year]?.[base] ?? null
  }
  if (dim === 'campus_group') {
    const groups = data.meta.campus_groups
    let sum = 0, any = false
    for (const c of Object.keys(D)) {
      if (c === 'All UC') continue
      if (groups[c] === cat) {
        const v = D[c]?.[year]?.[base]
        if (typeof v === 'number') { sum += v; any = true }
      }
    }
    return any ? sum : null
  }
  if (dim === 'title_status') {
    // Penetration vs. the matching all-UC faculty type. The faculty_type is a
    // function of title_status, so look it up from the meta map.
    const ftype = data.meta.title_to_faculty_type[cat]
    const key = FACULTY_TYPE_TO_KEY[ftype]
    if (!key) return null
    return D['All UC']?.[year]?.[key] ?? null
  }
  if (dim === 'campus_dept') {
    return data.denominators.department?.[cat] ?? null
  }
  return null
}

// Single measure value for a category, given its count-so-far cntT.
export function measureValue(measure, cntT, N, T, fac) {
  switch (measure) {
    case 'count':        return cntT
    case 'share_all':    return N > 0 ? cntT / N : 0
    case 'share_so_far': return T > 0 ? cntT / T : 0
    case 'faculty':      return fac && fac > 0 ? cntT / fac : null
    default:             return cntT
  }
}

// Ranked rows for the composition panel + table.
export function rankedRows(data, { dim, field, measure, T, base, year, topN }) {
  const sigs = data.signatories
  const N = sigs.length
  const cntMap = countsAtT(sigs, field, T)
  const order = data.category_order[dim] || [...cntMap.keys()]
  const rows = []
  for (const cat of order) {
    const cntT = cntMap.get(cat) || 0
    if (cntT === 0 && measure !== 'faculty') continue
    const fac = measure === 'faculty' ? facultyDenominator(data, dim, cat, base, year) : null
    if (measure === 'faculty' && (fac == null)) continue
    const value = measureValue(measure, cntT, N, T, fac)
    if (value == null) continue
    rows.push({ cat, cntT, fac, value })
  }
  rows.sort((a, b) => b.value - a.value || b.cntT - a.cntT)
  const shown = topN === 'all' ? rows : rows.slice(0, topN)
  const remainder = topN === 'all' ? [] : rows.slice(topN)
  return { rows, shown, remainder, N }
}

// Build the per-order category sequence for a field (sorted by order).
export function catByOrder(sigs, field) {
  const arr = new Array(sigs.length)
  const byOrder = [...sigs].sort((a, b) => a.order - b.order)
  for (let i = 0; i < byOrder.length; i++) arr[i] = byOrder[i][field]
  return arr
}

// Cumulative counts at every order position for a set of categories, with
// everything outside `cats` folded into 'Other'.
export function cumulativeSeries(catArr, cats, includeOther = true) {
  const N = catArr.length
  const set = new Set(cats)
  const keys = includeOther ? [...cats, 'Other'] : [...cats]
  const cum = {}
  const run = {}
  for (const k of keys) { cum[k] = new Float64Array(N + 1); run[k] = 0 }
  for (let o = 1; o <= N; o++) {
    const c = catArr[o - 1]
    const k = set.has(c) ? c : 'Other'
    if (k in run) run[k] += 1
    for (const key of keys) cum[key][o] = run[key]
  }
  return { cum, keys, N }
}

// Convert cumulative counts to the selected measure at each order.
export function trajectoryValue(measure, cumAtO, o, N, fac) {
  switch (measure) {
    case 'count':        return cumAtO
    case 'share_all':    return N > 0 ? cumAtO / N : 0
    case 'share_so_far': return o > 0 ? cumAtO / o : 0
    case 'faculty':      return fac && fac > 0 ? cumAtO / fac : null
    default:             return cumAtO
  }
}

// Composition within each signing-order decile (1..10): share of each category.
export function decileComposition(sigs, field, cats) {
  const set = new Set(cats)
  const counts = {}        // decile -> {cat -> n}
  const totals = {}        // decile -> n
  for (let d = 1; d <= 10; d++) { counts[d] = {}; totals[d] = 0 }
  for (const s of sigs) {
    const d = s.decile
    const k = set.has(s[field]) ? s[field] : 'Other'
    counts[d][k] = (counts[d][k] || 0) + 1
    totals[d] += 1
  }
  return { counts, totals }
}

// Stable categorical palette. Colors are assigned by a category's rank in the
// dimension's global ordering so a category keeps its color across panels.
const PALETTE = [
  '#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#76b7b2', '#edc948',
  '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac', '#86bcb6', '#d37295',
  '#a0cbe8', '#ffbe7d', '#8cd17d', '#f1ce63', '#fabfd2', '#b6992d',
  '#499894', '#d4a6c8',
]
export function colorMap(data, dim) {
  const order = data.category_order[dim] || []
  const m = {}
  order.forEach((cat, i) => { m[cat] = PALETTE[i % PALETTE.length] })
  m['Other'] = '#c7c7c7'
  return m
}

export function fmtValue(v, pct) {
  if (v == null) return '—'
  if (pct) return (100 * v).toFixed(1) + '%'
  return Math.round(v).toLocaleString()
}
