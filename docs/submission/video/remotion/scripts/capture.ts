/**
 * Records the demo video's screen captures from the live app (https://exante.linek.dev).
 * Responsibility: run each SHOTS entry (scripts/shots.ts) logged in as "Ekspert (demo)"
 * in a 1440x810 viewport at device scale 4/3, so every frame is 1920x1080. Video shots
 * are recorded in VIRTUAL time (the page clock only moves when we step it 1/60 s), so
 * the footage is exactly 60 fps whatever the machine. A drawn cursor glides to each
 * click target, since headless screenshots have no pointer.
 * Waits marked `record: false` advance the page clock without saving frames: the clip
 * jumps there, and the jump frame is listed in the manifest (`cuts`) for the editor.
 * Writes public/captures/<id>.mp4 (or .png) and merges public/captures/manifest.json.
 * Idempotency: re-running a shot overwrites its file and manifest entry. Shots marked
 * `writes` create records on live; they run once, without a warm-up pass.
 *
 *   pnpm capture                 # all shots not parked
 *   pnpm capture report sim      # just these
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { type BrowserContext, type CDPSession, chromium, type Locator, type Page } from 'playwright';
import { SHOTS, type Shot, type Step, type Target } from './shots.ts';

const ORIGIN = process.env.ORIGIN ?? 'https://exante.linek.dev';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = join(ROOT, 'public');
const VIEWPORT = { width: 1440, height: 810 };
const DSF = 4 / 3;
const OUT_FPS = 60;
const FRAME_MS = 1000 / OUT_FPS;

const log = (m: string): void => {
  process.stdout.write(`${m}\n`);
};

interface ManifestEntry {
  file: string;
  durationSec: number;
  /** Frames where a non-recorded wait made the clip jump. */
  cuts?: number[];
  /** Frames where a click landed. */
  clicks?: number[];
  height?: number;
  capturedAt: string;
}
interface Manifest {
  vars: Record<string, string>;
  shots: Record<string, ManifestEntry>;
}

function locate(page: Page, t: Target, nth = 0): Locator {
  if (typeof t === 'string') {
    const esc = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return page
      .getByRole('button', { name: t, exact: true })
      .or(page.getByRole('button', { name: new RegExp(`^${esc}`) }))
      .or(page.getByRole('link', { name: t, exact: true }))
      .or(page.getByText(t, { exact: true }))
      .nth(nth);
  }
  if ('css' in t) return page.locator(t.css).nth(nth);
  return page.getByRole(t.role, { name: t.name, exact: t.exact ?? false }).nth(nth);
}

const QUIET_MS = 500;
function quietWatcher(page: Page): (cap?: number) => Promise<void> {
  let inflight = 0;
  let last = Date.now();
  const bump = (d: number) => () => {
    inflight = Math.max(0, inflight + d);
    last = Date.now();
  };
  page.on('request', bump(1));
  page.on('requestfinished', bump(-1));
  page.on('requestfailed', bump(-1));
  return async (cap = 15_000) => {
    const start = Date.now();
    await page.waitForTimeout(120);
    while (Date.now() - start < cap) {
      if (inflight === 0 && Date.now() - last >= QUIET_MS) return;
      await page.waitForTimeout(80);
    }
  };
}

