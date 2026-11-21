import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { RealAnalysis } from '@/features/documents/types'
import { server } from '@/mocks/node'
import { renderRoute } from '@/test/render'
import {
  duplicateLine,
  failedChecks,
  maybeDocument,
  needsDocumentRouting,
  needsMapping,
  projectLine,
  resultLine,
} from './route'

describe('Źródła routing helpers', () => {
  it('treats PDF, DOCX, scans and text as possible case documents, XLSX/CSV/ZIP as datasets', () => {
    expect(maybeDocument('Risk_Miner_pismo_termin_grodzisko.pdf')).toBe(true)
    expect(maybeDocument('Risk_Miner_protokol_koniecznosci_zławieś.DOCX')).toBe(true)
    expect(maybeDocument('projekty.xlsx')).toBe(false)
    expect(maybeDocument('paczka.zip')).toBe(false)
    expect(needsDocumentRouting([{ name: 'a.xlsx' }, { name: 'b.csv' }])).toBe(false)
    expect(needsDocumentRouting([{ name: 'a.xlsx' }, { name: 'protokol.pdf' }])).toBe(true)
  })

  it('runs the mapping step only when a dataset or record is left after routing', () => {
    expect(needsMapping([{ name: 'a.pdf' }], { tables: 0 })).toBe(false)
    expect(needsMapping([{ name: 'a.pdf' }, { name: 'b.xlsx' }], { tables: 1 })).toBe(true)
    expect(needsMapping([{ name: 'b.xlsx' }], null)).toBe(true)
  })

  it('describes the link, the growth and the failed checks in Polish', () => {
    const a = {
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
          { kind: 'kpo', ok: true, value: 'KPOD.03.15-IW.21-0025/25', detail: 'ok' },
        ],
      },
      growth: {
        contract_changes: 0,
        risk_events: 6,
        catalogue_proposals: [],
        sentence: null,
        short: '+6 zdarzeń ryzyka',
      },
      review_items: [
        { id: 1, kind: 'discrepancy', title: 'NIP', status: 'open', href: '' },
        { id: 2, kind: 'event', title: 'R03', status: 'open', href: '' },
        { id: 3, kind: 'event', title: 'R01', status: 'approved', href: '' },
      ],
    } as unknown as RealAnalysis
    expect(projectLine(a)).toBe('RM-2026-010, numer KPO z dokumentu, wynik 1,00')
    expect(resultLine(a)).toBe('+6 zdarzeń ryzyka, 2 propozycje do przeglądu')
    expect(failedChecks(a)).toEqual(['NIP 8161571014: suma kontrolna niepoprawna. W rejestrze: 8161570014.'])
  })

  it('tells a re-dropped file apart from a new one', () => {
    expect(duplicateLine({ duplicate: false, jobs: [] })).toBeNull()
    expect(
      duplicateLine({
        duplicate: true,
        jobs: [],
        previous: { project_rm_id: 'RM-2026-002', has_facts: true, linked: true, open_review_items: 5 },
      }),
    ).toBe('Ten plik już był: pokazujemy wyniki z pierwszego wczytania (projekt RM-2026-002).')
  })
})

// ---- the screen: a dropped PDF goes to the document pipeline, not to the column mapping ----------------------------

