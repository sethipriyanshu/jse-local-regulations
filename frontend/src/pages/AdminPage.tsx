import { useCallback, useEffect, useState, type FormEvent } from 'react'
import SourceQueue from '../components/SourceQueue'
import { useAdmin } from '../lib/admin'
import { ApiError } from '../lib/api'
import { getQueue, type Queue } from '../lib/sources'

export default function AdminPage() {
  const { isAdmin, checked, logout } = useAdmin()

  if (!checked) return <div className="page" aria-busy="true" />
  if (!isAdmin) return <AdminLogin />
  return <AdminConsole onLogout={() => void logout()} />
}

function AdminConsole({ onLogout }: { onLogout: () => void }) {
  const [queue, setQueue] = useState<Queue | null>(null)
  const [error, setError] = useState(false)
  const load = useCallback(() => {
    getQueue().then(setQueue).catch(() => setError(true))
  }, [])
  useEffect(load, [load])

  return (
    <div className="page">
      <p className="eyebrow">Admin</p>
      <div className="page-head">
        <h1 className="page-title">Review queue</h1>
        <button type="button" className="btn btn-secondary" onClick={onLogout}>
          Exit admin view
        </button>
      </div>
      <p className="page-sub">
        Approve sources to start monitoring them; the AI extracts their MEP rules as pending items.
      </p>

      <div className="stat-row">
        <Stat label="Sources to review" value={queue?.counts.sources} />
        <Stat label="Rules pending verification" value={queue?.counts.rules} hint="Review UI arrives in week 5" />
        <Stat label="Detected changes" value={queue?.counts.changes} hint="Daily monitor arrives in week 7" />
      </div>

      <h2 className="section-title">Submitted sources</h2>
      {error && <p className="form-error">Could not load the queue.</p>}
      {!queue && !error && <div className="skeleton skeleton-block" />}
      {queue && <SourceQueue sources={queue.sources} onChanged={load} />}
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: number | undefined; hint?: string }) {
  return (
    <div className="card stat" title={hint}>
      <span className="stat-value">{value ?? '–'}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

function AdminLogin() {
  const { login } = useAdmin()
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(passcode)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page page-narrow">
      <p className="eyebrow">Admin</p>
      <h1 className="page-title">Enter admin passcode</h1>
      <p className="page-sub">The admin view lets you approve sources, rules, and changes.</p>
      <form className="card form-card" onSubmit={onSubmit}>
        <label htmlFor="passcode">Passcode</label>
        <input
          id="passcode"
          type="password"
          autoComplete="current-password"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          autoFocus
        />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy || !passcode}>
          {busy ? 'Checking…' : 'Enter admin view'}
        </button>
      </form>
    </div>
  )
}
