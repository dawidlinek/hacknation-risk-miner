import { useQuery } from '@tanstack/react-query'
import { Layer, Map as MapGL, type MapRef, Marker, Source } from '@vis.gl/react-maplibre'
import type { FeatureCollection, Point } from 'geojson'
import type { MapGeoJSONFeature, MapLayerMouseEvent, StyleSpecification } from 'maplibre-gl'
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
import { type Box, colorAt, placeBoxes, planPills, type ScaledRegion, umowy } from './logic'
import { maplibregl } from './maplibre-setup'

const STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#FFFFFF' } }],
}

const GREY = '#E7E7E5'
const WHITE = '#FFFFFF'
/** Camera flight between levels and the cross-fade of the region layers, ms. */
const FLY_MS = 650
const FADE = { duration: 350, delay: 0 }

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
  /** powiat counts of the selected voivodeship are in (the powiat layer fades in once they are) */
  powReady: boolean
  powNames: Map<string, string>
  gmiNames: Map<string, string>
  signals: Signal[]
  showPins: boolean
  /** px to keep free on the left when fitting (the floating list on narrow layouts) */
  leftPad?: number
  onSelectWoj: (terc: string) => void
  onSelectPow: (terc: string) => void
  onSelectSignal: (s: Signal) => void
  /** hover intent: the layout prefetches the next level so the click lands on cached data */
  prefetch?: { woj: (terc: string) => void; pow: (terc: string) => void; signal: (s: Signal) => void }
  /** value formatter of the active metric (labels on the map) */
  fmt: (v: number) => string
  /** the minus button: one level up in the drill-down */
  onUp: () => void
}

/** Pills shown on the powiat map without pins; signals arrive sorted by days overdue. */
const PILL_CAP = 12
/** Height of one "+N d" pill plus the gap to the next one in a stack, px. */
const PILL_STEP = 24

function emptyFC(): GeoFC {
  return { type: 'FeatureCollection', features: [] }
}

const reduced = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Remembers the last defined value, so a layer can fade out with the data it showed. */
function useLast<T>(v: T | undefined): T | undefined {
  const r = useRef(v)
  if (v !== undefined) r.current = v
  return r.current
}

const pillText = (s: Signal) => `+${fmtInt(s.days_late ?? 0)} d`

