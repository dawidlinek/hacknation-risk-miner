import { createContext, useContext } from 'react'
import type { MetricKey, MonitoringMode, RegionsOut } from '@/api/contracts/monitoring'
import type { GeoFC } from './geo'
import type { MetricDef, ScaledRegion } from './logic'

export interface MonitoringSearch {
  tryb?: 'done' | 'open'
  miara?: string
  sygnaly?: number
  q?: string
}

export interface MonitoringCtx {
  mode: MonitoringMode
  metric: MetricKey
  def: MetricDef
  wojRegions: RegionsOut | undefined
  scaled: ScaledRegion[]
  wojGeo: GeoFC | undefined
  pins: boolean
  /** replay date (YYYY-MM-DD) from the time machine, null = today */
  asOf: string | null
  search: MonitoringSearch
  setSearch: (patch: Partial<MonitoringSearch>) => void
}

export const MonitoringContext = createContext<MonitoringCtx | null>(null)
export function useMonitoring(): MonitoringCtx {
  const c = useContext(MonitoringContext)
  if (!c) throw new Error('useMonitoring outside MonitoringLayout')
  return c
}
