import { api } from './api'
import type { Jurisdiction } from './jurisdictions'
import type { Rule } from './sources'

export type EffectiveCode = {
  code: string
  edition: string
  effective_on: string | null
  status: 'verified' | 'pending'
  rule_id: number
  jurisdiction_fips: string
  jurisdiction_name: string
  overrides: { jurisdiction_fips: string; jurisdiction_name: string; edition: string }[]
}

export type Regulations = {
  stack: Jurisdiction[]
  rules: Rule[]
  effective_codes: EffectiveCode[]
}

export type ProposedAction = { action: 'add' | 'update' | 'remove'; title: string; detail: string }

export type Change = {
  id: number
  source_id: number
  source_url: string
  source_title: string | null
  jurisdiction_fips: string
  jurisdiction_name: string
  mep_relevant: boolean | null
  ai_summary: string | null
  proposed_actions: ProposedAction[] | null
  status: 'new' | 'approved' | 'dismissed'
  created_at: string
  reviewed_at: string | null
  diff_text: string | null
}

export type ExportFormat = 'pdf' | 'docx' | 'json'

export type StackOptions = { stack?: string[]; includePending?: boolean }

function query(o: StackOptions & { address?: string | null }): string {
  const q = new URLSearchParams()
  if (o.stack?.length) q.set('stack', o.stack.join(','))
  if (o.includePending === false) q.set('include_pending', 'false')
  if (o.address) q.set('address', o.address)
  const s = q.toString()
  return s ? `?${s}` : ''
}

const j = (fips: string) => `/jurisdictions/${encodeURIComponent(fips)}`

export const getRegulations = (fips: string, o: StackOptions = {}) =>
  api<Regulations>(`${j(fips)}/regulations${query(o)}`)

export const getChanges = (fips: string, o: StackOptions = {}) =>
  api<Change[]>(`${j(fips)}/changes${query({ stack: o.stack })}`)

export const getRuleHistory = (id: number) => api<Rule[]>(`/rules/${id}/history`)

/** Download URL; the API sends Content-Disposition so the browser saves the file. */
export function exportUrl(
  fips: string,
  format: ExportFormat,
  o: StackOptions & { address?: string | null } = {},
): string {
  return `/api${j(fips)}/export.${format}${query(o)}`
}
