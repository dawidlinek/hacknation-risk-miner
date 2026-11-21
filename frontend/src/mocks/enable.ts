import { anyMocked } from './config'

/** Starts the MSW worker when at least one group is mocked. Unhandled requests go to the real backend. */
export async function enableMocking() {
  if (typeof window === 'undefined' || !anyMocked()) return
  const { worker } = await import('./browser')
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true, serviceWorker: { url: '/mockServiceWorker.js' } })
}
