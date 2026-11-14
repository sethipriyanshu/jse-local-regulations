import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { approveChange, dismissChange, getChangeQueue } from '../../lib/adminApi'
import { ApiError } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { Change } from '../../lib/regulations'

/** Changes lane (PLAN.md F3, MON-6): what the daily monitor found, with the AI's
 * triage and the raw diff. */
export default function ChangeReview({ onChanged }: { onChanged: () => void }) {
  const [changes, setChanges] = useState<Change[] | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    getChangeQueue(showAll).then(setChanges).catch(() => setError(true))
  }, [showAll])
  useEffect(load, [load])

  return (
    <div>
      <label className="check lane-toggle">
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
        Also show changes the AI judged not MEP-relevant
      </label>
      {error && <p className="form-error">Could not load changes.</p>}
      {!changes && !error && <div className="skeleton skeleton-block" />}
      {changes?.length === 0 && (
        <p className="queue-empty">No detected changes waiting. The monitor runs daily.</p>
      )}
      <ul className="queue-list">
        {changes?.map((c) => (
          <ChangeItem key={c.id} c={c} onChanged={() => { load(); onChanged() }} />
        ))}
      </ul>
    </div>
  )
}

function ChangeItem({ c, onChanged }: { c: Change; onChanged: () => void }) {
  const [showDiff, setShowDiff] = useState(false)
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
    <li className="queue-item card change-item">
      <div className="queue-main">
        <div className="queue-where">
          <Link to={`/?j=${c.jurisdiction_fips}`}>{c.jurisdiction_name}</Link>
          <span>· detected {formatDateTime(c.created_at)}</span>
          {c.mep_relevant === false && <span className="tag">Not MEP-relevant</span>}
        </div>
        <a className="queue-url" href={c.source_url} target="_blank" rel="noreferrer noopener">
          {c.source_title ?? c.source_url} ↗
        </a>
        <p className="change-summary">{c.ai_summary ?? 'Not triaged.'}</p>
        {c.proposed_actions && c.proposed_actions.length > 0 && (
          <ul className="proposed">
            {c.proposed_actions.map((a, i) => (
              <li key={i}><span className={`act act-${a.action}`}>{a.action}</span> <strong>{a.title}</strong> — {a.detail}</li>
            ))}
          </ul>
        )}
        <button type="button" className="link-btn small" onClick={() => setShowDiff((s) => !s)}>
          {showDiff ? 'Hide diff' : 'Show diff'}
        </button>
        {showDiff && <Diff text={c.diff_text ?? ''} />}
        {error && <p className="form-error">{error}</p>}
      </div>
      <div className="queue-actions">
        <button type="button" className="btn btn-primary btn-sm" disabled={busy}
          title="Re-extract the new version; updated items arrive in the Rules tab"
          onClick={() => void act(() => approveChange(c.id))}>
          Accept &amp; re-extract
        </button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => void act(() => dismissChange(c.id))}>
          Dismiss
        </button>
      </div>
    </li>
  )
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="diff" aria-label="Changes to the page text">
      {text.split('\n').map((line, i) => (
        <span key={i} className={line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'hunk' : ''}>
          {line || ' '}
          {'\n'}
        </span>
      ))}
    </pre>
  )
}
