import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import demo from './__fixtures__/draft.demo.json'
import {
  adaptUpload,
  aiStatusLine,
  type Chip,
  canRun,
  type Draft,
  fileError,
  parseMoney,
  parseNumber,
  patchValue,
  readyToCreate,
} from './logic'
import { ChipsEditor } from './NewAnalysisScreen'

// captured from the API (regex chips for the demo description): a real response, not a mock
const draft = demo as unknown as Draft
const wrap = (ui: ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('1.1 logic', () => {
  it('creates the draft at 20 characters or the first document', () => {
    expect(readyToCreate('krótko', [])).toBe(false)
    expect(readyToCreate('Budowa kanalizacji sanitarnej', [])).toBe(true)
    expect(readyToCreate('', [11062])).toBe(true)
    expect(canRun('Budowa kanalizacji sanitarnej', [], true)).toBe(false)
  })
  it('parses Polish numbers and money', () => {
    expect(parseNumber('6,2')).toBe(6.2)
    expect(parseNumber('6 200')).toBe(6200)
    expect(parseNumber('abc')).toBeNull()
    expect(parseMoney('7 mln zł brutto')).toEqual({ amount: 7e6, vat: 'gross' })
    expect(parseMoney('7,5 mln netto')).toEqual({ amount: 7.5e6, vat: 'net' })
    expect(parseMoney('850 tys.')).toEqual({ amount: 850e3, vat: 'gross' })
    expect(patchValue({ editor: 'money' }, '7 mln')).toEqual({
      amount: '7000000.00',
      currency: 'PLN',
      vat_basis: 'gross',
    })
    expect(patchValue({ editor: 'months' }, '14')).toBe(14)
    expect(patchValue({ editor: 'number' }, 'x')).toBeNull()
  })
  it('adapts the upload response and rejects unsupported files', () => {
    const d = adaptUpload({
      document_id: 5,
      filename: 'PFU.pdf',
      pages: 38,
      doc_type: { code: 'PFU' },
      sensitivity: 'public',
    })
    expect(d).toMatchObject({ doc_type: 'PFU', label: 'PFU, 38 s.' })
    expect(
      adaptUpload({
        document_id: 6,
        filename: 'x.pdf',
        pages: 2,
        doc_type: { code: 'INNE' },
        sensitivity: 'confidential',
      }).label,
    ).toBe('dokument, 2 s.')
    expect(fileError({ name: 'a.xlsx', size: 10 })).toMatch(/PDF i DOCX/)
    expect(fileError({ name: 'a.pdf', size: 60 * 1024 * 1024 })).toMatch(/50 MB/)
    expect(fileError({ name: 'a.docx', size: 10 })).toBeNull()
  })
  it('AI status line: busy while pending, the backend note when AI failed', () => {
    expect(aiStatusLine({ ai_pending: true })?.tone).toBe('busy')
    expect(
      aiStatusLine({
        ai_pending: false,
        ai_features: { job_id: 1, status: 'failed', note: 'Odczyt AI niedostępny.' },
      })?.text,
    ).toBe('Odczyt AI niedostępny.')
    expect(aiStatusLine({ ai_pending: false })).toBeNull()
  })
})

describe('ChipsEditor', () => {
  it('renders the API chips with their source; unsure chips are dashed', () => {
    wrap(<ChipsEditor id={draft.id} chips={draft.features as Chip[]} onDraft={() => {}} />)
    const list = screen.getByTestId('chips')
    expect(within(list).getByText('kanalizacja sanitarna')).toBeInTheDocument()
    expect(within(list).getByText('7 mln zł brutto')).toBeInTheDocument()
    expect(screen.getByTestId('chip-dlugosc_km').className).toMatch(/border-dashed/)
    expect(screen.getByTestId('chip-podsektor').className).not.toMatch(/border-dashed/)
  })
  it('the follow-up asks for connections (missing from the description)', () => {
    expect(draft.follow_ups.map((f) => f.key)).toEqual(['przylacza'])
    expect(draft.follow_ups[0].title).toBe('Ile będzie przyłączy?')
  })
})

describe('JellySite', () => {
  it('reduced motion (and jsdom without matchMedia): a static still frame, no canvas, no animation loop', async () => {
    const { JellySite } = await import('../jelly/JellySite')
    render(<JellySite />)
    const site = screen.getByTestId('jelly-site')
    expect(site.querySelector('canvas')).toBeNull()
    expect(site.querySelectorAll('[data-still-bot]')).toHaveLength(4)
    expect(site).toHaveAttribute('aria-hidden', 'true')
  })
  it('motion allowed: four sleeping hard-hat bots for the WebGL renderer', async () => {
    const orig = window.matchMedia
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as never
    try {
      const { JellySite } = await import('../jelly/JellySite')
      render(<JellySite />)
      const bots = screen.getByTestId('jelly-site').querySelectorAll('[data-jelly]')
      expect(bots).toHaveLength(4)
      expect(
        [...bots].every(
          (b) => b.getAttribute('data-hat') === 'hard' && b.getAttribute('data-state') === 'asleep',
        ),
      ).toBe(true)
    } finally {
      window.matchMedia = orig
    }
  })
})
