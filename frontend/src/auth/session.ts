import { type QueryClient, queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { redirect } from '@tanstack/react-router'
import { ApiError, contractFetch } from '@/api/client'
import type { DemoPersona, LoginIn, NavCounts, Role, Session } from '@/api/contracts/session'
import { keys } from '@/lib/keys'

export const PUBLIC_SESSION: Session = { role: 'public', name: null, initials: null }

/** Backend (api_contract §2.1) answers `{user: {name, role} | null}`; the mock answers a Session. */
export function adaptSession(raw: unknown): Session {
  if (!raw || typeof raw !== 'object') return PUBLIC_SESSION
  const r = raw as Record<string, unknown>
  if (typeof r.role === 'string') {
    const role = (r.role === 'admin' ? 'admin' : r.role === 'expert' ? 'expert' : 'public') as Role
    return {
      role,
      name: (r.name as string | null) ?? null,
      initials: (r.initials as string | null) ?? null,
      persona: (r.persona as string | null | undefined) ?? null,
      read_only: Boolean(r.read_only),
    }
  }
  const user = r.user as
    | { name?: string; role?: string; persona?: string | null; read_only?: boolean }
    | null
    | undefined
  if (!user || !user.role) return PUBLIC_SESSION
  const role = (user.role === 'admin' ? 'admin' : user.role === 'expert' ? 'expert' : 'public') as Role
  const name = user.name ?? null
  return {
    role,
    name,
    initials: name ? name.slice(0, 1).toUpperCase() : role === 'admin' ? 'A' : 'E',
    persona: user.persona ?? null,
    read_only: Boolean(user.read_only),
  }
}

export const sessionQuery = queryOptions({
  queryKey: keys.session,
  queryFn: async (): Promise<Session> => {
    try {
      return adaptSession(await contractFetch<unknown>('/api/auth/me'))
    } catch {
      return PUBLIC_SESSION
    }
  },
  staleTime: Number.POSITIVE_INFINITY,
})

export function useSession() {
  const q = useQuery(sessionQuery)
  const session = q.data ?? PUBLIC_SESSION
  return {
    session,
    isPublic: session.role === 'public',
    isExpert: session.role !== 'public',
    isAdmin: session.role === 'admin',
    readOnly: Boolean(session.read_only),
    isLoading: q.isLoading,
  }
}

export const navCountsQuery = queryOptions({
  queryKey: keys.navCounts,
  queryFn: () => contractFetch<NavCounts>('/api/nav/counts'),
  staleTime: 60_000,
})

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: LoginIn) =>
      adaptSession(await contractFetch<unknown>('/api/auth/login', { method: 'POST', json: input })),
    onSuccess: (s) => {
      qc.setQueryData(keys.session, s)
      qc.invalidateQueries({ queryKey: keys.navCounts })
    },
  })
}

/** One-click demo accounts (GET /api/auth/demo-personas); an empty list means the demo login is off. */
export const demoPersonasQuery = queryOptions({
  queryKey: ['auth', 'demo-personas'],
  queryFn: async (): Promise<DemoPersona[]> => {
    try {
      return await contractFetch<DemoPersona[]>('/api/auth/demo-personas')
    } catch {
      return []
    }
  },
  staleTime: Number.POSITIVE_INFINITY,
})

export function useDemoLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (persona: DemoPersona['persona']) =>
      adaptSession(
        await contractFetch<unknown>('/api/auth/demo-login', { method: 'POST', json: { persona } }),
      ),
    onSuccess: (s) => {
      qc.setQueryData(keys.session, s)
      qc.invalidateQueries({ queryKey: keys.navCounts })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => contractFetch<void>('/api/auth/logout', { method: 'POST' }),
    onSettled: () => {
      qc.setQueryData(keys.session, PUBLIC_SESSION)
      qc.removeQueries({ queryKey: keys.navCounts })
    },
  })
}

const RANK: Record<Role, number> = { public: 0, expert: 1, admin: 2 }

/** `beforeLoad` guard: redirects to /zaloguj?redirect=<href> when the role is too low. */
export async function requireRole(ctx: { queryClient: QueryClient }, role: Role, href: string) {
  const s = await ctx.queryClient.ensureQueryData(sessionQuery)
  if (RANK[s.role] < RANK[role]) throw redirect({ to: '/zaloguj', search: { redirect: href } })
  return s
}

export const isRateLimited = (e: unknown) => e instanceof ApiError && e.status === 429
export const RATE_LIMIT_MSG = 'Za dużo pytań naraz. Spróbuj za minutę.'
