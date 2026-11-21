import { keepPreviousData, queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, contractFetch } from '@/api/client'
import { adaptDiff, adaptEntry, adaptHistory } from './adapt'
import { dayRange, GLOBAL_CATEGORY } from './logic'
import type { GlobalKind, RealAuditPage, RealCompare, RealHistory } from './types'

export const projectHistoryQuery = (id: string) =>
  queryOptions({
    queryKey: ['project', id, 'history'],
    queryFn: async () =>
      adaptHistory(await contractFetch<RealHistory>(`/api/projects/${encodeURIComponent(id)}/history`)),
  })

export const projectDiffQuery = (id: string, from: string | null, to: string) =>
  queryOptions({
    queryKey: ['project', id, 'history', 'compare', from, to],
    enabled: !!from,
    queryFn: async () =>
      adaptDiff(
        await contractFetch<RealCompare>(`/api/projects/${encodeURIComponent(id)}/history/compare`, {
          query: { from, to },
        }),
      ),
  })

export const globalAuditQuery = (kind: GlobalKind, day: string | null) =>
  queryOptions({
    queryKey: ['audit', 'global', kind, day],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const range = day ? dayRange(day) : null
      const page = await contractFetch<RealAuditPage>('/api/audit', {
        query: { category: GLOBAL_CATEGORY[kind], since: range?.since, until: range?.until, limit: 200 },
      })
      return { total: page.total, entries: page.items.map(adaptEntry) }
    },
  })

/** CSV/JSON of the same selection (`/api/export/audit.{fmt}`; Polish Excel separator for CSV). */
export function auditExportUrl(fmt: string, kind: GlobalKind, day: string | null): string {
  const q = new URLSearchParams()
  const cat = GLOBAL_CATEGORY[kind]
  if (cat) q.set('category', cat)
  const r = day ? dayRange(day) : null
  if (r) {
    q.set('since', r.since)
    q.set('until', r.until)
  }
  if (fmt === 'csv') q.set('sep', 'semicolon')
  const s = q.toString()
  return `/api/export/audit.${fmt}${s ? `?${s}` : ''}`
}

export function useRestore(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, reason }: { entryId: number; reason: string }) =>
      contractFetch<{ review_id: number; audit_id: number }>(`/api/audit/${entryId}/restore`, {
        method: 'POST',
        json: { reason },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}

/** 409 (approved data protected, stale row, already restored) and 403 read_only show the backend's Polish reason. */
export const restoreErrorMessage = (e: unknown): string => {
  if (e instanceof ApiError) {
    if (e.status === 403)
      return e.code === 'read_only'
        ? 'To konto jest tylko do odczytu.'
        : 'Przywrócenie wymaga konta eksperta.'
    return e.detail
  }
  return 'Nie udało się przywrócić wartości.'
}
