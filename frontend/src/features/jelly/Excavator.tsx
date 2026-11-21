import type { CSSProperties, ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** Arm swing of the koparka (A1, A2 mockups); off under reduced motion. */
const ARM_CSS = `@keyframes jxDig{0%,100%{transform:rotate(-8deg)}45%,62%{transform:rotate(17deg)}}
.jx-arm{transform-box:view-box;transform-origin:62px 40px;transform:rotate(-8deg)}
[data-dig="on"] .jx-arm{animation:jxDig 2.4s ease-in-out infinite}
@media (prefers-reduced-motion: reduce){[data-dig="on"] .jx-arm{animation:none}}`

/**
 * The yellow koparka from the A1 and A2 mockups (SVG in a 120x78 box, scaled by `width`). `driver` sits in the cab:
 * a `data-jelly` span for the WebGL overlay, or a still bot. Illustration colours come from the design asset.
 */
export function Excavator({ width, dig, driver }: { width: number; dig: boolean; driver?: ReactNode }) {
  const height = (width * 78) / 120
  return (
    <div
      data-exc
      data-dig={dig ? 'on' : 'off'}
      className="pointer-events-none absolute bottom-0 left-0"
      style={{ width, height }}
    >
      <style>{ARM_CSS}</style>
      {driver}
      <svg
        viewBox="0 0 120 78"
        width={width}
        height={height}
        aria-hidden="true"
        className="absolute top-0 left-0 overflow-visible"
      >
        <rect x="4" y="58" width="72" height="16" rx="8" fill="#262626" />
        {[14, 32, 50, 66].map((cx) => (
          <circle key={cx} cx={cx} cy="66" r="4.5" fill="#737373" />
        ))}
        <rect x="2" y="38" width="12" height="18" rx="4" fill="#CA8A04" />
        <rect x="8" y="36" width="66" height="22" rx="5" fill="#FACC15" />
        <rect x="8" y="51" width="66" height="4" fill="#EAB308" />
        <path
          d="M12 37 V13 Q12 9 16 9 H44 Q48 9 48 13 V37"
          stroke="#EAB308"
          strokeWidth="4"
          fill="none"
          strokeLinejoin="round"
        />
        <rect x="9" y="5" width="42" height="7" rx="3.5" fill="#FACC15" />
        <g className="jx-arm">
          <line x1="58" y1="30" x2="84" y2="18" stroke="#A3A3A3" strokeWidth="2.5" strokeLinecap="round" />
          <line x1="62" y1="40" x2="92" y2="12" stroke="#FACC15" strokeWidth="8" strokeLinecap="round" />
          <line x1="92" y1="12" x2="110" y2="42" stroke="#EAB308" strokeWidth="5.5" strokeLinecap="round" />
          <path d="M103 40 L117 43 L115 56 Q106 59 101 50 Z" fill="#525252" />
        </g>
        <circle cx="62" cy="40" r="3.5" fill="#CA8A04" />
      </svg>
    </div>
  )
}

/** Static, awake jelly (reduced-motion and no-WebGL still frame): rounded body, two eyes, optional hard hat. */
export function StillBot({
  color,
  size,
  hat = false,
  className,
  style,
}: {
  color: string
  size: number
  hat?: boolean
  className?: string
  style?: CSSProperties
}) {
  const eye = Math.max(3, Math.round(size / 8))
  return (
    <span
      className={cn('relative', className)}
      style={{ display: 'block', width: size, height: size, ...style }}
      data-still-bot
    >
      <span className="absolute inset-0" style={{ background: color, borderRadius: Math.round(size * 0.3) }}>
        <span
          className="absolute rounded-pill bg-white"
          style={{ width: eye, height: eye, top: size * 0.36, left: size * 0.27 }}
        />
        <span
          className="absolute rounded-pill bg-white"
          style={{ width: eye, height: eye, top: size * 0.36, right: size * 0.27 }}
        />
      </span>
      {hat ? (
        <>
          <span
            className="absolute bg-[#FACC15]"
            style={{
              left: size * 0.12,
              width: size * 0.76,
              top: -size * 0.3,
              height: size * 0.32,
              borderRadius: `${size * 0.4}px ${size * 0.4}px 0 0`,
            }}
          />
          <span
            className="absolute rounded-pill bg-[#EAB308]"
            style={{ left: -size * 0.04, width: size * 1.08, top: -size * 0.04, height: size * 0.1 }}
          />
        </>
      ) : null}
    </span>
  )
}
