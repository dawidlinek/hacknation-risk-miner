import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { FileText, Upload, X } from 'lucide-react'
import {
  type DragEvent,
  type FormEvent,
  lazy,
  type KeyboardEvent as ReactKeyboardEvent,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import type { FollowUp, UploadedDocument } from '@/api/contracts/analyses'
import { Page, PageHeader } from '@/app/Page'
import { OriginMarker } from '@/components/common/ProvenanceTag'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { useFeature } from '@/config/features'
import { cn } from '@/lib/cn'
import { runAnalysis } from '../report/api'
import { createAnalysis, draftQuery, patchFeatures, uploadDocument } from './api'
import {
  ACCEPT,
  aiStatusLine,
  type Chip,
  canRun,
  type Draft,
  fileError,
  patchValue,
  readyToCreate,
} from './logic'

/** Enter inside a nested editor saves that editor only (it lives inside the main form, so no inner <form>). */
const onEnter = (fn: () => void) => (e: ReactKeyboardEvent<HTMLElement>) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    fn()
  }
}

const JellySite = lazy(() => import('../jelly/JellySite').then((m) => ({ default: m.JellySite })))

interface FileItem {
  key: string
  name: string
  status: 'uploading' | 'done' | 'error'
  doc?: UploadedDocument
  error?: string
}

