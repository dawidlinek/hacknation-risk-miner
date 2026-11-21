import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { RedPen } from './logic'

/** GET /api/analyses/{id}/redpen/{doc}?pages=all; polls while the AI scan job is queued or running. */
export const redpenQuery = (id: string, doc: number) =>
  queryOptions({
    queryKey: ['analysis', id, 'redpen', doc],
    queryFn: () =>
      contractFetch<RedPen>(`/api/analyses/${encodeURIComponent(id)}/redpen/${doc}`, {
        query: { pages: 'all' },
      }),
    staleTime: 30_000,
    refetchInterval: (q) =>
      q.state.data?.status === 'queued' || q.state.data?.status === 'running' ? 4000 : false,
  })
