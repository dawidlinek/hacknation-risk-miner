import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import demo from './__fixtures__/simulation.demo.json'
import { SimulationBody } from './SimulationScreen'
import type { SimulationResponse } from './scenario'

const sim = demo as unknown as SimulationResponse
const wrap = (ui: ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('SimulationBody', () => {
  it('renders API values: KPI row, four options, drivers and the what-if answer', () => {
    const onChecked = vi.fn()
    wrap(
      <SimulationBody
        sim={sim}
        id="AN-2026-0001"
        metric="time"
        checked={[]}
        onMetric={() => {}}
        onChecked={onChecked}
      />,
    )
    const kpi = screen.getByTestId('kpi-row')
    expect(within(kpi).getByText('W terminie z planu')).toBeInTheDocument()
    expect(within(kpi).getByText(/^3\d%$/)).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(4)
    expect(screen.getByText('Co najbardziej przesuwa termin')).toBeInTheDocument()
    expect(screen.getByText(/Do końca programu zostanie wtedy/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('checkbox')[0])
    expect(onChecked).toHaveBeenCalledWith(['geo'])
  })

  it('competition view has no offers panel and no method note', () => {
    wrap(
      <SimulationBody
        sim={sim}
        id="AN-2026-0001"
        metric="comp"
        checked={[]}
        onMetric={() => {}}
        onChecked={() => {}}
      />,
    )
    expect(screen.queryByText('Więcej ofert, mniej opóźnień')).not.toBeInTheDocument()
    expect(screen.queryByText('Skąd te linie')).not.toBeInTheDocument()
  })

  it('switches the metric through the tab list', () => {
    const onMetric = vi.fn()
    wrap(
      <SimulationBody
        sim={sim}
        id="AN-2026-0001"
        metric="cost"
        checked={['k07']}
        onMetric={onMetric}
        onChecked={() => {}}
      />,
    )
    expect(screen.getByRole('tab', { name: 'Koszt' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: 'Konkurencja' }))
    expect(onMetric).toHaveBeenCalledWith('comp')
  })

  it('n < 10: the whole section becomes the insufficient message', () => {
    const tiny = {
      n: 7,
      runs: 0,
      insufficient: true,
      options: [],
      metrics: {},
      whatifs: [],
      message: 'Za mało podobnych umów, żeby symulować (n = 7). Pokazujemy tylko zakresy z raportu.',
    } as unknown as SimulationResponse
    wrap(
      <SimulationBody
        sim={tiny}
        id="AN-X"
        metric="time"
        checked={[]}
        onMetric={() => {}}
        onChecked={() => {}}
      />,
    )
    expect(screen.getByText(/Za mało podobnych umów, żeby symulować \(n = 7\)/)).toBeInTheDocument()
    expect(screen.queryByTestId('scenario-lines')).toBeNull()
  })
})
