// Pure helpers for the "new document" panel: processing steps, extracted facts, "Co się zmieniło".
import { fmtDate, fmtDateTime } from '@/lib/dates'
import type { ChangeLine, LineDecision, RealAnalysis, RealFact, RealStep, StepState } from './types'

export const STATE_LABEL: Record<StepState, string> = {
  done: 'gotowe',
  running: 'w toku',
  queued: 'w kolejce',
  pending: 'czeka',
  failed: 'błąd',
}

/** Whether the panel should keep polling: something is running or the pipeline has not reached linking yet. */
export function stillProcessing(steps: RealStep[]): boolean {
  if (steps.some((s) => s.state === 'failed')) return false
  const linking = steps.find((s) => s.key === 'linking')
  if (linking?.state === 'done') return false
  return (
    steps.some((s) => s.state === 'running' || s.state === 'queued') ||
    steps.some((s) => s.key === 'extraction' && s.state !== 'done')
  )
}

export const stepsSummary = (steps: RealStep[]): string => {
  const failed = steps.find((s) => s.state === 'failed')
  if (failed) return `Błąd na etapie: ${failed.label.toLowerCase()}. ${failed.error ?? ''}`.trim()
  const done = steps.filter((s) => s.state === 'done').length
  if (done === steps.length)
    return 'Dokument przetworzony. Wnioski czekają na decyzję eksperta w Przeglądzie.'
  const cur = steps.find((s) => s.state !== 'done')
  return `Etap ${done + 1} z ${steps.length}: ${cur?.label.toLowerCase() ?? ''}, ${STATE_LABEL[cur?.state ?? 'pending']}.`
}

const FIELD_LABEL: Record<string, string> = {
  delta_months: 'zmiana terminu (miesiące)',
  delta_days: 'zmiana terminu (dni)',
  old_end: 'dotychczasowy termin',
  new_end: 'nowy termin',
  planned_end_calc: 'nowy planowany koniec umowy',
  requested_end: 'wnioskowany termin realizacji projektu',
  delta_value: 'kwota zmiany',
  value: 'kwota',
  legal_basis: 'podstawa prawna',
  contract_number: 'numer umowy',
  contract_date: 'data zawarcia umowy',
  kpo: 'numer KPO',
}

export const factLabel = (f: Pick<RealFact, 'field'>): string =>
  FIELD_LABEL[f.field] ?? f.field.replace(/_/g, ' ')

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
export function factDisplay(f: RealFact): string {
  if (f.display) return f.display
  const v = f.value
  if (typeof v === 'string' && ISO_DAY.test(v)) return fmtDate(v)
  if (typeof v === 'number') return String(v).replace('.', ',')
  if (Array.isArray(v)) return v.join(', ')
  if (v && typeof v === 'object') return JSON.stringify(v)
  return v === null || v === undefined || v === '' ? 'brak' : String(v)
}

export const VERIFY_LABEL: Record<string, { text: string; tone: 'ok' | 'warn' | 'neutral' }> = {
  exact: { text: 'cytat sprawdzony na stronie', tone: 'ok' },
  structured_field: { text: 'pole sprawdzone', tone: 'ok' },
  fuzzy: { text: 'cytat przybliżony', tone: 'warn' },
  unverified: { text: 'cytat niezweryfikowany', tone: 'warn' },
}

export const ORIGIN_NAME: Record<string, string> = { CALC: 'reguła', AI: 'odczyt modelu', SOURCE: 'źródło' }

export const GROUPS: {
  key: 'potwierdzone' | 'zmienione' | 'nowe' | 'zamkniete'
  title: string
  hint: string
}[] = [
  { key: 'potwierdzone', title: 'Potwierdzone', hint: 'zgodne z BZP i rejestrami' },
  { key: 'zmienione', title: 'Zmienione', hint: 'inne niż dotąd w bazie' },
  { key: 'nowe', title: 'Nowe', hint: 'pojawiły się dzięki dokumentowi' },
  { key: 'zamkniete', title: 'Zamknięte', hint: 'sprawy i luki rozwiązane' },
]

export const lineText = (l: ChangeLine): string =>
  l.before !== undefined && l.after !== undefined ? `${l.before} → ${l.after}` : (l.value ?? l.where ?? '')

/** Links to the queue only for experts; the public view never links to Przegląd. */
export const reviewLinks = (a: Pick<RealAnalysis, 'review_items'>, isExpert: boolean) =>
  isExpert ? a.review_items : []

export const sensitivityLabel = (s: string | null | undefined) => (s === 'public' ? 'publiczny' : 'poufny')

/** "zatwierdzone przez Ekspert test, 21.11.2026 13:10" (audit trail of a decided proposal). */
export const decisionText = (d: LineDecision): string =>
  `${d.action_label} przez ${d.by_label}, ${fmtDateTime(d.at)}`

export const rerunText = (codes: string[] | undefined): string | null =>
  codes && codes.length > 0
    ? `Analizy do przeliczenia (nowe dane w przypadku podobnym): ${codes.join(', ')}.`
    : null
