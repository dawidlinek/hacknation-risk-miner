import { describe, expect, it } from 'vitest'
import { adaptRegions, type RealRegions } from '@/api/adapters/monitoring'
import type { RegionStat, Signal } from '@/api/contracts/monitoring'
import {
  colorAt,
  effectiveMetric,
  levelOf,
  METRICS,
  parseMetric,
  pillStacks,
  scaleRegions,
  signalsInView,
  tintFor,
} from './logic'

const stat = (teryt: string, late: number, completed = 100): RegionStat => ({
  teryt,
  name: teryt,
  completed,
  late_pct: late,
  median_delay_days: 60,
  over_pct: 10,
  overpaid: { amount: '1', currency: 'PLN', vat_basis: 'gross' },
  total_value: { amount: '10', currency: 'PLN', vat_basis: 'gross' },
  changed_pct: 40,
  improper_pct: 0.5,
  signals: 7,
  insufficient: completed < 10,
})

describe('colour scale', () => {
  it('ink ramp endpoints', () => {
    expect(colorAt(0, 'done')).toBe('rgb(232,238,255)')
    expect(colorAt(1, 'done')).toBe('rgb(28,52,150)')
  })
  it('signals use the orange heat ramp', () => {
    expect(colorAt(0, 'open')).toBe('rgb(255,246,209)')
    expect(colorAt(1, 'open')).toBe('rgb(153,27,27)')
  })
  it('scaleRegions: rank, label colour above t = 0.55, neutral fill for too little data', () => {
    const { regions, lo, hi } = scaleRegions(
      [stat('a', 20), stat('b', 40), stat('c', 30), stat('d', 99, 5)],
      'late',
      'done',
    )
    expect([lo, hi]).toEqual([20, 40])
    const byId = Object.fromEntries(regions.map((r) => [r.stat.teryt, r]))
    expect(byId.b.rank).toBe(1)
    expect(byId.a.rank).toBe(3)
    expect(byId.b.lightText).toBe(true)
    expect(byId.c.lightText).toBe(false)
    expect(byId.d.value).toBeNull()
    expect(byId.d.rank).toBe(0)
    expect(byId.d.fill).toBe('#F6F6F6')
  })
})

describe('metrics and levels', () => {
  it('formats with one decimal and a comma', () => {
    expect(METRICS.late.fmt(32)).toBe('32,0%')
    expect(METRICS.delay.fmt(62)).toBe('+62 d')
  })
  it('open mode forces the signals metric', () => {
    expect(effectiveMetric('open', 'late')).toBe('sig')
    expect(effectiveMetric('done', 'over')).toBe('over')
    expect(parseMetric('nonsens')).toBe('late')
  })
  it('levelOf follows the URL params', () => {
    expect(levelOf({})).toBe(0)
    expect(levelOf({ woj: '12' })).toBe(1)
    expect(levelOf({ woj: '12', pow: '1209' })).toBe(2)
    expect(levelOf({ woj: '12', pow: '1209', umowa: '5' })).toBe(3)
  })
  it('powiat tint by count', () => {
    expect(tintFor(0)).toBeNull()
    expect(tintFor(1)).toBe('#FFF6D1')
    expect(tintFor(2)).toBe('#FFE27A')
    expect(tintFor(9)).toBe('#FFD23F')
  })
})

const sig = (id: string, woj: string, pow: string, gmi: string | null): Signal => ({
  id,
  bzp: 'x',
  ocid: 'o',
  buyer: 'b',
  object: 'o',
  value: { amount: 1, currency: 'PLN', vat_basis: 'gross' },
  days_late: 100,
  planned_end: '2022-01-01',
  signed_on: null,
  changes: 0,
  parts: 1,
  teryt: { woj, pow, gmi },
  lon: 1,
  lat: 1,
})

describe('signals in view and pill stacking', () => {
  const all = [
    sig('1', '12', '1209', '1209052'),
    sig('2', '12', '1209', '1209052'),
    sig('3', '12', '1206', '1206113'),
    sig('4', '14', '1401', null),
  ]
  it('filters by level', () => {
    expect(signalsInView(all, {})).toHaveLength(4)
    expect(signalsInView(all, { woj: '12' })).toHaveLength(3)
    expect(signalsInView(all, { woj: '12', pow: '1209' })).toHaveLength(2)
  })
  it('stacks pills per gmina', () => {
    const s = pillStacks(all)
    expect([s.get('1'), s.get('2'), s.get('3'), s.get('4')]).toEqual([0, 1, 0, 0])
  })
})

describe('adaptRegions', () => {
  it('maps the real metrics and marks thin regions', () => {
    const raw: RealRegions = {
      level: 'woj',
      parent: null,
      total: { label: '11 210 umów', n: 11210 },
      regions: [
        {
          terc: '12',
          name: 'małopolskie',
          metrics: {
            n_completed: 8,
            late_pct: 29.6,
            median_delay_days_late: 62,
            overpaid_pln: '5.00',
            value_pln: '10.00',
            over_pct: 23.1,
            changes_pct: 44.7,
            improper_pct: 0.5,
            signals: 265,
          },
        },
      ],
    }
    const out = adaptRegions(raw)
    expect(out.items[0].insufficient).toBe(true)
    expect(out.items[0].median_delay_days).toBe(62)
    expect(out.total_label).toBe('11 210 umów')
  })
})
