import { useSuspenseQuery } from '@tanstack/react-query'
import { AlertTriangle, Download } from 'lucide-react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import { useState } from 'react'
import { toast } from 'sonner'
import type { AllocationRisk, Position } from '@/api/contracts/allocation'
import { Panel, TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { EmptyState } from '@/components/common/DataState'
import { ProvenanceTag } from '@/components/common/ProvenanceTag'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { env } from '@/config/env'
import { useFeatures } from '@/config/features'
import { cn } from '@/lib/cn'
import { downloadFile } from '@/lib/download'
import { AnalysisHeader } from '../simulation/AnalysisHeader'
import { type AllocationResponse, allocationQuery, useAllocationChoices } from './api'
import { type Balance, balance, balanceAria, balanceNote, fmtTpln, WHO } from './balance'

export function AllocationScreen({ id }: { id: string }) {
  const { data } = useSuspenseQuery(allocationQuery(id))
  return (
    <div className="flex flex-col gap-7">
      <AnalysisHeader id={id} title="Kto ponosi które ryzyko" />
      <AllocationBody id={id} data={data} />
    </div>
  )
}

export function AllocationBody({ id, data }: { id: string; data: AllocationResponse }) {
  const { choices, choose, saving } = useAllocationChoices(id, data)
  const b = balance(data.risks, choices, data.premium)
  return (
    <TwoCol
      main={
        data.risks.length === 0 ? (
          <EmptyState>Analiza nie wskazała ryzyk do podziału.</EmptyState>
        ) : (
          <>
            <BalanceSection b={b} attention={data.premium_attention_tpln} saving={saving} />
            <RiskMatrix risks={data.risks} choices={choices} onChoose={choose} />
            {(data.limitations ?? []).map((l) => (
              <p key={l} className="t-caption m-0 text-muted">
                {l}
              </p>
            ))}
          </>
        )
      }
      aside={<PackPanel id={id} data={data} />}
    />
  )
}

function BalanceSection({ b, attention, saving }: { b: Balance; attention: number; saving: boolean }) {
  const total = b.segments.buyer + b.segments.shared + b.segments.contractor || 1
  const segs = [
    { k: 'buyer', v: b.segments.buyer, c: 'bg-ink' },
    { k: 'shared', v: b.segments.shared, c: 'bg-[#D4D4D4]' },
    { k: 'contractor', v: b.segments.contractor, c: 'bg-attention' },
  ].filter((s) => s.v > 0)
  const legend = [
    { l: 'Po stronie zamawiającego', v: fmtTpln(b.buyer), dot: 'bg-ink', warn: false },
    { l: 'Po stronie wykonawcy', v: fmtTpln(b.contractor), dot: 'bg-attention', warn: false },
    {
      l: 'Doliczą w ofertach',
      v: `+${fmtTpln(b.premium)}`,
      dot: 'bg-attention-soft border border-attention',
      warn: b.premium > attention,
    },
  ]
  return (
    <section aria-labelledby="bal" className="flex flex-col gap-3 rounded-panel border border-divider p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="bal" className="t-h3 m-0">
          Bilans Twojego podziału
        </h2>
        <span className="t-caption text-muted">
          {saving ? 'Zapisujemy…' : 'szacunek, oczekiwany koszt ryzyk'}
        </span>
      </div>
      <div
        role="img"
        aria-label={balanceAria(b)}
        className="flex h-4 w-full overflow-hidden rounded-pill bg-soft"
        data-testid="balance-bar"
      >
        {segs.map((s) => (
          <span key={s.k} className={cn('h-full', s.c)} style={{ width: `${(s.v / total) * 100}%` }} />
        ))}
      </div>
      <div className="flex flex-col gap-1.5">
        {legend.map((k) => (
          <div key={k.l} className="flex items-center justify-between gap-3">
            <span className="t-small flex items-center gap-2">
              <span aria-hidden className={cn('size-2.5 rounded-pill', k.dot)} />
              {k.l}
            </span>
            <span className={cn('t-item', k.warn && 'text-attention-text')} data-testid={`legend-${k.l}`}>
              {k.v}
            </span>
          </div>
        ))}
      </div>
      <p className="t-small m-0 text-text-body-muted" data-testid="balance-note">
        {balanceNote(b.off)}
      </p>
      <ProvenanceTag
        origin="CALC"
        text="koszt ryzyk z podobnych umów; premie i koszt opóźnienia to założenia eksperta"
      />
    </section>
  )
}

function RiskMatrix({
  risks,
  choices,
  onChoose,
}: {
  risks: AllocationRisk[]
  choices: Record<string, Position>
  onChoose: (code: string, p: Position) => void
}) {
  return (
    <section aria-label="Ryzyka" className="flex flex-col">
      <div className="t-caption grid grid-cols-[minmax(0,1fr)_240px] gap-3 border-b border-divider px-1 pb-2 text-muted">
        <span>ryzyko i skutek</span>
        <span className="grid grid-cols-3 text-center">
          {WHO.map((w) => (
            <span key={w}>{w}</span>
          ))}
        </span>
      </div>
      {risks.map((r) => (
        <RiskRow
          key={r.code}
          r={r}
          chosen={choices[r.code] ?? r.recommended}
          onChoose={(p) => onChoose(r.code, p)}
        />
      ))}
    </section>
  )
}

function RiskRow({
  r,
  chosen,
  onChoose,
}: {
  r: AllocationRisk
  chosen: Position
  onChoose: (p: Position) => void
}) {
  const off = chosen !== r.recommended
  return (
    <div className="flex flex-col gap-2 border-b border-divider px-1 py-3.5" data-testid={`risk-${r.code}`}>
      <div className="grid grid-cols-[minmax(0,1fr)_240px] items-center gap-3">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-item">
            <span className="t-mono mr-2 text-muted">{r.code}</span>
            {r.title}
          </span>
          <span className="t-caption text-text-body-muted">
            jeśli się zdarzy: {r.impact_label}, oczekiwany koszt {fmtTpln(r.expected_cost_tpln)}
          </span>
        </span>
        <RadioGroupPrimitive.Root
          aria-label={`Kto ponosi: ${r.title}`}
          value={String(chosen)}
          onValueChange={(v) => onChoose(Number(v) as Position)}
          className="relative grid grid-cols-3"
        >
          <span aria-hidden className="absolute top-[9px] right-[16%] left-[16%] h-px bg-border" />
          {WHO.map((w, i) => (
            <span key={w} className="relative flex flex-col items-center gap-1">
              <RadioGroupPrimitive.Item
                value={String(i)}
                aria-label={w}
                className={cn(
                  'relative size-[18px] rounded-pill border-2 bg-surface outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink',
                  chosen === i ? 'border-ink bg-ink' : 'border-border hover:border-text-muted',
                )}
              />
              {r.recommended === i ? <span className="t-mono text-[10px] text-muted">zalecane</span> : null}
            </span>
          ))}
        </RadioGroupPrimitive.Root>
      </div>
      <div className="t-small text-text-body-muted">
        <span className="text-muted">jak: </span>
        {r.how[chosen]}
      </div>
      {off ? (
        <div
          className="t-small flex items-start gap-2 rounded-item bg-attention-soft px-3 py-2 text-attention-text"
          role="note"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {r.warning}
            {r.cases?.length ? (
              <>
                {' '}
                {r.cases.map((c) => (
                  <a key={c.href} href={c.href} className="underline underline-offset-2">
                    {c.label}
                  </a>
                ))}
              </>
            ) : null}
          </span>
        </div>
      ) : null}
    </div>
  )
}

const FORMAT_LABEL = { docx: 'Pobierz DOCX', pdf: 'PDF', csv: 'CSV', json: 'JSON' } as const

function PackPanel({ id, data }: { id: string; data: AllocationResponse }) {
  const f = useFeatures()
  const session = useSession()
  const [included, setIncluded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(data.pack.items.map((i) => [i.key, i.included])),
  )
  const [busy, setBusy] = useState<string | null>(null)
  const items = data.pack.items.filter((i) => included[i.key]).map((i) => i.key)
  const download = async (fmt: (typeof data.pack.formats)[number]) => {
    setBusy(fmt)
    try {
      const qs = items.length ? `?items=${items.join(',')}` : ''
      await downloadFile(
        `${env.apiBase}/api/analyses/${encodeURIComponent(id)}/pack.${fmt}${qs}`,
        `${id}_pakiet.${fmt}`,
      )
    } catch {
      toast.error('Nie udało się przygotować pliku. Spróbuj ponownie.')
    } finally {
      setBusy(null)
    }
  }
  const pending = data.pack.pending_ai
  const isExpert = session.isExpert
  return (
    <Panel aria-labelledby="pk">
      <div className="flex flex-col gap-0.5">
        <h2 id="pk" className="t-h3 m-0">
          Pakiet do akt postępowania
        </h2>
        <span className="t-caption text-muted">jeden plik, gotowy do dołączenia</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {data.pack.items.map((i) => (
          <label
            key={i.key}
            htmlFor={`pk-${i.key}`}
            className="flex cursor-pointer items-center gap-3 rounded-item bg-surface px-3.5 py-2.5"
          >
            <Checkbox
              id={`pk-${i.key}`}
              checked={!!included[i.key]}
              onCheckedChange={(v) => setIncluded((p) => ({ ...p, [i.key]: v === true }))}
            />
            <span className="t-small flex-1">{i.title}</span>
            <span className="t-mono text-muted">{i.note}</span>
          </label>
        ))}
      </div>
      {pending > 0 ? (
        isExpert ? (
          <a
            href={`/przeglad?analiza=${encodeURIComponent(id)}`}
            className="t-small flex items-center gap-2 text-attention-text"
          >
            <span aria-hidden className="size-2 rounded-pill border border-dashed border-prov-ai" />
            {pending}{' '}
            {pending === 1 ? 'wniosek AI czeka' : pending < 5 ? 'wnioski AI czekają' : 'wniosków AI czeka'} na
            przegląd. Do pakietu trafią tylko zatwierdzone.
          </a>
        ) : (
          <p className="t-small m-0 text-attention-text">
            {pending}{' '}
            {pending === 1 ? 'wniosek AI czeka' : pending < 5 ? 'wnioski AI czekają' : 'wniosków AI czeka'} na
            przegląd. Do pakietu trafią tylko zatwierdzone.
          </p>
        )
      ) : null}
      {f.pack_export ? (
        <div className="flex flex-wrap gap-2" data-testid="export-buttons">
          {data.pack.formats.map((fmt, i) => (
            <Button
              key={fmt}
              variant={i === 0 ? 'default' : 'outline'}
              size={i === 0 ? 'lg' : 'default'}
              disabled={busy !== null}
              aria-busy={busy === fmt}
              onClick={() => void download(fmt)}
            >
              {i === 0 ? <Download aria-hidden /> : null}
              {busy === fmt ? 'Przygotowujemy plik…' : FORMAT_LABEL[fmt]}
            </Button>
          ))}
        </div>
      ) : null}
    </Panel>
  )
}
