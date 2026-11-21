import { ExportMenu, type ExportFormat } from '@/components/common/ExportMenu'

/** GET /api/projects/{id}/export.{fmt}: the whole project record (identification, BZP link, plan vs actual,
 *  changes, risk events with evidence, AI proposals marked as proposals, sources with sha256). */
export const projectRecordExportUrl = (id: string, fmt: ExportFormat) =>
  `/api/projects/${encodeURIComponent(id)}/export.${fmt}`

export const RECORD_FORMATS: ExportFormat[] = ['pdf', 'docx', 'md', 'json']

export function ProjectRecordExport({ id }: { id: string }) {
  return (
    <ExportMenu
      label="Eksportuj rekord"
      formats={RECORD_FORMATS}
      urlFor={(f) => projectRecordExportUrl(id, f)}
      filename={(f) => `rekord_${id}.${f}`}
    />
  )
}
