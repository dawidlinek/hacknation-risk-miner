import type { LinkRef } from './common'

export type Position = 0 | 1 | 2 // 0 Zamawiający, 1 Wspólnie, 2 Wykonawca
export interface AllocationRisk {
  code: string
  title: string
  impact_label: string
  expected_cost_tpln: number
  controlled_by: 'buyer' | 'neither' | 'contractor'
  recommended: Position
  chosen: Position
  how: [string, string, string]
  warning: string
  cases?: LinkRef[]
}
export interface AllocationOut {
  risks: AllocationRisk[]
  premium: { shared: number; contractor: number; shared_if_contractor_controls: number; contractor_if_contractor_controls: number }
  premium_attention_tpln: number
  pack: {
    items: { key: string; title: string; note: string; included: boolean }[]
    pending_ai: number
    formats: ('docx' | 'pdf' | 'csv' | 'json')[]
  }
}
export interface AllocationPutIn {
  choices: Record<string, Position>
}
