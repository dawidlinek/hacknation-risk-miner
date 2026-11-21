import type { AuditEntry, DiffRow, VersionOption } from '@/api/contracts/audit'
import type { RealAuditEntry, RealCompare, RealHistory } from './types'

/** Prefixes of the entry ids shown in the global Historia (`evt-1187`, `kat-1`, `link-22`). */
const REF_PREFIX: Record<string, string> = {
  risk_event: 'evt',
  project_procedure: 'link',
  link_candidate: 'link',
  project: 'prj',
  review_item: 'sprawa',
  gold_example: 'gold',
  catalogue_version: 'kat',
  app_setting: 'demo',
  contract_performance: 'wyk',
  contract_change: 'zm',
  ingestion_run: 'run',
}

export function entryRef(
  table: string | null | undefined,
  rowId: number | null | undefined,
  id: number,
): string {
  if (!table) return `log-${id}`
  const prefix = table.startsWith('catalogue') ? 'kat' : (REF_PREFIX[table] ?? table)
  return `${prefix}-${rowId ?? id}`
}

export function adaptEntry(e: RealAuditEntry): AuditEntry {
  const id = e.audit_id ?? e.id
  return {
    id,
    at: e.at,
    actor: e.actor_kind,
    actor_label: e.actor_label,
    action: e.action_label,
    before: e.before || 'brak',
    after: e.after || 'brak',
    why: e.why,
    version: e.version ?? '',
    restorable: !!e.can_restore,
    object: e.object?.href
      ? { label: e.object.label, href: e.object.href }
      : e.object
        ? { label: e.object.label, href: '' }
        : null,
    note: e.note ?? null,
    ref: entryRef(e.table, e.row_id, id),
  }
}

export function adaptHistory(raw: RealHistory): {
  current: string
  versions: VersionOption[]
  entries: AuditEntry[]
} {
  return {
    current: raw.record_version,
    versions: raw.versions.map((v) => ({ version: v.version, label: v.label })),
    entries: raw.items.map(adaptEntry),
  }
}

export const adaptDiff = (raw: RealCompare): DiffRow[] =>
  raw.changes.map((c) => ({ field: c.field, before: c.before || 'brak', after: c.after || 'brak' }))