const analysis: RealAnalysis = {
  document: {
    id: 501,
    filename: 'Risk_Miner_pismo_termin_grodzisko.pdf',
    title: 'Risk_Miner_pismo_termin_grodzisko.pdf',
    sensitivity: 'public',
    pages: 1,
    doc_kind_label: 'pismo do instytucji pośredniczącej',
    doc_date: '2025-11-06',
    level: 'grant',
  },
  steps: [
    { key: 'upload', label: 'Wczytanie pliku', state: 'done' },
    { key: 'ocr', label: 'Rozpoznanie tekstu (OCR)', state: 'done' },
    { key: 'extraction', label: 'Odczyt faktów', state: 'done' },
    { key: 'linking', label: 'Powiązanie z projektem i umową', state: 'done' },
  ],
  facts: [],
  causes: [],
  effects: [],
  flags: [],
  link: {
    project: { rm_id: 'RM-2026-010', method: 'exact_id', score: 1 },
    contract: null,
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
  review_items: [
    {
      id: 77,
      kind: 'discrepancy',
      title: 'NIP w dokumencie niepoprawny (suma kontrolna); w rejestrze 8161570014',
      status: 'open',
      href: '/przeglad?sprawa=77',
    },
  ],
  project_rm_id: 'RM-2026-010',
  growth: {
    contract_changes: 0,
    risk_events: 6,
    catalogue_proposals: [],
    sentence: 'Nowe w bazie dzięki temu dokumentowi: +6 zdarzeń ryzyka',
    short: '+6 zdarzeń ryzyka',
  },
}

const importState = (files: { name: string; kind: string }[], status = 'uploaded') => ({
  code: 'IMP-2026-0099',
  status,
  status_label: status === 'uploaded' ? 'wgrane' : 'przejrzane',
  files: files.map((f) => ({ ...f, bytes: 1000, duplicate_of_source_id: null })),
  tool_calls: [],
  mapping: [],
  questions: [],
  rules: [],
  importer: null,
  test_run: null,
  job_id: null,
})

function mockImports(files: { name: string; kind: string }[], tables: number, calls: string[]) {
  let status = 'uploaded'
  server.use(
    http.get('/api/importers', () => HttpResponse.json([])),
    http.post('/api/imports', () => HttpResponse.json({ code: 'IMP-2026-0099' }, { status: 201 })),
    http.get('/api/imports/IMP-2026-0099', () => HttpResponse.json(importState(files, status))),
    http.post('/api/imports/IMP-2026-0099/inspect', () => {
      calls.push('inspect')
      status = 'inspected'
      return HttpResponse.json(importState(files, status))
    }),
    http.post('/api/imports/IMP-2026-0099/documents', () => {
      calls.push('documents')
      return HttpResponse.json({
        code: 'IMP-2026-0099',
        tables,
        documents: files
          .filter((f) => f.kind === 'pdf')
          .map((f) => ({
            name: f.name,
            document_id: 501,
            duplicate: false,
            text_status: 'needs_ocr',
            jobs: [],
            error: null,
          })),
      })
    }),
    http.post('/api/imports/IMP-2026-0099/propose-mapping', () => {
      calls.push('propose-mapping')
      return HttpResponse.json(importState(files, 'mapped'))
    }),
    http.get('/api/documents/501/analysis', () => HttpResponse.json(analysis)),
  )
}

describe('ImportScreen document routing', () => {
  afterEach(() => localStorage.removeItem('rm.mockRole'))

  it('routes a dropped scan to the document pipeline and shows the linked project, growth and NIP check', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const calls: string[] = []
    mockImports([{ name: 'Risk_Miner_pismo_termin_grodzisko.pdf', kind: 'pdf' }], 0, calls)
    await renderRoute('/zrodla')
    const input = await screen.findByLabelText('Wybierz pliki do importu')
    await userEvent.upload(
      input,
      new File(['%PDF-1.4'], 'Risk_Miner_pismo_termin_grodzisko.pdf', { type: 'application/pdf' }),
    )
    expect(await screen.findByText(/RM-2026-010, numer KPO z dokumentu, wynik 1,00/)).toBeInTheDocument()
    expect(screen.getByTestId('growth')).toHaveTextContent('+6 zdarzeń ryzyka, 1 propozycja do przeglądu')
    expect(
      screen.getByText(/NIP 8161571014: suma kontrolna niepoprawna. W rejestrze: 8161570014./),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Co się zmieniło w projekcie RM-2026-010' })).toHaveAttribute(
      'href',
      '/projekty/RM-2026-010/dokumenty?dok=doc%3A501',
    )
    expect(screen.getByText('dokumenty przekazane do analizy')).toBeInTheDocument()
    expect(calls).toEqual(['inspect', 'documents']) // no column mapping for a document
  })

  it('still proposes a mapping when a dataset comes in the same drop', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    const calls: string[] = []
    mockImports(
      [
        { name: 'projekty.xlsx', kind: 'xlsx' },
        { name: 'protokol.pdf', kind: 'pdf' },
      ],
      1,
      calls,
    )
    await renderRoute('/zrodla')
    const input = await screen.findByLabelText('Wybierz pliki do importu')
    await userEvent.upload(input, [
      new File(['x'], 'projekty.xlsx'),
      new File(['%PDF-1.4'], 'protokol.pdf', { type: 'application/pdf' }),
    ])
    await waitFor(() => expect(calls).toEqual(['inspect', 'documents', 'propose-mapping']))
  })
})
