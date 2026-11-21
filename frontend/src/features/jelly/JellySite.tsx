import { useEffect, useRef, useState } from 'react'
import { Excavator, StillBot } from './Excavator'
import { loadJelly, prefersReducedMotion } from './loadJelly'

/** Builder bots (README §3, A1 mockup): colour and starting x in px. */
const BOTS = [
  { color: '#2563EB', x: 270 },
  { color: '#F97316', x: 340 },
  { color: '#14B8A6', x: 410 },
  { color: '#8B5CF6', x: 480 },
]
const DIGGER = '#EC4899'
const BW = 28 // block width
const BH = 17 // block height
const GAP = 3
const ROWS = [4, 3, 2, 1] // pyramid rows, bottom up
const G = 18 // ground line from the bottom
const PILE_X = 134

interface Bot {
  el: HTMLElement
  span: HTMLElement | null
  x: number
  mode: 'sleep' | 'idle' | 'toPile' | 'pick' | 'toSite' | 'place' | 'wait'
  t: number
  sp: number
  carry: HTMLElement | null
  slot?: { x: number; y: number }
  fx: number
  fy: number
  ph: number
  i: number
}

/**
 * 1.1 building site (flag `jelly`): four jelly bots in hard hats sleep, wake 1,6 s after the page opens or when the
 * pointer enters the strip, carry blocks from the pile and stack a 4-3-2-1 pyramid over a dashed outline, bounce when
 * it is done and start again; a pink jelly drives the koparka. three r128 and the ZgraiJelly renderer load lazily.
 * Reduced motion or no WebGL: a still frame (bots awake, pyramid finished), no canvas and no animation loop.
 * The loop stops while the tab is hidden or the strip is scrolled out of view.
 */
