// Shapes the real backend returns (docs/impl/api_contract.md, api/prov.py) shared by the F2 adapters.
import type { Money, Origin, ReviewStatus } from '@/api/contracts/common'

export interface RealRef {
  kind: string
  id: string
  label: string
  url?: string | null
  page_no?: number | null
  field_code?: string | null
  quote?: string | null
}

export interface RealProv {
  role: 'source' | 'calc' | 'case' | 'ai'
  review_status: ReviewStatus
  n?: number | null
  method?: string | null
  refs?: RealRef[]
  insufficient?: boolean | null
}

/** `Num`: a value that carries its display string and provenance. */
export interface RealNum {
  value: number | null
  display: string
  unit: string
  prov?: RealProv
}

export type RealMoney = Money

export const ROLE_TO_ORIGIN: Record<RealProv['role'], Origin> = {
  source: 'SOURCE',
  calc: 'CALC',
  case: 'CASE',
  ai: 'AI',
}

const ROLE_LABEL: Record<RealProv['role'], string> = {
  source: 'źródło',
  calc: 'obliczenie',
  case: 'przypadek',
  ai: 'AI',
}

/** The mono line under a number: "obliczenie, n = 84". */
export function provText(prov: RealProv | null | undefined, fallback = ''): string {
  if (!prov) return fallback
  const n =
    prov.n !== null && prov.n !== undefined
      ? `, n = ${prov.n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')}`
      : ''
  return `${ROLE_LABEL[prov.role]}${n}`
}

export const numValue = (x: RealNum | null | undefined): number | null => (x ? x.value : null)
