import { createRootRouteWithContext, HeadContent, Outlet, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { AppShell } from '@/app/AppShell'
import type { RouterContext } from '@/app/router'
import { sessionQuery } from '@/auth/session'
import { TooltipProvider } from '@/components/ui/tooltip'
import { brand } from '@/config/brand'
import { featuresQuery } from '@/config/features'

export const Route = createRootRouteWithContext<RouterContext>()({
  beforeLoad: async ({ context }) => {
    await Promise.all([
      context.queryClient.ensureQueryData(sessionQuery),
      context.queryClient.ensureQueryData(featuresQuery),
    ])
  },
  head: () => ({ meta: [{ title: brand.name }] }),
  component: Root,
})

/** On navigation, focus moves to the page <h1> (a11y, frontend.md §1.2). */
function useFocusOnNavigate() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const status = useRouterState({ select: (s) => s.status })
  const first = useRef(true)
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run on every path change (focus the new page's h1)
  useEffect(() => {
    if (status !== 'idle') return
    if (first.current) {
      first.current = false
      return
    }
    const h = document.querySelector<HTMLElement>('[data-page-title]') ?? document.getElementById('main')
    h?.focus({ preventScroll: true })
  }, [pathname, status])
}

function Root() {
  useFocusOnNavigate()
  return (
    <TooltipProvider delayDuration={200}>
      <HeadContent />
      <AppShell>
        <Outlet />
      </AppShell>
    </TooltipProvider>
  )
}
