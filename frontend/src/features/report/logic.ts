// Pure helpers for 1.2 Raport (frontend.md §2 1.2). All numbers come from GET /api/analyses/{id}.
import type { AnalysisReport, QuestionCard, ReportFlag } from '@/api/contracts/analyses'
import type { SimilarCase } from '@/api/contracts/common'
import { fmtDays, fmtPct } from '@/lib/format'

/** Server extras on top of the frontend contract (api_contract J2 fields). */
export type Report = AnalysisReport & {
  code?: string
  text?: string
  missing?: { no: string; rule: string; title: string; state_label?: string; limits?: string }[]
  reference_class:
    | (AnalysisReport['reference_class'] & {
        widened?: boolean
        widen_note?: string | null
        reweight_note?: string | null
        sector?: string
        sector_label?: string
        sector_status?: string
        funnel: { label: string; n: number; width_pct?: number }[]
      })
    | null
  similar_cases: ReportCase[]
  shares?: Record<string, { k: number; n: number; value: number | null; display: string }>
  data_as_of?: string | null
  stale_sections?: string[]
  /** similar cases that got new approved data since this version (new documents pipeline) */
  stale_cases?: { case: string; label?: string | null; reason?: string | null; at?: string }[]
  features?: { key: string; label: string; display: string }[]
}

export type ReportCase = SimilarCase & {
  rank?: number
  href?: string
  rm_id?: string | null
  is_pilot?: boolean
  badge?: string | null
  diff?: string
  risk_overlap?: { risk: string; text: string }[]
  buyer_name?: string | null
}

export type ReportQuestion = QuestionCard & {
  key_display?: string | null
  answer_step?: number | null
  missing?: string
}

/** Position (0..100 %) of x on a question card's scale, clamped. */
export function pos(x: number | null | undefined, scale: { min: number; max: number }): number | null {
  if (x === null || x === undefined || !Number.isFinite(x)) return null
  const span = scale.max - scale.min || 1
  return Math.min(100, Math.max(0, ((x - scale.min) / span) * 100))
}

export interface RangeGeometry {
  band: { left: number; width: number } | null
  median: number | null
  you: number | null
  programme: number | null
}

export function rangeGeometry(q: QuestionCard): RangeGeometry {
  const a = q.band ? pos(q.band.from, q.scale) : null
  const b = q.band ? pos(q.band.to, q.scale) : null
  return {
    band: a !== null && b !== null ? { left: a, width: Math.max(1, b - a) } : null,
    median: pos(q.median, q.scale),
    you: pos(q.you, q.scale),
    programme: pos(q.programme_end, q.scale),
  }
}

export const ANSWER_TONE: Record<QuestionCard['tone'], string> = {
  bad: 'text-attention-text',
  good: 'text-success-text',
  neutral: 'text-text-secondary',
}

export function keyDisplay(q: ReportQuestion): string {
  if (q.insufficient) return 'za mało danych'
  if (q.key_display) return q.key_display
  if (q.key_value === null) return 'brak danych'
  return q.key_kind === 'chance'
    ? `${fmtPct(q.key_value, { fromShare: true })} szans`
    : `${q.key_value} mln zł/km`
}

/** Link from a card to the simulation with the right metric. */
export function cardHref(id: string, q: QuestionCard): string {
  const miara = q.metric === 'cost' ? 'koszt' : q.metric === 'comp' ? 'konkurencja' : 'czas'
  return `/analizy/${encodeURIComponent(id)}/symulacja?miara=${miara}`
}

export type FlagDot = 'calc' | 'ai-approved' | 'ai-proposed' | 'ai-rejected'

export function flagDot(f: ReportFlag): FlagDot {
  if (f.origin === 'CALC') return 'calc'
  if (f.review_status === 'approved' || f.review_status === 'edited') return 'ai-approved'
  if (f.review_status === 'rejected') return 'ai-rejected'
  return 'ai-proposed'
}

/** CALC flags first (rule order), then AI flags; rejected AI flags are dropped. */
export function sortFlags(flags: ReportFlag[]): ReportFlag[] {
  const kept = flags.filter((f) => flagDot(f) !== 'ai-rejected')
  return [...kept.filter((f) => f.origin === 'CALC'), ...kept.filter((f) => f.origin !== 'CALC')]
}

