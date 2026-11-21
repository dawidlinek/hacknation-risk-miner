// Pure balance math for 1.5 (frontend.md §2 1.5; mockup A5-Podzial.dc.html). Expected costs (tys. zł) and the
// premium factors come from GET /api/analyses/{id}/allocation; this file only sums them for the chosen positions.
import type { AllocationOut, AllocationRisk, Position } from '@/api/contracts/allocation'
import { NBSP } from '@/lib/format'
import { plural } from '@/lib/plural'

export type Premium = AllocationOut['premium']
export const WHO = ['Zamawiający', 'Wspólnie', 'Wykonawca'] as const

export interface Balance {
  buyer: number
  contractor: number
  premium: number
  /** bar segments: Σe of rows kept by the buyer, shared, given to the contractor */
  segments: { buyer: number; shared: number; contractor: number }
  off: number
}

type Row = Pick<AllocationRisk, 'code' | 'expected_cost_tpln' | 'controlled_by' | 'recommended'>

export function balance(rows: Row[], choices: Record<string, Position>, p: Premium): Balance {
  let buyer = 0
  let contractor = 0
  let premium = 0
  const seg = { buyer: 0, shared: 0, contractor: 0 }
  let off = 0
  for (const r of rows) {
    const e = r.expected_cost_tpln
    const w = choices[r.code] ?? r.recommended
    const ctl = r.controlled_by === 'contractor'
    if (w !== r.recommended) off++
    if (w === 0) {
      buyer += e
      seg.buyer += e
    } else if (w === 1) {
      buyer += e / 2
      contractor += e / 2
      seg.shared += e
      premium += e * (ctl ? p.shared_if_contractor_controls : p.shared)
    } else {
      contractor += e
      seg.contractor += e
      premium += e * (ctl ? p.contractor_if_contractor_controls : p.contractor)
    }
  }
  return { buyer, contractor, premium, segments: seg, off }
}

/** Round to 10 tys. zł for display ("560 tys. zł"); small amounts keep one decimal of tys. zł. */
export function fmtTpln(t: number): string {
  if (!Number.isFinite(t)) return 'brak'
  const v = Math.abs(t) >= 50 ? Math.round(t / 10) * 10 : Math.round(t)
  return `${new Intl.NumberFormat('pl-PL', { useGrouping: 'always' as unknown as boolean }).format(v).replace(/\s/g, NBSP)}${NBSP}tys.${NBSP}zł`
}

export function balanceNote(off: number): string {
  if (off === 0) return 'Podział zgodny z zaleceniami. Wykonawcy doliczą głównie za ryzyka dzielone.'
  return `${off} ${plural(off, ['ryzyko podzielone', 'ryzyka podzielone', 'ryzyk podzielonych'])} inaczej niż zalecamy. Sprawdź uwagi pod nimi.`
}

export function balanceAria(b: Balance): string {
  return `Po stronie zamawiającego ${fmtTpln(b.buyer)}, po stronie wykonawcy ${fmtTpln(b.contractor)}, wykonawcy doliczą w ofertach ${fmtTpln(b.premium)}.`
}

export function initialChoices(rows: Pick<AllocationRisk, 'code' | 'chosen'>[]): Record<string, Position> {
  return Object.fromEntries(rows.map((r) => [r.code, r.chosen])) as Record<string, Position>
}
