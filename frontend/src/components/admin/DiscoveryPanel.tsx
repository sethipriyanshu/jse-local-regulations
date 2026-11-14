import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, getJobs, startDiscovery, type Job } from '../../lib/adminApi'
import { ApiError } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { searchJurisdictions, TYPE_LABEL, type Jurisdiction } from '../../lib/jurisdictions'

/** AI discovery (PLAN.md E1–E4): web search for official pages; results land in the
 * Sources tab as "AI suggested" for approval. */
export default function DiscoveryPanel({ onFinished }: { onFinished: () => void }) {
  const [job, setJob] = useState<Job | null>(null)
  const [history, setHistory] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pick, setPick] = useState<Jurisdiction | null>(null)

  const loadHistory = useCallback(() => {
    getJobs('discovery').then((jobs) => {
      setHistory(jobs)
      setJob((cur) => cur ?? jobs.find((j) => j.status === 'running') ?? null)
    }).catch(() => {})
  }, [])
  useEffect(loadHistory, [loadHistory])

  // Poll the running job.
  const finishedRef = useRef(onFinished)
  finishedRef.current = onFinished
  useEffect(() => {
    if (!job || job.status !== 'running') return
    const t = setTimeout(() => {
      getJob(job.id).then((j) => {
        setJob(j)
        if (j.status !== 'running') {
          loadHistory()
          finishedRef.current()
        }
      }).catch(() => {})
    }, 3000)
    return () => clearTimeout(t)
  }, [job, loadHistory])

  async function run(fips?: string[]) {
    setError(null)
    try {
      setJob(await startDiscovery(fips))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start discovery')
    }
  }

  const running = job?.status === 'running'
  const pct = job?.total ? Math.round((job.done / job.total) * 100) : 0

  return (
    <div className="discovery">
      <div className="card discovery-card">
        <h3>Find sources with AI web search</h3>
        <p className="page-sub">
          Searches the web for each jurisdiction’s adopted-codes page, building department, permit
          requirements and code of ordinances. Every candidate is fetched to check it exists, then
          appears in the <strong>Sources</strong> tab for you to approve or reject. Nothing is
          monitored until you approve it.
        </p>
        <div className="action-row">
          <button type="button" className="btn btn-primary" disabled={running} onClick={() => void run()}>
            Run for all pilot jurisdictions
          </button>
        </div>
        <p className="muted-note">
          Takes about half a minute per jurisdiction (the search tool is rate limited). Costs
          roughly $0.02 per jurisdiction.
        </p>
        <div className="discovery-single">
          <JurisdictionPicker value={pick} onChange={setPick} />
          <button type="button" className="btn btn-secondary btn-sm" disabled={running || !pick}
            onClick={() => pick && void run([pick.fips])}>
            Run for this one
          </button>
        </div>
        {error && <p className="form-error">{error}</p>}
      </div>

      {job && (
        <div className="card job-card">
          <div className="section-head">
            <h3>Run #{job.id} · {job.status === 'running' ? 'in progress' : job.status}</h3>
            <span className="muted-note">{job.done} / {job.total ?? '?'} jurisdictions</span>
          </div>
          <div className="progress"><span style={{ width: `${pct}%` }} /></div>
          <p className="muted-note">
            {job.changes_found} new candidate{job.changes_found === 1 ? '' : 's'} added to the Sources tab.
            {job.errors?.length ? ` ${job.errors.length} jurisdiction(s) failed.` : ''}
          </p>
        </div>
      )}

      {history.length > 0 && (
        <>
          <h3 className="section-title">Previous runs</h3>
          <table className="codes-table">
            <thead><tr><th>Run</th><th>Started</th><th>Jurisdictions</th><th>Added</th><th>Status</th></tr></thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td>#{h.id}</td><td>{formatDateTime(h.started_at)}</td>
                  <td>{h.done}/{h.total}</td><td>{h.changes_found}</td><td>{h.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function JurisdictionPicker({ value, onChange }: {
  value: Jurisdiction | null; onChange: (j: Jurisdiction | null) => void
}) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Jurisdiction[]>([])
  useEffect(() => {
    if (value || q.trim().length < 2) {
      setResults([])
      return
    }
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      searchJurisdictions(q, ctrl.signal).then(setResults).catch(() => {})
    }, 200)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [q, value])

  if (value) {
    return (
      <span className="picked">
        {value.name}, {value.state_code} <span className="layer-type">{TYPE_LABEL[value.type]}</span>
        <button type="button" className="link-btn small" onClick={() => { onChange(null); setQ('') }}>change</button>
      </span>
    )
  }
  return (
    <div className="picker">
      <input placeholder="One jurisdiction, e.g. Fulton County GA" value={q}
        onChange={(e) => setQ(e.target.value)} aria-label="Jurisdiction" />
      {results.length > 0 && (
        <ul className="picker-results card">
          {results.map((r) => (
            <li key={r.fips}>
              <button type="button" onClick={() => onChange(r)}>
                {r.name}, {r.state_code} <span className="layer-type">{TYPE_LABEL[r.type]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
