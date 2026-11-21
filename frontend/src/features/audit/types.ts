// Real API shapes for the audit log (api_contract §2.4 2.6, §2.8). Adapted to api/contracts/audit.ts AuditEntry in adapt.ts.
export interface RealAuditEntry {
  id: number
  audit_id?: number
  at: string
  actor_kind: 'expert' | 'model' | 'system'
  actor_label: string
  action: string
  action_label: string
  object?: { label: string; href: string | null } | null
  table?: string | null
  row_id?: number | null
  before: string
  after: string
  why: string
  note?: string | null
  version?: string | null
  can_restore?: boolean
}

export interface RealHistory {
  record_version: string
  versions: { version: string; label: string }[]
  items: RealAuditEntry[]
}

export interface RealAuditPage {
  total: number
  limit: number
  offset: number
  items: RealAuditEntry[]
}

export interface RealCompare {
  from: string
  to: string
  changes: { table: string; row_id: number; field: string; before: string; after: string }[]
}

export type WhoFilter = 'wszystko' | 'ekspert' | 'model' | 'system'
export type GlobalKind = 'wszystko' | 'ekspert' | 'import' | 'katalog' | 'model'
