// Contract for 2.2 Projekty and 2.3 Karta projektu (docs/impl/frontend.md sections 2.2, 2.3).
import type { EvidenceState, Money, Origin, Page, ReviewStatus, Sentence, SimilarCase } from './common'
import type { JobOut } from './import'

export type ProjectFilter = 'all' | 'late' | 'discrepancy' | 'review'
export type ProjectSortKey =
  | 'title'
  | 'subsector'
  | 'value'
  | 'delay'
  | 'cost'
  | 'changes'
  | 'performed'
  | 'state'

export interface ProjectState {
  tone: 'review' | 'ok' | 'discrepancy'
  label: string // '2 do przeglądu' | 'zatwierdzone' | 'rozbieżność wartości'
}

export interface ProjectRow {
  rm_id: string
  title: string
  buyer_name: string
  subsector_label: string
  contract_value: Money // gross
  delay_days: number | null
  cost_dev_pct: number | null
  changes: number | null
  properly_performed: boolean | null
  state: ProjectState
}

export interface ProjectsStat {
  label: string
  value: string
  note?: string | null
}

export interface ProjectsFacets {
  all: number
  late: number
  discrepancy: number
  review: number
  subsectors: { key: string; label: string; n: number }[]
}

export interface ProjectsTableOut extends Page<ProjectRow> {
  stats: ProjectsStat[]
  facets: ProjectsFacets
}

export interface ProjectsTableQuery {
  q?: string
  filter?: ProjectFilter
  subsector?: string
  province?: string
  sort?: ProjectSortKey
  dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

// ---- 2.3 Karta ----

export interface PlanVsActual {
  key: 'time' | 'cost'
  label: string // 'Termin' | 'Koszt'
  delta_label: string // '+277 dni'
  plan: number // bar basis (days or amount)
  actual: number
  note: string
}

export interface TimelineStep {
  state: 'done' | 'now' | 'missing'
  title: string
  text: string
  date_label: string // '04.06.2024' | 'po 08.2025'
  ref: string // '2024/BZP 00349631/01' | 'obliczenie'
  href: string // graph node, BZP notice or review item; '' when none
  origin: Origin
  review_status: ReviewStatus
}

export interface ProjectLesson {
  id: number
  title: string
  text: string
  code_label: string // 'R01, źródło: BZP'
  risk_code: string | null
  origin: Origin
  review_status: ReviewStatus
  review_item_id?: number | null
}

export interface ProjectGap {
  doc: string
  state: EvidenceState
  limits: string
}

export interface ProjectIdentifier {
  key: string // 'rekord' | 'BZP' | 'OCID' | 'NIP'
  value: string
  check?: 'ok' | 'bad' | null
}

export interface ProjectCard {
  id: string
  auto_card: boolean
  title: string
  buyer: { name: string; nip: string | null; nip_valid: boolean | null }
  summary: Sentence
  doc_counts: { have: number; expected: number }
  plan_vs_actual: PlanVsActual[]
  timeline: TimelineStep[]
  similar_cases: SimilarCase[]
  lessons: ProjectLesson[]
  gaps: ProjectGap[]
  identifiers: ProjectIdentifier[]
  chat: { suggestions: string[] }
}

export type EnrichResult = JobOut