/**
 * Identical warnings found on several pages (same title, text, origin and review state) show once; their meta lines
 * merge when only the last part (the page) differs: "R03.3, reguła, PFU s. 2" + "... PFU s. 6" -> "..., PFU s. 2, PFU s. 6".
 */
export function groupFlags(flags: ReportFlag[]): ReportFlag[] {
  const out: ReportFlag[] = []
  const metas = new Map<string, string[]>()
  for (const f of flags) {
    const key = [f.title, f.text, f.origin, f.review_status].join('|')
    const seen = metas.get(key)
    if (seen) {
      seen.push(f.meta)
      continue
    }
    metas.set(key, [f.meta])
    out.push(f)
  }
  return out.map((f) => {
    const all = metas.get([f.title, f.text, f.origin, f.review_status].join('|')) ?? [f.meta]
    if (all.length === 1) return f
    const head = (m: string) => m.split(', ').slice(0, -1).join(', ')
    const same = all.every((m) => head(m) === head(all[0]) && head(m) !== '')
    const meta = same
      ? `${head(all[0])}, ${[...new Set(all.map((m) => m.split(', ').at(-1)))].join(', ')}`
      : [...new Set(all)].join('; ')
    return { ...f, meta }
  })
}

export function flagHref(id: string, f: ReportFlag): string | null {
  if (!f.doc) return null
  const hash = f.doc.note_no ? `#u${f.doc.note_no}` : ''
  return `/analizy/${encodeURIComponent(id)}/dokumenty/${f.doc.document_id}?s=${f.doc.page}${hash}`
}

export const SIM_COLOR: Record<string, string> = {
  podsektor: 'var(--sim-podsektor)',
  formula: 'var(--sim-formula)',
  zakres: 'var(--sim-zakres)',
  wartosc: 'var(--sim-wartosc)',
  tekst: 'var(--sim-tekst)',
  inne: 'var(--border)',
}
export const SIM_LABEL: Record<string, string> = {
  podsektor: 'podsektor',
  formula: 'formuła',
  zakres: 'zakres i ilości',
  wartosc: 'wartość',
  tekst: 'opis (tekst)',
  inne: 'inne cechy',
}

/** Stacked bar segments in % of the full bar (score 1.0 = 100 %); they sum to the score. */
export function similaritySegments(
  c: SimilarCase,
): { feature: string; pct: number; color: string; label: string }[] {
  return c.contributions
    .filter((x) => x.value > 0)
    .map((x) => ({
      feature: x.feature,
      pct: x.value * 100,
      color: SIM_COLOR[x.feature] ?? 'var(--border)',
      label: SIM_LABEL[x.feature] ?? x.feature,
    }))
}

export function caseDelay(c: SimilarCase): string {
  if (c.delay_days === null || c.delay_days === undefined) return 'termin: b.d.'
  return c.delay_days === 0 ? 'w terminie' : fmtDays(c.delay_days)
}

export function caseCost(c: SimilarCase): string {
  if (c.cost_dev_pct === null || c.cost_dev_pct === undefined) return 'koszt: b.d.'
  return fmtPct(c.cost_dev_pct, { signed: true, digits: 1 })
}

export function caseHref(c: ReportCase): string {
  return c.href ?? `/projekty/${encodeURIComponent(c.project_id)}`
}

/** Funnel bar width as in the mockup: max(6, sqrt(n / n_all) * 100) %. */
export function funnelWidth(n: number, nAll: number): number {
  return nAll > 0 ? Math.max(6, Math.sqrt(n / nAll) * 100) : 6
}

export function isRunning(r: Pick<AnalysisReport, 'status'>): boolean {
  return r.status === 'running'
}

/** "Nowe dane w przypadku podobnym: Bestwina (nowy protokół konieczności). Uruchom analizę ponownie…" */
export function staleCasesText(cases: NonNullable<Report['stale_cases']>): string {
  const parts = cases.map((c) => `${(c.label ?? c.case).slice(0, 60)}${c.reason ? ` (${c.reason})` : ''}`)
  return `Nowe dane w ${cases.length === 1 ? 'przypadku podobnym' : 'przypadkach podobnych'}: ${parts.join('; ')}. Uruchom analizę ponownie, żeby je uwzględnić.`
}
