import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'
import { cardHandler } from '../audit/testkit'
import type { RealDocuments, RealFacts } from './types'

const docs: RealDocuments = {
  summary: 'Mamy 3 ogłoszenia z BZP. Brakuje 1 dokumentu z budowy.',
  have: 1,
  expected_total: 2,
  expected: [
    {
      key: 'swz',
      title: 'Specyfikacja warunków zamówienia (SWZ)',
      ext: 'PDF',
      have: true,
      state_label: 'mamy dokument',
      unlocks: 'Pozwoli sprawdzić podział ryzyk.',
      where_to_find: 'Platforma zakupowa',
    },
    {
      key: 'ppu',
      title: 'Projektowane postanowienia umowy',
      ext: 'PDF',
      have: false,
      state_label: 'nie ma w paczce',
      unlocks: 'Pokaże klauzule waloryzacyjne (R08).',
      where_to_find: 'Załączniki do SWZ',
    },
  ],
  public: [
    {
      kind: 'notice',
      key: 'a1',
      object_id: 'a1',
      ref: '2024/BZP 00554831/01',
      title: 'Ogłoszenie o zmianie umowy',
      ext: 'BZP',
      date: '2024-10-21',
      facts: 2,
      risk_codes: ['R01'],
      review_status: 'approved',
      status_label: 'z ogłoszenia BZP',
      url: 'https://ezamowienia.gov.pl/a1',
    },
    {
      kind: 'notice',
      key: 'a2',
      object_id: 'a2',
      ref: '2024/BZP 00618384/01',
      title: 'Ogłoszenie o zmianie umowy',
      ext: 'BZP',
      date: '2024-11-27',
      facts: 1,
      risk_codes: ['R02'],
      review_status: 'proposed',
      status_label: 'z ogłoszenia BZP',
      url: 'https://ezamowienia.gov.pl/a2',
    },
  ],
}

const facts: RealFacts = {
  rows: [
    {
      field_code: '4.4',
      label: 'wartość zmiany',
      value: '+758 084,56 zł brutto',
      tag: 'źródło',
      tag_role: 'source',
    },
  ],
  meta: {
    url: 'https://ezamowienia.gov.pl/a1',
    retrieved_at: '2026-11-12T11:55:53+00:00',
    sha256: 'af0e37',
    licence: 'x',
    licence_label: 'informacja publiczna',
  },
}

const handlers = () => [
  cardHandler({ have: 1, expected: 2 }),
  http.get('/api/projects/:id/documents', () => HttpResponse.json(docs)),
  http.get('/api/notices/:oid/facts', () => HttpResponse.json(facts)),
]

