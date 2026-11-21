import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'
import { cardHandler } from '../audit/testkit'
import { factDisplay, factLabel, GROUPS, lineText, stepsSummary, stillProcessing } from './analysis'
import type { RealAnalysis, RealChangesSince, RealDocuments, RealStep } from './types'

const step = (key: RealStep['key'], state: RealStep['state'], extra: Partial<RealStep> = {}): RealStep => ({
  key,
  label: key,
  state,
  ...extra,
})

describe('analysis helpers', () => {
  it('polls while something runs or extraction is missing, stops at linking or on failure', () => {
    expect(
      stillProcessing([
        step('upload', 'done'),
        step('ocr', 'running'),
        step('extraction', 'pending'),
        step('linking', 'pending'),
      ]),
    ).toBe(true)
    expect(
      stillProcessing([
        step('upload', 'done'),
        step('ocr', 'done'),
        step('extraction', 'done'),
        step('linking', 'pending'),
      ]),
    ).toBe(false)
    expect(
      stillProcessing([
        step('upload', 'done'),
        step('ocr', 'done'),
        step('extraction', 'done'),
        step('linking', 'done'),
      ]),
    ).toBe(false)
    expect(
      stillProcessing([
        step('upload', 'done'),
        step('ocr', 'failed'),
        step('extraction', 'pending'),
        step('linking', 'pending'),
      ]),
    ).toBe(false)
  })
  it('summary sentences', () => {
    const labelled = (k: RealStep['key'], l: string, s: RealStep['state']) => step(k, s, { label: l })
    expect(
      stepsSummary([
        labelled('upload', 'Wczytanie pliku', 'done'),
        labelled('ocr', 'Rozpoznanie tekstu (OCR)', 'running'),
      ]),
    ).toBe('Etap 2 z 2: rozpoznanie tekstu (ocr), w toku.')
    expect(stepsSummary([step('upload', 'done'), step('linking', 'done')])).toContain(
      'Wnioski czekają na decyzję eksperta',
    )
    expect(stepsSummary([step('ocr', 'failed', { label: 'OCR', error: 'brak tesseract' })])).toBe(
      'Błąd na etapie: ocr. brak tesseract',
    )
  })
  it('fact labels and display values', () => {
    expect(factLabel({ field: 'planned_end_calc' })).toBe('nowy planowany koniec umowy')
    expect(factLabel({ field: 'some_field' })).toBe('some field')
    expect(factDisplay({ field: 'x', value: '2026-06-05' })).toBe('05.06.2026')
    expect(factDisplay({ field: 'x', value: 1.5 })).toBe('1,5')
    expect(factDisplay({ field: 'x', value: ['a', 'b'] })).toBe('a, b')
    expect(factDisplay({ field: 'x', value: null })).toBe('brak')
    expect(factDisplay({ field: 'x', value: 1, display: '1 miesiąc' })).toBe('1 miesiąc')
  })
  it('change lines and groups', () => {
    expect(GROUPS.map((g) => g.title)).toEqual(['Potwierdzone', 'Zmienione', 'Nowe', 'Zamknięte'])
    expect(lineText({ key: 'a', label: 'x', before: '05.05.2026', after: '05.06.2026' })).toBe(
      '05.05.2026 → 05.06.2026',
    )
    expect(lineText({ key: 'b', label: 'x', value: 'R18, do przeglądu' })).toBe('R18, do przeglądu')
  })
})

const docs: RealDocuments = {
  summary: 'Mamy 1 ogłoszenie z BZP. Brakuje 1 dokumentu z budowy.',
  have: 1,
  expected_total: 2,
  expected: [
    { key: 'swz', title: 'SWZ', ext: 'PDF', have: true, state_label: 'mamy dokument', unlocks: 'a' },
    {
      key: 'protokol',
      title: 'Protokół konieczności lub odbioru',
      ext: 'PDF',
      have: false,
      state_label: 'nie ma w paczce',
      unlocks: 'Pokaże zmiany zakresu i terminu.',
    },
  ],
  public: [
    {
      kind: 'document',
      key: 'doc:77',
      object_id: '77',
      ref: 'zagrodno.pdf',
      title: 'Protokół aneksowania',
      ext: 'pdf',
      date: null,
      facts: 0,
      review_status: 'auto',
      status_label: 'dokument z postępowania',
    },
  ],
}

