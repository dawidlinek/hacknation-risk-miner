import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { featuresQuery, mergeFeatures } from '@/config/features'
import demo from './__fixtures__/report.demo.json'
import {
  flagHref,
  funnelWidth,
  groupFlags,
  keyDisplay,
  type Report,
  type ReportQuestion,
  rangeGeometry,
  similaritySegments,
  sortFlags,
} from './logic'
import { ReportBody } from './ReportScreen'

// captured from the engine (demo analysis + 2 public BZP documents): a real response, not a mock
const r = demo as unknown as Report

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(
    featuresQuery.queryKey,
    mergeFeatures({ red_pen: true, monte_carlo: true, unit_cost: true, backtest: true }),
  )
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('report logic', () => {
  const qs = r.questions as ReportQuestion[]
  it('range geometry: band, median, "Ty" and programme tick inside 0..100 %', () => {
    const t = qs.find((q) => q.key === 'time') as ReportQuestion
    const g = rangeGeometry(t)
    expect(g.band?.left).toBeGreaterThanOrEqual(0)
    expect((g.band?.left ?? 0) + (g.band?.width ?? 0)).toBeLessThanOrEqual(100.0001)
    expect(g.you).not.toBeNull()
    expect(g.median).toBeGreaterThan(g.you as number)
    expect(keyDisplay(t)).toMatch(/^\d+% szans$/)
    const p = qs.find((q) => q.key === 'programme') as ReportQuestion
    expect(rangeGeometry(p).programme).not.toBeNull()
  })
  it('similarity segments sum to the score; "inne" is kept (grey)', () => {
    for (const c of r.similar_cases) {
      const s = similaritySegments(c).reduce((a, x) => a + x.pct, 0) / 100
      expect(Math.abs(s - c.score)).toBeLessThan(0.01)
    }
    expect(r.similar_cases.some((c) => c.contributions.some((x) => (x.feature as string) === 'inne'))).toBe(
      true,
    )
  })
  it('flags: calc first, document flags link to the red pen page', () => {
    const sorted = sortFlags(r.flags)
    expect(sorted[0].origin).toBe('CALC')
    const doc = r.flags.find((f) => f.doc)
    expect(doc && flagHref('AN-1', doc)).toMatch(/^\/analizy\/AN-1\/dokumenty\/\d+\?s=\d+/)
  })
  it('funnel widths follow the mockup formula', () => {
    expect(funnelWidth(11222, 11222)).toBe(100)
    expect(funnelWidth(82, 11222)).toBeCloseTo(Math.sqrt(82 / 11222) * 100)
    expect(funnelWidth(1, 11222)).toBe(6)
  })
})

describe('ReportBody', () => {
  it('renders the summary, three question cards, flags, cases and clauses from the API', () => {
    wrap(<ReportBody id="AN-1" r={r} />)
    expect(screen.getByText(r.summary.text)).toBeInTheDocument()
    const cards = screen.getByTestId('question-cards')
    expect(within(cards).getByText('Czy zdążysz w 14 miesięcy?')).toBeInTheDocument()
    expect(within(screen.getByTestId('q-time')).getByTestId('range-you')).toBeInTheDocument()
    expect(within(screen.getByTestId('q-programme')).getByTestId('range-programme')).toBeInTheDocument()
    expect(within(screen.getByTestId('flags')).getByText('Termin krótszy niż typowy')).toBeInTheDocument()
    expect(screen.getAllByTestId('case-row').length).toBe(r.similar_cases.length)
    expect(screen.getAllByRole('button', { name: 'Dodaj do pakietu' }).length).toBe(r.clauses.length)
    const funnel = screen.getByTestId('funnel')
    expect(within(funnel).getAllByRole('listitem')).toHaveLength(r.reference_class?.funnel.length ?? 0)
    expect(screen.getByTestId('backtest')).toHaveTextContent('Sprawdziliśmy prognozy')
  })
  it('draft (not run yet) offers "Uruchom analizę" instead of numbers', () => {
    const draft = {
      ...r,
      status: 'draft',
      summary: null,
      questions: [],
      flags: [],
      similar_cases: [],
      clauses: [],
    } as unknown as Report
    wrap(<ReportBody id="AN-1" r={draft} />)
    expect(screen.getByRole('button', { name: 'Uruchom analizę' })).toBeInTheDocument()
    expect(screen.queryByTestId('question-cards')).toBeNull()
  })
  it('insufficient card shows "za mało danych" and no band', () => {
    const q = {
      ...(r.questions[0] as ReportQuestion),
      insufficient: true,
      n: 7,
      band: null,
      answer: 'Nie wiemy' as const,
    }
    wrap(<ReportBody id="AN-1" r={{ ...r, questions: [q] } as Report} />)
    const card = screen.getByTestId(`q-${q.key}`)
    expect(within(card).getAllByText(/za mało danych/).length).toBeGreaterThan(0)
    expect(within(card).queryByTestId('range-band')).toBeNull()
  })
})

