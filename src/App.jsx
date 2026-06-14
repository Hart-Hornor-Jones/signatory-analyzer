import { useEffect, useMemo, useRef, useState } from 'react'
import PlotlyChart from './components/PlotlyChart.jsx'
import {
  MEASURES, rankedRows, countsAtT, catByOrder, cumulativeSeries,
  trajectoryValue, decileComposition, facultyDenominator, colorMap, fmtValue,
} from './lib/compute.js'

const DATA_URL = `${import.meta.env.BASE_URL}data/data.json`
const TOPN_OPTIONS = [8, 12, 20, 'all']

const THEME_KEY = 'ucol-theme'
function getInitialTheme() {
  try { return localStorage.getItem(THEME_KEY) || 'dark' } catch { return 'dark' }
}
function useNarrow() {
  const [n, setN] = useState(typeof window !== 'undefined' && window.innerWidth < 620)
  useEffect(() => {
    const f = () => setN(window.innerWidth < 620)
    window.addEventListener('resize', f)
    return () => window.removeEventListener('resize', f)
  }, [])
  return n
}
// Plotly chrome (grid/axis/marker) per theme; category colors stay shared.
const CHART_CHROME = {
  dark:  { grid: '#1c2547', axis: '#93a0bd', marker: '#aab6d8' },
  light: { grid: '#e9edf5', axis: '#5b6478', marker: '#39425a' },
}

const LETTER_OPTIONS = [
  { id: 'both', label: 'Both letters' },
  { id: 'stem', label: 'STEM' },
  { id: 'ssh',  label: 'SocSci/Hum' },
]

