import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAdmin } from '../lib/admin'
import { formatDate, formatDateTime, useLabels } from '../lib/format'
import { TYPE_LABEL, type Jurisdiction } from '../lib/jurisdictions'
import {
  getChanges,
  getRegulations,
  getRuleHistory,
  type Change,
  type Regulations,
} from '../lib/regulations'
import {
  HEALTH_LABEL,
  displayUrl,
  getSources,
  refreshSource,
  type Rule,
  type Source,
} from '../lib/sources'
import ContributeForms, { type ContributeMode } from './ContributeForms'
import ExportMenu from './ExportMenu'

type Props = {
  fips: string
  placeName: string
  isPilot: boolean
  stack: Jurisdiction[]
  address: string | null
}

type Tab = 'overview' | 'rules' | 'changes' | 'sources'

const POLL_MS = 4000
const POLL_LIMIT = 30 // ~2 minutes

export default function RegulationsSection({ fips, placeName, isPilot, stack, address }: Props) {
  const { isAdmin } = useAdmin()
  const { label } = useLabels()
  const [regs, setRegs] = useState<Regulations | null>(null)
  const [changes, setChanges] = useState<Change[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [tab, setTab] = useState<Tab>('overview')
  const [contribute, setContribute] = useState<ContributeMode | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [polls, setPolls] = useState(0)

  const stackFips = useMemo(() => stack.map((s) => s.fips), [stack])
  const stackKey = stackFips.join(',')

  const load = useCallback(() => {
    const stack = stackKey ? stackKey.split(',') : undefined
    getRegulations(fips, { stack }).then(setRegs).catch(() =>
      setRegs({ stack: [], rules: [], effective_codes: [] }))
    getChanges(fips, { stack }).then(setChanges).catch(() => setChanges([]))
    getSources(fips).then(setSources).catch(() => setSources([]))
  }, [fips, stackKey])

  useEffect(() => {
    setRegs(null)
    setPolls(0)
    load()
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

  const rules = regs?.rules ?? []
  const others = rules.filter((r) => r.category !== 'adopted_code')
  const visibleSources = sources.filter((s) => s.status !== 'rejected' || isAdmin)
  const layerName = useMemo(() => {
    const m = new Map(stack.map((s) => [s.fips, s.name]))
    return (f: string) => m.get(f) ?? f
  }, [stack])

  const tabs: [Tab, string][] = [
    ['overview', 'Overview'],
    ['rules', `Rules${others.length ? ` (${others.length})` : ''}`],
    ['changes', `Changes${changes.length ? ` (${changes.length})` : ''}`],
    ['sources', `Sources${visibleSources.length ? ` (${visibleSources.length})` : ''}`],
  ]

  return (
    <>
      {toast && <div className="inline-toast" role="status">{toast}</div>}

      <div className="detail-tabs-row">
        <ExportMenu fips={fips} stack={stackFips} address={address} />
        <div className="seg detail-tabs" role="tablist">
          {tabs.map(([t, text]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t}
              className={`seg-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
              {text}
            </button>
          ))}
        </div>
      </div>

      {regs === null ? (
        <section className="jp-section"><div className="skeleton skeleton-block" /></section>
      ) : tab === 'overview' ? (
        <Overview regs={regs} isPilot={isPilot} placeName={placeName} stack={stack}
          onAdd={() => { setTab('sources'); setContribute('url') }} />
      ) : tab === 'rules' ? (
        <RulesTab rules={others} label={label} layerName={layerName} isAdmin={isAdmin}
          onAdd={() => { setTab('sources'); setContribute('manual') }} />
      ) : tab === 'changes' ? (
        <ChangesTab changes={changes} rules={rules} />
      ) : null}

      {tab === 'sources' && (
        <section className="jp-section">
          <div className="section-head">
            <h2>Sources for {placeName}</h2>
            {processing && <span className="processing"><span className="spinner-sm" /> Processing</span>}
          </div>
          {visibleSources.length > 0 ? (
            <ul className="source-list">
              {visibleSources.map((s) => (
                <SourceRow key={s.id} s={s} isAdmin={isAdmin} onRefreshed={() => {
                  setPolls(0)
                  load()
                }} />
              ))}
            </ul>
          ) : (
            <p className="muted-note">No sources yet for this layer. Sources for the state or county are on their own pages.</p>
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
      )}
    </>
  )
}

function Overview({ regs, isPilot, placeName, stack, onAdd }: {
  regs: Regulations; isPilot: boolean; placeName: string; stack: Jurisdiction[]; onAdd: () => void
}) {
  const codes = regs.effective_codes
  const showDates = codes.some((c) => c.effective_on)
  const layerType = (fips: string) => {
    const j = stack.find((s) => s.fips === fips)
    return j ? TYPE_LABEL[j.type] : fips
  }
  const pending = regs.rules.filter((r) => r.status === 'pending').length
  if (regs.rules.length === 0) {
    return (
      <section className="jp-section empty-state">
        <h2>No regulations recorded yet</h2>
        <p>
          {isPilot
            ? `${placeName} is a pilot jurisdiction. Add an official source and the AI will extract its MEP rules for review.`
            : 'This area is outside the pilot, but you can still add an official source.'}
        </p>
        <button type="button" className="btn btn-primary btn-sm" onClick={onAdd}>Suggest a source</button>
      </section>
    )
  }
  return (
    <section className="jp-section">
      <h2>Adopted codes</h2>
      {codes.length === 0 ? (
        <p className="muted-note">No code adoptions recorded for these layers yet.</p>
      ) : (
        <table className="codes-table">
          <thead>
            <tr><th>Code</th><th>Edition</th>{showDates && <th>Effective</th>}<th>Set by</th></tr>
          </thead>
          <tbody>
            {codes.map((c) => (
              <tr key={c.code}>
                <td>
                  <i className={`status-dot status-dot-${c.status}`}
                    title={c.status === 'verified' ? 'Verified' : 'Pending review'} />
                  {c.code}
                </td>
                <td><strong>{c.edition}</strong></td>
                {showDates && <td>{formatDate(c.effective_on)}</td>}
                <td title={c.jurisdiction_name}>
                  {layerType(c.jurisdiction_fips)}
                  {c.overrides.map((o) => (
                    <span key={o.jurisdiction_fips} className="override-note">
                      replaces {layerType(o.jurisdiction_fips).toLowerCase()} {o.edition}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted-note">
        <i className="status-dot status-dot-verified" /> verified · <i className="status-dot status-dot-pending" /> pending review.
        When several layers adopt the same code, the most local one wins.
        {pending > 0 && ` ${pending} item${pending === 1 ? ' is' : 's are'} still pending review.`}
      </p>
    </section>
  )
}

function RulesTab({ rules, label, layerName, isAdmin, onAdd }: {
  rules: Rule[]
  label: (k: string | null) => string
  layerName: (fips: string) => string
  isAdmin: boolean
  onAdd: () => void
}) {
  const [discipline, setDiscipline] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [verifiedOnly, setVerifiedOnly] = useState(false)

  const disciplines = useMemo(
    () => [...new Set(rules.map((r) => r.discipline).filter((d): d is string => !!d))],
    [rules],
  )
  const filtered = rules.filter((r) => {
    if (discipline && r.discipline !== discipline) return false
    if (verifiedOnly && r.status !== 'verified') return false
    if (!q) return true
    const hay = `${r.title} ${r.summary} ${r.code_ref ?? ''} ${r.excerpt ?? ''}`.toLowerCase()
    return hay.includes(q.toLowerCase())
  })
  const grouped = useMemo(() => {
    const g = new Map<string, Rule[]>()
    for (const r of filtered) {
      const k = r.category ?? 'other'
      g.set(k, [...(g.get(k) ?? []), r])
    }
    return [...g.entries()]
  }, [filtered])

  if (rules.length === 0) {
    return (
      <section className="jp-section empty-state">
        <h2>No requirements recorded yet</h2>
        <p>Permit, submittal, inspection and amendment details appear here as sources are reviewed.</p>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onAdd}>Add one manually</button>
      </section>
    )
  }

  return (
    <>
      <section className="jp-section rule-filters">
        <input className="filter-search" type="search" placeholder="Search requirements…"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search requirements" />
        <div className="chip-row">
          <button type="button" className={`chip ${discipline === null ? 'active' : ''}`}
            onClick={() => setDiscipline(null)}>All</button>
          {disciplines.map((d) => (
            <button key={d} type="button" className={`chip ${discipline === d ? 'active' : ''}`}
              onClick={() => setDiscipline(discipline === d ? null : d)}>{label(d)}</button>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} />
          Verified only
        </label>
      </section>
      {grouped.length === 0 && <p className="muted-note jp-section">Nothing matches these filters.</p>}
      {grouped.map(([cat, list]) => (
        <section className="jp-section" key={cat}>
          <h2>{label(cat)}</h2>
          <div className="rule-list">
            {list.map((r) => (
              <RuleCard key={r.id} rule={r} label={label} layer={layerName(r.jurisdiction_fips)} isAdmin={isAdmin} />
            ))}
          </div>
        </section>
      ))}
    </>
  )
}

function ChangesTab({ changes, rules }: { changes: Change[]; rules: Rule[] }) {
  type Item = { at: string; kind: 'change' | 'verified'; title: string; body: string; where: string }
  const items: Item[] = [
    ...changes.map((c) => ({
      at: c.created_at, kind: 'change' as const,
      title: c.status === 'approved' ? 'Source change accepted' : 'Source changed · awaiting review',
      body: c.ai_summary ?? 'The page changed.',
      where: `${c.jurisdiction_name} · ${c.source_title ?? c.source_url}`,
    })),
    ...rules.filter((r) => r.verified_at).map((r) => ({
      at: r.verified_at as string, kind: 'verified' as const, title: `Verified: ${r.title}`,
      body: r.summary, where: r.jurisdiction_name,
    })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 40)

  if (items.length === 0) {
    return (
      <section className="jp-section empty-state">
        <h2>No changes yet</h2>
        <p>Approved sources are checked every day. Detected changes and verifications show up here.</p>
      </section>
    )
  }
  return (
    <section className="jp-section">
      <ol className="timeline">
        {items.map((i, n) => (
          <li key={n} className={`tl-${i.kind}`}>
            <span className="tl-when">{formatDateTime(i.at)}</span>
            <strong>{i.title}</strong>
            <p>{i.body}</p>
            <span className="tl-where">{i.where}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`pill pill-${status}`}>
      {status === 'pending' ? 'Pending review' : status === 'verified' ? 'Verified' : status}
    </span>
  )
}

function RuleCard({ rule: r, label, layer, isAdmin }: {
  rule: Rule; label: (k: string | null) => string; layer: string; isAdmin: boolean
}) {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<Rule[] | null>(null)
  return (
    <article className="rule-card">
      <header>
        <h3>{r.title}</h3>
        <StatusPill status={r.status} />
      </header>
      <p>{r.summary}</p>
      <div className="rule-meta">
        <span className="tag tag-layer">{layer}</span>
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
      <div className="rule-links">
        {(r.excerpt || r.source_url) && (
          <button type="button" className="link-btn small" onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide source' : 'Show source quote'}
          </button>
        )}
        {r.supersedes_id && history === null && (
          <button type="button" className="link-btn small"
            onClick={() => getRuleHistory(r.id).then(setHistory).catch(() => setHistory([]))}>
            Show history
          </button>
        )}
      </div>
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
      {history && history.length > 0 && (
        <ul className="history-list">
          {history.map((h) => (
            <li key={h.id}>
              <strong>Previously:</strong> {h.title}
              {h.verified_at && <span> · verified {formatDate(h.verified_at)}</span>}
            </li>
          ))}
        </ul>
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
          {s.last_fetched_at && s.status === 'approved' && ` · checked ${formatDateTime(s.last_fetched_at)}`}
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
