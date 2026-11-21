import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { PageHeader } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { ProvenanceTag } from '@/components/common/ProvenanceTag'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/cn'
import { addClauseToPack, decideItem } from '../report/api'
import { redpenQuery } from './api'
import {
  canAddClause,
  canDecide,
  countsLabel,
  firstPage,
  type Note,
  neighbour,
  noteMeta,
  type RedPen,
  STATUS_LABEL,
  segments,
  stepPages,
} from './logic'

export interface RedPenScreenProps {
  id: string
  doc: number
  page?: number | null
  onlyNoted: boolean
  active: string | null
  onPage: (p: number) => void
  onOnlyNoted: (v: boolean) => void
  onActive: (no: string | null) => void
}

export function RedPenScreen(props: RedPenScreenProps) {
  const { data } = useSuspenseQuery(redpenQuery(props.id, props.doc))
  return <RedPenBody r={data} {...props} />
}

export function RedPenBody({
  r,
  id,
  doc,
  page,
  onlyNoted,
  active,
  onPage,
  onOnlyNoted,
  onActive,
}: RedPenScreenProps & { r: RedPen }) {
  const notes = r.notes as Note[]
  const current = firstPage(r, page)
  const steps = stepPages(r.pages, onlyNoted)
  const shown = r.pages.find((p) => p.page_no === current)
  const activeNote = notes.find((n) => n.no === active) ?? null
  // a note chosen from the list jumps to its page
  useEffect(() => {
    if (activeNote?.page && activeNote.page !== current) onPage(activeNote.page)
  }, [activeNote?.page, current, onPage])
  const docType = r.document.doc_type
  const found = notes.filter((n) => n.kind === 'found')
  const missing = notes.filter((n) => n.kind === 'missing')
  return (
    <div className="flex flex-wrap items-start gap-9">
      <section aria-label="Dokument" className="flex min-w-0 flex-[999_1_560px] flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-item bg-soft px-4 py-2.5">
          <span className="t-mono truncate">{r.document.filename}</span>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Poprzednia strona"
              disabled={current === null || neighbour(steps, current, -1) === null}
              onClick={() => current !== null && onPage(neighbour(steps, current, -1) as number)}
            >
              <ChevronLeft aria-hidden />
            </Button>
            <span className="t-mono" data-testid="page-indicator">
              s. {current ?? '-'} / {r.document.pages || r.pages.length}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Następna strona"
              disabled={current === null || neighbour(steps, current, 1) === null}
              onClick={() => current !== null && onPage(neighbour(steps, current, 1) as number)}
            >
              <ChevronRight aria-hidden />
            </Button>
            <label htmlFor="only-noted" className="t-small ml-2 flex cursor-pointer items-center gap-2">
              <Checkbox
                id="only-noted"
                checked={onlyNoted}
                onCheckedChange={(v) => onOnlyNoted(v === true)}
              />
              tylko strony z uwagami
            </label>
          </div>
        </div>
        {shown ? (
          <article
            className="flex flex-col gap-3 rounded-panel border border-divider px-6 py-5"
            data-testid="page-text"
          >
            <span className="t-caption text-muted">
              {docType}, strona {shown.page_no}
            </span>
            {shown.paragraphs.length === 0 ? (
              <EmptyState>Tej strony nie udało się odczytać. Pokaż oryginał PDF.</EmptyState>
            ) : (
              shown.paragraphs.map((p, i) =>
                p.heading ? (
                  <h2 key={i} className="t-h3 m-0">
                    {p.text}
                  </h2>
                ) : (
                  <p key={i} className="t-small m-0 whitespace-pre-line text-text-secondary">
                    {segments(p).map((s, j) =>
                      s.notes.length ? (
                        <span key={j}>
                          <mark className={cn(s.notes.includes(active ?? '') && 'ring-2 ring-attention')}>
                            {s.text}
                          </mark>
                          {s.endsHere.map((no) => (
                            <a
                              key={no}
                              href={`#u${no}`}
                              aria-label={`Uwaga ${no}`}
                              onClick={() => onActive(no)}
                              className="t-mono ml-0.5 inline-flex size-[18px] items-center justify-center rounded-pill bg-attention align-super text-[10px] text-on-ink no-underline"
                            >
                              {no}
                            </a>
                          ))}
                        </span>
                      ) : (
                        <span key={j}>{s.text}</span>
                      ),
                    )}
                  </p>
                ),
              )
            )}
          </article>
        ) : (
          <EmptyState>Brak tekstu dokumentu.</EmptyState>
        )}
        <span className="t-caption text-muted">
          Tekst strony z wgranego dokumentu{r.document.demo ? ' (dokument publiczny z BZP)' : ''}. Zaznaczenia
          to cytaty sprawdzone w tekście.
        </span>
      </section>
      <aside className="flex min-w-0 max-w-full flex-[1_1_360px] flex-col gap-3">
        <PageHeader title="Uwagi do dokumentów" subtitle={countsLabel(r.counts.found, r.counts.missing)} />
        {r.status === 'queued' || r.status === 'running' ? (
          <p className="t-small m-0 rounded-item bg-prov-ai-soft px-4 py-2.5 text-prov-ai" role="status">
            Model AI czyta dokument. Poniżej uwagi z reguł; uwagi AI dojdą same.
          </p>
        ) : null}
        {found.length === 0 && missing.length === 0 ? (
          <EmptyState>Nie znaleźliśmy ryzykownych zapisów w tym dokumencie.</EmptyState>
        ) : null}
        {[...found, ...missing].map((n) =>
          n.no === active ? (
            <NoteCard key={n.no} id={id} doc={doc} n={n} docType={docType} onClose={() => onActive(null)} />
          ) : (
            <NoteRow key={n.no} n={n} docType={docType} onOpen={() => onActive(n.no)} />
          ),
        )}
        {(r.case_hints ?? []).length ? (
          <section aria-label="Podobne przypadki" className="flex flex-col gap-2 rounded-panel bg-soft p-4">
            {(r.case_hints ?? []).map((h) => (
              <div key={h.risk_code} className="flex flex-col gap-1">
                <span className="t-small">{h.text}</span>
                <span className="flex flex-wrap gap-1.5">
                  {h.cases.map((c) => (
                    <a
                      key={c.href}
                      href={c.href}
                      className="t-mono rounded-chip bg-surface px-1.5 py-0.5 text-prov-case no-underline"
                    >
                      {c.label}
                    </a>
                  ))}
                </span>
              </div>
            ))}
            <ProvenanceTag origin="CASE" text="najbardziej podobne umowy z BZP" />
          </section>
        ) : null}
        {(r.limitations ?? []).map((l) => (
          <p key={l} className="t-caption m-0 text-muted">
            {l}
          </p>
        ))}
      </aside>
    </div>
  )
}

