/** Brand tokens copied from the app (blue #3056F5, attention yellow #FFD23F, Geist). */
import { loadFont } from '@remotion/fonts';
import { staticFile } from 'remotion';

export const C = {
  blue: '#3056F5',
  blueDeep: '#1F3BC4',
  blueTint: '#EEF2FF',
  yellow: '#FFD23F',
  ink: '#0A0A0A',
  muted: '#5B6170',
  paper: '#FFFFFF',
  canvas: '#F4F6FB',
} as const;

export const FONT = 'Geist, system-ui, sans-serif';
export const MONO = '"Geist Mono", ui-monospace, monospace';

const faces: [string, string, number][] = [];
for (const w of [400, 500, 600, 700]) {
  faces.push(['Geist', `fonts/geist-latin-${w}-normal.woff2`, w]);
  faces.push(['Geist', `fonts/geist-latin-ext-${w}-normal.woff2`, w]);
}
faces.push(['Geist Mono', 'fonts/geist-mono-latin-500-normal.woff2', 500]);
faces.push(['Geist Mono', 'fonts/geist-mono-latin-ext-500-normal.woff2', 500]);

export const fontsReady = Promise.all(
  faces.map(([family, file, weight]) => loadFont({ family, url: staticFile(file), weight: String(weight) })),
);
