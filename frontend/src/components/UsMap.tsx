import maplibregl, { type ExpressionSpecification, type MapGeoJSONFeature } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { LOWER_48, type Bbox, type UsGeo } from '../lib/geo'
import { STATUS_LABEL, type MapStatus } from '../lib/jurisdictions'
import type { Metro } from '../lib/metros'

/** Map colors. Kept in sync with theme.css by hand (MapLibre can't read CSS variables). */
export const STATUS_COLOR: Record<MapStatus, string> = {
  none: '#ffffff',
  pilot: '#fbe3d3',
  partial: '#e8b48f',
  verified: '#4f9a65',
  changes_pending: '#d9a21b',
}
const BRAND = '#b52025'
const INK = '#1d1d1f'

export type MapFocus = { bbox: Bbox; seq: number }

type Props = {
  geo: UsGeo
  statusByFips: Map<string, MapStatus>
  selected: string[]
  focus: MapFocus | null
  pin: { lng: number; lat: number } | null
  metros: Metro[]
  onSelect: (fips: string) => void
  onMetro: (metro: Metro) => void
}

type Hover = { x: number; y: number; name: string; state: string; status: MapStatus }

function fillExpression(statusByFips: Map<string, MapStatus>): ExpressionSpecification | string {
  const pairs: string[] = []
  statusByFips.forEach((status, fips) => {
    if (status !== 'none') pairs.push(fips, STATUS_COLOR[status])
  })
  if (pairs.length === 0) return STATUS_COLOR.none
  return ['match', ['get', 'GEOID'], ...pairs, STATUS_COLOR.none] as unknown as ExpressionSpecification
}

export default function UsMap(props: Props) {
  const { geo, statusByFips, selected, focus, pin, metros, onSelect, onMetro } = props
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState<Hover | null>(null)
  const selectedRef = useRef<string[]>([])
  const pinRef = useRef<maplibregl.Marker | null>(null)
  // Latest callbacks/status for map event handlers registered once.
  const live = useRef({ onSelect, onMetro, statusByFips })
  live.current = { onSelect, onMetro, statusByFips }

  // Create the map once.
  useEffect(() => {
    if (!container.current) return
    const map = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#eef1f4' } }],
      },
      bounds: LOWER_48,
      fitBoundsOptions: { padding: 24 },
      minZoom: 2.5,
      maxZoom: 11,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: { compact: true, customAttribution: 'Boundaries: US Census Bureau' },
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    mapRef.current = map

    map.on('load', () => {
      map.addSource('counties', { type: 'geojson', data: geo.counties, promoteId: 'GEOID' })
      map.addSource('states', { type: 'geojson', data: geo.states })
      map.addLayer({
        id: 'county-fill',
        type: 'fill',
        source: 'counties',
        paint: {
          'fill-color': fillExpression(live.current.statusByFips),
          'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.75, 1],
        },
      })
      map.addLayer({
        id: 'county-line',
        type: 'line',
        source: 'counties',
        paint: {
          'line-color': '#c9ced6',
          'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.2, 6, 0.6, 9, 1.2],
        },
      })
      map.addLayer({
        id: 'state-line',
        type: 'line',
        source: 'states',
        paint: {
          'line-color': '#7d8590',
          'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.7, 8, 2],
        },
      })
      map.addLayer({
        id: 'county-hover',
        type: 'line',
        source: 'counties',
        paint: {
          'line-color': INK,
          'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 1.5, 0],
        },
      })
      map.addLayer({
        id: 'county-selected',
        type: 'line',
        source: 'counties',
        paint: {
          'line-color': BRAND,
          'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 3, 0],
        },
      })
      setReady(true)
    })

    let hovered: string | number | undefined
    const clearHover = () => {
      if (hovered !== undefined) map.setFeatureState({ source: 'counties', id: hovered }, { hover: false })
      hovered = undefined
      map.getCanvas().style.cursor = ''
      setHover(null)
    }
    map.on('mousemove', 'county-fill', (e) => {
      const f = e.features?.[0] as MapGeoJSONFeature | undefined
      if (!f || f.id === undefined) return
      if (f.id !== hovered) {
        if (hovered !== undefined) map.setFeatureState({ source: 'counties', id: hovered }, { hover: false })
        hovered = f.id
        map.setFeatureState({ source: 'counties', id: f.id }, { hover: true })
      }
      map.getCanvas().style.cursor = 'pointer'
      const fips = String(f.id)
      setHover({
        x: e.point.x,
        y: e.point.y,
        name: f.properties.NAME,
        state: f.properties.STUSPS,
        status: live.current.statusByFips.get(fips) ?? 'none',
      })
    })
    map.on('mouseleave', 'county-fill', clearHover)
    // Overlays (search, legend) sit above the canvas, so the layer never sees the pointer leave.
    map.getCanvas().addEventListener('mouseleave', clearHover)
    map.on('click', 'county-fill', (e) => {
      const id = e.features?.[0]?.id
      if (id !== undefined) live.current.onSelect(String(id))
    })

    const markers = metros.map((m) => {
      const el = document.createElement('button')
      el.type = 'button'
      el.className = 'metro-pin'
      el.title = `${m.label} (JSE pilot metro)`
      el.setAttribute('aria-label', `Jump to ${m.label}`)
      el.addEventListener('click', (ev) => {
        ev.stopPropagation()
        live.current.onMetro(m)
      })
      return new maplibregl.Marker({ element: el }).setLngLat(m.center).addTo(map)
    })

    return () => {
      markers.forEach((mk) => mk.remove())
      map.remove()
      mapRef.current = null
    }
    // geo and metros are stable for the page's lifetime; handlers read `live`.
  }, [])

  // Coverage colors.
  useEffect(() => {
    const map = mapRef.current
    if (ready && map) map.setPaintProperty('county-fill', 'fill-color', fillExpression(statusByFips))
  }, [ready, statusByFips])

  // Selection outline.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    for (const id of selectedRef.current) map.setFeatureState({ source: 'counties', id }, { selected: false })
    for (const id of selected) map.setFeatureState({ source: 'counties', id }, { selected: true })
    selectedRef.current = selected
  }, [ready, selected])

  // Camera.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !focus) return
    const [w, s, e, n] = focus.bbox
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: 90, maxZoom: 8, duration: 900 },
    )
  }, [focus])

  // Address pin.
  useEffect(() => {
    const map = mapRef.current
    pinRef.current?.remove()
    pinRef.current = null
    if (!map || !pin) return
    const el = document.createElement('div')
    el.className = 'address-pin'
    pinRef.current = new maplibregl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([pin.lng, pin.lat])
      .addTo(map)
  }, [pin])

  return (
    <div className="map-wrap">
      <div ref={container} className="map-canvas" />
      {hover && (
        <div className="map-tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <strong>
            {hover.name}, {hover.state}
          </strong>
          <span>
            <i className="swatch" style={{ background: STATUS_COLOR[hover.status] }} />
            {STATUS_LABEL[hover.status]}
          </span>
        </div>
      )}
      <MapLegend />
    </div>
  )
}

function MapLegend() {
  const order: MapStatus[] = ['pilot', 'partial', 'verified', 'changes_pending', 'none']
  return (
    <div className="map-legend" aria-label="Map legend">
      {order.map((s) => (
        <span key={s}>
          <i className="swatch" style={{ background: STATUS_COLOR[s] }} />
          {STATUS_LABEL[s]}
        </span>
      ))}
    </div>
  )
}
