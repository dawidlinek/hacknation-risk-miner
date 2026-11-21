import { useQuery } from '@tanstack/react-query'
import { Layer, Map as MapGL, type MapRef, Marker, Source } from '@vis.gl/react-maplibre'
import type { FeatureCollection, Point } from 'geojson'
import type { MapLayerMouseEvent, StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MonitoringMode, Signal } from '@/api/contracts/monitoring'
import { cn } from '@/lib/cn'
import { fmtInt } from '@/lib/format'
import {
  type Bbox,
  bboxOf,
  type GeoFC,
  gmiGeoQuery,
  labelsQuery,
  POLAND_BBOX,
  powGeoQuery,
  wojGeoQuery,
} from './geo'
import { pillStacks, type ScaledRegion, tintFor } from './logic'
import { maplibregl } from './maplibre-setup'

const STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#FFFFFF' } }],
}

const GREY = '#E7E7E5'
const WHITE = '#FFFFFF'

export interface MapTarget {
  level: 0 | 1 | 2 | 3
  woj?: string
  pow?: string
  signalId?: string
}

export interface ChoroplethMapProps {
  target: MapTarget
  mode: MonitoringMode
  /** voivodeship colouring (level 0) */
  regions: ScaledRegion[]
  /** signals counted per powiat (level 1) and per gmina (levels 2-3) */
  powCounts: Map<string, number>
  gmiCounts: Map<string, number>
  powNames: Map<string, string>
  gmiNames: Map<string, string>
  signals: Signal[]
  showPins: boolean
  /** px to keep free on the left when fitting (the floating list on narrow layouts) */
  leftPad?: number
  onSelectWoj: (terc: string) => void
  onSelectPow: (terc: string) => void
  onSelectSignal: (s: Signal) => void
  /** value formatter of the active metric (labels on the map) */
  fmt: (v: number) => string
  /** the minus button: one level up in the drill-down */
  onUp: () => void
}

function emptyFC(): GeoFC {
  return { type: 'FeatureCollection', features: [] }
}

