import { useEffect, useMemo, useRef, useState } from 'react'
import { CityScene } from './scene.js'
import { AREA, areaName, loadAll, loadComparison } from './data.js'
import ResultsChart from './ResultsChart.jsx'
import { CHANGE_LEGEND, NO_TRAFFIC, SCORE_LEGEND, SPEED_LEGEND, changeColor, cssGradient, scoreColor, speedColor } from './colors.js'

// Defaults = WEIGHTS in backend/urban/evaluate.py, so the default ranking equals the backend's.
// S = wdT*dT + wdQ*dQ + wdC*dC - wL*L - wP*P   (idea.md §7); the sliders re-rank live in the browser.
const DEFAULT_W = { dT: 1, dQ: 0.5, dC: 0.01, L: 0.002, P: 0.25 }
const SIGN = { dT: 1, dQ: 1, dC: 1, L: -1, P: -1 }
const SLIDERS = [
  ['dT', 'Delay saved (w₁)', 3, 0.1], ['dQ', 'Queueing saved (w₂)', 2, 0.05], ['dC', 'Connectivity (w₃)', 0.05, 0.001],
  ['L', 'Length cost (w₄)', 0.01, 0.0005], ['P', 'Demolition / crossings (w₅)', 1, 0.05],
]
const TERMS = { dT: 'Delay saved', dQ: 'Queueing saved', dC: 'Connectivity', L: 'Length cost', P: 'Demolition / crossings' }
const scoreOf = (r, w) => r ? Object.keys(SIGN).reduce((s, k) => s + SIGN[k] * w[k] * r[k], 0) : null

const LAYERS = [
  ['roads', 'Roads (traffic)', true], ['roadLabels', 'Road names', true], ['buildings', 'Buildings', true],
  ['candidates', 'Candidate roads', true], ['construction', 'Metro worksites', true],
  ['obstacles', 'Lakes, parks, no-build zones', true], ['studyBox', 'Study box', true],
  ['feasible', 'Feasible, not selected', false], ['rejected', 'Rejected pairs', false],
]

