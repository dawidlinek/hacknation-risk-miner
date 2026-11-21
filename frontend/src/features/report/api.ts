import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { Report } from './logic'

/** Shared cache key for the analysis record: ['analysis', id, 'report'] (layout, 1.2, packs). */
export const reportQuery = (id: string) =>
  queryOptions({
    queryKey: ['analysis', id, 'report'],
    queryFn: () => contractFetch<Report>(`/api/analyses/${encodeURIComponent(id)}`),
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : false),
  })

export const runAnalysis = (id: string) =>
  contractFetch<{ id: string; version: number; status: string; redpen_job_id?: number | null }>(
    `/api/analyses/${encodeURIComponent(id)}/run`,
    { method: 'POST', json: {} },
  )

export const addClauseToPack = (id: string, code: string, text?: string) =>
  contractFetch<{ code: string; in_pack: boolean }>(`/api/analyses/${encodeURIComponent(id)}/pack/clauses`, {
    method: 'POST',
    json: { code, ...(text ? { text } : {}) },
  })

export const decideItem = (
  id: string,
  itemId: number,
  body: { action: 'approve' | 'edit' | 'reject'; reason?: string; value?: unknown; add_clause?: string },
) =>
  contractFetch<{ item_id: number; review_status: string; in_pack: boolean }>(
    `/api/analyses/${encodeURIComponent(id)}/items/${itemId}/decision`,
    { method: 'POST', json: body },
  )