const reduced = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function ChoroplethMap(p: ChoroplethMapProps) {
  const ref = useRef<MapRef>(null)
  const { target } = p
  const woj = useQuery(wojGeoQuery)
  const pow = useQuery({ ...powGeoQuery(target.woj ?? '12'), enabled: Boolean(target.woj) })
  const gmi = useQuery({ ...gmiGeoQuery(target.pow ?? '1209'), enabled: Boolean(target.pow) })
  const wojLabels = useQuery(labelsQuery('woj-labels'))
  const powLabels = useQuery({ ...labelsQuery('pow-centroids'), enabled: target.level === 1 })
  const gmiLabels = useQuery({ ...labelsQuery('gmi-centroids'), enabled: target.level >= 2 })
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)

  const byTerc = useMemo(() => new Map(p.regions.map((r) => [r.stat.teryt, r])), [p.regions])

  // voivodeships: coloured at level 0, grey elsewhere (the selected one is covered by its powiats)
  const wojFC = useMemo<GeoFC>(() => {
    if (!woj.data) return emptyFC()
    return {
      ...woj.data,
      features: woj.data.features.map((f) => ({
        ...f,
        properties: {
          ...f.properties,
          fill:
            target.level === 0
              ? (byTerc.get(f.properties.terc)?.fill ?? GREY)
              : f.properties.terc === target.woj
                ? 'rgba(255,255,255,0)'
                : GREY,
          tip:
            target.level === 0
              ? `${f.properties.name}: ${byTerc.get(f.properties.terc)?.value ?? 'za mało danych'}`
              : f.properties.name,
        },
      })),
    }
  }, [woj.data, byTerc, target.level, target.woj])

  const powFC = useMemo<GeoFC>(() => {
    if (!pow.data || target.level === 0) return emptyFC()
    return {
      ...pow.data,
      features: pow.data.features.map((f) => {
        const n = p.powCounts.get(f.properties.terc) ?? 0
        const on = f.properties.terc === target.pow
        const fill =
          target.level >= 2
            ? on
              ? 'rgba(255,255,255,0.92)'
              : 'rgba(255,255,255,0.25)'
            : (tintFor(n) ?? 'rgba(255,255,255,0.55)')
        return {
          ...f,
          properties: {
            ...f.properties,
            fill,
            on: on ? 1 : 0,
            tip: `${f.properties.name}${n ? `: ${n} sygnałów` : ''}`,
          },
        }
      }),
    }
  }, [pow.data, p.powCounts, target.level, target.pow])

  const gmiFC = useMemo<GeoFC>(() => {
    if (!gmi.data || target.level < 2) return emptyFC()
    const sel = p.signals.find((s) => s.id === target.signalId)?.teryt.gmi
    return {
      ...gmi.data,
      features: gmi.data.features.map((f) => {
        const on = f.properties.terc === sel
        const has = (p.gmiCounts.get(f.properties.terc) ?? 0) > 0
        return {
          ...f,
          properties: {
            ...f.properties,
            fill: on ? '#FFF3EB' : has ? '#FFFFFF' : '#FAFAFA',
            on: on ? 1 : 0,
            tip: f.properties.name,
          },
        }
      }),
    }
  }, [gmi.data, p.gmiCounts, p.signals, target.level, target.signalId])

  const pinsFC = useMemo<FeatureCollection<Point>>(
    () => ({
      type: 'FeatureCollection',
      features: p.signals
        .filter((s) => s.lon !== null && s.lat !== null)
        .map((s) => ({
          type: 'Feature' as const,
          properties: {
            id: s.id,
            r: 2 + Math.sqrt(Math.max(Number(s.value.amount ?? 0), 0) / 1e6) * 1.6,
            sel: s.id === target.signalId ? 1 : 0,
          },
          geometry: { type: 'Point' as const, coordinates: [s.lon as number, s.lat as number] },
        })),
    }),
    [p.signals, target.signalId],
  )

  // fit the camera to the target
  const bbox = useMemo<Bbox>(() => {
    if (target.level === 0 || !woj.data) return POLAND_BBOX
    if (target.level === 1)
      return bboxOf(woj.data.features.filter((f) => f.properties.terc === target.woj)) ?? POLAND_BBOX
    if (target.level === 2 && pow.data)
      return bboxOf(pow.data.features.filter((f) => f.properties.terc === target.pow)) ?? POLAND_BBOX
    const s = p.signals.find((x) => x.id === target.signalId)
    const g = gmi.data?.features.filter((f) => f.properties.terc === s?.teryt.gmi)
    return (
      (g && bboxOf(g)) ||
      (pow.data && bboxOf(pow.data.features.filter((f) => f.properties.terc === target.pow))) ||
      POLAND_BBOX
    )
  }, [target.level, target.woj, target.pow, target.signalId, woj.data, pow.data, gmi.data, p.signals])

  const [ready, setReady] = useState(false)
  useEffect(() => {
    const map = ref.current?.getMap()
    if (!map || !ready) return
    map.fitBounds(
      [
        [bbox[0], bbox[1]],
        [bbox[2], bbox[3]],
      ],
      {
        padding: { left: (p.leftPad ?? 0) + 24, right: 24, top: 24, bottom: 88 },
        duration: reduced() ? 0 : 600,
        maxZoom: target.level === 3 ? 12 : 10,
      },
    )
  }, [bbox, ready, p.leftPad, target.level])

  const onClick = (e: MapLayerMouseEvent) => {
    const f = e.features?.[0]
    if (!f) return
    if (f.layer.id === 'pin') {
      const s = p.signals.find((x) => x.id === String(f.properties.id))
      if (s) p.onSelectSignal(s)
    } else if (f.layer.id === 'pow-fill' && target.level >= 1) p.onSelectPow(String(f.properties.terc))
    else if (f.layer.id === 'woj-fill' && target.level === 0) p.onSelectWoj(String(f.properties.terc))
    else if (f.layer.id === 'woj-fill' && target.level >= 1) p.onSelectWoj(String(f.properties.terc))
  }
  const onMove = (e: MapLayerMouseEvent) => {
    const f = e.features?.[0]
    if (!f) return setTip(null)
    setTip({ x: e.point.x, y: e.point.y, text: String(f.properties.tip ?? f.properties.name ?? '') })
  }

  // labels
  const wojLabelList = useMemo(
    () =>
      target.level === 0 && wojLabels.data
        ? p.regions
            .filter((r) => wojLabels.data[r.stat.teryt])
            .map((r) => ({ r, at: wojLabels.data[r.stat.teryt] }))
        : [],
    [target.level, wojLabels.data, p.regions],
  )
  const powLabelList = useMemo(
    () =>
      target.level === 1 && powLabels.data
        ? [...p.powCounts.entries()]
            .filter(([c]) => powLabels.data[c])
            .map(([c, n]) => ({
              c,
              n,
              at: powLabels.data[c],
              name: (p.powNames.get(c) ?? c).replace('powiat ', ''),
            }))
        : [],
    [target.level, powLabels.data, p.powCounts, p.powNames],
  )
  const gmiLabelList = useMemo(
    () =>
      target.level >= 2 && gmiLabels.data && gmi.data
        ? gmi.data.features
            .filter((f) => gmiLabels.data[f.properties.terc])
            .map((f) => ({
              c: f.properties.terc,
              name: f.properties.name,
              at: gmiLabels.data[f.properties.terc],
            }))
        : [],
    [target.level, gmiLabels.data, gmi.data],
  )
  const stacks = useMemo(() => pillStacks(p.signals), [p.signals])
  const pillSignals =
    target.level >= 2 ? (p.showPins ? p.signals : p.signals.filter((s) => s.id === target.signalId)) : []

  return (
    <div className="relative h-full w-full overflow-hidden rounded-card bg-surface">
      <MapGL
        ref={ref}
        mapLib={maplibregl as never}
        mapStyle={STYLE}
        initialViewState={{ bounds: POLAND_BBOX, fitBoundsOptions: { padding: 24 } }}
        attributionControl={false}
        dragRotate={false}
        touchPitch={false}
        interactiveLayerIds={['woj-fill', 'pow-fill', 'pin']}
        onClick={onClick}
        onMouseMove={onMove}
        onMouseLeave={() => setTip(null)}
        onLoad={() => setReady(true)}
        cursor={tip ? 'pointer' : 'grab'}
        style={{ width: '100%', height: '100%' }}
      >
        <Source id="woj" type="geojson" data={wojFC}>
          <Layer id="woj-fill" type="fill" paint={{ 'fill-color': ['get', 'fill'] }} />
          <Layer
            id="woj-line"
            type="line"
            paint={{ 'line-color': WHITE, 'line-width': target.level === 0 ? 0.9 : 0.6 }}
          />
        </Source>
        <Source id="pow" type="geojson" data={powFC}>
          <Layer id="pow-fill" type="fill" paint={{ 'fill-color': ['get', 'fill'] }} />
          <Layer
            id="pow-line"
            type="line"
            paint={{
              'line-color': ['case', ['==', ['get', 'on'], 1], '#0A0A0A', WHITE],
              'line-width': ['case', ['==', ['get', 'on'], 1], 1.4, 0.7],
            }}
          />
        </Source>
        <Source id="gmi" type="geojson" data={gmiFC}>
          <Layer id="gmi-fill" type="fill" paint={{ 'fill-color': ['get', 'fill'] }} />
          <Layer
            id="gmi-line"
            type="line"
            paint={{
              'line-color': ['case', ['==', ['get', 'on'], 1], '#C2410C', '#A3A3A3'],
              'line-width': ['case', ['==', ['get', 'on'], 1], 1.6, 0.5],
            }}
          />
        </Source>
        {p.showPins && target.level < 2 ? (
          <Source id="pins" type="geojson" data={pinsFC}>
            <Layer
              id="pin"
              type="circle"
              paint={{
                'circle-radius': ['get', 'r'],
                'circle-color': '#EA580C',
                'circle-opacity': 0.55,
                'circle-stroke-color': '#C2410C',
                'circle-stroke-width': 0.6,
              }}
            />
          </Source>
        ) : null}

        {wojLabelList.map(({ r, at }) => (
          <Marker
            key={r.stat.teryt}
            longitude={at[0]}
            latitude={at[1]}
            anchor="center"
            style={{ pointerEvents: 'none' }}
          >
            <div
              className={cn(
                'flex flex-col items-center text-center leading-tight',
                r.lightText ? 'text-white' : 'text-ink',
              )}
            >
              <span className="text-[10px] font-medium">{r.stat.name}</span>
              <span className="text-[12px] font-semibold">
                {r.value === null ? 'za mało danych' : fmtMetric(r.value)}
              </span>
            </div>
          </Marker>
        ))}
        {powLabelList.map(({ c, n, at, name }) => (
          <Marker
            key={c}
            longitude={at[0]}
            latitude={at[1]}
            anchor="center"
            style={{ pointerEvents: 'none' }}
          >
            <div className="flex flex-col items-center text-center leading-tight text-ink">
              <span className="text-[11px] font-medium">{name}</span>
              <span className="text-[10px] text-text-secondary">
                {n} {n === 1 ? 'sygnał' : n < 5 ? 'sygnały' : 'sygnałów'}
              </span>
            </div>
          </Marker>
        ))}
        {gmiLabelList.map(({ c, name, at }) => (
          <Marker
            key={c}
            longitude={at[0]}
            latitude={at[1]}
            anchor="center"
            style={{ pointerEvents: 'none' }}
          >
            <span className="text-[10px] text-text-secondary">{name}</span>
          </Marker>
        ))}
        {pillSignals
          .filter((s) => s.lon !== null && s.lat !== null)
          .map((s) => {
            const on = s.id === target.signalId
            return (
              <Marker
                key={s.id}
                longitude={s.lon as number}
                latitude={s.lat as number}
                anchor="bottom"
                offset={[0, -(stacks.get(s.id) ?? 0) * 14]}
              >
                <button
                  type="button"
                  onClick={() => p.onSelectSignal(s)}
                  aria-label={`Umowa ${s.buyer}, ${s.days_late ?? 0} dni po terminie`}
                  className={cn(
                    'rounded-pill border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap shadow-sm',
                    on
                      ? 'border-attention-text bg-attention-text text-white'
                      : 'border-attention-text bg-surface text-attention-text',
                  )}
                >
                  +{fmtInt(s.days_late ?? 0)} d
                </button>
              </Marker>
            )
          })}
      </MapGL>
      <div className="absolute top-3 right-3 flex flex-col gap-1">
        {(['+', '−'] as const).map((s) => (
          <button
            key={s}
            type="button"
            aria-label={s === '+' ? 'Przybliż' : p.target.level === 0 ? 'Oddal' : 'Poziom wyżej'}
            onClick={() => (s === '+' ? ref.current?.getMap().zoomIn() : p.onUp())}
            className="size-9 rounded-md border border-border bg-surface text-[18px] leading-none shadow-sm hover:bg-soft"
          >
            {s}
          </button>
        ))}
      </div>
      {tip ? (
        <div
          className="pointer-events-none absolute z-10 rounded-md bg-ink px-2 py-1 text-[12px] text-on-ink"
          style={{ left: tip.x + 12, top: tip.y + 12 }}
        >
          {tip.text}
        </div>
      ) : null}
    </div>
  )

  function fmtMetric(v: number) {
    return p.fmt(v)
  }
}
