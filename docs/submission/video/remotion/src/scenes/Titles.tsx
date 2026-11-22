import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { C, FONT, MONO } from '../brand';
import { EXPO, sec, useIn, useSpring } from '../clock';
import { Wordmark } from '../components/Wordmark';
import data from '../data.json';

const pl = (n: number): string => Math.round(n).toLocaleString('pl-PL').replace(/ /g, ' ');
const pct = (x: number): string => `${Math.round(x * 100)}%`;
const asOf = data.dataAsOf.split('-').reverse().join('.');

const Source: React.FC<{ text: string; delay?: number; color?: string }> = ({ text, delay = 0.8, color = C.muted }) => {
  const a = useIn(delay, 0.6);
  return <div style={{ fontFamily: MONO, fontSize: 24, color, opacity: a, marginTop: 30 }}>{text}</div>;
};

/** One big live number counting up, with a line under it and its source. */
const Stat: React.FC<{ value: number; fmt: (n: number) => string; line: string; src: string; tone?: 'blue' | 'yellow' }> = ({ value, fmt, line, src, tone = 'blue' }) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [sec(0.1), sec(1.3)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EXPO });
  const a = useIn(0, 0.5);
  const b = useIn(0.45, 0.6);
  return (
    <AbsoluteFill style={{ background: C.paper, justifyContent: 'center', padding: '0 170px', fontFamily: FONT }}>
      <div style={{ fontSize: 230, fontWeight: 700, letterSpacing: -9, color: tone === 'blue' ? C.blue : C.ink, opacity: a, lineHeight: 1, position: 'relative', display: 'inline-block', alignSelf: 'flex-start' }}>
        {tone === 'yellow' ? (
          <span style={{ position: 'absolute', left: -20, right: -20, bottom: 12, height: 90, background: C.yellow, zIndex: 0, transformOrigin: 'left', transform: `scaleX(${b})` }} />
        ) : null}
        <span style={{ position: 'relative' }}>{fmt(value * p)}</span>
      </div>
      <div style={{ fontSize: 64, fontWeight: 600, color: C.ink, marginTop: 26, opacity: b, transform: `translateY(${(1 - b) * 20}px)`, letterSpacing: -1.2, maxWidth: 1500 }}>{line}</div>
      <Source text={src} delay={0.9} />
    </AbsoluteFill>
  );
};

export const HookCompleted: React.FC = () => (
  <Stat value={data.completed.value} fmt={pl} line="umów wodno-kanalizacyjnych wykonano w Polsce od 2021 roku" src={`BZP, stan danych ${asOf}`} />
);
export const HookLate: React.FC = () => (
  <Stat value={data.lateShare.value * 100} fmt={(n) => `${Math.round(n)}%`} tone="yellow" line="z nich skończyło się po terminie" src={`n = ${pl(data.lateShare.n)} umów z terminami, BZP`} />
);
export const HookLateSolo: React.FC = () => (
  <Stat value={data.lateShare.value * 100} fmt={(n) => `${Math.round(n)}%`} tone="yellow" line="umów wod-kan od 2021 r. skończyło się po terminie" src={`n = ${pl(data.lateShare.n)} umów z terminami, BZP, stan danych ${asOf}`} />
);
export const HookDays: React.FC = () => (
  <Stat value={data.delayDays.value / 1000} fmt={(n) => `${Math.round(n)} tys.`} line="dni opóźnień łącznie" src={`suma opóźnień, n = ${pl(data.delayDays.n)} umów po terminie`} />
);
export const HookMoney: React.FC = () => (
  <Stat value={data.overpaidMln.value} fmt={(n) => `${Math.round(n)} mln zł`} tone="yellow" line="zapłacono ponad wartość umów" src={`brutto, n = ${pl(data.overpaidMln.n)} umów z kwotą wykonania`} />
);

