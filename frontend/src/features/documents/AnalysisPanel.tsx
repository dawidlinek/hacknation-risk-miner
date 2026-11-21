import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, CircleAlert, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useSession } from '@/auth/session'
import { DataState } from '@/components/common/DataState'
import { QuoteCard } from '@/components/common/QuoteCard'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { fmtDate } from '@/lib/dates'
import {
  decisionText,
  factDisplay,
  factLabel,
  GROUPS,
  lineText,
  ORIGIN_NAME,
  rerunText,
  reviewLinks,
  STATE_LABEL,
  sensitivityLabel,
  stepsSummary,
  VERIFY_LABEL,
} from './analysis'
import { changesSinceQuery, documentAnalysisQuery, uploadErrorMessage, useLinkDocument } from './api'
import { READ_ONLY_REASON } from './logic'
import type { ChangeLine, RealAnalysis, RealStep } from './types'

function StepIcon({ state }: { state: RealStep['state'] }) {
  if (state === 'done') return <Check aria-hidden className="size-4 text-success-text" />
  if (state === 'failed') return <CircleAlert aria-hidden className="size-4 text-sev-high" />
  if (state === 'running') return <Loader2 aria-hidden className="size-4 animate-spin text-attention-text" />
  return <span aria-hidden className="size-3 rounded-pill border-2 border-dashed border-border" />
}

export function ProcessingSteps({ steps }: { steps: RealStep[] }) {
  return (
    <ol aria-label="Etapy przetwarzania" className="m-0 flex list-none flex-col gap-1.5 p-0">
      {steps.map((s) => (
        <li key={s.key} className="flex items-center gap-2.5 rounded-item bg-surface px-3.5 py-2 text-[14px]">
          <StepIcon state={s.state} />
          <span className="flex-1">
            {s.label}
            {s.detail ? <span className="ml-2 text-[12px] text-muted">{s.detail}</span> : null}
          </span>
          <span
            className={cn(
              't-mono text-[12px]',
              s.state === 'failed'
                ? 'text-sev-high'
                : s.state === 'done'
                  ? 'text-success-text'
                  : 'text-muted',
            )}
          >
            {STATE_LABEL[s.state]}
          </span>
        </li>
      ))}
    </ol>
  )
}

function Facts({ a }: { a: RealAnalysis }) {
  if (a.facts.length === 0 && a.causes.length === 0) return null
  return (
    <section aria-labelledby="fakty-z-dokumentu" className="flex flex-col gap-2">
      <h3 id="fakty-z-dokumentu" className="t-h3 m-0">
        Fakty z dokumentu
      </h3>
      {a.facts.map((f, i) => {
        const v = VERIFY_LABEL[f.verification ?? 'unverified'] ?? VERIFY_LABEL.unverified
        return (
          <QuoteCard
            key={`${f.field}-${i}`}
            title={`${factLabel(f)}: ${factDisplay(f)}`}
            reference={f.page ? `s. ${f.page}` : undefined}
            hit={f.quote ?? ''}
            origin={f.origin === 'AI' ? 'AI' : 'CALC'}
            chips={[
              { text: v.text, tone: v.tone },
              { text: ORIGIN_NAME[f.origin ?? 'CALC'] ?? 'reguła', tone: 'neutral' },
            ]}
          />
        )
      })}
      {a.causes.map((c, i) => {
        const v = VERIFY_LABEL[c.verification ?? 'unverified'] ?? VERIFY_LABEL.unverified
        return (
          <QuoteCard
            key={`${c.code}-${i}`}
            title={`Przyczyna ${c.code}: ${c.why ?? ''}`.trim()}
            reference={c.page ? `s. ${c.page}` : undefined}
            hit={c.quote ?? ''}
            origin={c.origin === 'AI' ? 'AI' : 'CALC'}
            chips={[
              { text: v.text, tone: v.tone },
              { text: 'wniosek do przeglądu', tone: 'warn' },
            ]}
          />
        )
      })}
    </section>
  )
}

function Line({ l }: { l: ChangeLine }) {
  return (
    <li className="flex flex-col gap-0.5 rounded-item bg-surface px-3.5 py-2.5 text-[14px]">
      <span className="font-medium">{l.label}</span>
      <span className="t-mono text-[12px] text-text-secondary">{lineText(l)}</span>
      {l.why ? <span className="text-[13px] text-text-body-muted">{l.why}</span> : null}
      {l.from_document ? (
        <span className="t-mono text-[11.5px] text-prov-calc">z nowego dokumentu</span>
      ) : null}
      {l.decision ? (
        <span className="t-mono text-[11.5px] text-success-text">{decisionText(l.decision)}</span>
      ) : null}
    </li>
  )
}

