import { useEffect, useRef, useState } from 'react'
import { Excavator, StillBot } from './Excavator'
import { loadJelly, prefersReducedMotion, tokenColor } from './loadJelly'

/**
 * 1.2 Raport (flag `jelly`, A2 mockup): before the project name the master jelly drives a small koparka whose arm digs.
 * The jelly takes the ink colour. Reduced motion or no WebGL: a still bot in the cab and a resting arm.
 */
export function JellyDigger() {
  const root = useRef<HTMLSpanElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [still, setStill] = useState(() => typeof window === 'undefined' || prefersReducedMotion())
  const [ink] = useState(() => (typeof window === 'undefined' ? '#3056F5' : tokenColor('--ink', '#3056F5')))

  useEffect(() => {
    if (still) return
    let dead = false
    let handle: ZgraiJellyHandle | null = null
    loadJelly().then((ok) => {
      if (dead) return
      if (!ok || !window.ZgraiJelly || !canvas.current || !root.current) {
        setStill(true)
        return
      }
      handle = window.ZgraiJelly.mountOverlay(canvas.current, root.current, {})
    })
    return () => {
      dead = true
      handle?.dispose()
    }
  }, [still])

  return (
    <span
      ref={root}
      aria-hidden="true"
      data-testid="jelly-digger"
      className="relative z-[4] hidden h-[62px] w-[96px] flex-none sm:block"
    >
      {still ? null : (
        <canvas
          ref={canvas}
          className="pointer-events-none absolute z-[3]"
          style={{ left: -12, top: -24, width: 124, height: 96 }}
        />
      )}
      <Excavator
        width={96}
        dig={!still}
        driver={
          still ? (
            <StillBot color={ink} size={22} className="absolute" style={{ left: 13, top: 8 }} />
          ) : (
            <span
              data-jelly="square"
              data-master
              data-color={ink}
              data-state="awake"
              className="absolute block"
              style={{ left: 12, top: 7, width: 24, height: 24 }}
            />
          )
        }
      />
    </span>
  )
}
