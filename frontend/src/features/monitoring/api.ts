import { type Query, queryOptions } from '@tanstack/react-query'
import {
  adaptContract,
  adaptRegionDetail,
  adaptRegions,
  adaptSignals,
  type RealContract,
  type RealRegionDetail,
  type RealRegions,
  type RealSignals,
} from '@/api/adapters/monitoring'
import { contractFetch } from '@/api/client'
import type { RegionLevel } from '@/api/contracts/monitoring'

/** While the replay date changes keep the previous answer on screen (same scope only), so the map never flashes empty. */
const scoped =
  <T>(scope: readonly unknown[]) =>
  (prev: T | undefined, prevQuery: Query<T> | undefined) =>
    prevQuery && scope.every((v, i) => prevQuery.queryKey[i] === v) ? prev : undefined

/** Filter bar of the map (Podsektor, Wartość, Lata); every monitoring query takes the same filters. */
export interface MonFilters {
  subsector?: string
  value?: string
  year?: number
}

/** Contract value buckets, gross (monitoring compares contract values, which are gross). */
export const VALUE_BUCKETS: { key: string; label: string; min?: number; max?: number }[] = [
  { key: 'do1', label: 'do 1 mln zł', max: 1_000_000 },
  { key: '1-5', label: '1 do 5 mln zł', min: 1_000_000, max: 5_000_000 },
  { key: '5-20', label: '5 do 20 mln zł', min: 5_000_000, max: 20_000_000 },
  { key: 'ponad20', label: 'ponad 20 mln zł', min: 20_000_000 },
]
export const YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

export function filterParams(f: MonFilters | undefined) {
  const b = VALUE_BUCKETS.find((x) => x.key === f?.value)
  return {
    subsector: f?.subsector || undefined,
    value_min: b?.min,
    value_max: b?.max,
    year_from: f?.year,
    year_to: f?.year,
  }
}
const fkey = (f: MonFilters | undefined) => `${f?.subsector ?? ''}|${f?.value ?? ''}|${f?.year ?? ''}`

/** Per-level stats for every metric in one request (the toolbar switches metric client-side). */
export const regionsQuery = (level: RegionLevel, parent?: string, asOf?: string | null, f?: MonFilters) =>
  queryOptions({
    queryKey: ['monitoring', 'regions', level, parent ?? null, fkey(f), asOf ?? null],
    queryFn: async () =>
      adaptRegions(
        await contractFetch<RealRegions>('/api/monitoring/regions', {
          query: { level, parent, as_of: asOf ?? undefined, ...filterParams(f) },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'regions', level, parent ?? null, fkey(f)]),
  })

export const regionDetailQuery = (terc: string, asOf?: string | null, f?: MonFilters) =>
  queryOptions({
    queryKey: ['monitoring', 'region', terc, fkey(f), asOf ?? null],
    queryFn: async () =>
      adaptRegionDetail(
        await contractFetch<RealRegionDetail>(`/api/monitoring/regions/${terc}`, {
          query: { as_of: asOf ?? undefined, ...filterParams(f) },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'region', terc, fkey(f)]),
  })

/** Signals of a region (terc + level), biggest overdue first; the backend caps `limit` at 500. */
export const signalsQuery = (
  terc: string | null,
  level: RegionLevel | null,
  q?: string,
  asOf?: string | null,
  f?: MonFilters,
) =>
  queryOptions({
    queryKey: ['monitoring', 'signals', terc, level, q ?? '', fkey(f), asOf ?? null],
    queryFn: async () =>
      adaptSignals(
        await contractFetch<RealSignals>('/api/monitoring/signals', {
          query: {
            terc: terc ?? undefined,
            level: level ?? undefined,
            q: q || undefined,
            limit: 500,
            as_of: asOf ?? undefined,
            ...filterParams(f),
          },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'signals', terc, level, q ?? '', fkey(f)]),
  })

export const contractQuery = (id: string) =>
  queryOptions({
    queryKey: ['monitoring', 'contract', id],
    queryFn: async () => adaptContract(await contractFetch<RealContract>(`/api/monitoring/contracts/${id}`)),
  })

export const signalsCsvUrl = (terc: string, level: RegionLevel) =>
  `/api/export/signals.csv?terc=${terc}&level=${level}&sep=semicolon`

/** Subsectors of the public sector pack (approved rows), for the Podsektor filter. */
export const subsectorsQuery = queryOptions({
  queryKey: ['monitoring', 'subsectors', 'wod-kan'],
  queryFn: () =>
    contractFetch<{ code: string; name: string }[]>('/api/catalogue/subsector', {
      query: { sector: 'wod-kan', status: 'approved' },
    }),
  staleTime: 60 * 60_000,
})
