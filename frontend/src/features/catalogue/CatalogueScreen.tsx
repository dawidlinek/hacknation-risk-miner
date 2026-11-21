// biome-ignore-all lint/a11y/noLabelWithoutControl: labels wrap the Input and Slider components Biome cannot see
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import type {
  CatalogueItem,
  CatalogueProposal,
  CatalogueRisk,
  SimilarityWeight,
} from '@/api/contracts/catalogue'
import { Page, PageHeader, TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { EmptyState } from '@/components/common/DataState'
import { FilterPills } from '@/components/common/FilterPills'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Textarea } from '@/components/ui/textarea'
import { useFeature } from '@/config/features'
import { cn } from '@/lib/cn'
import { fmtDateTime } from '@/lib/dates'
import { catalogueQuery, decideProposal, patchRisk, putWeights } from './api'
import { ClausesPanel } from './ClausesPanel'

export type CatalogueTab = 'ryzyka' | 'wersje' | 'podsektory' | 'dokumenty' | 'listy' | 'zapisy'
export const TABS: CatalogueTab[] = ['ryzyka', 'wersje', 'podsektory', 'dokumenty', 'listy', 'zapisy']

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError && e.detail ? e.detail : fallback)

/** Input that saves on blur when its value changed. */
function EditableField({
  label,
  value,
  editable,
  multiline,
  onSave,
}: {
  label: string
  value: string
  editable: boolean
  multiline?: boolean
  onSave: (v: string) => void
}) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  const commit = () => v.trim() && v !== value && onSave(v.trim())
  return (
    <label className="flex flex-col gap-1">
      <span className="t-caption text-muted">{label}</span>
      {!editable ? (
        <span className="text-[14px]">{value}</span>
      ) : multiline ? (
        <Textarea value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} rows={3} />
      ) : (
        <Input value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} className="h-10" />
      )}
    </label>
  )
}

