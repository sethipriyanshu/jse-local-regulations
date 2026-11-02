import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import {
  TYPE_LABEL,
  looksLikeAddress,
  searchJurisdictions,
  type Jurisdiction,
} from '../lib/jurisdictions'

type Props = {
  onJurisdiction: (j: Jurisdiction) => void
  onAddress: (address: string) => Promise<void>
}

/** One box for both: type a place name to get jurisdiction suggestions, or a street
 * address and press Enter to geocode it. */
export default function SearchBox({ onJurisdiction, onAddress }: Props) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Jurisdiction[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [busy, setBusy] = useState(false)
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)

  const isAddress = looksLikeAddress(q)
  // Rows: suggestions, plus an "address" row whenever the text could be an address.
  const showAddressRow = q.trim().length >= 5 && (isAddress || results.length === 0)
  const rowCount = results.length + (showAddressRow ? 1 : 0)

  useEffect(() => {
    const term = q.trim()
    if (term.length < 2 || isAddress) {
      setResults([])
      return
    }
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      searchJurisdictions(term, ctrl.signal)
        .then((r) => {
          setResults(r)
          setActive(-1)
        })
        .catch(() => {})
    }, 180)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [q, isAddress])

  function pick(j: Jurisdiction) {
    setQ(`${j.name}, ${j.state_code}`)
    setOpen(false)
    onJurisdiction(j)
    inputRef.current?.blur()
  }

  async function lookupAddress() {
    const address = q.trim()
    if (!address) return
    setOpen(false)
    setBusy(true)
    try {
      await onAddress(address)
    } finally {
      setBusy(false)
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => Math.min(a + 1, rowCount - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, -1))
    } else if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (active >= 0 && active < results.length) pick(results[active])
      else if (isAddress || active === results.length) void lookupAddress()
      else if (results.length > 0) pick(results[0])
      else void lookupAddress()
    }
  }

  return (
    <div className="search" role="search">
      <div className="search-field">
        <svg className="search-icon" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          type="search"
          value={q}
          placeholder="Search a county, city, or project address"
          aria-label="Search a county, city, or project address"
          role="combobox"
          aria-expanded={open && rowCount > 0}
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
        {busy && <span className="spinner" aria-label="Looking up address" />}
      </div>
      {open && rowCount > 0 && (
        <ul className="search-results" id={listId} role="listbox">
          {results.map((j, i) => (
            <li
              key={j.fips}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(j)}
            >
              <span className="sr-name">
                {j.name}, {j.state_code}
              </span>
              <span className="sr-meta">
                {j.is_pilot && <span className="tag tag-brand">Pilot</span>}
                {TYPE_LABEL[j.type]}
              </span>
            </li>
          ))}
          {showAddressRow && (
            <li
              id={`${listId}-${results.length}`}
              role="option"
              aria-selected={active === results.length}
              className={`sr-address ${active === results.length ? 'active' : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void lookupAddress()}
            >
              <span className="sr-name">Look up address “{q.trim()}”</span>
              <span className="sr-meta">Enter ↵</span>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
