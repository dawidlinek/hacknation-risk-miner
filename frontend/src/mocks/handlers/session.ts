import type { NavCounts, Role, Session } from '@/api/contracts/session'
import { FEATURE_DEFAULTS } from '@/config/features'
import { HttpResponse, mockable } from '../mockable'

const s = mockable('session', { latency: 60 })
const c = mockable('config', { latency: 30 })

function role(): Role {
  try {
    const r = localStorage.getItem('rm.mockRole')
    return r === 'expert' || r === 'admin' ? r : 'public'
  } catch {
    return 'public'
  }
}
function setRole(r: Role) {
  try {
    if (r === 'public') localStorage.removeItem('rm.mockRole')
    else localStorage.setItem('rm.mockRole', r)
  } catch {
    /* ignore */
  }
}
const sessionFor = (r: Role): Session =>
  r === 'public' ? { role: 'public', name: null, initials: null } : { role: r, name: r === 'admin' ? 'Administrator' : 'Ekspert', initials: r === 'admin' ? 'A' : 'E' }

export const handlers = [
  s.get('/api/auth/me', () => HttpResponse.json(sessionFor(role()))),
  s.post('/api/auth/login', async ({ request }) => {
    const body = (await request.json()) as { username?: string; password?: string }
    if (!body.username || !body.password || body.password.length < 3) {
      return HttpResponse.json({ detail: 'Nieprawidłowy login lub hasło.', code: 'bad_credentials' }, { status: 401 })
    }
    const r: Role = body.username === 'admin' ? 'admin' : 'expert'
    setRole(r)
    return HttpResponse.json(sessionFor(r))
  }),
  s.post('/api/auth/logout', () => {
    setRole('public')
    return new HttpResponse(null, { status: 204 })
  }),
  s.get('/api/nav/counts', () => HttpResponse.json<NavCounts>({ review_open: 37, monitoring_new: 12 })),
  // In mock mode every built feature is on (jelly off: it needs WebGL).
  c.get('/api/config/features', () =>
    HttpResponse.json(Object.fromEntries(Object.keys(FEATURE_DEFAULTS).map((k) => [k, k !== 'jelly']))),
  ),
]
