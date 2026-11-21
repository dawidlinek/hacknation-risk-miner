import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileText } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { AnalysisPanel, ProcessingSteps } from '@/features/documents/AnalysisPanel'
import { stepsSummary } from '@/features/documents/analysis'
import { documentAnalysisQuery } from '@/features/documents/api'
import { fmtDate } from '@/lib/dates'
import {
  cardHref,
  contractLine,
  duplicateLine,
  failedChecks,
  projectLine,
  type RoutedDocument,
  resultLine,
} from './route'

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2 text-[14px]">
      <span className="text-text-secondary">{k}:</span>
      <span className="font-medium">{v}</span>
    </div>
  )
}

/** One routed document: live processing steps, then what it is, where it was linked and what it added. */
function DocumentResult({ doc }: { doc: RoutedDocument & { document_id: number } }) {
  const q = useQuery(documentAnalysisQuery(doc.document_id))
  const [more, setMore] = useState(false)
  const a = q.data
  const linked = a?.steps.find((s) => s.key === 'linking')?.state === 'done'
  const rm = a?.project_rm_id ?? null
  const checks = a ? failedChecks(a) : []
  return (
    <li
      className="flex flex-col gap-3 rounded-item border border-border bg-surface p-4"
      data-testid="document-intake"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="t-item inline-flex items-center gap-2">
          <FileText aria-hidden className="size-4 text-muted" />
          {doc.name}
        </span>
        <span className="t-mono text-[12px] text-muted">dokument #{doc.document_id}</span>
      </div>
      {duplicateLine(doc) ? (
        <p className="m-0 text-[14px] text-text-secondary" data-testid="duplicate">
          {duplicateLine(doc)}
        </p>
      ) : null}
      {q.isError ? (
        <span className="text-attention-text">Nie udało się pobrać stanu dokumentu.</span>
      ) : !a ? (
        <span className="text-[14px] text-muted">Sprawdzamy stan dokumentu…</span>
      ) : (
        <>
          <p className="m-0 text-[13px] text-text-body-muted" aria-live="polite">
            {stepsSummary(a.steps)}
          </p>
          <ProcessingSteps steps={a.steps} />
          {a.document.doc_kind_label ? (
            <Row
              k="Rodzaj dokumentu"
              v={`${a.document.doc_kind_label}${a.document.doc_date ? `, ${fmtDate(a.document.doc_date)}` : ''}`}
            />
          ) : null}
          {linked ? (
            <Row k="Projekt" v={projectLine(a) ?? 'nie powiązano, sprawa czeka w Przeglądzie'} />
          ) : null}
          {contractLine(a) ? <Row k="Umowa" v={contractLine(a)} /> : null}
          {resultLine(a) ? (
            <p className="m-0 rounded-inner bg-soft px-3 py-2 text-[14px] font-medium" data-testid="growth">
              {resultLine(a)}
            </p>
          ) : null}
          {checks.map((c) => (
            <p
              key={c}
              role="alert"
              className="m-0 rounded-inner border border-dashed border-attention bg-attention-soft px-3 py-2 text-[14px] text-attention-text"
            >
              {c}
            </p>
          ))}
          {linked ? (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[14px]">
              {rm ? (
                <Link {...cardHref(rm, doc.document_id)} className="font-medium">
                  Co się zmieniło w projekcie {rm}
                </Link>
              ) : null}
              {a.review_items.length > 0 ? (
                <Link to="/przeglad" className="font-medium">
                  Otwórz Przegląd
                </Link>
              ) : null}
              <Button variant="outline" size="sm" onClick={() => setMore((v) => !v)}>
                {more ? 'Ukryj szczegóły' : 'Pokaż fakty i cytaty'}
              </Button>
            </div>
          ) : null}
          {more ? <AnalysisPanel documentId={doc.document_id} /> : null}
        </>
      )}
    </li>
  )
}

/** Case documents the import agent handed to the document pipeline, one card per file. */
export function DocumentIntake({ docs }: { docs: RoutedDocument[] }) {
  if (docs.length === 0) return null
  return (
    <section aria-label="Dokumenty przekazane do analizy" className="flex flex-col gap-2">
      <p className="m-0 text-[14px]">
        {docs.length === 1 ? 'Ten plik to dokument sprawy' : 'Te pliki to dokumenty sprawy'}, nie zestaw
        danych. Odczytujemy fakty i sami szukamy projektu po numerze KPO, NIP, zamawiającym i numerze umowy.
      </p>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {docs.map((d) =>
          d.document_id ? (
            <DocumentResult key={d.name} doc={{ ...d, document_id: d.document_id }} />
          ) : (
            <li
              key={d.name}
              role="alert"
              className="rounded-item border border-dashed border-attention bg-attention-soft px-4 py-3 text-[14px] text-attention-text"
            >
              {d.name}: {d.error ?? 'nie udało się przekazać pliku.'}
            </li>
          ),
        )}
      </ul>
    </section>
  )
}
