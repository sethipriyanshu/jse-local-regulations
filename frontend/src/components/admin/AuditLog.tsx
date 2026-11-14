import { useEffect, useState } from 'react'
import { getAudit, type AuditEntry } from '../../lib/adminApi'
import { formatDateTime } from '../../lib/format'

/** Audit log of every write (PLAN.md H2, ADM-3). */
export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null)
  const [more, setMore] = useState(true)

  useEffect(() => {
    getAudit().then((r) => {
      setRows(r)
      setMore(r.length === 100)
    }).catch(() => setRows([]))
  }, [])

  function loadMore() {
    const last = rows?.[rows.length - 1]
    if (!last) return
    getAudit(last.id).then((r) => {
      setRows((prev) => [...(prev ?? []), ...r])
      setMore(r.length === 100)
    }).catch(() => {})
  }

  if (!rows) return <div className="skeleton skeleton-block" />
  if (rows.length === 0) return <p className="queue-empty">Nothing recorded yet.</p>
  return (
    <>
      <table className="codes-table audit-table">
        <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Item</th><th>Details</th></tr></thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{formatDateTime(a.ts)}</td>
              <td>{a.actor}</td>
              <td><code>{a.action}</code></td>
              <td>{a.entity} #{a.entity_id ?? '—'}</td>
              <td className="audit-detail">{describe(a)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {more && <button type="button" className="btn btn-secondary btn-sm" onClick={loadMore}>Load older</button>}
    </>
  )
}

function describe(a: AuditEntry): string {
  const after = a.after ?? {}
  const before = a.before ?? {}
  const parts: string[] = []
  for (const k of ['title', 'url', 'name', 'file', 'count']) {
    if (after[k] !== undefined && after[k] !== null) parts.push(String(after[k]))
  }
  if (before.status !== undefined && after.status !== undefined && before.status !== after.status) {
    parts.push(`${before.status} → ${after.status}`)
  }
  if (after.review_note) parts.push(`“${after.review_note}”`)
  return parts.join(' · ')
}
