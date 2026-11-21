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
  it('lists sources once and names what is missing', () => {
    expect(a.sources).toEqual(['n = 11 186', 'brakuje: słownik TERYT powiatów'])
  })
  it('keeps known actions only', () => {
    expect(a.actions.map((x) => x.kind)).toEqual(['save', 'export_csv'])
  })
  it('AI answers get the long role label', () => {
    expect(adaptAnswer({ ...raw, role: 'ai', role_label: 'wniosek AI' }, 'q').role_label).toBe(
      'wniosek AI z zatwierdzonych zdarzeń',
    )
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

describe('adaptSession (demo personas)', () => {
  it('passes persona and read_only through the flat shape', () => {
    const s = adaptSession({
      role: 'expert',
      name: 'juror',
      initials: 'J',
      persona: 'juror',
      read_only: true,
    })
    expect(s.read_only).toBe(true)
    expect(s.persona).toBe('juror')
  })
  it('anonymous stays public', () => {
    expect(adaptSession({ user: null, role: 'public', name: null, initials: null }).role).toBe('public')
  })
})