/** All four numbers on one card, for short cuts. */
export const HookAll: React.FC = () => {
  const items = [
    [pl(data.completed.value), 'umów wod-kan od 2021 r.'],
    [pct(data.lateShare.value), 'po terminie'],
    [`${Math.round(data.delayDays.value / 1000)} tys.`, 'dni opóźnień'],
    [`${data.overpaidMln.value} mln zł`, 'ponad wartość umów'],
  ] as const;
  return (
    <AbsoluteFill style={{ background: C.paper, justifyContent: 'center', padding: '0 150px', fontFamily: FONT }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '60px 90px' }}>
        {items.map(([v, l], i) => (
          <HookCell key={l} v={v} l={l} delay={i * 0.35} hi={i === 1 || i === 3} />
        ))}
      </div>
      <Source text={`Źródło: BZP, stan danych ${asOf}`} delay={1.8} />
    </AbsoluteFill>
  );
};
const HookCell: React.FC<{ v: string; l: string; delay: number; hi: boolean }> = ({ v, l, delay, hi }) => {
  const a = useIn(delay, 0.6);
  return (
    <div style={{ opacity: a, transform: `translateY(${(1 - a) * 30}px)` }}>
      <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: -6, color: hi ? C.ink : C.blue, lineHeight: 1 }}>
        <span style={{ background: hi ? `linear-gradient(transparent 58%, ${C.yellow} 58%, ${C.yellow} 92%, transparent 92%)` : 'none', padding: '0 8px' }}>{v}</span>
      </div>
      <div style={{ fontSize: 46, fontWeight: 600, color: C.ink, marginTop: 10 }}>{l}</div>
    </div>
  );
};

/** "The knowledge exists, scattered": source chips fly into one place. */
export const Problem: React.FC = () => {
  const srcs = ['BZP', 'TED', 'BIP', 'KIO', 'NIK', 'Mapa Dotacji', 'Centralny Rejestr Umów', 'aneksy i protokoły'];
  const t = useIn(0, 0.6);
  const t2 = useIn(2.2, 0.7);
  return (
    <AbsoluteFill style={{ background: C.canvas, justifyContent: 'center', alignItems: 'center', fontFamily: FONT }}>
      <div style={{ fontSize: 76, fontWeight: 700, letterSpacing: -2, color: C.ink, opacity: t, textAlign: 'center' }}>Ta wiedza już istnieje.</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, justifyContent: 'center', maxWidth: 1400, marginTop: 50 }}>
        {srcs.map((s, i) => (
          <Chip key={s} text={s} delay={0.35 + i * 0.12} />
        ))}
      </div>
      <div style={{ fontSize: 60, fontWeight: 600, letterSpacing: -1.5, color: C.blue, marginTop: 60, opacity: t2, transform: `translateY(${(1 - t2) * 20}px)` }}>
        Ale każda gmina uczy się sama.
      </div>
    </AbsoluteFill>
  );
};
const Chip: React.FC<{ text: string; delay: number }> = ({ text, delay }) => {
  const s = useSpring(delay, 14);
  return (
    <div style={{ transform: `scale(${0.6 + 0.4 * s})`, opacity: Math.min(1, s * 1.4), background: C.paper, border: '2px solid #D6DCEF', borderRadius: 999, padding: '14px 30px', fontSize: 40, fontWeight: 600, color: C.ink, boxShadow: '0 6px 18px rgba(20,34,110,.08)' }}>
      {text}
    </div>
  );
};

/** The wordmark reveal with the tagline. */
export const Logo: React.FC<{ line?: string }> = ({ line = 'Wiedza ex post, decyzje ex ante.' }) => {
  const s = useSpring(0.05, 13);
  const box = useSpring(0.35, 11);
  const t = useIn(0.9, 0.7);
  return (
    <AbsoluteFill style={{ background: C.paper, justifyContent: 'center', alignItems: 'center', fontFamily: FONT }}>
      <div style={{ transform: `scale(${0.85 + 0.15 * s})`, opacity: Math.min(1, s * 1.5) }}>
        <Wordmark size={180} boxScale={0.6 + 0.4 * box} />
      </div>
      <div style={{ fontSize: 54, fontWeight: 500, color: C.muted, marginTop: 50, opacity: t, letterSpacing: -0.8 }}>{line}</div>
    </AbsoluteFill>
  );
};

