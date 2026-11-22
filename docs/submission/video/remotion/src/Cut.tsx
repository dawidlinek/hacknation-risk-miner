import { linearTiming, type TransitionPresentation, TransitionSeries } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { wipe } from '@remotion/transitions/wipe';
import { AbsoluteFill, Easing } from 'remotion';
import { C, MONO } from './brand';
import { sec, useIn } from './clock';
import { Captions } from './components/Caption';
import { Framed, Screen } from './components/Screen';
import * as T from './scenes/Titles';
import type { Cut, Scene, Trans } from './timeline';

const TITLES = {
  hookCompleted: T.HookCompleted,
  hookLate: T.HookLate,
  hookLateSolo: T.HookLateSolo,
  hookDays: T.HookDays,
  hookMoney: T.HookMoney,
  hookAll: T.HookAll,
  problem: T.Problem,
} as const;
export type TitleId = keyof typeof TITLES;

const StepChip: React.FC<{ text: string }> = ({ text }) => {
  const a = useIn(0.3, 0.5);
  return (
    <div style={{ position: 'absolute', top: 10, left: 40, background: C.blue, color: C.paper, fontFamily: MONO, fontSize: 22, letterSpacing: 1.5, textTransform: 'uppercase', padding: '8px 18px', borderRadius: 999, opacity: a, boxShadow: '0 8px 20px rgba(48,86,245,.3)' }}>
      {text}
    </div>
  );
};

const SceneView: React.FC<{ scene: Scene; framed: boolean }> = ({ scene, framed }) => {
  switch (scene.kind) {
    case 'title': {
      const Comp = TITLES[scene.id];
      return <Comp />;
    }
    case 'logo':
      return <T.Logo {...(scene.line ? { line: scene.line } : {})} />;
    case 'chapter':
      return <T.Chapter kicker={scene.kicker} title={scene.title} {...(scene.sub ? { sub: scene.sub } : {})} />;
    case 'question':
      return <T.Question q={scene.q} {...(scene.mark ? { mark: scene.mark } : {})} {...(scene.kicker ? { kicker: scene.kicker } : {})} />;
    case 'end':
      return <T.End {...(scene.line ? { line: scene.line } : {})} />;
    case 'screen': {
      const inner = <Screen shot={scene.shot} {...(scene.from !== undefined ? { from: scene.from } : {})} {...(scene.rate ? { rate: scene.rate } : {})} {...(scene.cam ? { cam: scene.cam } : {})} />;
      const useFrame = scene.framed ?? framed;
      return (
        <AbsoluteFill>
          {useFrame ? <Framed {...(scene.url ? { label: scene.url } : {})}>{inner}</Framed> : inner}
          {scene.chip ? <StepChip text={scene.chip} /> : null}
          <Captions {...(scene.caps ? { caps: scene.caps } : {})} />
        </AbsoluteFill>
      );
    }
  }
};

export const TRANS_SEC = 0.5;
// biome-ignore lint: presentations differ only in their props
function presentation(t: Trans): TransitionPresentation<any> {
  switch (t) {
    case 'slide':
      return slide({ direction: 'from-right' }) as TransitionPresentation<any>;
    case 'wipe':
      return wipe({ direction: 'from-left' }) as TransitionPresentation<any>;
    default:
      return fade() as TransitionPresentation<any>;
  }
}

export const CutView: React.FC<{ cut: Cut }> = ({ cut }) => (
  <AbsoluteFill style={{ background: C.paper }}>
    <TransitionSeries>
      {cut.scenes.flatMap((scene, i) => {
        const items = [];
        const t = scene.in ?? cut.trans ?? 'fade';
        if (i > 0 && t !== 'cut') {
          items.push(
            <TransitionSeries.Transition
              key={`t${i}`}
              presentation={presentation(t)}
              timing={linearTiming({ durationInFrames: sec(TRANS_SEC), easing: Easing.inOut(Easing.cubic) })}
            />,
          );
        }
        items.push(
          <TransitionSeries.Sequence key={`s${i}`} durationInFrames={sec(scene.dur)} premountFor={60}>
            <SceneView scene={scene} framed={cut.framed ?? false} />
          </TransitionSeries.Sequence>,
        );
        return items;
      })}
    </TransitionSeries>
  </AbsoluteFill>
);