// Derive the active view: filter to a letter (re-ranking 1..N within it and
// recomputing deciles) or use the combined normalized-interleave order baked
// into data.json. category_order is recomputed so rankings reflect the view.
function deriveView(data, letter) {
  let sigs
  if (letter === 'both') {
    sigs = data.signatories
  } else {
    const key = letter === 'stem' ? 'order_stem' : 'order_ssh'
    sigs = data.signatories
      .filter((s) => s[key])
      .map((s) => ({ ...s, order: s[key] }))
      .sort((a, b) => a.order - b.order)
    const n = sigs.length
    sigs.forEach((s, i) => { s.decile = Math.min(10, Math.floor((i * 10) / n) + 1) })
  }
  const category_order = {}
  for (const [dim, m] of Object.entries(data.dimensions)) {
    const c = new Map()
    for (const s of sigs) c.set(s[m.field], (c.get(s[m.field]) || 0) + 1)
    category_order[dim] = [...c.entries()]
      .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
      .map(([cat]) => cat)
  }
  return { ...data, signatories: sigs, category_order }
}

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const [letter, setLetter] = useState('both')
  const [dim, setDim] = useState('campus')
  const [measure, setMeasure] = useState('count')
  const [base, setBase] = useState('faculty_ladder')
  const [year, setYear] = useState(null)
  const [T, setT] = useState(null)
  const [topN, setTopN] = useState(12)
  const [playing, setPlaying] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [theme, setTheme] = useState(getInitialTheme)
  const narrow = useNarrow()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* private mode */ }
    const mt = document.querySelector('meta[name="theme-color"]')
    if (mt) mt.setAttribute('content', theme === 'dark' ? '#0a0f1e' : '#f4f6fb')
  }, [theme])
  const chrome = CHART_CHROME[theme]

  useEffect(() => {
    fetch(DATA_URL)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { setData(d); setYear(d.meta.default_year); setT(d.meta.total_signatories) })
      .catch((e) => setError(String(e)))
  }, [])

  const view = useMemo(() => (data ? deriveView(data, letter) : null), [data, letter])

  const dimMeta = data?.dimensions[dim]
  const field = dimMeta?.field
  const N = view?.signatories.length || 0
  const supportsFaculty = !!dimMeta?.supports_faculty_denominator
  const letterMeta = data?.meta.letters

  // Switching letters resets the cutoff to the new view's full range.
  useEffect(() => {
    if (view) { setPlaying(false); setT(view.signatories.length) }
  }, [letter])  // eslint-disable-line react-hooks/exhaustive-deps

  // If the chosen measure needs faculty data but the dimension can't supply it,
  // fall back to a composition measure.
  useEffect(() => {
    if (measure === 'faculty' && !supportsFaculty) setMeasure('share_so_far')
  }, [measure, supportsFaculty])

  // Animate the as-of cutoff when "play" is on.
  const playRef = useRef(null)
  useEffect(() => {
    if (!playing || !N) return
    if (T >= N) setT(1)
    const stepMs = 30
    const inc = Math.max(1, Math.round(N / 200))
    playRef.current = setInterval(() => {
      setT((prev) => {
        const next = (prev ?? 0) + inc
        if (next >= N) { setPlaying(false); return N }
        return next
      })
    }, stepMs)
    return () => clearInterval(playRef.current)
  }, [playing, N])

  const colors = useMemo(() => (view ? colorMap(view, dim) : {}), [view, dim])

  // Ranked rows for the composition panel + table.
  const ranked = useMemo(() => {
    if (!view || !field) return null
    return rankedRows(view, { dim, field, measure, T, base, year, topN })
  }, [view, dim, field, measure, T, base, year, topN])

  // Categories whose trajectories we draw: top-N by OVERALL count (stable in T).
  const trajCats = useMemo(() => {
    if (!view || !field) return []
    const tot = countsAtT(view.signatories, field, N)
    const order = (view.category_order[dim] || [...tot.keys()])
      .filter((c) => (tot.get(c) || 0) > 0)
    const k = topN === 'all' ? Math.min(order.length, 12) : topN
    return order.slice(0, k)
  }, [view, dim, field, topN, N])

  const catArr = useMemo(() => (view && field ? catByOrder(view.signatories, field) : []), [view, field])
  const cumSeries = useMemo(() => {
    if (!catArr.length) return null
    return cumulativeSeries(catArr, trajCats, measure !== 'faculty')
  }, [catArr, trajCats, measure])

  if (error) return <div className="loading">Could not load data: {error}</div>
  if (!data || !view || T == null) return <div className="loading">Loading signatory data…</div>

  const measureMeta = MEASURES.find((m) => m.id === measure)
  const pct = measureMeta.pct
  const Tc = Math.min(T, N)

  // ---- Panel A: ranked composition (horizontal bars) ----
  const aRows = [...ranked.shown].reverse()
  const barTrace = {
    type: 'bar', orientation: 'h',
    x: aRows.map((r) => r.value),
    y: aRows.map((r) => r.cat),
    marker: { color: aRows.map((r) => colors[r.cat] || '#4e79a7') },
    customdata: aRows.map((r) => [r.cntT, r.fac]),
    hovertemplate:
      '<b>%{y}</b><br>' +
      (pct ? 'Value: %{x:.1%}<br>' : 'Value: %{x:,}<br>') +
      'Signatures (so far): %{customdata[0]:,}' +
      (measure === 'faculty' ? '<br>Faculty denominator: %{customdata[1]:,}' : '') +
      '<extra></extra>',
  }
  const aLayout = {
    margin: { l: 8, r: 16, t: 10, b: 36 },
    height: Math.max(220, aRows.length * (narrow ? 24 : 26) + 60),
    font: { color: chrome.axis },
    xaxis: { tickformat: pct ? '.0%' : ',d', zeroline: true, gridcolor: chrome.grid, tickfont: { size: narrow ? 10.5 : 12, color: chrome.axis } },
    yaxis: { automargin: true, tickfont: { size: narrow ? 10.5 : 12, color: chrome.axis } },
    bargap: 0.25,
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }

  // ---- Panel B: trajectory over signing order ----
  let bTraces = []
  if (cumSeries) {
    const step = Math.max(1, Math.round(N / 400))
    for (const key of cumSeries.keys) {
      const fac = measure === 'faculty' && key !== 'Other'
        ? facultyDenominator(view, dim, key, base, year) : null
      if (measure === 'faculty' && (key === 'Other' || fac == null)) continue
      const xs = [], ys = []
      for (let o = 1; o <= N; o += step) {
        xs.push(o)
        ys.push(trajectoryValue(measure, cumSeries.cum[key][o], o, N, fac))
      }
      if (xs[xs.length - 1] !== N) {
        xs.push(N); ys.push(trajectoryValue(measure, cumSeries.cum[key][N], N, N, fac))
      }
      bTraces.push({
        type: 'scatter', mode: 'lines', name: key,
        x: xs, y: ys,
        line: { width: key === 'Other' ? 1.5 : 2, color: colors[key] || '#888', dash: key === 'Other' ? 'dot' : 'solid' },
        hovertemplate: `<b>${key}</b><br>by signature #%{x}<br>` + (pct ? '%{y:.1%}' : '%{y:,}') + '<extra></extra>',
      })
    }
  }
  const orderAxisTitle = letter === 'both'
    ? 'Combined signing order (the two letters interleaved by % progress through each)'
    : 'Signing order (1 = first to sign → N = most recent)'
  const bLayout = {
    // narrow: extra height + bottom margin so the multi-row horizontal
    // legend has room below the axis instead of colliding with it
    margin: { l: narrow ? 46 : 56, r: 12, t: 10, b: narrow ? 150 : 44 },
    height: narrow ? 500 : 480,
    font: { color: chrome.axis },
    xaxis: { title: { text: narrow ? 'Signing order' : orderAxisTitle, standoff: 16 }, gridcolor: chrome.grid, range: [1, N], tickfont: { color: chrome.axis } },
    yaxis: { tickformat: pct ? '.0%' : ',d', gridcolor: chrome.grid, rangemode: 'tozero', tickfont: { color: chrome.axis } },
    legend: { orientation: 'h', y: narrow ? -0.14 : -0.20, yanchor: 'top', x: 0, xanchor: 'left', font: { size: narrow ? 10 : 11, color: chrome.axis } },
    shapes: [{ type: 'line', x0: Tc, x1: Tc, y0: 0, y1: 1, yref: 'paper', line: { color: chrome.marker, width: 1, dash: 'dash' } }],
    annotations: [{ x: Tc, y: 1, yref: 'paper', text: `as of #${Tc}`, showarrow: false, font: { size: 11, color: chrome.marker }, xanchor: Tc > N * 0.8 ? 'right' : 'left' }],
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }

  // ---- Panel C: composition within signing-order deciles ----
  const dec = decileComposition(view.signatories, field, trajCats)
  const cKeys = [...trajCats, 'Other']
  const cTraces = cKeys.map((key) => ({
    type: 'bar', name: key,
    x: Array.from({ length: 10 }, (_, i) => i + 1),
    y: Array.from({ length: 10 }, (_, i) => {
      const d = i + 1
      return dec.totals[d] ? (dec.counts[d][key] || 0) / dec.totals[d] : 0
    }),
    marker: { color: colors[key] || '#c7c7c7' },
    hovertemplate: `<b>${key}</b><br>decile %{x}: %{y:.1%}<extra></extra>`,
  }))
  const cLayout = {
    barmode: 'stack',
    // narrow: no axis title and a deep bottom margin — the legend wraps to
    // ~5-6 rows on a phone and was overprinting the title
    margin: { l: 48, r: 12, t: 10, b: narrow ? 130 : 42 },
    height: narrow ? 420 : 320,
    font: { color: chrome.axis },
    xaxis: { title: narrow ? undefined : { text: 'Signing-order decile (1 = earliest tenth → 10 = latest tenth)', standoff: 16 }, dtick: 1, gridcolor: chrome.grid, tickfont: { color: chrome.axis } },
    yaxis: { tickformat: '.0%', gridcolor: chrome.grid, range: [0, 1], tickfont: { color: chrome.axis } },
    legend: { orientation: 'h', y: narrow ? -0.10 : -0.24, yanchor: 'top', x: 0, xanchor: 'left', font: { size: narrow ? 10 : 11, color: chrome.axis } },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  }

  const topRow = ranked.shown[0]
  const nCats = ranked.rows.length
  const quickStops = [50, 100, 250, 500].filter((q) => q < N)

  return (
    <div className="app">
      <div className="topbar-in">
        <span className="crumb">UC open letters</span>
        <nav className="tblinks">
          <a href={`${import.meta.env.BASE_URL}campus_saturation.html`}>Campus saturation</a>
          <a href={`${import.meta.env.BASE_URL}ucsd_saturation_time.html`}>UCSD deep dive</a>
        </nav>
        <button className="themebtn" title="Toggle light/dark"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
          {theme === 'dark' ? '\u2600' : '\u263e'}
        </button>
      </div>
      <header className="hdr">
        <h1>UC Open-Letter <span className="grad">Signatory Explorer</span></h1>
        <p className="sub">
          {data.meta.total_signatories.toLocaleString()} unique faculty signers across two
          ucstudentsuccess.org open letters — the STEM letter
          ({letterMeta.stem.n.toLocaleString()}) and the Social Sciences, Humanities &amp;
          Professional Schools letter ({letterMeta.ssh.n.toLocaleString()});{' '}
          {data.meta.n_both_letters.toLocaleString()} signed both.
          Compare signers by campus, discipline, and rank, and watch the composition change across the
          signing sequence. Deep dives:{' '}
          <a href={`${import.meta.env.BASE_URL}campus_saturation.html`}>department &amp; field saturation, all campuses</a>{' · '}
          <a href={`${import.meta.env.BASE_URL}ucsd_saturation_time.html`}>UCSD</a>.{' '}
          <button className="link" onClick={() => setShowNotes((s) => !s)}>
            {showNotes ? 'Hide data notes ▲' : 'Data notes & caveats ▼'}
          </button>
        </p>
        {showNotes && <NotesPanel meta={data.meta} />}
      </header>

      <section className="controls">
        <div className="ctrl">
          <label>Letter</label>
          <div className="quick">
            {LETTER_OPTIONS.map((o) => (
              <button key={o.id} className={letter === o.id ? 'on' : ''}
                title={o.id === 'both' ? 'Union of the two letters, deduplicated' : (letterMeta[o.id]?.label || o.label)}
                onClick={() => setLetter(o.id)}>
                {o.label}{letterMeta[o.id] ? ` (${letterMeta[o.id].n.toLocaleString()})` : ` (${data.meta.total_signatories.toLocaleString()})`}
              </button>
            ))}
          </div>
        </div>

        <div className="ctrl">
          <label>Compare by</label>
          <select value={dim} onChange={(e) => setDim(e.target.value)}>
            {Object.entries(data.dimensions).map(([id, m]) => (
              <option key={id} value={id}>{m.label}</option>
            ))}
          </select>
        </div>

        <div className="ctrl">
          <label>Measure</label>
          <select value={measure} onChange={(e) => setMeasure(e.target.value)}>
            {MEASURES.map((m) => (
              <option key={m.id} value={m.id} disabled={m.needsFaculty && !supportsFaculty}>
                {m.label}{m.needsFaculty && !supportsFaculty ? ' — campus/rank only' : ''}
              </option>
            ))}
          </select>
        </div>

        <div className={`ctrl ${measure === 'faculty' ? '' : 'disabled'}`}>
          <label>Faculty base</label>
          <select value={base} disabled={measure !== 'faculty' || dim === 'title_status' || dim === 'campus_dept'}
            onChange={(e) => setBase(e.target.value)}>
            {Object.entries(data.meta.faculty_bases).map(([id, lbl]) => (
              <option key={id} value={id}>{lbl}</option>
            ))}
          </select>
        </div>

        <div className="ctrl">
          <label>Show top</label>
          <select value={topN} onChange={(e) => setTopN(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
            {TOPN_OPTIONS.map((n) => <option key={n} value={n}>{n === 'all' ? 'All' : `Top ${n}`}</option>)}
          </select>
        </div>

        <div className="ctrl grow">
          <label>As of signature #{Tc} {' '}
            <span className="muted">({((Tc / N) * 100).toFixed(0)}% of {N})</span>
          </label>
          <div className="sliderrow">
            <button className="play" onClick={() => setPlaying((p) => !p)} title="Animate over signing order">
              {playing ? '❚❚' : '▶'}
            </button>
            <input type="range" min={1} max={N} value={Tc} onChange={(e) => { setPlaying(false); setT(Number(e.target.value)) }} />
          </div>
          <div className="quick">
            {[...quickStops, N].map((q) => (
              <button key={q} className={Tc === q ? 'on' : ''} onClick={() => { setPlaying(false); setT(q) }}>
                {q === N ? 'All' : q}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="kpis">
        <Kpi label={letter === 'both' ? 'Unique signers (both letters)' : `Signatories (${letterMeta[letter].label})`}
          value={N.toLocaleString()} />
        {letter === 'both' && <Kpi label="Signed both letters" value={data.meta.n_both_letters.toLocaleString()} />}
        <Kpi label="Signed by cutoff" value={Tc.toLocaleString()} />
        <Kpi label={`${dimMeta.label} categories`} value={nCats.toLocaleString()} />
        {topRow && <Kpi label={`Top ${dimMeta.label.toLowerCase()}`} value={topRow.cat}
          sub={`${fmtValue(topRow.value, pct)}${measure === 'faculty' ? ' of faculty' : ''}`} />}
      </section>

      <div className="help-line">{measureMeta.help}</div>

      <main className="grid">
        <Card title={`Composition by ${dimMeta.label.toLowerCase()}`}
          subtitle={`Ranked by ${measureMeta.label.toLowerCase()}, as of signature #${Tc}`}>
          <PlotlyChart data={[barTrace]} layout={aLayout} />
          {ranked.remainder.length > 0 && (
            <div className="muted small">+ {ranked.remainder.length} more categor{ranked.remainder.length === 1 ? 'y' : 'ies'} not shown (raise “Show top”).</div>
          )}
        </Card>

        <Card title="Trajectory over the signing sequence"
          subtitle={`Cumulative ${measureMeta.label.toLowerCase()} as signatures accumulate${letter === 'both' ? ' (combined interleaved order)' : ''}`}>
          <PlotlyChart data={bTraces} layout={bLayout} />
        </Card>
      </main>

      <Card title="How composition shifts from early to late signers"
        subtitle="Share of each signing-order decile (each column sums to 100%)" wide>
        <PlotlyChart data={cTraces} layout={cLayout} />
      </Card>

      <Card title={`Detail table — ${dimMeta.label.toLowerCase()}`}
        subtitle={`As of signature #${Tc}. ${measure === 'faculty' ? (dim === 'campus_dept' ? 'Department faculty rosters from campus catalogs (Senate faculty + teaching + emeriti; covered departments only).' : 'Faculty denominators: UC Information Center headcounts, Oct ' + year + (dim === 'title_status' ? ' (each rank vs. its matching faculty type).' : ' (' + data.meta.faculty_bases[base] + ').')) : ''}`} wide>
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>#</th><th>{dimMeta.label}</th><th className="num">Signatures</th>
                <th className="num">% of all</th><th className="num">% so far</th>
                {supportsFaculty && <th className="num">Faculty</th>}
                {supportsFaculty && <th className="num">% of faculty</th>}
              </tr>
            </thead>
            <tbody>
              {ranked.shown.map((r, i) => {
                const facv = supportsFaculty ? facultyDenominator(view, dim, r.cat, base, year) : null
                return (
                  <tr key={r.cat}>
                    <td className="muted">{i + 1}</td>
                    <td><span className="swatch" style={{ background: colors[r.cat] || '#ccc' }} />{r.cat}</td>
                    <td className="num">{r.cntT.toLocaleString()}</td>
                    <td className="num">{fmtValue(r.cntT / N, true)}</td>
                    <td className="num">{fmtValue(Tc > 0 ? r.cntT / Tc : 0, true)}</td>
                    {supportsFaculty && <td className="num">{facv ? facv.toLocaleString() : '—'}</td>}
                    {supportsFaculty && <td className="num">{facv ? fmtValue(r.cntT / facv, true) : '—'}</td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <footer className="ftr">
        <span>Signatory order is a proxy for time (the published lists have no timestamps).</span>
        <span>“Both letters” interleaves the two letters by normalized progress and deduplicates signers who appear on both.</span>
        <span>Faculty denominators: UC Information Center campus headcounts (Oct snapshots). Discipline/department offer share-of-signatures only.</span>
        <span>Generated {data.meta.generated}.</span>
      </footer>
    </div>
  )
}

function Card({ title, subtitle, children, wide }) {
  return (
    <section className={`card ${wide ? 'wide' : ''}`}>
      <div className="card-h">
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

function Kpi({ label, value, sub }) {
  return (
    <div className="kpi">
      <div className="kpi-l">{label}</div>
      <div className="kpi-v">{value}</div>
      {sub && <div className="kpi-s">{sub}</div>}
    </div>
  )
}

function NotesPanel({ meta }) {
  return (
    <div className="notes">
      <ul>
        <li><b>Two letters.</b> The STEM letter ({meta.letters.stem.n.toLocaleString()} signatories) and the
          Social Sciences, Humanities &amp; Professional Schools letter ({meta.letters.ssh.n.toLocaleString()})
          are scraped separately; {meta.n_both_letters.toLocaleString()} people signed both and are counted once
          in the combined view (matched on normalized name + campus, plus a hand-adjudicated merge list for
          name variants).</li>
        <li><b>Time axis = signing order.</b> {meta.order_note}</li>
        <li><b>Denominators.</b> {meta.denominator_source} {meta.denominator_scope_note}</li>
        <li><b>Measures.</b> “% of all signatures” divides by the full signature total; “% of signatures so far” divides by signers up to the cutoff; “% of faculty” divides by the relevant UC headcount.</li>
        <li><b>Rank penetration.</b> Headcounts split faculty into ladder-rank, clinical/adjunct, and lecturers — not by professor rank. So “% of faculty” for assistant/associate/full/distinguished professors all share the all-UC ladder-rank denominator; it decomposes overall ladder penetration by rank rather than comparing within-rank.</li>
        <li><b>Classification.</b> Discipline (field group) and rank (title-status) are inferred from free-text department and title strings; some departments bridge categories.</li>
      </ul>
    </div>
  )
}
