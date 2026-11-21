// Real GET /api/monitoring/* (D, api_contract 2.7) -> api/contracts/monitoring.ts.
import type { Money } from '@/api/contracts/common'
import type {
  ContractDetail,
  RegionDetail,
  RegionLevel,
  RegionStat,
  RegionsOut,
  Signal,
  SignalsOut,
} from '@/api/contracts/monitoring'
import type { RealNum } from './real'

interface RealMetrics {
  n_completed: number
  late_pct: number
  median_delay_days_late: number | null
  overpaid_pln: string
  value_pln: string
  over_pct: number
  changes_pct: number
  improper_pct: number
  signals: number
}

export interface RealRegions {
  level: RegionLevel
  parent: string | null
  total: { label: string; n: number }
  regions: { terc: string; name: string; metrics: RealMetrics }[]
}

const pln = (amount: string): Money => ({ amount, currency: 'PLN', vat_basis: 'gross' })

export function adaptRegions(raw: RealRegions): RegionsOut {
  const items: RegionStat[] = raw.regions.map((r) => ({
    teryt: r.terc,
    name: r.name,
    completed: r.metrics.n_completed,
    late_pct: r.metrics.late_pct,
    median_delay_days: r.metrics.median_delay_days_late,
    over_pct: r.metrics.over_pct,
    overpaid: pln(r.metrics.overpaid_pln),
    total_value: pln(r.metrics.value_pln),
    changed_pct: r.metrics.changes_pct,
    improper_pct: r.metrics.improper_pct,
    signals: r.metrics.signals,
    insufficient: r.metrics.n_completed < 10,
  }))
  return { level: raw.level, parent: raw.parent, total_label: raw.total.label, items }
}

export interface RealSignal {
  contract_id: number
  ocid: string
  bzp_number: string
  lot_no: number
  n_parts: number
  buyer_name: string
  title: string
  value: {
    amount: number | string | null
    currency: string | null
    vat_basis: 'net' | 'gross' | 'unknown' | null
  }
  signed_on: string | null
  planned_end_on: string
  days_overdue: RealNum
  n_change_notices: number
  has_performance: boolean
  woj: string
  pow: string
  gmi: string | null
  lon: number | null
  lat: number | null
}

export const adaptSignal = (s: RealSignal): Signal => ({
  id: String(s.contract_id),
  bzp: s.bzp_number,
  ocid: s.ocid,
  buyer: s.buyer_name,
  object: s.title,
  value: s.value,
  days_late: s.days_overdue.value,
  planned_end: s.planned_end_on,
  signed_on: s.signed_on,
  changes: s.n_change_notices,
  parts: s.n_parts,
  teryt: { woj: s.woj, pow: s.pow, gmi: s.gmi },
  lon: s.lon,
  lat: s.lat,
})

export interface RealSignals {
  total: number
  items: RealSignal[]
}
export const adaptSignals = (raw: RealSignals): SignalsOut => ({
  total: raw.total,
  items: raw.items.map(adaptSignal),
})

export interface RealRegionDetail {
  terc: string
  name: string
  level: RegionLevel
  kpis: { key: string; label: string; attention?: boolean; value: RealNum }[]
  children: { terc: string; name: string; signals: number; buyers: string[] }[]
  signals: { total: number; on_map: number; csv_href: string; note: string }
}

export const adaptRegionDetail = (raw: RealRegionDetail): RegionDetail => ({
  terc: raw.terc,
  name: raw.name,
  level: raw.level,
  kpis: raw.kpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value.display,
    attention: Boolean(k.attention) || k.key === 'signals',
  })),
  children: raw.children,
  signals_total: raw.signals.total,
  on_map: raw.signals.on_map,
  note: raw.signals.note,
  csv_href: raw.signals.csv_href,
})

export interface RealContract {
  signal: RealSignal
  plan: { planned_days: RealNum; overdue_days: RealNum }
  compare: { region_late_pct: RealNum; region_median_delay: RealNum; sentence: string }
  sources: {
    k: string
    v: string
    url?: string | null
    missing?: boolean
    items?: { v: string; url?: string | null }[]
  }[]
  actions: { card_href: string; can_watch: boolean; can_report: boolean }
}

export const adaptContract = (raw: RealContract): ContractDetail => ({
  signal: adaptSignal(raw.signal),
  planned_days: raw.plan.planned_days.value,
  overdue_days: raw.plan.overdue_days.value,
  region_late_pct: raw.compare.region_late_pct.value,
  region_median_delay: raw.compare.region_median_delay.value,
  sentence: raw.compare.sentence,
  sources: raw.sources.map((s) => ({ ...s, missing: Boolean(s.missing) })),
  card_href: raw.actions.card_href,
  can_watch: raw.actions.can_watch,
  can_report: raw.actions.can_report,
})
