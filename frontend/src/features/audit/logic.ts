import type { AuditActor, AuditEntry } from '@/api/contracts/audit'
import type { GlobalKind, WhoFilter } from './types'

export const WHO_OPTIONS: { value: WhoFilter; label: string }[] = [
  { value: 'wszystko', label: 'Wszystko' },
  { value: 'ekspert', label: 'Decyzje eksperta' },
  { value: 'model', label: 'Propozycje modelu' },
  { value: 'system', label: 'System' },
]

export const WHO_ACTOR: Record<WhoFilter, AuditActor | null> = {
  wszystko: null,
  ekspert: 'expert',
  model: 'model',
  system: 'system',
}

export const parseWho = (v: string | undefined): WhoFilter =>
  WHO_OPTIONS.some((o) => o.value === v) ? (v as WhoFilter) : 'wszystko'

export const filterByWho = (entries: AuditEntry[], who: WhoFilter) => {
  const a = WHO_ACTOR[who]
  return a ? entries.filter((e) => e.actor === a) : entries
}

export const GLOBAL_OPTIONS: { value: GlobalKind; label: string }[] = [
  { value: 'wszystko', label: 'Wszystko' },
  { value: 'ekspert', label: 'Decyzje eksperta' },
  { value: 'import', label: 'Import i wzbogacanie' },
  { value: 'katalog', label: 'Katalog' },
  { value: 'model', label: 'Model' },
]

/** Backend `category` for the global filter. */
export const GLOBAL_CATEGORY: Record<GlobalKind, string | null> = {
  wszystko: null,
  ekspert: 'expert',
  import: 'import',
  katalog: 'catalogue',
  model: 'model',
}

export const parseKind = (v: string | undefined): GlobalKind =>
  GLOBAL_OPTIONS.some((o) => o.value === v) ? (v as GlobalKind) : 'wszystko'

/** ISO day -> [since, until) for GET /api/audit (Warsaw midnight, DST safe through the offset of that day). */
export function dayRange(day: string): { since: string; until: string } | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null
  const d = new Date(`${day}T00:00:00`)
  if (Number.isNaN(d.getTime())) return null
  const next = new Date(d)
  next.setDate(next.getDate() + 1)
  return { since: d.toISOString(), until: next.toISOString() }
}

/** Counts shown under the filters of the project history. */
export function historyStats(entries: AuditEntry[], current: string) {
  const n = (a: AuditActor) => entries.filter((e) => e.actor === a).length
  return { version: current, expert: n('expert'), model: n('model'), system: n('system') }
}

/** '2026-11-21T12:41:00+01:00' -> { time: '12:41', date: '21.11.2026' } in Europe/Warsaw. */
export function splitTime(iso: string): { time: string; date: string } {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { time: '', date: iso }
  const p = new Intl.DateTimeFormat('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Europe/Warsaw',
  }).formatToParts(d)
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? ''
  return { time: `${g('hour')}:${g('minute')}`, date: `${g('day')}.${g('month')}.${g('year')}` }
}

export const avatarOf = (a: AuditActor): { letter: string; cls: string } =>
  a === 'expert'
    ? { letter: 'E', cls: 'rounded-pill bg-ink text-on-ink' }
    : a === 'model'
      ? { letter: 'AI', cls: 'rounded-[12px] bg-prov-ai text-white' }
      : { letter: 'S', cls: 'rounded-[12px] bg-prov-source text-white' }

export const restoreConfirm = (e: Pick<AuditEntry, 'version'>) =>
  e.version
    ? `Przywrócić wersję przed zmianą ${e.version}? Powstanie nowy wpis w dzienniku.`
    : 'Przywrócić wartość sprzed tej zmiany? Powstanie nowy wpis w dzienniku.'
