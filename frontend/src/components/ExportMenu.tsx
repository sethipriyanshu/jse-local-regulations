import { useEffect, useRef, useState } from 'react'
import { exportUrl, type ExportFormat } from '../lib/regulations'

type Props = { fips: string; stack: string[]; address: string | null }

const FORMATS: { f: ExportFormat; label: string; hint: string }[] = [
  { f: 'pdf', label: 'PDF', hint: 'Branded report' },
  { f: 'docx', label: 'Word', hint: 'Editable .docx' },
  { f: 'json', label: 'JSON', hint: 'Schema v1, for tools' },
]

/** Download the merged regulations for this stack (PLAN.md C1–C4). */
export default function ExportMenu({ fips, stack, address }: Props) {
  const [open, setOpen] = useState(false)
  const [includePending, setIncludePending] = useState(true)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div className="export-menu" ref={ref}>
      <button type="button" className="btn btn-secondary btn-sm" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        Export ▾
      </button>
      {open && (
        <div className="export-pop card" role="menu">
          <p className="eyebrow">Download everything that applies here</p>
          {FORMATS.map(({ f, label, hint }) => (
            <a key={f} role="menuitem" className="export-item" download
              href={exportUrl(fips, f, { stack, includePending, address })}
              onClick={() => setOpen(false)}>
              <strong>{label}</strong>
              <span>{hint}</span>
            </a>
          ))}
          <label className="check">
            <input type="checkbox" checked={includePending}
              onChange={(e) => setIncludePending(e.target.checked)} />
            Include items pending review
          </label>
        </div>
      )}
    </div>
  )
}
