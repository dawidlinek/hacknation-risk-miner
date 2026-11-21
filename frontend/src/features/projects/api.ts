import { queryOptions } from '@tanstack/react-query'
import {
  adaptCard,
  adaptProjectsPage,
  type RealCard,
  type RealProjectsPage,
  type RealProjectsStats,
} from '@/api/adapters/projects'
import { contractFetch } from '@/api/client'

/** Whole pilot list (22 rows): sorting, filtering and paging run client-side (frontend.md 2.2, <= 100 rows). */
export const projectsTableQuery = queryOptions({
  queryKey: ['projects', 'table'],
  queryFn: async () => {
    const [page, stats] = await Promise.all([
      contractFetch<RealProjectsPage>('/api/projects', {
        query: { limit: 100, offset: 0, sort: '-delay_days' },
      }),
      contractFetch<RealProjectsStats>('/api/projects/stats').catch(() => null),
    ])
    return adaptProjectsPage(page, stats)
  },
})

export const projectCardQuery = (id: string) =>
  queryOptions({
    queryKey: ['project', id, 'card'],
    queryFn: async () =>
      adaptCard(await contractFetch<RealCard>(`/api/projects/${encodeURIComponent(id)}/card`)),
  })
