import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { fmtN, isInsufficient, MIN_N } from '@/lib/format'

/** Soft card: label, value, mono provenance. With `n < 10` the value becomes "za mało danych" (n stays visible). */
export function StatCard({
  label,
  value,
  provenance,
  n,
  minN = MIN_N,
  note,
  attention,
  className,
}: {
  label: ReactNode
  value: ReactNode
  provenance?: ReactNode
  n?: number | null
  minN?: number
  note?: ReactNode
  attention?: boolean
  className?: string
}) {
  const insufficient = n !== undefined && isInsufficient(n, minN)
  return (
    <div className={cn('flex flex-col gap-1.5 rounded-card bg-soft px-5 py-4.5', className)}>
      <span className="flex items-center justify-between gap-2 text-[14px] text-muted">
        {label}
        {attention ? <AttentionDot /> : null}
      </span>
      {insufficient ? (
        <span className="t-h3 text-text-secondary">za mało danych</span>
      ) : (
        <span className={cn('t-stat', attention && 'text-attention-text')}>{value}</span>
      )}
      {note ? <span className="text-[13px] text-text-body-muted">{note}</span> : null}
      {provenance || n !== undefined ? (
        <span className="t-mono text-muted">
          {provenance}
          {provenance && n !== undefined && n !== null ? ', ' : ''}
          {n !== undefined && n !== null ? fmtN(n) : ''}
        </span>
      ) : null}
    </div>
  )
}

export function AttentionDot({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center">
      <span aria-hidden className="size-2.5 rounded-pill bg-attention" />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}

/** Link card (Pulpit tiles): label, big value, sub line, attention dot. */
export function StatTile({
  label,
  value,
  sub,
  href,
  attention,
}: {
  label: ReactNode
  value: ReactNode
  sub?: ReactNode
  href: string
  attention?: boolean
}) {
  return (
    <Link
      to={href as never}
      className="flex flex-col gap-1.5 rounded-card bg-soft px-5 py-4.5 text-text no-underline hover:bg-soft-2"
    >
      <span className="flex items-center justify-between text-[14px] text-muted">
        {label}
        {attention ? <AttentionDot label="wymaga uwagi" /> : null}
      </span>
      <span className="text-[34px] leading-none font-semibold tracking-[-0.04em]">{value}</span>
      {sub ? <span className="text-[13px] text-text-body-muted">{sub}</span> : null}
    </Link>
  )
}

export function KpiGrid({ children, min = 220, className }: { children: ReactNode; min?: number; className?: string }) {
  return (
    <div className={cn('grid gap-3', className)} style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))` }}>
      {children}
    </div>
  )
}
