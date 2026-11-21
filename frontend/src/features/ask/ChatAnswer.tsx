import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'
import type { AskAnswer } from '@/api/contracts/common'
import { OriginMarker } from '@/components/common/ProvenanceTag'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { downloadFile } from '@/lib/download'
import { rowsCsvUrl, useSaveQuestion } from './api'

/** "template:summary_v1" → "szablon (bez AI)", "llm" → "model AI", "sql" → "zapytanie SQL". */
export function methodLabel(m: string): string {
  if (m === 'sql') return 'zapytanie SQL do bazy umów'
  if (m === 'llm') return 'model AI na liczbach z tej analizy'
  if (m === 'template' || m.startsWith('template:')) return 'szablon na liczbach z bazy (bez AI)'
  return m
}

const ROLE_ORIGIN = { obliczenie: 'CALC', wniosek_ai: 'AI', brak_danych: 'SOURCE' } as const

/** Pattern 13: role label, text, bars, source chips, actions. */
export function ChatAnswer({
  answer,
  onSaved,
  compact,
  className,
}: {
  answer: AskAnswer
  onSaved?: (code: string) => void
  compact?: boolean
  className?: string
}) {
  const save = useSaveQuestion()
  const code = save.data?.code ?? answer.saved_id ?? null
  const max = answer.scale_max ?? Math.max(...(answer.bars ?? []).map((b) => b.value), 1)
  const bars = answer.bars ?? []
  return (
    <article className={cn('flex flex-col gap-3 rounded-card bg-soft p-4', className)}>
      <header className="flex flex-col gap-1">
        <span className="text-[14px] font-medium text-text-secondary">{answer.question}</span>
        <span className="t-mono inline-flex items-center gap-1.5 text-muted">
          <OriginMarker origin={ROLE_ORIGIN[answer.role]} />
          {answer.role_label}
        </span>
      </header>
      <p className="m-0 text-[15px] leading-[1.55]">{answer.text}</p>
      {bars.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Zestawienie">
          {bars.slice(0, compact ? 5 : 16).map((b) => (
            <li
              key={b.label}
              className="grid grid-cols-[minmax(110px,170px)_1fr_auto] items-center gap-3 text-[13px]"
            >
              <span className="truncate">{b.label}</span>
              <span aria-hidden className="h-2 overflow-hidden rounded-pill bg-soft-2">
                <span
                  className={cn('block h-full', b.attention ? 'bg-attention' : 'bg-text-secondary')}
                  style={{ width: `${Math.max(2, (b.value / max) * 100)}%` }}
                />
              </span>
              <span className={cn('t-mono', b.attention && 'text-attention-text')}>{b.display}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {answer.sources.length > 0 ? (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Źródła">
          {answer.sources.map((s) => (
            <li
              key={s}
              className={cn(
                't-mono rounded-pill px-2.5 py-1',
                s.startsWith('brakuje')
                  ? 'bg-attention-soft text-attention-text'
                  : 'bg-surface text-text-secondary',
              )}
            >
              {s}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {answer.actions.map((a) => {
          if (a.kind === 'save') {
            return code ? (
              <span key="save" className="t-mono rounded-pill bg-surface px-3 py-1.5 text-text-secondary">
                zapisano jako {code}
              </span>
            ) : (
              <Button
                key="save"
                variant="outline"
                size="sm"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(answer.id, {
                    onSuccess: (r) => {
                      toast.success(`Zapisano jako ${r.code}.`)
                      onSaved?.(r.code)
                    },
                    onError: () => toast.error('Nie udało się zapisać odpowiedzi.'),
                  })
                }
              >
                {a.label}
              </Button>
            )
          }
          if (a.kind === 'export_csv') {
            return code ? (
              <Button
                key="csv"
                variant="outline"
                size="sm"
                onClick={() =>
                  downloadFile(rowsCsvUrl(code), `${code}.csv`).catch(() =>
                    toast.error('Nie udało się pobrać pliku.'),
                  )
                }
              >
                {a.label}
              </Button>
            ) : null
          }
          return a.href ? (
            <Button key={a.label} variant="outline" size="sm" asChild>
              <Link to={a.href as never}>{a.label}</Link>
            </Button>
          ) : null
        })}
      </div>
    </article>
  )
}
