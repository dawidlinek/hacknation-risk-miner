import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1,
        refetchOnWindowFocus: false,
      },
    },
  })
}
export const queryClient = makeQueryClient()
