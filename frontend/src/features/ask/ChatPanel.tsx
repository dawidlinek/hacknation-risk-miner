import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { AskAnswer } from '@/api/contracts/common'
import { askErrorMessage, suggestionsQuery } from './api'
import { ChatAnswer } from './ChatAnswer'
import { Composer, SuggestionChips } from './Composer'

/**
 * Docked chat: suggestion chips, composer, answers. `ask` performs the call (project chat, report chat, global ask);
 * answers are cached per question so re-picking a chip does not call the model again.
 */
export function ChatPanel({
  title = 'Zapytaj o ten projekt',
  context,
  ask,
  extraSuggestions = [],
  placeholder,
  compact = true,
}: {
  title?: string
  context: 'pulpit' | 'zapytaj' | 'analysis' | 'project'
  ask: (q: string) => Promise<AskAnswer>
  extraSuggestions?: string[]
  placeholder?: string
  compact?: boolean
}) {
  const sugg = useQuery(suggestionsQuery(context))
  const [thread, setThread] = useState<AskAnswer[]>([])
  const [cache] = useState(() => new Map<string, AskAnswer>())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (q: string) => {
    setError(null)
    const hit = cache.get(q)
    if (hit) return setThread((t) => [hit, ...t.filter((a) => a.id !== hit.id)])
    setBusy(true)
    try {
      const a = await ask(q)
      cache.set(q, a)
      setThread((t) => [a, ...t])
    } catch (e) {
      setError(askErrorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const chips = [...extraSuggestions.map((l) => ({ key: l, label: l })), ...(sugg.data ?? [])]
  return (
    <section aria-label={title} className="flex flex-col gap-3 rounded-panel bg-soft p-5">
      <h2 className="t-h3 m-0">{title}</h2>
      <SuggestionChips items={chips} onPick={run} disabled={busy} />
      <Composer onSubmit={run} busy={busy} placeholder={placeholder} label={title} />
      {busy ? (
        <p role="status" className="t-mono m-0 text-muted">
          Szukamy odpowiedzi w danych…
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-[14px] text-attention-text">
          {error}
        </p>
      ) : null}
      {thread.map((a) => (
        <ChatAnswer key={a.id} answer={a} compact={compact} className="bg-surface" />
      ))}
    </section>
  )
}
