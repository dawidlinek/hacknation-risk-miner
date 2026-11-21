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
import type { DecisionResult, ReviewCard, ReviewKind, ReviewOption } from '@/api/contracts/review'
import { type CardContext, contextOf, type QueueFilter, type RawContext, type ReviewFacets } from './context'

export type ReviewCardView = ReviewCard & CardContext

export const reviewCountsQuery = queryOptions({
  queryKey: ['review', 'counts'],
  queryFn: async () => adaptCounts(await contractFetch<RealCounts>('/api/review-items/counts')),
  staleTime: 15_000,
})

const filterQuery = (f: QueueFilter) => ({
  type: f.type || undefined,
  rm_id: f.project || undefined,
  sort: f.sort ?? 'strength',
})

/** Open items of a kind, strongest evidence first by default; `first` (?sprawa=) is delivered first by the backend. */
export const reviewListQuery = (
  kind: ReviewKind | undefined,
  first: number | undefined,
  code: string | undefined,
  filter: QueueFilter = {},
) =>
  queryOptions({
    queryKey: [
      'review',
      'list',
      kind ?? 'all',
      first ?? 0,
      code ?? '',
      filter.type ?? '',
      filter.project ?? '',
      filter.sort ?? '',
    ],
    queryFn: () =>
      contractFetch<RealReviewList>('/api/review-items', {
        query: {
          status: 'open',
          kind: kind ? REAL_KIND[kind] : undefined,
          code,
          id: first,
          limit: 200,
          ...filterQuery(filter),
        },
      }),
    staleTime: 0,
  })

/** Type, project and strength facets of the current list; each facet's numbers add up to the list total. */
export const reviewFacetsQuery = (
  kind: ReviewKind | undefined,
  code: string | undefined,
  filter: QueueFilter = {},
) =>
  queryOptions({
    queryKey: ['review', 'facets', kind ?? 'all', code ?? '', filter.type ?? '', filter.project ?? ''],
    queryFn: () =>
      contractFetch<ReviewFacets>('/api/review-items/facets', {
        query: {
          status: 'open',
          kind: kind ? REAL_KIND[kind] : undefined,
          code,
          ...filterQuery(filter),
          sort: undefined,
        },
      }),
    staleTime: 15_000,
  })

export const reviewCardQuery = (id: number) =>
  queryOptions({
    queryKey: ['review', 'card', id],
    queryFn: async (): Promise<ReviewCardView> => {
      const raw = await contractFetch<RealReviewCard & RawContext>(`/api/review-items/${id}`)
      return { ...adaptReviewCard(raw), ...contextOf(raw) }
    },
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
