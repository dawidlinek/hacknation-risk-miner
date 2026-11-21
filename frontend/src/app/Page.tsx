import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** max-width 1240, gutter 24, top 36, bottom 72 (README §5). */
export function Page({ className, ...p }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('mx-auto flex w-full max-w-[1240px] flex-col gap-7 px-6 pt-9 pb-18', className)}
      {...p}
    />
  )
}

/** main (flex 999 1 560px) + aside (flex 1 1 360px), gap 36, stacks on phones. */
export function TwoCol({
  main,
  aside,
  className,
}: {
  main: ReactNode
  aside: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-start gap-9', className)}>
      <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-7">{main}</div>
      <aside className="flex min-w-0 max-w-full flex-[1_1_360px] flex-col gap-4">{aside}</aside>
    </div>
  )
}

/** Soft panel, radius 28. */
export function Panel({ className, ...p }: ComponentProps<'section'>) {
  return <section className={cn('flex flex-col gap-2 rounded-panel bg-soft p-5', className)} {...p} />
}

/** White item inside a panel, radius 18. */
export function Item({ className, ...p }: ComponentProps<'div'>) {
  return <div className={cn('rounded-item bg-surface px-4 py-3', className)} {...p} />
}

/** Bordered panel (no fill), radius 28. */
export function OutlinePanel({ className, ...p }: ComponentProps<'section'>) {
  return (
    <section
      className={cn('flex flex-col gap-1 rounded-panel border border-divider px-5.5 py-5', className)}
      {...p}
    />
  )
}

export function PageHeader({
  title,
  eyebrow,
  breadcrumb,
  subtitle,
  actions,
  lead,
  before,
}: {
  title: ReactNode
  eyebrow?: ReactNode
  breadcrumb?: ReactNode
  subtitle?: ReactNode
  lead?: ReactNode
  actions?: ReactNode
  before?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-2">
        {breadcrumb ? <div className="t-mono text-muted">{breadcrumb}</div> : null}
        {eyebrow ? <div className="t-caption text-muted">{eyebrow}</div> : null}
        <div className="flex items-center gap-3">
          {before}
          <h1 className="t-h1 m-0" tabIndex={-1} data-page-title>
            {title}
          </h1>
        </div>
        {subtitle ? <div className="t-mono text-muted">{subtitle}</div> : null}
        {lead ? <p className="m-0 max-w-[720px] text-text-body-muted">{lead}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  )
}

export function SectionTitle({
  children,
  id,
  aside,
}: {
  children: ReactNode
  id?: string
  aside?: ReactNode
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <h2 id={id} className="t-h3 m-0">
        {children}
      </h2>
      {aside}
    </div>
  )
}
