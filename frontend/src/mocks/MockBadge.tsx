import { useEffect, useState } from 'react'
import { mockGroupsSeen, subscribeMock } from '@/api/mockSignal'

/** Small pill in the header while any shown data came from the mock layer. Never hidden in production. */
export function MockBadge() {
  const [groups, setGroups] = useState<string[]>(() => [...mockGroupsSeen()])
  useEffect(() => subscribeMock((g) => setGroups([...g])), [])
  if (groups.length === 0) return null
  return (
    <span
      className="inline-flex min-h-7 items-center gap-1.5 rounded-pill border border-dashed border-attention px-2.5 text-[12px] font-medium text-attention-text"
      title={`Dane przykładowe: ${groups.join(', ')}`}
      data-testid="mock-badge"
    >
      <span aria-hidden className="size-1.5 rounded-pill bg-attention" />
      dane przykładowe
    </span>
  )
}
