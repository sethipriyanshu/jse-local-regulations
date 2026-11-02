import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAdmin } from '../lib/admin'
import {
  HEALTH_LABEL,
  displayUrl,
  getRules,
  getSources,
  getTaxonomy,
  refreshSource,
  type Rule,
  type Source,
  type Taxonomy,
} from '../lib/sources'
import ContributeForms, { type ContributeMode } from './ContributeForms'

type Props = { fips: string; placeName: string; isPilot: boolean }

const POLL_MS = 4000
const POLL_LIMIT = 30 // ~2 minutes

export default function RegulationsSection({ fips, placeName, isPilot }: Props) {
  const { isAdmin } = useAdmin()
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [tax, setTax] = useState<Taxonomy | null>(null)
  const [contribute, setContribute] = useState<ContributeMode | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [polls, setPolls] = useState(0)

  const load = useCallback(() => {
    getRules(fips).then(setRules).catch(() => setRules([]))
    getSources(fips).then(setSources).catch(() => setSources([]))
  }, [fips])

  useEffect(() => {
    setRules(null)
    setPolls(0)
    load()
    getTaxonomy().then(setTax).catch(() => {})
  }, [load])

  // While approved sources are still being fetched/extracted, refresh periodically.
  const processing = sources.some((s) => s.status === 'approved' && !s.last_fetched_at)
  useEffect(() => {
    if (!processing || polls >= POLL_LIMIT) return
    const t = setTimeout(() => {
      load()
      setPolls((p) => p + 1)
    }, POLL_MS)
    return () => clearTimeout(t)
  }, [processing, polls, load])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(t)
  }, [toast])

  const label = useMemo(() => {
    const m = new Map<string, string>()
    tax?.disciplines.forEach((t) => m.set(t.key, t.label))
    tax?.categories.forEach((t) => m.set(t.key, t.label))
    return (k: string | null) => (k ? (m.get(k) ?? k) : '')
  }, [tax])

  const adoptions = (rules ?? []).filter((r) => r.category === 'adopted_code')
  const others = (rules ?? []).filter((r) => r.category !== 'adopted_code')
  const grouped = useMemo(() => {
    const g = new Map<string, Rule[]>()
    for (const r of others) {
      const k = r.category ?? 'other'
      g.set(k, [...(g.get(k) ?? []), r])
    }
    return [...g.entries()]
  }, [others])
  const visibleSources = sources.filter((s) => s.status !== 'rejected' || isAdmin)

  return (
    <>
      {toast && <div className="inline-toast" role="status">{toast}</div>}

      {rules === null ? (
        <section className="jp-section">
          <div className="skeleton skeleton-block" />
        </section>
      ) : rules.length === 0 ? (
        <section className="jp-section empty-state">
          <h2>No regulations recorded yet</h2>
          <p>
            {isPilot
              ? 'This is a pilot jurisdiction. Add an official source and the AI will extract its MEP rules for review.'
              : 'This area is outside the pilot, but you can still add an official source.'}
          </p>
        </section>
      ) : (
        <>
          {adoptions.length > 0 && (
            <section className="jp-section">
              <h2>Adopted codes</h2>
              <table className="codes-table">
                <thead>
                  <tr><th>Code</th><th>Edition</th><th>Effective</th><th /></tr>
                </thead>
                <tbody>
                  {adoptions.map((r) => (
                    <tr key={r.id}>
                      <td>{r.code_ref}</td>
                      <td><strong>{r.code_edition}</strong></td>
                      <td>{r.effective_on ? formatDate(r.effective_on) : '—'}</td>
                      <td><StatusPill rule={r} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {grouped.map(([cat, list]) => (
            <section className="jp-section" key={cat}>
              <h2>{label(cat)}</h2>
              <div className="rule-list">
                {list.map((r) => <RuleCard key={r.id} rule={r} label={label} isAdmin={isAdmin} />)}
              </div>
            </section>
          ))}
        </>
      )}

      <section className="jp-section">
        <div className="section-head">
          <h2>Sources ({visibleSources.length})</h2>
          {processing && <span className="processing"><span className="spinner-sm" /> Processing</span>}
        </div>
        {visibleSources.length > 0 && (
          <ul className="source-list">
            {visibleSources.map((s) => (
              <SourceRow key={s.id} s={s} isAdmin={isAdmin} onRefreshed={() => {
                setPolls(0)
                load()
              }} />
            ))}
          </ul>
        )}
        {contribute ? (
          <ContributeForms
            fips={fips}
            placeName={placeName}
            isAdmin={isAdmin}
            initialMode={contribute}
            onCancel={() => setContribute(null)}
            onDone={(msg) => {
              setContribute(null)
              setToast(msg)
              setPolls(0)
              load()
            }}
          />
        ) : (
          <div className="action-row">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setContribute('url')}>
              Suggest a source
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setContribute('pdf')}>
              Upload PDF
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setContribute('manual')}>
              Add manually
            </button>
          </div>
        )}
      </section>
    </>
  )
}

function StatusPill({ rule }: { rule: Rule }) {
  return (
    <span className={`pill pill-${rule.status}`}>
      {rule.status === 'pending' ? 'Pending review' : rule.status === 'verified' ? 'Verified' : rule.status}
    </span>
  )
}

function RuleCard({ rule: r, label, isAdmin }: { rule: Rule; label: (k: string | null) => string; isAdmin: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <article className="rule-card">
      <header>
        <h3>{r.title}</h3>
        <StatusPill rule={r} />
      </header>
      <p>{r.summary}</p>
      <div className="rule-meta">
        {r.discipline && <span className="tag">{label(r.discipline)}</span>}
        {r.code_ref && <span>{r.code_ref}{r.code_edition ? ` · ${r.code_edition}` : ''}</span>}
        {r.effective_on && <span>Effective {formatDate(r.effective_on)}</span>}
        {r.origin === 'ai' && <span>AI-extracted</span>}
        {isAdmin && r.grounded === false && (
          <span className="warn" title="The quote was not found verbatim in the source snapshot">
            ⚠ Quote not found in source
          </span>
        )}
      </div>
      {(r.excerpt || r.source_url) && (
        <button type="button" className="link-btn small" onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide source' : 'Show source quote'}
        </button>
      )}
      {open && (
        <div className="rule-source">
          {r.excerpt && <blockquote>{r.excerpt}</blockquote>}
          {r.source_url && !r.source_url.startsWith('upload://') && (
            <a href={r.source_url} target="_blank" rel="noreferrer noopener">
              {r.source_title ?? r.source_url.replace(/^https?:\/\//, '')} ↗
            </a>
          )}
          {r.source_url?.startsWith('upload://') && <span>From uploaded PDF: {r.source_title}</span>}
        </div>
      )}
    </article>
  )
}

function SourceRow({ s, isAdmin, onRefreshed }: { s: Source; isAdmin: boolean; onRefreshed: () => void }) {
  const healthy = s.health === 'ok' || s.health === 'redirected'
  const statusText =
    s.status === 'submitted' ? 'Awaiting review'
      : s.status === 'rejected' ? 'Rejected'
        : !s.last_fetched_at ? 'Processing…'
          : HEALTH_LABEL[s.health]
  return (
    <li className="source-row">
      <span className={`dot ${s.status !== 'approved' ? 'dot-muted' : !s.last_fetched_at ? 'dot-warn' : healthy ? 'dot-ok' : 'dot-bad'}`} />
      <div className="source-main">
        {s.is_upload ? (
          <span className="source-title">📄 {displayUrl(s)}</span>
        ) : (
          <a className="source-title" href={s.url} target="_blank" rel="noreferrer noopener">
            {s.title || displayUrl(s)}
          </a>
        )}
        <span className="source-sub">
          {statusText}
          {s.rule_count > 0 && ` · ${s.rule_count} item${s.rule_count === 1 ? '' : 's'}`}
          {s.official && ' · official'}
        </span>
      </div>
      {isAdmin && s.status === 'approved' && s.last_fetched_at && (
        <button
          type="button"
          className="link-btn small"
          title="Fetch again now"
          onClick={() => refreshSource(s.id).then(onRefreshed).catch(() => {})}
        >
          Check now
        </button>
      )}
    </li>
  )
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
