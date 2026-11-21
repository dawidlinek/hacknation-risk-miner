import { Link, useRouterState } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { type FeatureName, useFeatures } from '@/config/features'
import { cn } from '@/lib/cn'

export interface PillTab {
  label: ReactNode
  /** resolved href, e.g. `/analizy/AN-2026-0014/symulacja` */
  href: string
  flag?: FeatureName
  /** active only on exact match (the index tab) */
  exact?: boolean
  /** extra prefixes that make the tab active */
  match?: string[]
}

/** Route tabs as links with aria-current; flagged tabs are hidden when their flag is off. */
export function PillTabs({
  tabs,
  label = 'Sekcje',
  className,
}: {
  tabs: PillTab[]
  label?: string
  className?: string
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const f = useFeatures()
  const visible = tabs.filter((t) => !t.flag || f[t.flag])
  return (
    <nav aria-label={label} className={cn('flex flex-wrap gap-1.5', className)}>
      {visible.map((t) => {
        const prefixes = [t.href, ...(t.match ?? [])]
        const active = t.exact
          ? pathname === t.href || pathname === `${t.href}/`
          : prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`))
        return (
          <Link
            key={t.href}
            to={t.href as never}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'inline-flex min-h-10 items-center rounded-pill px-4 text-[14px] font-medium no-underline',
              active ? 'bg-ink text-on-ink' : 'bg-soft text-text-secondary hover:bg-soft-2 hover:text-text',
            )}
          >
            {t.label}
          </Link>
        )
      })}
    </nav>
  )
}