const analysis = (over: Partial<RealAnalysis> = {}): RealAnalysis => ({
  document: {
    id: 77,
    filename: 'zagrodno.pdf',
    title: 'Protokół aneksowania',
    sensitivity: 'confidential',
    pages: 1,
    doc_kind_label: 'Protokół konieczności aneksowania umowy',
    doc_date: '2026-05-05',
    level: 'contract',
  },
  steps: [
    { key: 'upload', label: 'Wczytanie pliku', state: 'done', detail: '1 str.' },
    { key: 'ocr', label: 'Rozpoznanie tekstu (OCR)', state: 'done', detail: 'dokument ma warstwę tekstu' },
    { key: 'extraction', label: 'Odczyt faktów', state: 'done' },
    { key: 'linking', label: 'Powiązanie z projektem i umową', state: 'done' },
  ],
  facts: [
    {
      field: 'planned_end_calc',
      value: '2026-06-05',
      origin: 'CALC',
      quote: '3 miesiące od dnia zawarcia umowy',
      page: 1,
      verification: 'exact',
    },
  ],
  causes: [
    {
      code: 'R03',
      origin: 'CALC',
      why: 'Kolizja z siecią wodociągową',
      quote: 'kolizji z siecią wodociągową uniemożliwiające posadowienie pompowni numer PM2',
      page: 1,
      verification: 'exact',
    },
  ],
  effects: [],
  flags: [],
  link: {
    project: { rm_id: 'RM-2026-002', method: 'exact_id', score: 1 },
    contract: { contract_id: 153400, score: 0.95, contractor: 'PTB' },
    checks: [],
  },
  review_items: [
    {
      id: 812,
      kind: 'fact',
      title: 'Zmiana umowy z dokumentu: termin +31 dni',
      status: 'open',
      href: '/przeglad?sprawa=812',
    },
  ],
  project_rm_id: 'RM-2026-002',
  ...over,
})

const changes: RealChangesSince = {
  document: { id: 77, kind_label: 'Protokół', date: '2026-05-05' },
  groups: {
    potwierdzone: [
      {
        key: 'kpo',
        label: 'Numer KPO z dokumentu',
        value: 'KPOD.03.15-IW.13-0004/25',
        where: 'zgodny z projektem',
      },
    ],
    zmienione: [
      {
        key: 'planned_end',
        label: 'Planowany koniec umowy',
        before: '05.05.2026',
        after: '05.06.2026',
        why: 'Protokół z 05.05.2026',
      },
    ],
    nowe: [{ key: 'event:1', label: 'Efekt użytkowy opóźniony', value: 'R18, do przeglądu' }],
    zamkniete: [],
  },
  counts: { potwierdzone: 1, zmienione: 1, nowe: 1, zamkniete: 0 },
  aggregates: {},
  review_items: [{ id: 812, title: 'x', status: 'open', kind: 'fact', href: '/przeglad?sprawa=812' }],
}

const base = () => [
  cardHandler({ have: 1, expected: 2 }),
  http.get('/api/projects/:id/documents', () => HttpResponse.json(docs)),
]

