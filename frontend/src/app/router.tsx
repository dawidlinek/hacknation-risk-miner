import type { QueryClient } from '@tanstack/react-query'
import { createRouter } from '@tanstack/react-router'
import { routeTree } from '@/routeTree.gen'
import { NotFound } from './NotFound'
import { PageSkeleton } from './PageSkeleton'
import { queryClient } from './queryClient'
import { RouteError } from './RouteError'

export interface RouterContext {
  queryClient: QueryClient
}

export function makeRouter(qc: QueryClient = queryClient) {
  return createRouter({
    routeTree,
    context: { queryClient: qc },
    defaultPreload: 'intent',
    defaultPreloadStaleTime: 0,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: () => <NotFound />,
    defaultPendingComponent: PageSkeleton,
    defaultPendingMs: 150,
    scrollRestoration: true,
  })
}
export const router = makeRouter()

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
