export const env = {
  dev: import.meta.env.DEV,
  prod: import.meta.env.PROD,
  test: import.meta.env.MODE === 'test',
  mocks: (import.meta.env.VITE_MOCKS ?? 'none') as string,
  apiBase: (import.meta.env.VITE_API_BASE ?? '') as string,
}
