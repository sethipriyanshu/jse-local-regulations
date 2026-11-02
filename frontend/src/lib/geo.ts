import type { Feature, FeatureCollection, Geometry, Position } from 'geojson'
import { feature } from 'topojson-client'
import type { Topology } from 'topojson-specification'

export type CountyProps = { GEOID: string; NAME: string; STUSPS: string; STATE_NAME: string }
export type StateProps = { GEOID: string; NAME: string; STUSPS: string }
export type Bbox = [number, number, number, number] // west, south, east, north

export type UsGeo = {
  states: FeatureCollection<Geometry, StateProps>
  counties: FeatureCollection<Geometry, CountyProps>
  countyByFips: Map<string, Feature<Geometry, CountyProps>>
}

/** Contiguous US, the default view. */
export const LOWER_48: Bbox = [-125, 24.4, -66.9, 49.5]

let cache: Promise<UsGeo> | null = null

/** Load and convert the Census boundaries built by scripts/build_geo.sh (cached). */
export function loadUsGeo(): Promise<UsGeo> {
  cache ??= fetch('/geo/us.topo.json')
    .then((r) => {
      if (!r.ok) throw new Error(`boundaries: HTTP ${r.status}`)
      return r.json() as Promise<Topology>
    })
    .then((topo) => {
      const states = feature(topo, topo.objects.states) as FeatureCollection<Geometry, StateProps>
      const counties = feature(topo, topo.objects.counties) as FeatureCollection<
        Geometry,
        CountyProps
      >
      const countyByFips = new Map(counties.features.map((f) => [f.properties.GEOID, f]))
      return { states, counties, countyByFips }
    })
  cache.catch(() => {
    cache = null // allow a retry after a failed load
  })
  return cache
}

/** Bounding box of a polygon feature. Ignores the antimeridian (only matters for Alaska). */
export function bboxOf(geometry: Geometry): Bbox {
  let w = Infinity
  let s = Infinity
  let e = -Infinity
  let n = -Infinity
  const visit = (p: Position) => {
    if (p[0] < w) w = p[0]
    if (p[0] > e) e = p[0]
    if (p[1] < s) s = p[1]
    if (p[1] > n) n = p[1]
  }
  const walk = (coords: unknown): void => {
    if (typeof (coords as Position)[0] === 'number') visit(coords as Position)
    else (coords as unknown[]).forEach(walk)
  }
  if (geometry.type === 'GeometryCollection') geometry.geometries.forEach((g) => walk(coordsOf(g)))
  else walk(coordsOf(geometry))
  return [w, s, e, n]
}

function coordsOf(g: Geometry): unknown {
  return g.type === 'GeometryCollection' ? [] : g.coordinates
}

export function unionBbox(boxes: Bbox[]): Bbox | null {
  if (boxes.length === 0) return null
  return boxes.reduce((a, b) => [
    Math.min(a[0], b[0]),
    Math.min(a[1], b[1]),
    Math.max(a[2], b[2]),
    Math.max(a[3], b[3]),
  ])
}