export function NewAnalysisScreen({ fromId }: { fromId?: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [id, setId] = useState<string | null>(fromId ?? null)
  const [text, setText] = useState('')
  const [files, setFiles] = useState<FileItem[]>([])
  const [isPublic, setIsPublic] = useState(false)
  const creating = useRef(false)
  const draft = useQuery({ ...draftQuery(id ?? '_'), enabled: !!id })
  const loadedFrom = useRef(false)

  // editing an existing analysis: take its text and documents once
  useEffect(() => {
    if (fromId && draft.data && !loadedFrom.current) {
      loadedFrom.current = true
      setText(draft.data.text ?? '')
      setFiles(
        draft.data.documents.map((d) => ({
          key: `d${d.document_id}`,
          name: d.filename,
          status: 'done',
          doc: d,
        })),
      )
    }
  }, [fromId, draft.data])

  const docIds = files
    .filter((f) => f.status === 'done' && f.doc)
    .map((f) => (f.doc as UploadedDocument).document_id)
  const uploading = files.some((f) => f.status === 'uploading')

  const setDraft = useCallback(
    (d: Draft) => {
      qc.setQueryData(draftQuery(d.id).queryKey, d)
      void qc.invalidateQueries({ queryKey: ['analysis', d.id, 'report'] })
    },
    [qc],
  )

  /** Create the draft once, then PATCH text/documents when they change. Returns the analysis id (or null). */
  const sync = useCallback(
    async (t: string, ids: number[]): Promise<string | null> => {
      try {
        if (!id) {
          if (!readyToCreate(t, ids) || creating.current) return null
          creating.current = true
          const d = await createAnalysis(t, ids)
          setId(d.id)
          setDraft(d)
          return d.id
        }
        const cur = qc.getQueryData(draftQuery(id).queryKey)
        const sameDocs =
          cur && [...cur.documents.map((x) => x.document_id)].sort().join() === [...ids].sort().join()
        if (!(cur && cur.text === t && sameDocs))
          setDraft(await patchFeatures(id, { text: t, document_ids: ids }))
        return id
      } catch (e) {
        toast.error(
          e instanceof ApiError && e.status === 403
            ? 'Nie możesz zmieniać tej analizy.'
            : 'Nie zapisaliśmy opisu. Spróbuj ponownie.',
        )
        return null
      } finally {
        creating.current = false
      }
    },
    [id, qc, setDraft],
  )

  // 800 ms after typing stops
  const docKey = docIds.join(',')
  useEffect(() => {
    if (fromId && !loadedFrom.current) return
    const ids = docKey ? docKey.split(',').map(Number) : []
    const t = setTimeout(() => void sync(text, ids), 800)
    return () => clearTimeout(t)
  }, [text, docKey, fromId, sync])

  const addFiles = async (list: FileList | File[]) => {
    for (const f of Array.from(list)) {
      const key = `${f.name}-${f.size}-${Date.now()}`
      const err = fileError(f)
      if (err) {
        setFiles((p) => [...p, { key, name: f.name, status: 'error', error: err }])
        continue
      }
      setFiles((p) => [...p, { key, name: f.name, status: 'uploading' }])
      try {
        const doc = await uploadDocument(f, isPublic ? 'public' : 'confidential', id)
        setFiles((p) => p.map((x) => (x.key === key ? { ...x, status: 'done', doc } : x)))
      } catch {
        setFiles((p) =>
          p.map((x) =>
            x.key === key
              ? {
                  ...x,
                  status: 'error',
                  error: 'Nie udało się wczytać pliku. Obsługujemy PDF i DOCX do 50 MB.',
                }
              : x,
          ),
        )
      }
    }
  }

  const run = useMutation({
    mutationFn: async () => {
      const target = (await sync(text, docIds)) ?? id
      if (!target) throw new Error('no draft')
      await runAnalysis(target)
      return target
    },
    onSuccess: (target) => {
      void qc.invalidateQueries({ queryKey: ['analysis', target] })
      void navigate({ to: '/analizy/$id', params: { id: target } })
    },
    onError: () => toast.error('Nie udało się uruchomić analizy. Spróbuj ponownie.'),
  })

  const d = draft.data
  const status = d ? aiStatusLine(d) : null
  const jelly = useFeature('jelly')
  return (
    <Page>
      {jelly ? (
        <Suspense fallback={null}>
          <JellySite />
        </Suspense>
      ) : null}
      <PageHeader
        title="Co planujesz zbudować?"
        breadcrumb={fromId ? `Edycja założeń ${fromId}` : undefined}
        lead="Opisz inwestycję własnymi słowami albo dołącz PFU lub projekt umowy. Porównamy ją z wykonanymi umowami wod-kan z BZP."
      />
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          if (canRun(text, docIds, uploading)) run.mutate()
        }}
      >
        <label htmlFor="opis" className="t-item">
          Opis inwestycji
        </label>
        <Textarea
          id="opis"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="np. Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS"
          className="rounded-panel p-5 text-[16px] shadow-[var(--shadow-composer)]"
        />
        <FileDrop onFiles={addFiles} />
        <label htmlFor="pub" className="t-small flex cursor-pointer items-center gap-2 text-text-body-muted">
          <Checkbox id="pub" checked={isPublic} onCheckedChange={(v) => setIsPublic(v === true)} />
          Dokument jest publiczny (np. pobrany z BZP)
        </label>
        <p className="t-caption m-0 text-muted">
          Dokumenty niepubliczne czyta wyłącznie model działający w Polsce. Gdy jest niedostępny, pokazujemy
          uwagi z reguł, a dokument nie trafia do chmury.
        </p>
        {files.length ? (
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {files.map((f) => (
              <li
                key={f.key}
                className={cn(
                  't-small flex items-center gap-2 rounded-pill border px-3 py-1.5',
                  f.status === 'error' ? 'border-attention text-attention-text' : 'border-border',
                )}
              >
                <FileText className="size-4" aria-hidden />
                <span className="max-w-[240px] truncate">{f.name}</span>
                <span className="t-mono text-muted">
                  {f.status === 'uploading' ? 'wczytujemy…' : f.status === 'done' ? f.doc?.label : f.error}
                </span>
                <button
                  type="button"
                  aria-label={`Usuń ${f.name}`}
                  onClick={() => setFiles((p) => p.filter((x) => x.key !== f.key))}
                  className="text-muted hover:text-text"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {id ? (
          <section aria-labelledby="chips" className="flex flex-col gap-3 rounded-panel bg-soft p-5">
            <h2 id="chips" className="t-h3 m-0">
              Rozumiemy to tak
            </h2>
            {status ? (
              <p
                role="status"
                className={cn('t-small m-0', status.tone === 'busy' ? 'text-prov-ai' : 'text-attention-text')}
              >
                {status.text}
              </p>
            ) : null}
            {d ? (
              <ChipsEditor id={id} chips={d.features as Chip[]} onDraft={setDraft} />
            ) : (
              <p className="t-small m-0 text-muted">Czytamy opis…</p>
            )}
            {d?.follow_ups.length ? <FollowUps id={id} items={d.follow_ups} onDraft={setDraft} /> : null}
          </section>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            size="xl"
            disabled={!canRun(text, docIds, uploading) || run.isPending}
            aria-busy={run.isPending}
          >
            {run.isPending ? 'Liczymy…' : 'Uruchom analizę'}
          </Button>
          {!canRun(text, docIds, uploading) ? (
            <span className="t-caption text-muted">
              {uploading
                ? 'Poczekaj, aż pliki się wczytają.'
                : 'Napisz co najmniej 20 znaków albo dołącz dokument.'}
            </span>
          ) : null}
        </div>
      </form>
    </Page>
  )
}

function FileDrop({ onFiles }: { onFiles: (f: FileList | File[]) => void }) {
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files)
  }
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: drop target only; the "Wybierz pliki" button is the keyboard path
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        'flex flex-wrap items-center justify-between gap-3 rounded-panel border-2 border-dashed px-5 py-4',
        over ? 'border-ink bg-soft' : 'border-border',
      )}
      data-testid="file-drop"
    >
      <span className="t-small text-text-body-muted">
        Przeciągnij tu PFU, projekt umowy lub SWZ (PDF, DOCX do 50 MB)
      </span>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        className="sr-only"
        aria-label="Wybierz pliki"
        onChange={(e) => e.target.files && onFiles(e.target.files)}
      />
      <Button type="button" variant="outline" onClick={() => input.current?.click()}>
        <Upload aria-hidden />
        Wybierz pliki
      </Button>
    </div>
  )
}

export function ChipsEditor({
  id,
  chips,
  onDraft,
}: {
  id: string
  chips: Chip[]
  onDraft: (d: Draft) => void
}) {
  if (!chips.length)
    return (
      <p className="t-small m-0 text-muted">Nie rozpoznaliśmy jeszcze cech. Dopisz szczegóły w opisie.</p>
    )
  return (
    <ul className="m-0 flex list-none flex-wrap gap-2 p-0" data-testid="chips">
      {chips.map((c) => (
        <li key={c.key}>
          <ChipView id={id} c={c} onDraft={onDraft} />
        </li>
      ))}
    </ul>
  )
}

function ChipView({ id, c, onDraft }: { id: string; c: Chip; onDraft: (d: Draft) => void }) {
  const [open, setOpen] = useState(false)
  const [val, setVal] = useState('')
  const save = useMutation({
    mutationFn: (value: unknown) => patchFeatures(id, { values: { [c.key]: value } }),
    onSuccess: (d) => {
      onDraft(d)
      setOpen(false)
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Nie możesz zmieniać tej analizy.'
          : 'Nie zapisaliśmy zmiany.',
      ),
  })
  const submit = () => {
    const v = c.editor === 'select' ? val : patchValue(c, val)
    if (v === null || v === '') return
    save.mutate(v)
  }
  const origin = c.origin === 'AI' ? 'AI' : c.origin === 'SOURCE' ? 'SOURCE' : 'CALC'
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o) setVal(c.editor === 'select' ? String(c.value ?? '') : '')
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex flex-col items-start gap-0.5 rounded-item border bg-surface px-3 py-2 text-left hover:border-ink',
            c.unsure ? 'border-dashed border-attention' : 'border-border',
          )}
          data-testid={`chip-${c.key}`}
        >
          <span className="t-caption text-muted">{c.label}</span>
          <span className="t-item">{c.display}</span>
          <span className="t-mono flex items-center gap-1.5 text-muted">
            <OriginMarker origin={origin} reviewStatus={c.review_status as never} />
            {c.source_label}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        <fieldset
          aria-label={c.label}
          className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0"
          onKeyDown={onEnter(submit)}
        >
          <label htmlFor={`ed-${c.key}`} className="t-small font-medium">
            {c.label}
          </label>
          {c.editor === 'select' && c.options ? (
            <select
              id={`ed-${c.key}`}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              className="t-small rounded-item border border-border bg-surface px-3 py-2"
            >
              {c.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <Input
              id={`ed-${c.key}`}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              placeholder={
                c.editor === 'money'
                  ? 'np. 7 mln zł brutto'
                  : c.editor === 'months'
                    ? 'np. 14'
                    : String(c.value ?? '')
              }
              inputMode={c.editor === 'text' ? 'text' : 'decimal'}
            />
          )}
          {c.editor !== 'select' && val && patchValue(c, val) === null ? (
            <span className="t-caption text-attention-text">Wpisz liczbę.</span>
          ) : null}
          <Button type="button" size="sm" disabled={save.isPending} onClick={submit}>
            Zapisz
          </Button>
        </fieldset>
      </PopoverContent>
    </Popover>
  )
}

