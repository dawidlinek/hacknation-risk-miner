/**
 * Renders every cut in src/timeline.ts to ../ex-ante-demo-<id>.mp4 (1080p60), one at a time
 * with low concurrency (RAM is tight), then a 720p preview next to it in ../preview/.
 * Positional args pick cuts: `pnpm render A C`. Idempotency: overwrites the outputs.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CUTS } from '../src/timeline.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '..');
const bin = join(root, 'node_modules/.bin/remotion');
const picked = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const cuts = picked.length > 0 ? CUTS.filter((c) => picked.includes(c.id)) : CUTS;
mkdirSync(join(outDir, 'preview'), { recursive: true });

for (const cut of cuts) {
  const out = join(outDir, `ex-ante-demo-${cut.id}.mp4`);
  process.stdout.write(`> ${cut.id}: ${cut.title}\n`);
  const t0 = Date.now();
  execFileSync(bin, ['render', 'src/index.ts', cut.id, out, '--concurrency=3', '--crf=20'], { cwd: root, stdio: ['ignore', 'ignore', 'inherit'] });
  const prev = join(outDir, 'preview', `ex-ante-demo-${cut.id}-720p.mp4`);
  execFileSync(bin, ['ffmpeg', '-y', '-loglevel', 'error', '-i', out, '-vf', 'scale=1280:720', '-r', '30', '-c:v', 'libx264', '-crf', '27', '-preset', 'medium', '-pix_fmt', 'yuv420p', prev], { cwd: root, stdio: ['ignore', 'ignore', 'inherit'] });
  const mb = (p: string) => (statSync(p).size / 1e6).toFixed(1);
  process.stdout.write(`  ${out} ${mb(out)} MB, preview ${mb(prev)} MB, ${((Date.now() - t0) / 1000).toFixed(0)} s\n`);
}
