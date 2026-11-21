import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime } from './dates'
import {
  fmtDays,
  fmtDec,
  fmtInt,
  fmtMoney,
  fmtMoneyShort,
  fmtMonths,
  fmtN,
  fmtNip,
  fmtPct,
  fmtPp,
  fmtScore,
  isInsufficient,
  NBSP,
} from './format'
import { plural } from './plural'

const S = NBSP
describe('format', () => {
  it('money with NBSP grouping, string amounts, vat suffix', () => {
    const m = { amount: '2131590.00', currency: 'PLN', vat_basis: 'gross' as const }
    expect(fmtMoney(m)).toBe(`2${S}131${S}590,00${S}zł`)
    expect(fmtMoney(m, { vat: true })).toBe(`2${S}131${S}590,00${S}zł brutto`)
    expect(fmtMoney({ ...m, vat_basis: 'net' }, { vat: true })).toMatch(/netto$/)
    expect(fmtMoney({ amount: null, currency: 'PLN', vat_basis: null })).toBe('brak')
    expect(fmtMoney({ amount: 1234, currency: 'EUR', vat_basis: null })).toBe(`1${S}234,00${S}EUR`)
    expect([...fmtMoney(m)].some((c) => c === ' ' || c === ' ')).toBe(false)
  })
  it('groups 4-digit numbers', () => {
    expect(fmtInt(1060)).toBe(`1${S}060`)
    expect(fmtInt(11184)).toBe(`11${S}184`)
    expect(fmtInt(null)).toBe('brak')
  })
  it('decimals with comma', () => {
    expect(fmtDec(0.82, 2)).toBe('0,82')
    expect(fmtDec(1.17, 2)).toBe('1,17')
    expect(fmtScore(0.82)).toBe('0,82')
  })
  it('short money', () => {
    expect(fmtMoneyShort(10.59, 'mln')).toBe(`10,59${S}mln${S}zł`)
    expect(fmtMoneyShort(20.7, 'mld', 1)).toBe(`20,7${S}mld${S}zł`)
    expect(fmtMoneyShort(560, 'tys', 0)).toBe(`560${S}tys.${S}zł`)
  })
  it('percent', () => {
    expect(fmtPct(40.3, { signed: true })).toBe('+40,3%')
    expect(fmtPct(-12.7)).toBe('−12,7%')
    expect(fmtPct(0.36, { fromShare: true })).toBe('36%')
  })
  it('pp', () => {
    expect(fmtPp(5)).toBe(`+5${S}pp`)
    expect(fmtPp(-3)).toBe(`−3${S}pp`)
    expect(fmtPp(0)).toBe('')
  })
  it('days and months', () => {
    expect(fmtDays(277)).toBe(`+277${S}dni`)
    expect(fmtDays(277, { short: true })).toBe(`+277${S}d`)
    expect(fmtDays(1060, { short: true })).toBe(`+1${S}060${S}d`)
    expect(fmtDays(1)).toBe(`+1${S}dzień`)
    expect(fmtMonths(16.3)).toBe(`16,3${S}mies.`)
  })
  it('dates do not shift with timezone', () => {
    expect(fmtDate('2024-06-04')).toBe('04.06.2024')
    expect(fmtDateTime('2026-11-21T12:40:00Z')).toBe('21.11.2026 13:40')
    expect(fmtDateTime('2026-11-21T12:40:00Z', { short: true })).toBe('21.11 13:40')
  })
  it('n and insufficient', () => {
    expect(fmtN(84)).toBe(`n${S}=${S}84`)
    expect(fmtN([1390, 9794])).toBe(`n${S}=${S}1${S}390 i 9${S}794`)
    expect(isInsufficient(7)).toBe(true)
    expect(isInsufficient(84)).toBe(false)
  })
  it('nip', () => {
    expect(fmtNip('8792466869')).toBe(`879${S}246${S}68${S}69`)
  })
  it('plural', () => {
    const f: [string, string, string] = ['umowa', 'umowy', 'umów']
    expect([1, 2, 5, 12, 22, 25].map((n) => plural(n, f))).toEqual([
      'umowa',
      'umowy',
      'umów',
      'umów',
      'umowy',
      'umów',
    ])
  })
})
