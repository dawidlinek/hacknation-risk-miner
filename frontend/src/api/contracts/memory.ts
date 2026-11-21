// W10 organization memory and W17 sector lessons digest (backend: analytics/org_memory.py, analytics/lessons.py).
import type { Money } from './common'

export interface CalcNum {
  value: number | null
  display: string
  unit: string
  prov: {
    role: 'calc' | 'source' | 'case' | 'ai'
    review_status: string
    n?: number | null
    method?: string | null
    insufficient?: boolean | null
    assumption?: boolean | null
  }
}

export interface MemoryContract {
  contract_id: number
  title: string | null
  ocid: string
  href: string
  signed_on: string | null
  planned_end_on: string | null
  counterparty: string | null
  value: Money
  state: 'completed' | 'ongoing' | 'unknown'
  state_label: string
  delay_days: number | null
}

export interface RoleMemory {
  role: 'contractor' | 'buyer'
  contracts_total: CalcNum
  completed: CalcNum
  ongoing: CalcNum
  late_share: CalcNum
  median_delay_days: CalcNum
  annexes: CalcNum
  contracts_with_change_share: CalcNum
  change_kinds: { kind: string; label: string; count: number; share: CalcNum }[]
  top_risks: { code: string; name: string; events: number; cases: number; count: CalcNum; href: string }[]
  recent_contracts: MemoryContract[]
  ongoing_value: { money: Money; n: number; method: string }
}

export interface MemoryFlag {
  code: string
  rule: string
  title: string
  text: string
  risk_codes: string[]
  n: number | null
}

export interface OrganizationMemory {
  organization: {
    nip: string
    name: string
    roles: string[]
    province: string | null
    city: string | null
    nip_valid: boolean | null
  }
  as_of: string
  min_n: number
  contractor: RoleMemory
  buyer: RoleMemory
  load: {
    ongoing: CalcNum
    history_median: CalcNum
    ongoing_value: { money: Money; n: number; method: string }
    history_median_value: { money: Money; n: number; method: string }
    months: number
  }
  flags: MemoryFlag[]
  note: string
}

export interface LessonSource {
  count: number
  cases: number
  text: string | null
  quote: string | null
  url: string | null
  field_code: string | null
  case_id: string | null
  title: string | null
  href: string | null
  event_id: number
  review_status: string
  origin: string
  effect?: string | null
}

export interface LessonCategory {
  code: string
  name: string
  events: CalcNum
  cases: CalcNum
  approved_events: number
  delay_median_days: CalcNum
  delay_total_days: CalcNum
  cost_median: CalcNum
  cost_total: CalcNum
  causes: LessonSource[]
  mitigations_measured: LessonSource[]
  mitigations_proposed: {
    code: string
    label: string
    rationale: string | null
    status: string
    assumption: boolean
  }[]
}

export interface LessonsDigest {
  sector: string
  scope: string
  totals: { events: CalcNum; cases: CalcNum; approved_events: number; excluded_events: number }
  min_n: number
  categories: LessonCategory[]
}
