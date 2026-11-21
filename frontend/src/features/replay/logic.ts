// Pure helpers for the monitoring time machine (W6, flag monitoring_replay). The backend replays the notices
// published up to `as_of` (GET /api/monitoring/signals?as_of=YYYY-MM-DD); this file only builds the steps.
import type { Signal } from '@/api/contracts/monitoring'

const pad = (n: number) => String(n).padStart(2, '0')

/** Last day of a month as ISO 'YYYY-MM-DD' (month 1..12). */
export function monthEnd(year: number, month: number): string {
  const d = new Date(Date.UTC(year, month, 0))
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}

/** Month-end steps from `from` (YYYY-MM) to `today` (YYYY-MM-DD); the last step is `today` itself. */
export function monthSteps(from: string, today: string): string[] {
  const [fy, fm] = from.split('-').map(Number)
  const [ty, tm] = today.split('-').map(Number)
  const out: string[] = []
  let y = fy
  let m = fm
  while (y < ty || (y === ty && m < tm)) {
    out.push(monthEnd(y, m))
    m += 1
    if (m > 12) {
      m = 1
      y += 1
    }
  }
  out.push(today)
  return out
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000)
}

/** Contracts that became overdue within the step: 1..stepDays days past their planned end on the step date. */
export function newInStep(items: Signal[], stepDays: number): Signal[] {
  return items.filter((s) => s.days_late !== null && s.days_late >= 1 && s.days_late <= stepDays)
}

export function deltaLabel(cur: number | null, prev: number | null): string {
  if (cur === null || prev === null) return ''
  const d = cur - prev
  if (d === 0) return 'bez zmian'
  return d > 0 ? `+${d}` : `−${Math.abs(d)}`
}

export const MONTHS = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru']

export function monthLabel(iso: string): string {
  const [y, m] = iso.split('-').map(Number)
  return `${MONTHS[m - 1]} ${y}`
}