function FollowUps({ id, items, onDraft }: { id: string; items: FollowUp[]; onDraft: (d: Draft) => void }) {
  const f = items[0]
  const [val, setVal] = useState('')
  const send = useMutation({
    mutationFn: (body: { values?: Record<string, unknown>; skipped?: string[] }) => patchFeatures(id, body),
    onSuccess: (d) => {
      onDraft(d)
      setVal('')
    },
    onError: () => toast.error('Nie zapisaliśmy odpowiedzi.'),
  })
  const submit = () => {
    const v = f.input === 'number' ? patchValue({ editor: 'number' }, val) : val.trim()
    if (v === null || v === '') return
    send.mutate({ values: { [f.key]: v } })
  }
  return (
    <fieldset
      aria-label={f.title}
      onKeyDown={onEnter(submit)}
      className="m-0 flex min-w-0 flex-col gap-2 rounded-item border-0 bg-surface px-4 py-3"
      data-testid="follow-up"
    >
      <label htmlFor={`fu-${f.key}`} className="t-item">
        {f.title}
      </label>
      <span className="t-caption text-text-body-muted">{f.why}</span>
      <div className="flex flex-wrap gap-2">
        <Input
          id={`fu-${f.key}`}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder={f.placeholder}
          inputMode={f.input === 'number' ? 'decimal' : 'text'}
          className="max-w-[200px]"
        />
        <Button type="button" size="sm" disabled={send.isPending} onClick={submit}>
          Zapisz
        </Button>
        {f.skippable ? (
          <Button type="button" size="sm" variant="ghost" onClick={() => send.mutate({ skipped: [f.key] })}>
            Nie wiem, pomiń
          </Button>
        ) : null}
      </div>
      {items.length > 1 ? (
        <span className="t-mono text-muted">jeszcze {items.length - 1} do uzupełnienia</span>
      ) : null}
    </fieldset>
  )
}
