import { queryOptions, useQuery } from '@tanstack/react-query'
import { notFound } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { env } from './env'

/**
 * Feature flags. Source of truth: config/config.yaml → features, served by GET /api/config/features.
 * The server values are merged over these defaults; an unknown or missing flag reads as off.
 */
export const FEATURE_DEFAULTS = {
  // existing in config.example.yaml
  red_pen: false,
  unit_cost: true,
  backtest: false,
  case_graph: true,
  monte_carlo: false,
  radar: false,
  learning_loop: false,
  sovereign_switch: false,
  /** read-only data-location view (Ustawienia) without the sovereign switch */
  settings_view: false,
  ask_memory: false,
  // new flags (frontend.md §1.6), off until the backend adds them
  allocation: true,
  pack_export: true,
  radar_drill: false,
  monitoring_replay: false,
  review_queue: false,
  catalogue_edit: false,
  import_agent: false,
  project_docs: false,
  project_history: false,
  jelly: false,
  dashboard: false,
} as const

export type FeatureName = keyof typeof FEATURE_DEFAULTS
export type Features = Record<FeatureName, boolean>

let devOverride: Partial<Features> = {}
/** Dev-only `?ff=red_pen,radar` (persisted for the tab in sessionStorage). */
function readDevOverride(): Partial<Features> {
  if (!env.dev || typeof window === 'undefined') return {}
  try {
    const q = new URLSearchParams(window.location.search).get('ff')
    if (q !== null) sessionStorage.setItem('rm.ff', q)
    const raw = q ?? sessionStorage.getItem('rm.ff') ?? ''
    const out: Partial<Features> = {}
    for (const part of raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)) {
      if (part.startsWith('-')) out[part.slice(1) as FeatureName] = false
      else out[part as FeatureName] = true
    }
    return out
  } catch {
    return {}
  }
}
devOverride = readDevOverride()

export function mergeFeatures(server: Record<string, unknown> | null | undefined): Features {
  const out = { ...FEATURE_DEFAULTS } as Features
  if (server) {
    for (const [k, v] of Object.entries(server)) {
      if (k in out && typeof v === 'boolean') out[k as FeatureName] = v
    }
  }
  const merged = { ...out, ...devOverride }
  // the sovereign switch implies the settings view
  if (merged.sovereign_switch) merged.settings_view = true
  return merged
}

export const featuresQuery = queryOptions({
  queryKey: ['config', 'features'],
  queryFn: async (): Promise<Features> => {
    try {
      const res = await fetch(`${env.apiBase}/api/config/features`, { credentials: 'include' })
      if (!res.ok) return mergeFeatures(null)
      const body = (await res.json()) as Record<string, unknown> | { features: Record<string, unknown> }
      const flags =
        'features' in body && typeof body.features === 'object'
          ? (body.features as Record<string, unknown>)
          : (body as Record<string, unknown>)
      return mergeFeatures(flags)
    } catch {
      return mergeFeatures(null)
    }
  },
  staleTime: Number.POSITIVE_INFINITY,
})

export function useFeatures(): Features {
  return useQuery(featuresQuery).data ?? mergeFeatures(null)
}
export function useFeature(name: FeatureName): boolean {
  return useFeatures()[name]
}
export function Feature({
  name,
  children,
  fallback = null,
}: {
  name: FeatureName
  children: ReactNode
  fallback?: ReactNode
}) {
  return useFeature(name) ? children : fallback
}

/** For `beforeLoad`: a disabled flag throws notFound(). */
export async function requireFeature(
  ctx: { queryClient: import('@tanstack/react-query').QueryClient },
  name: FeatureName,
) {
  const f = await ctx.queryClient.ensureQueryData(featuresQuery)
  if (!f[name]) throw notFound()
}
