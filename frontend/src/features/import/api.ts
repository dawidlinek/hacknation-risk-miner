import { queryOptions } from '@tanstack/react-query'
import { adaptImport, adaptImporters, type RealImport, type RealImporter } from '@/api/adapters/imports'
import { contractFetch } from '@/api/client'
import type { ImportSession, JobOut } from '@/api/contracts/import'

const adapt = async (p: Promise<RealImport>) => adaptImport(await p)

export function uploadFiles(files: File[]): Promise<ImportSession> {
  const body = new FormData()
  for (const f of files) body.append('files', f)
  // the upload response is a short state; the full state comes from GET
  return contractFetch<{ code: string }>('/api/imports', { method: 'POST', body }).then((r) =>
    getImport(r.code),
  )
}
export const getImport = (code: string) => adapt(contractFetch<RealImport>(`/api/imports/${code}`))
export const inspectImport = (code: string) =>
  contractFetch<unknown>(`/api/imports/${code}/inspect`, { method: 'POST' }).then(() => getImport(code))
export const proposeMapping = (code: string) =>
  contractFetch<unknown>(`/api/imports/${code}/propose-mapping`, { method: 'POST' }).then(() =>
    getImport(code),
  )
export const answerQuestion = (code: string, key: string, value: string) =>
  contractFetch<unknown>(`/api/imports/${code}/answers`, { method: 'POST', json: { [key]: value } }).then(
    () => getImport(code),
  )
export const testRun = (code: string, rows = 50) =>
  contractFetch<unknown>(`/api/imports/${code}/test-run`, { method: 'POST', json: { rows } }).then(() =>
    getImport(code),
  )
export const approveImport = (code: string, importer_name: string) =>
  contractFetch<unknown>(`/api/imports/${code}/approve`, { method: 'POST', json: { importer_name } })
export const runImport = (code: string) =>
  contractFetch<{ job_id: number; run_id: string }>(`/api/imports/${code}/run`, { method: 'POST' })

export const importersQuery = queryOptions({
  queryKey: ['importers'],
  queryFn: async () => adaptImporters(await contractFetch<RealImporter[]>('/api/importers')),
})

export const jobQuery = (id: number | null) =>
  queryOptions({
    queryKey: ['job', id],
    enabled: id !== null,
    queryFn: () => contractFetch<JobOut>(`/api/jobs/${id}`),
    refetchInterval: (q) =>
      q.state.data && ['done', 'failed', 'error', 'cancelled'].includes(q.state.data.status) ? false : 1200,
  })

export const startEnrich = () =>
  contractFetch<JobOut>('/api/jobs', { method: 'POST', json: { kind: 'load_all', payload: {} } })
