import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { OrganizationMemory } from '@/api/contracts/memory'

export const organizationMemoryQuery = (nip: string) =>
  queryOptions({
    queryKey: ['organization', nip, 'memory'],
    queryFn: () => contractFetch<OrganizationMemory>(`/api/organizations/${encodeURIComponent(nip)}/memory`),
  })
