import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Check, Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import type { ClauseHint, ReportFlag } from '@/api/contracts/analyses'
import { Panel, TwoCol } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { ProvenanceTag } from '@/components/common/ProvenanceTag'
import { SummaryCard, SummaryCardSkeleton } from '@/components/common/SummaryCard'
import { Button } from '@/components/ui/button'
import { useFeatures } from '@/config/features'
import { cn } from '@/lib/cn'
import { fmtInt, fmtScore } from '@/lib/format'
import { plural } from '@/lib/plural'
import { addClauseToPack, reportQuery, runAnalysis } from './api'
import {
  ANSWER_TONE,
  cardHref,
  caseCost,
  caseDelay,
  caseHref,
  flagDot,
  flagHref,
  funnelWidth,
  groupFlags,
  keyDisplay,
  type Report,
  type ReportCase,
  type ReportQuestion,
  rangeGeometry,
  SIM_COLOR,
  SIM_LABEL,
  similaritySegments,
  sortFlags,
  staleCasesText,
} from './logic'

/** 1.2 Raport. `chat` is the slot for the analysis chat ("Zapytaj o tę analizę", session F1). */
export function ReportScreen({ id, chat }: { id: string; chat?: ReactNode }) {
  const { data } = useSuspenseQuery(reportQuery(id))
  return <ReportBody id={id} r={data} chat={chat} />
}

export function ReportBody({ id, r, chat }: { id: string; r: Report; chat?: ReactNode }) {
  const flags = useFeatures()
  if (r.status === 'running') {
    return (
      <div className="flex flex-col gap-7">
        <SummaryCardSkeleton note="Liczymy: grupa porównawcza, podobne przypadki, zapisy w PFU…" />
      </div>
    )
  }
  if (r.status === 'draft' || r.status === 'error' || !r.summary) {
    return <NotRun id={id} r={r} />
  }
  return (
    <div className="flex flex-col gap-7">
      {r.reference_class?.sector && r.reference_class.sector !== 'wod-kan' ? (
        <span
          className="t-mono rounded-chip bg-prov-ai-soft px-2 py-0.5 text-prov-ai"
          data-testid="sector-badge"
        >
          sektor: {r.reference_class.sector_label ?? r.reference_class.sector}
          {r.reference_class.sector_status === 'proposed' ? ', pakiet do zatwierdzenia' : ''}
        </span>
      ) : null}
      <SummaryCard eyebrow="W skrócie" sentence={r.summary.text} provenance={r.summary.provenance} />
      {r.stale_cases?.length ? <RerunBanner id={id} text={staleCasesText(r.stale_cases)} /> : null}
      {r.stale_sections?.length ? (
        <RerunBanner id={id} text="Założenia zmieniły się po ostatnim obliczeniu. Policz raport ponownie." />
      ) : null}
      <div className="grid gap-3 md:grid-cols-3" data-testid="question-cards">
        {(r.questions as ReportQuestion[])
          .filter((q) => q.key !== 'budget' || flags.unit_cost)
          .map((q) => (
            <QuestionCardView key={q.key} id={id} q={q} />
          ))}
      </div>
      <TwoCol
        main={
          <>
            <FlagList id={id} flags={r.flags} firstDoc={r.documents?.[0]?.document_id} />
            {chat ?? null}
            <Details r={r} />
          </>
        }
        aside={
          <>
            <CaseList cases={r.similar_cases} />
            <ClauseList id={id} clauses={r.clauses} />
          </>
        }
      />
    </div>
  )
}

function NotRun({ id, r }: { id: string; r: Report }) {
  return (
    <div className="flex flex-col gap-5">
      <EmptyState>
        {r.status === 'error'
          ? `Nie udało się policzyć raportu${r.error ? `: ${r.error}` : '.'}`
          : 'Raport nie został jeszcze policzony dla tych założeń.'}
      </EmptyState>
      <RerunBanner
        id={id}
        text="Uruchom analizę, żeby zobaczyć grupę porównawczą, szanse i podobne przypadki."
      />
    </div>
  )
}

function RerunBanner({ id, text }: { id: string; text: string }) {
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: () => runAnalysis(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analysis', id] }),
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Tylko autor analizy może ją przeliczyć.'
          : 'Nie udało się uruchomić analizy.',
      ),
  })
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-item bg-attention-soft px-4 py-3">
      <span className="t-small text-attention-text">{text}</span>
      <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending} aria-busy={run.isPending}>
        {run.isPending ? 'Liczymy…' : 'Uruchom analizę'}
      </Button>
    </div>
  )
}

