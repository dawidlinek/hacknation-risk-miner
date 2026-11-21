// Contract for 3.1 Przeglad (docs/impl/frontend.md section 3.1).
import type { LinkRef } from './common'

export type ReviewKind = 'events' | 'links' | 'discrepancies' | 'facts' | 'catalogue'

export type ChipTone = 'ok' | 'warn' | 'neutral'

export interface ReviewOptionInput {
  /** which body field carries the text: `value` (edit) or `reason` (reject) */
  field: 'value' | 'reason'
  label: string
  kind: 'text' | 'risk_code' | 'bzp_number' | 'date'
  required: boolean
}

export interface ReviewEffect {
  where: string
  before: string
  after: string
}

export interface ReviewOption {
  key: string
  title: string
  sub: string
  badge?: string | null // 'propozycja modelu, 0,80' | 'model rozważał, 0,31' | 'odczyt modelu'
  decision: 'approve' | 'edit' | 'reject'
  input?: ReviewOptionInput | null
  short: string // used in the toast 'Zapisano: R02. ...'
  effects: ReviewEffect[]
}

export interface ReviewEvidence {
  title: string
  ref: string
  ref_url?: string | null
  pre: string
  hit: string
  post: string
  verified: boolean
}

export interface ReviewCard {
  id: number
  kind: ReviewKind
  kind_label: string // 'Zdarzenie ryzyka'
  context: LinkRef
  question: string
  sub: string
  evidence: ReviewEvidence
  chips: { text: string; tone: ChipTone }[]
  options: ReviewOption[]
  default_option: number // the model's pick
  gold: ReviewEffect | null // null => no "Wzorcowy przykład"
}

export interface ReviewQueue {
  total: number
  counts: Record<ReviewKind, number>
  items: ReviewCard[]
  next_cursor?: string | null
}

export interface DecisionIn {
  option_key: string
  value?: string
  reason?: string
  gold: boolean
}

export interface DecisionResult {
  toast: string
  undo_token: string
  learning?: { text: string; link?: LinkRef | null } | null
}

export interface QueueQuery {
  kind?: ReviewKind
  cursor?: string
  item?: number // ?sprawa=<id>: this item is delivered first
}
