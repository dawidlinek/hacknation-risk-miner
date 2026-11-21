// Real /api/projects* shapes -> the UI contract in api/contracts/projects.ts.
import type {
  EvidenceState,
  Money,
  Origin,
  ReviewStatus,
  SimFeature,
  SimilarCase,
} from '@/api/contracts/common'
import type {
  PlanVsActual,
  ProjectCard,
  ProjectGap,
  ProjectLesson,
  ProjectRow,
  ProjectsStat,
  ProjectsTableOut,
  TimelineStep,
} from '@/api/contracts/projects'
import { numValue, provText, type RealMoney, type RealNum, type RealProv, type RealRef } from './real'

// ---- list (GET /api/projects) ----
export interface RealProjectItem {
  rm_id: string
  title: string
  beneficiary_name: string | null
  subsector_main: string | null
  metrics: {
    contract_value: RealMoney
    delay_days: RealNum | null
    cost_dev_pct: RealNum | null
    changes: RealNum | null
    properly_performed: boolean | null
    state: { code: 'discrepancy' | 'to_review' | 'partial_payment' | 'auto'; label: string }
  }
}

export interface RealProjectsPage {
  total: number
  limit: number
  offset: number
  items: RealProjectItem[]
  facets: {
    all: number
    late: number
    discrepancy: number
    review: number | null
    subsectors: { key: string; label: string; n: number }[]
  }
}

export interface RealProjectsStats {
  late: { label: string; value: RealNum; note: string | null }
  overpaid: { label: string; value: RealNum; note: string | null }
  improper: { label: string; value: RealNum; note: string | null }
  changes: { label: string; value: RealNum; note: string | null }
}

const TONE = {
  discrepancy: 'discrepancy',
  partial_payment: 'discrepancy',
  to_review: 'review',
  auto: 'ok',
} as const

export function adaptProjectsPage(raw: RealProjectsPage, stats: RealProjectsStats | null): ProjectsTableOut {
  const sub = new Map(raw.facets.subsectors.map((s) => [s.key, s.label]))
  const items: ProjectRow[] = raw.items.map((r) => ({
    rm_id: r.rm_id,
    title: r.title,
    buyer_name: r.beneficiary_name ?? '',
    subsector_label: sub.get(r.subsector_main ?? '') ?? r.subsector_main ?? 'brak',
    contract_value: r.metrics.contract_value,
    delay_days: numValue(r.metrics.delay_days),
    cost_dev_pct: numValue(r.metrics.cost_dev_pct),
    changes: numValue(r.metrics.changes),
    properly_performed: r.metrics.properly_performed,
    state: { tone: TONE[r.metrics.state.code] ?? 'ok', label: r.metrics.state.label },
  }))
  return {
    total: raw.total,
    limit: raw.limit,
    offset: raw.offset,
    items,
    stats: stats ? adaptStats(stats) : [],
    facets: {
      all: raw.facets.all,
      late: raw.facets.late,
      discrepancy: raw.facets.discrepancy,
      review: raw.facets.review ?? 0,
      subsectors: raw.facets.subsectors,
    },
  }
}

function adaptStats(s: RealProjectsStats): ProjectsStat[] {
  return [s.late, s.overpaid, s.improper, s.changes].map((x) => ({
    label: x.label,
    value: x.value.display,
    note: x.note,
  }))
}

// ---- card (GET /api/projects/{rm_id}/card) ----
interface RealStep {
  date: string | null
  state: 'done' | 'now' | 'missing'
  title: string
  text: string
  ref: RealRef | string | null
  review_status: ReviewStatus
  date_label: string
  href: string | null
}

interface RealEvent {
  id: number
  title: string
  text: string
  risk_code: string | null
  review_status: ReviewStatus
  origin: Origin
  review_item_id?: number | null
}

interface RealSimilar {
  rank: number
  rm_id: string | null
  ocid: string | null
  title: string
  score: RealNum
  why: string
  contributions: { feature: string; label?: string; value: number }[]
  outcome?: { delay_days?: RealNum | null; cost_dev_pct?: RealNum | null } | null
}

export interface RealCard {
  rm_id: string
  id: string
  title: string
  auto_card?: boolean
  buyer: { name: string | null; nip: string | null; nip_valid: boolean | null }
  summary: { sentence: string; prov?: RealProv }
  plan_vs_actual: {
    key: 'time' | 'cost'
    label: string
    planned?: RealNum | null
    actual?: RealNum | null
    planned_money?: Money | null
    actual_money?: Money | null
    delta: RealNum | null
    note?: string | null
  }[]
  steps?: RealStep[]
  timeline?: RealStep[]
  lessons?: RealEvent[]
  events?: RealEvent[]
  gaps: { doc_type: string; evidence_state: string; state_label: string; limits: string }[]
  doc_counts: { have: number; expected: number }
  identifiers: { k: string; v: string; verified?: boolean | null }[]
  similar: RealSimilar[]
  chat?: { suggestions: string[] }
}

