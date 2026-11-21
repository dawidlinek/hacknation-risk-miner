import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { DataState, EmptyState } from '@/components/common/DataState'
import { DetailPanel } from '@/components/common/DetailPanel'
import { SummaryCard } from '@/components/common/SummaryCard'
import { Button } from '@/components/ui/button'
import { AnalysisPanel } from './AnalysisPanel'
import { documentDetail, expectedDetail, noticeDetail } from './adapt'
import { noticeFactsQuery, projectDocumentsQuery, uploadErrorMessage, useUploadDocument } from './api'
import { docsHeading, findSelection, READ_ONLY_REASON } from './logic'
import { CtaLink, ExpectedDocRow, FieldTag, FileDrop, MetaList, PublicDocRow } from './parts'
import type { DetailView, PublicItem } from './types'

function SectionHead({ id, title, aside }: { id: string; title: string; aside?: React.ReactNode }) {
  return (
    <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
      <h2 id={id} className="t-h3 m-0">
        {title}
      </h2>
      {aside}
    </div>
  )
}

function NoticePanel({ item, canReview }: { item: PublicItem; canReview: boolean }) {
  const facts = useQuery({ ...noticeFactsQuery(item.objectId), enabled: item.kind === 'notice' })
  return (
    <DataState
      query={
        item.kind === 'notice'
          ? facts
          : { data: undefined, isPending: false, isError: false, error: null, refetch: facts.refetch }
      }
    >
      {(data) => (
        <Detail
          detail={item.kind === 'notice' ? noticeDetail(item, data, canReview, null) : documentDetail(item)}
        />
      )}
    </DataState>
  )
}

function Detail({ detail }: { detail: DetailView }) {
  return (
    <DetailPanel
      kind={detail.kind}
      title={detail.title}
      rows={detail.fields.map((f) => ({ k: f.label, v: f.value, tag: <FieldTag field={f} /> }))}
      footer={
        <>
          <MetaList meta={detail.meta} />
          {detail.cta ? (
            <CtaLink href={detail.cta.href} external={detail.cta.external}>
              {detail.cta.label}
            </CtaLink>
          ) : null}
        </>
      }
    />
  )
}

export function DocumentsScreen({
  id,
  selected,
  onSelect,
}: {
  id: string
  selected: string | null
  onSelect: (key: string | null) => void
}) {
  const { isPublic, isExpert, readOnly } = useSession()
  const { data: view } = useSuspenseQuery(projectDocumentsQuery(id, isPublic))
  const upload = useUploadDocument(id)
  const [showAll, setShowAll] = useState(false)
  const sel = findSelection(view, selected)
  const empty = view.expected.length === 0 && view.publicDocs.length === 0

  const onFile = (file: File, makePublic: boolean) =>
    upload.mutate(
      { file, isPublic: makePublic },
      {
        onSuccess: (r) => {
          toast.success('Dokument w kolejce. Fakty trafią do Przeglądu.')
          onSelect(`doc:${r.document_id}`)
        },
        onError: (e) => toast.error(uploadErrorMessage(e)),
      },
    )

  let panel: React.ReactNode
  if (sel?.type === 'expected') panel = <Detail detail={expectedDetail(sel.item, isExpert)} />
  else if (sel?.type === 'public')
    panel =
      sel.item.kind === 'document' ? (
        <AnalysisPanel key={sel.item.key} documentId={Number(sel.item.objectId)} />
      ) : (
        <NoticePanel key={sel.item.key} item={sel.item} canReview={isExpert} />
      )
  else
    panel = (
      <DetailPanel
        kind="dokumenty projektu"
        title="Wybierz dokument z listy"
        rows={[
          { k: 'z budowy', v: `${docsHeading(view)} oczekiwanych dokumentów` },
          { k: 'ze źródeł publicznych', v: `${view.publicDocs.length} pozycji` },
        ]}
      />
    )

  return (
    <>
      <SummaryCard sentence={view.summary} />
      {empty ? <EmptyState>Nie znaleźliśmy ogłoszeń dla tego projektu.</EmptyState> : null}
      <TwoCol
        main={
          <>
            <section aria-labelledby="dok-budowa" className="flex flex-col gap-1.5">
              <SectionHead
                id="dok-budowa"
                title="Dokumenty z budowy"
                aside={
                  <span className="t-mono text-[13px] font-semibold text-attention-text">
                    {docsHeading(view)}
                  </span>
                }
              />
              {view.expected.map((e) => (
                <ExpectedDocRow
                  key={e.key}
                  item={e}
                  selected={selected === e.key}
                  onPick={() => onSelect(selected === e.key ? null : e.key)}
                />
              ))}
              {isExpert ? (
                <FileDrop
                  onFile={onFile}
                  busy={upload.isPending}
                  disabledReason={readOnly ? READ_ONLY_REASON : null}
                />
              ) : null}
            </section>
            <section aria-labelledby="dok-publiczne" className="flex flex-col gap-1.5">
              <SectionHead
                id="dok-publiczne"
                title="Ze źródeł publicznych"
                aside={
                  <span className="text-[13px] text-muted">pobrane automatycznie, bez zmian w treści</span>
                }
              />
              {view.publicDocs.length === 0 ? (
                <EmptyState>Nie znaleźliśmy ogłoszeń dla tego projektu.</EmptyState>
              ) : (
                (showAll ? view.publicDocs : view.publicDocs.slice(0, 8)).map((d) => (
                  <PublicDocRow
                    key={d.key}
                    item={d}
                    selected={selected === d.key}
                    onPick={() => onSelect(selected === d.key ? null : d.key)}
                  />
                ))
              )}
              {view.publicDocs.length > 8 ? (
                <Button variant="outline" className="self-start" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? 'Pokaż mniej' : `Pokaż wszystkie (${view.publicDocs.length})`}
                </Button>
              ) : null}
            </section>
          </>
        }
        aside={panel}
      />
    </>
  )
}
