import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Origin } from '@/api/contracts/common'
import { cn } from '@/lib/cn'

export interface QuoteChip {
  text: string
  tone: 'ok' | 'warn' | 'neutral'
}

/**
 * Evidence as a quote: title, source reference (link), the quote with the matched part marked, and chips.
 * `<mark>` is orange-soft for source quotes and violet-soft for AI readings.
 */
export function QuoteCard({
  title,
  reference,
  referenceUrl,
  pre,
  hit,
  post,
  origin = 'SOURCE',
  chips,
  onOpenSource,
  className,
  children,
}: {
  title: ReactNode
  reference?: string
  referenceUrl?: string | null
  pre?: string
  hit: string
  post?: string
  origin?: Origin
  chips?: QuoteChip[]
  onOpenSource?: () => void
  className?: string
  children?: ReactNode
}) {
  return (
    <figure className={cn('m-0 flex flex-col gap-3 rounded-card bg-soft p-5', className)}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="t-item">{title}</span>
        {reference ? (
          referenceUrl ? (
            <a
              href={referenceUrl}
              target="_blank"
              rel="noreferrer"
              onClick={onOpenSource}
              onAuxClick={onOpenSource}
              className="t-mono inline-flex items-center gap-1 text-text-secondary hover:underline"
            >
              {reference}
              <ExternalLink aria-hidden className="size-3" />
              <span className="sr-only">(otwiera się w nowej karcie)</span>
            </a>
          ) : (
            <span className="t-mono text-muted">{reference}</span>
          )
        ) : null}
      </figcaption>
      <blockquote className="m-0 rounded-item bg-surface px-4 py-3 text-[15px] leading-[1.6]">
        {pre}
        <mark className={origin === 'AI' ? 'bg-prov-ai-soft' : undefined}>{hit}</mark>
        {post}
      </blockquote>
      {chips && chips.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <span
              key={c.text}
              className={cn(
                'inline-flex min-h-7.5 items-center rounded-pill px-3 text-[13px]',
                c.tone === 'ok' && 'bg-success-soft text-success-text',
                c.tone === 'warn' && 'bg-attention-soft text-attention-text',
                c.tone === 'neutral' && 'bg-soft-2 text-text',
              )}
            >
              {c.text}
            </span>
          ))}
        </div>
      ) : null}
      {children}
    </figure>
  )
}
