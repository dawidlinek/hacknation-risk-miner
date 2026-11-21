// biome-ignore-all lint/a11y/noLabelWithoutControl: labels wrap Radix and custom controls Biome cannot see
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { KIND_TAB_LABEL } from '@/api/adapters/review'
import { ApiError } from '@/api/client'
import type { DecisionResult, ReviewCard, ReviewKind } from '@/api/contracts/review'
import { Page, PageHeader, TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { EmptyState, SkeletonBlock } from '@/components/common/DataState'
import { QuoteCard } from '@/components/common/QuoteCard'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Kbd } from '@/components/ui/kbd'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { useFeature } from '@/config/features'
import { cn } from '@/lib/cn'
import { decide, reviewCardQuery, reviewCountsQuery, reviewListQuery, skipItem, undoDecision } from './api'
import { resolveHotkey } from './hotkeys'

const KINDS: ReviewKind[] = ['events', 'links', 'discrepancies', 'facts', 'catalogue']

function KindTabs({
  counts,
  active,
  onPick,
}: {
  counts: Record<ReviewKind, number> | undefined
  active: ReviewKind | undefined
  onPick: (k: ReviewKind | undefined) => void
}) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0">
      <legend className="sr-only">Rodzaje spraw do przeglądu</legend>
      {KINDS.map((k) => {
        const on = active === k
        return (
          <button
            key={k}
            type="button"
            aria-pressed={on}
            onClick={() => onPick(on ? undefined : k)}
            className={cn(
              'inline-flex min-h-9.5 items-center gap-2 rounded-pill py-0 pr-2 pl-3.5 text-[14px] font-medium transition-colors',
              on
                ? 'border border-ink bg-ink text-on-ink'
                : 'border border-border bg-surface text-text-secondary hover:bg-soft',
            )}
          >
            {KIND_TAB_LABEL[k]}
            <span
              className={cn(
                't-mono rounded-pill px-1.5',
                on ? 'bg-surface text-text' : 'bg-soft-2 text-text-secondary',
              )}
            >
              {counts ? counts[k] : '…'}
            </span>
          </button>
        )
      })}
    </fieldset>
  )
}

