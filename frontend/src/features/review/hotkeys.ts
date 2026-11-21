// Review page hotkeys: 1-4 pick an option, Enter saves (when valid), J/K next/previous (wrapping), G toggles "Wzorcowy przykład".
// Ignored while focus is in an input, textarea, select or contenteditable.
export type HotkeyAction =
  | { type: 'pick'; index: number }
  | { type: 'save' }
  | { type: 'move'; to: number }
  | { type: 'gold' }
  | null

export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof Element)) return false
  const tag = el.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    (el as HTMLElement).isContentEditable === true
  )
}

export function resolveHotkey(
  e: { key: string; target: EventTarget | null; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean },
  ctx: { optionCount: number; canSave: boolean; hasGold: boolean; index: number; length: number },
): HotkeyAction {
  if (e.metaKey || e.ctrlKey || e.altKey) return null
  if (isTypingTarget(e.target)) return null
  const k = e.key
  if (/^[1-9]$/.test(k)) {
    const i = Number(k) - 1
    return i < ctx.optionCount ? { type: 'pick', index: i } : null
  }
  if (k === 'Enter') return ctx.canSave ? { type: 'save' } : null
  if (ctx.length > 0 && (k === 'j' || k === 'J')) return { type: 'move', to: (ctx.index + 1) % ctx.length }
  if (ctx.length > 0 && (k === 'k' || k === 'K'))
    return { type: 'move', to: (ctx.index - 1 + ctx.length) % ctx.length }
  if ((k === 'g' || k === 'G') && ctx.hasGold) return { type: 'gold' }
  return null
}