const VIRTUAL_TIME = `
(() => {
  const real = {
    raf: window.requestAnimationFrame.bind(window),
    caf: window.cancelAnimationFrame.bind(window),
    perfNow: performance.now.bind(performance),
    dateNow: Date.now,
    setTimeout: window.setTimeout.bind(window),
    clearTimeout: window.clearTimeout.bind(window),
    setInterval: window.setInterval.bind(window),
    clearInterval: window.clearInterval.bind(window),
  };
  const vt = { on: false, now: 0, perfBase: 0, dateBase: 0, raf: new Map(), timers: new Map(), seq: 1e7 };
  window.__vt = vt;
  const moved = new Map();
  performance.now = () => (vt.on ? vt.now : real.perfNow());
  Date.now = () => (vt.on ? vt.dateBase + (vt.now - vt.perfBase) : real.dateNow());
  window.requestAnimationFrame = (cb) => {
    if (!vt.on) return real.raf(cb);
    const id = ++vt.seq;
    vt.raf.set(id, cb);
    return id;
  };
  const unmove = (id) => {
    const m = moved.get(id);
    if (!m) return false;
    moved.delete(id);
    if (m.kind === 'r') real.caf(m.rid); else if (m.kind === 'i') real.clearInterval(m.rid); else real.clearTimeout(m.rid);
    return true;
  };
  window.cancelAnimationFrame = (id) => (vt.raf.delete(id) || unmove(id) ? undefined : real.caf(id));
  const addTimer = (fn, ms, args, every) => {
    const id = ++vt.seq;
    vt.timers.set(id, { at: vt.now + Math.max(0, Number(ms) || 0), fn, args, every });
    return id;
  };
  window.setTimeout = (fn, ms, ...args) =>
    vt.on ? addTimer(fn, ms, args, 0) : real.setTimeout(fn, ms, ...args);
  window.setInterval = (fn, ms, ...args) =>
    vt.on ? addTimer(fn, ms, args, Math.max(1, Number(ms) || 0)) : real.setInterval(fn, ms, ...args);
  window.clearTimeout = (id) => (vt.timers.delete(id) || unmove(id) ? undefined : real.clearTimeout(id));
  window.clearInterval = (id) => (vt.timers.delete(id) || unmove(id) ? undefined : real.clearInterval(id));
  const call = (fn, args) => {
    try {
      typeof fn === 'function' ? fn(...args) : (0, eval)(String(fn));
    } catch (e) {
      console.error(e);
    }
  };
  // Hand the page back to the real clock (for flows that break under virtual time); pending
  // virtual timers and frames move to real ones, and clear* still finds them.
  vt.pause = () => {
    if (!vt.on) return;
    vt.on = false;
    for (const [id, t] of vt.timers) {
      const wait = Math.max(0, t.at - vt.now);
      moved.set(id, t.every > 0
        ? { kind: 'i', rid: real.setInterval(() => call(t.fn, t.args), t.every) }
        : { kind: 't', rid: real.setTimeout(() => call(t.fn, t.args), wait) });
    }
    vt.timers.clear();
    for (const [id, cb] of vt.raf) moved.set(id, { kind: 'r', rid: real.raf(cb) });
    vt.raf.clear();
  };
  vt.start = () => {
    vt.perfBase = real.perfNow();
    vt.dateBase = real.dateNow();
    vt.now = vt.perfBase;
    vt.on = true;
  };
  vt.step = (ms) => {
    const target = vt.now + ms;
    for (let guard = 0; guard < 10000; guard++) {
      let next = null;
      for (const [id, t] of vt.timers) if (t.at <= target && (next === null || t.at < next[1].at)) next = [id, t];
      if (next === null) break;
      const [id, t] = next;
      vt.now = Math.max(vt.now, t.at);
      if (t.every > 0) t.at += t.every;
      else vt.timers.delete(id);
      call(t.fn, t.args);
    }
    vt.now = target;
    const due = [...vt.raf.values()];
    vt.raf.clear();
    for (const cb of due) call(cb, [vt.now]);
  };
})();
`;

/** The drawn pointer: an arrow and a click ring, positioned per frame (CSS animation would not follow the virtual clock). */
const CURSOR = `
(() => {
  if (document.getElementById('__cur')) return;
  const c = document.createElement('div');
  c.id = '__cur';
  c.style.cssText = 'position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;transform:translate(720px,520px);filter:drop-shadow(0 2px 4px rgba(0,0,0,.35))';
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2.5 L4 19 L8.6 14.8 L11.6 21.4 L14.4 20.2 L11.4 13.7 L17.6 13.4 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const r = document.createElement('div');
  r.id = '__ring';
  r.style.cssText = 'position:fixed;left:0;top:0;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #3056F5;background:rgba(48,86,245,.18);z-index:2147483646;pointer-events:none;opacity:0';
  document.documentElement.append(r, c);
  window.__curSet = (x, y) => { c.style.transform = 'translate(' + (x - 4) + 'px,' + (y - 2) + 'px)'; };
  window.__ringSet = (x, y, s, o) => { r.style.left = x + 'px'; r.style.top = y + 'px'; r.style.transform = 'scale(' + s + ')'; r.style.opacity = String(o); };
})();
`;

