import { STATUS_COLOR } from './UsMap'
import {
  STATUS_LABEL,
  TYPE_LABEL,
  mapStatus,
  type Jurisdiction,
  type JurisdictionDetail,
  type Resolved,
} from '../lib/jurisdictions'

type Props = {
  detail: JurisdictionDetail | null
  loading: boolean
  error: string | null
  address: Resolved | null
  onSelect: (fips: string) => void
  onClose: () => void
}

function StatusBadge({ j }: { j: Jurisdiction }) {
  const s = mapStatus(j)
  return (
    <span className="status-badge">
      <i className="swatch" style={{ background: STATUS_COLOR[s] }} />
      {STATUS_LABEL[s]}
    </span>
  )
}

export default function JurisdictionPanel({ detail, loading, error, address, onSelect, onClose }: Props) {
  if (error) {
    return (
      <div className="jp">
        <PanelHeader onClose={onClose} />
        <p className="form-error">{error}</p>
      </div>
    )
  }
  if (loading || !detail) {
    return (
      <div className="jp" aria-busy="true">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-block" />
      </div>
    )
  }

  const j = detail.jurisdiction
  return (
    <div className="jp">
      <PanelHeader onClose={onClose} />

      {address && (
        <div className="address-card">
          <p className="eyebrow">Project address</p>
          <p className="address-line">{address.matched_address}</p>
          {address.unincorporated && (
            <p className="address-note">Unincorporated: county rules apply, no city layer.</p>
          )}
        </div>
      )}

      <nav className="stack-trail" aria-label="Jurisdiction stack">
        {detail.stack.map((s, i) => (
          <span key={s.fips}>
            {i > 0 && <span className="stack-sep">›</span>}
            {s.fips === j.fips ? (
              <span className="stack-current">{s.name}</span>
            ) : (
              <button type="button" className="link-btn" onClick={() => onSelect(s.fips)}>
                {s.name}
              </button>
            )}
          </span>
        ))}
      </nav>

      <h1 className="panel-title">
        {j.name}
        {j.type !== 'state' && j.type !== 'district' && <span className="title-state">, {j.state_code}</span>}
      </h1>
      <div className="badge-row">
        <span className="tag">{TYPE_LABEL[j.type]}</span>
        {j.is_pilot && <span className="tag tag-brand">Pilot</span>}
        <StatusBadge j={j} />
      </div>

      <section className="jp-section">
        <h2>Rules that apply here</h2>
        <ol className="layer-list">
          {(address ? address.stack : detail.stack).map((s) => (
            <li key={s.fips}>
              <div>
                <strong>{s.name}</strong>
                <span className="layer-type">{TYPE_LABEL[s.type]} layer</span>
              </div>
              <StatusBadge j={s} />
            </li>
          ))}
        </ol>
      </section>

      {detail.counties.length > 1 && (
        <section className="jp-section">
          <h2>Spans {detail.counties.length} counties</h2>
          <div className="chip-row">
            {detail.counties.map((c) => (
              <button key={c.fips} type="button" className="chip" onClick={() => onSelect(c.fips)}>
                {c.name}
              </button>
            ))}
          </div>
        </section>
      )}

      {detail.places.length > 0 && (
        <section className="jp-section">
          <h2>Cities in this county</h2>
          <div className="chip-row">
            {detail.places.map((p) => (
              <button key={p.fips} type="button" className="chip" onClick={() => onSelect(p.fips)}>
                {p.name}
                {p.is_pilot && <i className="chip-dot" aria-label="pilot" />}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="jp-section empty-state">
        <h2>No regulations recorded yet</h2>
        <p>
          {j.is_pilot
            ? 'This is a pilot jurisdiction. Sources are being collected and reviewed.'
            : 'This area is outside the pilot. You can still suggest an official source.'}
        </p>
        <button type="button" className="btn btn-secondary" disabled title="Arrives in week 3">
          Suggest a source
        </button>
      </section>
    </div>
  )
}

function PanelHeader({ onClose }: { onClose: () => void }) {
  return (
    <div className="jp-top">
      <button type="button" className="link-btn back-btn" onClick={onClose}>
        ← All pilot metros
      </button>
    </div>
  )
}
