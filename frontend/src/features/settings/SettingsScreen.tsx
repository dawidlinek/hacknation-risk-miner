import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import type { LlmProvider, LlmSettings, LlmTask } from '@/api/contracts/settings'
import { Page, PageHeader, TwoCol } from '@/app/Page'
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

/** Polish names for task keys the API does not label (fallback; the API label wins when it is not the raw key). */
const TASK_PL: Record<string, string> = {
  document_facts: 'Fakty z dokumentów projektu',
  extract_features: 'Cechy inwestycji z PFU i PPU',
  extract_features_text: 'Cechy inwestycji z opisu',
  redpen_scan: 'Czerwony długopis: uwagi w dokumentach',
  classify_causes: 'Klasyfikacja przyczyn zmian umów',
  chat: 'Rozmowa o analizie i projekcie',
  nl2sql: 'Zapytaj pamięć',
  import_mapping: 'Agent importu: mapowanie kolumn',
  catalogue_proposals: 'Propozycje do katalogu ryzyk',
  review_phrasing: 'Pytania w przeglądzie',
  rescore_gold: 'Przeliczenie po decyzji eksperta',
}
const taskName = (t: LlmTask) =>
  t.label && t.label !== t.task ? t.label : (TASK_PL[t.task] ?? 'Zadanie modelu')

const ALIAS_PL: Record<string, string> = {
  fast: 'szybki',
  strong: 'mocny',
  best: 'najlepszy',
  bulk: 'masowy',
  sovereign: 'suwerenny',
  sovereign_alt: 'suwerenny zapasowy',
  emergency: 'awaryjny',
}
const aliasPl = (a: string) => ALIAS_PL[a] ?? a

/** "global (Gemini Developer API)" -> "chmura, Gemini Developer API". */
function locPl(loc: string): string {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(loc)
  const where = m?.[1] ?? loc
  const detail = (m?.[2] ?? '')
    .replace(/routed to upstream providers/i, 'dostawcy zewnętrzni')
    .replace(/^nagrane odpowiedzi$/i, 'nagrane odpowiedzi')
  if (/^PL\b/i.test(where)) return detail ? `Polska, ${detail}` : 'Polska'
  if (/^global/i.test(where)) return detail ? `chmura, ${detail}` : 'chmura'
  return detail ? `${where}, ${detail}` : where
}

const KIND_PL: Record<string, string> = {
  google_genai: 'API Gemini',
  openai_compatible: 'API zgodne z OpenAI',
  replay: 'nagrane odpowiedzi',
}

function Where({ loc, label }: { loc: string; label?: string }) {
  const pl = isPl(loc)
  return (
    <span
      className={cn(
        't-mono rounded-pill px-2.5 py-1 text-right',
        pl ? 'bg-success-soft text-success-text' : 'bg-soft-2 text-text-secondary',
      )}
    >
      {label ?? (pl ? 'Polska' : 'chmura')}
    </span>
  )
}

const HEALTH: Record<string, { dot: string; label: string }> = {
  up: { dot: 'bg-success', label: 'działa' },
  configured: { dot: 'bg-success', label: 'skonfigurowany' },
  standby: { dot: 'bg-border', label: 'w gotowości' },
  down: { dot: 'bg-attention', label: 'nie odpowiada' },
  unknown: { dot: 'bg-border', label: 'nie sprawdzono' },
}

interface TaskRow {
  task: string
  name: string
  data: string
  pub?: LlmTask
  conf?: LlmTask
}

function groupTasks(tasks: LlmTask[]): TaskRow[] {
  const rows = new Map<string, TaskRow>()
  for (const t of tasks) {
    const r = rows.get(t.task) ?? { task: t.task, name: taskName(t), data: '' }
    if (t.sensitivity === 'confidential') r.conf = t
    else {
      r.pub = t
      r.data = t.data_label
    }
    rows.set(t.task, r)
  }
  return [...rows.values()]
}

function ModelCell({ t, caption }: { t?: LlmTask; caption: string }) {
  if (!t) return <span className="t-caption text-text-body-muted">{caption}: nie dotyczy</span>
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="t-mono">{t.model ?? 'brak modelu'}</span>
      <span className="t-mono text-muted">
        {caption}, {aliasPl(t.alias)}
      </span>
    </span>
  )
}

/** Read-only config fragment rebuilt from the API values (never hardcoded). */
function configFragment(data: LlmSettings): string {
  const pad = (s: string, n: number) => s.padEnd(n)
  const models = Object.values(data.models ?? {}).filter((m) => m.provider)
  const w = Math.max(0, ...models.map((m) => m.alias.length)) + 1
  const lines = ['models:']
  for (const m of models) lines.push(`  ${pad(`${m.alias}:`, w)} ${m.provider}:${m.model}`)
  for (const sens of ['public', 'confidential'] as const) {
    const per = data.tasks.filter((t) => t.sensitivity === sens)
    if (!per.length) continue
    if (sens === 'public') lines.push('routing:')
    lines.push(`  ${sens}:`)
    for (const t of per) lines.push(`    ${t.task}: ${t.alias}`)
  }
  return lines.join('\n')
}

