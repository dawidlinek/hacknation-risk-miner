// Contract for 2.5 Dokumenty projektu (docs/impl/frontend.md section 2.5).
import type { EvidenceState, LinkRef, Origin, ReviewStatus } from './common'
import type { ImportSession } from './import'

export interface ExpectedDoc {
  key: string
  title: string
  ext: string // 'PDF'
  state: EvidenceState
  unlocks: string
  where: string
  checklist: string
  have: boolean
}

export interface PublicDoc {
  key: string
  title: string
  ext: 'XLSX' | 'BZP' | 'PDF' | 'DOCX'
  ref: string
  date: string // dd.mm.rrrr
  facts_label: string // '2 fakty, R01'
  review_status: ReviewStatus
  status_label: string // 'zatwierdzone' | 'do przeglądu' | 'zgodne z BZP'
}

export interface DocDetailField {
  label: string
  value: string
  tag: string // 'źródło' | 'R01, zatwierdzone'
  tag_role: Origin | ReviewStatus
}

export interface DocDetail {
  kind: string
  title: string
  fields: DocDetailField[]
  meta: { k: string; v: string }[] // źródło, pobrano, sha256, licencja
  cta: LinkRef
}

export interface ProjectDocuments {
  summary: string
  expected: ExpectedDoc[]
  public_docs: PublicDoc[]
  details: Record<string, DocDetail>
}

export type DocumentUploadResult = ImportSession
