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

/** Per-level stats for every metric in one request (the toolbar switches metric client-side). */
export const regionsQuery = (level: RegionLevel, parent?: string, asOf?: string | null) =>
  queryOptions({
    queryKey: ['monitoring', 'regions', level, parent ?? null, asOf ?? null],
    queryFn: async () =>
      adaptRegions(
        await contractFetch<RealRegions>('/api/monitoring/regions', {
          query: { level, parent, as_of: asOf ?? undefined },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'regions', level, parent ?? null]),
  })

export const regionDetailQuery = (terc: string, asOf?: string | null) =>
  queryOptions({
    queryKey: ['monitoring', 'region', terc, asOf ?? null],
    queryFn: async () =>
      adaptRegionDetail(
        await contractFetch<RealRegionDetail>(`/api/monitoring/regions/${terc}`, {
          query: { as_of: asOf ?? undefined },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'region', terc]),
  })

/** Signals of a region (terc + level), biggest overdue first; the backend caps `limit` at 500. */
export const signalsQuery = (
  terc: string | null,
  level: RegionLevel | null,
  q?: string,
  asOf?: string | null,
) =>
  queryOptions({
    queryKey: ['monitoring', 'signals', terc, level, q ?? '', asOf ?? null],
    queryFn: async () =>
      adaptSignals(
        await contractFetch<RealSignals>('/api/monitoring/signals', {
          query: {
            terc: terc ?? undefined,
            level: level ?? undefined,
            q: q || undefined,
            limit: 500,
            as_of: asOf ?? undefined,
          },
        }),
      ),
    staleTime: 5 * 60_000,
    placeholderData: scoped(['monitoring', 'signals', terc, level, q ?? '']),
  })

export const contractQuery = (id: string) =>
  queryOptions({
    queryKey: ['monitoring', 'contract', id],
    queryFn: async () => adaptContract(await contractFetch<RealContract>(`/api/monitoring/contracts/${id}`)),
  })

export const signalsCsvUrl = (terc: string, level: RegionLevel) =>
  `/api/export/signals.csv?terc=${terc}&level=${level}&sep=semicolon`
