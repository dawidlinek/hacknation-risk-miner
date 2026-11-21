import type { ReactNode } from 'react'
import type { EvidenceKey, Origin, ReviewStatus } from '@/api/contracts/common'
import { cn } from '@/lib/cn'
import { EvidencePopover } from './EvidencePopover'

export const ORIGIN_LABEL: Record<Origin, string> = {
  SOURCE: 'źródło',
  CALC: 'obliczenie',
  CASE: 'przypadek',
  AI: 'AI',
}

/** Shape + colour per README pattern 3: source grey square, calc teal circle, case blue circle, AI violet square (dashed while proposed). */
export function OriginMarker({
  origin,
  reviewStatus,
  className,
}: {
  origin: Origin
  reviewStatus?: ReviewStatus
  className?: string
}) {
  const dashed = origin === 'AI' && reviewStatus === 'proposed'
  return (
    <span
      aria-hidden
      data-origin={origin}
      className={cn(
        'inline-block size-2 shrink-0',
        origin === 'SOURCE' && 'rounded-[2px] bg-prov-source',
        origin === 'CALC' && 'rounded-pill bg-prov-calc',
        origin === 'CASE' && 'rounded-pill bg-prov-case',
        origin === 'AI' &&
          (dashed
            ? 'rounded-[2px] border border-dashed border-prov-ai bg-transparent'
            : 'rounded-[2px] bg-prov-ai'),
        className,
      )}
    />
  )
}

export function ProvenanceTag({
  origin,
  reviewStatus,
  label,
  text,
  evidence,
  className,
}: {
  origin: Origin
  reviewStatus?: ReviewStatus
  /** overrides the role label ("założenie eksperta") */
  label?: string
  /** the rest of the mono line ("n = 84", "PFU s. 14") */
  text?: ReactNode
  evidence?: EvidenceKey | null
  className?: string
}) {
  const dashed = origin === 'AI' && reviewStatus === 'proposed'
  const body = (
    <span
      className={cn('t-mono inline-flex items-center gap-1.5 text-muted', className)}
      data-dashed={dashed || undefined}
    >
      <OriginMarker origin={origin} reviewStatus={reviewStatus} />
      <span>
        {label ?? ORIGIN_LABEL[origin]}
        {text ? <>, {text}</> : null}
      </span>
    </span>
  )
  if (!evidence) return body
  return <EvidencePopover evidence={evidence}>{body}</EvidencePopover>
}
