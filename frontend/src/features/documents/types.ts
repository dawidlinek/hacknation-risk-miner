// View models for 2.5 Dokumenty projektu. The real API shape (api_contract §2.4) is adapted in adapt.ts.
import type { Origin, ReviewStatus } from '@/api/contracts/common'

export interface ExpectedItem {
  key: string
  title: string
  ext: string
  have: boolean
  /** 'nie ma w paczce' | 'mamy dokument' ... */
  stateLabel: string
  unlocks: string
  where: string
  checklist: string
}

export interface PublicItem {
  key: string
  kind: 'notice' | 'document'
  /** notice object_id (for /api/notices/{id}/facts) or document id */
  objectId: string
  title: string
  ext: 'XLSX' | 'BZP' | 'PDF' | 'DOCX'
  ref: string
  dateLabel: string
  factsLabel: string
  riskCodes: string[]
  reviewStatus: ReviewStatus
  statusLabel: string
  url: string | null
}

export interface DocsView {
  summary: string
  expected: ExpectedItem[]
  publicDocs: PublicItem[]
  have: number
  expectedTotal: number
}

export interface DetailField {
  label: string
  value: string
  tag: string
  tagRole: Origin | ReviewStatus
}

export interface DetailView {
  kind: string
  title: string
  fields: DetailField[]
  meta: { k: string; v: string }[]
  cta: { label: string; href: string; external?: boolean } | null
}

// ---- real API shapes -------------------------------------------------------------------------------------------------
export interface RealExpected {
  key: string
  title?: string
  label?: string
  ext?: string
  have: boolean
  state_label?: string
  unlocks?: string
  where?: string
  where_to_find?: string
  checklist?: string
}

export interface RealPublic {
  kind: 'notice' | 'document'
  key: string
  object_id: string
  ref: string
  title: string
  ext: string
  date: string | null
  facts: number
  risk_codes?: string[]
  review_status: ReviewStatus
  status_label?: string
  url?: string | null
}

export interface RealDocuments {
  expected: RealExpected[]
  public?: RealPublic[]
  public_docs?: RealPublic[]
  have: number
  expected_total: number
  summary: string
}

export interface RealFactRow {
  field_code: string | null
  label: string
  value: string
  tag?: string
  tag_role?: string
  review_status?: ReviewStatus
}

export interface RealFacts {
  rows: RealFactRow[]
  meta: {
    url: string | null
    retrieved_at: string | null
    sha256: string | null
    licence: string | null
    licence_label?: string
    notice_number?: string
  }
}

// ---- new documents: analysis (G5) --------------------------------------------------------------------------------------
export type StepState = 'done' | 'running' | 'queued' | 'pending' | 'failed'

export interface RealStep {
  key: 'upload' | 'ocr' | 'extraction' | 'linking'
  label: string
  state: StepState
  detail?: string | null
  error?: string | null
}

export interface RealFact {
  field: string
  value: unknown
  display?: string | null
  origin?: 'CALC' | 'AI' | 'SOURCE' | null
  method?: string | null
  quote?: string | null
  page?: number | null
  verification?: 'exact' | 'fuzzy' | 'unverified' | 'structured_field' | null
}

export interface RealCause {
  code: string
  origin?: 'CALC' | 'AI' | null
  why?: string | null
  quote?: string | null
  page?: number | null
  verification?: string | null
}

export interface RealAnalysis {
  document: {
    id: number
    filename: string | null
    title: string | null
    sensitivity: string | null
    pages: number | null
    doc_kind_label: string | null
    doc_date: string | null
    level: 'contract' | 'grant' | null
  }
  steps: RealStep[]
  facts: RealFact[]
  causes: RealCause[]
  effects: RealCause[]
  flags: { code: string; text: string }[]
  link: {
    project?: { rm_id: string; method: string; score: number } | null
    contract?: { contract_id: number; score: number; contractor: string } | null
    checks?: { kind: string; ok: boolean; value: string; detail: string; expected?: string | null }[]
    warnings?: string[]
  } | null
  review_items: { id: number; kind: string; title: string; status: string; href: string }[]
  project_rm_id: string | null
  growth?: Growth | null
}

export interface LineDecision {
  action: 'approve' | 'edit' | 'reject'
  action_label: string
  by: string
  by_label: string
  at: string
}

export interface Growth {
  contract_changes: number
  risk_events: number
  catalogue_proposals: string[]
  sentence: string | null
  short: string | null
}

export interface ChangeLine {
  key: string
  from_document?: boolean
  decision?: LineDecision | null
  label: string
  value?: string
  where?: string
  before?: string
  after?: string
  why?: string
}

export interface RealChangesSince {
  document: { id: number; kind_label: string; date: string | null }
  groups: Record<'potwierdzone' | 'zmienione' | 'nowe' | 'zamkniete', ChangeLine[]>
  counts: Record<'potwierdzone' | 'zmienione' | 'nowe' | 'zamkniete', number>
  aggregates: Record<string, unknown>
  review_items: { id: number; title: string; status: string; kind: string; href: string }[]
  growth?: Growth | null
  analyses_to_rerun?: string[]
}
