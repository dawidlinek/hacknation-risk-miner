import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import type { ReviewStatus } from '@/api/contracts/common'
import { useSession } from '@/auth/session'
import { cn } from '@/lib/cn'

export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  auto: '',
  proposed: 'do przeglądu',
  approved: 'zatwierdzone',
  edited: 'poprawione',
  rejected: 'odrzucone',
}

export function ReviewDot({ status, className }: { status: ReviewStatus; className?: string }) {
  if (status === 'proposed')
    return (
      <span
        aria-hidden
        className={cn(
          'inline-flex size-3.5 items-center justify-center rounded-pill border-2 border-attention',
          className,
        )}
      >
        <span className="size-1 rounded-pill bg-attention" />
      </span>
    )
  if (status === 'approved')
    return (
      <span
        aria-hidden
        className={cn(
          'inline-flex size-3.5 items-center justify-center rounded-pill bg-ink text-on-ink',
          className,
        )}
      >
        <Check className="size-2.5" strokeWidth={3.5} />
      </span>
    )
  if (status === 'edited')
    return <span aria-hidden className={cn('inline-block size-3 rounded-pill bg-review-edited', className)} />
  return null
}

/** Public mode: `proposed` reads "niezweryfikowane" and never links to Przegląd. */
export function ReviewStatusBadge({
  status,
  reviewItemId,
  className,
}: {
  status: ReviewStatus
  reviewItemId?: number | null
  className?: string
}) {
  const { isPublic } = useSession()
  if (status === 'auto') return null
  if (status === 'proposed' && isPublic)
    return (
      <span className={cn('inline-flex items-center gap-1.5 text-[13px] text-muted', className)}>
        <span aria-hidden className="size-3 rounded-pill border-2 border-dashed border-border" />
        niezweryfikowane
      </span>
    )
  const label = REVIEW_LABEL[status]
  const inner = (
    <>
      <ReviewDot status={status} />
      <span className={cn(status === 'rejected' && 'text-sev-high line-through')}>{label}</span>
    </>
  )
  const cls = cn(
    'inline-flex items-center gap-1.5 text-[13px] font-medium',
    status === 'proposed'
      ? 'text-attention-text'
      : status === 'edited'
        ? 'text-review-edited'
        : 'text-text-secondary',
    className,
  )
  if (status === 'proposed' && reviewItemId)
    return (
      <Link
        to={'/przeglad' as never}
        search={{ sprawa: reviewItemId } as never}
        className={cn(cls, 'no-underline hover:underline')}
      >
        {inner}
      </Link>
    )
  return <span className={cls}>{inner}</span>
}
