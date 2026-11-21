import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'
import { cardHandler } from './testkit'
import type { RealAuditEntry, RealHistory } from './types'

const entry = (id: number, over: Partial<RealAuditEntry>): RealAuditEntry => ({
  id,
  audit_id: id,
  at: '2026-11-21T13:10:00+01:00',
  actor_kind: 'expert',
  actor_label: 'Ekspert',
  action: 'review.approve',
  action_label: 'zatwierdził zdarzenie ryzyka',
  object: { label: 'zdarzenie ryzyka w RM-2026-003', href: '/projekty/RM-2026-003' },
  table: 'risk_event',
  row_id: 1187,
  before: 'review_status: proposed',
  after: 'review_status: approved',
  why: 'sprawa #812',
  version: `v${id}`,
  can_restore: false,
  ...over,
})

const history: RealHistory = {
  record_version: 'v3',
  versions: [
    { version: 'v1', label: 'v1' },
    { version: 'v2', label: 'v2' },
    { version: 'v3', label: 'v3' },
  ],
  items: [
    entry(3, { can_restore: true }),
    entry(2, {
      actor_kind: 'model',
      actor_label: 'Model Bielik 11B (Polska)',
      action_label: 'zaproponował zdarzenie ryzyka',
    }),
    entry(1, { actor_kind: 'system', actor_label: 'System', action_label: 'zaimportował rekord' }),
  ],
}

const asExpert = () => localStorage.setItem('rm.mockRole', 'expert')

describe('2.6 Historia zmian projektu', () => {
  it('lists entries, stats, filters by actor and offers restore only where restorable', async () => {
    asExpert()
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/history', () => HttpResponse.json(history)),
    )
    await renderRoute('/projekty/RM-2026-003/historia')
    const list = await screen.findByRole('list', { name: 'Historia zmian projektu' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByTestId('history-stats')).toHaveTextContent(
      'Wersja rekordu v3, decyzje ekspertów 1, propozycje modelu 1, zmiany z systemu 1',
    )
    expect(screen.getAllByRole('button', { name: /Przywróć wartość/ })).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'Propozycje modelu' }))
    expect(
      within(await screen.findByRole('list', { name: 'Historia zmian projektu' })).getAllByRole('listitem'),
    ).toHaveLength(1)
    expect(screen.queryByText('zaimportował rekord')).not.toBeInTheDocument()
    expect(screen.getByText(/Dziennik tylko do dopisywania/)).toBeInTheDocument()
  })

  it('restore asks for a reason, posts it and reports the new entry', async () => {
    asExpert()
    let body: unknown = null
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/history', () => HttpResponse.json(history)),
      http.post('/api/audit/:id/restore', async ({ request, params }) => {
        body = { id: params.id, ...((await request.json()) as object) }
        return HttpResponse.json({ review_id: 9, audit_id: 10 })
      }),
    )
    await renderRoute('/projekty/RM-2026-003/historia')
    await userEvent.click(await screen.findByRole('button', { name: /Przywróć wartość/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Powstanie nowy wpis w dzienniku/)).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: 'Przywróć' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByRole('textbox'), 'pomyłka przy zatwierdzeniu')
    await userEvent.click(confirm)
    await waitFor(() => expect(body).toEqual({ id: '3', reason: 'pomyłka przy zatwierdzeniu' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('409 keeps the list and shows the backend reason', async () => {
    asExpert()
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/history', () => HttpResponse.json(history)),
      http.post('/api/audit/:id/restore', () =>
        HttpResponse.json(
          {
            detail: 'Rekord zmienił się po tej decyzji, przywrócenie nadpisałoby nowszą zmianę.',
            code: 'stale',
          },
          { status: 409 },
        ),
      ),
    )
    await renderRoute('/projekty/RM-2026-003/historia')
    await userEvent.click(await screen.findByRole('button', { name: /Przywróć wartość/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByRole('textbox'), 'test')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Przywróć' }))
    expect(await screen.findByText(/przywrócenie nadpisałoby nowszą zmianę/)).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(3)
  })

  it('compare shows the field differences between a version and the current one', async () => {
    asExpert()
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/history', () => HttpResponse.json(history)),
      http.get('/api/projects/:id/history/compare', ({ request }) => {
        const u = new URL(request.url)
        expect([u.searchParams.get('from'), u.searchParams.get('to')]).toEqual(['v1', 'v3'])
        return HttpResponse.json({
          from: 'v1',
          to: 'v3',
          changes: [
            { table: 'project_procedure', row_id: 4, field: 'lots', before: '[1]', after: '[1, 2, 3, 4]' },
          ],
        })
      }),
    )
    await renderRoute('/projekty/RM-2026-003/historia')
    await userEvent.selectOptions(await screen.findByLabelText(/Porównaj wersję/), 'v1')
    const region = await screen.findByRole('region', { name: 'Różnice między wersjami' })
    expect(await within(region).findByText('lots')).toBeInTheDocument()
    expect(within(region).getByText('[1, 2, 3, 4]')).toBeInTheDocument()
  })

  it('empty filter result and public redirect', async () => {
    asExpert()
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/history', () =>
        HttpResponse.json({ ...history, items: [history.items[0]] }),
      ),
    )
    await renderRoute('/projekty/RM-2026-003/historia?kto=system')
    expect(await screen.findByText('Brak wpisów tego rodzaju.')).toBeInTheDocument()
  })

  it('public visitors are sent to the login screen', async () => {
    server.use(cardHandler())
    const { router } = await renderRoute('/projekty/RM-2026-003/historia')
    await waitFor(() => expect(router.state.location.pathname).toBe('/zaloguj'))
  })
})