function ProviderRow({ p }: { p: LlmProvider }) {
  const h = HEALTH[p.health.status] ?? HEALTH.unknown
  return (
    <li className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-item bg-soft px-4 py-3">
      <span aria-hidden className={cn('size-2.5 rounded-pill', h.dot)} />
      <span className="flex min-w-0 flex-col">
        <span className="t-item t-mono">{p.id}</span>
        <span className="t-caption text-text-body-muted">
          {KIND_PL[p.kind] ?? 'dostawca modeli'}, {h.label}
          {p.configured ? '' : ', brak klucza'}
          {p.health.latency_ms ? `, ${fmtInt(p.health.latency_ms)} ms` : ''}
        </span>
      </span>
      <Where loc={p.data_location} label={locPl(p.data_location)} />
    </li>
  )
}

export function SettingsScreen() {
  const { data } = useSuspenseQuery(settingsQuery)
  const sovereignSwitch = useFeature('sovereign_switch')
  const confidential = data.tasks.filter((t) => t.sensitivity === 'confidential')
  const outside = confidential.filter((t) => !t.sovereign).length
  const rows = groupTasks(data.tasks)
  return (
    <Page>
      <PageHeader
        eyebrow="z pliku config.yaml, zmiana bez zmiany kodu"
        title="Modele i miejsce przetwarzania"
        lead="Gdzie trafiają dane i który model je czyta. Zmiany robi się w pliku konfiguracji, tu jest widok tylko do odczytu."
      />
      <SummaryCard
        eyebrow="Gdzie są dane"
        sentence={
          outside === 0
            ? 'Poufne dokumenty czyta wyłącznie model w Polsce. Dane publiczne mogą trafiać do modeli w chmurze.'
            : `${outside} zadań z poufnymi danymi nie jest przypisanych do modelu w Polsce.`
        }
        provenance={`z konfiguracji, ${rows.length} zadań, ${data.providers.length} dostawców`}
      />
      <TwoCol
        main={
          <>
            <section className="flex flex-col gap-2" aria-labelledby="route-h">
              <h2 id="route-h" className="t-h3 m-0">
                Kto wykonuje które zadanie
              </h2>
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {rows.map((r) => (
                  <li
                    key={r.task}
                    className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3.5 rounded-item border border-divider px-4 py-3.5"
                  >
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="t-item">{r.name}</span>
                      {r.data ? <span className="t-caption text-text-body-muted">{r.data}</span> : null}
                    </span>
                    <span className="flex min-w-0 flex-col gap-1.5">
                      <ModelCell t={r.pub} caption="dane publiczne" />
                      {r.pub ? <Where loc={r.pub.data_location} label={locPl(r.pub.data_location)} /> : null}
                    </span>
                    <span className="flex min-w-0 flex-col gap-1.5">
                      <ModelCell t={r.conf} caption="dokumenty poufne" />
                      {r.conf ? (
                        <Where loc={r.conf.data_location} label={locPl(r.conf.data_location)} />
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="flex flex-col gap-2" aria-labelledby="prov-h">
              <h2 id="prov-h" className="t-h3 m-0">
                Dostawcy
              </h2>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {data.providers.map((p) => (
                  <ProviderRow key={p.id} p={p} />
                ))}
              </ul>
            </section>
          </>
        }
        aside={
          <>
            {sovereignSwitch ? (
              <section
                aria-labelledby="sov-h"
                className="flex flex-col gap-2.5 rounded-panel bg-success-soft p-5.5 text-success-text"
              >
                <div className="flex items-center justify-between gap-2.5">
                  <h2 id="sov-h" className="t-h3 m-0">
                    Tryb suwerenny
                  </h2>
                  <Switch checked disabled aria-label="Tryb suwerenny włączony na stałe dla poufnych" />
                </div>
                <span className="t-body">
                  Dla poufnych dokumentów nie da się go wyłączyć. Jeśli model w Polsce jest niedostępny,
                  zadanie czeka w kolejce i nie trafia do chmury.
                </span>
                <span className="t-mono">
                  ostatnie 24 godziny: {data.usage_24h.calls.display} wywołań modeli, poufne zadania poza
                  Polską: {outside}
                </span>
              </section>
            ) : null}
            <section
              aria-labelledby="cfg-h"
              className="flex flex-col gap-2.5 rounded-panel border border-divider p-5.5"
            >
              <h2 id="cfg-h" className="t-h3 m-0">
                Fragment config.yaml
              </h2>
              <pre className="m-0 overflow-x-auto rounded-item bg-ink px-4 py-3.5 font-mono text-[12.5px] leading-[1.6] text-on-ink">
                {configFragment(data)}
              </pre>
              <span className="t-caption text-text-body-muted">
                Panel pokazuje konfigurację; zmienia się ją w pliku, bez zmiany kodu.
              </span>
            </section>
          </>
        }
      />
      <p className="t-mono m-0 text-muted">
        ostatnie 24 godziny: {data.usage_24h.calls.display} wywołań, {fmtInt(data.usage_24h.tokens_in)}{' '}
        tokenów wejścia, {fmtInt(data.usage_24h.tokens_out)} tokenów wyjścia
      </p>
    </Page>
  )
}