export function ChoroplethMap(p: ChoroplethMapProps) {
  const ref = useRef<MapRef>(null)
  const { target } = p
  // the last voivodeship and powiat stay loaded on the way up, so their layers fade out instead of vanishing
  const lastWoj = useLast(target.woj)
  const lastPow = useLast(target.pow)
  const woj = useQuery(wojGeoQuery)
  const pow = useQuery({ ...powGeoQuery(lastWoj ?? '12'), enabled: Boolean(lastWoj) })
  const gmi = useQuery({ ...gmiGeoQuery(lastPow ?? '1209'), enabled: Boolean(lastPow) })
  const wojLabels = useQuery(labelsQuery('woj-labels'))
  const powLabels = useQuery(labelsQuery('pow-centroids'))
  const gmiLabels = useQuery({ ...labelsQuery('gmi-centroids'), enabled: target.level >= 1 })
  const [tip, setTip] = useState<{ x: number; y: number; text: string; click: boolean } | null>(null)
  const hovered = useRef<string | null>(null)

  const byTerc = useMemo(() => new Map(p.regions.map((r) => [r.stat.teryt, r])), [p.regions])

  // voivodeships keep their metric colour; deeper levels fade the "woj-dim" and "woj-sel" layers in on top
  const wojFC = useMemo<GeoFC>(() => {
    if (!woj.data) return emptyFC()
    return {
      ...woj.data,
      features: woj.data.features.map((f) => {
        const r = byTerc.get(f.properties.terc)
        return {
          ...f,
          properties: {
            ...f.properties,
            fill: r?.fill ?? GREY,
            tip: `${f.properties.name}: ${r?.value == null ? 'za mało danych' : p.fmt(r.value)}`,
          },
        }
      }),
    }
  }, [woj.data, byTerc, p.fmt])

  const powFC = useMemo<GeoFC>(() => {
    if (!pow.data || pow.data.features[0]?.properties.terc.slice(0, 2) !== lastWoj) return emptyFC()
    return {
      ...pow.data,
      features: pow.data.features.map((f) => {
        const n = p.powCounts.get(f.properties.terc) ?? 0
        const on = f.properties.terc === target.pow
        // relative yellow-to-red scale: the busiest powiat in this województwo is the darkest
        const maxN = Math.max(1, ...p.powCounts.values())
        const fill =
          target.level >= 2
            ? on
              ? 'rgba(255,255,255,0.92)'
              : 'rgba(255,255,255,0.25)'
            : n > 0
              ? colorAt(0.15 + 0.85 * (n / maxN), 'open')
              : 'rgba(255,255,255,0.55)'
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
  }, [pow.data, lastWoj, p.powCounts, target.level, target.pow])

  const gmiFC = useMemo<GeoFC>(() => {
    if (!gmi.data) return emptyFC()
    const sel = p.signals.find((s) => s.id === target.signalId)?.teryt.gmi
    // gminas coloured by signal count (yellow to red, relative to the busiest gmina in this powiat)
    const maxN = Math.max(1, ...gmi.data.features.map((f) => p.gmiCounts.get(f.properties.terc) ?? 0))
    return {
      ...gmi.data,
      features: gmi.data.features.map((f) => {
        const on = f.properties.terc === sel
        const n = p.gmiCounts.get(f.properties.terc) ?? 0
        return {
          ...f,
          properties: {
            ...f.properties,
            fill: n > 0 ? colorAt(0.15 + 0.85 * (n / maxN), 'open') : on ? '#FFF6D1' : '#F4F4F2',
            on: on ? 1 : 0,
            n,
            tip:
              n > 0
                ? `${f.properties.name}: ${n} ${n === 1 ? 'sygnał' : n < 5 ? 'sygnały' : 'sygnałów'}`
                : f.properties.name,
          },
        }
      }),
    }
  }, [gmi.data, p.gmiCounts, p.signals, target.signalId])

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
    const powBox = pow.data && bboxOf(pow.data.features.filter((f) => f.properties.terc === target.pow))
    const wojBox = bboxOf(woj.data.features.filter((f) => f.properties.terc === target.woj))
    if (target.level === 2) return powBox || wojBox || POLAND_BBOX
    const s = p.signals.find((x) => x.id === target.signalId)
    const g = gmi.data?.features.filter((f) => f.properties.terc === s?.teryt.gmi)
    return (g && bboxOf(g)) || powBox || wojBox || POLAND_BBOX
  }, [target.level, target.woj, target.pow, target.signalId, woj.data, pow.data, gmi.data, p.signals])
  // refit only when the box itself changes, not on every new array (data refreshes must not restart the flight)
  const bboxKey = bbox.map((v) => v.toFixed(4)).join(',')

  const [ready, setReady] = useState(false)
  // labels and pills wait until the style, the sources and the first frame are in (otherwise they pile up at the centre)
  const [idle, setIdle] = useState(false)
  // ...and until the camera has landed on the new level; `view` counts landings so label placement is recomputed
  const [settled, setSettled] = useState(false)
  const [view, setView] = useState(0)
  const targetKey = `${target.level}|${target.woj}|${target.pow}|${target.signalId}`
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on every new target
  useEffect(() => {
    setTip(null)
  }, [targetKey])
  useEffect(() => {
    const map = ref.current?.getMap()
    if (!map || !ready) return
    const [w, s, e, n] = bboxKey.split(',').map(Number)
    const duration = reduced() ? 0 : FLY_MS
    setSettled(false)
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      {
        padding: { left: (p.leftPad ?? 0) + 24, right: 24, top: 24, bottom: 88 },
        duration,
        maxZoom: target.level === 3 ? 12 : 10,
      },
    )
    // moveend lands the labels; the timer covers a fit that did not move the camera
    const t = setTimeout(() => {
      setSettled(true)
      setView((v) => v + 1)
    }, duration + 150)
    return () => clearTimeout(t)
  }, [bboxKey, ready, p.leftPad, target.level])

  /** The feature under the pointer that this level reacts to (hidden layers fading out are ignored). */
  const pick = (fs: MapGeoJSONFeature[] | undefined) => {
    const order =
      target.level === 0
        ? ['pin', 'woj-fill']
        : target.level === 1
          ? ['pin', 'pow-fill', 'woj-fill']
          : ['gmi-fill', 'pow-fill', 'woj-fill']
    for (const id of order) {
      const f = fs?.find(
        (x) =>
          x.layer.id === id &&
          !(id === 'woj-fill' && target.level >= 1 && x.properties.terc === target.woj) &&
          !(id === 'pow-fill' && target.level >= 2 && x.properties.terc === target.pow),
      )
      if (f) return f
    }
    return undefined
  }

  const onClick = (e: MapLayerMouseEvent) => {
    // a click on a pill or label is the marker's own; maplibre reports it as a map click as well
    if ((e.originalEvent?.target as Element | null)?.closest?.('.maplibregl-marker')) return
    const f = pick(e.features)
    if (!f) return
    const terc = String(f.properties.terc)
    if (f.layer.id === 'pin') {
      const s = p.signals.find((x) => x.id === String(f.properties.id))
      if (s) p.onSelectSignal(s)
    } else if (f.layer.id === 'gmi-fill') {
      // a gmina with signals opens its longest overdue contract (signals come sorted by delay)
      const s = p.signals.find((x) => x.teryt.gmi === terc)
      if (s) p.onSelectSignal(s)
    } else if (f.layer.id === 'pow-fill') p.onSelectPow(terc)
    else if (f.layer.id === 'woj-fill') p.onSelectWoj(terc)
  }
  const onMove = (e: MapLayerMouseEvent) => {
    if ((e.originalEvent?.target as Element | null)?.closest?.('.maplibregl-marker')) return setTip(null)
    const f = pick(e.features)
    if (!f) return setTip(null)
    // a gmina without signals has nothing to open: name only, no pointer
    const click = f.layer.id !== 'gmi-fill' || Number(f.properties.n) > 0
    setTip({ x: e.point.x, y: e.point.y, text: tipFor(f), click })
    const key = `${f.layer.id}:${f.properties.terc ?? f.properties.id}`
    if (hovered.current === key) return
    hovered.current = key
    if (f.layer.id === 'woj-fill') p.prefetch?.woj(String(f.properties.terc))
    else if (f.layer.id === 'pow-fill') p.prefetch?.pow(String(f.properties.terc))
    else if (f.layer.id === 'pin') {
      const s = p.signals.find((x) => x.id === String(f.properties.id))
      if (s) p.prefetch?.signal(s)
    }
  }
  const tipFor = (f: MapGeoJSONFeature) => String(f.properties.tip ?? f.properties.name ?? '')

  // pills: the longest overdue (all with pins on) plus the selected one, at most 3 per gmina
  const plan = useMemo(() => {
    if (target.level < 2) return { pills: [], more: [] }
    const list = p.showPins ? p.signals : p.signals.filter((s, i) => i < PILL_CAP || s.id === target.signalId)
    return planPills(list, target.signalId)
  }, [target.level, target.signalId, p.showPins, p.signals])

  // label candidates in priority order: [key, lng/lat, width, height, content]
  type Label = { key: string; at: [number, number]; w: number; h: number; node: React.ReactNode }
  const labels = useMemo<Label[]>(() => {
    if (target.level === 0 && wojLabels.data)
      return p.regions
        .filter((r) => wojLabels.data[r.stat.teryt])
        .map((r) => {
          const v = r.value === null ? 'za mało danych' : p.fmt(r.value)
          return {
            key: `w${r.stat.teryt}`,
            at: wojLabels.data[r.stat.teryt],
            w: Math.max(r.stat.name.length * 5.6, v.length * 7.4) + 6,
            h: 28,
            node: (
              <div
                className={cn(
                  'flex flex-col items-center text-center leading-tight',
                  r.lightText
                    ? 'text-white'
                    : `text-text ${'[text-shadow:0_0_3px_#fff,0_0_2px_#fff,0_0_1px_#fff]'}`,
                )}
              >
                <span className="text-[10px] font-medium">{r.stat.name}</span>
                <span className="text-[12px] font-semibold">{v}</span>
              </div>
            ),
          }
        })
    if (target.level === 1 && powLabels.data)
      return [...p.powCounts.entries()]
        .filter(([c]) => c.startsWith(target.woj ?? '-') && powLabels.data[c])
        .sort((a, b) => b[1] - a[1])
        .map(([c, n]) => {
          const name = (p.powNames.get(c) ?? c).replace('powiat ', '')
          return {
            key: `p${c}`,
            at: powLabels.data[c],
            w: Math.max(name.length * 6, 62) + 6,
            h: 26,
            node: (
              <div className="flex flex-col items-center text-center leading-tight text-text [text-shadow:0_0_3px_#fff,0_0_2px_#fff,0_0_1px_#fff]">
                <span className="text-[11px] font-semibold">{name}</span>
                <span className="text-[10px] text-text">
                  {n} {n === 1 ? 'sygnał' : n < 5 ? 'sygnały' : 'sygnałów'}
                </span>
              </div>
            ),
          }
        })
    if (target.level >= 2 && gmiLabels.data && gmi.data)
      return gmi.data.features
        .filter((f) => gmiLabels.data[f.properties.terc])
        .sort((a, b) => (p.gmiCounts.get(b.properties.terc) ?? 0) - (p.gmiCounts.get(a.properties.terc) ?? 0))
        .map((f) => ({
          key: `g${f.properties.terc}`,
          at: gmiLabels.data[f.properties.terc],
          w: f.properties.name.length * 5.4 + 6,
          h: 14,
          node: <span className="text-[10px] text-text-secondary">{f.properties.name}</span>,
        }))
    return []
  }, [
    target.level,
    target.woj,
    wojLabels.data,
    powLabels.data,
    gmiLabels.data,
    gmi.data,
    p.regions,
    p.powCounts,
    p.powNames,
    p.gmiCounts,
    p.fmt,
  ])

  // collision pass in screen space once the camera has landed: pills first, then labels by priority
  // biome-ignore lint/correctness/useExhaustiveDependencies: `view` re-runs the pass after every landing
  const shownLabels = useMemo(() => {
    const map = ref.current?.getMap()
    if (!map || !settled || !idle) return new Set<string>()
    const c = map.getCanvas()
    const W = c.clientWidth
    const H = c.clientHeight
    const fixed: Box[] = [
      { key: 'zoom', x: W - 56, y: 0, w: 56, h: 100 },
      { key: 'toolbar', x: 0, y: H - 76, w: W, h: 76 },
    ]
    const at = (lng: number, lat: number) => map.project([lng, lat])
    for (const { s, stack } of plan.pills) {
      const pt = at(s.lon as number, s.lat as number)
      const w = pillText(s).length * 6.6 + 18
      fixed.push({ key: `pill${s.id}`, x: pt.x - w / 2, y: pt.y - (stack + 1) * PILL_STEP, w, h: 22 })
    }
    for (const m of plan.more) {
      const pt = at(m.lon, m.lat)
      fixed.push({ key: `more${m.key}`, x: pt.x - 36, y: pt.y - (m.stack + 1) * PILL_STEP, w: 72, h: 20 })
    }
    const boxes = labels.map((l) => {
      const pt = at(l.at[0], l.at[1])
      return { key: l.key, x: pt.x - l.w / 2, y: pt.y - l.h / 2, w: l.w, h: l.h }
    })
    return placeBoxes(boxes, { w: W, h: H }, fixed)
  }, [settled, idle, view, labels, plan])

  const landed = idle && settled

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
        interactiveLayerIds={['woj-fill', 'pow-fill', 'gmi-fill', 'pin']}
        onClick={onClick}
        onMouseMove={onMove}
        onMouseLeave={() => {
          setTip(null)
          hovered.current = null
        }}
        onLoad={() => setReady(true)}
        onIdle={() => setIdle(true)}
        onMoveStart={(e) => {
          // programmatic flights hide the labels until they land; a drag keeps them (they move with the map)
          if (!e.originalEvent) setSettled(false)
        }}
        onMoveEnd={(e) => {
          if (e.target.isMoving()) return
          setSettled(true)
          setView((v) => v + 1)
        }}
        cursor={tip?.click ? 'pointer' : 'grab'}
        style={{ width: '100%', height: '100%' }}
      >
        <Source id="woj" type="geojson" data={wojFC}>
          <Layer id="woj-fill" type="fill" paint={{ 'fill-color': ['get', 'fill'] }} />
          <Layer
            id="woj-dim"
            type="fill"
            filter={['!=', ['get', 'terc'], lastWoj ?? '']}
            paint={{
              'fill-color': GREY,
              'fill-opacity': target.level === 0 ? 0 : 1,
              'fill-opacity-transition': FADE,
            }}
          />
          {/* the selected voivodeship keeps its colour until its powiats are in, then both cross-fade */}
          <Layer
            id="woj-sel"
            type="fill"
            filter={['==', ['get', 'terc'], lastWoj ?? '']}
            paint={{
              'fill-color': WHITE,
              'fill-opacity': target.level >= 1 && p.powReady ? 1 : 0,
              'fill-opacity-transition': FADE,
            }}
          />
          <Layer
            id="woj-line"
            type="line"
            paint={{ 'line-color': WHITE, 'line-width': target.level === 0 ? 0.9 : 0.6 }}
          />
        </Source>
        <Source id="pow" type="geojson" data={powFC}>
          <Layer
            id="pow-fill"
            type="fill"
            paint={{
              'fill-color': ['get', 'fill'],
              'fill-opacity': target.level >= 1 && p.powReady ? 1 : 0,
              'fill-opacity-transition': FADE,
            }}
          />
          <Layer
            id="pow-line"
            type="line"
            paint={{
              'line-color': ['case', ['==', ['get', 'on'], 1], '#0A0A0A', WHITE],
              'line-width': ['case', ['==', ['get', 'on'], 1], 1.4, 0.7],
              'line-opacity': target.level >= 1 ? 1 : 0,
              'line-opacity-transition': FADE,
            }}
          />
        </Source>
        <Source id="gmi" type="geojson" data={gmiFC}>
          <Layer
            id="gmi-fill"
            type="fill"
            paint={{
              'fill-color': ['get', 'fill'],
              'fill-opacity': target.level >= 2 ? 1 : 0,
              'fill-opacity-transition': FADE,
            }}
          />
          <Layer
            id="gmi-line"
            type="line"
            paint={{
              'line-color': ['case', ['==', ['get', 'on'], 1], '#2341B9', '#A3A3A3'],
              'line-width': ['case', ['==', ['get', 'on'], 1], 1.6, 0.5],
              'line-opacity': target.level >= 2 ? 1 : 0,
              'line-opacity-transition': FADE,
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
                'circle-color': '#3056F5',
                'circle-opacity': 0.55,
                'circle-stroke-color': '#2341B9',
                'circle-stroke-width': 0.6,
              }}
            />
          </Source>
        ) : null}

        {(landed ? labels : [])
          .filter((l) => shownLabels.has(l.key))
          .map((l) => (
            <Marker
              key={l.key}
              longitude={l.at[0]}
              latitude={l.at[1]}
              anchor="center"
              style={{ pointerEvents: 'none' }}
            >
              <div className="animate-in fade-in duration-200">{l.node}</div>
            </Marker>
          ))}
        {(landed ? plan.pills : []).map(({ s, stack }) => {
          const on = s.id === target.signalId
          return (
            <Marker
              key={s.id}
              longitude={s.lon as number}
              latitude={s.lat as number}
              anchor="bottom"
              offset={[0, -stack * PILL_STEP]}
              style={{ zIndex: on ? 2 : 1 }}
            >
              <button
                type="button"
                onClick={() => p.onSelectSignal(s)}
                onMouseEnter={() => p.prefetch?.signal(s)}
                onFocus={() => p.prefetch?.signal(s)}
                aria-label={`${pillText(s)}, ${s.buyer}, po terminie`}
                aria-current={on ? 'true' : undefined}
                className={cn(
                  'animate-in fade-in rounded-pill border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap shadow-sm duration-200',
                  on
                    ? 'border-attention-text bg-attention-text text-white'
                    : 'border-attention-text bg-surface text-attention-text hover:bg-attention-text hover:text-white',
                )}
              >
                {pillText(s)}
              </button>
            </Marker>
          )
        })}
        {(landed ? plan.more : []).map((m) => (
          <Marker
            key={`more${m.key}`}
            longitude={m.lon}
            latitude={m.lat}
            anchor="bottom"
            offset={[0, -m.stack * PILL_STEP]}
            style={{ pointerEvents: 'none' }}
          >
            <span
              title={`Jeszcze ${m.n} ${umowy(m.n)} w tej gminie, pełna lista po lewej`}
              className="animate-in fade-in rounded-pill border border-border bg-surface px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-text-secondary shadow-sm duration-200"
            >
              jeszcze {m.n}
            </span>
          </Marker>
        ))}
      </MapGL>
      {idle ? null : (
        <div
          role="status"
          className="pointer-events-none absolute inset-0 grid place-items-center bg-surface text-[14px] text-text-body-muted"
        >
          Wczytujemy mapę…
        </div>
      )}
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
}
