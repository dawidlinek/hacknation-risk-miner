import { queryOptions } from '@tanstack/react-query'
import { adaptCatalogue, type RealCatalogue } from '@/api/adapters/catalogue'
import { contractFetch } from '@/api/client'
import type { ProposalDecisionIn } from '@/api/contracts/catalogue'

export const catalogueQuery = queryOptions({
  queryKey: ['catalogue', 'view'],
  queryFn: async () =>
    adaptCatalogue(
      await contractFetch<RealCatalogue>('/api/catalogue/view', { query: { sector: 'wod-kan' } }),
    ),
  staleTime: 30_000,
})

export interface EditResult {
  code: string
  version: number
  status: string
  catalogue_version: string
}

/** PATCH one field of a risk; a successful edit creates a new catalogue version. */
export const patchRisk = (code: string, patch: { name?: string; description?: string }, comment = '') =>
  contractFetch<EditResult>(`/api/catalogue/risk/${encodeURIComponent(code)}`, {
    method: 'PATCH',
    json: { patch, comment },
  })

export const putWeights = (values: Record<string, number>) =>
  contractFetch<unknown>('/api/catalogue/similarity/weights', {
    method: 'PUT',
    json: {
      weights: Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v / 100])),
      comment: 'zmiana wag w Katalogu',
    },
  })

export const decideProposal = (id: number, body: ProposalDecisionIn) =>
  contractFetch<unknown>(`/api/catalogue/proposals/${id}/decision`, { method: 'POST', json: body })