const FEATURE: Record<string, SimFeature> = {
  subsector_main: 'podsektor',
  formula: 'formula',
  design_build: 'formula',
  physical_size: 'zakres',
  scope: 'zakres',
  value: 'wartosc',
  budget: 'wartosc',
  text: 'tekst',
}

const EVIDENCE: Record<string, EvidenceState> = {
  BRAK_W_PACZCE: 'nie_ma_w_paczce',
  DOKUMENT_NIE_WSPOMINA: 'dokument_nie_wspomina',
  BRAK_POTWIERDZENIA: 'brak_potwierdzenia',
  POTWIERDZONO_BRAK: 'potwierdzono_brak',
}

/** Human names for the expected-document codes the catalogue uses. Unknown codes are shown as they are. */
export const DOC_TYPE_LABEL: Record<string, string> = {
  PFU: 'PFU',
  PPU: 'Projektowane postanowienia umowy',
  SWZ: 'SWZ',
  UMOWA: 'Podpisana umowa i aneksy',
  GEOTECH: 'Dokumentacja geotechniczna',
  DECYZJA_WODNOPRAWNA: 'Decyzja wodnoprawna',
  PROTOKOL_ODBIORU: 'Protokół odbioru',
}

export const docLabel = (code: string) => DOC_TYPE_LABEL[code] ?? code

function stepRef(step: RealStep, projectId: string): { ref: string; href: string; origin: Origin } {
  const r = step.ref
  if (!r) return { ref: '', href: step.href ?? '', origin: 'CALC' }
  if (typeof r === 'string')
    return { ref: r, href: step.href ?? '', origin: r === 'obliczenie' ? 'CALC' : 'SOURCE' }
  const internal = step.href?.startsWith('/') ? step.href : ''
  // steps read from an uploaded document open that document on the Dokumenty tab
  const doc = r.kind === 'document' ? `/projekty/${projectId}/dokumenty?dok=doc:${r.id}` : ''
  return {
    ref: r.id || r.label,
    href: internal || doc || r.url || '',
    origin: r.kind === 'notice' ? 'SOURCE' : r.kind === 'document' ? 'AI' : 'CALC',
  }
}

const adaptStep = (s: RealStep, projectId: string): TimelineStep => {
  const { ref, href, origin } = stepRef(s, projectId)
  return {
    state: s.state,
    title: s.title,
    text: s.text,
    date_label: s.date_label,
    ref,
    href,
    origin,
    review_status: s.review_status,
  }
}

const adaptEvent = (e: RealEvent): ProjectLesson => ({
  id: e.id,
  title: e.title,
  text: e.text,
  code_label: [e.risk_code, e.origin === 'AI' ? 'AI' : e.origin === 'CALC' ? 'obliczenie' : 'źródło: BZP']
    .filter(Boolean)
    .join(', '),
  risk_code: e.risk_code,
  origin: e.origin,
  review_status: e.review_status,
  review_item_id: e.review_item_id ?? null,
})

function adaptPlan(p: RealCard['plan_vs_actual'][number]): PlanVsActual {
  const plan = p.planned ? (p.planned.value ?? 0) : Number(p.planned_money?.amount ?? 0)
  const actual = p.actual ? (p.actual.value ?? 0) : Number(p.actual_money?.amount ?? 0)
  return { key: p.key, label: p.label, delta_label: p.delta?.display ?? '', plan, actual, note: p.note ?? '' }
}

const adaptSimilar = (s: RealSimilar): SimilarCase => ({
  project_id: s.rm_id ?? s.ocid ?? '',
  title: s.title,
  why: s.why,
  score: s.score.value ?? 0,
  contributions: s.contributions.map((c) => ({ feature: FEATURE[c.feature] ?? 'zakres', value: c.value })),
  delay_days: numValue(s.outcome?.delay_days ?? null),
  cost_dev_pct: numValue(s.outcome?.cost_dev_pct ?? null),
})

export function adaptCard(raw: RealCard): ProjectCard {
  const gaps: ProjectGap[] = raw.gaps.map((g) => ({
    doc: docLabel(g.doc_type),
    state: EVIDENCE[g.evidence_state] ?? 'nie_ma_w_paczce',
    limits: g.limits,
  }))
  return {
    id: raw.id,
    // Pilot projects have an RM id and are not automatic cards, whatever the flag says.
    auto_card: !/^RM-/.test(raw.id),
    title: raw.title,
    buyer: { name: raw.buyer.name ?? '', nip: raw.buyer.nip, nip_valid: raw.buyer.nip_valid },
    summary: { text: raw.summary.sentence, provenance: provText(raw.summary.prov, 'obliczenie') },
    doc_counts: raw.doc_counts,
    plan_vs_actual: raw.plan_vs_actual.map(adaptPlan),
    timeline: (raw.steps ?? raw.timeline ?? []).map((s) => adaptStep(s, raw.id)),
    similar_cases: raw.similar.map(adaptSimilar),
    lessons: (raw.lessons ?? raw.events ?? []).map(adaptEvent),
    gaps,
    identifiers: raw.identifiers.map((i) => ({ key: i.k, value: i.v, check: i.verified ? 'ok' : null })),
    chat: { suggestions: raw.chat?.suggestions ?? [] },
  }
}