export function JellySite() {
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [still, setStill] = useState(() => typeof window === 'undefined' || prefersReducedMotion())

  useEffect(() => {
    const site = root.current
    const layer = site?.querySelector<HTMLElement>('[data-blocks]')
    if (!site || !layer) return
    const W = site.clientWidth || 732
    const H = site.clientHeight || 150
    const ink = 'var(--ink)'
    const timers: ReturnType<typeof setTimeout>[] = []
    let raf = 0
    let dead = false
    let woke = false
    let visible = !document.hidden
    let inView = true
    let handle: ZgraiJellyHandle | null = null

    const blk = (x: number, y: number, css: string) => {
      const d = document.createElement('div')
      d.style.cssText = `position:absolute;left:0;top:0;width:${BW}px;height:${BH}px;border-radius:5px;transition:opacity .45s;transform:translate(${x}px,${y}px);${css}`
      layer.appendChild(d)
      return d
    }
    const sx = W - 24 - (4 * BW + 3 * GAP)
    const slots: { x: number; y: number }[] = []
    ROWS.forEach((n, r) => {
      const off = ((4 - n) * (BW + GAP)) / 2
      for (let c = 0; c < n; c++)
        slots.push({ x: sx + off + c * (BW + GAP), y: H - G - (r + 1) * BH - r * GAP })
    })
    const pile = () =>
      [
        [0, 0],
        [1, 0],
        [2, 0],
        [0.5, 1],
        [1.5, 1],
      ].forEach(([c, r]) => {
        blk(PILE_X + c * (BW + GAP), H - G - (r + 1) * BH - r * GAP, `background:${ink}`)
      })

    if (still) {
      pile()
      for (const s of slots) blk(s.x, s.y, `background:${ink}`)
      return () => layer.replaceChildren()
    }

    for (const s of slots)
      blk(s.x, s.y, 'border:1.5px dashed var(--border);box-sizing:border-box;background:transparent')
    pile()
    const pileX = PILE_X + 3 * (BW + GAP) + 4
    const dropX = sx - 58
    const bots: Bot[] = [...site.querySelectorAll<HTMLElement>('[data-bot]')].map((el, i) => ({
      el,
      span: el.querySelector<HTMLElement>('[data-jelly]'),
      x: BOTS[i]?.x ?? 270 + i * 70,
      mode: 'sleep',
      t: 0,
      sp: 118 + i * 14,
      carry: null,
      fx: 0,
      fy: 0,
      ph: i * 1.7,
      i,
    }))
    const state = (b: Bot, s: string) => b.span?.setAttribute('data-state', s)
    let claimed = 0
    let filled = 0
    let placed: HTMLElement[] = []
    let party = 0
    const put = (b: Bot, hop: number) => {
      b.el.style.transform = `translate(${b.x}px,${-hop}px)`
      if (b.carry) b.carry.style.transform = `translate(${b.x + 13}px,${H - G - 50 - BH - hop}px)`
    }
    const reset = () => {
      for (const d of placed) d.style.opacity = '0'
      const old = placed
      placed = []
      timers.push(
        setTimeout(() => {
          for (const d of old) d.remove()
        }, 500),
      )
      claimed = 0
      filled = 0
    }

    let last = performance.now()
    const step = () => {
      raf = 0
      if (dead) return
      const now = performance.now()
      const dt = Math.max(0, Math.min(0.05, (now - last) / 1000))
      last = now
      if (party > 0) {
        party -= dt
        if (party <= 0) {
          for (const b of bots) {
            state(b, 'awake')
            if (b.mode === 'wait') b.mode = 'toPile'
          }
          reset()
        }
      }
      for (const b of bots) {
        let hop = 0
        const go = (tx: number) => {
          const d = tx - b.x
          b.x += Math.sign(d) * Math.min(Math.abs(d), b.sp * dt)
          b.ph += dt * 11
          hop = Math.abs(Math.sin(b.ph)) * 6
          return Math.abs(tx - b.x) < 0.5
        }
        if (b.mode === 'toPile') {
          if (go(pileX + (b.i % 2) * 10)) {
            if (claimed < slots.length && party <= 0) {
              b.mode = 'pick'
              b.t = 0
              state(b, 'speaking')
            } else b.mode = 'wait'
          }
        } else if (b.mode === 'pick') {
          b.t += dt
          if (b.t > 0.35) {
            b.slot = slots[claimed++]
            b.carry = blk(b.x + 13, 0, `background:${ink};z-index:2`)
            state(b, 'awake')
            b.mode = 'toSite'
          }
        } else if (b.mode === 'toSite') {
          if (go(dropX - b.i * 15)) {
            b.mode = 'place'
            b.t = 0
            b.fx = b.x + 13
            b.fy = H - G - 50 - BH
            state(b, 'speaking')
          }
        } else if (b.mode === 'place' && b.carry && b.slot) {
          b.t += dt
          const k = Math.min(1, b.t / 0.55)
          const e = k * k * (3 - 2 * k)
          const arc = Math.sin(Math.PI * k) * 34
          b.carry.style.transform = `translate(${b.fx + (b.slot.x - b.fx) * e}px,${b.fy + (b.slot.y - b.fy) * e - arc}px)`
          if (k >= 1) {
            placed.push(b.carry)
            b.carry = null
            filled++
            state(b, 'awake')
            b.mode = 'toPile'
            if (filled === slots.length) {
              party = 1.8
              for (const o of bots) state(o, 'speaking')
            }
          }
        }
        if (b.mode !== 'place') put(b, hop)
        else b.el.style.transform = `translate(${b.x}px,0)`
      }
      run()
    }
    // one frame loop, only while awake, visible and on screen
    const run = () => {
      if (!raf && !dead && woke && visible && inView) raf = requestAnimationFrame(step)
    }
    const halt = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    }

    const wake = () => {
      if (woke || dead) return
      woke = true
      const ex = site.querySelector<HTMLElement>('[data-exc]')
      if (ex) {
        ex.querySelector('[data-jelly]')?.setAttribute('data-state', 'awake')
        timers.push(setTimeout(() => ex.setAttribute('data-dig', 'on'), 500))
      }
      bots.forEach((b, i) => {
        timers.push(
          setTimeout(() => {
            state(b, 'awake')
            timers.push(
              setTimeout(() => {
                b.mode = 'toPile'
              }, 700),
            )
          }, i * 180),
        )
      })
      last = performance.now()
      run()
    }
    const onVis = () => {
      visible = !document.hidden
      if (visible) {
        last = performance.now()
        run()
      } else halt()
    }
    const io =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(([e]) => {
            inView = !!e?.isIntersecting
            if (inView) {
              last = performance.now()
              run()
            } else halt()
          })
    io?.observe(site)
    document.addEventListener('visibilitychange', onVis)
    site.addEventListener('pointerenter', wake)

    loadJelly().then((ok) => {
      if (dead) return
      if (!ok || !window.ZgraiJelly || !canvas.current) {
        setStill(true)
        return
      }
      handle = window.ZgraiJelly.mountOverlay(canvas.current, site, {})
      timers.push(setTimeout(wake, 1600))
    })

    return () => {
      dead = true
      halt()
      for (const t of timers) clearTimeout(t)
      io?.disconnect()
      document.removeEventListener('visibilitychange', onVis)
      site.removeEventListener('pointerenter', wake)
      handle?.dispose()
      layer.replaceChildren()
    }
  }, [still])

  return (
    <div
      ref={root}
      aria-hidden="true"
      className="relative mx-auto -mb-2 hidden h-[150px] w-full max-w-[760px] sm:block"
      data-testid="jelly-site"
    >
      {still ? null : (
        <canvas
          ref={canvas}
          className="pointer-events-none absolute z-[3]"
          style={{ left: -24, top: -40, width: 'calc(100% + 48px)', height: 'calc(100% + 40px)' }}
        />
      )}
      <div className="absolute right-0 bottom-[17px] left-0 h-px bg-border" />
      <div className="absolute bottom-[14px] left-0 z-[4] h-[78px] w-[120px]">
        <Excavator
          width={120}
          dig={false}
          driver={
            still ? (
              <StillBot color={DIGGER} size={26} className="absolute" style={{ left: 17, top: 11 }} />
            ) : (
              <span
                data-jelly="auto"
                data-color={DIGGER}
                data-state="asleep"
                className="absolute block"
                style={{ left: 15, top: 9, width: 30, height: 30 }}
              />
            )
          }
        />
      </div>
      <div data-blocks className="pointer-events-none absolute inset-0 z-[4]" />
      {BOTS.map((b) => (
        <div
          key={b.color}
          data-bot
          className="pointer-events-none absolute bottom-[18px] left-0 z-[5] size-[54px]"
          style={{ transform: `translate(${b.x}px,0)` }}
        >
          {still ? (
            <StillBot color={b.color} size={40} hat className="absolute bottom-0 left-[7px]" />
          ) : (
            <span
              data-jelly="auto"
              data-color={b.color}
              data-state="asleep"
              data-hat="hard"
              className="absolute top-0 left-0 block size-[54px]"
            />
          )}
        </div>
      ))}
    </div>
  )
}
