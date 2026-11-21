import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { ChevronDown, MessageSquare } from 'lucide-react'
import type { ReactNode } from 'react'
import { navCountsQuery, useLogout, useSession } from '@/auth/session'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Toaster } from '@/components/ui/sonner'
import { brand } from '@/config/brand'
import { useFeatures } from '@/config/features'
import { cn } from '@/lib/cn'
import { MockBadge } from '@/mocks/MockBadge'
import { MockPanel } from '@/mocks/MockPanel'
import { isActive, MORE, NAV, type NavItem } from './nav'

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-block text-[19px] font-bold tracking-[-0.04em]', className)}>
      <span>{brand.wordA}</span>{' '}
      <span className="rounded-chip bg-ink px-1.5 pb-0.5 tracking-[-0.02em] text-on-ink">{brand.wordB}</span>
    </span>
  )
}

function useVisibleItems(items: NavItem[]) {
  const { isPublic } = useSession()
  const f = useFeatures()
  return items.filter((i) => (!i.expertOnly || !isPublic) && (!i.flag || f[i.flag]))
}

export function NavPills() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const { isPublic } = useSession()
  const items = useVisibleItems(NAV)
  const counts = useQuery({ ...navCountsQuery, enabled: !isPublic })
  const more = useVisibleItems(MORE)
  return (
    <nav aria-label="Moduły" className="flex flex-wrap items-center gap-1">
      {items.map((i) => {
        const active = isActive(i, pathname)
        const n = !isPublic && i.count ? counts.data?.[i.count] : undefined
        return (
          <Link
            key={i.to}
            to={i.to as never}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'inline-flex min-h-9 items-center rounded-pill px-3 text-[14px] font-medium no-underline',
              active ? 'bg-ink text-on-ink' : 'text-text-secondary hover:bg-soft hover:text-text',
            )}
          >
            {i.label}
            {n ? (
              <span
                className={cn(
                  'ml-1.5 rounded-pill px-1.5 py-px font-mono text-[11px] font-semibold',
                  active ? 'bg-surface text-text' : 'bg-soft-2 text-text-secondary',
                )}
              >
                <span className="sr-only">, czeka: </span>
                {n}
              </span>
            ) : null}
          </Link>
        )
      })}
      {more.length > 0 ? (
        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              'inline-flex min-h-9 items-center gap-1 rounded-pill px-3 text-[14px] font-medium text-text-secondary hover:bg-soft hover:text-text',
              more.some((m) => isActive(m, pathname)) && 'bg-ink text-on-ink hover:bg-ink hover:text-on-ink',
            )}
          >
            Więcej <ChevronDown aria-hidden className="size-3.5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[200px]">
            {more.map((m) => (
              <DropdownMenuItem key={m.to} asChild>
                <Link to={m.to as never} className="text-[14px] font-medium">
                  {m.label}
                </Link>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </nav>
  )
}

export function AskPill() {
  const f = useFeatures()
  if (!f.ask_memory) return null
  return (
    <Link
      to={'/zapytaj' as never}
      className="inline-flex min-h-10 items-center gap-2 rounded-pill border border-border px-3.5 text-[14px] font-medium text-text no-underline hover:bg-soft"
    >
      <MessageSquare aria-hidden className="size-[15px]" />
      Zapytaj
    </Link>
  )
}

export function AccountMenu() {
  const { session } = useSession()
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <div className="flex items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`${session.initials ?? 'E'}, konto: ${session.name ?? 'ekspert'}`}
          className="inline-flex size-10 items-center justify-center rounded-pill border border-border bg-soft text-[14px] font-semibold"
        >
          {session.initials ?? 'E'}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[200px]">
          <DropdownMenuLabel className="text-[13px] text-muted">
            {session.name ?? 'Ekspert (demo)'}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => logout.mutate(undefined, { onSettled: () => navigate({ to: '/' }) })}
          >
            Wyloguj
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function AppHeader() {
  const { isPublic } = useSession()
  const f = useFeatures()
  const href = useRouterState({ select: (s) => s.location.href })
  const home = isPublic ? (f.radar ? '/monitoring' : '/analizy/nowa') : '/'
  return (
    <header className="border-b border-divider">
      <div className="mx-auto flex max-w-[1288px] flex-wrap items-center justify-between gap-x-5 gap-y-3 px-6 py-3.5">
        <div className="flex items-center gap-3">
          <Link to={home as never} className="text-text no-underline">
            <Wordmark />
            <span className="sr-only">, strona główna</span>
          </Link>
          <MockBadge />
        </div>
        <NavPills />
        <div className="flex items-center gap-2.5">
          <AskPill />
          {isPublic ? (
            <Link
              to="/zaloguj"
              search={{ redirect: href.startsWith('/zaloguj') ? undefined : href }}
              className="inline-flex min-h-10 items-center rounded-pill bg-ink px-4 text-[14px] font-semibold text-on-ink no-underline"
            >
              Zaloguj się
            </Link>
          ) : (
            <AccountMenu />
          )}
        </div>
      </div>
    </header>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <a
        href="#main"
        className="sr-only z-50 rounded-pill bg-ink px-4 py-2 text-on-ink focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Przejdź do treści
      </a>
      <AppHeader />
      <main id="main" tabIndex={-1} className="outline-none">
        {children}
      </main>
      <Toaster position="bottom-center" />
      <MockPanel />
    </div>
  )
}
