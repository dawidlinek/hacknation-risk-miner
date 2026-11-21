import { useQuery } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { EmptyState, SkeletonBlock } from '@/components/common/DataState'
import { Button } from '@/components/ui/button'
import { fmtDateTime } from '@/lib/dates'
import { clausesQuery, type RawClause, riskNamesQuery } from './api'

const ORIGIN: Record<RawClause['origin'], string> = {
  SOURCE: 'z materiału eksperckiego (pakiet sektorowy)',
  CALC: 'wyliczony',
  AI: 'zaproponowany przez model',
}

/** Provenance line in plain Polish: where the clause came from, who proposed or approved it, and when it last changed. */
export function clauseProvenance(c: RawClause): string {
  const who = c.approved_by
    ? `zatwierdził ${c.approved_by}`
    : c.proposed_by
      ? `zaproponował ${c.proposed_by}`
      : ORIGIN[c.origin]
  const when = fmtDateTime(c.updated_at, { short: true })
  return `${who}, wersja ${c.version}, ostatnia zmiana ${when}`
}

const top = (code: string | null) => (code ?? '').split('.')[0] || 'bez ryzyka'

function copy(text: string) {
  try {
    void navigator.clipboard.writeText(text)
    toast('Skopiowano zapis do schowka.')
  } catch {
    toast.error('Nie udało się skopiować.')
  }
}

/** Zapisy umowne: model clauses for the draft contract (PPU), grouped by the risk they limit. Status and provenance are
 * said once when they are the same for every clause, and per clause only where they differ. */
export function ClausesPanel() {
  const clauses = useQuery(clausesQuery)
  const names = useQuery(riskNamesQuery)
  if (clauses.isPending) return <SkeletonBlock className="h-[320px]" />
  if (clauses.isError)
    return <EmptyState>Nie udało się wczytać zapisów umownych. Odśwież stronę za chwilę.</EmptyState>
  const rows = clauses.data
    .filter((c) => c.status !== 'rejected' && c.status !== 'retired')
    .sort((a, b) => a.code.localeCompare(b.code, 'pl', { numeric: true }))
  if (rows.length === 0)
    return <EmptyState>W pakiecie sektorowym nie ma jeszcze zapisów umownych.</EmptyState>
  const approved = rows.filter((c) => c.status === 'approved').length
  const provs = rows.map(clauseProvenance)
  const common = provs.every((p) => p === provs[0]) ? provs[0] : null
  const groups = new Map<string, Map<string, RawClause[]>>()
  for (const c of rows) {
    const t = top(c.risk_code)
    const g = groups.get(t) ?? new Map<string, RawClause[]>()
    const sub = c.risk_code ?? t
    g.set(sub, [...(g.get(sub) ?? []), c])
    groups.set(t, g)
  }
  const name = (code: string | null) => (code ? names.data?.[code] : undefined)
  return (
    <div className="flex flex-col gap-6">
      <div className="flex max-w-[860px] flex-col gap-1">
        <p className="m-0 text-text-body-muted">
          Gotowe brzmienie postanowień do projektu umowy (PPU), każde ogranicza jedno ryzyko z katalogu.
          Wartości w nawiasach kwadratowych uzupełnij dla swojej inwestycji.
        </p>
        <p className="t-caption m-0 text-muted">
          {rows.length} zapisów,{' '}
          {approved === 0
            ? 'wszystkie są propozycjami i czekają na decyzję eksperta'
            : `zatwierdzonych ${approved}`}
          {common ? `. Pochodzenie: ${common}.` : '.'}
        </p>
      </div>
      {[...groups.entries()].map(([risk, subs]) => (
        <section key={risk} aria-labelledby={`zap-${risk}`} className="flex flex-col gap-3">
          <h2 id={`zap-${risk}`} className="t-h3 m-0">
            <span className="t-mono mr-2">{risk}</span>
            {name(risk) ?? ''}
          </h2>
          {[...subs.entries()].map(([sub, list]) => (
            <div
              key={sub}
              className="flex flex-col gap-1.5 rounded-item border border-border bg-surface px-4 py-3"
            >
              {sub !== risk ? (
                <span className="flex flex-wrap items-baseline gap-2">
                  <span className="t-mono text-muted">{sub}</span>
                  <span className="t-item">{name(sub) ?? ''}</span>
                </span>
              ) : null}
              <ol className="m-0 flex list-none flex-col gap-2 p-0">
                {list.map((c) => (
                  <li key={c.id} className="group flex items-start gap-3">
                    <p className="m-0 flex-1 text-[15px] leading-[1.6]">
                      {c.title ? <span className="font-medium">{c.title}. </span> : null}
                      {c.text}
                      {c.status === 'approved' ? (
                        <span className="t-caption ml-2 rounded-pill bg-success-soft px-2 py-0.5 text-success-text">
                          zatwierdzony
                        </span>
                      ) : null}
                      {common ? null : (
                        <span className="t-caption block text-muted">{clauseProvenance(c)}</span>
                      )}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => copy(c.text)}
                      aria-label={`Kopiuj zapis ${c.code}`}
                      title="Kopiuj zapis"
                      className="shrink-0"
                    >
                      <Copy aria-hidden className="size-3.5" />
                      Kopiuj
                    </Button>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