const ease = (t: number): number => 1 - (1 - t) ** 3;
const easeInOut = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

class Recorder {
  frames = 0;
  cuts: number[] = [];
  clicks: number[] = [];
  private cx = 720;
  private cy = 520;

  constructor(
    private readonly page: Page,
    private readonly cdp: CDPSession,
    private readonly dir: string,
    private readonly quiet: (cap?: number) => Promise<void>,
  ) {}

  async start(): Promise<void> {
    await this.page.evaluate(CURSOR);
    await this.page.evaluate(`window.__curSet(${this.cx}, ${this.cy})`);
    await this.page.evaluate('window.__vt.start()');
  }

  async frame(before?: string): Promise<void> {
    if (before) await this.page.evaluate(before);
    await this.page.evaluate(`window.__vt.step(${FRAME_MS})`);
    await this.quiet(2_000);
    const shot = (await this.cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 92 })) as { data: string };
    writeFileSync(join(this.dir, `f${String(this.frames++).padStart(6, '0')}.jpg`), Buffer.from(shot.data, 'base64'));
  }

  async advance(ms: number): Promise<void> {
    const n = Math.max(1, Math.round(ms / FRAME_MS));
    for (let i = 0; i < n; i++) await this.frame();
  }

  async moveTo(x: number, y: number, ms = 600): Promise<void> {
    const n = Math.max(1, Math.round(ms / FRAME_MS));
    const [x0, y0] = [this.cx, this.cy];
    for (let i = 1; i <= n; i++) {
      const k = easeInOut(i / n);
      await this.frame(`window.__curSet(${x0 + (x - x0) * k}, ${y0 + (y - y0) * k})`);
    }
    [this.cx, this.cy] = [x, y];
    await this.page.mouse.move(x, y);
  }

  async ripple(click?: () => Promise<void>): Promise<void> {
    this.clicks.push(this.frames);
    const n = 22;
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1);
      await this.frame(`window.__ringSet(${this.cx}, ${this.cy}, ${0.3 + ease(t) * 0.9}, ${(1 - t) * 0.9})`);
      if (i === 2 && click) await click();
    }
    await this.page.evaluate(`window.__ringSet(0,0,0,0)`);
  }

  /** Steps the page clock without saving frames (the clip jumps here). */
  async skip(ms: number): Promise<void> {
    await this.page.evaluate(`window.__vt.step(${ms})`);
    await this.page.waitForTimeout(ms);
  }

  markCut(): void {
    if (this.cuts.at(-1) !== this.frames) this.cuts.push(this.frames);
  }

  encode(out: string): number {
    if (this.frames === 0) throw new Error('no frames recorded after mark');
    execFileSync(
      join(ROOT, 'node_modules/.bin/remotion'),
      ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', String(OUT_FPS), '-i', join(this.dir, 'f%06d.jpg'),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', '-preset', 'medium', out],
      { stdio: ['ignore', 'ignore', 'inherit'] },
    );
    return this.frames / OUT_FPS;
  }
}

async function center(page: Page, loc: Locator): Promise<{ x: number; y: number }> {
  await loc.waitFor({ state: 'visible', timeout: 30_000 });
  await loc.scrollIntoViewIfNeeded();
  const b = await loc.boundingBox();
  if (b === null) throw new Error('target has no box');
  return { x: b.x + Math.min(b.width / 2, 60), y: b.y + b.height / 2 };
}

async function conditionMet(page: Page, c: { text?: string; css?: string; url?: string; gone?: string }): Promise<boolean> {
  if (c.url !== undefined && !page.url().includes(c.url)) return false;
  if (c.css !== undefined && !(await page.locator(c.css).first().isVisible().catch(() => false))) return false;
  if (c.text !== undefined && !(await page.getByText(c.text).first().isVisible().catch(() => false))) return false;
  if (c.gone !== undefined && (await page.getByText(c.gone).first().isVisible().catch(() => false))) return false;
  return true;
}