const fmt = (v, d = 1) => v == null || Number.isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })
const signed = (v, d = 1) => v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v, d)}`
const label = c => `Candidate c${String(c.meso?.cand ?? c.micro?.cand ?? '?').padStart(2, '0')}`
const short = c => label(c).replace('Candidate ', '')
// the most trustworthy result for a candidate: the microsim check where it exists, else the meso screen
const best = c => c.micro ?? c.meso
// repeated-run result for the candidate as evaluated (the first, default variant), if urban.noise ran it
const seedRun = c => c.noise?.[0]
const seedTag = n => n.verdict !== 'real effect' ? ['', 'no effect'] : n.dT > 0 ? ['ok', 'better'] : ['fail', 'worse']

export default function App() {
  const host = useRef(null), sceneRef = useRef(null), statsRef = useRef(null)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [layers, setLayers] = useState(Object.fromEntries(LAYERS.map(([k, , v]) => [k, v])))
  const [selKey, setSelKey] = useState(null)
  const [mode, setMode] = useState('baseline')        // baseline | after | change
  const [simPref, setSimPref] = useState('meso')
  const [cmp, setCmp] = useState(null)
  const [hover, setHover] = useState(null)
  const [road, setRoad] = useState(null)
  const [tab, setTab] = useState('ranking')
  const [w, setW] = useState(DEFAULT_W)

  const byKey = useMemo(() => new Map((data?.selected || []).map(c => [c.key, c])), [data])
  const sel = selKey ? byKey.get(selKey) : null
  const sim = simPref === 'micro' && sel?.micro ? 'micro' : 'meso'
  const rec = sel?.[sim]
  const custom = Object.keys(DEFAULT_W).some(k => w[k] !== DEFAULT_W[k])

  // ranking: validated candidates by their micro score, the rest by meso, all with the current weights
  const ranked = useMemo(() => (data?.selected || []).filter(c => c.meso)
    .map(c => ({ ...c, score: scoreOf(best(c), w), mesoScore: scoreOf(c.meso, w), microScore: scoreOf(c.micro, w) }))
    .sort((a, b) => b.score - a.score)
    .map((c, i) => ({ ...c, rank: i + 1 })), [data, w])
  const rankOf = useMemo(() => new Map(ranked.map(c => [c.key, c])), [ranked])

  // scene + data, once
  useEffect(() => {
    const s = new CityScene(host.current, {
      onPick: hit => {
        if (hit?.kind === 'candidate') { setSelKey(hit.key); setRoad(null) }
        else if (hit?.kind === 'road') setRoad(hit.props)
        else setRoad(null)
      },
      onHover: (hit, x, y) => {
        setHover(hit ? { hit, x, y } : null)
        s.setHovered(hit?.kind === 'candidate' ? hit.key : null)
      },
    })
    sceneRef.current = s
    loadAll().then(d => {
      s.build(d, d.bbox)
      if (d.live) s.setLive(d.live.points, p => speedColor(p.ratio))
      setData(d)
      if (!d.hasSim && d.live) setMode('live')
      // deep link for demos: ?cand=22&view=change&sim=micro&tab=chart
      const q = new URLSearchParams(location.search)
      const hit = q.has('cand') && d.selected.find(c => (c.meso ?? c.micro)?.cand === Number(q.get('cand')))
      if (hit) setSelKey(hit.key)
      if (['after', 'change'].includes(q.get('view')) || (q.get('view') === 'live' && d.live)) setMode(q.get('view'))
      if (q.get('sim') === 'micro') setSimPref('micro')
      if (q.get('tab') === 'chart') setTab('chart')
    }).catch(e => setError(String(e.message || e)))
    return () => s.dispose()
  }, [])

  // map colours follow the current weights
  useEffect(() => {
    if (!data) return
    sceneRef.current?.setCandidateColors(k => scoreColor(rankOf.get(k)?.score))
  }, [data, rankOf])

  useEffect(() => { for (const [k, v] of Object.entries(layers)) sceneRef.current?.setLayerVisible(k, v) }, [layers, data])

  useEffect(() => {
    sceneRef.current?.setSelected(selKey)
    if (selKey) sceneRef.current?.focus(selKey)
  }, [selKey, data])

  useEffect(() => {
    setCmp(null)
    if (!sel) { if (data) setMode('baseline'); return }
    let live = true
    loadComparison(sel.meso?.cand ?? sel.micro?.cand, sim).then(c => live && setCmp(c)).catch(() => live && setCmp({ missing: true }))
    return () => { live = false }
  }, [selKey, sim])

  // road colours for the current view
  useEffect(() => {
    const s = sceneRef.current
    if (!data || !s?.roadMesh) return
    s.setLayerVisible('live', mode === 'live')
    const ok = cmp && !cmp.missing
    if (mode === 'live') {   // real traffic: dim the simulated colours, the TomTom segments carry the data
      statsRef.current = { kind: 'speed', stats: {} }
      s.setRoadColors(() => NO_TRAFFIC)
    } else if (mode === 'change' && ok) {
      statsRef.current = { kind: 'change', before: cmp.before, after: cmp.after }
      s.setRoadColors(p => {
        const b = cmp.before[p.id]?.time_loss || 0, a = cmp.after[p.id]?.time_loss || 0
        return a === 0 && b === 0 ? NO_TRAFFIC : changeColor(a - b)
      })
    } else {
      const stats = mode === 'after' && ok ? cmp.after : ok ? cmp.before : data.edgeStats
      statsRef.current = { kind: 'speed', stats }
      s.setRoadColors(p => stats[p.id] ? speedColor(stats[p.id].speed_rel) : NO_TRAFFIC)
    }
  }, [data, cmp, mode])

  const pending = (data?.selected || []).filter(c => !c.meso)
  const improving = ranked.filter(c => c.mesoScore > 0).length
  const validated = ranked.filter(c => c.micro)
  const legend = mode === 'change' && cmp && !cmp.missing ? CHANGE_LEGEND : SPEED_LEGEND
  const viewLabel = mode === 'live' ? `Real traffic from TomTom, ${data?.live?.fetched_at?.replace('T', ' ')} IST`
    : !sel ? 'Baseline traffic (microsim)'
    : mode === 'baseline' ? `Before: baseline (${sim})` : mode === 'after' ? `After: with ${label(sel)} (${sim})` : `Change with ${label(sel)} (${sim})`
  const chartRows = ranked.map(c => ({ key: c.key, name: short(c), score: c.score, vph: best(c).cand_vph, dT: best(c).dT, micro: !!c.micro }))
  const select = k => { setSelKey(k); setRoad(null) }
  // list rows and chart dots light up the road on the map, with a floating label
  const hoverCand = k => {
    const c = k && rankOf.get(k)
    sceneRef.current?.setHovered(k, c ? `${short(c)} · ${signed(c.score)}` : null)
  }

  return (
    <div className="app">
      <div className="viewport" ref={host} />

      <aside className="panel left">
        <header>
          <div className="brand"><span className="mark" />Urban infrastructure planner</div>
          <h1>{areaName(AREA)} Road Planner</h1>
          <p className="sub">Simulation-based evaluation of new road connections, {areaName(AREA)}, Bengaluru</p>
        </header>
        {error && <div className="error">Could not load data: {error}<br />Run <code>uv run python -m urban.export {AREA}</code> in <code>backend/</code>.</div>}
        {!data && !error && <div className="muted">Loading city…</div>}
        {data && !ranked.length && (
          <div className="notice">
            <b>Not simulated yet.</b> The map and roads are real; traffic and candidate roads appear once the pipeline
            has run for this area:
            <code>{['sim', 'candidates', 'evaluate', 'export'].map(m => `uv run python -m urban.${m} ${AREA}`).join('\n')}</code>
          </div>
        )}
        {data && ranked.length > 0 && <>
          <div className="summary">
            <div><b>{ranked.length}<span className="of">/{data.selected.length}</span></b><span>candidates simulated</span></div>
            <div><b className={improving ? 'good' : ''}>{improving}</b><span>improve in fast screen</span></div>
            <div><b className={validated.some(c => c.microScore > 0) ? 'good' : ''}>{validated.filter(c => c.microScore > 0).length}
              <span className="of">/{validated.length}</span></b><span>pass micro check</span></div>
          </div>
          <div className="tabs">
            <button className={tab === 'ranking' ? 'on' : ''} onClick={() => setTab('ranking')}>Ranking</button>
            <button className={tab === 'chart' ? 'on' : ''} onClick={() => setTab('chart')}>Chart</button>
          </div>
          {tab === 'chart' && <ResultsChart rows={chartRows} selKey={selKey} onSelect={select} onHover={hoverCand} />}
          {tab === 'ranking' && <>
            <p className="muted small rank-note">Micro score where validated, otherwise the fast meso screen; tags show repeated-run results.{custom && ' Custom weights.'}</p>
            <ol className="ranking">
              {ranked.map(c => (
                <li key={c.key} onClick={() => select(c.key)}
                    className={[c.key === selKey && 'active', hover?.hit?.key === c.key && 'hovered'].filter(Boolean).join(' ')}
                    onMouseEnter={() => hoverCand(c.key)} onMouseLeave={() => hoverCand(null)}
                    title={c.micro ? `meso ${signed(c.mesoScore)} · micro ${signed(c.microScore)}` : `meso ${signed(c.mesoScore)}`}>
                  <span className="rank">{c.rank}</span>
                  <span className="name">{short(c)}{seedRun(c)
                    ? <em className={`tag ${seedTag(seedRun(c))[0]}`} title={`${seedRun(c).n} seeds, ${seedRun(c).sim}sim`}>
                        {seedRun(c).n} seeds: {seedTag(seedRun(c))[1]}</em>
                    : c.micro && (c.microScore > 0
                    ? <em className="tag ok">micro ✓</em> : <em className="tag fail">micro ✗</em>)}</span>
                  <span className="sbar"><span style={{
                    width: `${Math.min(100, 100 * Math.log10(1 + Math.abs(c.score)) / Math.log10(301))}%`,
                    background: `#${scoreColor(c.score).getHexString()}` }} /></span>
                  <span className={`score ${c.score > 0 ? 'good' : 'bad'}`}>{signed(c.score)}</span>
                </li>
              ))}
              {pending.map(c => <li key={c.key} className="pending"><span className="rank">·</span><span className="name">{c.props.u} → {c.props.v}</span><span className="muted">not run</span></li>)}
            </ol>
          </>}
        </>}
      </aside>

      <aside className="panel right">
        <section>
          <h2>View</h2>
          <div className="seg">
            {[['baseline', 'Before'], ['after', 'After'], ['change', 'Change']].map(([k, t]) => (
              <button key={k} disabled={k !== 'baseline' && !sel} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{t}</button>
            ))}
          </div>
          {data?.live && (
            <button className={`live-btn ${mode === 'live' ? 'on' : ''}`} onClick={() => setMode(mode === 'live' ? 'baseline' : 'live')}>
              <span className="dot" /> Real traffic (TomTom)
            </button>
          )}
          {mode === 'live' && data?.live && <LiveSummary live={data.live} sim={data.edgeStats} />}
          {sel?.micro && (
            <div className="seg small">
              {['meso', 'micro'].map(k => <button key={k} className={sim === k ? 'on' : ''} onClick={() => setSimPref(k)}>{k}sim</button>)}
            </div>
          )}
          <p className="muted small">{sel || mode === 'live' ? viewLabel : 'Select a candidate road to compare before and after.'}</p>
          {cmp?.missing && <p className="error small">No per-road stats for this run. Re-run the export.</p>}
          <Legend {...legend} />
          {layers.candidates && <Legend {...SCORE_LEGEND} />}
        </section>
        <section>
          <details>
            <summary><h2>Scoring weights {custom && <span className="tag">custom</span>}</h2></summary>
            <p className="muted small">S = w₁ΔT + w₂ΔQ + w₃ΔC − w₄L − w₅P. Drag to see how the ranking depends on priorities.</p>
            {SLIDERS.map(([k, t, max, step]) => (
              <label key={k} className="slider">
                <span className="row"><span>{t}</span><span className="mono">{w[k]}</span></span>
                <input type="range" min="0" max={max} step={step} value={w[k]}
                       onChange={e => setW(v => ({ ...v, [k]: Number(e.target.value) }))} />
              </label>
            ))}
            <button className="ghost" disabled={!custom} onClick={() => setW(DEFAULT_W)}>Reset to backend weights</button>
          </details>
        </section>
        <section>
          <details open>
            <summary><h2>Layers</h2></summary>
            {LAYERS.map(([k, t]) => (
              <label key={k} className="check">
                <input type="checkbox" checked={layers[k]} onChange={e => setLayers(l => ({ ...l, [k]: e.target.checked }))} /> {t}
              </label>
            ))}
            <p className="muted small">Building heights are illustrative; OSM has no height data for this area.</p>
          </details>
        </section>
      </aside>

      {sel && <CandidateCard c={sel} sim={sim} rec={rec} base={data.baseline[sim]} w={w} rank={rankOf.get(selKey)?.rank}
                             onClose={() => setSelKey(null)} />}
      {road && <RoadCard p={road} stats={statsRef.current} docked={!!sel} onClose={() => setRoad(null)} />}
      {hover && <Tooltip {...hover} byKey={rankOf} stats={statsRef.current} />}
    </div>
  )
}