describe('D3 Historia', () => {
  it('requests the category for the pill, shows object links and entry ids', async () => {
    asExpert()
    const seen: string[] = []
    server.use(
      http.get('/api/audit', ({ request }) => {
        seen.push(new URL(request.url).search)
        return HttpResponse.json({
          total: 1,
          limit: 200,
          offset: 0,
          items: [
            entry(7, {
              table: 'catalogue_version',
              row_id: null,
              object: { label: 'Katalogu wiedzy', href: '/katalog' },
              note: 'katalog v1.2 → v1.3',
              action_label: 'zapisał wersję',
            }),
          ],
        })
      }),
    )
    await renderRoute('/historia')
    expect(await screen.findByRole('link', { name: 'Katalogu wiedzy' })).toHaveAttribute('href', '/katalog')
    expect(screen.getByText('kat-7')).toBeInTheDocument()
    expect(screen.getByText('katalog v1.2 → v1.3')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Katalog' }))
    await waitFor(() => expect(seen.some((s) => s.includes('category=catalogue'))).toBe(true))
  })

  it('day filter sends since and until', async () => {
    asExpert()
    const seen: string[] = []
    server.use(
      http.get('/api/audit', ({ request }) => {
        seen.push(new URL(request.url).search)
        return HttpResponse.json({ total: 0, limit: 200, offset: 0, items: [] })
      }),
    )
    await renderRoute('/historia?dzien=2026-11-21')
    expect(await screen.findByText('Brak wpisów dla tych filtrów.')).toBeInTheDocument()
    expect(seen[0]).toContain('since=')
    expect(seen[0]).toContain('until=')
  })

  it('public visitors are sent to the login screen', async () => {
    const { router } = await renderRoute('/historia')
    await waitFor(() => expect(router.state.location.pathname).toBe('/zaloguj'))
  })
})

describe('read-only account', () => {
  it('Przywróć is disabled with the reason', async () => {
    server.use(
      http.get('/api/auth/me', () =>
        HttpResponse.json({ role: 'expert', name: 'juror', initials: 'J', read_only: true }),
      ),
      cardHandler(),
      http.get('/api/projects/:id/history', () => HttpResponse.json(history)),
    )
    await renderRoute('/projekty/RM-2026-003/historia')
    const btn = await screen.findByRole('button', { name: /Przywróć wartość/ })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'To konto jest tylko do odczytu.')
  })
})
