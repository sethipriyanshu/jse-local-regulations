import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJobs, type Job, type Overview } from '../../lib/adminApi'
import { formatDateTime } from '../../lib/format'
import { HEALTH_LABEL, displayUrl } from '../../lib/sources'

/** Jobs & health (PLAN.md MON-5, H4, OPS-1). */
export default function HealthPanel({ overview }: { overview: Overview | null }) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  useEffect(() => {
    getJobs().then(setJobs).catch(() => setJobs([]))
  }, [])
  if (!overview) return <div className="skeleton skeleton-block" />
  const d = overview.last_daily
  const stale = d ? Date.now() - new Date(d.started_at).getTime() > 36 * 3600 * 1000 : true

  return (
    <div className="health">
      <div className="stat-row">
        <div className={`card stat ${stale || d?.status === 'failed' ? 'stat-bad' : ''}`}>
          <span className="stat-value">{d ? d.status : 'never'}</span>
          <span className="stat-label">
            Last daily check{d ? ` · ${formatDateTime(d.started_at)}` : ''}
            {stale && ' · overdue'}
          </span>
        </div>
        <div className="card stat">
          <span className="stat-value">{overview.counts.monitored}</span>
          <span className="stat-label">Monitored sources</span>
        </div>
        <div className="card stat">
          <span className="stat-value">${overview.cost.last_30d_usd.toFixed(2)}</span>
          <span className="stat-label">AI spend, last 30 days ({overview.cost.calls_30d} calls)</span>
        </div>
      </div>

      {Object.keys(overview.cost.by_kind).length > 0 && (
        <p className="muted-note">
          By task: {Object.entries(overview.cost.by_kind)
            .map(([k, v]) => `${k} $${v.toFixed(3)}`).join(' · ')}
        </p>
      )}

      <h3 className="section-title">Sources needing attention ({overview.unhealthy_sources.length})</h3>
      {overview.unhealthy_sources.length === 0 ? (
        <p className="queue-empty">All monitored sources fetched fine on their last check.</p>
      ) : (
        <ul className="source-list">
          {overview.unhealthy_sources.map((s) => (
            <li key={s.id} className="source-row">
              <span className="dot dot-bad" />
              <div className="source-main">
                <a className="source-title" href={s.url} target="_blank" rel="noreferrer noopener">
                  {s.title || displayUrl(s)}
                </a>
                <span className="source-sub">
                  <Link to={`/?j=${s.jurisdiction_fips}`}>{s.jurisdiction_name}</Link>
                  {' · '}{HEALTH_LABEL[s.health]}
                  {s.health === 'blocked' && ' · upload the page as a PDF instead'}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="section-title">Recent jobs</h3>
      {!jobs ? <div className="skeleton skeleton-line" /> : jobs.length === 0 ? (
        <p className="queue-empty">No jobs have run yet.</p>
      ) : (
        <table className="codes-table">
          <thead><tr><th>Job</th><th>Started</th><th>Progress</th><th>Found</th><th>Errors</th><th>Status</th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{j.job.replace('_', ' ')}</td>
                <td>{formatDateTime(j.started_at)}</td>
                <td>{j.done}{j.total !== null ? `/${j.total}` : ''}</td>
                <td>{j.changes_found}</td>
                <td title={j.errors?.map((e) => e.error).join('\n')}>{j.errors?.length ?? 0}</td>
                <td><span className={`pill pill-${j.status === 'succeeded' ? 'verified' : j.status === 'failed' ? 'rejected' : 'pending'}`}>{j.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
