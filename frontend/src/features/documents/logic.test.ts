import { describe, expect, it } from 'vitest'
import {
  adaptDocuments,
  documentDetail,
  expectedDetail,
  factsLabel,
  noticeDetail,
  statusLabel,
} from './adapt'
import { findSelection, validateUpload } from './logic'
import type { RealDocuments, RealFacts } from './types'

const raw: RealDocuments = {
  summary: 'Mamy 5 ogłoszeń z BZP. Brakuje 2 dokumentów z budowy.',
  have: 1,
  expected_total: 3,
  expected: [
    {
      key: 'pfu',
      title: 'Program funkcjonalno-użytkowy (PFU)',
      ext: 'PDF',
      have: true,
      state_label: 'mamy dokument',
      unlocks: 'Potwierdzi R01.',
      where_to_find: 'BIP',
      checklist: 'PFU: jest w paczce',
    },
    {
      key: 'ppu',
      label: 'Projektowane postanowienia umowy',
      have: false,
      state_label: 'nie ma w paczce',
      unlocks: 'Pokaże waloryzację.',
      where: 'SWZ',
    },
    {
      key: 'geotech',
      label: 'Dokumentacja geotechniczna',
      have: false,
      state_label: 'nie ma w paczce',
      unlocks: 'Potwierdzi R02.',
    },
  ],
  public: [
    {
      kind: 'notice',
      key: 'n1',
      object_id: 'n1',
      ref: '2024/BZP 00554831/01',
      title: 'Ogłoszenie o zmianie umowy',
      ext: 'BZP',
      date: '2024-10-21',
      facts: 2,
      risk_codes: ['R01'],
      review_status: 'proposed',
      status_label: 'z ogłoszenia BZP',
      url: 'https://ezamowienia.gov.pl/x',
    },
    {
      kind: 'document',
      key: 'doc:7',
      object_id: '7',
      ref: 'swz.pdf',
      title: 'SWZ',
      ext: 'pdf',
      date: null,
      facts: 0,
      review_status: 'auto',
      status_label: 'dokument z postępowania',
    },
  ],
}

describe('documents adapter', () => {
  it('maps expected docs and keeps counts', () => {
    const v = adaptDocuments(raw, false)
    expect(v.have).toBe(1)
    expect(v.expectedTotal).toBe(3)
    expect(v.expected[0].stateLabel).toBe('mamy dokument')
    expect(v.expected[1]).toMatchObject({
      title: 'Projektowane postanowienia umowy',
      ext: 'PDF',
      where: 'SWZ',
      stateLabel: 'nie ma w paczce',
    })
  })
  it('formats public docs: dates, facts, ext', () => {
    const v = adaptDocuments(raw, false)
    expect(v.publicDocs[0]).toMatchObject({
      dateLabel: '21.10.2024',
      factsLabel: '2 fakty, R01',
      ext: 'BZP',
      statusLabel: 'do przeglądu',
    })
    expect(v.publicDocs[1]).toMatchObject({ factsLabel: 'bez faktów', ext: 'PDF', dateLabel: '' })
  })
  it('public mode: proposed reads "niezweryfikowane"', () => {
    expect(adaptDocuments(raw, true).publicDocs[0].statusLabel).toBe('niezweryfikowane')
    expect(statusLabel('approved', undefined, true)).toBe('zatwierdzone')
    expect(statusLabel('auto', undefined, false)).toBe('z ogłoszenia BZP')
  })
  it('factsLabel plural forms', () => {
    expect(factsLabel(1)).toBe('1 fakt')
    expect(factsLabel(3, ['R02'])).toBe('3 fakty, R02')
    expect(factsLabel(5)).toBe('5 faktów')
  })
})

describe('documents details', () => {
  const view = adaptDocuments(raw, false)
  it('expected detail is built client-side and offers upload only to experts when missing', () => {
    const d = expectedDetail(view.expected[1], true)
    expect(d.kind).toBe('dokument z budowy, nie ma w paczce')
    expect(d.fields.map((f) => f.label)).toEqual(['co odblokuje', 'gdzie szukać'])
    expect(d.cta).toEqual({ label: 'Dodaj dokument', href: '#dodaj' })
    expect(expectedDetail(view.expected[1], false).cta).toBeNull()
    expect(expectedDetail(view.expected[0], true).cta).toBeNull()
  })
  const facts: RealFacts = {
    rows: [
      {
        field_code: '4.4',
        label: 'wartość zmiany',
        value: '+758 084,56 zł brutto',
        tag: 'źródło',
        tag_role: 'source',
      },
      {
        field_code: '5.3',
        label: 'zdarzenie ryzyka',
        value: 'roboty nieprzewidziane w PFU',
        tag: 'R01, zatwierdzone',
        tag_role: 'source',
        review_status: 'approved',
      },
    ],
    meta: {
      url: 'https://ezamowienia.gov.pl/y',
      retrieved_at: '2026-11-12T11:55:53+00:00',
      sha256: 'af0e37',
      licence: 'public information',
      licence_label: 'informacja publiczna',
    },
  }
  it('notice detail: fields with field codes, provenance meta, CTA', () => {
    const d = noticeDetail(view.publicDocs[0], facts, false, null)
    expect(d.fields[0]).toMatchObject({
      label: 'pole 4.4, wartość zmiany',
      value: '+758 084,56 zł brutto',
      tag: 'źródło',
      tagRole: 'SOURCE',
    })
    expect(d.meta.map((m) => m.k)).toEqual(['źródło', 'pobrano', 'sha256', 'licencja'])
    expect(d.meta[2].v).toBe('af0e37')
    expect(d.meta[3].v).toBe('informacja publiczna')
    expect(d.cta).toEqual({ label: 'Otwórz w BZP', href: 'https://ezamowienia.gov.pl/y', external: true })
  })
  it('missing sha256 keeps the placeholder verbatim', () => {
    const d = noticeDetail(
      view.publicDocs[0],
      { rows: [], meta: { url: null, retrieved_at: null, sha256: null, licence: null } },
      false,
      null,
    )
    expect(d.meta[2].v).toBe('[skrót pliku]')
  })
  it('proposed notice links to the review queue for experts', () => {
    const d = noticeDetail(view.publicDocs[0], facts, true, '/przeglad?sprawa=812')
    expect(d.cta).toEqual({ label: 'Przejrzyj w kolejce', href: '/przeglad?sprawa=812' })
  })
  it('document detail', () => {
    expect(documentDetail(view.publicDocs[1]).kind).toBe('dokument z postępowania')
  })
})

describe('documents logic', () => {
  const view = adaptDocuments(raw, false)
  it('findSelection', () => {
    expect(findSelection(view, 'ppu')?.type).toBe('expected')
    expect(findSelection(view, 'n1')?.type).toBe('public')
    expect(findSelection(view, 'zzz')).toBeNull()
    expect(findSelection(view, null)).toBeNull()
  })
  it('validateUpload', () => {
    expect(validateUpload({ name: 'a.pdf', size: 10 })).toBeNull()
    expect(validateUpload({ name: 'PACZKA.ZIP', size: 10 })).toBeNull()
    expect(validateUpload({ name: 'a.exe', size: 10 })).toMatch(/PDF, DOCX i ZIP/)
    expect(validateUpload({ name: 'a.pdf', size: 60 * 1024 * 1024 })).toMatch(/50 MB/)
  })
})
