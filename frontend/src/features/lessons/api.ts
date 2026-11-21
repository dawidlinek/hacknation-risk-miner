import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { LessonsDigest } from '@/api/contracts/memory'

export const lessonsQuery = (sector = 'wod-kan') =>
  queryOptions({
    queryKey: ['analytics', 'lessons', sector],
    queryFn: () => contractFetch<LessonsDigest>('/api/analytics/lessons', { query: { sector } }),
  })
