import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { makeQueryClient } from '@/app/queryClient'
import { routeTree } from '@/routeTree.gen'

/** Renders the real route tree at `path` with a fresh QueryClient (MSW node handlers answer the API). */
export async function renderRoute(path: string) {
  const queryClient = makeQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } })
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  await router.load()
  return { ...utils, router, queryClient }
}
