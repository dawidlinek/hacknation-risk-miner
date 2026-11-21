import { ExternalLink, Upload } from 'lucide-react'
import { type DragEvent, useRef, useState } from 'react'
import type { Origin, ReviewStatus } from '@/api/contracts/common'
import { cn } from '@/lib/cn'
import { ACCEPT, validateUpload } from './logic'
import type { DetailField, ExpectedItem, PublicItem } from './types'

const rowCls = (on: boolean, dashed: boolean) =>
  cn(
    'flex w-full items-center gap-3.5 rounded-item px-3.5 py-3 text-left transition-colors',
    on
      ? 'border border-ink bg-soft'
      : dashed
        ? 'border border-dashed border-border bg-surface hover:bg-soft'
        : 'border border-divider bg-surface hover:bg-soft',
  )

export function ExpectedDocRow({
  item,
  selected,
  onPick,
}: {
  item: ExpectedItem
  selected: boolean
  onPick: () => void
}) {
  return (
    <button type="button" aria-pressed={selected} onClick={onPick} className={rowCls(selected, !item.have)}>
      <span
        aria-hidden
        className={cn(
          't-mono flex h-11 w-9 shrink-0 items-center justify-center rounded-[8px] text-[10px] font-semibold text-muted',
          item.have ? 'border border-divider bg-soft' : 'border-[1.5px] border-dashed border-prov-source',
        )}
      >
        {item.ext}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-[15px] font-semibold">{item.title}</span>
        <span className="text-[13px] text-text-body-muted">{item.unlocks}</span>
      </span>
      <span
        className={cn(
          't-mono whitespace-nowrap text-[12px]',
          item.have ? 'text-success-text' : 'text-attention-text',
        )}
      >
        {item.stateLabel}
      </span>
    </button>
  )
}

const STATUS_TONE: Record<ReviewStatus, string> = {
  auto: 'text-muted',
  proposed: 'text-attention-text',
  approved: 'text-success-text',
  edited: 'text-review-edited',
  rejected: 'text-sev-high',
}

export function PublicDocRow({
  item,
  selected,
  onPick,
}: {
  item: PublicItem
  selected: boolean
  onPick: () => void
}) {
  return (
    <button type="button" aria-pressed={selected} onClick={onPick} className={rowCls(selected, false)}>
      <span
        aria-hidden
        className="t-mono flex h-11 w-9 shrink-0 items-center justify-center rounded-[8px] border border-border bg-soft text-[10px] font-semibold text-text-secondary"
      >
        {item.ext}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-[15px] font-semibold">{item.title}</span>
        <span className="t-mono text-[12px] text-muted">
          {item.ref}
          {item.dateLabel ? `, ${item.dateLabel}` : ''}
        </span>
      </span>
      <span className="flex flex-col items-end gap-0.5">
        <span className="t-mono whitespace-nowrap text-[12px]">{item.factsLabel}</span>
        <span className={cn('t-mono whitespace-nowrap text-[11.5px]', STATUS_TONE[item.reviewStatus])}>
          {item.statusLabel}
        </span>
      </span>
    </button>
  )
}

const TAG_TONE = (role: Origin | ReviewStatus, tag: string): string => {
  if (role === 'AI' || role === 'proposed' || /do przeglądu/.test(tag)) return 'text-attention-text'
  if (role === 'approved' || /zatwierdzone/.test(tag)) return 'text-success-text'
  if (role === 'CALC') return 'text-prov-calc'
  return 'text-muted'
}

export function FieldTag({ field }: { field: DetailField }) {
  if (!field.tag) return null
  return <span className={cn('t-mono text-[11.5px]', TAG_TONE(field.tagRole, field.tag))}>{field.tag}</span>
}

