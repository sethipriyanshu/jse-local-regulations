import { api, ApiError } from './api'

export type SourceStatus = 'submitted' | 'approved' | 'rejected' | 'broken'
export type SourceHealth = 'unknown' | 'ok' | 'redirected' | 'not_found' | 'blocked' | 'error'
export type RuleStatus = 'pending' | 'verified' | 'superseded' | 'rejected'
export type Origin = 'user' | 'admin' | 'ai' | 'seed'

export type Source = {
  id: number
  jurisdiction_fips: string
  jurisdiction_name: string
  url: string
  title: string | null
  domain: string
  status: SourceStatus
  origin: Origin
  health: SourceHealth
  official: boolean
  is_upload: boolean
  submitted_by_name: string | null
  note: string | null
  reject_reason: string | null
  discovery_reason: string | null
  last_fetched_at: string | null
  created_at: string
  rule_count: number
}

export type Rule = {
  id: number
  jurisdiction_fips: string
  jurisdiction_name: string
  title: string
  summary: string
  excerpt: string | null
  discipline: string | null
  category: string | null
  code_ref: string | null
  code_edition: string | null
  effective_on: string | null
  status: RuleStatus
  origin: Origin
  confidence: number | null
  grounded: boolean | null
  source_id: number | null
  source_url: string | null
  source_title: string | null
  submitted_by_name: string | null
  review_note: string | null
  supersedes_id: number | null
  snapshot_id: number | null
  created_at: string
  verified_at: string | null
}

export type TaxonomyItem = { key: string; label: string }
export type Taxonomy = { disciplines: TaxonomyItem[]; categories: TaxonomyItem[] }

export type Queue = {
  sources: Source[]
  counts: { sources: number; rules: number; changes: number }
}

export type RuleInput = {
  title: string
  summary: string
  discipline: string
  category: string
  excerpt?: string
  code_ref?: string
  code_edition?: string
  effective_on?: string
  source_url?: string
  submitted_by_name?: string
}

const j = (fips: string) => `/jurisdictions/${encodeURIComponent(fips)}`

export const getSources = (fips: string) => api<Source[]>(`${j(fips)}/sources`)
export const getRules = (fips: string) => api<Rule[]>(`${j(fips)}/rules`)

let taxonomyCache: Promise<Taxonomy> | null = null
export const getTaxonomy = () => (taxonomyCache ??= api<Taxonomy>('/taxonomy'))

export const submitSource = (fips: string, url: string, note: string, name: string) =>
  api<Source>(`${j(fips)}/sources`, {
    method: 'POST',
    body: JSON.stringify({ url, note: note || null, submitted_by_name: name || null }),
  })

export const addRule = (fips: string, input: RuleInput) =>
  api<Rule>(`${j(fips)}/rules`, { method: 'POST', body: JSON.stringify(input) })

export async function uploadPdf(fips: string, file: File, title: string, name: string) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  if (name) form.append('submitted_by_name', name)
  const res = await fetch(`/api${j(fips)}/uploads`, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText)
  return body as Source
}

export const getQueue = () => api<Queue>('/admin/queue')
export const approveSource = (id: number) =>
  api<Source>(`/admin/sources/${id}/approve`, { method: 'POST' })
export const rejectSource = (id: number, reason: string) =>
  api<Source>(`/admin/sources/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) })
export const refreshSource = (id: number, reextract = false) =>
  api<Source>(`/admin/sources/${id}/refresh?reextract=${reextract}`, { method: 'POST' })

/** "Your name" for attribution without login (PLAN.md ADM-2), remembered per browser. */
const NAME_KEY = 'jse-regs:name'
export function getSavedName(): string {
  try {
    return localStorage.getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}
export function saveName(name: string): void {
  try {
    localStorage.setItem(NAME_KEY, name.trim())
  } catch {
    // storage unavailable (private mode); attribution is optional
  }
}

export const HEALTH_LABEL: Record<SourceHealth, string> = {
  unknown: 'Not fetched yet',
  ok: 'OK',
  redirected: 'Redirected',
  not_found: 'Not found (404)',
  blocked: 'Blocked by site',
  error: 'Fetch error',
}

export function displayUrl(s: Pick<Source, 'url' | 'is_upload' | 'title'>): string {
  if (s.is_upload) return s.title ?? 'Uploaded PDF'
  return s.url.replace(/^https?:\/\/(www\.)?/, '')
}
