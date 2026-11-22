import { C, FONT } from '../brand';

/** The `ex [ante]` wordmark: "ex" in ink, "ante" white in a blue box. */
export const Wordmark: React.FC<{ size?: number; inverted?: boolean; boxScale?: number }> = ({
  size = 96,
  inverted = false,
  boxScale = 1,
}) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: size * 0.05, fontFamily: FONT, fontWeight: 700, fontSize: size, letterSpacing: -size * 0.03, lineHeight: 1 }}>
    <span style={{ color: inverted ? C.paper : C.ink }}>ex</span>
    <span
      style={{
        background: inverted ? C.paper : C.blue,
        color: inverted ? C.blue : C.paper,
        borderRadius: size * 0.18,
        padding: `${size * 0.08}px ${size * 0.16}px ${size * 0.12}px`,
        transform: `scale(${boxScale})`,
        display: 'inline-block',
      }}
    >
      ante
    </span>
  </div>
);