describe('G5 new document panel', () => {
  it('shows steps, facts with verified quotes, the diff and links to the review queue', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(analysis())),
      http.get('/api/projects/:id/changes-since', ({ request }) => {
        expect(new URL(request.url).searchParams.get('document_id')).toBe('77')
        return HttpResponse.json(changes)
      }),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    const steps = await screen.findByRole('list', { name: 'Etapy przetwarzania' })
    expect(within(steps).getAllByText('gotowe')).toHaveLength(4)
    expect(screen.getByText(/Dokument przetworzony/)).toBeInTheDocument()
    expect(screen.getByText(/aneksowania umowy, poufny, 05.05.2026/)).toBeInTheDocument()
    expect(screen.getByText(/nowy planowany koniec umowy: 05.06.2026/)).toBeInTheDocument()
    expect(screen.getByText('3 miesiące od dnia zawarcia umowy')).toBeInTheDocument()
    expect(screen.getAllByText('cytat sprawdzony na stronie').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/Przyczyna R03: Kolizja z siecią wodociągową/)).toBeInTheDocument()
    // Co się zmieniło
    const diff = await screen.findByRole('heading', { name: 'Co się zmieniło' })
    const sec = diff.closest('section') as HTMLElement
    for (const g of ['Potwierdzone', 'Zmienione', 'Nowe', 'Zamknięte'])
      expect(within(sec).getByRole('heading', { name: new RegExp(g) })).toBeInTheDocument()
    expect(within(sec).getByText('05.05.2026 → 05.06.2026')).toBeInTheDocument()
    expect(within(sec).getByText('Nic w tej grupie.')).toBeInTheDocument()
    // review links
    const link = screen.getByRole('link', { name: /Zmiana umowy z dokumentu: termin \+31 dni/ })
    expect(link).toHaveAttribute('href', expect.stringContaining('sprawa=812'))
  })

  it('public visitors never get links to the queue', async () => {
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(analysis())),
      http.get('/api/projects/:id/changes-since', () => HttpResponse.json(changes)),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    await screen.findByRole('list', { name: 'Etapy przetwarzania' })
    expect(screen.queryByRole('link', { name: /Zmiana umowy z dokumentu/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/spraw czeka w Przeglądzie/)).not.toBeInTheDocument()
  })

  it('processing: shows running OCR and keeps the diff hidden until linking is done', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const steps = analysis().steps.map((s) =>
      s.key === 'ocr'
        ? { ...s, state: 'running' as const, detail: null }
        : s.key === 'upload'
          ? s
          : { ...s, state: 'pending' as const },
    )
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () =>
        HttpResponse.json(analysis({ steps, facts: [], causes: [], link: null, review_items: [] })),
      ),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    expect(await screen.findByText(/Etap 2 z 4: rozpoznanie tekstu \(ocr\), w toku/)).toBeInTheDocument()
    expect(screen.getByText('w toku')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Co się zmieniło' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Powiąż z projektem' })).not.toBeInTheDocument()
  })

  it('extracted but not linked: an expert can run the linking', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const steps = analysis().steps.map((s) => (s.key === 'linking' ? { ...s, state: 'pending' as const } : s))
    let called = false
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () =>
        HttpResponse.json(analysis({ steps, link: null, review_items: [], project_rm_id: null })),
      ),
      http.post('/api/documents/:id/link', () => {
        called = true
        return HttpResponse.json({ ok: true })
      }),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    await userEvent.click(await screen.findByRole('button', { name: 'Powiąż z projektem' }))
    await waitFor(() => expect(called).toBe(true))
  })

  it('a failed identifier check is shown as an alert with the registry value', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const a = analysis({
      link: {
        project: { rm_id: 'RM-2026-010', method: 'exact_id', score: 1 },
        checks: [
          {
            kind: 'nip',
            ok: false,
            value: '8161571014',
            detail: 'suma kontrolna niepoprawna',
            expected: '8161570014',
          },
        ],
      },
    })
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(a)),
      http.get('/api/projects/:id/changes-since', () => HttpResponse.json(changes)),
    )
    await renderRoute('/projekty/RM-2026-010/dokumenty?dok=doc:77')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('NIP 8161571014: suma kontrolna niepoprawna. W rejestrze: 8161570014.')
  })

  it('execution-phase uploads default to public with a one-line reason; the expert can override to confidential', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const sent: string[] = []
    server.use(
      ...base(),
      http.post('/api/documents/upload', async ({ request }) => {
        sent.push(/name="sensitivity"\r?\n\r?\n([^\r\n]*)/.exec(await request.text())?.[1] ?? '')
        return HttpResponse.json({ document_id: 77, filename: 'zagrodno.pdf' })
      }),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(analysis())),
      http.get('/api/projects/:id/changes-since', () => HttpResponse.json(changes)),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty')
    const pub = await screen.findByRole('radio', { name: 'Publiczny' })
    expect(pub).toBeChecked()
    expect(screen.getByTestId('poufnosc-opis')).toHaveTextContent(
      'Domyślnie publiczny: dotyczy udzielonego zamówienia publicznego, przetwarza go model w chmurze; zaznacz poufny, jeśli dokument zawiera dane wrażliwe.',
    )
    const file = () => new File(['%PDF'], 'zagrodno.pdf', { type: 'application/pdf' })
    await userEvent.upload(screen.getByLabelText('Wybierz plik z dysku'), file())
    await waitFor(() => expect(sent).toEqual(['public']))
    await userEvent.click(screen.getByRole('radio', { name: 'Poufny' }))
    expect(screen.getByTestId('poufnosc-opis')).toHaveTextContent(
      'Poufny: plik widzisz tylko Ty i administrator',
    )
    await userEvent.upload(screen.getByLabelText('Wybierz plik z dysku'), file())
    await waitFor(() => expect(sent).toEqual(['public', 'confidential']))
  })

  it('shows what the document added to the base, who decided what, and analyses to re-run', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const withGrowth = analysis({
      growth: {
        contract_changes: 1,
        risk_events: 2,
        catalogue_proposals: ['R18'],
        sentence:
          'Nowe w bazie dzięki temu dokumentowi: +1 zmiana umowy, +2 zdarzenia ryzyka, 1 propozycja do katalogu (R18)',
        short: null,
      },
    })
    const diff: RealChangesSince = {
      ...changes,
      groups: {
        ...changes.groups,
        nowe: [
          {
            key: 'event:1',
            label: 'Kolizja z siecią wodociągową',
            value: 'R03, zatwierdzone',
            from_document: true,
            decision: {
              action: 'approve',
              action_label: 'zatwierdzone',
              by: 'user:ekspert',
              by_label: 'Ekspert ekspert',
              at: '2026-11-21T13:10:00+01:00',
            },
          },
        ],
      },
      analyses_to_rerun: ['AN-2026-0014'],
    }
    server.use(
      ...base(),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(withGrowth)),
      http.get('/api/projects/:id/changes-since', () => HttpResponse.json(diff)),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    expect(await screen.findByTestId('growth')).toHaveTextContent(
      '+1 zmiana umowy, +2 zdarzenia ryzyka, 1 propozycja do katalogu (R18)',
    )
    expect(
      await screen.findByText('zatwierdzone przez Ekspert ekspert, 21.11.2026 13:10'),
    ).toBeInTheDocument()
    expect(screen.getByText('z nowego dokumentu')).toBeInTheDocument()
    expect(screen.getByText(/Analizy do przeliczenia.*AN-2026-0014/)).toBeInTheDocument()
  })
})