export function ChangesSince({ rmId, documentId }: { rmId: string; documentId: number }) {
  const q = useQuery(changesSinceQuery(rmId, documentId, true))
  const { isExpert } = useSession()
  return (
    <DataState query={q}>
      {(d) => (
        <section aria-labelledby="co-sie-zmienilo" className="flex flex-col gap-3">
          <h3 id="co-sie-zmienilo" className="t-h3 m-0">
            Co się zmieniło
          </h3>
          {GROUPS.map((g) => (
            <div key={g.key} className="flex flex-col gap-1.5">
              <h4 className="m-0 flex items-baseline gap-2 text-[15px] font-semibold">
                {g.title}
                <span className="t-mono text-[12px] font-normal text-muted">{d.counts[g.key]}</span>
                <span className="text-[12px] font-normal text-muted">{g.hint}</span>
              </h4>
              {d.groups[g.key].length === 0 ? (
                <p className="m-0 text-[13px] text-muted">Nic w tej grupie.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                  {d.groups[g.key].map((l) => (
                    <Line key={l.key} l={l} />
                  ))}
                </ul>
              )}
            </div>
          ))}
          {rerunText(d.analyses_to_rerun) ? (
            <p className="m-0 text-[13px] text-attention-text">{rerunText(d.analyses_to_rerun)}</p>
          ) : null}
          {isExpert && d.review_items.length > 0 ? (
            <p className="m-0 text-[13px] text-text-secondary">
              {d.review_items.filter((i) => i.status === 'open').length} z {d.review_items.length} spraw czeka
              w Przeglądzie.
            </p>
          ) : null}
        </section>
      )}
    </DataState>
  )
}

/** The "new document" panel: sensitivity, processing steps, extracted facts with verified quotes, "Co się zmieniło", review links. */
export function AnalysisPanel({ documentId }: { documentId: number }) {
  const q = useQuery(documentAnalysisQuery(documentId))
  const { isExpert, readOnly } = useSession()
  const link = useLinkDocument(documentId)
  return (
    <DataState query={q}>
      {(a) => {
        const extracted = a.steps.find((s) => s.key === 'extraction')?.state === 'done'
        const linked = a.steps.find((s) => s.key === 'linking')?.state === 'done'
        const items = reviewLinks(a, isExpert)
        return (
          <section aria-label="Analiza dokumentu" className="flex flex-col gap-4 rounded-panel bg-soft p-5">
            <header className="flex flex-col gap-1">
              <span className="t-eyebrow text-muted">
                {a.document.doc_kind_label ?? 'dokument'}, {sensitivityLabel(a.document.sensitivity)}
                {a.document.doc_date ? `, ${fmtDate(a.document.doc_date)}` : ''}
              </span>
              <h2 className="t-h3 m-0">{a.document.title ?? a.document.filename}</h2>
              <p className="m-0 text-[13px] text-text-body-muted" aria-live="polite">
                {stepsSummary(a.steps)}
              </p>
            </header>
            {a.growth?.sentence ? (
              <p
                className="m-0 rounded-item bg-surface px-3.5 py-2.5 text-[14px] font-medium"
                data-testid="growth"
              >
                {a.growth.sentence}
              </p>
            ) : null}
            <ProcessingSteps steps={a.steps} />
            {extracted && !linked && isExpert ? (
              <Button
                size="lg"
                disabled={link.isPending || readOnly}
                title={readOnly ? READ_ONLY_REASON : undefined}
                onClick={() => link.mutate(undefined, { onError: (e) => toast.error(uploadErrorMessage(e)) })}
              >
                {link.isPending ? 'Powiązujemy…' : 'Powiąż z projektem'}
              </Button>
            ) : null}
            {a.link?.checks?.some((c) => !c.ok) ? (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {a.link.checks
                  .filter((c) => !c.ok)
                  .map((c) => (
                    <li
                      key={`${c.kind}-${c.value}`}
                      role="alert"
                      className="rounded-item border border-dashed border-attention bg-attention-soft px-3.5 py-2.5 text-[14px] text-attention-text"
                    >
                      {c.kind.toUpperCase()} {c.value}: {c.detail}
                      {c.expected ? `. W rejestrze: ${c.expected}.` : '.'}
                    </li>
                  ))}
              </ul>
            ) : null}
            <Facts a={a} />
            {linked && a.project_rm_id ? (
              <ChangesSince rmId={a.project_rm_id} documentId={documentId} />
            ) : null}
            {items.length > 0 ? (
              <section aria-labelledby="sprawy-z-dokumentu" className="flex flex-col gap-1.5">
                <h3 id="sprawy-z-dokumentu" className="t-h3 m-0">
                  Sprawy do przeglądu
                </h3>
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                  {items.map((i) => (
                    <li key={i.id}>
                      <Link
                        to={'/przeglad' as never}
                        search={{ sprawa: i.id } as never}
                        className="flex items-center justify-between gap-2 rounded-item bg-surface px-3.5 py-2.5 text-[14px] no-underline hover:bg-soft-2"
                      >
                        <span>{i.title}</span>
                        <span
                          className={cn(
                            't-mono text-[12px]',
                            i.status === 'open' ? 'text-attention-text' : 'text-muted',
                          )}
                        >
                          {i.status === 'open' ? 'do przeglądu' : 'rozstrzygnięte'}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </section>
        )
      }}
    </DataState>
  )
}
