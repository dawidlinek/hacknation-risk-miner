import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { adaptSignals, type RealSignals } from '@/api/adapters/monitoring'
import may from './__fixtures__/signals.2025-05-31.json'
import june from './__fixtures__/signals.2025-06-30.json'
import { daysBetween, deltaLabel, monthEnd, monthLabel, monthSteps, newInStep } from './logic'
import { replayQuery, TimeMachine } from './TimeMachine'

// captured from GET /api/monitoring/signals?as_of=… on the live DB: real responses, not mocks
const J = adaptSignals(june as unknown as RealSignals)
const M = adaptSignals(may as unknown as RealSignals)

describe('replay logic', () => {
  it('month-end steps ending on today', () => {
    expect(monthEnd(2024, 2)).toBe('2024-02-29')
    const s = monthSteps('2025-10', '2025-12-15')
    expect(s).toEqual(['2025-10-31', '2025-11-30', '2025-12-15'])
    expect(daysBetween('2025-05-31', '2025-06-30')).toBe(30)
    expect(monthLabel('2025-06-30')).toBe('cze 2025')
  })
  it('new signals in a step are the ones 1..stepDays past their planned end', () => {
    const fresh = newInStep(J.items, 30)
    expect(fresh.length).toBeGreaterThan(0)
    expect(fresh.every((s) => (s.days_late ?? 0) >= 1 && (s.days_late ?? 0) <= 30)).toBe(true)
  })
  it('delta labels', () => {
    expect(deltaLabel(2929, 2900)).toBe('+29')
    expect(deltaLabel(10, 12)).toBe('−2')
    expect(deltaLabel(5, 5)).toBe('bez zmian')
    expect(deltaLabel(null, 5)).toBe('')
  })
})

describe('TimeMachine', () => {
  it('shows the total for the step, the change since the previous month and the new signals', () => {
    const qc = new QueryClient()
    qc.setQueryData(replayQuery('2025-06-30').queryKey, J)
    qc.setQueryData(replayQuery('2025-05-31').queryKey, M)
    render(
      <QueryClientProvider client={qc}>
        <TimeMachine from="2025-05" today="2025-06-30" />
      </QueryClientProvider>,
    )
    expect(screen.getByTestId('tm-total').textContent?.replace(/\D/g, '')).toBe(String(J.total))
    expect(screen.getByText(/od 31\.05\.2025/)).toBeInTheDocument()
    expect(within(screen.getByTestId('tm-new')).getAllByRole('listitem').length).toBeGreaterThan(0)
    expect(screen.getByRole('slider', { name: /Data, do której/ })).toHaveAttribute(
      'aria-valuetext',
      '30.06.2025',
    )
  })
})

describe('TimeMachine while a step loads', () => {
  it('shows a loading line, never the numbers of another date', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
    render(
      <QueryClientProvider client={qc}>
        <TimeMachine from="2025-05" today="2025-06-30" />
      </QueryClientProvider>,
    )
    expect(screen.getByTestId('tm-total')).toHaveTextContent('…')
    expect(screen.getByText(/Wczytujemy stan na 30\.06\.2025/)).toBeInTheDocument()
  })
})

describe('TimeMachine debounce', () => {
  it('rapid slider moves: label moves at once, "liczę…" until the last step settles, one query for it', async () => {
    const { fireEvent, act } = await import('@testing-library/react')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(replayQuery('2025-06-30').queryKey, J)
    qc.setQueryData(replayQuery('2025-05-31').queryKey, M)
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    vi.useFakeTimers()
    try {
      render(
        <QueryClientProvider client={qc}>
          <TimeMachine from="2025-01" today="2025-06-30" />
        </QueryClientProvider>,
      )
      const slider = screen.getByRole('slider', { name: /Data, do której/ })
      for (const v of [4, 3, 2, 1]) fireEvent.change(slider, { target: { value: String(v) } })
      expect(slider).toHaveAttribute('aria-valuetext', '28.02.2025')
      expect(screen.getAllByText('liczę…').length).toBeGreaterThan(0)
      expect(screen.getByTestId('tm-total')).toHaveTextContent('…')
      expect(fetchSpy).not.toHaveBeenCalled()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(350)
      })
      const urls = fetchSpy.mock.calls.map((c) => String(c[0]))
      expect(urls.filter((u) => u.includes('as_of=2025-02-28')).length).toBe(1)
      expect(urls.some((u) => u.includes('as_of=2025-04-30') || u.includes('as_of=2025-03-31'))).toBe(false)
    } finally {
      vi.useRealTimers()
      fetchSpy.mockRestore()
    }
  })
})