function EffectsPanel({ card, pick, gold }: { card: ReviewCard; pick: number; gold: boolean }) {
  const option = card.options[pick]
  const rows = [...(option?.effects ?? []), ...(gold && card.gold ? [card.gold] : [])]
  return (
    <section className="flex flex-col gap-3 rounded-panel bg-soft p-5" aria-live="polite">
      <h2 className="t-h3 m-0">Co zmieni Twoja odpowiedź</h2>
      {rows.length === 0 ? (
        <p className="m-0 text-[14px] text-text-body-muted">Ta opcja nie zmienia innych danych.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {rows.map((r) => (
            <li
              key={`${r.where}-${r.after}`}
              className="flex flex-col gap-0.5 rounded-item bg-surface px-4 py-2.5"
            >
              <span className="t-caption text-muted">{r.where}</span>
              <span className="text-[13px] text-text-body-muted">{r.before}</span>
              <span className="text-[14px] font-medium">→ {r.after}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="t-caption m-0 text-muted">
        Nic się nie zmienia, dopóki nie klikniesz „Zapisz”. Każdą decyzję możesz cofnąć.
      </p>
    </section>
  )
}

function ReviewItemView({
  card,
  position,
  total,
  length,
  index,
  onDecide,
  onSkip,
  onMove,
}: {
  card: ReviewCard
  position: number
  total: number
  length: number
  index: number
  onDecide: (card: ReviewCard, pick: number, text: string, gold: boolean) => Promise<void>
  onSkip: (card: ReviewCard) => Promise<void>
  onMove: (to: number) => void
}) {
  const learning = useFeature('learning_loop')
  const { readOnly } = useSession()
  const [pick, setPick] = useState(card.default_option)
  const [text, setText] = useState('')
  const [gold, setGold] = useState(false)
  const [opened, setOpened] = useState(false)
  const [busy, setBusy] = useState(false)
  const option = card.options[pick]
  const hasEvidence = card.evidence.hit.length > 0
  const sourceGate = hasEvidence && !card.evidence.verified && option?.decision === 'approve' && !opened
  const textOk = !option?.input?.required || text.trim().length > 0
  const canSave = Boolean(option) && textOk && !sourceGate && !busy && !readOnly
  const showGold = learning && card.gold !== null

  const save = useCallback(async () => {
    if (!canSave) return
    setBusy(true)
    try {
      await onDecide(card, pick, text, gold && showGold)
    } finally {
      setBusy(false)
    }
  }, [canSave, onDecide, card, pick, text, gold, showGold])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const a = resolveHotkey(e, {
        optionCount: card.options.length,
        canSave,
        hasGold: showGold,
        index,
        length,
      })
      if (!a) return
      e.preventDefault()
      if (a.type === 'pick') setPick(a.index)
      else if (a.type === 'save') void save()
      else if (a.type === 'move') onMove(a.to)
      else if (a.type === 'gold') setGold((g) => !g)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [card.options.length, canSave, showGold, index, length, onMove, save])

  return (
    <TwoCol
      main={
        <>
          <div className="flex flex-col gap-2">
            <span className="t-caption flex flex-wrap items-baseline justify-between gap-2 text-muted">
              <span>
                {card.kind_label}
                {card.context.href ? (
                  <>
                    {', '}
                    <Link to={card.context.href as never} className="text-text-secondary hover:underline">
                      {card.context.label}
                    </Link>
                  </>
                ) : null}
              </span>
              <span className="t-mono text-muted">
                {position} z {total}
              </span>
            </span>
            <h2 className="t-h2 m-0" data-review-question>
              {card.question}
            </h2>
            {card.sub ? <p className="m-0 max-w-[720px] text-text-body-muted">{card.sub}</p> : null}
          </div>

          {hasEvidence ? (
            <QuoteCard
              title={card.evidence.title}
              reference={card.evidence.ref}
              referenceUrl={card.evidence.ref_url}
              pre={card.evidence.pre}
              hit={card.evidence.hit}
              post={card.evidence.post}
              chips={[
                ...card.chips,
                ...(card.evidence.verified
                  ? []
                  : [{ text: 'cytat niezweryfikowany', tone: 'warn' as const }]),
              ]}
              onOpenSource={() => setOpened(true)}
            />
          ) : card.chips.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {card.chips.map((c) => (
                <span
                  key={c.text}
                  className={cn(
                    'inline-flex min-h-7.5 items-center rounded-pill px-3 text-[13px]',
                    c.tone === 'ok' && 'bg-success-soft text-success-text',
                    c.tone === 'warn' && 'bg-attention-soft text-attention-text',
                    c.tone === 'neutral' && 'bg-soft-2 text-text',
                  )}
                >
                  {c.text}
                </span>
              ))}
            </div>
          ) : null}

          <RadioGroup
            value={String(pick)}
            onValueChange={(v) => setPick(Number(v))}
            aria-label="Twoja decyzja"
            className="gap-2.5"
          >
            {card.options.map((o, i) => (
              <label
                key={o.key}
                className={cn(
                  'flex cursor-pointer items-center gap-3.5 rounded-item bg-surface',
                  i === pick ? 'border-2 border-ink px-3.75 py-3.25' : 'border border-border px-4 py-3.5',
                )}
              >
                <RadioGroupItem value={String(i)} className="size-5" />
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="t-item flex flex-wrap items-center gap-2">
                    {o.title}
                    {o.badge ? (
                      <span className="t-mono rounded-pill bg-soft-2 px-2 py-0.5 text-muted">{o.badge}</span>
                    ) : null}
                  </span>
                  {o.sub ? (
                    <span
                      className="text-[14px] text-text-body-muted"
                      title={o.sub}
                      style={{
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {o.sub}
                    </span>
                  ) : null}
                </span>
                <Kbd aria-hidden>{i + 1}</Kbd>
              </label>
            ))}
          </RadioGroup>

          {option?.input ? (
            <label className="flex flex-col gap-1.5">
              <span className="t-caption text-muted">{option.input.label}</span>
              <Input
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
                aria-required
                className="h-11"
              />
            </label>
          ) : null}

          {sourceGate ? (
            <p role="note" className="m-0 text-[13px] text-attention-text">
              Cytat nie został potwierdzony w źródle. Otwórz źródło (link powyżej), zanim zatwierdzisz.
            </p>
          ) : null}

          {showGold ? (
            <label className="flex cursor-pointer items-center gap-3 text-[14px]">
              <Checkbox
                checked={gold}
                onCheckedChange={(v) => setGold(v === true)}
                className="size-5.5 rounded-[7px]"
              />
              <span>
                Wzorcowy przykład <Kbd aria-hidden>G</Kbd>
              </span>
            </label>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="xl"
              onClick={save}
              disabled={!canSave}
              title={readOnly ? 'Konto tylko do odczytu' : undefined}
            >
              Zapisz i dalej{' '}
              <Kbd aria-hidden className="bg-on-ink/20 text-on-ink">
                ⏎
              </Kbd>
            </Button>
            <Button variant="outline" size="xl" onClick={() => onSkip(card)} disabled={busy}>
              Pomiń
            </Button>
            <span className="t-caption text-muted">
              1–{Math.max(card.options.length, 1)} wybór, J / K następna / poprzednia
            </span>
          </div>
        </>
      }
      aside={<EffectsPanel card={card} pick={pick} gold={gold && showGold} />}
    />
  )
}

function errMsg(e: unknown, fallback: string) {
  return e instanceof ApiError && e.detail ? e.detail : fallback
}

export function ReviewScreen({
  kind,
  first,
  code,
  onKind,
}: {
  kind: ReviewKind | undefined
  first: number | undefined
  code: string | undefined
  onKind: (k: ReviewKind | undefined) => void
}) {
  const qc = useQueryClient()
  const counts = useQuery(reviewCountsQuery)
  const list = useQuery(reviewListQuery(kind, first, code))
  const [ids, setIds] = useState<number[] | null>(null)
  const [index, setIndex] = useState(0)
  const [learning, setLearning] = useState<DecisionResult['learning']>(null)

  useEffect(() => {
    if (list.data) {
      setIds(list.data.items.map((i) => i.id))
      setIndex(0)
    }
  }, [list.data])

  const currentId = ids?.[index]
  const card = useQuery({ ...reviewCardQuery(currentId ?? 0), enabled: currentId !== undefined })
  // warm the next two cards
  useEffect(() => {
    for (const id of ids?.slice(index + 1, index + 3) ?? []) void qc.prefetchQuery(reviewCardQuery(id))
  }, [ids, index, qc])

  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['review', 'counts'] })
    void qc.invalidateQueries({ queryKey: ['nav', 'counts'] })
    void qc.invalidateQueries({ queryKey: ['project'] })
    void qc.invalidateQueries({ queryKey: ['projects'] })
  }, [qc])

  const removeCurrent = useCallback((id: number) => {
    setIds((prev) => {
      const next = (prev ?? []).filter((x) => x !== id)
      setIndex((i) => Math.min(i, Math.max(next.length - 1, 0)))
      return next
    })
  }, [])

  const onDecide = useCallback(
    async (c: ReviewCard, pick: number, text: string, gold: boolean) => {
      const at = index
      try {
        const r = await decide(c.id, c.options[pick], { text, gold })
        removeCurrent(c.id)
        setLearning(r.learning ?? null)
        toast(r.toast, {
          duration: 9000,
          action: {
            label: 'Cofnij',
            onClick: async () => {
              try {
                await undoDecision(r.undo_token)
                setIds((prev) => {
                  const next = [...(prev ?? [])]
                  next.splice(Math.min(at, next.length), 0, c.id)
                  return next
                })
                setIndex(at)
                setLearning(null)
                refresh()
              } catch (e) {
                toast.error(errMsg(e, 'Nie udało się cofnąć decyzji.'))
              }
            },
          },
        })
        refresh()
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          toast.error(errMsg(e, 'Ta sprawa została już rozstrzygnięta.'))
          removeCurrent(c.id)
        } else {
          toast.error(errMsg(e, 'Nie zapisaliśmy decyzji.'))
        }
      }
    },
    [index, refresh, removeCurrent],
  )

  const onSkip = useCallback(async (c: ReviewCard) => {
    try {
      await skipItem(c.id)
    } catch {
      /* skipping is a local reordering, the backend call is best effort */
    }
    setIds((prev) => [...(prev ?? []).filter((x) => x !== c.id), c.id])
    toast('Pominięto, sprawa wróci na koniec kolejki.')
  }, [])

  const total = useMemo(() => {
    const c = counts.data
    if (!c) return ids?.length ?? 0
    return kind ? c[kind] : Object.values(c).reduce((a, b) => a + b, 0)
  }, [counts.data, kind, ids])

  return (
    <Page>
      <PageHeader
        title="Przegląd"
        lead="Model proponuje, Ty decydujesz. Każda decyzja ma źródło i da się ją cofnąć."
      />
      <KindTabs counts={counts.data} active={kind ?? card.data?.kind} onPick={onKind} />
      {learning ? (
        <div role="status" className="rounded-item bg-soft px-4 py-3 text-[14px] text-text-body-muted">
          {learning.text}
        </div>
      ) : null}
      {list.isPending || (ids !== null && ids.length > 0 && card.isPending) ? (
        <SkeletonBlock className="h-[420px]" />
      ) : list.isError ? (
        <EmptyState>Nie udało się wczytać kolejki. Odśwież stronę za chwilę.</EmptyState>
      ) : ids !== null && ids.length === 0 ? (
        <EmptyState>
          Wszystko przejrzane. Nowe sprawy pojawią się po kolejnym wzbogacaniu.{' '}
          <Link to="/" className="font-medium">
            Wróć do Pulpitu
          </Link>
        </EmptyState>
      ) : card.data ? (
        <ReviewItemView
          key={card.data.id}
          card={card.data}
          position={index + 1}
          total={Math.max(total, ids?.length ?? 0)}
          length={ids?.length ?? 0}
          index={index}
          onDecide={onDecide}
          onSkip={onSkip}
          onMove={setIndex}
        />
      ) : card.isError ? (
        <EmptyState>Nie udało się wczytać tej sprawy. Przejdź do następnej (J).</EmptyState>
      ) : null}
    </Page>
  )
}