export function MetaList({ meta }: { meta: { k: string; v: string }[] }) {
  if (!meta.length) return null
  return (
    <dl className="m-0 flex flex-col gap-1 pt-1">
      {meta.map((m) => (
        <div key={m.k} className="grid grid-cols-[90px_minmax(0,1fr)] gap-2 text-[12.5px]">
          <dt className="text-muted">{m.k}</dt>
          <dd className="t-mono m-0 [overflow-wrap:anywhere]">{m.v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function CtaLink({
  href,
  external,
  children,
}: {
  href: string
  external?: boolean
  children: React.ReactNode
}) {
  const cls =
    'inline-flex min-h-10.5 items-center justify-center gap-1.5 rounded-pill bg-ink px-5 text-[14px] font-semibold text-on-ink no-underline hover:opacity-90'
  return (
    <a href={href} className={cls} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}>
      {children}
      {external ? (
        <>
          <ExternalLink aria-hidden className="size-3.5" />
          <span className="sr-only">(otwiera się w nowej karcie)</span>
        </>
      ) : null}
    </a>
  )
}

/** Dashed drop area: PDF, DOCX or ZIP. Expert only; the parent decides what happens with the file. */
export function FileDrop({
  onFile,
  busy,
  disabledReason,
}: {
  onFile: (file: File, isPublic: boolean) => void
  busy: boolean
  disabledReason?: string | null
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [isPublic, setPublic] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const take = (f: File | undefined) => {
    if (!f) return
    const err = validateUpload(f)
    setError(err)
    if (!err) onFile(f, isPublic)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (!disabledReason) take(e.dataTransfer.files[0])
  }
  return (
    <fieldset
      id="dodaj"
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        'mx-0 mt-1.5 flex min-w-0 flex-col items-center gap-1.5 rounded-card border-[1.5px] border-dashed p-5.5 text-center',
        over ? 'border-ink bg-soft' : 'border-border',
      )}
    >
      <legend className="sr-only">Dodawanie dokumentów</legend>
      <span className="text-[15px] font-semibold">Upuść PDF, DOCX albo ZIP</span>
      <span className="max-w-[460px] text-[13px] text-muted">
        Agent importu rozpozna typ dokumentu, przypisze go do projektu i zaproponuje fakty do przeglądu. Nic
        nie trafi do karty bez Twojej decyzji.
      </span>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        aria-label="Wybierz plik z dysku"
        onChange={(e) => {
          take(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      <button
        type="button"
        disabled={busy || !!disabledReason}
        onClick={() => input.current?.click()}
        className="mt-1 inline-flex min-h-10 items-center gap-2 rounded-pill border border-border bg-surface px-4 text-[14px] font-medium hover:bg-soft disabled:opacity-50"
      >
        <Upload aria-hidden className="size-4" />
        {busy ? 'Wysyłamy…' : 'Wybierz plik'}
      </button>
      <fieldset className="m-0 mt-1 flex min-w-0 flex-col items-center gap-1 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium text-text-secondary">Poufność dokumentu</legend>
        <div className="flex flex-wrap justify-center gap-4 text-[13px]">
          <label className="flex items-center gap-1.5">
            <input type="radio" name="dok-poufnosc" checked={isPublic} onChange={() => setPublic(true)} />
            Publiczny
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="dok-poufnosc" checked={!isPublic} onChange={() => setPublic(false)} />
            Poufny
          </label>
        </div>
        <span className="max-w-[460px] text-[12.5px] text-muted" data-testid="poufnosc-opis">
          {isPublic
            ? 'Domyślnie publiczny: dotyczy udzielonego zamówienia publicznego, przetwarza go model w chmurze; zaznacz poufny, jeśli dokument zawiera dane wrażliwe.'
            : 'Poufny: plik widzisz tylko Ty i administrator, nie trafia do wyszukiwarki ani eksportów.'}
        </span>
      </fieldset>
      {disabledReason ? <span className="text-[13px] text-attention-text">{disabledReason}</span> : null}
      {error ? (
        <span role="alert" className="text-[13px] text-attention-text">
          {error}
        </span>
      ) : null}
    </fieldset>
  )
}
