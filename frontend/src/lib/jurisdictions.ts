import { api } from './api'

export type JurisdictionType = 'state' | 'county' | 'city' | 'consolidated' | 'district'
export type Coverage = 'none' | 'partial' | 'verified' | 'changes_pending'

export type Jurisdiction = {
  id: number
  fips: string
  name: string
  type: JurisdictionType
  state_code: string
  coverage: Coverage
  is_pilot: boolean
  pilot_metro: string | null
}

export type JurisdictionDetail = {
  jurisdiction: Jurisdiction
  stack: Jurisdiction[]
  places: Jurisdiction[]
  counties: Jurisdiction[]
}

export type Resolved = {
  matched_address: string
  lng: number
  lat: number
  county_fips: string | null
  stack: Jurisdiction[]
  unincorporated: boolean
}

export type CoverageItem = Pick<Jurisdiction, 'fips' | 'coverage' | 'is_pilot' | 'pilot_metro'>

/** What the map shows for a county. "pilot" = in the MVP but no approved data yet. */
export type MapStatus = 'none' | 'pilot' | Exclude<Coverage, 'none'>

export function mapStatus(c: Pick<CoverageItem, 'coverage' | 'is_pilot'> | undefined): MapStatus {
  if (!c) return 'none'
  if (c.coverage !== 'none') return c.coverage
  return c.is_pilot ? 'pilot' : 'none'
}

export const STATUS_LABEL: Record<MapStatus, string> = {
  none: 'No data',
  pilot: 'Pilot · collecting',
  partial: 'Partial',
  verified: 'Verified',
  changes_pending: 'Changes pending',
}

export const TYPE_LABEL: Record<JurisdictionType, string> = {
  state: 'State',
  county: 'County',
  city: 'City',
  consolidated: 'City-county',
  district: 'District',
}

export const searchJurisdictions = (q: string, signal?: AbortSignal) =>
  api<Jurisdiction[]>(`/jurisdictions/search?q=${encodeURIComponent(q)}`, { signal })

export const getJurisdiction = (fips: string, signal?: AbortSignal) =>
  api<JurisdictionDetail>(`/jurisdictions/${encodeURIComponent(fips)}`, { signal })

export const getCoverage = () => api<CoverageItem[]>('/jurisdictions/coverage')

export const resolveAddress = (address: string, signal?: AbortSignal) =>
  api<Resolved>(`/resolve?address=${encodeURIComponent(address)}`, { signal })

/** Heuristic: a house number plus at least one more word reads as a street address. */
export function looksLikeAddress(q: string): boolean {
  return /^\s*\d+[a-z]?\s+\S+/i.test(q)
}
