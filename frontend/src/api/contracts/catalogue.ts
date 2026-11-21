// Contract for 3.2 Katalog wiedzy as the UI consumes it (adapter: api/adapters/catalogue.ts, real GET /api/catalogue/view).

export interface RiskPart {
  k: string
  v: string
}

export interface CatalogueRisk {
  code: string
  title: string
  effect: string
  counts_label: string // '1 zatw., 3 do przeglądu' | 'brak zdarzeń'
  parts: RiskPart[]
  quality: {
    badge: string
    detail: string
    attention?: boolean
    review: { rodzaj: string; ryzyko: string } | null
  } | null
}

export interface CatalogueProposal {
  id: number
  review_item_id: number | null
  title: string
  detail: string | null
  source_label: string | null
  merge_target: string | null
}

export interface SimilarityWeight {
  key: string
  label: string
  /** share in percent, 0..40 */
  value: number
  /** the five weights experts tune (the rest stay as shipped) */
  main: boolean
}

export interface CatalogueVersion {
  label: string // 'v1.1'
  summary: string
  who: string // 'system, 21.11 18:32'
}

export interface CatalogueItem {
  code: string
  name: string
  detail?: string
}

export interface CatalogueOut {
  version: string // 'v1.1'
  updated_at: string | null
  risks: CatalogueRisk[]
  proposals: CatalogueProposal[]
  weights: SimilarityWeight[]
  versions: CatalogueVersion[]
  subsectors: CatalogueItem[]
  doc_types: CatalogueItem[]
  checklists: CatalogueItem[]
  clauses: CatalogueItem[]
}

export interface ProposalDecisionIn {
  action: 'approve' | 'merge' | 'reject'
  merge_into?: string
  reason?: string
}
