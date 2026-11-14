import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRuleQueue, rejectRule, verifyGrounded, verifyRule, type RuleEdits } from '../../lib/adminApi'
import { ApiError } from '../../lib/api'
import { formatDate, useLabels } from '../../lib/format'
import type { Rule, Taxonomy } from '../../lib/sources'

/** Rules lane (PLAN.md REV-1..4): verify, edit-and-verify, or reject pending items,
 * grouped by the document they came from. */
export default function RuleReview({ onChanged }: { onChanged: () => void }) {
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const { label, tax } = useLabels()

  const load = useCallback(() => {
    getRuleQueue()
      .then((q) => {
        setRules(q.rules)
        setTotal(q.total)
      })
      .catch(() => setError('Could not load pending rules.'))
  }, [])
  useEffect(load, [load])

  const done = useCallback(() => {
    load()
    onChanged()
  }, [load, onChanged])

  const groups = useMemo(() => {
    const g = new Map<string, Rule[]>()
    for (const r of rules ?? []) {
      const k = `${r.jurisdiction_fips}|${r.source_id ?? 'manual'}`
      g.set(k, [...(g.get(k) ?? []), r])
    }
    return [...g.values()]
  }, [rules])

  if (error) return <p className="form-error">{error}</p>
  if (!rules) return <div className="skeleton skeleton-block" />
  if (rules.length === 0) return <p className="queue-empty">No rules waiting for verification.</p>

  return (
    <div className="review-groups">
      {total > rules.length && (
        <p className="muted-note">Showing the first {rules.length} of {total} pending rules.</p>
      )}
      {groups.map((list) => (
        <RuleGroup key={`${list[0].jurisdiction_fips}-${list[0].source_id}`} rules={list}
          label={label} tax={tax} onChanged={done} />
      ))}
    </div>
  )
}

function RuleGroup({ rules, label, tax, onChanged }: {
  rules: Rule[]; label: (k: string | null) => string; tax: Taxonomy | null; onChanged: () => void
}) {
  const first = rules[0]
  const grounded = rules.filter((r) => r.grounded).length
  const [busy, setBusy] = useState(false)
  return (
    <section className="review-group card">
      <header className="review-group-head">
        <div>
          <Link to={`/?j=${first.jurisdiction_fips}`} className="review-place">{first.jurisdiction_name}</Link>
          <div className="review-source">
            {first.source_url && !first.source_url.startsWith('upload://') ? (
              <a href={first.source_url} target="_blank" rel="noreferrer noopener">
                {first.source_title ?? first.source_url.replace(/^https?:\/\//, '')} ↗
              </a>
            ) : first.source_url ? (
              <span>📄 {first.source_title ?? 'Uploaded PDF'}</span>
            ) : (
              <span>Manual entries</span>
            )}
            <span> · {rules.length} pending</span>
          </div>
        </div>
        {first.source_id && grounded > 0 && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
            title="Verify every item from this source whose quote was found in the document"
            onClick={() => {
              setBusy(true)
              verifyGrounded(first.source_id as number).then(onChanged).finally(() => setBusy(false))
            }}>
            Verify {grounded} quoted item{grounded === 1 ? '' : 's'}
          </button>
        )}
      </header>
      <ul className="review-list">
        {rules.map((r) => <ReviewItem key={r.id} rule={r} label={label} tax={tax} onChanged={onChanged} />)}
      </ul>
    </section>
  )
}

function ReviewItem({ rule: r, label, tax, onChanged }: {
  rule: Rule; label: (k: string | null) => string; tax: Taxonomy | null; onChanged: () => void
}) {
  const [mode, setMode] = useState<'view' | 'edit' | 'reject'>('view')
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
    <li className="review-item">
      {mode === 'edit' ? (
        <EditForm rule={r} tax={tax} busy={busy} onCancel={() => setMode('view')}
          onSave={(edits) => void act(() => verifyRule(r.id, edits))} />
      ) : (
        <>
          <div className="review-item-head">
            <h3>{r.title}</h3>
            <div className="review-actions">
              {mode === 'reject' ? (
                <form className="reject-form" onSubmit={(e) => {
                  e.preventDefault()
                  void act(() => rejectRule(r.id, reason))
                }}>
                  <input autoFocus placeholder="Reason (optional)" value={reason}
                    onChange={(e) => setReason(e.target.value)} />
                  <button type="submit" className="btn btn-secondary btn-sm" disabled={busy}>Reject</button>
                  <button type="button" className="link-btn small" onClick={() => setMode('view')}>Cancel</button>
                </form>
              ) : (
                <>
                  <button type="button" className="btn btn-primary btn-sm" disabled={busy}
                    onClick={() => void act(() => verifyRule(r.id))}>Verify</button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                    onClick={() => setMode('edit')}>Edit</button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                    onClick={() => setMode('reject')}>Reject</button>
                </>
              )}
            </div>
          </div>
          <p>{r.summary}</p>
          <div className="rule-meta">
            {r.category && <span className="tag">{label(r.category)}</span>}
            {r.discipline && <span className="tag">{label(r.discipline)}</span>}
            {r.code_ref && <span>{r.code_ref}{r.code_edition ? ` · ${r.code_edition}` : ''}</span>}
            {r.effective_on && <span>Effective {formatDate(r.effective_on)}</span>}
            {r.confidence !== null && <span>Confidence {Math.round(r.confidence * 100)}%</span>}
            {r.origin !== 'ai' && <span>Entered by {r.submitted_by_name ?? r.origin}</span>}
            {r.grounded === false && <span className="warn">⚠ Quote not found in source — check it</span>}
            {r.grounded === true && <span className="ok">✓ Quote found in source</span>}
          </div>
          {r.excerpt && <blockquote className="review-quote">{r.excerpt}</blockquote>}
        </>
      )}
      {error && <p className="form-error">{error}</p>}
    </li>
  )
}

