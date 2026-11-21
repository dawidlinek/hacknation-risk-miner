import { useState } from 'react'
import { MOCK_GROUPS, type MockGroup, mockedGroups, setMockedGroups } from './config'

/** Dev-only panel (bottom-left): one checkbox per mock group, "przeładuj" applies. */
export function MockPanel() {
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState<Set<MockGroup>>(() => new Set(mockedGroups()))
  const [role, setRole] = useState(() => {
    try {
      return localStorage.getItem('rm.mockRole') ?? 'public'
    } catch {
      return 'public'
    }
  })
  if (!import.meta.env.DEV) return null
  const toggle = (g: MockGroup) =>
    setSel((s) => {
      const n = new Set(s)
      if (n.has(g)) n.delete(g)
      else n.add(g)
      return n
    })
  const apply = () => {
    setMockedGroups([...sel])
    try {
      localStorage.setItem('rm.mockRole', role)
    } catch {
      /* ignore */
    }
    const url = new URL(window.location.href)
    url.searchParams.delete('mocks')
    window.location.replace(url.toString())
  }
  return (
    <div className="fixed bottom-3 left-3 z-50 text-[12px]">
      {open ? (
        <div className="w-64 rounded-item border border-border bg-surface p-3 shadow-popover">
          <div className="mb-2 flex items-center justify-between">
            <strong className="text-[13px]">Mocki (dev)</strong>
            <button type="button" className="text-muted" onClick={() => setOpen(false)}>
              zamknij
            </button>
          </div>
          <div className="mb-2 flex gap-2">
            <button type="button" className="underline" onClick={() => setSel(new Set(MOCK_GROUPS))}>
              wszystkie
            </button>
            <button type="button" className="underline" onClick={() => setSel(new Set())}>
              żadne
            </button>
          </div>
          <div className="grid max-h-64 grid-cols-2 gap-x-2 gap-y-1 overflow-auto">
            {MOCK_GROUPS.map((g) => (
              <label key={g} className="flex items-center gap-1.5 font-mono">
                <input type="checkbox" checked={sel.has(g)} onChange={() => toggle(g)} />
                {g}
              </label>
            ))}
          </div>
          <label className="mt-2 flex items-center gap-2">
            rola (mock)
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded border border-border px-1"
            >
              <option value="public">public</option>
              <option value="expert">expert</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <button
            type="button"
            onClick={apply}
            className="mt-2 w-full rounded-pill bg-ink py-1.5 text-on-ink"
          >
            przeładuj
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-pill border border-border bg-surface px-2.5 py-1 font-mono text-muted shadow-popover"
        >
          mocks: {mockedGroups().size}/{MOCK_GROUPS.length}
        </button>
      )}
    </div>
  )
}
