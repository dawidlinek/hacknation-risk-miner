import { Composition, continueRender, delayRender } from 'remotion';
import { fontsReady } from './brand';
import { FPS } from './clock';
import { CutView } from './Cut';
import { CUTS, cutFrames } from './timeline';

const handle = delayRender('fonts');
fontsReady.then(() => continueRender(handle)).catch(() => continueRender(handle));

export const Root: React.FC = () => (
  <>
    {CUTS.map((cut) => (
      <Composition key={cut.id} id={cut.id} component={CutView} defaultProps={{ cut }} durationInFrames={cutFrames(cut)} fps={FPS} width={1920} height={1080} />
    ))}
  </>
);