// Real (TomTom) vs simulated speeds on the same roads: the honest check of how realistic the simulation is.
function LiveSummary({ live, sim }) {
  const pts = live.points.filter(p => p.ratio != null)
  const both = pts.filter(p => sim[p.edge])
  const mean = xs => xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length)
  const real = mean(pts.map(p => p.ratio)), realBoth = mean(both.map(p => p.ratio)), simBoth = mean(both.map(p => sim[p.edge].speed_rel))
  const worst = [...pts].sort((a, b) => a.ratio - b.ratio).slice(0, 5)
  return (
    <div className="live-sum">
      <table className="kv">
        <tbody>
          <tr><th>Road segments measured</th><td>{pts.length}</td></tr>
          <tr><th>Real speed, all measured roads</th><td><b>{fmt(100 * real, 0)} %</b> of free flow</td></tr>
          {both.length > 0 && <>
            <tr><th>Same roads: real</th><td><b>{fmt(100 * realBoth, 0)} %</b></td></tr>
            <tr><th>Same roads: simulation</th><td><b>{fmt(100 * simBoth, 0)} %</b></td></tr>
          </>}
        </tbody>
      </table>
      {both.length > 0 && (
        <p className="small verdict">
          {Math.abs(simBoth - realBoth) < 0.08 ? 'The simulation matches real speeds closely on these roads.'
            : simBoth > realBoth ? `The simulation runs faster than reality here (${fmt(100 * (simBoth - realBoth), 0)} points), so real congestion is worse than modelled.`
            : `The simulation is slower than reality here (${fmt(100 * (realBoth - simBoth), 0)} points), so it overstates congestion.`}
        </p>
      )}
      <h3>Slowest right now</h3>
      <ol className="worst">
        {worst.map((p, i) => <li key={i}><span>{fmt(p.current_kmh, 0)} km/h</span><span className="muted"> of {fmt(p.free_flow_kmh, 0)} km/h</span></li>)}
      </ol>
      <p className="muted small">{live.source}. A single snapshot: speeds change through the day.</p>
    </div>
  )
}

