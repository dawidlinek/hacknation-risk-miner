import { useMutation, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Page, PageHeader, TwoCol } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { Button } from '@/components/ui/button'
import { fmtDateTime } from '@/lib/dates'
import { askErrorMessage, askQuestion, rerunQuestion, savedQuestionQuery, savedQuestionsQuery } from './api'
import { ChatAnswer } from './ChatAnswer'
import { ChatPanel } from './ChatPanel'

function SavedList() {
  const q = useQuery(savedQuestionsQuery)
  const items = q.data?.items ?? []
  return (
    <section className="flex flex-col gap-2 rounded-panel bg-soft p-5" aria-labelledby="saved-h">
      <h2 id="saved-h" className="t-h3 m-0">
        Zapisane pytania
      </h2>
      {items.length === 0 ? (
        <p className="m-0 text-[14px] text-text-body-muted">
          Zapisz odpowiedź jako rekord, a pojawi się tutaj.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {items.map((i) => (
            <li key={i.code}>
              <Link
                to="/zapytaj/$qid"
                params={{ qid: i.code }}
                className="flex flex-col gap-0.5 rounded-item bg-surface px-3.5 py-2.5 text-text no-underline hover:bg-soft-2"
              >
                <span className="t-item">{i.title}</span>
                <span className="t-mono text-muted">
                  {i.code}, {fmtDateTime(i.saved_at, { short: true })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** 1.6: ask the memory. Answers come from SQL over approved data (calculation) or from approved events (AI conclusion). */
export function AskScreen() {
  return (
    <Page>
      <PageHeader
        title="Zapytaj pamięć"
        lead="Pytania o doświadczenia z dotychczasowych umów. Odpowiedź ma rolę: obliczenie, wniosek AI albo brak danych, i pokazuje, jak ją policzyliśmy."
      />
      <TwoCol
        main={
          <ChatPanel
            title="Zadaj pytanie"
            context="zapytaj"
            ask={askQuestion}
            compact={false}
            placeholder="np. Ile przetargów miało jedną ofertę?"
          />
        }
        aside={<SavedList />}
      />
    </Page>
  )
}

export function SavedQuestionScreen({ code }: { code: string }) {
  const { data } = useSuspenseQuery(savedQuestionQuery(code))
  return (
    <Page>
      <PageHeader
        breadcrumb={
          <Link to="/zapytaj" className="text-muted no-underline hover:underline">
            Zapytaj pamięć
          </Link>
        }
        title={code}
      />
      {data ? (
        <>
          <ChatAnswer answer={{ ...data, question: data.question || code }} />
          <Rerun code={code} question={data.question || code} />
        </>
      ) : (
        <EmptyState>Nie znaleziono pytania.</EmptyState>
      )}
    </Page>
  )
}

function Rerun({ code, question }: { code: string; question: string }) {
  const rerun = useMutation({ mutationFn: () => rerunQuestion(code) })
  return (
    <section className="flex flex-col gap-3" aria-label="Zadaj ponownie">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          onClick={() => rerun.mutate()}
          disabled={rerun.isPending}
          aria-busy={rerun.isPending}
        >
          {rerun.isPending ? 'Liczymy ponownie…' : 'Zadaj ponownie'}
        </Button>
        <span className="t-caption text-muted">
          Zapisana odpowiedź zostaje bez zmian; nowa pojawi się obok, na dzisiejszych danych.
        </span>
      </div>
      {rerun.isError ? (
        <p role="alert" className="m-0 text-[14px] text-attention-text">
          {askErrorMessage(rerun.error)}
        </p>
      ) : null}
      {rerun.data ? (
        rerun.data.changed ? (
          <div className="flex flex-col gap-2">
            <h2 className="t-h3 m-0">Odpowiedź na dzisiejszych danych</h2>
            <ChatAnswer answer={{ ...rerun.data.answer, question: rerun.data.answer.question || question }} />
          </div>
        ) : (
          <p role="status" className="t-small m-0 text-text-body-muted">
            Wynik się nie zmienił od zapisania.
          </p>
        )
      ) : null}
    </section>
  )
}
