import { useEffect, useState } from 'react'
import { AREA } from './data.js'

// Phase 7: run pipeline steps from the UI through the FastAPI server (backend/urban/api.py). One job at a time,
// because every SUMO step rewrites the shared route files. After an export, reload to see the new results.
const ago = t => t ? `${Math.round((Date.now() / 1000 - t) / 60)} min ago` : ''

export default function RunPanel() {
  const [steps, setSteps] = useState(null)
  const [jobs, setJobs] = useState([])
  const [step, setStep] = useState('export')
  const [args, setArgs] = useState('')
  const [err, setErr] = useState(null)

  const refresh = () => fetch('/api/jobs').then(r => r.json()).then(setJobs).catch(() => {})
  useEffect(() => {
    fetch('/api/steps').then(r => r.json()).then(s => setSteps(s.steps)).catch(() => setSteps(false))
    refresh()
    const t = setInterval(refresh, 2000)
    return () => clearInterval(t)
  }, [])

  if (steps === false) return (
    <p className="notice">No API server. Start it with
      <code>cd backend{'\n'}uv run uvicorn urban.api:app --port 8000</code></p>
  )
  if (!steps) return <p className="muted">Loading…</p>

  const running = jobs.find(j => j.status === 'running' || j.status === 'stopping')
  const start = async () => {
    setErr(null)
    const r = await fetch('/api/jobs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step, area: AREA, args: args.split(/\s+/).filter(Boolean) }),
    })
    if (!r.ok) setErr((await r.json()).detail)
    refresh()
  }
  const stop = id => fetch(`/api/jobs/${id}/stop`, { method: 'POST' }).then(refresh)
  const last = jobs[0]

  return (
    <div className="run">
      <label>Step
        <select value={step} onChange={e => setStep(e.target.value)}>
          {Object.keys(steps).map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <p className="muted">{steps[step]}</p>
      <label>Arguments <input value={args} onChange={e => setArgs(e.target.value)} placeholder="--workers 2" /></label>
      <div className="run-buttons">
        <button disabled={!!running} onClick={start}>Run on {AREA}</button>
        {running && <button onClick={() => stop(running.id)}>Stop job {running.id}</button>}
        {last?.status === 'done' && last.step === 'export' && <button onClick={() => location.reload()}>Reload results</button>}
      </div>
      {err && <p className="notice">{err}</p>}
      {jobs.map(j => (
        <details key={j.id} open={j.id === last?.id}>
          <summary>#{j.id} {j.step} {j.args.join(' ')} · <b>{j.status}</b>{j.returncode != null && ` (exit ${j.returncode})`} · {ago(j.started)}</summary>
          <pre className="run-log">{j.log || '…'}</pre>
        </details>
      ))}
    </div>
  )
}
