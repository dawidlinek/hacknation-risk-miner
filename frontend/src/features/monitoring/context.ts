import { createContext, useContext } from 'react'
import type { MetricKey, MonitoringMode, RegionsOut, Signal } from '@/api/contracts/monitoring'
import type { MonFilters } from './api'
import type { GeoFC } from './geo'
import type { MetricDef, ScaledRegion } from './logic'

export interface MonitoringSearch {
  tryb?: 'done' | 'open'
  miara?: string
  sygnaly?: number
  q?: string
  podsektor?: string
  wartosc?: string
  rok?: number
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
  /** Podsektor, Wartość, Lata from the filter bar, passed to every monitoring query */
  filters: MonFilters
  setSearch: (patch: Partial<MonitoringSearch>) => void
  /** the voivodeship numbers on screen belong to the previous filters while the new ones load */
  wojStale: boolean
  /** name of a voivodeship or powiat already loaded for the map (panels show it before their own data lands) */
  regionName: (terc: string) => string | undefined
  /** a signal already loaded for the map, by contract id */
  signalById: (id: string) => Signal | undefined
  /** hover intent on the map or a list row: fetch the next level before the click */
  prefetch: { woj: (terc: string) => void; pow: (terc: string) => void; signal: (s: Signal) => void }
}

export const MonitoringContext = createContext<MonitoringCtx | null>(null)
export function useMonitoring(): MonitoringCtx {
  const c = useContext(MonitoringContext)
  if (!c) throw new Error('useMonitoring outside MonitoringLayout')
  return c
}
