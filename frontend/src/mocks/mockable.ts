import {
  type DefaultBodyType,
  delay,
  HttpResponse,
  type HttpResponseResolver,
  http,
  type PathParams,
  passthrough,
} from 'msw'
import { isMocked, type MockGroup } from './config'

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'
type Resolver<P extends PathParams = PathParams> = HttpResponseResolver<P, DefaultBodyType, DefaultBodyType>

/**
 * `const m = mockable('analyses'); export const handlers = [m.get('/api/analyses/:id', ({ params }) => HttpResponse.json(x))]`
 * The resolver runs only while its group is mocked; otherwise the request passes through to the real backend.
 * Every mocked response gets `x-rm-mock: 1` (MockBadge shows "dane przykładowe").
 */
export function mockable(group: MockGroup, opts: { latency?: number } = {}) {
  const make =
    (method: Method) =>
    <P extends PathParams = PathParams>(path: string, resolver: Resolver<P>) =>
      http[method]<P>(path, async (info) => {
        if (!isMocked(group)) return passthrough()
        if (import.meta.env.MODE !== 'test') await delay(opts.latency ?? 180)
        const res = (await resolver(info as never)) as Response | undefined
        if (!res) return res
        try {
          res.headers.set('x-rm-mock', '1')
          res.headers.set('x-rm-mock-group', group)
          return res
        } catch {
          const headers = new Headers(res.headers)
          headers.set('x-rm-mock', '1')
          headers.set('x-rm-mock-group', group)
          return new HttpResponse(res.body, { status: res.status, headers })
        }
      })
  return {
    get: make('get'),
    post: make('post'),
    put: make('put'),
    patch: make('patch'),
    delete: make('delete'),
  }
}

export { delay, HttpResponse }
