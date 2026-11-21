import type { Origin, ReviewStatus } from '@/api/contracts/common'
import { fmtDate, fmtDateTime } from '@/lib/dates'
import { plural } from '@/lib/plural'
import type {
  DetailField,
  DetailView,
  DocsView,
  ExpectedItem,
  PublicItem,
  RealDocuments,
  RealFacts,
  RealPublic,
} from './types'

const EXT: PublicItem['ext'][] = ['XLSX', 'BZP', 'PDF', 'DOCX']
const asExt = (x: string): PublicItem['ext'] => {
  const up = x.toUpperCase()
  return (EXT as string[]).includes(up)
    ? (up as PublicItem['ext'])
    : up === 'WORDPROCESSINGML.DOCUMENT'
      ? 'DOCX'
      : 'PDF'
}

/** '2 fakty, R01' | 'bez faktów' */
export function factsLabel(n: number, codes: string[] = []): string {
  if (!n) return 'bez faktów'
  const base = `${n} ${plural(n, ['fakt', 'fakty', 'faktów'])}`
  return codes.length ? `${base}, ${codes.join(', ')}` : base
}

/** Public mode: `proposed` reads "niezweryfikowane" (README pattern 3). */
export function statusLabel(status: ReviewStatus, fallback: string | undefined, isPublic: boolean): string {
  if (status === 'proposed') return isPublic ? 'niezweryfikowane' : 'do przeglądu'
  if (status === 'approved') return 'zatwierdzone'
  if (status === 'edited') return 'poprawione'
  if (status === 'rejected') return 'odrzucone'
  return fallback || 'z ogłoszenia BZP'
}

export function adaptDocuments(raw: RealDocuments, isPublic: boolean): DocsView {
  const expected: ExpectedItem[] = raw.expected.map((e) => ({
    key: e.key,
    title: e.title ?? e.label ?? e.key,
    ext: e.ext ?? 'PDF',
    have: e.have,
    stateLabel: e.have ? 'mamy dokument' : (e.state_label ?? 'nie ma w paczce'),
    unlocks: e.unlocks ?? '',
    where: e.where ?? e.where_to_find ?? '',
    checklist: e.checklist ?? '',
  }))
  const publicDocs: PublicItem[] = (raw.public_docs ?? raw.public ?? []).map((p: RealPublic) => ({
    key: p.key,
    kind: p.kind,
    objectId: p.object_id,
    title: p.title,
    ext: asExt(p.ext),
    ref: p.ref,
    dateLabel: p.date ? fmtDate(p.date) : '',
    factsLabel: factsLabel(p.facts, p.risk_codes),
    riskCodes: p.risk_codes ?? [],
    reviewStatus: p.review_status,
    statusLabel: statusLabel(p.review_status, p.status_label, isPublic),
    url: p.url ?? null,
  }))
  return {
    summary: raw.summary,
    expected,
    publicDocs,
    have: raw.have ?? expected.filter((e) => e.have).length,
    expectedTotal: raw.expected_total ?? expected.length,
  }
}

/** Details of an expected (missing or present) document are built client-side (frontend.md §2.5). */
export function expectedDetail(e: ExpectedItem, canUpload: boolean): DetailView {
  return {
    kind: `dokument z budowy, ${e.stateLabel}`,
    title: e.title,
    fields: (
      [
        {
          label: 'co odblokuje',
          value: e.unlocks,
          tag: e.have ? 'jest w paczce' : 'po dodaniu',
          tagRole: 'CALC',
        },
        { label: 'gdzie szukać', value: e.where, tag: '', tagRole: 'SOURCE' },
      ] as DetailField[]
    ).filter((f) => f.value),
    meta: e.checklist ? [{ k: 'oczekiwany', v: e.checklist }] : [],
    cta: e.have ? null : canUpload ? { label: 'Dodaj dokument', href: '#dodaj' } : null,
  }
}

const TAG_ROLE: Record<string, Origin | ReviewStatus> = {
  source: 'SOURCE',
  calc: 'CALC',
  ai: 'AI',
  case: 'CASE',
}

/** Notice details: fields come from GET /api/notices/{object_id}/facts, meta from its `meta` (provenance). */
export function noticeDetail(
  item: PublicItem,
  facts: RealFacts | undefined,
  canReview: boolean,
  reviewItemHref?: string | null,
): DetailView {
  const fields = (facts?.rows ?? []).map((r) => ({
    label: r.field_code ? `pole ${r.field_code}, ${r.label}` : r.label,
    value: r.value || 'brak',
    tag: r.tag ?? 'źródło',
    tagRole: (r.tag_role && TAG_ROLE[r.tag_role]) || ((r.review_status ?? 'auto') as Origin | ReviewStatus),
  }))
  const m = facts?.meta
  const meta = [
    { k: 'źródło', v: `ezamowienia.gov.pl, ${item.ref}` },
    { k: 'pobrano', v: m?.retrieved_at ? `${fmtDateTime(m.retrieved_at)}, kopia BZP` : 'brak' },
    { k: 'sha256', v: m?.sha256 ?? '[skrót pliku]' },
    { k: 'licencja', v: m?.licence_label ?? 'informacja publiczna' },
  ]
  const url = m?.url ?? item.url
  const toReview = canReview && item.reviewStatus === 'proposed' && reviewItemHref
  return {
    kind: `${item.title.toLowerCase()}, BZP`,
    title: item.ref,
    fields,
    meta,
    cta: toReview
      ? { label: 'Przejrzyj w kolejce', href: reviewItemHref as string }
      : url
        ? { label: 'Otwórz w BZP', href: url, external: true }
        : null,
  }
}

export function documentDetail(item: PublicItem): DetailView {
  return {
    kind: 'dokument z postępowania',
    title: item.title,
    fields: [{ label: 'nazwa pliku', value: item.ref || item.title, tag: 'źródło', tagRole: 'SOURCE' }],
    meta: [{ k: 'źródło', v: item.url ?? 'dokumentacja postępowania' }],
    cta: item.url ? { label: 'Otwórz dokument', href: item.url, external: true } : null,
  }
}
