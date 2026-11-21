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

/** Raw catalogue rows (any status, login only): `GET /api/catalogue/{table}` in routers/data.py. */
export interface RawClause {
  id: number
  code: string
  risk_code: string | null
  title: string | null
  text: string
  status: 'approved' | 'proposed' | 'rejected' | 'retired'
  version: number
  origin: 'SOURCE' | 'CALC' | 'AI'
  proposed_by: string | null
  approved_by: string | null
  created_at: string
  updated_at: string
}

export interface RawRisk {
  code: string
  name: string
  status: string
  version: number
  parent_code: string | null
}

export const clausesQuery = queryOptions({
  queryKey: ['catalogue', 'clauses', 'wod-kan'],
  queryFn: () => contractFetch<RawClause[]>('/api/catalogue/clause', { query: { sector: 'wod-kan' } }),
  staleTime: 60_000,
})

export const riskNamesQuery = queryOptions({
  queryKey: ['catalogue', 'risk-names', 'wod-kan'],
  queryFn: async () => {
    const rows = await contractFetch<RawRisk[]>('/api/catalogue/risk', { query: { sector: 'wod-kan' } })
    const names: Record<string, string> = {}
    for (const r of [...rows].sort((a, b) => a.version - b.version))
      if (r.status !== 'rejected') names[r.code] = r.name
    return names
  },
  staleTime: 60_000,
})
