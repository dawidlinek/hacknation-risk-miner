// Real /api/review-items* (api_contract 2.5, review/cards.py) -> the UI contract in api/contracts/review.ts.
import type { LinkRef } from '@/api/contracts/common'
import type {
  ChipTone,
  DecisionResult,
  ReviewCard,
  ReviewEffect,
  ReviewKind,
  ReviewOption,
} from '@/api/contracts/review'
import type { RealRef } from './real'

export type RealKind = 'event' | 'link' | 'discrepancy' | 'fact' | 'catalogue'

const KIND: Record<RealKind, ReviewKind> = {
  event: 'events',
  link: 'links',
  discrepancy: 'discrepancies',
  fact: 'facts',
  catalogue: 'catalogue',
}
export const REAL_KIND: Record<ReviewKind, RealKind> = {
  events: 'event',
  links: 'link',
  discrepancies: 'discrepancy',
  facts: 'fact',
  catalogue: 'catalogue',
}

/** URL slugs of `?rodzaj=`; English plural names and singular backend names are accepted as aliases. */
export const KIND_SLUG: Record<ReviewKind, string> = {
  events: 'zdarzenia',
  links: 'powiazania',
  discrepancies: 'rozbieznosci',
  facts: 'fakty',
  catalogue: 'katalog',
}
export function parseKindParam(s: string | undefined | null): ReviewKind | undefined {
  if (!s) return undefined
  for (const [k, slug] of Object.entries(KIND_SLUG))
    if (s === slug || s === k || s === REAL_KIND[k as ReviewKind]) return k as ReviewKind
  return undefined
}

export const KIND_TAB_LABEL: Record<ReviewKind, string> = {
  events: 'Zdarzenia ryzyka',
  links: 'Powiązania',
  discrepancies: 'Rozbieżności w danych',
  facts: 'Fakty z dokumentów',
  catalogue: 'Propozycje do katalogu',
}

export interface RealOption {
  key: string
  action: 'approve' | 'edit' | 'reject'
  label: string
  sub: string | null
  model_pick: boolean
  confidence: number | null
  badge: string | null
  needs_input: 'value' | 'reason' | null
  input_placeholder: string | null
  effects: ReviewEffect[]
}

export interface RealReviewCard {
  id: number
  kind: RealKind
  kind_label: string
  code: string | null
  context: { label: string | null; href: string | null }
  question: string
  sub: string
  evidence: {
    title: string
    ref: RealRef | string | null
    pre: string
    hit: string
    post: string
    verification: string | null
  } | null
  chips: { text: string; tone: ChipTone }[]
  options: RealOption[]
  gold: ReviewEffect | null
}

export interface RealReviewListItem {
  id: number
  kind: RealKind
  question: string | null
  title: string
}

export interface RealReviewList {
  total: number
  items: RealReviewListItem[]
}

export type RealCounts = Record<RealKind | 'total', number>

export interface RealDecisionResult {
  item_id: number
  review_id: number
  undo_until: string | null
  next_item_id: number | null
  gold: { gold_example_id: number | null; job_id: number | null; similar_pending: number } | null
}

export const adaptCounts = (c: RealCounts): Record<ReviewKind, number> => ({
  events: c.event,
  links: c.link,
  discrepancies: c.discrepancy,
  facts: c.fact,
  catalogue: c.catalogue,
})

const shortOf = (o: RealOption) => (/^R\d{2}$/.test(o.key) ? o.key : o.label)

function adaptOption(o: RealOption): ReviewOption {
  return {
    key: o.key,
    title: o.label,
    sub: o.sub ?? '',
    badge: o.badge,
    decision: o.action,
    input: o.needs_input
      ? {
          field: o.needs_input,
          label:
            o.input_placeholder ?? (o.needs_input === 'reason' ? 'Powód (wymagany)' : 'Wartość (wymagana)'),
          kind: 'text',
          required: true,
        }
      : null,
    short: shortOf(o),
    effects: o.effects,
  }
}

const verified = (v: string | null) => v === 'exact' || v === 'structured_field'

export function adaptReviewCard(raw: RealReviewCard): ReviewCard {
  const ev = raw.evidence
  const ref = ev?.ref
  const refLabel = !ref ? '' : typeof ref === 'string' ? ref : `${ref.id}${ref.label ? `, ${ref.label}` : ''}`
  const context: LinkRef = { label: raw.context.label ?? raw.kind_label, href: raw.context.href ?? '' }
  const options = raw.options.map(adaptOption)
  const pick = raw.options.findIndex((o) => o.model_pick)
  return {
    id: raw.id,
    kind: KIND[raw.kind],
    kind_label: raw.kind_label,
    context,
    question: raw.question,
    sub: raw.sub,
    evidence: ev
      ? {
          title: ev.title,
          ref: refLabel,
          ref_url: ref && typeof ref !== 'string' ? (ref.url ?? null) : null,
          pre: ev.pre,
          hit: ev.hit,
          post: ev.post,
          verified: verified(ev.verification),
        }
      : { title: '', ref: '', ref_url: null, pre: '', hit: '', post: '', verified: true },
    chips: raw.chips,
    options,
    default_option: Math.max(pick, 0),
    gold: raw.gold,
  }
}

export function adaptDecision(raw: RealDecisionResult, option: ReviewOption, gold: boolean): DecisionResult {
  const pending = raw.gold?.similar_pending ?? 0
  return {
    toast: `Zapisano: ${option.short}. Zmiany są już na miejscu.`,
    undo_token: String(raw.review_id),
    learning:
      gold && raw.gold
        ? {
            text:
              pending > 0
                ? `Model przeliczy ${pending} podobnych spraw według Twojej decyzji. Te, które zmienią wynik, wrócą do kolejki.`
                : 'Zapisano jako wzorcowy przykład. Model uwzględni go przy kolejnych propozycjach.',
            link: null,
          }
        : null,
  }
}
