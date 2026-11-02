import { useEffect, useState } from 'react'
import { api, type Health } from '../lib/api'
import { METROS } from '../lib/metros'

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)

  useEffect(() => {
    api<Health>('/health')
      .then(setHealth)
      .catch(() => setHealthError(true))
  }, [])

  return (
    <div className="home">
      <section className="map-stage" aria-label="Map">
        <div className="map-placeholder">
          <p className="eyebrow">Coming next</p>
          <h2>Interactive county map</h2>
          <p>Select a county or search an address to see its MEP regulations.</p>
        </div>
      </section>

      <aside className="side-panel">
        <p className="eyebrow">Pilot metros</p>
        <h1 className="panel-title">Where we have data</h1>
        <p className="panel-sub">
          Pick a metro to jump to it on the map. Coverage grows as sources are approved.
        </p>
        <div className="chip-row">
          {METROS.map((m) => (
            <button key={m.key} type="button" className="chip" disabled title="Map arrives in week 2">
              {m.label}
            </button>
          ))}
        </div>

        <div className="status-card card">
          <span className={`dot ${health?.status === 'ok' ? 'dot-ok' : healthError ? 'dot-bad' : 'dot-warn'}`} />
          <div>
            <strong>System status</strong>
            <p>
              {healthError && 'API unreachable'}
              {!healthError && !health && 'Checking…'}
              {health && `API ${health.status} · database ${health.db} · ${health.env}`}
            </p>
          </div>
        </div>
      </aside>
    </div>
  )
}
