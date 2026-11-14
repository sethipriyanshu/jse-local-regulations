import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import SourceQueue from '../components/SourceQueue'
import AuditLog from '../components/admin/AuditLog'
import ChangeReview from '../components/admin/ChangeReview'
import DiscoveryPanel from '../components/admin/DiscoveryPanel'
import HealthPanel from '../components/admin/HealthPanel'
import RuleReview from '../components/admin/RuleReview'
import TeamsSettings from '../components/admin/TeamsSettings'
import { useAdmin } from '../lib/admin'
import { getOverview, type Overview } from '../lib/adminApi'
import { ApiError } from '../lib/api'
import { getQueue, type Queue } from '../lib/sources'

export default function AdminPage() {
  const { isAdmin, checked, logout } = useAdmin()

  if (!checked) return <div className="page" aria-busy="true" />
  if (!isAdmin) return <AdminLogin />
  return <AdminConsole onLogout={() => void logout()} />
}

type Tab = 'sources' | 'rules' | 'changes' | 'discovery' | 'health' | 'teams' | 'audit'

function AdminConsole({ onLogout }: { onLogout: () => void }) {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab | null) ?? 'sources'
  const setTab = (t: Tab) => setParams(t === 'sources' ? {} : { tab: t }, { replace: true })

  const [queue, setQueue] = useState<Queue | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState(false)
  const load = useCallback(() => {
    getQueue().then(setQueue).catch(() => setError(true))
    getOverview().then(setOverview).catch(() => {})
  }, [])
  useEffect(load, [load])

  const c = overview?.counts ?? queue?.counts
  const tabs: [Tab, string, number | undefined][] = [
    ['sources', 'Sources', c?.sources],
    ['rules', 'Rules', c?.rules],
    ['changes', 'Changes', c?.changes],
    ['discovery', 'AI discovery', undefined],
    ['health', 'Jobs & health', overview?.unhealthy_sources.length || undefined],
    ['teams', 'Teams', undefined],
    ['audit', 'Audit log', undefined],
  ]

  return (
    <div className="page page-wide">
      <p className="eyebrow">Admin</p>
      <div className="page-head">
        <h1 className="page-title">Review &amp; operations</h1>
        <button type="button" className="btn btn-secondary" onClick={onLogout}>
          Exit admin view
        </button>
      </div>

      <div className="stat-row">
        <Stat label="Sources to review" value={c?.sources} onClick={() => setTab('sources')} />
        <Stat label="Rules pending verification" value={c?.rules} onClick={() => setTab('rules')} />
        <Stat label="Detected changes" value={c?.changes} onClick={() => setTab('changes')} />
        <Stat label="Verified rules" value={overview?.counts.verified_rules} />
      </div>

      <nav className="admin-tabs" role="tablist">
        {tabs.map(([t, text, n]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t}
            className={`admin-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {text}
            {n ? <span className="tab-count">{n}</span> : null}
          </button>
        ))}
      </nav>

      {tab === 'sources' && (
        <>
          <p className="page-sub">
            Approve sources to start monitoring them; the AI extracts their MEP rules as pending items
            for the Rules tab. AI-suggested sources are listed first, best match first.
          </p>
          {error && <p className="form-error">Could not load the queue.</p>}
          {!queue && !error && <div className="skeleton skeleton-block" />}
          {queue && <SourceQueue sources={queue.sources} onChanged={load} />}
        </>
      )}
      {tab === 'rules' && <RuleReview onChanged={load} />}
      {tab === 'changes' && <ChangeReview onChanged={load} />}
      {tab === 'discovery' && <DiscoveryPanel onFinished={load} />}
      {tab === 'health' && <HealthPanel overview={overview} />}
      {tab === 'teams' && <TeamsSettings />}
      {tab === 'audit' && <AuditLog />}
    </div>
  )
}

function Stat({ label, value, onClick }: { label: string; value: number | undefined; onClick?: () => void }) {
  const body = (
    <>
      <span className="stat-value">{value ?? '–'}</span>
      <span className="stat-label">{label}</span>
    </>
  )
  return onClick ? (
    <button type="button" className="card stat stat-btn" onClick={onClick}>{body}</button>
  ) : (
    <div className="card stat">{body}</div>
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
