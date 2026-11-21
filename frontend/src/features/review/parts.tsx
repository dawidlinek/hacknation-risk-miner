// biome-ignore-all lint/a11y/noLabelWithoutControl: labels wrap native selects
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import {
  type AboutFact,
  type CardAbout,
  type CardProposal,
  type Facet,
  proposalEvidence,
  type QueueFilter,
  type ReviewFacets,
} from './context'

const isExternal = (href: string) => /^https?:\/\//.test(href) || href.startsWith('/api/')

function FactValue({ f }: { f: AboutFact }) {
  if (!f.href) return <span>{f.value}</span>
  if (isExternal(f.href))
    return (
      <a
        href={f.href}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-baseline gap-1 text-text hover:underline"
      >
        {f.value}
        <ExternalLink aria-hidden className="size-3 shrink-0 self-center text-muted" />
        <span className="sr-only">(otwiera się w nowej karcie)</span>
      </a>
    )
  return (
    <Link to={f.href as never} className="text-text hover:underline">
      {f.value}
    </Link>
  )
}

/** What the item is about: the subject in one line, the model's reading, and the facts with links (project, contract, notice). */
export function SubjectBlock({
  about,
  hideLead = false,
  hideHref,
  heading,
}: {
  about: CardAbout
  /** the card heading; the subject title is not repeated when it says the same */
  heading?: string
  /** the lead is already shown elsewhere (e.g. as the model's option text) */
  hideLead?: boolean
  /** a fact linking here is already in the caption above */
  hideHref?: string
}) {
  const facts = about.facts.filter((f) => !hideHref || f.href !== hideHref)
  if (!about.title && facts.length === 0) return null
  return (
    <section
      aria-label="Czego dotyczy sprawa"
      className="flex flex-col gap-3 rounded-card border border-border p-5"
    >
      <span className="t-caption text-muted">Czego dotyczy</span>
      {about.title && about.title !== heading ? <p className="t-h3 m-0">{about.title}</p> : null}
      {about.lead && !hideLead ? (
        <p className="m-0 line-clamp-4 max-w-[760px] text-[15px] text-text-body-muted" title={about.lead}>
          {about.lead}
        </p>
      ) : null}
      {facts.length > 0 ? (
        <dl className="m-0 grid grid-cols-[minmax(120px,max-content)_1fr] gap-x-5 gap-y-1.5 text-[14px]">
          {facts.map((f) => (
            <div key={`${f.label}-${f.value}`} className="contents">
              <dt className="text-muted">{f.label}</dt>
              <dd className="m-0 min-w-0 break-words">
                <FactValue f={f} />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  )
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="t-item m-0">{title}</h3>
      {children}
    </div>
  )
}

/** A catalogue proposal in full: which risk, its definition, why the model proposes it (cases, examples), and how it
 * differs from the risks already in the catalogue. */
export function ProposalPanel({ proposal: p }: { proposal: CardProposal }) {
  const evidence = proposalEvidence(p)
  return (
    <section
      aria-label="Proponowane ryzyko"
      className="flex flex-col gap-4 rounded-card border border-border p-5"
    >
      <div className="flex flex-col gap-1">
        <span className="t-caption text-muted">
          Proponowane ryzyko, sektor {p.sector_label}
          {p.parent_code ? `, podkategoria ${p.parent_code}` : ', ryzyko główne'}
          {p.proposed_by ? `, zaproponował: ${p.proposed_by}` : ''}
        </span>
        <p className="t-h3 m-0">
          <span className="t-mono mr-2">{p.code}</span>
          {p.name}
        </p>
        <p className="m-0 max-w-[760px] text-[15px] text-text-body-muted">
          {p.description ?? 'Propozycja nie ma jeszcze opisu. Opis dopiszesz w Katalogu po dodaniu ryzyka.'}
        </p>
      </div>

      {p.copied_from_wodkan ? (
        <p className="m-0 rounded-inner bg-soft px-3.5 py-2.5 text-[14px] text-text-body-muted">
          Propozycja pochodzi z pakietu sektora wodociągi i kanalizacja. Liczby i przykłady poniżej dotyczą
          umów z tego sektora.
        </p>
      ) : null}

      {p.rationale || evidence.length > 0 ? (
        <Block title="Dlaczego model to proponuje">
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-[14px]">
            {p.rationale ? <li>{p.rationale}</li> : null}
            {evidence.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </Block>
      ) : null}

      {p.examples.length > 0 ? (
        <Block title={`Przykłady ze źródeł (${p.examples.length})`}>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {p.examples.map((e) => (
              <li
                key={`${e.label}-${e.quote.slice(0, 40)}`}
                className="flex flex-col gap-1 rounded-item bg-soft px-4 py-3"
              >
                <blockquote className="m-0 text-[14px] leading-[1.55]">„{e.quote}”</blockquote>
                <span className="t-caption flex flex-wrap items-center gap-x-2 text-muted">
                  {e.href ? (
                    <a
                      href={e.href}
                      target="_blank"
                      rel="noreferrer"
                      className="t-mono text-text-secondary hover:underline"
                    >
                      {e.label} ↗<span className="sr-only">(otwiera się w nowej karcie)</span>
                    </a>
                  ) : (
                    <span className="t-mono">{e.label}</span>
                  )}
                  {e.context ? <span className="min-w-0 truncate">{e.context}</span> : null}
                  {e.verified ? <span className="text-success-text">cytat potwierdzony</span> : null}
                </span>
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      <Block title="Czym różni się od ryzyk w katalogu">
        {p.closest.length === 0 ? (
          <p className="m-0 text-[14px] text-text-body-muted">
            Model nie wskazał podobnego ryzyka w obecnym katalogu.
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {p.closest.map((c) => (
              <li key={c.code} className="flex flex-col gap-0.5 rounded-item bg-soft px-4 py-2.5 text-[14px]">
                <span>
                  <span className="t-mono mr-1.5">{c.code}</span>
                  {c.name}
                </span>
                <span className="t-caption text-muted">
                  {c.why}
                  {c.description ? `. W katalogu: ${c.description}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Block>

      {p.events.length > 0 || p.signals.length > 0 || p.clauses.length > 0 ? (
        <details className="group">
          <summary className="t-caption cursor-pointer text-text-secondary hover:underline">
            Po czym je rozpoznać i proponowany zapis w umowie
          </summary>
          <div className="mt-3 flex flex-col gap-4">
            {p.events.length > 0 || p.signals.length > 0 ? (
              <Block title="Po czym je rozpoznać">
                <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-[14px]">
                  {p.events.length > 0 ? (
                    <li>Zdarzenia w umowie: {p.events.map((e) => e.name).join(', ')}.</li>
                  ) : null}
                  {p.signals.map((s) => (
                    <li key={s.text}>
                      Sygnał w dokumentach: <span className="t-mono text-[13px]">{s.text}</span>
                    </li>
                  ))}
                </ul>
              </Block>
            ) : null}

            {p.clauses.length > 0 ? (
              <Block title="Proponowany zapis w umowie">
                <p className="m-0 rounded-item bg-soft px-4 py-3 text-[14px] leading-[1.55]">
                  {p.clauses[0]}
                </p>
              </Block>
            ) : null}
          </div>
        </details>
      ) : null}
    </section>
  )
}

function FacetSelect({
  label,
  value,
  all,
  options,
  onChange,
}: {
  label: string
  value: string | undefined
  all: string
  options: Facet[]
  onChange: (v: string | undefined) => void
}) {
  const total = options.reduce((a, o) => a + o.n, 0)
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="t-caption text-muted">{label}</span>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="h-9.5 max-w-[340px] rounded-pill border border-border bg-surface px-3 text-[14px]"
      >
        <option value="">
          {all} ({total.toLocaleString('pl-PL')})
        </option>
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label} ({o.n.toLocaleString('pl-PL')})
          </option>
        ))}
      </select>
    </label>
  )
}

/** Type and project filters with counts that add up, the order, and the strength split of the current list. */
export function QueueFilters({
  facets,
  filter,
  codeFilter,
  showStrength = true,
  onChange,
}: {
  facets: ReviewFacets | undefined
  filter: QueueFilter
  codeFilter: string | undefined
  /** evidence strength and its order make sense only where items carry a source quote (events, facts) */
  showStrength?: boolean
  onChange: (f: QueueFilter) => void
}) {
  if (!facets) return <div className="h-[62px]" aria-hidden />
  if (facets.total === 0 && !filter.type && !filter.project && !codeFilter) return null
  const strength = Object.fromEntries(facets.strength.map((s) => [s.key, s]))
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
      {facets.types.length > 1 || filter.type ? (
        <FacetSelect
          label="Rodzaj"
          value={filter.type}
          all="Wszystkie rodzaje"
          options={facets.types}
          onChange={(type) => onChange({ ...filter, type })}
        />
      ) : null}
      {facets.projects.length > 1 || filter.project ? (
        <FacetSelect
          label="Projekt"
          value={filter.project}
          all="Wszystkie projekty"
          options={facets.projects}
          onChange={(project) => onChange({ ...filter, project })}
        />
      ) : null}
      {showStrength ? (
        <label className="flex flex-col gap-1">
          <span className="t-caption text-muted">Kolejność</span>
          <select
            value={filter.sort ?? 'strength'}
            onChange={(e) => onChange({ ...filter, sort: e.target.value as QueueFilter['sort'] })}
            className="h-9.5 rounded-pill border border-border bg-surface px-3 text-[14px]"
          >
            <option value="strength">Najpierw gotowe do akceptacji</option>
            <option value="queue">Od najstarszych</option>
          </select>
        </label>
      ) : null}
      {codeFilter ? (
        <button
          type="button"
          onClick={() => onChange({ ...filter, code: '' })}
          className="inline-flex h-9.5 items-center gap-2 rounded-pill bg-ink px-3.5 text-[14px] text-on-ink"
          aria-label={`Usuń filtr ryzyka ${codeFilter}`}
        >
          Ryzyko {codeFilter} <span aria-hidden>×</span>
        </button>
      ) : null}
      <p className="t-caption m-0 ml-auto flex flex-wrap gap-x-3 text-muted">
        <span className="sr-only">Siła dowodu w tej liście:</span>
        {(['ready', 'check', 'weak'] as const)
          .filter((k) => showStrength && strength[k] && (strength.ready || strength.check))
          .map((k) => (
            <span key={k} className={cn(k === 'ready' && 'text-success-text')}>
              {strength[k].label}: <span className="t-mono">{strength[k].n.toLocaleString('pl-PL')}</span>
            </span>
          ))}
      </p>
    </div>
  )
}
