import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { RealNum } from '@/api/adapters/real'
import { contractFetch } from '@/api/client'
import { Page, PageHeader } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { StatTile } from '@/components/common/StatCard'
import { StepDot } from '@/components/common/StepList'
import { SummaryCard } from '@/components/common/SummaryCard'
import { Button } from '@/components/ui/button'
import { useFeature } from '@/config/features'
import { askQuestion } from '@/features/ask/api'
import { ChatPanel } from '@/features/ask/ChatPanel'
import { cn } from '@/lib/cn'
import { fmtDateTime } from '@/lib/dates'

interface Dashboard {
  tiles: { key: string; label: string; value: RealNum; sub: string; href: string; attention: boolean }[]
  sources: {
    kind: string
    label: string
    what: string
    count_label: string | null
    last_retrieved_at: string | null
    state: 'ok' | 'not_started' | 'error'
  }[]
  issues: { id: number; rm_id: string | null; code: string; title: string }[]
}
interface Headline {
  sentence: string
  data_as_of: string
  completed: RealNum
}

export const dashboardQuery = queryOptions({
  queryKey: ['dashboard'],
  queryFn: async () => {
    const [d, h] = await Promise.all([
      contractFetch<Dashboard>('/api/dashboard'),
      contractFetch<Headline>('/api/analytics/headline').catch(() => null),
    ])
    return { d, h }
  },
  staleTime: 30_000,
})

const TILE_HREF: Record<string, string> = {
  review_open: '/przeglad',
  monitoring_new: '/monitoring',
  my_analyses: '/analizy/nowa',
}

/** Short Polish title per discrepancy code; the API sentence stays as the description. */
const ISSUE_TITLE: Record<string, string> = {
  value_deviation: 'Wartość odbiega od BZP',
  part_scope_wider: 'Zakres części szerszy niż w zestawie',
  part_mismatch: 'Niezgodna część zamówienia',
}
const issueTitle = (code: string) => ISSUE_TITLE[code] ?? 'Rozbieżność w danych'

/** The API sentence may carry a raw word list ("[['100', '237']]"); show it as plain words. */
export const tidyIssue = (t: string) =>
  t.replace(/\[\[?((?:'[^']*'(?:,\s*)?)+)\]?\]/g, (_, inner: string) => inner.replace(/'/g, ''))

export function PulpitScreen() {
  const { data } = useSuspenseQuery(dashboardQuery)
  const { d, h } = data
  const chat = useFeature('ask_memory')
  return (
    <Page>
      <PageHeader
        title="Pulpit"
        actions={
          <>
            <Button variant="outline" size="lg" asChild>
              <Link to="/zrodla">Dodaj dane</Link>
            </Button>
            <Button size="lg" asChild>
              <Link to="/analizy/nowa">Nowa analiza</Link>
            </Button>
          </>
        }
      />
      {h ? <SummaryCard eyebrow="W skrócie" size="lg" sentence={h.sentence} /> : null}
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        {d.tiles.map((t) => (
          <StatTile
            key={t.key}
            label={t.label}
            value={t.value.display}
            sub={t.sub}
            href={TILE_HREF[t.key] ?? t.href}
            attention={t.attention}
          />
        ))}
      </div>
      {/* Main mockup: chat in the main column, compact source list on the right. The discrepancies sit under the chat
          (the mockup has them on the right next to a filled conversation; with an empty chat that left a hole) */}
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[999_1_600px] flex-col gap-6">
          {chat ? (
            <ChatPanel
              title="Zapytaj pamięć"
              context="pulpit"
              ask={askQuestion}
              placeholder="Zadaj pytanie o dane"
            />
          ) : (
            <EmptyState>
              Przeglądaj dotychczasowe umowy w <Link to="/projekty">Projektach</Link>.
            </EmptyState>
          )}
          <section className="flex flex-col gap-2 rounded-panel bg-soft p-5" aria-labelledby="iss-h">
            <div className="flex flex-col gap-0.5 px-1 pb-2">
              <h2 id="iss-h" className="t-h3 m-0">
                Do wyjaśnienia w danych
              </h2>
              <span className="t-caption text-muted">rozbieżności między zestawem a źródłami</span>
            </div>
            {d.issues.length === 0 ? (
              <p className="m-0 text-[14px] text-text-body-muted">Brak rozbieżności do wyjaśnienia.</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {d.issues.map((i) => (
                  <li key={i.id}>
                    <Link
                      to="/przeglad"
                      search={{ sprawa: i.id } as never}
                      className="flex items-start gap-3 rounded-item bg-surface px-3.5 py-3 text-text no-underline hover:bg-soft-2"
                    >
                      <span className="mt-px">
                        <StepDot state="now" />
                      </span>
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="t-item">{issueTitle(i.code)}</span>
                        <span className="line-clamp-3 text-[13px] text-text-body-muted" title={i.title}>
                          {tidyIssue(i.title)}
                        </span>
                        <span className="t-mono text-muted">{i.rm_id ?? i.code}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <aside className="flex min-w-0 max-w-full flex-[1_1_360px] flex-col gap-4">
          <section
            className="flex flex-col gap-1 rounded-panel border border-divider px-5.5 py-5"
            aria-labelledby="src-h"
          >
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <h2 id="src-h" className="t-h3 m-0">
                Źródła danych
              </h2>
              <Link to="/zrodla" className="font-medium text-[13px]">
                Uruchomienia →
              </Link>
            </div>
            <ul className="m-0 flex list-none flex-col p-0">
              {d.sources.map((s) => (
                <li
                  key={s.kind}
                  className="flex items-center gap-2.5 border-divider border-t py-2"
                  title={`${s.what}${s.last_retrieved_at ? `, pobrano ${fmtDateTime(s.last_retrieved_at, { short: true })}` : ''}`}
                >
                  <span
                    aria-hidden
                    className={cn(
                      'size-2 shrink-0 rounded-pill',
                      s.state === 'ok' ? 'bg-success' : s.state === 'error' ? 'bg-attention' : 'bg-border',
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate font-medium text-[14px]">{s.label}</span>
                  <span className="t-mono whitespace-nowrap text-text-body-muted">
                    {s.count_label ?? 'do uruchomienia'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </Page>
  )
}
