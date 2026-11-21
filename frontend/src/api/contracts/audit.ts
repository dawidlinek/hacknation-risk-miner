// Contract for 2.6 Historia zmian projektu and D3 Historia (docs/impl/frontend.md sections 2.6, D3).
import type { LinkRef } from './common'

export type AuditActor = 'expert' | 'model' | 'system'

export interface AuditEntry {
  id: number
  at: string // ISO datetime
  actor: AuditActor
  actor_label: string // 'Ekspert' | 'Model Bielik 11B (Polska)' | 'System'
  action: string // 'zatwierdził zdarzenie R01 ...'
  before: string
  after: string
  why: string
  version: string // 'v7'
  restorable: boolean
  object?: LinkRef | null // global Historia
  note?: string | null // global Historia: 'katalog v1.2 → v1.3'
  ref?: string | null // global Historia: 'kat-v1.3'
}

export interface VersionOption {
  version: string
  label: string // 'v1, import 12:05'
}

export interface DiffRow {
  field: string
  before: string
  after: string
}

export interface AuditStat {
  label: string
  value: string
}

export type GlobalAuditKind = 'expert' | 'import' | 'catalogue' | 'model'

export interface AuditQuery {
  actor?: AuditActor
  kind?: GlobalAuditKind
  day?: string // ISO date
}
