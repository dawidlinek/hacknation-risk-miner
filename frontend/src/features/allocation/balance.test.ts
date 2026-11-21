import { describe, expect, it } from 'vitest'
import type { AllocationOut } from '@/api/contracts/allocation'
import demo from './__fixtures__/allocation.demo.json'
import { balance, balanceNote, fmtTpln, initialChoices } from './balance'

const P = {
  shared: 0.1,
  contractor: 0.6,
  shared_if_contractor_controls: 0,
  contractor_if_contractor_controls: 0.1,
}

describe('balance (mockup A5 default state)', () => {
  // e = 210, 90, 120, 160, 250, 230 tys. zł; ctl buyer/buyer/neither/neither/buyer/neither
  const rows = [
    { code: 'R02', expected_cost_tpln: 210, controlled_by: 'buyer', recommended: 0 },
    { code: 'R03', expected_cost_tpln: 90, controlled_by: 'buyer', recommended: 0 },
    { code: 'R04', expected_cost_tpln: 120, controlled_by: 'neither', recommended: 1 },
    { code: 'R06', expected_cost_tpln: 160, controlled_by: 'neither', recommended: 1 },
    { code: 'R08', expected_cost_tpln: 250, controlled_by: 'buyer', recommended: 1 },
    { code: 'R13', expected_cost_tpln: 230, controlled_by: 'neither', recommended: 1 },
  ] as const
  const choices = { R02: 0, R03: 0, R04: 1, R06: 1, R08: 2, R13: 1 } as const

  it('555 / 505 / 201, one risk off the recommendation', () => {
    const b = balance([...rows], { ...choices }, P)
    expect(Math.round(b.buyer)).toBe(555)
    expect(Math.round(b.contractor)).toBe(505)
    expect(Math.round(b.premium)).toBe(201)
    expect(b.off).toBe(1)
    expect(b.segments).toEqual({ buyer: 300, shared: 510, contractor: 250 })
  })
  it('displays rounded to 10 tys. zł like the mockup', () => {
    const b = balance([...rows], { ...choices }, P)
    expect(fmtTpln(b.buyer)).toBe('560 tys. zł')
    expect(fmtTpln(b.contractor)).toBe('510 tys. zł')
    expect(fmtTpln(b.premium)).toBe('200 tys. zł')
  })
  it('contractor-controlled risks carry the lower premium', () => {
    const b = balance(
      [{ code: 'X', expected_cost_tpln: 100, controlled_by: 'contractor', recommended: 2 }],
      { X: 2 },
      P,
    )
    expect(b.premium).toBeCloseTo(10)
    const s = balance(
      [{ code: 'X', expected_cost_tpln: 100, controlled_by: 'contractor', recommended: 2 }],
      { X: 1 },
      P,
    )
    expect(s.premium).toBe(0)
  })
  it('notes with Polish plurals', () => {
    expect(balanceNote(0)).toMatch(/^Podział zgodny z zaleceniami/)
    expect(balanceNote(1)).toBe('1 ryzyko podzielone inaczej niż zalecamy. Sprawdź uwagi pod nimi.')
    expect(balanceNote(3)).toMatch(/^3 ryzyka podzielone/)
    expect(balanceNote(5)).toMatch(/^5 ryzyk podzielonych/)
  })
})

describe('real allocation response (engine, demo analysis)', () => {
  const al = demo as unknown as AllocationOut
  it('defaults to the recommended positions and stays off = 0', () => {
    const b = balance(al.risks, initialChoices(al.risks), al.premium)
    expect(b.off).toBe(0)
    expect(b.buyer + b.contractor).toBeCloseTo(al.risks.reduce((s, r) => s + r.expected_cost_tpln, 0))
    expect(al.risks.every((r) => r.how.length === 3)).toBe(true)
  })
})
