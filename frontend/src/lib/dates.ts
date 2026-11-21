import { EMPTY } from './format'

/** '2024-06-04' or '2024-06-04T…' → '04.06.2024'. Date-only strings are split, never parsed. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (m) return `${m[3]}.${m[2]}.${m[1]}`
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Europe/Warsaw',
  }).format(d)
}

/** '21.11.2026 13:40'; short → '21.11 13:40' (Europe/Warsaw). */
export function fmtDateTime(iso: string | null | undefined, opts: { short?: boolean } = {}): string {
  if (!iso) return EMPTY
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const parts = new Intl.DateTimeFormat('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Europe/Warsaw',
  }).formatToParts(d)
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return opts.short
    ? `${g('day')}.${g('month')} ${g('hour')}:${g('minute')}`
    : `${g('day')}.${g('month')}.${g('year')} ${g('hour')}:${g('minute')}`
}
