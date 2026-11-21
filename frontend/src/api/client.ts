import createClient, { type Middleware } from 'openapi-fetch'
import createQueryClient from 'openapi-react-query'
import { env } from '@/config/env'
import { markMockResponse } from './mockSignal'
import type { paths } from './schema.gen'

export class ApiError extends Error {
  status: number
  detail: string
  code: string | null
  requestId: string | null
  constructor(status: number, detail: string, code: string | null = null, requestId: string | null = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = code
    this.requestId = requestId
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = `Błąd serwera (${res.status}).`
  let code: string | null = null
  try {
    const body = await res.clone().json()
    if (typeof body?.detail === 'string') detail = body.detail
    else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join('; ')
    if (typeof body?.code === 'string') code = body.code
  } catch {
    /* not json */
  }
  return new ApiError(res.status, detail, code, res.headers.get('x-request-id'))
}

const WRITE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
function withHeaders(init: RequestInit = {}, method = 'GET'): RequestInit {
  const headers = new Headers(init.headers)
  if (WRITE.has(method.toUpperCase())) headers.set('X-Requested-With', 'ex-ante')
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  return { credentials: 'include', ...init, method, headers }
}

const middleware: Middleware = {
  onRequest({ request }) {
    if (WRITE.has(request.method)) request.headers.set('X-Requested-With', 'ex-ante')
    return request
  },
  async onResponse({ response }) {
    markMockResponse(response)
    if (!response.ok) throw await toApiError(response)
    return response
  },
}

export const http = createClient<paths>({ baseUrl: env.apiBase, credentials: 'include' })
http.use(middleware)
export const $api = createQueryClient(http)

/**
 * For endpoints not (yet) in schema.gen.ts: typed by the hand-written contract in api/contracts.
 * Same behaviour as `http`: mock signal, ApiError on non-2xx, CSRF header on writes.
 */
export async function contractFetch<T>(
  path: string,
  init: Omit<RequestInit, 'body'> & {
    method?: string
    json?: unknown
    body?: BodyInit
    query?: Record<string, unknown>
  } = {},
): Promise<T> {
  const { json, query, method = 'GET', ...rest } = init
  let url = `${env.apiBase}${path}`
  if (query) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '') continue
      qs.set(k, Array.isArray(v) ? v.join(',') : String(v))
    }
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  const req = withHeaders(rest, method)
  if (json !== undefined) {
    ;(req.headers as Headers).set('Content-Type', 'application/json')
    req.body = JSON.stringify(json)
  } else if (rest.body !== undefined) {
    req.body = rest.body
  }
  const res = await fetch(url, req)
  markMockResponse(res)
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('json') ? await res.json() : await res.text()) as T
}
