import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { approveSource, displayUrl, rejectSource, type Source } from '../lib/sources'

type Props = { sources: Source[]; onChanged: () => void }

export default function SourceQueue({ sources, onChanged }: Props) {
  if (sources.length === 0) {
    return <p className="queue-empty">No sources waiting for review. Nice.</p>
  }
  return (
    <ul className="queue-list">
      {sources.map((s) => <QueueItem key={s.id} s={s} onChanged={onChanged} />)}
    </ul>
  )
}

function QueueItem({ s, onChanged }: { s: Source; onChanged: () => void }) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
      onChanged()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Action failed')
      setBusy(false)
    }
  }

  return (
    <li className="queue-item card">
      <div className="queue-main">
        <div className="queue-where">
          <Link to={`/?j=${s.jurisdiction_fips}`}>{s.jurisdiction_name}</Link>
          <span>· submitted {new Date(s.created_at).toLocaleDateString()}</span>
          {s.submitted_by_name && <span>by {s.submitted_by_name}</span>}
        </div>
        {s.is_upload ? (
          <strong className="queue-url">📄 {displayUrl(s)}</strong>
        ) : (
          <a className="queue-url" href={s.url} target="_blank" rel="noreferrer noopener">
            {displayUrl(s)} ↗
          </a>
        )}
        <div className="badge-row">
          {s.official && <span className="tag tag-ok">Official domain</span>}
          {s.is_upload && <span className="tag">PDF upload</span>}
          {s.origin === 'ai' && <span className="tag">AI suggested</span>}
        </div>
        {s.note && <p className="queue-note">“{s.note}”</p>}
        {s.discovery_reason && <p className="queue-note">{s.discovery_reason}</p>}
        {error && <p className="form-error">{error}</p>}
      </div>
      <div className="queue-actions">
        {rejecting ? (
          <form
            className="reject-form"
            onSubmit={(e) => {
              e.preventDefault()
              void act(() => rejectSource(s.id, reason))
            }}
          >
            <input
              autoFocus
              placeholder="Reason (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button type="submit" className="btn btn-secondary btn-sm" disabled={busy}>Reject</button>
            <button type="button" className="link-btn small" onClick={() => setRejecting(false)}>Cancel</button>
          </form>
        ) : (
          <>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy}
              onClick={() => void act(() => approveSource(s.id))}>
              Approve &amp; extract
            </button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
              onClick={() => setRejecting(true)}>
              Reject
            </button>
          </>
        )}
      </div>
    </li>
  )
}
