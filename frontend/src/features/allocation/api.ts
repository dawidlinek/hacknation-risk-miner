import { queryOptions, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ApiError, contractFetch } from '@/api/client'
import type { AllocationOut, Position } from '@/api/contracts/allocation'
import { initialChoices } from './balance'

/** Server extras on top of the frontend contract. */
export type AllocationResponse = AllocationOut & {
  balance?: { note?: string; off_recommendation?: number }
  limitations?: string[]
  version?: number
}

export const allocationQuery = (id: string) =>
  queryOptions({
    queryKey: ['analysis', id, 'allocation'],
    queryFn: () => contractFetch<AllocationResponse>(`/api/analyses/${encodeURIComponent(id)}/allocation`),
    staleTime: 60_000,
  })

export const putAllocation = (id: string, choices: Record<string, Position>) =>
  contractFetch<AllocationResponse>(`/api/analyses/${encodeURIComponent(id)}/allocation`, {
    method: 'PUT',
    json: { choices },
  })

export const READ_ONLY_TOAST =
  'Ta analiza jest tylko do odczytu: możesz sprawdzać warianty, ale wybory nie zostaną zapisane.'
export const FAILED_TOAST = 'Nie zapisaliśmy wyboru. Spróbuj ponownie.'

export type Notify = { error: (msg: string) => void; info: (msg: string) => void }
const sonner: Notify = { error: (m) => toast.error(m), info: (m) => toast(m) }

/**
 * Local choices with optimistic updates; the whole map is PUT 600 ms after the last change.
 * Failure reverts to the last saved state with a toast; 403 (someone else's analysis) keeps the local choices
 * as an unsaved what-if and says so once.
 */
export function useAllocationChoices(
  id: string,
  data: AllocationResponse,
  opts: { delay?: number; notify?: Notify; save?: typeof putAllocation } = {},
) {
  const { delay = 600, notify = sonner, save = putAllocation } = opts
  const qc = useQueryClient()
  const [choices, setChoices] = useState<Record<string, Position>>(() => initialChoices(data.risks))
  const saved = useRef(choices)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const readOnly = useRef(false)
  const [saving, setSaving] = useState(false)

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const flush = useCallback(
    async (next: Record<string, Position>) => {
      if (readOnly.current) return
      setSaving(true)
      try {
        const out = await save(id, next)
        saved.current = next
        qc.setQueryData(allocationQuery(id).queryKey, out)
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) {
          readOnly.current = true
          notify.info(READ_ONLY_TOAST)
        } else {
          setChoices(saved.current)
          notify.error(FAILED_TOAST)
        }
      } finally {
        setSaving(false)
      }
    },
    [id, qc, notify, save],
  )

  const choose = useCallback(
    (code: string, pos: Position) => {
      setChoices((prev) => {
        const next = { ...prev, [code]: pos }
        if (timer.current) clearTimeout(timer.current)
        timer.current = setTimeout(() => void flush(next), delay)
        return next
      })
    },
    [flush, delay],
  )

  return { choices, choose, saving, readOnly: readOnly.current }
}
