// Mock groups (frontend.md §1.4). VITE_MOCKS=all | none | <comma list>; dev override ?mocks=a,b (localStorage rm.mocks).
export const MOCK_GROUPS = [
  'config',
  'session',
  'dashboard',
  'ask',
  'analyses',
  'redpen',
  'simulation',
  'allocation',
  'pack',
  'import',
  'projects',
  'project_card',
  'graph',
  'documents',
  'audit',
  'review',
  'catalogue',
  'monitoring',
  'settings',
] as const
export type MockGroup = (typeof MOCK_GROUPS)[number]

/** Groups whose fixtures hold only real figures (README §10); the only ones allowed in production builds. */
export const DEMO_SAFE: readonly MockGroup[] = []

function parse(raw: string | null | undefined): Set<MockGroup> {
  const v = (raw ?? '').trim()
  if (v === 'all') return new Set(MOCK_GROUPS)
  if (v === '' || v === 'none') return new Set()
  return new Set(v.split(',').map((s) => s.trim()).filter((s): s is MockGroup => (MOCK_GROUPS as readonly string[]).includes(s)))
}

function resolve(): Set<MockGroup> {
  const mode = import.meta.env.MODE
  if (mode === 'test') return new Set(MOCK_GROUPS)
  let raw: string | null = import.meta.env.VITE_MOCKS ?? 'none'
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    try {
      const q = new URLSearchParams(window.location.search).get('mocks')
      if (q !== null) localStorage.setItem('rm.mocks', q)
      raw = localStorage.getItem('rm.mocks') ?? raw
    } catch {
      /* storage blocked */
    }
  }
  const set = parse(raw)
  if (import.meta.env.PROD) for (const g of [...set]) if (!DEMO_SAFE.includes(g)) set.delete(g)
  return set
}

let active = resolve()
export const mockedGroups = (): ReadonlySet<MockGroup> => active
export const isMocked = (g: MockGroup) => active.has(g)
export const anyMocked = () => active.size > 0

export function setMockedGroups(groups: MockGroup[]) {
  active = new Set(groups)
  try {
    localStorage.setItem('rm.mocks', groups.length === MOCK_GROUPS.length ? 'all' : groups.length ? groups.join(',') : 'none')
  } catch {
    /* ignore */
  }
}
