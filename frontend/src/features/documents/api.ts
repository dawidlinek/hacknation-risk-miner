import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, contractFetch } from '@/api/client'
import { adaptDocuments } from './adapt'
import { stillProcessing } from './analysis'
import type { RealAnalysis, RealChangesSince, RealDocuments, RealFacts } from './types'

export const projectDocumentsQuery = (id: string, isPublic: boolean) =>
  queryOptions({
    queryKey: ['project', id, 'documents', isPublic ? 'public' : 'expert'],
    queryFn: async () =>
      adaptDocuments(
        await contractFetch<RealDocuments>(`/api/projects/${encodeURIComponent(id)}/documents`),
        isPublic,
      ),
  })

export const noticeFactsQuery = (objectId: string) =>
  queryOptions({
    queryKey: ['notice', objectId, 'facts'],
    queryFn: () => contractFetch<RealFacts>(`/api/notices/${encodeURIComponent(objectId)}/facts`),
    staleTime: 5 * 60_000,
  })

export interface UploadResult {
  document_id: number
  filename: string
  pages?: number | null
  text_status?: string
}

/** POST /api/documents/upload (multipart) bound to the project; goes to review as facts to confirm. */
export function useUploadDocument(rmId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, isPublic }: { file: File; isPublic: boolean }) => {
      const body = new FormData()
      body.set('file', file)
      body.set('sensitivity', isPublic ? 'public' : 'confidential')
      body.set('project_rm_id', rmId)
      return contractFetch<UploadResult>('/api/documents/upload', { method: 'POST', body })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', rmId, 'documents'] })
      qc.invalidateQueries({ queryKey: ['project', rmId, 'card'] })
    },
  })
}

export const uploadErrorMessage = (e: unknown): string =>
  e instanceof ApiError
    ? e.status === 403
      ? e.code === 'read_only'
        ? 'To konto jest tylko do odczytu.'
        : 'Dodawanie dokumentów wymaga zalogowania.'
      : e.status === 413
        ? 'Plik jest za duży.'
        : e.detail
    : 'Nie udało się dodać dokumentu.'

export const documentAnalysisQuery = (documentId: number) =>
  queryOptions({
    queryKey: ['document', documentId, 'analysis'],
    queryFn: () => contractFetch<RealAnalysis>(`/api/documents/${documentId}/analysis`),
    refetchInterval: (q) => {
      const steps = q.state.data?.steps
      return steps && stillProcessing(steps) && q.state.dataUpdateCount < 200 ? 3000 : false
    },
  })

export const changesSinceQuery = (rmId: string, documentId: number, enabled: boolean) =>
  queryOptions({
    queryKey: ['project', rmId, 'changes-since', documentId],
    enabled,
    queryFn: () =>
      contractFetch<RealChangesSince>(`/api/projects/${encodeURIComponent(rmId)}/changes-since`, {
        query: { document_id: documentId },
      }),
  })

export function useLinkDocument(documentId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      contractFetch<unknown>(`/api/documents/${documentId}/link`, { method: 'POST', json: {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['document', documentId] })
      qc.invalidateQueries({ queryKey: ['project'] })
    },
  })
}