function Legend({ title, stops, left, right }) {
  return (
    <div className="legend">
      <div className="muted small">{title}</div>
      <div className="bar" style={{ background: cssGradient(stops) }} />
      <div className="ends small"><span>{left}</span><span>{right}</span></div>
    </div>
  )
}

function CandidateCard({ c, sim, rec, base, w, rank, onClose }) {
  const p = c.props
  const s = scoreOf(rec, w)
  const contrib = rec ? Object.keys(SIGN).map(k => [k, SIGN[k] * w[k] * rec[k]]) : []
  const maxAbs = Math.max(1, ...contrib.map(([, v]) => Math.abs(v)))
  const microS = scoreOf(c.micro, w)
  return (
    <div className="card">
      <button className="close" onClick={onClose}>×</button>
      <h2>{label(c)} <span className="muted">rank {rank ?? '—'} · {sim}sim</span></h2>
      {!rec ? <p className="muted">Not simulated yet.</p> : <>
        <div className={`big ${s > 0 ? 'good' : 'bad'}`}>{signed(s, 2)} <span>score</span></div>
        {sim === 'meso' && c.micro && (microS > 0) !== (s > 0) && (
          <div className={`banner ${microS > 0 ? 'ok' : 'fail'}`}>
            {microS > 0 ? 'Confirmed' : 'Not confirmed'} by the detailed microsimulation: score {signed(microS, 2)},
            delay {c.micro.dT > 0 ? `${fmt(c.micro.dT)} % lower` : `${fmt(-c.micro.dT)} % higher`}
            {seedRun(c) ? ' in a single run; see the repeated runs below.' : '. Switch to microsim above for details.'}
          </div>
        )}
        <p className="verdict">{seedRun(c) ? seedVerdict(c.noise) : verdict(best(c), scoreOf(best(c), w), !!c.micro)}</p>
        {c.noise.length > 0 && <SeedRuns runs={c.noise} />}
        <table className="kv">
          <tbody>
            <tr><th>Mean delay per trip</th><td>{fmt(base?.mean_time_loss)} s → <b>{fmt(rec.mean_time_loss)} s</b></td></tr>
            <tr><th>Queueing in study box</th><td>{fmt(base?.box_waiting, 0)} s → <b>{fmt(rec.box_waiting, 0)} s</b></td></tr>
            <tr><th>Traffic on new road</th><td><b>{fmt(rec.cand_vph, 0)}</b> veh/h</td></tr>
            <tr><th>Teleports (stuck vehicles)</th><td>{fmt(base?.teleports, 0)} → {fmt(rec.teleports, 0)}</td></tr>
          </tbody>
        </table>
        <h3>Score breakdown</h3>
        <div className="contrib">
          {contrib.map(([k, v]) => (
            <div key={k} className="row">
              <span className="k">{TERMS[k]}</span>
              <span className="track"><span className={`fill ${v >= 0 ? 'pos' : 'neg'}`} style={{ width: `${50 * Math.abs(v) / maxAbs}%`, [v >= 0 ? 'left' : 'right']: '50%' }} /></span>
              <span className="v">{signed(v, 2)}</span>
            </div>
          ))}
        </div>
        <p className="muted small">ΔT {signed(rec.dT)} % delay · ΔQ {signed(rec.dQ)} % queueing · ΔC {fmt(rec.dC)} % detour removed</p>
      </>}
      <h3>Construction</h3>
      <table className="kv">
        <tbody>
          <tr><th>Length</th><td>{fmt(p.length_m, 0)} m <span className="muted">(today {fmt(p.net_dist, 0)} m by road, {fmt(p.detour)}× detour)</span></td></tr>
          <tr><th>Buildings demolished</th><td>{p.buildings_hit}</td></tr>
          <tr><th>Road crossings (grade separated)</th><td>{p.road_crossings}</td></tr>
          <tr><th>Metro worksite crossings</th><td>{p.worksite_crossings}</td></tr>
          <tr><th>Junctions</th><td className="mono">{p.u} → {p.v}</td></tr>
        </tbody>
      </table>
    </div>
  )
}

