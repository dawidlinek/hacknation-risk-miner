import { screen, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import type { CalcNum, LessonsDigest } from '@/api/contracts/memory'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'

const num = (value: number | null, display: string, n: number): CalcNum => ({
  value: n < 5 ? null : value,
  display: n < 5 ? 'za mało danych' : display,
  unit: 'count',
  prov: { role: 'calc', review_status: 'auto', n, method: 'count(test)' },
})

const digest: LessonsDigest = {
  sector: 'wod-kan',
  scope: 'Zatwierdzone lub obliczone zdarzenia, bez propozycji AI.',
  min_n: 5,
  totals: { events: num(120, '120', 120), cases: num(60, '60', 60), approved_events: 4, excluded_events: 9 },
  categories: [
    {
      code: 'R07',
      name: 'Nieprzewidziane zmiany i roboty dodatkowe',
      events: num(100, '100', 100),
      cases: num(50, '50', 50),
      approved_events: 4,
      delay_median_days: num(90, '90 dni', 30),
      delay_total_days: num(2000, '2 000 dni', 30),
      cost_median: num(null, '', 2),
      cost_total: num(null, '', 2),
      causes: [
        {
          count: 12,
          cases: 9,
          text: 'Kolizja z niezinwentaryzowanym uzbrojeniem',
          quote: 'kolizja z istniejącą infrastrukturą',
          url: 'https://ezamowienia.gov.pl/x',
          field_code: '5.4.4',
          case_id: 'RM-2026-003',
          title: 'Steklin',
          href: '/projekty/RM-2026-003',
          event_id: 1,
          review_status: 'approved',
          origin: 'CALC',
        },
      ],
      mitigations_measured: [],
      mitigations_proposed: [
        {
          code: 'M-GEO',
          label: 'Badania gruntu przed przetargiem',
          rationale: null,
          status: 'proposed',
          assumption: true,
        },
      ],
    },
  ],
}

describe('Wnioski sektorowe', () => {
  it('renders categories with causes, source links and flags assumptions', async () => {
    server.use(http.get('/api/analytics/lessons', () => HttpResponse.json(digest)))
    await renderRoute('/wnioski')
    expect(await screen.findByRole('heading', { name: 'Wnioski sektorowe' })).toBeInTheDocument()
    const cat = screen.getByRole('region', { name: /R07/ })
    expect(within(cat).getByText('Kolizja z niezinwentaryzowanym uzbrojeniem')).toBeInTheDocument()
    expect(within(cat).getByRole('link', { name: 'Steklin' })).toHaveAttribute(
      'href',
      '/projekty/RM-2026-003',
    )
    expect(within(cat).getByText('założenie eksperta, nie zmierzone')).toBeInTheDocument()
    expect(
      within(cat).getByText('Brak zmierzonych środków w przypadkach (za mało danych).'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Pominięto 9 propozycji/)).toBeInTheDocument()
  })
})
