import { screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import type { CalcNum, OrganizationMemory, RoleMemory } from '@/api/contracts/memory'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'

const num = (value: number | null, display: string, n: number): CalcNum => ({
  value: n < 5 ? null : value,
  display: n < 5 ? 'za mało danych' : display,
  unit: 'count',
  prov: { role: 'calc', review_status: 'auto', n, method: 'count(test)' },
})
const money = { amount: '1000000', currency: 'PLN', vat_basis: 'gross' as const }
const role = (n: number): RoleMemory => ({
  role: 'contractor',
  contracts_total: num(n, String(n), n),
  completed: num(n, String(n), n),
  ongoing: num(3, '3', n),
  late_share: num(0.4, '40,0%', n),
  median_delay_days: num(30, '30 dni', n),
  annexes: num(9, '9', n),
  contracts_with_change_share: num(0.3, '30,0%', n),
  change_kinds: [{ kind: 'time', label: 'zmiana terminu', count: 5, share: num(0.5, '50%', 10) }],
  top_risks: [
    {
      code: 'R06',
      name: 'Harmonogram',
      events: 4,
      cases: 3,
      count: num(4, '4', 4),
      href: '/przeglad?ryzyko=R06',
    },
  ],
  recent_contracts: [
    {
      contract_id: 1,
      title: 'Budowa kanalizacji w Kamionce',
      ocid: 'ocds-1',
      href: '/projekty/ocds-1',
      signed_on: '2026-01-02',
      planned_end_on: null,
      counterparty: 'Gmina Kamionka',
      value: money,
      state: 'ongoing',
      state_label: 'w toku',
      delay_days: null,
    },
  ],
  ongoing_value: { money, n, method: 'sum' },
})

const memory = (n: number, flags = true): OrganizationMemory => ({
  organization: {
    nip: '5210421928',
    name: 'Wykonawca Test Sp. z o.o.',
    roles: ['contractor'],
    province: null,
    city: null,
    nip_valid: true,
  },
  as_of: '2026-11-21',
  min_n: 5,
  contractor: role(n),
  buyer: role(0),
  load: {
    ongoing: num(12, '12', n),
    history_median: num(4, '4', n),
    ongoing_value: { money, n, method: 'sum' },
    history_median_value: { money, n, method: 'median' },
    months: 24,
  },
  flags: flags
    ? [
        {
          code: 'R12',
          rule: 'ongoing >= 5',
          title: 'Obciążenie wykonawcy',
          text: 'Wykonawca ma teraz 12 umów w toku.',
          risk_codes: ['R12'],
          n,
        },
      ]
    : [],
  note: 'Neutralne fakty z ogłoszeń BZP.',
})

describe('Pamięć organizacji', () => {
  it('shows history, the R12 flag and a link to recent contracts', async () => {
    server.use(http.get('/api/organizations/:nip/memory', () => HttpResponse.json(memory(40))))
    await renderRoute('/organizacje/5210421928')
    expect(await screen.findByRole('heading', { name: 'Wykonawca Test Sp. z o.o.' })).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Obciążenie wykonawcy')
    expect(screen.getByRole('link', { name: 'Budowa kanalizacji w Kamionce' })).toHaveAttribute(
      'href',
      '/projekty/ocds-1',
    )
    expect(screen.getByText(/zmiana terminu \(5\)/)).toBeInTheDocument()
  })
  it('shows "za mało danych" below n = 5', async () => {
    server.use(http.get('/api/organizations/:nip/memory', () => HttpResponse.json(memory(3, false))))
    await renderRoute('/organizacje/5210421928')
    await screen.findByRole('heading', { name: 'Wykonawca Test Sp. z o.o.' })
    expect(screen.getAllByText('za mało danych').length).toBeGreaterThan(3)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })
})