const delayText = dT => dT > 0 ? `${fmt(dT)} % lower` : `${fmt(-dT)} % higher`

// Over several seeds, so it outranks any single run. runs[0] = the road as evaluated; later = stronger variants.
function seedVerdict(runs) {
  const [n, ...bigger] = runs
  const worse = bigger.filter(b => b.verdict === 'real effect' && b.dT < 0)
  const braess = worse.length ? ` Built bigger (${worse[0].label}), it reliably makes traffic worse: delay ${delayText(worse[0].dT)} (Braess paradox).` : ''
  if (n.verdict !== 'real effect')
    return `No measurable effect: over ${n.n} seeds the change in delay (${signed(-n.dT)} %) is within the simulation's own run-to-run variation.${braess}`
  if (n.dT > 0) return `Reliably reduces delay over ${n.n} seeds: ${delayText(n.dT)} on average.${braess}`
  return `Reliably makes traffic worse over ${n.n} seeds: delay ${delayText(n.dT)} on average` +
    (n.cand_vph > 150 ? `. The shortcut draws ${fmt(n.cand_vph, 0)} veh/h onto it and creates a new jam (Braess paradox).` : '.') + braess
}

function SeedRuns({ runs }) {
  const b = runs[0].baseline
  return <>
    <h3>Repeated runs <span className="muted">({runs[0].n} seeds, {runs[0].sim}sim)</span></h3>
    <table className="kv seeds">
      <tbody>
        {runs.map(n => {
          const [cls, txt] = seedTag(n)
          return (
            <tr key={n.id}>
              <th>{n.label}</th>
              <td><b className={cls === 'ok' ? 'good' : cls === 'fail' ? 'bad' : ''}>delay {signed(-n.dT)} %</b>
                <span className="muted"> ± {fmt(n.dT_sd)}</span> <em className={`tag ${cls}`}>{txt}</em>
                <div className="muted small">range {signed(-n.dT_max)} to {signed(-n.dT_min)} % · {fmt(n.cand_vph, 0)} veh/h on it</div></td>
            </tr>
          )
        })}
      </tbody>
    </table>
    <p className="muted small">Each seed changes only driver randomness; the demand is the same. With no new road the baseline
      itself varies ±{fmt(100 * b.sd / b.mean_time_loss)} % ({fmt(b.min)}–{fmt(b.max)} s delay per trip), so a change counts as
      real only if its average is more than 2 standard errors from zero. Positive = more delay.</p>
  </>
}

