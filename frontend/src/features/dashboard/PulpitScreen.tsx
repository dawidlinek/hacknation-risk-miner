import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { RealNum } from '@/api/adapters/real'
import { contractFetch } from '@/api/client'
import { Page, PageHeader } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { StatTile } from '@/components/common/StatCard'
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
      {h ? (
        <SummaryCard
          eyebrow="W skrócie"
          size="lg"
          sentence={h.sentence}
          provenance={`obliczenie, ${h.completed.display} umów, dane na ${h.data_as_of.split('-').reverse().join('.')}`}
        />
      ) : null}
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
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[999_1_480px] flex-col gap-6">
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
            <h2 id="iss-h" className="t-h3 m-0">
              Do wyjaśnienia
            </h2>
            {d.issues.length === 0 ? (
              <p className="m-0 text-[14px] text-text-body-muted">Brak rozbieżności do wyjaśnienia.</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {d.issues.map((i) => (
                  <li key={i.id}>
                    <Link
                      to="/przeglad"
                      search={{ sprawa: i.id } as never}
                      className="flex flex-col gap-0.5 rounded-item bg-surface px-3.5 py-2.5 text-text no-underline hover:bg-soft-2"
                    >
                      <span className="t-item">{i.title}</span>
                      <span className="t-mono text-muted">{i.rm_id ?? i.code}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <aside
          className="flex min-w-0 flex-[1_1_320px] flex-col gap-3 rounded-panel bg-soft p-5"
          aria-labelledby="src-h"
        >
          <h2 id="src-h" className="t-h3 m-0">
            Źródła danych
          </h2>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {d.sources.map((s) => (
              <li key={s.kind} className="flex items-start gap-3 rounded-item bg-surface px-3.5 py-2.5">
                <span
                  aria-hidden
                  className={cn(
                    'mt-1.5 size-2.5 shrink-0 rounded-pill',
                    s.state === 'ok' ? 'bg-success' : s.state === 'error' ? 'bg-attention' : 'bg-border',
                  )}
                />
                <span className="flex min-w-0 flex-col">
                  <span className="t-item">{s.label}</span>
                  <span className="t-caption text-text-body-muted">{s.what}</span>
                  <span className="t-mono text-muted">
                    {s.count_label ?? '[do uruchomienia]'}
                    {s.last_retrieved_at
                      ? `, pobrano ${fmtDateTime(s.last_retrieved_at, { short: true })}`
                      : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </Page>
  )
}
