import { queryOptions } from '@tanstack/react-query'
import { adaptGraph, type RealGraph } from '@/api/adapters/graph'
import { contractFetch } from '@/api/client'

export const projectGraphQuery = (id: string) =>
  queryOptions({
    queryKey: ['project', id, 'graph'],
    queryFn: async () =>
      adaptGraph(await contractFetch<RealGraph>(`/api/projects/${encodeURIComponent(id)}/graph`)),
  })
