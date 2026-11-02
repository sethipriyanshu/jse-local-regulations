import { useState, type FormEvent } from 'react'
import { useAdmin } from '../lib/admin'
import { ApiError } from '../lib/api'

export default function AdminPage() {
  const { isAdmin, checked, logout } = useAdmin()

  if (!checked) return <div className="page" aria-busy="true" />
  if (!isAdmin) return <AdminLogin />

  return (
    <div className="page">
      <p className="eyebrow">Admin</p>
      <div className="page-head">
        <h1 className="page-title">Admin console</h1>
        <button type="button" className="btn btn-secondary" onClick={() => void logout()}>
          Exit admin view
        </button>
      </div>
      <p className="page-sub">
        Review submissions, approve sources, and watch the daily monitor. These sections fill in as
        the pipeline is built.
      </p>
      <div className="tile-grid">
        {[
          ['Review queue', 'Submissions, AI-extracted rules, and detected changes'],
          ['Discover sources', 'AI search for official sources, per jurisdiction or in bulk'],
          ['Jobs & health', 'Daily monitor runs, broken sources, AI spend'],
          ['Teams', 'Channels that receive the daily digest and alerts'],
        ].map(([title, desc]) => (
          <div key={title} className="card tile tile-disabled">
            <h3>{title}</h3>
            <p>{desc}</p>
          </div>
        ))}
      </div>
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
