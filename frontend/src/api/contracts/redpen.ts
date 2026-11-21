import type { EvidenceState, LinkRef, ReviewStatus } from './common'

export interface RedPenMark {
  note_no: string
  start: number
  end: number
}
export interface RedPenParagraph {
  text: string
  heading?: boolean
  marks: RedPenMark[]
}
export interface RedPenPage {
  page_no: number
  title?: string | null
  paragraphs: RedPenParagraph[]
}
export interface RedPenNote {
  no: string
  kind: 'found' | 'missing'
  risk_codes: string[]
  page?: number | null
  locator?: string | null
  title: string
  why: string
  review_status: ReviewStatus
  evidence_state?: EvidenceState | null
  quote?: { text: string; verified: boolean } | null
  cases: LinkRef[]
  clause?: { code: string; text: string; in_pack: boolean } | null
  limits?: string | null
}
export interface RedPenOut {
  status?: 'queued' | 'running' | 'done'
  document: { id: number; filename: string; pages: number; doc_type: string; demo: boolean; file_url?: string | null }
  pages: RedPenPage[]
  notes: RedPenNote[]
  counts: { found: number; missing: number }
}
