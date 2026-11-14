import { useEffect, useMemo, useState } from 'react'
import { getTaxonomy, type Taxonomy } from './sources'

/** "2024-03-01" → "Mar 1, 2024" without timezone shifts. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

/** Taxonomy key → label lookup ("fire_protection" → "Fire protection"). */
export function useLabels(): { label: (k: string | null) => string; tax: Taxonomy | null } {
  const [tax, setTax] = useState<Taxonomy | null>(null)
  useEffect(() => {
    getTaxonomy().then(setTax).catch(() => {})
  }, [])
  const label = useMemo(() => {
    const m = new Map<string, string>()
    tax?.disciplines.forEach((t) => m.set(t.key, t.label))
    tax?.categories.forEach((t) => m.set(t.key, t.label))
    return (k: string | null) => (k ? (m.get(k) ?? k) : '')
  }, [tax])
  return { label, tax }
}
