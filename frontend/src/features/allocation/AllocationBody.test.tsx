import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import { sessionQuery } from '@/auth/session'
import { featuresQuery, mergeFeatures } from '@/config/features'
import demo from './__fixtures__/allocation.demo.json'
import { AllocationBody } from './AllocationScreen'
import { type AllocationResponse, FAILED_TOAST, READ_ONLY_TOAST, useAllocationChoices } from './api'

// captured from the engine for the demo analysis: a real response, not a mock
const data = demo as unknown as AllocationResponse

function client() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(featuresQuery.queryKey, mergeFeatures({ allocation: true, pack_export: true }))
  qc.setQueryData(sessionQuery.queryKey, { role: 'public', name: null, initials: null })
  return qc
}
const wrapper =
  (qc: QueryClient) =>
  ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useAllocationChoices', () => {
  it('debounces the PUT and sends the whole map', async () => {
    const save = vi.fn().mockResolvedValue(data)
    const notify = { error: vi.fn(), info: vi.fn() }
    const { result } = renderHook(() => useAllocationChoices('AN-1', data, { save, notify }), {
      wrapper: wrapper(client()),
    })
    act(() => result.current.choose('R02', 2))
    act(() => result.current.choose('R03', 1))
    expect(save).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0][1]).toMatchObject({ R02: 2, R03: 1, R04: 1 })
    expect(notify.error).not.toHaveBeenCalled()
  })

  it('reverts the choice and toasts when the PUT fails', async () => {
    const save = vi.fn().mockRejectedValue(new ApiError(500, 'x'))
    const notify = { error: vi.fn(), info: vi.fn() }
    const { result } = renderHook(() => useAllocationChoices('AN-1', data, { save, notify }), {
      wrapper: wrapper(client()),
    })
    act(() => result.current.choose('R02', 2))
    expect(result.current.choices.R02).toBe(2)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(notify.error).toHaveBeenCalledWith(FAILED_TOAST)
    expect(result.current.choices.R02).toBe(0)
  })

  it('read-only (403): keeps the local what-if, toasts once, stops saving', async () => {
    const save = vi
      .fn()
      .mockRejectedValue(new ApiError(403, 'Tylko autor analizy może ją zmieniać.', 'forbidden'))
    const notify = { error: vi.fn(), info: vi.fn() }
    const { result } = renderHook(() => useAllocationChoices('AN-1', data, { save, notify }), {
      wrapper: wrapper(client()),
    })
    act(() => result.current.choose('R02', 2))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    act(() => result.current.choose('R03', 2))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(notify.info).toHaveBeenCalledTimes(1)
    expect(notify.info).toHaveBeenCalledWith(READ_ONLY_TOAST)
    expect(save).toHaveBeenCalledTimes(1)
    expect(result.current.choices).toMatchObject({ R02: 2, R03: 2 })
  })
})

describe('AllocationBody', () => {
  it('renders the API risks with the recommended position checked and a zero-off note', () => {
    render(<AllocationBody id="AN-1" data={data} />, { wrapper: wrapper(client()) })
    for (const r of data.risks) {
      const row = screen.getByTestId(`risk-${r.code}`)
      const checked = within(row).getByRole('radio', { checked: true })
      expect(checked).toHaveAccessibleName(['Zamawiający', 'Wspólnie', 'Wykonawca'][r.recommended])
      expect(within(row).getByText('zalecane')).toBeInTheDocument()
    }
    expect(screen.getByTestId('balance-note')).toHaveTextContent('Podział zgodny z zaleceniami')
    expect(screen.getByTestId('export-buttons')).toHaveTextContent('Pobierz DOCX')
  })

  it('choosing another position shows the warning and updates the note at once', () => {
    render(<AllocationBody id="AN-1" data={data} />, { wrapper: wrapper(client()) })
    const row = screen.getByTestId('risk-R02')
    fireEvent.click(within(row).getByRole('radio', { name: 'Wykonawca' }))
    expect(within(row).getByRole('note')).toBeInTheDocument()
    expect(screen.getByTestId('balance-note')).toHaveTextContent('1 ryzyko podzielone inaczej niż zalecamy')
  })
})
