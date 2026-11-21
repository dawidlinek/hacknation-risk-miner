import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { adaptSession } from '@/auth/session'
import { adaptAnswer, askErrorMessage, type RealAnswer } from './api'

const raw: RealAnswer = {
  id: 'q180',
  code: null,
  role: 'calc',
  role_label: 'obliczenie',
  text: 'Najczęściej po terminie kończy województwo lubuskie.',
  bars: [
    { label: 'lubuskie', value: 43.6, display: '43,6', highlight: true },
    { label: 'dolnośląskie', value: 40.3, display: '40,3', highlight: false },
  ],
  method: { kind: 'template', sql: 'SELECT 1', template: 'ask:woj_late' },
  sources: [{ kind: 'query', id: 'v_ask_contract', label: 'n = 11 186' }],
  n: 11186,
  missing: ['słownik TERYT powiatów'],
  actions: [
    { kind: 'save', label: 'Zapisz jako rekord', href: null },
    { kind: 'rows_csv', label: 'Pobierz wiersze (CSV)', href: null },
    { kind: 'unknown_kind', label: 'x', href: null },
  ],
}

describe('adaptAnswer', () => {
  const a = adaptAnswer(raw, 'Które województwa?')
  it('maps role, bars and sql', () => {
    expect(a.role).toBe('obliczenie')
    expect(a.bars?.[0]).toEqual({ label: 'lubuskie', value: 43.6, display: '43,6', attention: true })
    expect(a.sql).toBe('SELECT 1')
    expect(a.method).toBe('ask:woj_late')
  })
  it('lists sources once and leaves out the "brakuje" notes', () => {
    expect(a.sources).toEqual(['n = 11 186'])
  })
  it('keeps known actions only', () => {
    expect(a.actions.map((x) => x.kind)).toEqual(['save', 'export_csv'])
  })
  it('AI answers keep the label the backend sends (a report chat is not built from approved events)', () => {
    expect(adaptAnswer({ ...raw, role: 'ai', role_label: 'wniosek AI' }, 'q').role_label).toBe('wniosek AI')
  })
  it('repeated sources become one chip each', () => {
    const src = { kind: 'query', id: 'x', label: 'klasa: kanalizacja sanitarna (82 umowy z BZP)' }
    const dup = adaptAnswer(
      { ...raw, n: null, sources: [src, src, { ...src, label: 'Katalog: czerwone flagi' }, src] },
      'q',
    )
    expect(dup.sources).toEqual(['klasa: kanalizacja sanitarna (82 umowy z BZP)', 'Katalog: czerwone flagi'])
  })
})

describe('error messages', () => {
  it('429 reads as a rate-limit hint', () => {
    expect(askErrorMessage(new ApiError(429, 'x'))).toBe('Za dużo pytań naraz. Spróbuj za minutę.')
  })
  it('other errors fall back to a Polish sentence', () => {
    expect(askErrorMessage(new Error('boom'))).toContain('Nie udało się odpowiedzieć')
  })
})

describe('adaptSession (demo user)', () => {
  it('passes the single demo user through the flat shape', () => {
    const s = adaptSession({
      role: 'admin',
      name: 'Ekspert (demo)',
      initials: 'ED',
      persona: 'demo',
      read_only: false,
    })
    expect(s.role).toBe('admin')
    expect(s.read_only).toBe(false)
    expect(s.persona).toBe('demo')
  })
  it('anonymous stays public', () => {
    expect(adaptSession({ user: null, role: 'public', name: null, initials: null }).role).toBe('public')
  })
})
