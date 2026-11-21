import { queryOptions } from '@tanstack/react-query'
import { contractFetch } from '@/api/client'
import { adaptUpload, type Draft, type UploadResponse } from './logic'

export const draftQuery = (id: string) =>
  queryOptions({
    queryKey: ['analysis', id, 'draft'],
    queryFn: () => contractFetch<Draft>(`/api/analyses/${encodeURIComponent(id)}/draft`),
    refetchInterval: (q) => (q.state.data?.ai_pending ? 2000 : false),
  })

export const createAnalysis = (text: string, documentIds: number[]) =>
  contractFetch<Draft>('/api/analyses', { method: 'POST', json: { text, document_ids: documentIds } })

export const patchFeatures = (
  id: string,
  body: { values?: Record<string, unknown>; skipped?: string[]; text?: string; document_ids?: number[] },
) => contractFetch<Draft>(`/api/analyses/${encodeURIComponent(id)}/features`, { method: 'PATCH', json: body })

export async function uploadDocument(
  file: File,
  sensitivity: 'confidential' | 'public',
  analysisCode?: string | null,
) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('sensitivity', sensitivity)
  if (analysisCode) fd.append('analysis_code', analysisCode)
  return adaptUpload(
    await contractFetch<UploadResponse>('/api/documents/upload', { method: 'POST', body: fd }),
  )
}

/** Owner's explicit choice when the sovereign model is down: the document is public, so the cloud AI may read it. */
export const makeDocumentPublic = (id: string, documentId: number) =>
  contractFetch<{ document_id: number; sensitivity: 'public'; jobs: Record<string, number | null> }>(
    `/api/analyses/${encodeURIComponent(id)}/documents/${documentId}/make-public`,
    { method: 'POST' },
  )
