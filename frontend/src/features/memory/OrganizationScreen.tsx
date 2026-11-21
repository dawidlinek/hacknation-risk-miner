import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { CalcNum, MemoryContract, RoleMemory } from '@/api/contracts/memory'
import { Page, PageHeader, Panel, SectionTitle } from '@/app/Page'
import { StatCard } from '@/components/common/StatCard'
import { SummaryCard } from '@/components/common/SummaryCard'
import { fmtMoney, fmtNip } from '@/lib/format'
import { organizationMemoryQuery } from './api'

const prov = (n: CalcNum) => `obliczenie, ${n.prov.method ?? ''}`
const nOf = (n: CalcNum) => n.prov.n ?? 0

function Stat({ label, num, attention }: { label: string; num: CalcNum; attention?: boolean }) {
  return (
    <StatCard
      label={label}
      value={num.display}
      n={nOf(num)}
      minN={5}
      provenance={prov(num)}
      attention={attention}
    />
  )
}

function RoleSection({ title, m }: { title: string; m: RoleMemory }) {
  const none = (m.contracts_total.prov.n ?? 0) === 0
  return (
    <section className="flex flex-col gap-3" aria-label={title}>
      <SectionTitle>{title}</SectionTitle>
      {none ? (
        <Panel>
          <span className="text-[14px] text-text-body-muted">Brak umów w tej roli w danych BZP.</span>
        </Panel>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Umowy łącznie" num={m.contracts_total} />
            <Stat label="Zakończone" num={m.completed} />
            <Stat label="W toku" num={m.ongoing} />
            <Stat label="Zakończone po terminie" num={m.late_share} />
            <Stat label="Mediana opóźnienia" num={m.median_delay_days} />
            <Stat label="Aneksy i zmiany umów" num={m.annexes} />
            <Stat label="Umowy ze zmianą" num={m.contracts_with_change_share} />
          </div>
          {m.change_kinds.length > 0 ? (
            <p className="m-0 text-[14px] text-text-body-muted">
              Typowe zmiany:{' '}
              {m.change_kinds
                .slice(0, 3)
                .map((k) => `${k.label} (${k.count})`)
                .join(', ')}
              .
            </p>
          ) : null}
          {m.top_risks.length > 0 ? (
            <Panel>
              <h3 className="t-item m-0">Najczęstsze ryzyka w zdarzeniach</h3>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {m.top_risks.map((r) => (
                  <li key={r.code} className="text-[14px]">
                    <span className="font-medium">{r.code}</span> {r.name}, {r.events}{' '}
                    <span className="t-mono text-muted">zdarzeń, {r.cases} postępowań</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
          <RecentContracts items={m.recent_contracts} />
        </>
      )}
    </section>
  )
}

function RecentContracts({ items }: { items: MemoryContract[] }) {
  if (items.length === 0) return null
  return (
    <Panel>
      <h3 className="t-item m-0">Ostatnie umowy</h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Ostatnie umowy">
        {items.map((c) => (
          <li key={c.contract_id} className="rounded-item bg-surface px-4 py-3">
            <Link to={c.href as never} className="font-medium">
              {c.title ?? c.ocid}
            </Link>
            <div className="t-mono text-muted">
              {c.signed_on ?? 'bez daty'}, {c.counterparty ?? 'brak kontrahenta'},{' '}
              {fmtMoney(c.value, { vat: true, digits: 0 })}, {c.state_label}
              {c.delay_days ? `, opóźnienie ${c.delay_days} dni` : ''}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

export function OrganizationScreen({ nip }: { nip: string }) {
  const { data: m } = useSuspenseQuery(organizationMemoryQuery(nip))
  const o = m.organization
  const flag = m.flags[0]
  const sentence = flag
    ? flag.text
    : `${o.name}: ${m.contractor.contracts_total.display} umów jako wykonawca i ${m.buyer.contracts_total.display} jako zamawiający.`
  return (
    <Page>
      <PageHeader
        breadcrumb={`Organizacje / NIP ${fmtNip(o.nip)}`}
        title={o.name}
        lead={m.note}
        subtitle={`Stan na ${m.as_of}, dane z ogłoszeń BZP`}
      />
      <SummaryCard
        eyebrow="Pamięć organizacji"
        sentence={sentence}
        provenance={flag ? `obliczenie, ${flag.rule}, n = ${flag.n}` : 'obliczenie z ogłoszeń BZP'}
      />
      {flag ? (
        <div role="note" className="rounded-item bg-attention-soft px-4 py-3 text-[14px] text-attention-text">
          <strong>{flag.title}.</strong> {flag.text} Mediana z 24 miesięcy: {m.load.history_median.display}.
        </div>
      ) : null}
      <RoleSection title="Jako wykonawca" m={m.contractor} />
      <RoleSection title="Jako zamawiający" m={m.buyer} />
    </Page>
  )
}
