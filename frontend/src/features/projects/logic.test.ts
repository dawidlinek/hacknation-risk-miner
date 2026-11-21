import { describe, expect, it } from 'vitest'
import { adaptProjectsPage, type RealProjectsPage } from '@/api/adapters/projects'
import { costBarPct, delayBarPct, filterRows, SORT_KEYS, slugToFilter, sortValue } from './logic'

const raw: RealProjectsPage = {
  total: 2,
  limit: 100,
  offset: 0,
  facets: {
    all: 2,
    late: 1,
    discrepancy: 1,
    review: null,
    subsectors: [{ key: 'SAN', label: 'Kanalizacja sanitarna', n: 2 }],
  },
  items: [
    {
      rm_id: 'RM-2026-003',
      title: 'Oczyszczalnia w Steklinie',
      beneficiary_name: 'Gmina Czernikowo',
      subsector_main: 'SAN',
      metrics: {
        contract_value: { amount: '2131590.00', currency: 'PLN', vat_basis: 'gross' },
        delay_days: { value: 277, display: '+277 dni', unit: 'days' },
        cost_dev_pct: { value: 40.3, display: '+40,3%', unit: 'pct' },
        changes: { value: 3, display: '3', unit: 'count' },
        properly_performed: true,
        state: { code: 'to_review', label: '5 do przeglądu' },
      },
    },
    {
      rm_id: 'RM-2026-007',
      title: 'Sieć w Kamionce',
      beneficiary_name: 'Gmina Kamionka',
      subsector_main: 'SAN',
      metrics: {
        contract_value: { amount: '1478460.00', currency: 'PLN', vat_basis: 'gross' },
        delay_days: null,
        cost_dev_pct: { value: -0.6, display: '-0,6%', unit: 'pct' },
        changes: null,
        properly_performed: false,
        state: { code: 'discrepancy', label: 'rozbieżność wartości' },
      },
    },
  ],
}

describe('projects table', () => {
  const page = adaptProjectsPage(raw, null)
  it('adapts rows with subsector labels and tones', () => {
    expect(page.items[0].subsector_label).toBe('Kanalizacja sanitarna')
    expect(page.items.map((r) => r.state.tone)).toEqual(['review', 'discrepancy'])
    expect(page.facets.review).toBe(0)
  })
  it('filters by pill, search and subsector', () => {
    expect(filterRows(page.items, { filter: 'late' })).toHaveLength(1)
    expect(filterRows(page.items, { filter: 'discrepancy' })[0].rm_id).toBe('RM-2026-007')
    expect(filterRows(page.items, { q: 'czernikowo' })).toHaveLength(1)
    expect(filterRows(page.items, { subsector: 'Uzdatnianie wody' })).toHaveLength(0)
  })
  it('sort values put missing numbers as null', () => {
    expect(sortValue(page.items[1], 'delay')).toBeNull()
    expect(sortValue(page.items[0], 'value')).toBe(2131590)
  })
  it('url slugs round trip', () => {
    expect(slugToFilter('po-terminie')).toBe('late')
    expect(slugToFilter('nonsens')).toBe('all')
  })
  it('bar widths are capped', () => {
    expect(delayBarPct(800)).toBe(100)
    expect(delayBarPct(200)).toBe(50)
    expect(costBarPct(-80)).toBe(50)
    expect(costBarPct(25)).toBe(25)
  })
})

describe('table columns', () => {
  it('Zmiany, Wykonanie and Stan are no longer sortable columns (old links fall back to delay)', () => {
    expect(SORT_KEYS).toEqual(['title', 'subsector', 'value', 'delay', 'cost'])
  })
})