describe('2.5 Dokumenty projektu', () => {
  it('shows the summary, both lists and the counter', async () => {
    server.use(...handlers())
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    expect(
      await screen.findByText('Mamy 3 ogłoszenia z BZP. Brakuje 1 dokumentu z budowy.'),
    ).toBeInTheDocument()
    const main = screen.getByRole('heading', { name: 'Dokumenty z budowy' }).closest('section') as HTMLElement
    expect(within(main).getByText('1 z 2')).toBeInTheDocument()
    expect(within(main).getByRole('button', { name: /Projektowane postanowienia umowy/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    const pub = screen
      .getByRole('heading', { name: 'Ze źródeł publicznych' })
      .closest('section') as HTMLElement
    expect(within(pub).getAllByRole('button')).toHaveLength(2)
    expect(within(pub).getByText('2 fakty, R01')).toBeInTheDocument()
  })

  it('selecting a missing document explains what it unlocks (client-side detail)', async () => {
    server.use(...handlers())
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    await userEvent.click(await screen.findByRole('button', { name: /Projektowane postanowienia umowy/ }))
    const panel = await screen.findByText('dokument z budowy, nie ma w paczce')
    const aside = panel.closest('section') as HTMLElement
    expect(within(aside).getByText('Pokaże klauzule waloryzacyjne (R08).')).toBeInTheDocument()
    expect(within(aside).getByText('Załączniki do SWZ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Projektowane postanowienia umowy/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('a notice loads its facts with provenance; ?dok= deep link works', async () => {
    server.use(...handlers())
    await renderRoute('/projekty/RM-2026-003/dokumenty?dok=a1')
    expect(await screen.findByText('pole 4.4, wartość zmiany')).toBeInTheDocument()
    expect(screen.getByText('+758 084,56 zł brutto')).toBeInTheDocument()
    expect(screen.getByText('af0e37')).toBeInTheDocument()
    expect(screen.getByText('informacja publiczna')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Otwórz w BZP/ })).toHaveAttribute(
      'href',
      'https://ezamowienia.gov.pl/a1',
    )
  })

  it('public visitors: proposed reads "niezweryfikowane", no upload area', async () => {
    server.use(...handlers())
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    expect(await screen.findByText('niezweryfikowane')).toBeInTheDocument()
    expect(screen.queryByText('Upuść PDF, DOCX albo ZIP')).not.toBeInTheDocument()
  })

  it('experts see the drop area; an upload is posted as multipart for this project and confirmed', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    let fields: Record<string, string> = {}
    server.use(
      ...handlers(),
      http.post('/api/documents/upload', async ({ request }) => {
        const raw = await request.text() // multipart body, read as text (jsdom FormData)
        const field = (n: string) => new RegExp(`name="${n}"\\r?\\n\\r?\\n([^\\r\\n]*)`).exec(raw)?.[1]
        fields = {
          project: String(field('project_rm_id')),
          sensitivity: String(field('sensitivity')),
          file: /name="file"; filename=/.test(raw) ? 'yes' : 'no',
        }
        return HttpResponse.json({ document_id: 11062, filename: 'ppu.pdf', pages: 22, text_status: 'ok' })
      }),
    )
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    expect(await screen.findByText('Upuść PDF, DOCX albo ZIP')).toBeInTheDocument()
    const file = new File(['%PDF-1.4'], 'ppu.pdf', { type: 'application/pdf' })
    await userEvent.upload(screen.getByLabelText('Wybierz plik z dysku'), file)
    await waitFor(() =>
      expect(fields).toEqual({ project: 'RM-2026-003', sensitivity: 'public', file: 'yes' }),
    )
    expect(await screen.findByText('Dokument w kolejce. Fakty trafią do Przeglądu.')).toBeInTheDocument()
  })

  it('unsupported files are refused before upload', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    server.use(...handlers())
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    const input = await screen.findByLabelText('Wybierz plik z dysku')
    await userEvent.upload(input, new File(['x'], 'virus.exe'), { applyAccept: false })
    expect(await screen.findByRole('alert')).toHaveTextContent('Obsługujemy pliki PDF, DOCX i ZIP.')
  })

  it('read-only account gets the backend reason on upload', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    server.use(
      ...handlers(),
      http.post('/api/documents/upload', () =>
        HttpResponse.json({ detail: 'To konto jest tylko do odczytu.', code: 'read_only' }, { status: 403 }),
      ),
    )
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    await userEvent.upload(await screen.findByLabelText('Wybierz plik z dysku'), new File(['%PDF'], 'a.pdf'))
    expect(await screen.findByText('To konto jest tylko do odczytu.')).toBeInTheDocument()
  })

  it('no documents: empty state', async () => {
    server.use(
      cardHandler(),
      http.get('/api/projects/:id/documents', () =>
        HttpResponse.json({
          ...docs,
          expected: [],
          public: [],
          have: 0,
          expected_total: 0,
          summary: 'Nie znaleźliśmy ogłoszeń dla tego projektu.',
        }),
      ),
    )
    await renderRoute('/projekty/RM-2026-003/dokumenty')
    expect(
      (await screen.findAllByText('Nie znaleźliśmy ogłoszeń dla tego projektu.')).length,
    ).toBeGreaterThan(0)
  })
})
