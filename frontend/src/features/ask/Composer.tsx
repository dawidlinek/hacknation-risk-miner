import { SendHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/cn'

export function Composer({
  onSubmit,
  busy,
  placeholder = 'Zadaj pytanie o dane',
  label = 'Pytanie',
}: {
  onSubmit: (q: string) => void
  busy?: boolean
  placeholder?: string
  label?: string
}) {
  const [v, setV] = useState('')
  const send = () => {
    const q = v.trim()
    if (!q || busy) return
    onSubmit(q)
    setV('')
  }
  return (
    <form
      className="flex items-end gap-2 rounded-panel border border-border bg-surface p-2 pl-4 shadow-composer"
      onSubmit={(e) => {
        e.preventDefault()
        send()
      }}
    >
      <div className="flex-1">
        <Textarea
          aria-label={label}
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          rows={1}
          placeholder={placeholder}
          className="min-h-10 resize-none border-0 bg-transparent px-0 py-2 shadow-none focus-visible:ring-0"
        />
      </div>
      <button
        type="submit"
        disabled={busy || !v.trim()}
        aria-label="Zapytaj"
        className={cn(
          'grid size-10 shrink-0 place-items-center rounded-pill bg-ink text-on-ink',
          (busy || !v.trim()) && 'opacity-40',
        )}
      >
        <SendHorizontal className="size-4" aria-hidden />
      </button>
    </form>
  )
}

export function SuggestionChips({
  items,
  onPick,
  disabled,
}: {
  items: { key: string; label: string }[]
  onPick: (label: string) => void
  disabled?: boolean
}) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Przykładowe pytania">
      {items.map((s) => (
        <li key={s.key}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(s.label)}
            className="rounded-pill border border-border bg-surface px-3.5 py-1.5 text-[13px] text-text-secondary hover:bg-soft disabled:opacity-50"
          >
            {s.label}
          </button>
        </li>
      ))}
    </ul>
  )
}
