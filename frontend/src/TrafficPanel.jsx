import { useEffect, useRef, useState } from 'react'
import { getJSON } from './data.js'
import { SPEED_LEGEND, cssGradient } from './colors.js'

// Controls for the vehicle animation (traffic.js): which run, play/pause, playback speed, time slider.
// list = traffic.json from urban.fcd ({runs: [{run, label, file}], begin, end, period}).
const RATES = [1, 5, 10, 30]
const clock = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export default function TrafficPanel({ list, scene, keyOf }) {
  // deep link ?traffic=<run>&t=<seconds into the window> (for screenshots and demos)
  const q = new URLSearchParams(location.search)
  const [run, setRun] = useState(q.get('traffic'))        // null = animation off
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(10)
  const [t, setT] = useState(0)
  const [count, setCount] = useState(0)
  const [used, setUsed] = useState(0)
  const [hl, setHl] = useState(true)
  const traffic = useRef(null)

  useEffect(() => {
    const s = scene()
    if (!s) return
    if (!run) { s.setTraffic(null); setPlaying(false); return }
    const meta = list.runs.find(r => r.run === run)
    let live = true
    setLoading(true)
    getJSON(meta.file).then(d => {
      if (!live) return
      const keepT = traffic.current?.t ?? 0    // switching run keeps the clock, so before/after line up
      traffic.current = s.setTraffic(d, tr => { setT(tr.t); setCount(tr.count); setUsed(tr.usedSoFar) }, keyOf(run))
      traffic.current.highlight = hl
      traffic.current.t = Math.min(q.has('t') && !keepT ? Number(q.get('t')) : keepT, traffic.current.duration)
      traffic.current.rate = rate
      traffic.current.playing = true
      setPlaying(true)
    }).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [run])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (traffic.current) traffic.current.rate = rate }, [rate])
  useEffect(() => { if (traffic.current) traffic.current.playing = playing }, [playing])
  useEffect(() => { if (traffic.current) traffic.current.highlight = hl }, [hl])

  if (!list?.runs?.length) return null
  const dur = list.end - list.begin
  const seek = v => { if (traffic.current) { traffic.current.t = v; setT(v) } }

  return (
    <section className="traffic-panel">
      <h2>Traffic animation</h2>
      <p className="muted small">Real vehicles from the microsimulation, minutes {clock(list.begin)}–{clock(list.end)} of the
        peak hour. Switch runs to compare: the clock stays where it is.</p>
      <div className="seg">
        <button className={!run ? 'on' : ''} onClick={() => setRun(null)}>Off</button>
        {list.runs.map(r => (
          <button key={r.run} className={run === r.run ? 'on' : ''} onClick={() => setRun(r.run)} title={r.label}>
            {r.run === 'base' ? 'Baseline' : `With ${r.run}`}
          </button>
        ))}
      </div>
      {loading && <p className="muted small">Loading vehicles…</p>}
      {run && !loading && <>
        <div className="player">
          <button className="play" onClick={() => setPlaying(p => !p)} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? '❚❚' : '▶'}
          </button>
          <input type="range" min="0" max={dur} step="0.5" value={t} onChange={e => seek(Number(e.target.value))}
                 aria-label="Simulation time" />
          <span className="mono small">{clock(list.begin + t)}</span>
        </div>
        <div className="row small">
          <span className="muted">Speed</span>
          <span className="rates">
            {RATES.map(r => <button key={r} className={rate === r ? 'on' : ''} onClick={() => setRate(r)}>{r}×</button>)}
          </span>
          <span className="muted">{count} cars</span>
        </div>
        {run !== 'base' && (
          <div className="users">
            <label className="check small">
              <input type="checkbox" checked={hl} onChange={e => setHl(e.target.checked)} />
              <span><i className="sw-hl" /> Highlight cars that use {run}</span>
            </label>
            <div className="small"><b>{used}</b> <span className="muted">cars have used {run} so far
              (of {traffic.current?.users.size ?? 0} in these {Math.round(dur / 60)} min)</span></div>
          </div>
        )}
        <div className="legend">
          <div className="muted small">Car speed (same colours as the roads)</div>
          <div className="bar" style={{ background: cssGradient(SPEED_LEGEND.stops) }} />
          <div className="ends small"><span>stopped</span><span>50+ km/h</span></div>
        </div>
        <p className="muted small">Cars are drawn larger when zoomed out so they stay visible.</p>
      </>}
    </section>
  )
}