function RiskRow({
  risk,
  editable,
  onSave,
}: {
  risk: CatalogueRisk
  editable: boolean
  onSave: (code: string, patch: { name?: string; description?: string }) => void
}) {
  return (
    <details className="group rounded-item border border-border bg-surface">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
        <span className="t-mono rounded-md bg-soft-2 px-2 py-0.5">{risk.code}</span>
        <span className="t-item min-w-0 flex-1">{risk.title}</span>
        <span className="t-mono text-muted">{risk.counts_label}</span>
        {risk.quality ? (
          <span
            className={cn(
              't-caption rounded-pill px-2.5 py-0.5',
              risk.quality.attention
                ? 'bg-attention-soft text-attention-text'
                : 'bg-soft-2 text-text-secondary',
            )}
          >
            {risk.quality.badge}
          </span>
        ) : null}
        <span className="basis-full text-[13px] text-text-body-muted">{risk.effect}</span>
      </summary>
      <div className="flex flex-col gap-3 border-t border-divider px-4 py-4">
        <EditableField
          label="nazwa ryzyka"
          value={risk.title}
          editable={editable}
          onSave={(name) => onSave(risk.code, { name })}
        />
        <EditableField
          label="skutki"
          value={risk.effect}
          editable={editable}
          multiline
          onSave={(description) => onSave(risk.code, { description })}
        />
        {risk.parts.map((p) => (
          <div key={p.k} className="flex flex-col gap-0.5">
            <span className="t-caption text-muted">{p.k}</span>
            <span className="text-[14px]">{p.v}</span>
          </div>
        ))}
        {risk.quality ? (
          <div
            className={cn(
              'flex flex-col gap-2 rounded-inner px-4 py-3 text-[14px]',
              risk.quality.attention ? 'bg-attention-soft' : 'bg-soft',
            )}
          >
            <span>{risk.quality.detail}</span>
            {risk.quality.review ? (
              <Link
                to="/przeglad"
                search={risk.quality.review as never}
                className={cn('font-medium', risk.quality.attention && 'text-attention-text')}
              >
                Przejrzyj propozycje {risk.code} →
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>
    </details>
  )
}

function ProposalCard({
  p,
  riskCodes,
  editable,
}: {
  p: CatalogueProposal
  riskCodes: string[]
  editable: boolean
}) {
  const qc = useQueryClient()
  const [target, setTarget] = useState(p.merge_target ?? riskCodes[0] ?? '')
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const m = useMutation({
    mutationFn: (b: Parameters<typeof decideProposal>[1]) => decideProposal(p.id, b),
    onSuccess: () => {
      toast.success('Zapisano decyzję. Katalog ma nową wersję.')
      void qc.invalidateQueries({ queryKey: ['catalogue'] })
      void qc.invalidateQueries({ queryKey: ['review'] })
    },
    onError: (e) => toast.error(errMsg(e, 'Nie zapisaliśmy decyzji.')),
  })
  return (
    <div className="flex flex-col gap-2 rounded-item bg-surface px-4 py-3.5">
      <span className="t-item">{p.title}</span>
      {p.detail ? <span className="text-[14px] text-text-body-muted">{p.detail}</span> : null}
      {p.source_label ? <span className="t-mono text-muted">{p.source_label}</span> : null}
      {editable ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={m.isPending} onClick={() => m.mutate({ action: 'approve' })}>
            Dodaj
          </Button>
          <span className="inline-flex items-center gap-1.5">
            <select
              aria-label="Z którym ryzykiem połączyć"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="h-8 rounded-pill border border-border bg-surface px-2.5 text-[13px]"
            >
              {riskCodes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={m.isPending || !target}
              onClick={() => m.mutate({ action: 'merge', merge_into: target })}
            >
              Połącz z {target}
            </Button>
          </span>
          <Button size="sm" variant="ghost" onClick={() => setRejecting((r) => !r)}>
            Odrzuć
          </Button>
        </div>
      ) : null}
      {rejecting ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Powód odrzucenia (wymagany)"
            className="h-9 min-w-[220px] flex-1"
            aria-label="Powód odrzucenia"
          />
          <Button
            size="sm"
            variant="destructive"
            disabled={!reason.trim() || m.isPending}
            onClick={() => m.mutate({ action: 'reject', reason: reason.trim() })}
          >
            Potwierdź odrzucenie
          </Button>
        </div>
      ) : null}
      {p.review_item_id ? (
        <Link
          to="/przeglad"
          search={{ sprawa: p.review_item_id } as never}
          className="t-caption text-text-secondary hover:underline"
        >
          Otwórz w Przeglądzie
        </Link>
      ) : null}
    </div>
  )
}

/** Five tunable similarity weights, 0 to 40 percent. Saved on slider release. */
function WeightSliders({ weights, editable }: { weights: SimilarityWeight[]; editable: boolean }) {
  const qc = useQueryClient()
  const main = weights.filter((w) => w.main)
  const [vals, setVals] = useState<Record<string, number>>(() =>
    Object.fromEntries(main.map((w) => [w.key, w.value])),
  )
  useEffect(
    () => setVals(Object.fromEntries(weights.filter((w) => w.main).map((w) => [w.key, w.value]))),
    [weights],
  )
  const m = useMutation({
    mutationFn: (v: Record<string, number>) => putWeights(v),
    onSuccess: () => {
      toast.success('Wagi zapisane. Katalog ma nową wersję.')
      void qc.invalidateQueries({ queryKey: ['catalogue'] })
      void qc.invalidateQueries({ queryKey: ['project'] })
    },
    onError: (e) => toast.error(errMsg(e, 'Nie zapisaliśmy wag.')),
  })
  return (
    <section className="flex flex-col gap-3 rounded-panel bg-soft p-5" aria-labelledby="wagi-h">
      <h2 id="wagi-h" className="t-h3 m-0">
        Wagi podobieństwa
      </h2>
      <p className="m-0 text-[14px] text-text-body-muted">Co decyduje, że dwie inwestycje są „podobne”.</p>
      {main.map((w) => (
        <label key={w.key} className="flex flex-col gap-1.5">
          <span className="flex items-baseline justify-between text-[14px]">
            {w.label}
            <span className="t-mono">{vals[w.key] ?? w.value}</span>
          </span>
          <Slider
            min={0}
            max={40}
            step={1}
            value={[vals[w.key] ?? w.value]}
            disabled={!editable || m.isPending}
            onValueChange={([x]) => setVals((v) => ({ ...v, [w.key]: x }))}
            onValueCommit={() => m.mutate(vals)}
            aria-label={`Waga: ${w.label}`}
          />
        </label>
      ))}
      <p className="t-caption m-0 text-muted">
        {m.isPending
          ? 'Przeliczamy podobne przypadki…'
          : 'założenie eksperta, zmiana przelicza podobne przypadki'}
      </p>
    </section>
  )
}

// phase codes of the sector pack (doc_types.yaml, checklist.yaml) shown in plain Polish
const PHASE: Record<string, string> = {
  przygotowanie: 'przygotowanie',
  postepowanie: 'postępowanie',
  realizacja: 'realizacja',
  odbior: 'odbiór',
  ewaluacja: 'ewaluacja',
  'WOD-PREP': 'przygotowanie inwestycji wodociągowej',
}

function ItemList({ items, empty }: { items: CatalogueItem[]; empty: string }) {
  if (items.length === 0) return <EmptyState>{empty}</EmptyState>
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
      {items.map((i) => (
        <li
          key={`${i.code}-${i.name}`}
          className="flex flex-wrap items-baseline gap-3 rounded-item bg-surface px-4 py-2.5"
        >
          <span className="t-mono rounded-md bg-soft-2 px-2 py-0.5">{i.code}</span>
          <span className="min-w-0 flex-1 text-[14px]">{i.name}</span>
          {i.detail ? <span className="t-caption text-muted">{PHASE[i.detail] ?? i.detail}</span> : null}
        </li>
      ))}
    </ul>
  )
}

export function CatalogueScreen({ tab, onTab }: { tab: CatalogueTab; onTab: (t: CatalogueTab) => void }) {
  const { data } = useSuspenseQuery(catalogueQuery)
  const qc = useQueryClient()
  const { readOnly } = useSession()
  const editable = useFeature('catalogue_edit') && !readOnly
  const save = useMutation({
    mutationFn: ({ code, patch }: { code: string; patch: { name?: string; description?: string } }) =>
      patchRisk(code, patch),
    onSuccess: (r) => {
      toast.success(`Zapisano w wersji ${r.catalogue_version}`)
      void qc.invalidateQueries({ queryKey: ['catalogue'] })
    },
    onError: (e) => toast.error(errMsg(e, 'Nie zapisaliśmy zmiany.')),
  })
  const when = data.updated_at ? fmtDateTime(data.updated_at) : ''
  const labels: Record<CatalogueTab, string> = {
    ryzyka: `Ryzyka ${data.risks[0]?.code ?? ''}–${data.risks.at(-1)?.code ?? ''}`,
    wersje: 'Wersje',
    podsektory: 'Podsektory',
    dokumenty: 'Dokumenty w fazach',
    listy: 'Listy kontrolne',
    zapisy: 'Zapisy umowne',
  }
  return (
    <Page>
      <PageHeader
        eyebrow={
          <span className="t-mono">{`wersja ${data.version.replace(/^v/, '')}${when ? `, ${when}` : ''}`}</span>
        }
        title="Katalog wiedzy"
      />
      <FilterPills
        label="Części katalogu"
        value={tab}
        onChange={onTab}
        options={TABS.map((t) => ({ value: t, label: labels[t] }))}
      />
      {tab === 'ryzyka' ? (
        <TwoCol
          main={
            <div className="flex flex-col gap-2">
              {data.risks.map((r) => (
                <RiskRow
                  key={r.code}
                  risk={r}
                  editable={editable}
                  onSave={(code, patch) => save.mutate({ code, patch })}
                />
              ))}
            </div>
          }
          aside={
            <>
              <section className="flex flex-col gap-2 rounded-panel bg-soft p-5" aria-labelledby="prop-h">
                <h2 id="prop-h" className="t-h3 m-0">
                  Propozycje modelu
                </h2>
                {data.proposals.length === 0 ? (
                  <p className="t-caption m-0 text-muted">Brak propozycji do rozstrzygnięcia.</p>
                ) : (
                  data.proposals.map((p) => (
                    <ProposalCard
                      key={p.id}
                      p={p}
                      riskCodes={data.risks.map((r) => r.code)}
                      editable={editable}
                    />
                  ))
                )}
              </section>
              <WeightSliders weights={data.weights} editable={editable} />
            </>
          }
        />
      ) : null}
      {tab === 'wersje' ? (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {data.versions.map((v) => (
            <li
              key={v.label}
              className="flex flex-wrap items-baseline justify-between gap-3 rounded-item bg-surface px-4 py-2.5"
            >
              <span className="text-[14px]">
                <span className="t-mono mr-2">{v.label}</span>
                {v.summary}
              </span>
              <span className="t-mono text-muted">{v.who}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {tab === 'podsektory' ? <ItemList items={data.subsectors} empty="Brak podsektorów." /> : null}
      {tab === 'dokumenty' ? <ItemList items={data.doc_types} empty="Brak typów dokumentów." /> : null}
      {tab === 'listy' ? <ItemList items={data.checklists} empty="Brak list kontrolnych." /> : null}
      {tab === 'zapisy' ? <ClausesPanel /> : null}
      {!editable ? (
        <p className="t-caption m-0 text-muted">
          {readOnly
            ? 'Konto tylko do odczytu: edycja katalogu jest zablokowana.'
            : 'Edycja katalogu jest wyłączona. Widok tylko do odczytu.'}
        </p>
      ) : null}
    </Page>
  )
}
