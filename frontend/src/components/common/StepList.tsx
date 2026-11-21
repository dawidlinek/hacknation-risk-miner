import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type StepState = 'done' | 'now' | 'missing' | 'calc' | 'ai_proposed' | 'ai_approved'

/** 22 px dot: done = black filled check, now = orange ring, missing = dashed grey ring, calc = teal circle. */
export function StepDot({ state, label }: { state: StepState; label?: ReactNode }) {
  const base = 'inline-flex size-5.5 shrink-0 items-center justify-center rounded-pill box-border'
  let dot: ReactNode
  if (state === 'done' || state === 'ai_approved')
    dot = (
      <span className={cn(base, 'bg-ink text-on-ink')}>
        <Check className="size-3" strokeWidth={3} />
      </span>
    )
  else if (state === 'now' || state === 'ai_proposed')
    dot = (
      <span className={cn(base, 'border-2 border-attention')}>
        <span className="size-2 rounded-pill bg-attention" />
      </span>
    )
  else if (state === 'calc')
    dot = (
      <span className={cn(base, 'bg-prov-calc-soft')}>
        <span className="size-2 rounded-pill bg-prov-calc" />
      </span>
    )
  else if (typeof label === 'string' || typeof label === 'number')
    dot = (
      <span
        className={cn(
          base,
          'border-2 border-dashed border-attention text-[11px] font-semibold text-attention-text',
        )}
      >
        {label}
      </span>
    )
  else dot = <span className={cn(base, 'border-2 border-dashed border-border')} />
  if (label !== undefined && state !== 'missing')
    return (
      <span
        className={cn(
          base,
          state === 'now' || state === 'ai_proposed' ? 'bg-attention text-text' : 'bg-ink text-on-ink',
          'text-[11px] font-semibold',
        )}
      >
        {label}
      </span>
    )
  return <span aria-hidden>{dot}</span>
}

export function StepList({
  title,
  children,
  className,
  aside,
}: {
  title?: ReactNode
  children: ReactNode
  className?: string
  aside?: ReactNode
}) {
  return (
    <section className={cn('flex flex-col gap-2 rounded-panel bg-soft p-5', className)}>
      {title ? (
        <div className="flex items-baseline justify-between gap-2 px-1 pb-1.5">
          <h2 className="t-h3 m-0">{title}</h2>
          {aside}
        </div>
      ) : null}
      <ol className="m-0 flex list-none flex-col gap-2 p-0">{children}</ol>
    </section>
  )
}

export function StepItem({
  state,
  title,
  text,
  meta,
  right,
  dotLabel,
  className,
  children,
}: {
  state: StepState
  title: ReactNode
  text?: ReactNode
  meta?: ReactNode
  right?: ReactNode
  dotLabel?: ReactNode
  className?: string
  children?: ReactNode
}) {
  return (
    <li className={cn('flex items-start gap-3 rounded-item bg-surface px-4 py-3', className)}>
      <span className="mt-px">
        <StepDot state={state} label={dotLabel} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="t-item">{title}</span>
        {text ? <span className="text-[14px] text-text-body-muted">{text}</span> : null}
        {meta ? <span className="t-mono text-muted">{meta}</span> : null}
        {children}
      </div>
      {right ? <div className="shrink-0 text-right">{right}</div> : null}
    </li>
  )
}
