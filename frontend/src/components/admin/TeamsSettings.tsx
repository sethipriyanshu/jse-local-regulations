import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addTeamsChannel,
  deleteTeamsChannel,
  getTeamsChannels,
  testTeamsChannel,
  type TeamsChannel,
} from '../../lib/adminApi'
import { ApiError } from '../../lib/api'
import { METROS } from '../../lib/metros'

/** Teams channels (PLAN.md G1–G4, TEAMS-4). */
export default function TeamsSettings() {
  const [channels, setChannels] = useState<TeamsChannel[] | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => {
    getTeamsChannels().then(setChannels).catch(() => setChannels([]))
  }, [])
  useEffect(load, [load])

  return (
    <div className="teams">
      <div className="card discovery-card">
        <h3>How to get a webhook URL</h3>
        <ol className="steps">
          <li>In Teams, open the channel → <strong>⋯</strong> → <strong>Workflows</strong>.</li>
          <li>Choose <strong>“Post to a channel when a webhook request is received”</strong> and finish the wizard.</li>
          <li>Copy the URL it gives you and paste it below.</li>
        </ol>
        <p className="muted-note">
          The daily digest lists MEP-relevant changes, broken sources and the review backlog. Alert
          channels also get job failures and new user submissions. A channel tied to a metro only
          hears about that metro.
        </p>
      </div>

      {msg && <div className="inline-toast" role="status">{msg}</div>}

      <h3 className="section-title">Channels</h3>
      {!channels ? <div className="skeleton skeleton-line" /> : channels.length === 0 ? (
        <p className="queue-empty">No channels yet.</p>
      ) : (
        <ul className="queue-list">
          {channels.map((c) => (
            <li key={c.id} className="queue-item card">
              <div className="queue-main">
                <strong>{c.name}</strong>
                <span className="source-sub">
                  {c.metro ? METROS.find((m) => m.key === c.metro)?.label ?? c.metro : 'All metros'}
                  {' · '}{[c.sends_digest && 'daily digest', c.sends_alerts && 'alerts'].filter(Boolean).join(' + ')}
                  {' · '}<code>{c.webhook}</code>
                </span>
              </div>
              <div className="queue-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() =>
                  testTeamsChannel(c.id).then(() => setMsg(`Test message sent to ${c.name}.`))
                    .catch((e) => setMsg(e instanceof ApiError ? e.message : 'Test failed'))}>
                  Send test
                </button>
                <button type="button" className="link-btn small" onClick={() =>
                  deleteTeamsChannel(c.id).then(load)}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <AddChannel onAdded={load} />
    </div>
  )
}

function AddChannel({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [metro, setMetro] = useState('')
  const [digest, setDigest] = useState(true)
  const [alerts, setAlerts] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await addTeamsChannel({ name, webhook_url: url, metro: metro || null, sends_digest: digest, sends_alerts: alerts })
      setName('')
      setUrl('')
      onAdded()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add the channel')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card form-stack add-channel" onSubmit={submit}>
      <h3>Add a channel</h3>
      <div className="field-row">
        <label className="field"><span>Name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="MEP regs – Atlanta" /></label>
        <label className="field"><span>Metro</span>
          <select value={metro} onChange={(e) => setMetro(e.target.value)}>
            <option value="">All metros</option>
            {METROS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select></label>
      </div>
      <label className="field"><span>Workflows webhook URL</span>
        <input required type="url" value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://….logic.azure.com/workflows/…" autoComplete="off" /></label>
      <div className="action-row">
        <label className="check"><input type="checkbox" checked={digest} onChange={(e) => setDigest(e.target.checked)} /> Daily digest</label>
        <label className="check"><input type="checkbox" checked={alerts} onChange={(e) => setAlerts(e.target.checked)} /> Alerts &amp; submissions</label>
      </div>
      {error && <p className="form-error">{error}</p>}
      <div><button type="submit" className="btn btn-primary btn-sm" disabled={busy}>Add channel</button></div>
    </form>
  )
}
