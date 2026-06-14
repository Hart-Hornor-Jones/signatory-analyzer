import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-basic-dist-min'

// Thin React wrapper around Plotly.react. Re-renders when data/layout change,
// resizes with the container, and cleans up on unmount.
//
// Mobile hardening (2026-06-12): the wrapper div takes an explicit height
// from layout.height so the surrounding card always reserves the chart's
// space — Android Chrome can measure a 0/partial-height container while the
// viewport is still settling, which used to collapse the card to a sliver —
// and every render is followed by a next-frame resize kick so Plotly
// re-measures once layout has settled.
export default function PlotlyChart({ data, layout, config, style }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current) return
    const cfg = { displaylogo: false, responsive: true, displayModeBar: false, ...(config || {}) }
    Plotly.react(ref.current, data, layout, cfg)
    const id = requestAnimationFrame(() => {
      if (ref.current) Plotly.Plots.resize(ref.current)
    })
    return () => cancelAnimationFrame(id)
  }, [data, layout, config])

  useEffect(() => {
    const el = ref.current
    const onResize = () => { if (el) Plotly.Plots.resize(el) }
    window.addEventListener('resize', onResize)
    window.addEventListener('orientationchange', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('orientationchange', onResize)
    }
  }, [])

  useEffect(() => () => { if (ref.current) Plotly.purge(ref.current) }, [])

  const h = layout && layout.height
  const fallback = h
    ? { width: '100%', height: `${h}px`, minHeight: `${h}px` }
    : { width: '100%', height: '100%' }
  return <div ref={ref} style={style || fallback} />
}
