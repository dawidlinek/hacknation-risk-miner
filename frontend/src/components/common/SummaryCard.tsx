import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** Black card with one plain-language sentence (template-filled, never LLM) and a mono provenance line. */
export function SummaryCard({
  eyebrow,
  sentence,
  provenance,
  children,
  className,
  size = 'md',
}: {
  eyebrow?: ReactNode
  sentence: ReactNode
  provenance?: ReactNode
  children?: ReactNode
  className?: string
  size?: 'md' | 'lg'
}) {
  return (
    <section className={cn('flex flex-col gap-2.5 rounded-card bg-ink px-6.5 py-6 text-on-ink', className)}>
      {eyebrow ? <span className="t-eyebrow text-on-ink-muted">{eyebrow}</span> : null}
      <p className={cn('m-0 max-w-[900px] font-medium', size === 'lg' ? 'text-[24px] leading-[1.4] tracking-[-0.015em]' : 't-summary')}>
        {sentence}
      </p>
      {provenance ? <span className="t-mono text-on-ink-muted">{provenance}</span> : null}
      {children}
    </section>
  )
}

export function SummaryCardSkeleton({ note }: { note?: string }) {
  return (
    <section className="flex flex-col gap-3 rounded-card bg-ink px-6.5 py-6 text-on-ink" aria-busy="true">
      <span className="h-5 w-3/4 animate-pulse rounded-chip bg-on-ink/15" />
      <span className="h-5 w-1/2 animate-pulse rounded-chip bg-on-ink/15" />
      {note ? <span className="t-mono text-on-ink-muted">{note}</span> : null}
    </section>
  )
}
