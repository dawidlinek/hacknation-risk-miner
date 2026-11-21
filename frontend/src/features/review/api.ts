import { queryOptions } from '@tanstack/react-query'
import {
  adaptCounts,
  adaptDecision,
  adaptReviewCard,
  REAL_KIND,
  type RealCounts,
  type RealDecisionResult,
  type RealReviewCard,
  type RealReviewList,
} from '@/api/adapters/review'
import { contractFetch } from '@/api/client'
import type { DecisionResult, ReviewKind, ReviewOption } from '@/api/contracts/review'

export const reviewCountsQuery = queryOptions({
  queryKey: ['review', 'counts'],
  queryFn: async () => adaptCounts(await contractFetch<RealCounts>('/api/review-items/counts')),
  staleTime: 15_000,
})

/** Open items of a kind, oldest first; `first` (?sprawa=) is delivered first by the backend. */
export const reviewListQuery = (
  kind: ReviewKind | undefined,
  first: number | undefined,
  code: string | undefined,
) =>
  queryOptions({
    queryKey: ['review', 'list', kind ?? 'all', first ?? 0, code ?? ''],
    queryFn: () =>
      contractFetch<RealReviewList>('/api/review-items', {
        query: { status: 'open', kind: kind ? REAL_KIND[kind] : undefined, code, id: first, limit: 100 },
      }),
    staleTime: 0,
  })

export const reviewCardQuery = (id: number) =>
  queryOptions({
    queryKey: ['review', 'card', id],
    queryFn: async () => adaptReviewCard(await contractFetch<RealReviewCard>(`/api/review-items/${id}`)),
    staleTime: 30_000,
  })

export async function decide(
  id: number,
  option: ReviewOption,
  state: { text: string; gold: boolean },
): Promise<DecisionResult> {
  const text = state.text.trim()
  const body: Record<string, unknown> = { option: option.key, action: option.decision, gold: state.gold }
  if (option.input?.field === 'value') body.value = text
  if (option.input?.field === 'reason') body.reason = text
  const raw = await contractFetch<RealDecisionResult>(`/api/review-items/${id}/decision`, {
    method: 'POST',
    json: body,
  })
  return adaptDecision(raw, option, state.gold)
}

export const undoDecision = (reviewId: string) =>
  contractFetch<unknown>(`/api/reviews/${reviewId}/undo`, { method: 'POST' })
export const skipItem = (id: number) =>
  contractFetch<unknown>(`/api/review-items/${id}/skip`, { method: 'POST' })
