import type { Money, ProvLine, ReviewStatus, Sentence, SimilarCase } from './common'

// 1.1 Nowa analiza
export type DocType = 'PFU' | 'PPU' | 'SWZ' | 'umowa' | 'inne'
export interface UploadedDocument {
  document_id: number
  filename: string
  doc_type: DocType
  pages: number
  label: string
  sensitivity: 'confidential' | 'public'
}
export type FeatureKey =
  | 'podsektor'
  | 'formula'
  | 'dlugosc_km'
  | 'przepompownie'
  | 'budzet'
  | 'termin_mies'
  | 'finansowanie'
  | 'przylacza'
  | (string & {})
export interface FeatureChip {
  key: FeatureKey
  label: string
  value: string | number | boolean | Money | null
  display: string
  source_label: string
  source?: { document_id: number; page: number } | null
  unsure: boolean
  editor: 'text' | 'number' | 'money' | 'months' | 'select'
  options?: { value: string; label: string }[]
  unit?: string | null
}
export interface FollowUp {
  key: FeatureKey
  title: string
  why: string
  input: 'number' | 'text'
  placeholder: string
  skippable: boolean
}
export type AnalysisStatus = 'draft' | 'running' | 'ready' | 'error'
export interface AnalysisDraft {
  id: string
  version: number
  status: AnalysisStatus
  text: string
  documents: UploadedDocument[]
  features: FeatureChip[]
  follow_ups: FollowUp[]
}
export interface AnalysisCreateIn {
  text: string
  document_ids: number[]
}
export interface FeaturesPatchIn {
  values: Record<string, unknown>
  skipped?: string[]
}

// 1.2 Raport
export type Answer = 'Nie' | 'Raczej nie' | 'Raczej tak' | 'Tak' | 'Nie wiemy'
export interface QuestionCard {
  key: 'time' | 'budget' | 'programme'
  question: string
  answer: Answer
  tone: 'bad' | 'good' | 'neutral'
  key_value: number | null
  key_kind: 'chance' | 'mln_per_km'
  key_display?: string | null
  scale: { min: number; max: number; lo_label: string; hi_label: string }
  band: { from: number; to: number; kind: 'p10_p90' | 'p25_p75' | 'p10_p80'; caption: string } | null
  median: number | null
  you: number | null
  programme_end: number | null
  n: number
  insufficient: boolean
  aria: string
  provenance: ProvLine
  metric: 'time' | 'cost' | 'comp'
}
export interface ReportFlag {
  id: string
  origin: 'CALC' | 'AI'
  review_status: ReviewStatus
  title: string
  text: string
  meta: string
  risk_codes: string[]
  doc?: { document_id: number; page: number; note_no?: string } | null
  review_item_id?: number | null
}
export interface ClauseHint {
  code: string
  title: string
  why: string
  in_pack: boolean
}
export interface AnalysisReport {
  id: string
  version: number
  status: 'running' | 'ready' | 'error' | 'draft'
  error?: string | null
  title: string
  subtitle: string
  summary: Sentence
  questions: QuestionCard[]
  flags: ReportFlag[]
  similar_cases: SimilarCase[]
  clauses: ClauseHint[]
  reference_class: { label: string; n: number; funnel: { label: string; n: number }[] }
  limitations: string[]
  backtest_note?: string | null
  pending_review: number
  unverified_hidden?: number
  documents: UploadedDocument[]
  chat: { suggestions: string[] }
}
