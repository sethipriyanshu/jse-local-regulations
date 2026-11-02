import {
  createContext,
  useContext,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { ApiError } from '../lib/api'
import {
  addRule,
  getSavedName,
  getTaxonomy,
  saveName,
  submitSource,
  uploadPdf,
  type Taxonomy,
} from '../lib/sources'

export type ContributeMode = 'url' | 'pdf' | 'manual'

type Props = {
  fips: string
  placeName: string
  isAdmin: boolean
  initialMode: ContributeMode
  onDone: (message: string) => void
  onCancel: () => void
}

/** Suggest a URL, upload a PDF, or type a rule in. Users' submissions go to the admin
 * queue; admin URL/PDF additions are approved and processed right away. */
export default function ContributeForms(props: Props) {
  const { fips, placeName, isAdmin, initialMode, onDone, onCancel } = props
  const [mode, setMode] = useState<ContributeMode>(initialMode)
  const [name, setName] = useState(getSavedName)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setError(null)
    try {
      if (name) saveName(name)
      onDone(await action())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const queued = isAdmin
    ? 'Added and approved. Fetching and extracting now; results appear in a minute.'
    : 'Thanks! Sent to the admin review queue.'

  return (
    <NameContext.Provider value={{ name, setName }}>
    <div className="contribute card">
      <div className="contribute-head">
        <div>
          <p className="eyebrow">Contribute</p>
          <h3>Add information for {placeName}</h3>
        </div>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Close">
          ×
        </button>
      </div>
      <div className="seg" role="tablist">
        {(
          [
            ['url', 'Website'],
            ['pdf', 'PDF'],
            ['manual', 'Type it in'],
          ] as const
        ).map(([m, label]) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={`seg-btn ${mode === m ? 'active' : ''}`}
            onClick={() => {
              setMode(m)
              setError(null)
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === 'url' && (
        <UrlForm busy={busy} onSubmit={(url, note) => run(async () => {
          await submitSource(fips, url, note, name)
          return queued
        })} />
      )}
      {mode === 'pdf' && (
        <PdfForm busy={busy} onSubmit={(file, title) => run(async () => {
          await uploadPdf(fips, file, title, name)
          return queued
        })} />
      )}
      {mode === 'manual' && (
        <ManualForm busy={busy} onSubmit={(input) => run(async () => {
          await addRule(fips, { ...input, submitted_by_name: name || undefined })
          return 'Saved as pending. It shows here once an admin verifies it.'
        })} />
      )}

      {error && <p className="form-error" role="alert">{error}</p>}
    </div>
    </NameContext.Provider>
  )
}

function Submit({ busy, children }: { busy: boolean; children: ReactNode }) {
  const { name, setName } = useContext(NameContext)
  return (
    <>
      <label className="field">
        <span>Your name (optional, for attribution)</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={128} />
      </label>
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? 'Sending…' : children}
      </button>
    </>
  )
}

const NameContext = createContext<{ name: string; setName: (n: string) => void }>({
  name: '',
  setName: () => {},
})

function UrlForm({ busy, onSubmit }: { busy: boolean; onSubmit: (url: string, note: string) => void }) {
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  return (
    <form
      className="form-stack"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        onSubmit(url, note)
      }}
    >
      <p className="form-hint">
        Official pages work best: the building department, adopted-codes page, or permit
        requirements. Code libraries like Municode block automated reading; save the section as a
        PDF and upload it instead.
      </p>
      <label className="field">
        <span>Page URL</span>
        <input
          type="url"
          required
          placeholder="https://www.example.gov/building/adopted-codes"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </label>
      <label className="field">
        <span>Note for the reviewer (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      </label>
      <Submit busy={busy}>Suggest source</Submit>
    </form>
  )
}

function PdfForm({ busy, onSubmit }: { busy: boolean; onSubmit: (file: File, title: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  return (
    <form
      className="form-stack"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        if (file) onSubmit(file, title)
      }}
    >
      <p className="form-hint">An ordinance, adoption notice, or code section saved as PDF (max 25 MB).</p>
      <label className="field">
        <span>PDF file</span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          required
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label className="field">
        <span>Title (optional)</span>
        <input
          placeholder="Ord. 2024-15: Adoption of 2021 I-Codes"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={512}
        />
      </label>
      <Submit busy={busy}>Upload PDF</Submit>
    </form>
  )
}

type ManualInput = {
  title: string
  summary: string
  discipline: string
  category: string
  code_ref?: string
  code_edition?: string
  effective_on?: string
  excerpt?: string
  source_url?: string
}

function ManualForm({ busy, onSubmit }: { busy: boolean; onSubmit: (input: ManualInput) => void }) {
  const [tax, setTax] = useState<Taxonomy | null>(null)
  const [f, setF] = useState<ManualInput>({ title: '', summary: '', discipline: '', category: '' })
  const set = (k: keyof ManualInput) => (e: { target: { value: string } }) =>
    setF((prev) => ({ ...prev, [k]: e.target.value }))

  useEffect(() => {
    getTaxonomy().then(setTax).catch(() => setTax({ disciplines: [], categories: [] }))
  }, [])

  return (
    <form
      className="form-stack"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        const clean = Object.fromEntries(
          Object.entries(f).filter(([, v]) => typeof v === 'string' && v.trim() !== ''),
        ) as ManualInput
        onSubmit(clean)
      }}
    >
      <label className="field">
        <span>Title</span>
        <input required minLength={3} value={f.title} onChange={set('title')}
          placeholder="Sealed MEP drawings required for commercial permits" />
      </label>
      <div className="field-row">
        <label className="field">
          <span>Discipline</span>
          <select required value={f.discipline} onChange={set('discipline')}>
            <option value="">Choose…</option>
            {tax?.disciplines.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Category</span>
          <select required value={f.category} onChange={set('category')}>
            <option value="">Choose…</option>
            {tax?.categories.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </label>
      </div>
      <label className="field">
        <span>Summary</span>
        <textarea required minLength={3} rows={3} value={f.summary} onChange={set('summary')} />
      </label>
      <div className="field-row">
        <label className="field">
          <span>Code reference</span>
          <input value={f.code_ref ?? ''} onChange={set('code_ref')} placeholder="NEC §210.8" />
        </label>
        <label className="field">
          <span>Edition</span>
          <input value={f.code_edition ?? ''} onChange={set('code_edition')} placeholder="2020" />
        </label>
        <label className="field">
          <span>Effective</span>
          <input type="date" value={f.effective_on ?? ''} onChange={set('effective_on')} />
        </label>
      </div>
      <label className="field">
        <span>Exact quote from the source (optional)</span>
        <textarea rows={2} value={f.excerpt ?? ''} onChange={set('excerpt')} />
      </label>
      <label className="field">
        <span>Source URL (optional)</span>
        <input type="url" value={f.source_url ?? ''} onChange={set('source_url')} />
      </label>
      <Submit busy={busy}>Save for review</Submit>
    </form>
  )
}