function verdict(r, s, micro) {
  if (s > 0 && r.cand_vph < 100) return 'Small gain, but few vehicles use it, so it may be within simulation noise.'
  if (s > 0) return micro ? 'Improves the network in the detailed microsimulation: a strong candidate.'
                          : 'Improves the network in the fast screen; not yet checked by microsimulation.'
  if (micro && r.cand_vph < 100) return 'Worse in the detailed microsimulation, though few vehicles use it, so part of the change is simulation noise.'
  if (r.cand_vph > 500) return 'Makes traffic worse: the shortcut attracts heavy traffic and creates a new jam (Braess paradox).'
  return 'Does not improve the network.'
}

function RoadCard({ p, stats, docked, onClose }) {
  const rows = [['Average speed', s => `${fmt(s.speed * 3.6, 0)} km/h`], ['Share of limit', s => `${fmt(s.speed_rel * 100, 0)} %`],
                ['Vehicles entered', s => fmt(s.entered, 0)], ['Total delay', s => `${fmt(s.time_loss / 3600)} veh-h`]]
  const before = stats?.kind === 'change' ? stats.before[p.id] : null, after = stats?.kind === 'change' ? stats.after[p.id] : null
  const one = stats?.kind === 'speed' ? stats.stats[p.id] : null
  return (
    <div className={`card road ${docked ? 'docked' : ''}`}>
      <button className="close" onClick={onClose}>×</button>
      <h2>{p.name || 'Unnamed road'}</h2>
      <p className="muted small">{(p.type || '').replace('highway.', '')} · {p.lanes} lane{p.lanes > 1 ? 's' : ''} · limit {fmt(p.speed * 3.6, 0)} km/h · {fmt(p.length, 0)} m</p>
      {stats?.kind === 'change' ? (
        <table className="kv cmp">
          <thead><tr><th /><td className="muted">before</td><td className="muted">after</td></tr></thead>
          <tbody>{rows.map(([t, f]) => <tr key={t}><th>{t}</th><td>{before ? f(before) : '—'}</td><td><b>{after ? f(after) : '—'}</b></td></tr>)}</tbody>
        </table>
      ) : one ? (
        <table className="kv"><tbody>{rows.map(([t, f]) => <tr key={t}><th>{t}</th><td>{f(one)}</td></tr>)}</tbody></table>
      ) : <p className="muted">No traffic on this road in the current view.</p>}
      <p className="muted small mono">SUMO edge {p.id}</p>
    </div>
  )
}

function Tooltip({ hit, x, y, byKey, stats }) {
  let body
  if (hit.kind === 'candidate') {
    const c = byKey.get(hit.key)
    body = <><b>{c ? label(c) : 'Candidate'}</b><br />score {signed(c?.score, 2)} · {fmt(c?.props.length_m, 0)} m</>
  } else {
    const p = hit.props
    let line = 'no traffic'
    if (stats?.kind === 'speed' && stats.stats[p.id]) line = `${fmt(stats.stats[p.id].speed_rel * 100, 0)} % of limit`
    if (stats?.kind === 'change') {
      const d = (stats.after[p.id]?.time_loss || 0) - (stats.before[p.id]?.time_loss || 0)
      line = `delay ${d > 0 ? '+' : ''}${fmt(d / 3600)} veh-h`
    }
    body = <><b>{p.name || 'Unnamed road'}</b><br />{line}</>
  }
  return <div className="tooltip" style={{ left: x + 14, top: y + 14 }}>{body}</div>
}
