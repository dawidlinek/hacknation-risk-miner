// Contract for 4.1 Monitoring and drill-down 4.1a-4.1c (docs/impl/frontend.md section 4.1), as the UI consumes it.
// The adapter in api/adapters/monitoring.ts maps the real /api/monitoring/* shapes to these.
import type { Money } from './common'

export type RegionLevel = 'woj' | 'pow' | 'gmi'
export type MonitoringMode = 'done' | 'open'
export type MetricKey = 'late' | 'delay' | 'over' | 'chg' | 'imp' | 'sig'

export interface RegionStat {
  teryt: string // '12' | '1209' | '1209052'
  name: string // 'małopolskie'
  completed: number
  late_pct: number
  median_delay_days: number | null
  over_pct: number
  overpaid: Money
  total_value: Money
  changed_pct: number
  improper_pct: number
  signals: number
  insufficient: boolean // completed < 10
}

export interface RegionsOut {
  level: RegionLevel
  parent: string | null
  total_label: string // '11 210 umów zakończonych, 30% po terminie'
  items: RegionStat[]
}

export interface Signal {
  id: string // contract_id
  bzp: string // '2022/BZP 00195927'
  ocid: string
  buyer: string
  object: string
  value: Money
  days_late: number | null // > 90
  planned_end: string // ISO date
  signed_on: string | null
  changes: number
  parts: number
  teryt: { woj: string; pow: string; gmi: string | null }
  lon: number | null
  lat: number | null
}

export interface SignalsOut {
  total: number // in region
  items: Signal[]
}

export interface RegionKpi {
  key: string
  label: string // 'PO TERMINIE'
  value: string // display
  attention: boolean
}

export interface RegionDetail {
  terc: string
  name: string
  level: RegionLevel
  kpis: RegionKpi[]
  children: { terc: string; name: string; signals: number; buyers: string[] }[]
  signals_total: number
  on_map: number
  note: string
  csv_href: string
}

export interface ContractDetail {
  signal: Signal
  planned_days: number | null
  overdue_days: number | null
  region_late_pct: number | null
  region_median_delay: number | null
  sentence: string
  sources: {
    k: string
    v: string
    url?: string | null
    missing: boolean
    items?: { v: string; url?: string | null }[]
  }[]
  card_href: string // '/projekty/<ocid>'
  can_watch: boolean
  can_report: boolean
}

// Static geometry served from /geo/* (scripts/geo-split.mjs).
export interface GeoProps {
  terc: string
  name: string
  kind?: string
}
