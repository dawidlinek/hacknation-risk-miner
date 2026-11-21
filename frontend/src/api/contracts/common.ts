// Shared contract types (frontend.md §1.10). The frontend's side of the API contract.
export type VatBasis = 'net' | 'gross' | 'unknown'
export interface Money {
  amount: string | number | null
  currency: string | null
  vat_basis: VatBasis | null
}
export type Origin = 'SOURCE' | 'CALC' | 'AI' | 'CASE'
export type ReviewStatus = 'auto' | 'proposed' | 'approved' | 'edited' | 'rejected'
export type EvidenceState =
  | 'nie_ma_w_paczce'
  | 'dokument_nie_wspomina'
  | 'brak_potwierdzenia'
  | 'potwierdzono_brak'
export const EVIDENCE_STATE_LABEL: Record<EvidenceState, string> = {
  nie_ma_w_paczce: 'nie ma w paczce',
  dokument_nie_wspomina: 'dokument nie wspomina',
  brak_potwierdzenia: 'brak potwierdzenia',
  potwierdzono_brak: 'potwierdzono brak',
}
export interface EvidenceKey {
  claim_table: string
  claim_id: number
  claim_field?: string
}
export interface ProvLine {
  origin: Origin
  text: string
  n?: number | null
  review_status?: ReviewStatus
  evidence?: EvidenceKey | null
}
export interface Sentence {
  text: string
  provenance: string
}
export interface LinkRef {
  label: string
  href: string
}
export interface Page<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}
export type SimFeature = 'podsektor' | 'formula' | 'zakres' | 'wartosc' | 'tekst'
export interface SimilarCase {
  project_id: string
  title: string
  why: string
  score: number
  contributions: { feature: SimFeature; value: number }[]
  delay_days: number | null
  cost_dev_pct: number | null
  href?: string | null
}
export interface AskAnswer {
  id: string
  question: string
  role: 'obliczenie' | 'wniosek_ai' | 'brak_danych'
  role_label: string
  text: string
  bars?: { label: string; value: number; display: string; attention: boolean }[]
  scale_max?: number
  sql?: string | null
  method?: string | null
  sources: string[]
  actions: {
    kind: 'save' | 'open_list' | 'export_csv' | 'open_map' | 'open_project' | 'open_review' | 'compare'
    label: string
    href?: string
  }[]
  saved_id?: string | null
}
