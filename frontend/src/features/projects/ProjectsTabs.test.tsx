import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'
import { nationalApiSort, nationalQueryFrom, rangeLabel } from './logic'

const num = (value: number | null, display: string) => ({
  value,
  display,
  unit: 'days',
  prov: { role: 'calc', method: 'x', n: 1, refs: [] },
})
const row = (i: number) => ({
  id: `ocds-148610-${i}`,
  title: `Budowa sieci ${i}`,
  buyer: `Gmina ${i}`,
  gmina: `Gmina ${i}`,
  powiat: null,
  woj: '14',
  status: i % 2 ? 'completed' : 'ongoing',
  status_label: i % 2 ? 'zakończone' : 'w toku',
  value: { amount: '1200000.00', currency: 'PLN', vat_basis: 'gross' },
  signed_on: '2024-01-10',
  planned_end_on: '2024-09-10',
  actual_end_on: null,
  actual_end_label: i % 2 ? '2024-10-01' : 'w toku',
  delay_days: num(21, '+21 dni'),
  changes: num(1, '1'),
  n_contracts: 1,
})

const calls: URLSearchParams[] = []
function mockApi() {
  calls.length = 0
  server.use(
    http.get('*/api/projects/stats', () => HttpResponse.json({}, { status: 404 })),
    http.get('*/api/projects/national', ({ request }) => {
      const u = new URL(request.url).searchParams
      calls.push(u)
      const size = Number(u.get('page_size') ?? 50)
      return HttpResponse.json({
        total: 18689,
        page: Number(u.get('page') ?? 1),
        page_size: size,
        as_of: '2026-11-22',
        items: Array.from({ length: Math.min(size, 3) }, (_, i) => row(i + 1)),
      })
    }),
    http.get('*/api/projects', () =>
      HttpResponse.json({
        total: 0,
        limit: 100,
        offset: 0,
        items: [],
        facets: { all: 22, late: 0, discrepancy: 0, review: null, subsectors: [] },
      }),
    ),
  )
}

describe('Projekty: zakładki', () => {
  it('shows both tabs with counts and keeps the pilot table by default', async () => {
    mockApi()
    await renderRoute('/projekty')
    const tabs = await screen.findByRole('tablist', { name: /Zakres listy/ })
    expect(within(tabs).getByRole('tab', { name: 'Pilotażowe (22)' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(await within(tabs).findByRole('tab', { name: /Wszystkie w Polsce \(18.689\)/ })).toHaveAttribute(
      'aria-selected',
      'false',
    )
    expect(screen.queryByPlaceholderText(/tytuł, zamawiający lub gmina/)).not.toBeInTheDocument()
  })

  it('switches to the national tab: search params in the URL, rows link to the card, range label', async () => {
    mockApi()
    const user = userEvent.setup()
    const { router } = await renderRoute('/projekty')
    await user.click(await screen.findByRole('tab', { name: /Wszystkie w Polsce/ }))
    expect(router.state.location.search).toMatchObject({ tab: 'polska' })
    const link = await screen.findByRole('link', { name: 'Budowa sieci 1' })
    expect(link).toHaveAttribute('href', '/projekty/ocds-148610-1')
    expect(await screen.findByText(/1.50 z 18.689/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Poprzednie' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Następne' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: 'polska', str: 2 }))
    await waitFor(() => expect(calls.some((c) => c.get('page') === '2')).toBe(true))

    await user.click(screen.getByRole('button', { name: /Opóźnienie/ }))
    await waitFor(() => expect(calls.some((c) => c.get('sort') === 'delay')).toBe(true))
    expect(router.state.location.search).toMatchObject({ nsort: 'delay', nkier: 'desc' })
    expect(router.state.location.search).not.toHaveProperty('str')
  })

  it('opens straight on the national tab with filters from the URL', async () => {
    mockApi()
    await renderRoute('/projekty?tab=polska&q=wodoci%C4%85g&woj=14&status=zakonczone&od=2022&nsort=value')
    await screen.findByRole('link', { name: 'Budowa sieci 1' })
    const c = calls.find((x) => x.get('q') === 'wodociąg')
    expect(c?.get('woj')).toBe('14')
    expect(c?.get('status')).toBe('completed')
    expect(c?.get('year_from')).toBe('2022')
    expect(c?.get('sort')).toBe('value')
    expect(screen.getByRole('tab', { name: 'Pilotażowe (22)' })).toHaveAttribute('aria-selected', 'false')
  })
})

describe('national query mapping', () => {
  it('maps sort, status and paging', () => {
    expect(nationalApiSort(undefined, undefined)).toBe('signed')
    expect(nationalApiSort('delay', 'asc')).toBe('delay_asc')
    expect(nationalQueryFrom({ status: 'w-toku', str: 3, skladniki: true })).toMatchObject({
      status: 'ongoing',
      page: 3,
      page_size: 50,
      relevance: 'all',
    })
    expect(rangeLabel(2, 50, 18689)).toBe('51–100 z 18 689')
  })
})
