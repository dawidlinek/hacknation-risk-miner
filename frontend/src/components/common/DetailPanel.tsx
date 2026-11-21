import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface DetailRow {
  k: string
  v: ReactNode
  /** coloured mono tag after the value (origin / review status) */
  tag?: ReactNode
}

/** Aside card: kind eyebrow, title, key/value rows, optional footer (CTA). `aria-live` so selection changes are announced. */
export function DetailPanel({
  kind,
  title,
  rows,
  children,
  footer,
  className,
}: {
  kind: ReactNode
  title: ReactNode
  rows: DetailRow[]
  children?: ReactNode
  footer?: ReactNode
  className?: string
}) {
  return (
    <section aria-live="polite" className={cn('flex flex-col gap-3 rounded-panel bg-soft p-5', className)}>
      <span className="t-eyebrow text-muted">{kind}</span>
      <h2 className="t-h3 m-0">{title}</h2>
      <dl className="m-0 flex flex-col gap-2.5">
        {rows.map((r) => (
          <div key={r.k} className="flex flex-col gap-0.5 rounded-item bg-surface px-4 py-2.5">
            <dt className="t-caption text-muted">{r.k}</dt>
            <dd className="m-0 text-[14px]">
              {r.v}
              {r.tag ? <span className="ml-2">{r.tag}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
      {children}
      {footer}
    </section>
  )
}