function EditForm({ rule: r, tax, busy, onSave, onCancel }: {
  rule: Rule; tax: Taxonomy | null; busy: boolean; onSave: (e: RuleEdits) => void; onCancel: () => void
}) {
  const [f, setF] = useState({
    title: r.title, summary: r.summary, discipline: r.discipline ?? '', category: r.category ?? '',
    code_ref: r.code_ref ?? '', code_edition: r.code_edition ?? '', effective_on: r.effective_on ?? '',
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((p) => ({ ...p, [k]: e.target.value }))
  return (
    <form className="form-stack" onSubmit={(e) => {
      e.preventDefault()
      onSave({ ...f, discipline: f.discipline || undefined, category: f.category || undefined })
    }}>
      <label className="field"><span>Title</span>
        <input required value={f.title} onChange={set('title')} /></label>
      <label className="field"><span>Summary</span>
        <textarea required rows={3} value={f.summary} onChange={set('summary')} /></label>
      <div className="field-row">
        <label className="field"><span>Discipline</span>
          <select value={f.discipline} onChange={set('discipline')}>
            <option value="">—</option>
            {tax?.disciplines.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select></label>
        <label className="field"><span>Category</span>
          <select value={f.category} onChange={set('category')}>
            <option value="">—</option>
            {tax?.categories.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select></label>
      </div>
      <div className="field-row">
        <label className="field"><span>Code</span>
          <input value={f.code_ref} onChange={set('code_ref')} placeholder="IPC" /></label>
        <label className="field"><span>Edition</span>
          <input value={f.code_edition} onChange={set('code_edition')} placeholder="2021" /></label>
        <label className="field"><span>Effective</span>
          <input type="date" value={f.effective_on} onChange={set('effective_on')} /></label>
      </div>
      <div className="action-row">
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>Save &amp; verify</button>
        <button type="button" className="link-btn small" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