describe('read-only account and the full chain', () => {
  const juror = () =>
    http.get('/api/auth/me', () =>
      HttpResponse.json({ role: 'expert', name: 'czytelnik', initials: 'C', read_only: true }),
    )

  it('a read-only account sees the screen but cannot upload or link', async () => {
    const steps = analysis().steps.map((s) => (s.key === 'linking' ? { ...s, state: 'pending' as const } : s))
    server.use(
      juror(),
      ...base(),
      http.get('/api/documents/:id/analysis', () =>
        HttpResponse.json(analysis({ steps, link: null, review_items: [], project_rm_id: null })),
      ),
    )
    await renderRoute('/projekty/RM-2026-002/dokumenty?dok=doc:77')
    expect(await screen.findByRole('button', { name: 'Powiąż z projektem' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Wybierz plik' })).toBeDisabled()
    expect(
      screen.getByText('To konto jest tylko do odczytu, dodawanie dokumentów jest wyłączone.'),
    ).toBeInTheDocument()
  })

  it('upload -> the new document opens with steps, facts, the diff and review links', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    server.use(
      ...base(),
      http.post('/api/documents/upload', () =>
        HttpResponse.json({ document_id: 77, filename: 'zagrodno.pdf' }),
      ),
      http.get('/api/documents/:id/analysis', () => HttpResponse.json(analysis())),
      http.get('/api/projects/:id/changes-since', () => HttpResponse.json(changes)),
    )
    const { router } = await renderRoute('/projekty/RM-2026-002/dokumenty')
    await userEvent.upload(
      await screen.findByLabelText('Wybierz plik z dysku'),
      new File(['%PDF'], 'zagrodno.pdf', { type: 'application/pdf' }),
    )
    await waitFor(() => expect(router.state.location.search).toMatchObject({ dok: 'doc:77' }))
    expect(await screen.findByRole('list', { name: 'Etapy przetwarzania' })).toBeInTheDocument()
    expect(await screen.findByText(/nowy planowany koniec umowy: 05.06.2026/)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Co się zmieniło' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Zmiana umowy z dokumentu/ })).toBeInTheDocument()
  })
})
