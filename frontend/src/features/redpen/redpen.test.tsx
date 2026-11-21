import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { RedPenParagraph } from '@/api/contracts/redpen'
import demo from './__fixtures__/redpen.demo.json'
import {
  canAddClause,
  canDecide,
  countsLabel,
  type Note,
  neighbour,
  noteFromHash,
  type RedPen,
  segments,
  stepPages,
} from './logic'
import { RedPenBody } from './RedPenScreen'

// captured from the engine (public BZP PFU, rule notes + missing items): a real response, not a mock
const r = demo as unknown as RedPen

const wrap = (ui: ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('red pen logic', () => {
  it('segments a paragraph around overlapping marks', () => {
    const p: RedPenParagraph = {
      text: 'abcdefghij',
      marks: [
        { note_no: '1', start: 2, end: 6 },
        { note_no: '2', start: 4, end: 8 },
      ],
    }
    const s = segments(p)
    expect(s.map((x) => x.text).join('')).toBe('abcdefghij')
    expect(s.find((x) => x.text === 'ef')?.notes).toEqual(['1', '2'])
    expect(s.find((x) => x.text === 'ef')?.endsHere).toEqual(['1'])
    expect(segments({ text: 'x', marks: [] })).toEqual([{ text: 'x', notes: [], endsHere: [] }])
  })
  it('every mark in the real response stays inside its paragraph', () => {
    for (const pg of r.pages)
      for (const para of pg.paragraphs) {
        const joined = segments(para)
          .map((x) => x.text)
          .join('')
        expect(joined).toBe(para.text)
      }
  })
  it('page stepping and labels', () => {
    const noted = stepPages(r.pages, true)
    expect(noted.length).toBeGreaterThan(0)
    expect(stepPages(r.pages, false).length).toBe(r.pages.length)
    expect(neighbour([3, 6, 11], 6, 1)).toBe(11)
    expect(neighbour([3, 6, 11], 3, -1)).toBeNull()
    expect(neighbour([3, 6, 11], 4, 1)).toBe(6)
    expect(countsLabel(3, 1)).toBe('3 uwagi, 1 brak')
    expect(countsLabel(5, 2)).toBe('5 uwag, 2 braki')
    expect(countsLabel(1, 0)).toBe('1 uwaga')
    expect(noteFromHash('#u2')).toBe('2')
    expect(noteFromHash('#uA')).toBe('A')
    expect(noteFromHash('')).toBeNull()
  })
  it('decisions only for proposed AI notes; no "Dodaj do PPU" for unverified quotes', () => {
    const ai = { origin: 'AI', review_status: 'proposed', item_id: 5, kind: 'found' } as Note
    expect(canDecide(ai)).toBe(true)
    expect(canDecide({ ...ai, review_status: 'approved' })).toBe(false)
    expect(canDecide({ ...ai, origin: 'CALC' })).toBe(false)
    const withClause = { ...ai, clause: { code: 'R02.1-K1', text: 'x', in_pack: false } } as Note
    expect(canAddClause({ ...withClause, quote: { text: 'q', verified: true } })).toBe(true)
    expect(canAddClause({ ...withClause, quote: { text: 'q', verified: false } })).toBe(false)
  })
})

describe('RedPenBody', () => {
  const props = {
    id: 'AN-1',
    doc: r.document.id,
    page: null,
    onlyNoted: true,
    active: null,
    onPage: () => {},
    onOnlyNoted: () => {},
    onActive: () => {},
  }
  it('renders page text with numbered marks, the notes list and the counts', () => {
    wrap(<RedPenBody r={r} {...props} />)
    expect(screen.getByText(/^\d+ uwag/)).toBeInTheDocument()
    const page = screen.getByTestId('page-text')
    expect(page.querySelectorAll('mark').length).toBeGreaterThan(0)
    expect(within(page).getAllByRole('link', { name: /^Uwaga / }).length).toBeGreaterThan(0)
    expect(screen.getByText('Brak: klauzula waloryzacyjna w PPU')).toBeInTheDocument()
  })
  it('clicking a note opens its card; the card offers the clause actions', () => {
    const onActive = vi.fn()
    const { rerender } = wrap(<RedPenBody r={r} {...props} onActive={onActive} />)
    fireEvent.click(screen.getByText('Brak: klauzula waloryzacyjna w PPU'))
    expect(onActive).toHaveBeenCalledWith('A')
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <RedPenBody r={r} {...props} active="A" />
      </QueryClientProvider>,
    )
    const card = screen.getByTestId('note-card')
    expect(within(card).getByText(/Proponowany zapis/i)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Popraw zapis' })).toBeInTheDocument()
  })
  it('queued AI scan shows the status line and keeps the rule notes', () => {
    wrap(<RedPenBody r={{ ...r, status: 'queued' }} {...props} />)
    expect(screen.getByRole('status')).toHaveTextContent('Model AI czyta dokument')
  })
  it('sovereign outage on a confidential document: rules-only banner with the make-public choice, never an error', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ document_id: r.document.id, sensitivity: 'public', jobs: {} }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const conf = {
      ...r,
      status: 'sovereign_unavailable',
      document: { ...r.document, sensitivity: 'confidential' },
    }
    wrap(<RedPenBody r={conf as unknown as RedPen} {...props} />)
    const banner = screen.getByTestId('sovereign-banner')
    expect(banner).toHaveTextContent(
      'Model suwerenny niedostępny: dokument poufny przetworzono tylko regułami, bez AI.',
    )
    expect(screen.queryByText(/Coś poszło nie tak|Nie udało się wczytać/)).toBeNull()
    expect(screen.getByTestId('page-text').querySelectorAll('mark').length).toBeGreaterThan(0)
    fireEvent.click(
      within(banner).getByRole('button', { name: 'Oznacz jako publiczny i przetwórz ponownie' }),
    )
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain(
      `/api/analyses/AN-1/documents/${r.document.id}/make-public`,
    )
    vi.unstubAllGlobals()
  })
  it('a public document under the same outage gets the banner without the button', () => {
    wrap(<RedPenBody r={{ ...r, status: 'sovereign_unavailable' } as unknown as RedPen} {...props} />)
    expect(screen.getByTestId('sovereign-banner')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Oznacz jako publiczny i przetwórz ponownie' })).toBeNull()
  })
})
