import { useState } from 'react'

// Phase 5 (PAGP): speedup S = Ts / Tp against worker count P, with the ideal S = P for reference, plus a table of
// wall time, efficiency E = S / P, throughput and whether the parallel results equal the sequential ones.
// Data: parallel.json from urban.parallel via urban.export, one row per worker count.
const W = 268, H = 230, M = { l: 30, r: 12, t: 12, b: 32 }
const fmt = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })
const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

export default function ParallelChart({ rows }) {
  const [hover, setHover] = useState(null)
  if (!rows?.length) return (
    <p className="notice">No benchmark yet. Run <code>uv run python -m urban.parallel hebbal</code>, then
      <code> urban.export</code>.</p>
  )
  const pts = [...rows].sort((a, b) => a.workers - b.workers)
  const pMax = Math.max(...pts.map(r => r.workers))
  const yMax = Math.max(pMax, ...pts.map(r => r.speedup))
  const x = p => M.l + (p / pMax) * (W - M.l - M.r)
  const y = s => M.t + (1 - s / yMax) * (H - M.t - M.b)
  const ticks = [...new Set([0, ...pts.map(r => r.workers)])]
  const yt = Array.from({ length: Math.floor(yMax) + 1 }, (_, i) => i).filter(i => yMax <= 8 || i % 2 === 0)
  const best = pts.reduce((a, b) => (b.speedup > a.speedup ? b : a))
  const seq = pts.find(r => r.workers === 1)
  const allSame = pts.every(r => r.identical === true || r.identical === 'True')
  const line = pts.map(r => `${x(r.workers)},${y(r.speedup)}`).join(' ')
  const h = hover != null ? pts[hover] : null
  const r0 = pts[0]

  return (
    <div className="chart parallel">
      <div className="chart-title">Speedup from parallel evaluation</div>
      <div className="muted small">
        The same {r0.scenarios} scenarios ({r0.mode} screen) run with 1 to {pMax} worker processes.
        Best: <b>{fmt(best.speedup, 2)}×</b> with {best.workers} workers.
      </div>
      <div className="plegend small">
        <span><i className="sw measured" />measured</span><span><i className="sw ideal" />ideal (S = P)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Line chart of measured speedup against number of workers, with the ideal linear speedup">
        {yt.map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={M.l - 6} y={y(t) + 3.5} className="tick" textAnchor="end">{t}×</text>
          </g>
        ))}
        {ticks.map(t => <text key={t} x={x(t)} y={H - M.b + 14} className="tick" textAnchor="middle">{t}</text>)}
        <text x={(M.l + W - M.r) / 2} y={H - 4} className="axis" textAnchor="middle">worker processes (P)</text>
        <line x1={x(0)} y1={y(0)} x2={x(pMax)} y2={y(pMax)} className="ideal" />
        <polyline points={line} className="measured" />
        {pts.map((r, i) => (
          <g key={r.workers} className="dot" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x(r.workers)} cy={y(r.speedup)} r="12" fill="transparent" />
            <circle cx={x(r.workers)} cy={y(r.speedup)} r={hover === i ? 5.5 : 4.5} className="pt" />
          </g>
        ))}
        <text x={x(best.workers) - 6} y={y(best.speedup) - 9} className="dlabel" textAnchor="end">{fmt(best.speedup, 2)}×</text>
      </svg>
      {h && (
        <div className="chart-tip" style={{ left: `${(100 * x(h.workers)) / W}%`, top: `${(100 * y(h.speedup)) / H}%` }}>
          <b>{h.workers} worker{h.workers > 1 ? 's' : ''}</b>: {fmt(h.speedup, 2)}× speedup, {fmt(100 * h.efficiency, 0)} % efficiency<br />
          {mmss(h.wall_s)} wall · {fmt(h.per_run_s, 0)} s per scenario
        </div>
      )}

      <table className="kv ptable">
        <thead><tr><th>P</th><th>Wall</th><th>Speedup</th><th>Efficiency</th><th>Scen./min</th></tr></thead>
        <tbody>
          {pts.map((r, i) => (
            <tr key={r.workers} className={hover === i ? 'hovered' : ''} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <td>{r.workers}</td><td>{mmss(r.wall_s)}</td><td><b>{fmt(r.speedup, 2)}×</b></td>
              <td>{fmt(100 * r.efficiency, 0)} %</td><td>{fmt(r.throughput_per_min, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className={`banner ${allSame ? 'ok' : 'fail'}`}>
        {allSame ? '✓ Parallel results are identical to the sequential run for every worker count.'
                 : '✗ Some parallel results differ from the sequential run.'}
      </div>
      <p className="muted small">
        Speedup S = T<sub>1</sub> / T<sub>P</sub>, efficiency E = S / P. Each scenario is independent, so they run as
        separate processes (Python <code>ProcessPoolExecutor</code>, one SUMO run per task).
        Per-scenario time grows from {fmt(seq?.per_run_s, 0)} s to {fmt(pts.at(-1).per_run_s, 0)} s as workers share
        memory and cache{r0.machine ? ` (${r0.machine}, ${r0.cpus} logical CPUs)` : ''}.
      </p>
    </div>
  )
}