async function scrollTarget(page: Page, to: number | Target, offset = 0): Promise<number> {
  let y: number;
  if (typeof to === 'number') y = to;
  else {
    const loc = locate(page, to);
    await loc.waitFor({ state: 'attached', timeout: 30_000 });
    y = await loc.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
  }
  const max = await page.evaluate('document.documentElement.scrollHeight - innerHeight');
  return Math.max(0, Math.min(Number(max), y + offset));
}

async function runSteps(
  page: Page,
  shot: Shot,
  vars: Record<string, string>,
  makeRec?: (quiet: (cap?: number) => Promise<void>) => Recorder,
): Promise<Recorder | null> {
  const quiet = quietWatcher(page);
  let rec: Recorder | null = null;
  for (const step of shot.steps as Step[]) {
    if (step === 'mark') {
      if (makeRec) {
        rec = makeRec(quiet);
        await rec.start();
      }
    } else if ('goto' in step) {
      if (rec) throw new Error(`${shot.id}: goto after mark`);
      const path = step.goto.replace('{AN}', vars.AN ?? '{AN}');
      if (path.includes('{AN}')) throw new Error(`${shot.id}: no analysis code yet (run the "new" shot first)`);
      await page.goto(`${ORIGIN}${path}`, { waitUntil: 'load' });
      await quiet();
    } else if ('wait' in step) {
      if (rec) await rec.advance(step.wait);
      else await page.waitForTimeout(step.wait);
    } else if ('click' in step) {
      const loc = locate(page, step.click, step.nth ?? 0);
      if (rec) {
        const p = await center(page, loc);
        await rec.moveTo(p.x, p.y);
        await rec.ripple(() => page.mouse.click(p.x, p.y));
      } else {
        await loc.click({ timeout: 30_000 });
        await quiet();
      }
    } else if ('fakeClick' in step) {
      if (rec) {
        const p = await center(page, locate(page, step.fakeClick));
        await rec.moveTo(p.x, p.y);
        await rec.ripple();
      }
    } else if ('hover' in step) {
      const loc = locate(page, step.hover);
      if (rec) {
        const p = await center(page, loc);
        await rec.moveTo(p.x, p.y);
        await rec.advance(step.ms ?? 800);
      } else await loc.hover({ timeout: 30_000 });
    } else if ('upload' in step) {
      const u = step.upload;
      let buffer = readFileSync(u.file);
      if (u.appendByte) buffer = Buffer.concat([buffer, Buffer.from('\n')]);
      await page.locator(u.css).first().setInputFiles({
        name: u.name ?? u.file.split('/').pop()!,
        mimeType: u.file.endsWith('.pdf') ? 'application/pdf' : 'application/octet-stream',
        buffer,
      });
      if (rec) await rec.advance(200);
    } else if ('until' in step) {
      const cap = step.cap ?? 30_000;
      const t0 = Date.now();
      if (rec && step.record !== false) {
        while (!(await conditionMet(page, step.until)) && Date.now() - t0 < cap) await rec.frame();
      } else if (rec && step.realtime) {
        rec.markCut();
        await page.evaluate('window.__vt.pause()');
        while (!(await conditionMet(page, step.until)) && Date.now() - t0 < cap) await page.waitForTimeout(250);
        await page.waitForTimeout(800);
        await page.evaluate('window.__vt.start()');
      } else if (rec) {
        rec.markCut();
        while (!(await conditionMet(page, step.until)) && Date.now() - t0 < cap) await rec.skip(150);
        await rec.skip(300);
      } else {
        while (!(await conditionMet(page, step.until)) && Date.now() - t0 < cap) await page.waitForTimeout(250);
      }
      if (!(await conditionMet(page, step.until))) log(`  ! ${shot.id}: until ${JSON.stringify(step.until)} timed out`);
    } else if ('scroll' in step) {
      const y1 = await scrollTarget(page, step.scroll.to, step.scroll.offset ?? 0);
      if (rec && step.scroll.ms > 0) {
        const y0 = Number(await page.evaluate('window.scrollY'));
        const n = Math.max(1, Math.round(step.scroll.ms / FRAME_MS));
        for (let i = 1; i <= n; i++) await rec.frame(`window.scrollTo(0, ${y0 + (y1 - y0) * easeInOut(i / n)})`);
      } else {
        await page.evaluate(`window.scrollTo(0, ${y1})`);
        await page.waitForTimeout(300);
      }
    } else if ('saveAn' in step) {
      const m = page.url().match(/AN-\d{4}-\d{4}/);
      if (!m) throw new Error(`${shot.id}: no analysis code in ${page.url()}`);
      vars.AN = m[0];
      log(`  created analysis ${m[0]}`);
    }
  }
  return rec;
}

