import { interpolate, useCurrentFrame } from 'remotion';
import { C, FONT, MONO } from '../brand';
import { EXPO, sec } from '../clock';

export interface Cap {
  /** Seconds from the scene start. */
  from: number;
  to: number;
  text: string;
  /** Small label above the text, e.g. "Ścieżka b, 2/5". */
  kicker?: string;
  pos?: 'bl' | 'br' | 'tl' | 'tr' | 'bc';
}

/** A lower-third caption card: slides in, holds, fades out. Polish copy, readable muted. */
export const Caption: React.FC<{ cap: Cap }> = ({ cap }) => {
  const f = useCurrentFrame();
  const a = sec(cap.from);
  const b = sec(cap.to);
  if (f < a - 1 || f > b + 1) return null;
  const inn = interpolate(f, [a, a + sec(0.5)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EXPO });
  const out = interpolate(f, [b - sec(0.35), b], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const pos = cap.pos ?? 'bl';
  const top = pos.startsWith('t');
  const style: React.CSSProperties = {
    position: 'absolute',
    maxWidth: 660,
    [top ? 'top' : 'bottom']: 64,
    ...(pos === 'bc' ? { left: '50%', transform: `translateX(-50%) translateY(${(1 - inn) * 30}px)` } : {}),
    ...(pos.endsWith('l') ? { left: 72 } : {}),
    ...(pos.endsWith('r') ? { right: 72 } : {}),
    opacity: inn * out,
    transform: pos === 'bc' ? `translateX(-50%) translateY(${(1 - inn) * 30}px)` : `translateY(${(top ? -1 : 1) * (1 - inn) * 30}px)`,
    background: C.paper,
    borderRadius: 22,
    padding: '22px 30px 24px',
    boxShadow: '0 18px 50px rgba(16,24,64,.22), 0 2px 6px rgba(16,24,64,.12)',
    borderLeft: `8px solid ${C.blue}`,
    fontFamily: FONT,
  };
  return (
    <div style={style}>
      {cap.kicker ? (
        <div style={{ fontFamily: MONO, fontSize: 21, color: C.blue, letterSpacing: 1, textTransform: 'uppercase', marginBottom: 8 }}>{cap.kicker}</div>
      ) : null}
      <div style={{ fontSize: 36, lineHeight: 1.24, fontWeight: 600, color: C.ink, letterSpacing: -0.5 }}>{cap.text}</div>
    </div>
  );
};

export const Captions: React.FC<{ caps?: Cap[] }> = ({ caps }) => (
  <>
    {(caps ?? []).map((c, i) => (
      <Caption key={i} cap={c} />
    ))}
  </>
);