// ---- question cards ----------------------------------------------------------------------------------------------

export function QuestionCardView({ id, q }: { id: string; q: ReportQuestion }) {
  const g = rangeGeometry(q)
  return (
    <a
      href={cardHref(id, q)}
      className="flex flex-col gap-3 rounded-card bg-soft p-5 text-text no-underline hover:bg-soft-2"
      data-testid={`q-${q.key}`}
    >
      <span className="t-small font-medium text-text-secondary">{q.question}</span>
      <span className="flex flex-wrap items-baseline gap-2">
        <span className={cn('t-h2', ANSWER_TONE[q.tone])}>{q.answer}</span>
        <span className="t-mono text-text-body-muted">{keyDisplay(q)}</span>
      </span>
      {q.insufficient ? (
        <span className="t-caption text-muted">{q.missing ?? `za mało danych (n = ${fmtInt(q.n)})`}</span>
      ) : (
        <RangeBar g={g} q={q} />
      )}
      <ProvenanceTag
        origin={q.provenance.origin}
        reviewStatus={q.provenance.review_status}
        text={q.provenance.text.replace(/^obliczenie, /, '')}
      />
    </a>
  )
}

export function RangeBar({ g, q }: { g: ReturnType<typeof rangeGeometry>; q: ReportQuestion }) {
  return (
    <div role="img" aria-label={q.aria} className="flex flex-col gap-1">
      <div className="relative h-11">
        <div className="absolute top-[18px] right-0 left-0 h-2 rounded-pill bg-[var(--chart-band-p10-p90)]" />
        {g.band ? (
          <div
            className="absolute top-[18px] h-2 rounded-pill bg-[var(--chart-p50)]"
            style={{ left: `${g.band.left}%`, width: `${g.band.width}%` }}
            data-testid="range-band"
          />
        ) : null}
        {g.median !== null ? (
          <div
            className="absolute top-[16px] h-3 w-[3px] -translate-x-1/2 rounded-pill bg-surface"
            style={{ left: `${g.median}%` }}
          />
        ) : null}
        {g.programme !== null ? (
          <div
            className="absolute top-[12px] h-5 w-[3px] -translate-x-1/2 rounded-pill bg-attention"
            style={{ left: `${g.programme}%` }}
            title="koniec programu"
            data-testid="range-programme"
          />
        ) : null}
        {g.you !== null ? (
          <div
            className="absolute top-0 flex -translate-x-1/2 flex-col items-center"
            style={{ left: `${g.you}%` }}
            data-testid="range-you"
          >
            <span className="t-mono text-[10px] text-ink">Ty</span>
            <span className="h-5 w-[3px] rounded-pill bg-ink" />
          </div>
        ) : null}
      </div>
      <div className="t-mono flex justify-between text-muted">
        <span>{q.scale.lo_label}</span>
        {q.band ? <span>{q.band.caption}</span> : null}
        <span>{q.scale.hi_label}</span>
      </div>
    </div>
  )
}

// ---- flags -------------------------------------------------------------------------------------------------------

/** A2 marker: calculation = teal ring, AI to review = attention ring, AI approved = ink check. */
function FlagDotView({ f }: { f: ReportFlag }) {
  const d = flagDot(f)
  return (
    <span
      aria-hidden
      className={cn(
        'mt-px flex size-5.5 shrink-0 items-center justify-center rounded-pill',
        d === 'calc' && 'border-2 border-prov-calc',
        d === 'ai-approved' && 'bg-ink text-on-ink',
        d === 'ai-proposed' && 'border-2 border-attention',
      )}
    >
      {d === 'ai-approved' ? (
        <Check className="size-3" />
      ) : (
        <span className={cn('size-2 rounded-pill', d === 'calc' ? 'bg-prov-calc' : 'bg-attention')} />
      )}
    </span>
  )
}

