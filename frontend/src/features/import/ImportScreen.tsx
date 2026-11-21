import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileUp, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import type { ImportSession } from '@/api/contracts/import'
import { Page, PageHeader, TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/cn'
import {
  answerQuestion,
  approveImport,
  getImport,
  importersQuery,
  inspectImport,
  jobQuery,
  proposeMapping,
  routeDocuments,
  runImport,
  startEnrich,
  testRun,
  uploadFiles,
} from './api'
import { DocumentIntake } from './DocumentIntake'
import { NO_FILES_IN_DROP, needsDocumentRouting, needsMapping, type RouteResult } from './route'

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError && e.detail ? e.detail : fallback)
const bare = (name: string) => name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ')

function ToolCallRow({ call, out }: { call: string; out: string }) {
  return (
    <li className="flex flex-col gap-0.5 rounded-inner bg-soft px-3.5 py-2">
      <code className="t-mono text-text">{call}</code>
      <span className="text-[13px] text-text-body-muted">{out}</span>
    </li>
  )
}

function MappingTable({ session }: { session: ImportSession }) {
  return (
    <div className="overflow-x-auto rounded-item border border-border bg-surface">
      <table className="w-full text-[14px]">
        <caption className="sr-only">Mapowanie kolumn pliku na pola bazy</caption>
        <thead>
          <tr className="border-b border-border text-left text-[12.5px] text-text-secondary">
            <th className="px-3 py-2 font-semibold">Kolumna w pliku</th>
            <th className="px-3 py-2 font-semibold">Pole w bazie</th>
            <th className="px-3 py-2 font-semibold">Reguła</th>
            <th className="px-3 py-2 font-semibold">Stan</th>
          </tr>
        </thead>
        <tbody>
          {session.mapping.map((m) => (
            <tr key={m.column} className="border-b border-divider last:border-0">
              <td className="px-3 py-2">{m.column}</td>
              <td className="t-mono px-3 py-2">{m.field}</td>
              <td className="px-3 py-2 text-text-body-muted">{m.rule}</td>
              <td
                className={cn(
                  'px-3 py-2 font-medium',
                  m.state === 'question'
                    ? 'text-attention-text'
                    : m.state === 'ok'
                      ? 'text-success-text'
                      : 'text-text-secondary',
                )}
              >
                {m.state_label}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The agent thread: files, tool calls, mapping, question, test run, approval, run. State comes from /api/imports/{code}. */
function AgentThread({ initial, onDone }: { initial: ImportSession; onDone: () => void }) {
  const [session, setSession] = useState(initial)
  const [busy, setBusy] = useState<string | null>(null)
  const [answered, setAnswered] = useState<Record<string, string>>({})
  const [routed, setRouted] = useState<RouteResult | null>(null)
  const started = useRef(false)
  const job = useQuery(jobQuery(session.status === 'running' ? session.job_id : null))
  const code = session.code

  const step = useCallback(async (label: string, fn: () => Promise<ImportSession>) => {
    setBusy(label)
    try {
      setSession(await fn())
    } catch (e) {
      toast.error(errMsg(e, 'Ten krok się nie powiódł.'))
    } finally {
      setBusy(null)
    }
  }, [])

  // uploaded -> agent inspects the files; case documents (PDF, DOCX, scans) go to the document pipeline, datasets and
  // project records get a mapping proposal
  useEffect(() => {
    if (session.status !== 'uploaded' || started.current) return
    started.current = true
    void step('Agent przegląda pliki…', async () => {
      const inspected = await inspectImport(code)
      let r: RouteResult | null = null
      if (needsDocumentRouting(inspected.files)) {
        setBusy('Przekazujemy dokumenty do analizy…')
        r = await routeDocuments(code)
        setRouted(r)
      }
      if (!needsMapping(inspected.files, r)) return getImport(code)
      setBusy('Agent proponuje mapowanie kolumn…')
      return proposeMapping(code)
    })
  }, [session.status, code, step])

  // run finished -> refresh the importer list and the run log
  useEffect(() => {
    if (job.data && job.data.status === 'done') onDone()
  }, [job.data, onDone])

  const approveAndRun = () =>
    step('Zatwierdzamy importer i uruchamiamy import…', async () => {
      const name = session.importer?.name ?? bare(session.files[0]?.name ?? 'importer')
      await approveImport(code, name)
      await runImport(code)
      return getImport(code)
    })

  const q = session.questions[0]
  const failed = job.data && ['failed', 'error'].includes(job.data.status)
  return (
    <section aria-label="Agent importu" className="flex flex-col gap-4 rounded-panel bg-soft p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="t-h3 m-0">
          Agent importu <span className="t-mono ml-1 text-muted">{code}</span>
        </h2>
        <span className="t-caption text-muted">
          {routed && routed.tables === 0 && routed.documents.length > 0
            ? 'dokumenty przekazane do analizy'
            : session.status_label}
        </span>
      </div>
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
        {session.files.map((f) => (
          <li
            key={f.name}
            className="inline-flex items-center gap-2 rounded-pill bg-surface px-3 py-1.5 text-[13px]"
          >
            <FileUp aria-hidden className="size-3.5 text-muted" />
            {f.name}
            <span className="t-mono text-muted">{f.detail}</span>
            {f.duplicate ? <span className="text-attention-text">ten plik był już wczytany</span> : null}
          </li>
        ))}
      </ul>
      {session.tool_calls.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Wywołania narzędzi agenta">
          {session.tool_calls.map((c) => (
            <ToolCallRow key={c.call} call={c.call} out={c.out} />
          ))}
        </ul>
      ) : null}
      {routed ? <DocumentIntake docs={routed.documents} /> : null}
      {session.mapping.length > 0 ? (
        <>
          <p className="m-0 text-[14px]">Tak mapuję kolumny pliku na pola bazy:</p>
          <MappingTable
            session={{
              ...session,
              mapping: session.mapping.map((m) =>
                m.state_label === 'zgodne' && answered.value_vat_basis && m.field === 'project.value'
                  ? { ...m, state_label: answered.value_vat_basis === 'gross' ? 'brutto' : 'netto' }
                  : m,
              ),
            }}
          />
        </>
      ) : null}

      {q ? (
        <div className="flex flex-col gap-2 rounded-item border border-attention bg-attention-soft p-4">
          <span className="t-item">{q.title}</span>
          <div className="flex flex-wrap gap-2">
            {q.options.map((o) => (
              <Button
                key={o.value}
                variant="outline"
                disabled={busy !== null}
                onClick={() => {
                  setAnswered((a) => ({ ...a, [q.key]: o.value }))
                  void step('Zapisujemy odpowiedź…', () => answerQuestion(code, q.key, o.value))
                }}
              >
                {o.label}
              </Button>
            ))}
          </div>
        </div>
      ) : null}

      {!q &&
      session.mapping.length > 0 &&
      session.status !== 'tested' &&
      session.status !== 'approved' &&
      session.status !== 'running' &&
      session.status !== 'done' ? (
        <Button
          size="lg"
          className="self-start"
          disabled={busy !== null}
          onClick={() => void step('Próbny import na 50 wierszach…', () => testRun(code, 50))}
        >
          Wykonaj próbny import (50 wierszy)
        </Button>
      ) : null}

      {session.test_run ? (
        <div className="flex flex-col gap-1 rounded-item bg-surface p-4 text-[14px]">
          <span className="t-item">Próbny import, transakcja wycofana</span>
          <span>
            {session.test_run.ok} z {session.test_run.rows} wierszy bez błędów, {session.test_run.failed}{' '}
            odrzuconych.
            {session.test_run.failed > 0
              ? ' Odrzucone nie wejdą do bazy, trafią do Przeglądu jako rozbieżności.'
              : ''}
          </span>
          {session.test_run.review_items_created > 0 ? (
            <Link to="/przeglad" search={{ rodzaj: 'rozbieznosci' } as never} className="font-medium">
              Zobacz w Przeglądzie
            </Link>
          ) : null}
        </div>
      ) : null}

      {session.status === 'tested' ? (
        <div className="flex flex-col gap-2 rounded-item border border-border bg-surface p-4">
          <span className="t-item">Uruchomić importer na całości?</span>
          <span className="text-[14px] text-text-body-muted">
            Reguły sprawdza kod, nie model. Import nie nadpisuje danych zatwierdzonych przez eksperta.
          </span>
          <div className="flex gap-2">
            <Button size="lg" onClick={approveAndRun} disabled={busy !== null}>
              Zatwierdź i importuj
            </Button>
          </div>
        </div>
      ) : null}

      {session.status === 'running' || session.status === 'done' ? (
        <div className="flex flex-col gap-2 rounded-item bg-surface p-4">
          <span className="t-item">
            {job.data?.status === 'done' || session.status === 'done'
              ? 'Import zakończony'
              : `Import ${code} w toku`}
          </span>
          {job.data?.status !== 'done' && session.status !== 'done' ? (
            <Progress value={undefined} aria-label="Import w toku" />
          ) : null}
          {failed ? (
            <span className="text-attention-text">{job.data?.error ?? 'Import zakończył się błędem.'}</span>
          ) : null}
          {job.data?.status === 'done' ? <ImportedProjects result={job.data.result} /> : null}
        </div>
      ) : null}
      {busy ? (
        <span role="status" className="t-mono text-muted">
          {busy}
        </span>
      ) : null}
    </section>
  )
}

type LinkedRow = { rm_id: string; method: string | null; score: number | null }
const LINK_METHOD: Record<string, string> = {
  exact_id: 'numer ogłoszenia BZP',
  cross_reference: 'numer powołany w późniejszych ogłoszeniach',
  kpo_cited: 'numer KPO w ogłoszeniach zamawiającego',
  fuzzy: 'NIP, nazwa, CPV i data',
}

/** After the run: each imported record, its BZP link (method, score) and a link to its card. */
export function ImportedProjects({ result }: { result: Record<string, unknown> | null }) {
  const ids = Array.isArray(result?.projects) ? (result.projects as string[]) : []
  if (ids.length === 0) return null
  const link = (result?.link ?? {}) as { link?: { per_project?: LinkedRow[] }; events?: number }
  const per = new Map((link.link?.per_project ?? []).map((r) => [r.rm_id, r]))
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Zaimportowane projekty">
      {ids.map((id) => {
        const r = per.get(id)
        return (
          <li key={id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[14px]">
            <Link to="/projekty/$id" params={{ id }} className="font-medium">
              Otwórz kartę projektu {id}
            </Link>
            <span className="text-text-body-muted">
              {r?.method
                ? `powiązano z BZP: ${LINK_METHOD[r.method] ?? r.method}, wynik ${(r.score ?? 0).toFixed(2).replace('.', ',')}`
                : 'nie znaleziono postępowania w BZP, sprawa trafiła do Przeglądu'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function EnrichCard() {
  const qc = useQueryClient()
  const { readOnly } = useSession()
  const m = useMutation({
    mutationFn: startEnrich,
    onSuccess: (job) => {
      toast.success(`Wzbogacanie uruchomione (#${job.id}).`)
      void qc.invalidateQueries({ queryKey: ['runs'] })
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Wzbogacanie może uruchomić administrator.'
          : errMsg(e, 'Nie udało się uruchomić wzbogacania.'),
      ),
  })
  return (
    <section className="flex flex-col gap-2 rounded-panel bg-soft p-5">
      <h2 className="t-h3 m-0">Wzbogacanie</h2>
      <p className="m-0 text-[14px] text-text-body-muted">
        Po imporcie pobierz ogłoszenia BZP, połącz je z projektami i policz opóźnienie oraz koszt.
      </p>
      <Button size="lg" className="self-start" onClick={() => m.mutate()} disabled={m.isPending || readOnly}>
        Uruchom wzbogacanie
      </Button>
    </section>
  )
}

export function ImportScreen() {
  const qc = useQueryClient()
  const importers = useQuery(importersQuery)
  const [session, setSession] = useState<ImportSession | null>(null)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const { readOnly } = useSession()
  const up = useMutation({
    mutationFn: uploadFiles,
    onSuccess: (s) => setSession(s),
    onError: (e) =>
      toast.error(errMsg(e, 'Nie udało się wczytać pliku. Obsługujemy XLSX, CSV, PDF, DOCX i ZIP.')),
  })
  const take = (list: FileList | null | undefined) => {
    if (readOnly) return toast.error('To konto jest tylko do odczytu.')
    if (!list || list.length === 0) return toast.error(NO_FILES_IN_DROP)
    up.mutate([...list])
  }
  // A file dropped next to the drop zone must not make the browser open it (a PDF replaces the app): the whole page
  // takes the drop.
  const takeRef = useRef(take)
  takeRef.current = take
  useEffect(() => {
    const over = (e: DragEvent) => e.preventDefault()
    const drop = (e: DragEvent) => {
      if (e.defaultPrevented) return
      e.preventDefault()
      takeRef.current(e.dataTransfer?.files)
    }
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [])
  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['runs'] })
    void qc.invalidateQueries({ queryKey: ['importers'] })
    void qc.invalidateQueries({ queryKey: ['projects'] })
  }, [qc])

  return (
    <Page>
      <PageHeader
        title="Import i źródła"
        lead="Wrzuć plik, agent rozpozna format, zaproponuje mapowanie i sprawdzi je na próbie. Nic nie trafia do bazy bez Twojej zgody."
      />
      <TwoCol
        main={
          <>
            <section
              aria-label="Wczytaj pliki"
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(false)
                take(e.dataTransfer.files)
              }}
              className={cn(
                'flex flex-col items-center gap-2 rounded-panel border-2 border-dashed px-6 py-8 text-center',
                over ? 'border-ink bg-soft' : 'border-border',
              )}
            >
              <Upload aria-hidden className="size-6 text-muted" />
              <span className="t-item">Upuść pliki tutaj albo wybierz z dysku</span>
              <span className="text-[14px] text-text-body-muted">
                Zestaw danych (XLSX, CSV) albo dokumenty sprawy (PDF, DOCX, skan). Dokumenty trafiają do
                analizy i same łączą się z projektem.
              </span>
              <input
                ref={input}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  take(e.target.files)
                  e.target.value = ''
                }}
                aria-label="Wybierz pliki do importu"
              />
              <Button
                variant="outline"
                size="lg"
                onClick={() => input.current?.click()}
                disabled={up.isPending}
              >
                {up.isPending ? 'Wczytujemy…' : 'Wybierz pliki'}
              </Button>
            </section>
            {session ? <AgentThread key={session.code} initial={session} onDone={refresh} /> : null}
            <EnrichCard />
          </>
        }
        aside={
          <>
            <section className="flex flex-col gap-2 rounded-panel bg-soft p-5">
              <h2 className="t-h3 m-0">Zapisane importery</h2>
              {(importers.data ?? []).length === 0 ? (
                <p className="m-0 text-[14px] text-text-body-muted">
                  Importery pojawią się po pierwszym zatwierdzeniu.
                </p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                  {importers.data?.map((i) => (
                    <li
                      key={`${i.name}-${i.version}`}
                      className="flex items-baseline justify-between gap-2 rounded-inner bg-surface px-3 py-2"
                    >
                      <span className="flex flex-col">
                        <span className="t-item">{i.name}</span>
                        <span className="t-caption text-text-body-muted">{i.detail}</span>
                      </span>
                      <span className="t-mono text-muted">{i.version}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        }
      />
    </Page>
  )
}
