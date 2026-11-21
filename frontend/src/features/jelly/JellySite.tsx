import { useEffect, useRef, useState } from 'react'

const BOTS = [
  { color: '#2563EB', x: 34 },
  { color: '#F97316', x: 46 },
  { color: '#14B8A6', x: 58 },
  { color: '#8B5CF6', x: 70 },
]

function reducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return true
  }
}

function webglOk(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl'))
  } catch {
    return false
  }
}

/**
 * 1.1 building site (README §3, flag `jelly`): four jelly bots in hard hats sleep, wake 1,6 s after the page opens
 * or when the pointer enters the strip. three r128 and the ZgraiJelly renderer load lazily; without WebGL the strip
 * shows only the static site, under reduced motion the bots wake but nothing moves on its own.
 */
export function JellySite() {
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  // reduced motion: no WebGL loop at all, a static still frame (bots awake, pyramid finished)
  const [still] = useState(() => typeof window === 'undefined' || reducedMotion())
  useEffect(() => {
    if (still) return
    let handle: ZgraiJellyHandle | null = null
    let dead = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const wake = () => {
      root.current?.querySelectorAll<HTMLElement>('[data-jelly]').forEach((el) => {
        el.dataset.state = 'awake'
      })
      handle?.refresh()
    }
    const onEnter = () => wake()
    const el = root.current
    if (!el || !canvas.current || !webglOk()) return
    ;(async () => {
      const THREE = await import('three')
      window.THREE = THREE
      await import('./jelly-scene.js')
      if (dead || !window.ZgraiJelly || !canvas.current || !root.current) return
      handle = window.ZgraiJelly.mountOverlay(canvas.current, root.current, {})
      timer = setTimeout(wake, 1600)
    })().catch(() => {
      /* decorative: stay static */
    })
    el.addEventListener('pointerenter', onEnter)
    return () => {
      dead = true
      if (timer) clearTimeout(timer)
      el.removeEventListener('pointerenter', onEnter)
      handle?.dispose()
    }
  }, [still])
  return (
    <div
      ref={root}
      aria-hidden="true"
      className="relative mx-auto h-[120px] w-full max-w-[760px]"
      data-testid="jelly-site"
    >
      {still ? null : (
        <canvas
          ref={canvas}
          className="pointer-events-none absolute z-[3]"
          style={{
            left: -24,
            right: -24,
            top: -40,
            bottom: 0,
            width: 'calc(100% + 48px)',
            height: 'calc(100% + 40px)',
          }}
        />
      )}
      <div className="absolute right-0 bottom-[17px] left-0 h-px bg-border" />
      {/* finished pyramid 4-3-2-1 */}
      <svg
        viewBox="0 0 120 72"
        className="absolute bottom-[17px] left-[80%] h-[60px] w-[100px] -translate-x-1/2"
        aria-hidden
      >
        {[4, 3, 2, 1].map((n, row) =>
          Array.from({ length: n }, (_, k) => (
            <rect
              key={`${row}-${k}`}
              x={(4 - n) * 15 + k * 30 + 1}
              y={72 - (row + 1) * 18}
              width={28}
              height={16}
              rx={3}
              fill="var(--ink)"
            />
          )),
        )}
      </svg>
      {BOTS.map((b) =>
        still ? (
          <StillBot key={b.color} color={b.color} x={b.x} />
        ) : (
          <span
            key={b.color}
            data-jelly="square"
            data-color={b.color}
            data-state="asleep"
            data-hat="hard"
            className="absolute block size-[30px]"
            style={{ left: `${b.x}%`, bottom: 18 }}
          />
        ),
      )}
    </div>
  )
}

/** Static, awake bot with a hard hat (reduced-motion still frame; no animation). */
function StillBot({ color, x }: { color: string; x: number }) {
  return (
    <span
      className="absolute block"
      style={{ left: `${x}%`, bottom: 18, width: 30, height: 40 }}
      data-still-bot
    >
      <span className="absolute top-0 left-[3px] h-[9px] w-[24px] rounded-t-[12px] bg-[#FACC15]" />
      <span className="absolute top-[7px] left-0 h-[3px] w-[30px] rounded-pill bg-[#EAB308]" />
      <span
        className="absolute top-[10px] left-0 h-[30px] w-[30px] rounded-[9px]"
        style={{ background: color }}
      >
        <span className="absolute top-[10px] left-[8px] size-[4px] rounded-pill bg-white" />
        <span className="absolute top-[10px] right-[8px] size-[4px] rounded-pill bg-white" />
      </span>
    </span>
  )
}
