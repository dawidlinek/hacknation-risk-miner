// Contract for 2.4 Graf powiazan, "skad wiemy" (docs/impl/frontend.md section 2.4).
import type { Origin, ReviewStatus } from './common'

export type FlowColumn = 0 | 1 | 2
export type FlowRole = 'organiser' | 'source' | 'ai' | 'calc' | 'group' | 'conclusion'

export interface FlowNode {
  id: string
  column: FlowColumn
  label: string
  sub: string
  role: FlowRole
  status_label?: string // conclusions: 'pewne' | 'obliczenie' | 'zatwierdzone' | 'do przeglądu' | 'wniosek AI'
  review_status?: ReviewStatus
  origin?: Origin
  selectable: boolean
}

export interface FlowLink {
  source: string
  target: string
  value: number // number of facts (band width)
}

export interface FlowDetail {
  kind: string
  title: string
  rows: { k: string; v: string }[]
  review_item_id?: number | null
  /** where the facts behind this node come from (notice, field code, link) */
  evidence?: { label: string; url?: string | null; field?: string | null }[]
}

export interface EvidenceFlow {
  nodes: FlowNode[]
  links: FlowLink[]
  details: Record<string, FlowDetail>
  overview: { kind: string; title: string; rows: { k: string; v: string }[] } // '16 faktów, 6 wniosków'
  default_selected?: string | null
}
