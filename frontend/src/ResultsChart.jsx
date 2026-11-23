import { useMemo, useState } from 'react'
import { scoreColor } from './colors.js'

// Score vs traffic on the new road, one dot per candidate. Shows the Braess pattern: the more traffic a shortcut
// attracts, the worse the network gets. Polarity is carried by position (above/below the zero line), colour repeats it.
const W = 268, H = 300, M = { l: 38, r: 10, t: 12, b: 34 }
const symlog = v => Math.sign(v) * Math.log10(1 + Math.abs(v))
const TICKS_Y = [-300, -100, -30, -10, -3, 0, 3, 10, 30]

export default function ResultsChart({ rows, selKey, onSelect, onHover = () => {} }) {
  const [hover, setHover] = useState(null)
  const pts = useMemo(() => rows.map(r => ({ ...r, ys: symlog(r.score) })), [rows])
  if (!pts.length) return null
  const xMax = Math.max(100, ...pts.map(p => p.vph)) * 1.05
  const yMin = Math.min(symlog(-10), ...pts.map(p => p.ys)) - 0.08, yMax = Math.max(symlog(3), ...pts.map(p => p.ys)) + 0.08
  const x = v => M.l + (v / xMax) * (W - M.l - M.r)
  const y = v => M.t + (1 - (v - yMin) / (yMax - yMin)) * (H - M.t - M.b)
  const xticks = [0, 250, 500, 750, 1000, 1250].filter(t => t <= xMax)
  const selected = pts.find(p => p.key === selKey)

  return (
    <div className="chart">
      <div className="chart-title">Score vs traffic on the new road</div>
      <div className="muted small">Each dot is one candidate. Busier shortcuts score worse (Braess paradox).</div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Scatter plot of candidate score against vehicles per hour on the new road">
        {TICKS_Y.filter(t => symlog(t) >= yMin && symlog(t) <= yMax).map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(symlog(t))} y2={y(symlog(t))} className={t === 0 ? 'zero' : 'grid'} />
            <text x={M.l - 6} y={y(symlog(t)) + 3.5} className="tick" textAnchor="end">{t > 0 ? `+${t}` : t}</text>
          </g>
        ))}
        {xticks.map(t => <text key={t} x={x(t)} y={H - M.b + 14} className="tick" textAnchor="middle">{t}</text>)}
        <text x={(M.l + W - M.r) / 2} y={H - 4} className="axis" textAnchor="middle">vehicles / hour on the new road</text>
        <text x={M.l + 4} y={y(symlog(0)) - 5} className="note">better ↑</text>
        <text x={M.l + 4} y={y(symlog(0)) + 12} className="note">worse ↓</text>
        {pts.map(p => (
          <g key={p.key} onMouseEnter={() => { setHover(p); onHover(p.key) }} onMouseLeave={() => { setHover(null); onHover(null) }}
             onClick={() => onSelect(p.key)}
             className="dot">
            <circle cx={x(p.vph)} cy={y(p.ys)} r="10" fill="transparent" />{/* hit target larger than the mark */}
            <circle cx={x(p.vph)} cy={y(p.ys)} r={p.key === selKey ? 6 : 4.5}
                    fill={`#${scoreColor(p.score).getHexString()}`} className={p.key === selKey ? 'sel' : ''} />
          </g>
        ))}
        {selected && <text x={x(selected.vph) + 9} y={y(selected.ys) + 4} className="dlabel">{selected.name}</text>}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${(x(hover.vph) / W) * 100}%`, top: `${(y(hover.ys) / H) * 100}%` }}>
          <b>{hover.name}</b> · score {hover.score > 0 ? '+' : ''}{hover.score.toFixed(1)}<br />
          {Math.round(hover.vph)} veh/h · delay {hover.dT > 0 ? `${hover.dT.toFixed(1)} % lower` : `${(-hover.dT).toFixed(1)} % higher`}
          {hover.micro && <><br /><span className="muted">micro-validated</span></>}
        </div>
      )}
    </div>
  )
}
