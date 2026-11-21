import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { LlmSettings } from '@/api/contracts/settings'
import { Page, PageHeader } from '@/app/Page'
import { SummaryCard } from '@/components/common/SummaryCard'
import { Switch } from '@/components/ui/switch'
import { useFeature } from '@/config/features'
import { cn } from '@/lib/cn'
import { fmtInt } from '@/lib/format'

export const settingsQuery = queryOptions({
  queryKey: ['settings', 'llm'],
  queryFn: () => contractFetch<LlmSettings>('/api/settings/llm'),
})

const isPl = (loc: string) => /^PL\b|Polsk/i.test(loc)

function Where({ loc }: { loc: string }) {
  const pl = isPl(loc)
  return (
    <span
      className={cn(
        't-mono rounded-pill px-2.5 py-1',
        pl ? 'bg-success-soft text-success-text' : 'bg-soft-2 text-text-secondary',
      )}
    >
      {pl ? 'Polska' : 'chmura'}
    </span>
  )
}

const HEALTH: Record<string, { dot: string; label: string }> = {
  up: { dot: 'bg-success', label: 'działa' },
  configured: { dot: 'bg-success', label: 'skonfigurowany' },
  down: { dot: 'bg-attention', label: 'nie odpowiada' },
  unknown: { dot: 'bg-border', label: 'nie sprawdzono' },
}

export function SettingsScreen() {
  const { data } = useSuspenseQuery(settingsQuery)
  const sovereignSwitch = useFeature('sovereign_switch')
  const confidential = data.tasks.filter((t) => t.sensitivity === 'confidential')
  const outside = confidential.filter((t) => !t.sovereign).length
  return (
    <Page>
      <PageHeader
        title="Ustawienia"
        lead="Gdzie trafiają dane i który model je czyta. Zmiany robi się w pliku konfiguracji, tu jest widok tylko do odczytu."
      />
      <SummaryCard
        eyebrow="Gdzie są dane"
        sentence={
          outside === 0
            ? 'Poufne dokumenty czyta wyłącznie model w Polsce. Dane publiczne mogą trafiać do modeli w chmurze.'
            : `${outside} zadań z poufnymi danymi nie jest przypisanych do modelu w Polsce.`
        }
        provenance={`z konfiguracji, ${data.tasks.length} zadań, ${data.providers.length} dostawców`}
      />
      <section className="flex flex-col gap-2" aria-labelledby="route-h">
        <h2 id="route-h" className="t-h3 m-0">
          Kierowanie zadań
        </h2>
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {data.tasks.map((t) => (
            <li
              key={`${t.task}-${t.sensitivity}`}
              className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-item bg-surface px-4 py-3"
            >
              <span className="flex min-w-0 flex-col">
                <span className="t-item">{t.label}</span>
                <span className="t-caption text-text-body-muted">
                  {t.data_label}, {t.model} <span className="t-mono text-muted">({t.alias})</span>
                </span>
              </span>
              <Where loc={t.data_location} />
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2" aria-labelledby="prov-h">
        <h2 id="prov-h" className="t-h3 m-0">
          Dostawcy modeli
        </h2>
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {data.providers.map((p) => {
            const h = HEALTH[p.health.status] ?? HEALTH.unknown
            return (
              <li
                key={p.id}
                className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-item bg-surface px-4 py-3"
              >
                <span aria-hidden className={cn('size-2.5 rounded-pill', h.dot)} />
                <span className="flex min-w-0 flex-col">
                  <span className="t-item t-mono">{p.id}</span>
                  <span className="t-caption text-text-body-muted">
                    {p.kind}, {p.data_location}, {h.label}
                    {p.health.latency_ms ? `, ${fmtInt(p.health.latency_ms)} ms` : ''}
                  </span>
                </span>
                <Where loc={p.data_location} />
              </li>
            )
          })}
        </ul>
      </section>
      {sovereignSwitch ? (
        <div className="flex items-center gap-3 rounded-item border border-border px-4 py-3">
          <Switch checked disabled aria-label="Tryb suwerenny" />
          <span className="flex flex-col">
            <span className="t-item">Tryb suwerenny</span>
            <span className="t-caption text-text-body-muted">
              Poufne dokumenty przed publikacją nigdy nie opuszczają Polski. Przełącznik jest zablokowany.
            </span>
          </span>
        </div>
      ) : null}
      <p className="t-mono m-0 text-muted">
        ostatnie 24 godziny: {data.usage_24h.calls.display} wywołań, {fmtInt(data.usage_24h.tokens_in)}{' '}
        tokenów wejścia, {fmtInt(data.usage_24h.tokens_out)} tokenów wyjścia
      </p>
    </Page>
  )
}
