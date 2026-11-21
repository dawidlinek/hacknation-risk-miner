// Records whether any response came from the MSW mock layer (header x-rm-mock: 1), so MockBadge can show
// "dane przykładowe". Kept dependency-free so lib/ and api/ can both import it.
type Listener = (groups: ReadonlySet<string>) => void
const seen = new Set<string>()
const listeners = new Set<Listener>()

export function markMockResponse(res: Response) {
  if (res.headers.get('x-rm-mock') !== '1') return
  const group = res.headers.get('x-rm-mock-group') ?? 'mock'
  if (seen.has(group)) return
  seen.add(group)
  for (const l of listeners) l(seen)
}
export function subscribeMock(l: Listener) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
export const mockGroupsSeen = (): ReadonlySet<string> => seen