/** A chapter card: kicker + title on brand blue. */
export const Chapter: React.FC<{ kicker: string; title: string; sub?: string }> = ({ kicker, title, sub }) => {
  const a = useIn(0, 0.6);
  const b = useIn(0.25, 0.7);
  const c = useIn(0.6, 0.7);
  return (
    <AbsoluteFill style={{ background: C.blue, justifyContent: 'center', padding: '0 170px', fontFamily: FONT, color: C.paper }}>
      <div style={{ fontFamily: MONO, fontSize: 32, letterSpacing: 2, textTransform: 'uppercase', opacity: a * 0.85 }}>{kicker}</div>
      <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: -4, marginTop: 18, opacity: b, transform: `translateX(${(1 - b) * -40}px)`, lineHeight: 1.04 }}>{title}</div>
      {sub ? <div style={{ fontSize: 48, fontWeight: 500, marginTop: 30, opacity: c * 0.92, maxWidth: 1400, lineHeight: 1.25 }}>{sub}</div> : null}
    </AbsoluteFill>
  );
};

/** A question card (version D): ink text, yellow marker under the key words. */
export const Question: React.FC<{ q: string; mark?: string; kicker?: string }> = ({ q, mark, kicker }) => {
  const a = useIn(0, 0.6);
  const m = useIn(0.5, 0.6);
  const parts = mark && q.includes(mark) ? q.split(mark) : [q];
  return (
    <AbsoluteFill style={{ background: C.paper, justifyContent: 'center', padding: '0 170px', fontFamily: FONT }}>
      {kicker ? <div style={{ fontFamily: MONO, fontSize: 30, color: C.blue, letterSpacing: 2, textTransform: 'uppercase', opacity: a }}>{kicker}</div> : null}
      <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: -4, lineHeight: 1.08, color: C.ink, opacity: a, transform: `translateY(${(1 - a) * 24}px)`, marginTop: 20 }}>
        {parts[0]}
        {mark && parts.length > 1 ? (
          <span style={{ position: 'relative', whiteSpace: 'nowrap' }}>
            <span style={{ position: 'absolute', left: -10, right: -10, bottom: 8, height: 50, background: C.yellow, transformOrigin: 'left', transform: `scaleX(${m})` }} />
            <span style={{ position: 'relative' }}>{mark}</span>
          </span>
        ) : null}
        {parts[1] ?? ''}
      </div>
    </AbsoluteFill>
  );
};

/** Inverted end card with the live URL in a white pill. */
export const End: React.FC<{ line?: string }> = ({ line = 'Wiedza ex post, decyzje ex ante.' }) => {
  const a = useSpring(0.05, 14);
  const b = useIn(0.5, 0.7);
  const c = useIn(0.9, 0.7);
  return (
    <AbsoluteFill style={{ background: C.blue, justifyContent: 'center', alignItems: 'center', fontFamily: FONT, color: C.paper }}>
      <div style={{ transform: `scale(${0.85 + 0.15 * a})`, opacity: Math.min(1, a * 1.5) }}>
        <Wordmark size={160} inverted />
      </div>
      <div style={{ fontSize: 54, fontWeight: 500, marginTop: 44, opacity: b }}>{line}</div>
      <div style={{ marginTop: 56, background: C.paper, color: C.blue, borderRadius: 999, padding: '20px 52px', fontSize: 52, fontWeight: 700, opacity: c, transform: `translateY(${(1 - c) * 20}px)` }}>
        exante.linek.dev
      </div>
      <div style={{ fontFamily: MONO, fontSize: 26, marginTop: 48, opacity: c * 0.8 }}>HackNation 2026, wyzwanie MFiPR Risk Miner, zespół Solvro Dawid</div>
    </AbsoluteFill>
  );
};