export function FlagList({ id, flags, firstDoc }: { id: string; flags: ReportFlag[]; firstDoc?: number }) {
  const f = useFeatures()
  const list = groupFlags(sortFlags(flags))
  return (
    <section aria-labelledby="r1" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="r1" className="t-h3 m-0">
          Na co uważać przed przetargiem
        </h2>
        {firstDoc && f.red_pen ? (
          <a
            href={`/analizy/${encodeURIComponent(id)}/dokumenty/${firstDoc}`}
            className="t-small text-text underline underline-offset-4"
          >
            Pokaż w dokumentach →
          </a>
        ) : null}
      </div>
      {list.length === 0 ? (
        <EmptyState>Nie znaleźliśmy sygnałów ryzyka w opisie i dokumentach.</EmptyState>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0" data-testid="flags">
          {list.map((fl) => {
            const href = f.red_pen ? flagHref(id, fl) : null
            const body = (
              <>
                <FlagDotView f={fl} />
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="t-item">{fl.title}</span>
                  <span className="t-small text-text-body-muted">{fl.text}</span>
                  <span className="t-mono text-muted">
                    {fl.meta}
                    {fl.origin === 'AI' && fl.review_status === 'proposed' ? ', niezweryfikowane' : ''}
                  </span>
                </span>
              </>
            )
            return (
              <li key={fl.id}>
                {href ? (
                  <a
                    href={href}
                    className="flex items-start gap-3.5 rounded-item border border-divider px-3.5 py-3 text-text no-underline hover:bg-soft"
                  >
                    {body}
                  </a>
                ) : (
                  <div className="flex items-start gap-3.5 rounded-item border border-divider px-3.5 py-3">
                    {body}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// ---- similar cases -----------------------------------------------------------------------------------------------

export function SimilarityBar({ c }: { c: ReportCase }) {
  const segs = similaritySegments(c)
  const legend = segs.map((s) => `${s.label} ${fmtScore(s.pct / 100)}`).join(', ')
  return (
    <span
      className="flex h-1.5 w-full overflow-hidden rounded-pill bg-soft-2"
      role="img"
      aria-label={`Podobieństwo ${fmtScore(c.score)}: ${legend}`}
      title={legend}
    >
      {segs.map((s) => (
        <span key={s.feature} style={{ width: `${s.pct}%`, background: s.color }} />
      ))}
    </span>
  )
}

export function CaseList({ cases }: { cases: ReportCase[] }) {
  return (
    <Panel aria-labelledby="r2">
      <h2 id="r2" className="t-h3 m-0">
        Podobne przypadki
      </h2>
      {cases.length === 0 ? (
        <EmptyState className="bg-surface">
          Brak podobnych przypadków z zatwierdzonymi zdarzeniami.
        </EmptyState>
      ) : (
        <>
          {cases.map((c) => (
            <a
              key={c.project_id}
              href={caseHref(c)}
              className="flex flex-col gap-1.5 rounded-item bg-surface px-4 py-3 text-text no-underline hover:bg-soft-2"
              data-testid="case-row"
            >
              <span className="flex items-start gap-3">
                <span className="t-mono shrink-0 rounded-chip bg-soft px-1.5 py-0.5">
                  {fmtScore(c.score)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="t-small line-clamp-3 font-medium">{c.title}</span>
                  <span className="t-mono flex flex-wrap gap-x-3">
                    <span className={cn((c.delay_days ?? 0) > 0 && 'text-attention-text')}>
                      {caseDelay(c)}
                    </span>
                    <span className="text-muted">koszt {caseCost(c)}</span>
                  </span>
                  <span className="t-caption text-text-body-muted">{c.why}</span>
                </span>
              </span>
              <SimilarityBar c={c} />
              <span className="flex flex-wrap gap-1.5">
                {c.badge ? (
                  <span className="t-mono rounded-chip bg-prov-case-soft px-1.5 py-0.5 text-prov-case">
                    {c.badge}
                  </span>
                ) : null}
                {(c.risk_overlap ?? []).map((o) => (
                  <span
                    key={o.risk}
                    className="t-mono rounded-chip bg-attention-soft px-1.5 py-0.5 text-attention-text"
                    title={o.text}
                  >
                    sygnał {o.risk} → w tym przypadku też
                  </span>
                ))}
              </span>
            </a>
          ))}
          <span className="t-mono flex flex-wrap gap-x-3 gap-y-1 text-muted">
            {Object.keys(SIM_COLOR).map((k) => (
              <span key={k} className="inline-flex items-center gap-1">
                <span aria-hidden className="size-2 rounded-pill" style={{ background: SIM_COLOR[k] }} />
                {SIM_LABEL[k]}
              </span>
            ))}
          </span>
        </>
      )}
    </Panel>
  )
}

// ---- clauses -----------------------------------------------------------------------------------------------------

export function ClauseList({ id, clauses }: { id: string; clauses: ClauseHint[] }) {
  const qc = useQueryClient()
  const [added, setAdded] = useState<Record<string, boolean>>({})
  const add = useMutation({
    mutationFn: (code: string) => addClauseToPack(id, code),
    onMutate: (code) => setAdded((p) => ({ ...p, [code]: true })),
    onError: (e, code) => {
      setAdded((p) => ({ ...p, [code]: false }))
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Ta analiza jest tylko do odczytu.'
          : 'Nie dodaliśmy zapisu. Spróbuj ponownie.',
      )
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['analysis', id, 'report'] }),
  })
  if (!clauses.length) return null
  return (
    <Panel aria-labelledby="r4">
      <h2 id="r4" className="t-h3 m-0">
        Co dopisać do umowy
      </h2>
      {clauses.map((k) => {
        const inPack = added[k.code] ?? k.in_pack
        return (
          <div
            key={k.code}
            className="flex items-center justify-between gap-3 rounded-item bg-surface px-3.5 py-3"
          >
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="t-item">{k.title}</span>
              <span className="t-caption text-text-body-muted">{k.why}</span>
              <span className="t-mono text-muted">{k.code}</span>
            </span>
            <Button
              size={inPack ? 'sm' : 'icon-sm'}
              variant={inPack ? 'outline' : 'default'}
              aria-pressed={inPack}
              aria-label={inPack ? 'W pakiecie' : 'Dodaj do pakietu'}
              onClick={() => !inPack && add.mutate(k.code)}
            >
              {inPack ? 'W pakiecie' : <Plus aria-hidden />}
            </Button>
          </div>
        )
      })}
    </Panel>
  )
}

// ---- comparison group, limitations, backtest ---------------------------------------------------------------------

function Details({ r }: { r: Report }) {
  const f = useFeatures()
  const rc = r.reference_class
  const nAll = rc?.funnel[0]?.n ?? 0
  return (
    <div className="flex flex-col gap-3">
      {rc ? (
        <details className="rounded-panel border border-divider px-5 py-4" open>
          <summary className="t-item cursor-pointer">
            Grupa porównawcza: {fmtInt(rc.n)} {plural(rc.n, ['umowa', 'umowy', 'umów'])}
          </summary>
          <ol className="m-0 mt-3 flex list-none flex-col gap-2 p-0" data-testid="funnel">
            {rc.funnel.map((f, i) => (
              <li key={f.label} className="flex flex-col gap-1">
                <span className="flex justify-between gap-2">
                  <span className="t-small">{(i ? '+ ' : '') + f.label}</span>
                  <span className="t-mono">{fmtInt(f.n)}</span>
                </span>
                <span
                  className={cn(
                    'h-2 rounded-pill',
                    i === rc.funnel.length - 1 ? 'bg-ink' : 'bg-[var(--chart-p50)]',
                  )}
                  style={{ width: `${funnelWidth(f.n, nAll)}%` }}
                />
              </li>
            ))}
          </ol>
          {rc.widen_note ? <p className="t-caption m-0 mt-2 text-attention-text">{rc.widen_note}</p> : null}
          {rc.reweight_note ? <p className="t-caption m-0 mt-1 text-muted">{rc.reweight_note}</p> : null}
          <div className="mt-2">
            <ProvenanceTag origin="CALC" text="ogłoszenia o wykonaniu umów z BZP" />
          </div>
        </details>
      ) : null}
      {r.backtest_note && f.backtest ? (
        <p
          className="t-small m-0 rounded-item bg-prov-calc-soft px-4 py-3 text-text-secondary"
          data-testid="backtest"
        >
          {r.backtest_note}
        </p>
      ) : null}
      <details className="rounded-panel border border-divider px-5 py-4">
        <summary className="t-item cursor-pointer">Ograniczenia analizy ({r.limitations.length})</summary>
        <ul className="t-small m-0 mt-3 flex flex-col gap-1.5 pl-5 text-text-body-muted">
          {r.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}