function Dot({ n }: { n: Note }) {
  return (
    <span
      aria-hidden
      className={cn(
        't-mono flex size-6 shrink-0 items-center justify-center rounded-pill text-[11px]',
        n.kind === 'missing'
          ? 'border-2 border-dashed border-attention text-attention-text'
          : 'bg-attention text-on-ink',
      )}
    >
      {n.no}
    </span>
  )
}

function NoteRow({ n, docType, onOpen }: { n: Note; docType: string; onOpen: () => void }) {
  return (
    <button
      type="button"
      id={`u${n.no}`}
      onClick={onOpen}
      className="flex w-full items-start gap-3 rounded-item bg-soft px-3.5 py-3 text-left hover:bg-soft-2"
    >
      <Dot n={n} />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-item">{n.title}</span>
        <span className="t-caption line-clamp-2 text-text-body-muted">{n.why}</span>
        <span className="t-mono text-muted">
          {n.kind === 'missing' ? (n.state_label ?? n.evidence_state ?? 'brak') : noteMeta(n, docType)}
        </span>
      </span>
    </button>
  )
}

export function NoteCard({
  id,
  doc,
  n,
  docType,
  onClose,
}: {
  id: string
  doc: number
  n: Note
  docType: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(n.clause?.text ?? '')
  const [inPack, setInPack] = useState(!!n.clause?.in_pack)
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['analysis', id, 'redpen', doc] })
    void qc.invalidateQueries({ queryKey: ['analysis', id, 'report'] })
  }
  const err = (e: unknown) =>
    toast.error(
      e instanceof ApiError && e.status === 403
        ? 'Ta analiza jest tylko do odczytu.'
        : 'Nie zapisaliśmy zmiany. Spróbuj ponownie.',
    )
  const add = useMutation({
    mutationFn: (t?: string) => addClauseToPack(id, n.clause?.code as string, t),
    onSuccess: () => {
      setInPack(true)
      setEditing(false)
      refresh()
    },
    onError: err,
  })
  const decide = useMutation({
    mutationFn: (body: { action: 'approve' | 'reject'; reason?: string }) =>
      decideItem(id, n.item_id as number, body),
    onSuccess: () => refresh(),
    onError: err,
  })
  return (
    <article
      id={`u${n.no}`}
      className="flex flex-col gap-2.5 rounded-panel border border-border bg-surface p-4"
      data-testid="note-card"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <Dot n={n} />
          <span className="t-mono text-muted">
            {n.kind === 'missing' ? (n.state_label ?? 'brak') : noteMeta(n, docType)}
          </span>
        </span>
        <span
          className={cn('t-mono', n.review_status === 'proposed' ? 'text-review-proposed' : 'text-muted')}
        >
          {STATUS_LABEL[n.review_status] ?? n.review_status}
        </span>
      </div>
      <span className="t-item">{n.title}</span>
      <span className="t-small text-text-body-muted">{n.why}</span>
      {n.quote ? (
        <blockquote className="t-small m-0 border-l-2 border-attention pl-3 text-text-secondary">
          „{n.quote.text}”
          {!n.quote.verified ? (
            <span className="t-mono ml-2 rounded-chip bg-attention-soft px-1.5 text-attention-text">
              cytat niezweryfikowany
            </span>
          ) : null}
        </blockquote>
      ) : null}
      {n.limits && n.kind === 'missing' ? <span className="t-caption text-muted">{n.limits}</span> : null}
      {n.cases.length ? (
        <div className="flex flex-wrap gap-1.5">
          {n.cases.map((c) => (
            <a
              key={c.href}
              href={c.href}
              className="t-mono rounded-chip bg-prov-case-soft px-1.5 py-0.5 text-prov-case no-underline"
            >
              {c.label}
            </a>
          ))}
        </div>
      ) : null}
      {n.clause?.code ? (
        <div className="flex flex-col gap-2 rounded-item bg-soft px-3.5 py-3">
          <span className="t-eyebrow text-muted">Proponowany zapis, {n.clause.code}</span>
          {editing ? (
            <textarea
              aria-label="Treść zapisu"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              className="t-small w-full rounded-inner border border-border bg-surface p-2"
            />
          ) : (
            <span className="t-small">{text || n.clause.text}</span>
          )}
          <div className="flex flex-wrap gap-2">
            {editing ? (
              <>
                <Button size="sm" onClick={() => add.mutate(text)} disabled={add.isPending}>
                  Zapisz
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                  Anuluj
                </Button>
              </>
            ) : (
              <>
                {canAddClause(n) ? (
                  <Button
                    size="sm"
                    aria-pressed={inPack}
                    disabled={inPack || add.isPending}
                    onClick={() => add.mutate(undefined)}
                  >
                    {inPack ? 'W pakiecie' : 'Dodaj do PPU'}
                  </Button>
                ) : null}
                <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                  Popraw zapis
                </Button>
              </>
            )}
          </div>
        </div>
      ) : null}
      {canDecide(n) ? (
        <div className="flex flex-col gap-2 border-t border-divider pt-2.5" data-testid="note-decision">
          <span className="t-caption text-muted">Wniosek AI: zdecyduj, czy trafi do pakietu.</span>
          {rejecting ? (
            <div className="flex flex-col gap-2">
              <input
                aria-label="Powód odrzucenia"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Powód odrzucenia"
                className="t-small rounded-pill border border-border px-3 py-1.5"
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={reason.trim().length < 3 || decide.isPending}
                  onClick={() => decide.mutate({ action: 'reject', reason })}
                >
                  Odrzuć
                </Button>
                <Button size="sm" variant="outline" onClick={() => setRejecting(false)}>
                  Anuluj
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => decide.mutate({ action: 'approve' })}
                disabled={decide.isPending}
              >
                Zatwierdź
              </Button>
              <Button size="sm" variant="outline" onClick={() => setRejecting(true)}>
                Odrzuć
              </Button>
            </div>
          )}
        </div>
      ) : null}
      <div className="flex items-center justify-between">
        {n.origin === 'AI' ? (
          <ProvenanceTag
            origin="AI"
            reviewStatus={n.review_status}
            text="cytat sprawdzony w tekście strony"
          />
        ) : (
          <ProvenanceTag
            origin="CALC"
            text={n.kind === 'missing' ? 'reguła i lista kontrolna' : 'reguła, cytat z tekstu'}
          />
        )}
        <Button size="xs" variant="ghost" onClick={onClose}>
          Zwiń
        </Button>
      </div>
    </article>
  )
}
