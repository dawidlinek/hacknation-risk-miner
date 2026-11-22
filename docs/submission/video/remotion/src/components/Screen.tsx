import { AbsoluteFill, Easing, Img, interpolate, OffthreadVideo, staticFile, useCurrentFrame } from 'remotion';
import manifest from '../../public/captures/manifest.json';
import { C, FONT, MONO } from '../brand';
import { FPS, sec } from '../clock';

export interface Key {
  /** Seconds from the scene start. */
  t: number;
  /** Zoom (1 = whole 1920x1080 window). */
  s?: number;
  /** Focal point inside the window, 0..1. */
  fx?: number;
  fy?: number;
  /** Stills only: page scroll in image pixels (top of the window). */
  scroll?: number;
}

export interface ScreenProps {
  shot: string;
  /** Seconds into the capture where the scene starts. */
  from?: number;
  /** Playback rate for video captures. */
  rate?: number;
  cam?: Key[];
}

type Entry = { file: string; durationSec: number; height?: number };
const shots = (manifest as { shots: Record<string, Entry> }).shots;

const W = 1920;
const H = 1080;

function camAt(cam: Key[], tSec: number): Required<Key> {
  const ks = cam.length > 0 ? cam : [{ t: 0 }];
  const full = ks.map((k) => ({ t: k.t, s: k.s ?? 1, fx: k.fx ?? 0.5, fy: k.fy ?? 0.5, scroll: k.scroll ?? 0 }));
  if (tSec <= full[0]!.t) return full[0]!;
  for (let i = 1; i < full.length; i++) {
    const a = full[i - 1]!;
    const b = full[i]!;
    if (tSec <= b.t) {
      const p = interpolate(tSec, [a.t, b.t], [0, 1], { easing: Easing.inOut(Easing.cubic) });
      return {
        t: tSec,
        s: a.s + (b.s - a.s) * p,
        fx: a.fx + (b.fx - a.fx) * p,
        fy: a.fy + (b.fy - a.fy) * p,
        scroll: a.scroll + (b.scroll - a.scroll) * p,
      };
    }
  }
  return full[full.length - 1]!;
}

const Missing: React.FC<{ name: string }> = ({ name }) => (
  <AbsoluteFill
    style={{
      background: `repeating-linear-gradient(45deg, #eee 0 30px, #ddd 30px 60px)`,
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: MONO,
      fontSize: 40,
    }}
  >
    brak nagrania: {name}
  </AbsoluteFill>
);

/** One capture (video or full-page still) under a camera: zoom toward a focal point, and scroll for stills. */
export const Screen: React.FC<ScreenProps> = ({ shot, from = 0, rate = 1, cam = [] }) => {
  const f = useCurrentFrame();
  const e = shots[shot];
  if (!e) return <Missing name={shot} />;
  const k = camAt(cam, f / FPS);
  const s = Math.max(1, k.s);
  const fx = Math.min(1 - 0.5 / s, Math.max(0.5 / s, k.fx));
  const fy = Math.min(1 - 0.5 / s, Math.max(0.5 / s, k.fy));
  const tx = W / 2 - fx * W * s;
  const ty = H / 2 - fy * H * s;
  const isVideo = e.file.endsWith('.mp4');
  const maxScroll = Math.max(0, (e.height ?? H) - H);
  const scroll = Math.min(maxScroll, Math.max(0, k.scroll));
  return (
    <AbsoluteFill style={{ overflow: 'hidden', background: C.paper }}>
      <div style={{ position: 'absolute', width: W, height: H, transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${s})`, overflow: 'hidden' }}>
        {isVideo ? (
          <OffthreadVideo src={staticFile(e.file)} trimBefore={Math.round(from * FPS)} playbackRate={rate} muted style={{ width: W, height: H }} />
        ) : (
          <Img src={staticFile(e.file)} style={{ position: 'absolute', top: -scroll, left: 0, width: W }} />
        )}
      </div>
    </AbsoluteFill>
  );
};

/** The app inside a browser window on a blue-tinted canvas, settling in when the scene starts. */
export const Framed: React.FC<{ children: React.ReactNode; scale?: number; label?: string }> = ({ children, scale = 0.86, label }) => {
  const f = useCurrentFrame();
  const settle = interpolate(f, [0, sec(0.9)], [0, 1], { extrapolateRight: 'clamp', easing: Easing.bezier(0.16, 1, 0.3, 1) });
  const bar = 44;
  const w = W * scale;
  const h = H * scale;
  return (
    <AbsoluteFill style={{ background: `radial-gradient(120% 120% at 20% 0%, ${C.blueTint} 0%, #DCE3FF 55%, #C9D3FF 100%)` }}>
      <div
        style={{
          position: 'absolute',
          left: (W - w) / 2,
          top: (H - h - bar) / 2 + 10,
          width: w,
          height: h + bar,
          borderRadius: 18,
          overflow: 'hidden',
          background: C.paper,
          boxShadow: '0 40px 90px rgba(20,34,110,.28), 0 6px 18px rgba(20,34,110,.14)',
          transform: `perspective(2200px) rotateX(${(1 - settle) * 6}deg) translateY(${(1 - settle) * 24}px)`,
        }}
      >
        <div style={{ height: bar, background: '#F3F4F7', display: 'flex', alignItems: 'center', gap: 9, padding: '0 18px', borderBottom: '1px solid #E4E6EC' }}>
          {['#FF5F57', '#FEBC2E', '#28C840'].map((c) => (
            <span key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />
          ))}
          <div style={{ marginLeft: 22, background: C.paper, borderRadius: 9, padding: '5px 18px', fontFamily: FONT, fontSize: 17, color: C.muted, border: '1px solid #E4E6EC' }}>
            exante.linek.dev{label ?? ''}
          </div>
        </div>
        <div style={{ position: 'relative', width: w, height: h, overflow: 'hidden' }}>
          <div style={{ width: W, height: H, transform: `scale(${scale})`, transformOrigin: '0 0', position: 'absolute' }}>{children}</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const shotLength = (shot: string): number => shots[shot]?.durationSec ?? 0;
