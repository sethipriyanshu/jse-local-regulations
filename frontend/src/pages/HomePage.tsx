import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import JurisdictionPanel from '../components/JurisdictionPanel'
import SearchBox from '../components/SearchBox'
import UsMap, { type MapFocus } from '../components/UsMap'
import { ApiError, api, type Health } from '../lib/api'
import { LOWER_48, bboxOf, loadUsGeo, unionBbox, type Bbox, type UsGeo } from '../lib/geo'
import {
  getCoverage,
  getJurisdiction,
  mapStatus,
  resolveAddress,
  type CoverageItem,
  type Jurisdiction,
  type JurisdictionDetail,
  type MapStatus,
  type Resolved,
} from '../lib/jurisdictions'
import { METROS, type Metro } from '../lib/metros'

export default function HomePage() {
  const [params, setParams] = useSearchParams()
  const selectedFips = params.get('j')

  const [geo, setGeo] = useState<UsGeo | null>(null)
  const [geoError, setGeoError] = useState(false)
  const [coverage, setCoverage] = useState<CoverageItem[]>([])
  const [detail, setDetail] = useState<JurisdictionDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [address, setAddress] = useState<Resolved | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [flyOnLoad, setFlyOnLoad] = useState(true) // fly to a ?j= deep link on first load

  useEffect(() => {
    loadUsGeo().then(setGeo).catch(() => setGeoError(true))
    getCoverage().then(setCoverage).catch(() => setCoverage([]))
  }, [])

  const statusByFips = useMemo(() => {
    const m = new Map<string, MapStatus>()
    for (const c of coverage) if (c.fips.length === 5) m.set(c.fips, mapStatus(c))
    return m
  }, [coverage])

  const flyTo = useCallback((bbox: Bbox | null) => {
    if (bbox) setFocus((f) => ({ bbox, seq: (f?.seq ?? 0) + 1 }))
  }, [])

  const bboxForDetail = useCallback(
    (d: JurisdictionDetail): Bbox | null => {
      if (!geo) return null
      const j = d.jurisdiction
      if (j.fips.length === 2) {
        const st = geo.states.features.find((f) => f.properties.GEOID === j.fips)
        return st ? bboxOf(st.geometry) : null
      }
      const fipsList = j.fips.length === 5 ? [j.fips] : d.counties.map((c) => c.fips)
      return unionBbox(
        fipsList.flatMap((f) => {
          const feat = geo.countyByFips.get(f)
          return feat ? [bboxOf(feat.geometry)] : []
        }),
      )
    },
    [geo],
  )

  // Load the selected jurisdiction whenever ?j= changes.
  useEffect(() => {
    setDetail(null)
    setDetailError(null)
    if (!selectedFips) return
    const ctrl = new AbortController()
    getJurisdiction(selectedFips, ctrl.signal)
      .then(setDetail)
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) {
          setDetailError(e instanceof ApiError ? e.message : 'Could not load this jurisdiction')
        }
      })
    return () => ctrl.abort()
  }, [selectedFips])

  // Fly once the detail (and boundaries) are available, if this selection asked for it.
  useEffect(() => {
    if (!flyOnLoad || !detail || !geo || address) return
    flyTo(bboxForDetail(detail))
    setFlyOnLoad(false)
  }, [flyOnLoad, detail, geo, address, flyTo, bboxForDetail])

  const select = useCallback(
    (fips: string, opts: { fly: boolean; keepAddress?: boolean }) => {
      if (!opts.keepAddress) setAddress(null)
      setFlyOnLoad(opts.fly)
      setParams(fips ? { j: fips } : {})
    },
    [setParams],
  )

  const onAddress = useCallback(
    async (q: string) => {
      setNotice(null)
      try {
        const r = await resolveAddress(q)
        if (!r.county_fips) throw new ApiError(404, 'That address did not resolve to a county.')
        setAddress(r)
        select(r.county_fips, { fly: false, keepAddress: true })
        flyTo([r.lng - 0.3, r.lat - 0.22, r.lng + 0.3, r.lat + 0.22])
      } catch (e) {
        setNotice(e instanceof ApiError ? e.message : 'Address lookup failed. Try again.')
      }
    },
    [select, flyTo],
  )

  const highlighted = useMemo(() => {
    if (!detail || detail.jurisdiction.fips !== selectedFips) return []
    const j = detail.jurisdiction
    if (j.fips.length === 5) return [j.fips]
    if (j.fips.length === 7) return detail.counties.map((c) => c.fips)
    return []
  }, [detail, selectedFips])

  const onMetro = useCallback((m: Metro) => select(m.county, { fly: true }), [select])

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(t)
  }, [notice])

  return (
    <div className="home">
      <section className="map-stage" aria-label="Map">
        {geo ? (
          <UsMap
            geo={geo}
            statusByFips={statusByFips}
            selected={highlighted}
            focus={focus}
            pin={address ? { lng: address.lng, lat: address.lat } : null}
            metros={METROS}
            onSelect={(fips) => select(fips, { fly: false })}
            onMetro={onMetro}
          />
        ) : (
          <div className="map-loading">
            {geoError ? 'Could not load map boundaries. Refresh to try again.' : 'Loading map…'}
          </div>
        )}
        <div className="map-overlay-top">
          <SearchBox
            onJurisdiction={(j: Jurisdiction) => select(j.fips, { fly: true })}
            onAddress={onAddress}
          />
          {notice && (
            <div className="map-notice" role="status">
              {notice}
            </div>
          )}
        </div>
      </section>

      <aside className="side-panel" key={selectedFips ?? 'home'}>
        {selectedFips ? (
          <JurisdictionPanel
            detail={detail}
            loading={!detail && !detailError}
            error={detailError}
            address={address}
            onSelect={(fips) => select(fips, { fly: true })}
            onClose={() => {
              select('', { fly: false })
              flyTo(LOWER_48)
            }}
          />
        ) : (
          <Overview onMetro={onMetro} />
        )}
      </aside>
    </div>
  )
}

function Overview({ onMetro }: { onMetro: (m: Metro) => void }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)

  useEffect(() => {
    api<Health>('/health')
      .then(setHealth)
      .catch(() => setHealthError(true))
  }, [])

  return (
    <>
      <p className="eyebrow">Pilot metros</p>
      <h1 className="panel-title">Local MEP regulations</h1>
      <p className="panel-sub">
        Select a county on the map, search a place, or enter a project address to see which state,
        county, and city rules apply.
      </p>
      <div className="chip-row">
        {METROS.map((m) => (
          <button key={m.key} type="button" className="chip" onClick={() => onMetro(m)}>
            {m.label}
          </button>
        ))}
      </div>

      <div className="status-card card">
        <span
          className={`dot ${health?.status === 'ok' ? 'dot-ok' : healthError ? 'dot-bad' : 'dot-warn'}`}
        />
        <div>
          <strong>System status</strong>
          <p>
            {healthError && 'API unreachable'}
            {!healthError && !health && 'Checking…'}
            {health && `API ${health.status} · database ${health.db} · ${health.env}`}
          </p>
        </div>
      </div>
    </>
  )
}