describe('stale similar cases', () => {
  it('shows the re-run banner naming the case and the reason', () => {
    const qc = new QueryClient()
    qc.setQueryData(featuresQuery.queryKey, mergeFeatures({}))
    render(
      <QueryClientProvider client={qc}>
        <ReportBody
          id="AN-1"
          r={{
            ...r,
            stale_cases: [{ case: 'RM-2026-013', label: 'Bestwina', reason: 'nowy protokół konieczności' }],
          }}
        />
      </QueryClientProvider>,
    )
    expect(
      screen.getByText(
        'Nowe dane w przypadku podobnym: Bestwina (nowy protokół konieczności). Uruchom analizę ponownie, żeby je uwzględnić.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Uruchom analizę' })).toBeInTheDocument()
  })
})

describe('second sector', () => {
  it('a road analysis shows the sector badge; wod-kan shows none', () => {
    const qc = new QueryClient()
    qc.setQueryData(featuresQuery.queryKey, mergeFeatures({}))
    const road = {
      ...r,
      reference_class: {
        ...(r.reference_class as object),
        sector: 'drogi',
        sector_label: 'Drogi lokalne i regionalne (rozszerzenie pilotażu)',
        sector_status: 'proposed',
      },
    } as Report
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <ReportBody id="AN-1" r={road} />
      </QueryClientProvider>,
    )
    expect(screen.getByTestId('sector-badge')).toHaveTextContent(
      'sektor: Drogi lokalne i regionalne (rozszerzenie pilotażu), pakiet do zatwierdzenia',
    )
    unmount()
    render(
      <QueryClientProvider client={qc}>
        <ReportBody id="AN-1" r={r} />
      </QueryClientProvider>,
    )
    expect(screen.queryByTestId('sector-badge')).toBeNull()
  })
})

describe('groupFlags', () => {
  const base = {
    origin: 'CALC' as const,
    review_status: 'auto' as const,
    title: 'Przekroczenie cieku, drogi lub kolei',
    text: 'Trasa przecina przeszkodę.',
    risk_codes: ['R03'],
  }
  it('the same warning on two pages shows once with both pages', () => {
    const out = groupFlags([
      { ...base, id: 'a', meta: 'R03.3, reguła, PFU s. 2' },
      { ...base, id: 'b', meta: 'R03.3, reguła, PFU s. 6' },
      { ...base, id: 'c', title: 'Inna uwaga', meta: 'R06, obliczenie' },
    ])
    expect(out.map((f) => f.id)).toEqual(['a', 'c'])
    expect(out[0].meta).toBe('R03.3, reguła, PFU s. 2, PFU s. 6')
  })
  it('different review states stay apart', () => {
    const out = groupFlags([
      { ...base, id: 'a', meta: 'R03.3, AI, PFU s. 2', origin: 'AI', review_status: 'proposed' },
      { ...base, id: 'b', meta: 'R03.3, AI, PFU s. 6', origin: 'AI', review_status: 'approved' },
    ])
    expect(out).toHaveLength(2)
  })
})