async function login(browser: Awaited<ReturnType<typeof chromium.launch>>, statePath: string): Promise<void> {
  const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'pl-PL' });
  const p = await ctx.newPage();
  await p.goto(`${ORIGIN}/zaloguj`);
  await p.getByRole('button', { name: 'Zaloguj się' }).first().click();
  await p.waitForURL((u) => !u.pathname.startsWith('/zaloguj'), { timeout: 30_000 });
  await ctx.storageState({ path: statePath });
  await ctx.close();
}

async function newContext(browser: Awaited<ReturnType<typeof chromium.launch>>, statePath: string): Promise<BrowserContext> {
  const ctx = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: DSF,
    locale: 'pl-PL',
    timezoneId: 'Europe/Warsaw',
    colorScheme: 'light',
    storageState: statePath,
    reducedMotion: 'no-preference',
  });
  await ctx.addInitScript(VIRTUAL_TIME);
  return ctx;
}

async function main(): Promise<void> {
  const named = process.argv.slice(2);
  const shots = named.length > 0 ? named.map((id) => {
    const s = SHOTS.find((x) => x.id === id);
    if (!s) throw new Error(`unknown shot ${id}`);
    return s;
  }) : SHOTS.filter((s) => !s.parked);

  const dir = join(PUBLIC, 'captures');
  const tmp = join(dir, '.tmp');
  await mkdir(tmp, { recursive: true });
  const manifestPath = join(dir, 'manifest.json');
  const manifest: Manifest = JSON.parse(await readFile(manifestPath, 'utf8').catch(() => '{"vars":{},"shots":{}}'));
  const save = () => writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const statePath = join(tmp, 'state.json');
  try {
    await login(browser, statePath);
    for (const shot of shots) {
      log(`> ${shot.id} (${shot.kind}${shot.writes ? ', writes to live' : ''})`);
      const t0 = Date.now();
      try {
        const ctx = await newContext(browser, statePath);
        if (!shot.writes) {
          const warm = await ctx.newPage();
          await runSteps(warm, shot, manifest.vars);
          await warm.close();
        }
        const page = await ctx.newPage();
        const frameDir = join(tmp, shot.id);
        await rm(frameDir, { recursive: true, force: true });
        await mkdir(frameDir, { recursive: true });
        const cdp = await ctx.newCDPSession(page);
        const rec = await runSteps(page, shot, manifest.vars, shot.kind === 'video' ? (q) => new Recorder(page, cdp, frameDir, q) : undefined);
        const capturedAt = new Date().toISOString();
        if (shot.kind === 'still') {
          const file = `captures/${shot.id}.png`;
          await page.evaluate('window.scrollTo(0,0)');
          await page.screenshot({ path: join(PUBLIC, file), fullPage: shot.fullPage ?? false });
          const height = Number(await page.evaluate('document.documentElement.scrollHeight')) * DSF;
          manifest.shots[shot.id] = { file, durationSec: 0, height, capturedAt };
          await ctx.close();
        } else {
          if (!rec) throw new Error('video shot needs mark');
          await ctx.close();
          const file = `captures/${shot.id}.mp4`;
          const durationSec = rec.encode(join(PUBLIC, file));
          manifest.shots[shot.id] = { file, durationSec, cuts: rec.cuts, clicks: rec.clicks, capturedAt };
          log(`  ${rec.frames} frames (${durationSec.toFixed(1)} s), cuts at ${rec.cuts.join(',') || '-'}`);
        }
        await save();
        log(`  ok in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
      } catch (e) {
        log(`  FAILED ${shot.id}: ${(e as Error).message.split('\n')[0]}`);
      }
    }
  } finally {
    await browser.close();
    await save();
  }
}

await main();
