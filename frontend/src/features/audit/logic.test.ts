import { describe, expect, it } from 'vitest'
import type { AuditEntry } from '@/api/contracts/audit'
import { adaptDiff, adaptEntry, adaptHistory, entryRef } from './adapt'
import {
  avatarOf,
  dayRange,
  filterByWho,
  historyStats,
  parseKind,
  parseWho,
  restoreConfirm,
  splitTime,
} from './logic'
import type { RealAuditEntry } from './types'

const real = (over: Partial<RealAuditEntry> = {}): RealAuditEntry => ({
  id: 5,
  audit_id: 5,
  at: '2026-11-21T12:41:00+01:00',
  actor_kind: 'model',
  actor_label: 'Model Bielik 11B',
  action: 'review.approve',
  action_label: 'zatwierdził zdarzenie ryzyka',
  object: { label: 'zdarzenie ryzyka w RM-2026-003', href: '/projekty/RM-2026-003' },
  table: 'risk_event',
  row_id: 1187,
  before: 'review_status: proposed',
  after: 'review_status: approved',
  why: 'sprawa #812',
  note: null,
  version: 'v7',
  can_restore: true,
  ...over,
})

describe('audit adapter', () => {
  it('maps a real entry to the AuditEntry contract', () => {
    const e = adaptEntry(real({ actor_kind: 'expert', actor_label: 'Ekspert' }))
    expect(e).toMatchObject({
      id: 5,
      actor: 'expert',
      action: 'zatwierdził zdarzenie ryzyka',
      version: 'v7',
      restorable: true,
      ref: 'evt-1187',
      object: { label: 'zdarzenie ryzyka w RM-2026-003', href: '/projekty/RM-2026-003' },
    })
  })
  it('empty before/after read "brak", object without href keeps its label', () => {
    const e = adaptEntry(
      real({ before: '', after: '', object: { label: 'rekord', href: null }, can_restore: undefined }),
    )
    expect(e.before).toBe('brak')
    expect(e.after).toBe('brak')
    expect(e.restorable).toBe(false)
    expect(e.object).toEqual({ label: 'rekord', href: '' })
  })
  it('entry refs by table', () => {
    expect(entryRef('catalogue_risk', 3, 9)).toBe('kat-3')
    expect(entryRef('project_procedure', 22, 9)).toBe('link-22')
    expect(entryRef(null, null, 9)).toBe('log-9')
    expect(entryRef('something_else', null, 9)).toBe('something_else-9')
  })
  it('history and diff', () => {
    const h = adaptHistory({
      record_version: 'v3',
      versions: [{ version: 'v1', label: 'v1' }],
      items: [real()],
    })
    expect(h.current).toBe('v3')
    expect(h.entries).toHaveLength(1)
    expect(
      adaptDiff({
        from: 'v1',
        to: 'v3',
        changes: [{ table: 'x', row_id: 1, field: 'lots', before: '', after: '[1, 2]' }],
      }),
    ).toEqual([{ field: 'lots', before: 'brak', after: '[1, 2]' }])
  })
})

describe('audit logic', () => {
  const entries: AuditEntry[] = [
    adaptEntry(real({ id: 1, audit_id: 1, actor_kind: 'expert' })),
    adaptEntry(real({ id: 2, audit_id: 2, actor_kind: 'model' })),
    adaptEntry(real({ id: 3, audit_id: 3, actor_kind: 'system', can_restore: false })),
    adaptEntry(real({ id: 4, audit_id: 4, actor_kind: 'system', can_restore: false })),
  ]
  it('filters and stats', () => {
    expect(filterByWho(entries, 'wszystko')).toHaveLength(4)
    expect(filterByWho(entries, 'system').map((e) => e.id)).toEqual([3, 4])
    expect(filterByWho(entries, 'ekspert')).toHaveLength(1)
    expect(historyStats(entries, 'v9')).toEqual({ version: 'v9', expert: 1, model: 1, system: 2 })
  })
  it('parses URL params with safe fallbacks', () => {
    expect(parseWho('model')).toBe('model')
    expect(parseWho('xx')).toBe('wszystko')
    expect(parseKind('katalog')).toBe('katalog')
    expect(parseKind(undefined)).toBe('wszystko')
  })
  it('time and day range use Europe/Warsaw', () => {
    expect(splitTime('2026-11-21T12:41:00+01:00')).toEqual({ time: '12:41', date: '21.11.2026' })
    expect(splitTime('2026-11-21T11:41:00Z')).toEqual({ time: '12:41', date: '21.11.2026' })
    const r = dayRange('2026-11-21')
    expect(r).not.toBeNull()
    expect(new Date(r!.until).getTime() - new Date(r!.since).getTime()).toBe(24 * 3600 * 1000)
    expect(dayRange('21.11.2026')).toBeNull()
  })
  it('avatars: E round ink, S square grey, AI violet square', () => {
    expect(avatarOf('expert')).toMatchObject({ letter: 'E' })
    expect(avatarOf('expert').cls).toContain('rounded-pill')
    expect(avatarOf('model')).toMatchObject({ letter: 'AI' })
    expect(avatarOf('system').cls).toContain('prov-source')
  })
  it('restore confirmation names the version and the new entry', () => {
    expect(restoreConfirm({ version: 'v6' })).toBe(
      'Przywrócić wersję przed zmianą v6? Powstanie nowy wpis w dzienniku.',
    )
    expect(restoreConfirm({ version: '' })).toContain('Powstanie nowy wpis')
  })
})
