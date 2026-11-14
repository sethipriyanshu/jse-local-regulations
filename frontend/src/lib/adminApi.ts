import { api } from './api'
import type { Change } from './regulations'
import type { Rule, Source } from './sources'

export type JobStatus = 'running' | 'succeeded' | 'failed'
export type Job = {
  id: number
  job: string
  status: JobStatus
  started_at: string
  finished_at: string | null
  total: number | null
  done: number
  sources_checked: number
  changes_found: number
  errors: { error: string; fips?: string; source_id?: number }[] | null
  summary: Record<string, unknown> | null
}

export type Overview = {
  counts: { sources: number; rules: number; changes: number; monitored: number; verified_rules: number }
  last_daily: Job | null
  unhealthy_sources: Source[]
  cost: { last_30d_usd: number; by_kind: Record<string, number>; calls_30d: number }
}

export type AuditEntry = {
  id: number
  actor: string
  action: string
  entity: string
  entity_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ts: string
}

export type TeamsChannel = {
  id: number
  name: string
  webhook: string
  metro: string | null
  sends_digest: boolean
  sends_alerts: boolean
  created_at: string
}

export type RuleEdits = Partial<{
  title: string
  summary: string
  discipline: string
  category: string
  excerpt: string
  code_ref: string
  code_edition: string
  effective_on: string
  supersedes_id: number
}>

const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const getOverview = () => api<Overview>('/admin/overview')

export const getRuleQueue = (o: { fips?: string; sourceId?: number } = {}) => {
  const q = new URLSearchParams()
  if (o.fips) q.set('fips', o.fips)
  if (o.sourceId) q.set('source_id', String(o.sourceId))
  return api<{ rules: Rule[]; total: number }>(`/admin/rules?${q}`)
}
export const verifyRule = (id: number, edits: RuleEdits = {}) =>
  post<{ rule: Rule; superseded: Rule[] }>(`/admin/rules/${id}/verify`, edits)
export const rejectRule = (id: number, reason: string) =>
  post<Rule>(`/admin/rules/${id}/reject`, { reason })
export const verifyGrounded = (sourceId: number) =>
  post<{ count: number }>(`/admin/sources/${sourceId}/verify-grounded`)
export const approveSources = (ids: number[]) =>
  post<{ count: number }>('/admin/sources/approve-bulk', { ids })

export const getChangeQueue = (includeIrrelevant = false) =>
  api<Change[]>(`/admin/changes?include_irrelevant=${includeIrrelevant}`)
export const approveChange = (id: number) => post<Change>(`/admin/changes/${id}/approve`)
export const dismissChange = (id: number) => post<Change>(`/admin/changes/${id}/dismiss`)

export const startDiscovery = (fips?: string[]) => post<Job>('/admin/discovery', { fips: fips ?? null })
export const getJobs = (job?: string) => api<Job[]>(`/admin/jobs${job ? `?job=${job}` : ''}`)
export const getJob = (id: number) => api<Job>(`/admin/jobs/${id}`)

export const getAudit = (beforeId?: number) =>
  api<AuditEntry[]>(`/admin/audit?limit=100${beforeId ? `&before_id=${beforeId}` : ''}`)

export const getTeamsChannels = () => api<TeamsChannel[]>('/admin/teams')
export const addTeamsChannel = (c: {
  name: string
  webhook_url: string
  metro: string | null
  sends_digest: boolean
  sends_alerts: boolean
}) => post<TeamsChannel>('/admin/teams', c)
export const deleteTeamsChannel = (id: number) =>
  fetch(`/api/admin/teams/${id}`, { method: 'DELETE', credentials: 'same-origin' })
export const testTeamsChannel = (id: number) => post<{ count: number }>(`/admin/teams/${id}/test`)
