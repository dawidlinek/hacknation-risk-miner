import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { SimulationResponse } from './scenario'

/** GET /api/analyses/{id}/simulation: every subset precomputed server-side, deterministic per analysis version. */
export const simulationQuery = (id: string) =>
  queryOptions({
    queryKey: ['analysis', id, 'simulation'],
    queryFn: () => contractFetch<SimulationResponse>(`/api/analyses/${encodeURIComponent(id)}/simulation`),
    staleTime: 5 * 60_000,
  })

export interface ChatAnswerLite {
  text: string
  role_label?: string
  role?: string
}

/** Free-text what-if goes to the analysis chat (session L). */
export function askAnalysis(id: string, message: string, metric: string, options: string[]) {
  return contractFetch<ChatAnswerLite>(`/api/analyses/${encodeURIComponent(id)}/chat`, {
    method: 'POST',
    json: { message, question: message, context: 'simulation', metric, options },
  })
}
