import { queryOptions } from '@tanstack/react-query'
import type { Feature, FeatureCollection, Geometry, Position } from 'geojson'
import type { GeoProps } from '@/api/contracts/monitoring'

export type GeoFC = FeatureCollection<Geometry, GeoProps>
export type GeoFeature = Feature<Geometry, GeoProps>
export type LngLat = [number, number]
export type Bbox = [number, number, number, number] // west, south, east, north

const getJson = async <T>(url: string): Promise<T> => {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`geo ${url}: ${r.status}`)
  return (await r.json()) as T
}

/** Static boundaries from public/geo (scripts/geo-split.mjs). */
export const wojGeoQuery = queryOptions({
  queryKey: ['geo', 'woj'],
  queryFn: () => getJson<GeoFC>('/geo/woj.json'),
  staleTime: Number.POSITIVE_INFINITY,
})
export const powGeoQuery = (woj: string) =>
  queryOptions({
    queryKey: ['geo', 'pow', woj],
    queryFn: () => getJson<GeoFC>(`/geo/pow/${woj}.json`),
    staleTime: Number.POSITIVE_INFINITY,
  })
export const gmiGeoQuery = (pow: string) =>
  queryOptions({
    queryKey: ['geo', 'gmi', pow],
    queryFn: () => getJson<GeoFC>(`/geo/gmi/${pow}.json`),
    staleTime: Number.POSITIVE_INFINITY,
  })
export const labelsQuery = (name: 'woj-labels' | 'pow-centroids' | 'gmi-centroids') =>
  queryOptions({
    queryKey: ['geo', name],
    queryFn: () => getJson<Record<string, LngLat>>(`/geo/${name}.json`),
    staleTime: Number.POSITIVE_INFINITY,
  })

export const POLAND_BBOX: Bbox = [14.1, 49.0, 24.15, 54.85]

function eachPosition(g: Geometry, fn: (p: Position) => void) {
  if (g.type === 'Polygon') for (const ring of g.coordinates) for (const p of ring) fn(p)
  else if (g.type === 'MultiPolygon')
    for (const poly of g.coordinates) for (const ring of poly) for (const p of ring) fn(p)
}

export function bboxOf(features: GeoFeature[]): Bbox | null {
  let w = Number.POSITIVE_INFINITY
  let s = Number.POSITIVE_INFINITY
  let e = Number.NEGATIVE_INFINITY
  let n = Number.NEGATIVE_INFINITY
  for (const f of features)
    eachPosition(f.geometry, ([x, y]) => {
      if (x < w) w = x
      if (x > e) e = x
      if (y < s) s = y
      if (y > n) n = y
    })
  return Number.isFinite(w) ? [w, s, e, n] : null
}

/** SVG path (viewBox 0 0 100 100) for a region thumbnail, equirectangular with cos(lat) correction. */
export function outlinePath(f: GeoFeature, size = 100, pad = 4): string {
  const b = bboxOf([f])
  if (!b) return ''
  const k = Math.cos((((b[1] + b[3]) / 2) * Math.PI) / 180)
  const w = (b[2] - b[0]) * k
  const h = b[3] - b[1]
  const scale = (size - 2 * pad) / Math.max(w, h)
  const ox = (size - w * scale) / 2
  const oy = (size - h * scale) / 2
  const proj = ([x, y]: Position) =>
    `${(ox + (x - b[0]) * k * scale).toFixed(1)} ${(oy + (b[3] - y) * scale).toFixed(1)}`
  const rings: Position[][] =
    f.geometry.type === 'Polygon'
      ? f.geometry.coordinates
      : f.geometry.type === 'MultiPolygon'
        ? f.geometry.coordinates.flat()
        : []
  return rings.map((r) => `M${r.map(proj).join('L')}Z`).join('')
}

/** Does this browser give us a WebGL context? (the map degrades to the list when not) */
export function hasWebGL(): boolean {
  try {
    const c = document.createElement('canvas')
    return Boolean(c.getContext('webgl2') ?? c.getContext('webgl'))
  } catch {
    return false
  }
}
