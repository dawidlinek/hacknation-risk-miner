# ex ante demo video (Remotion)

Sources of the demo videos in `docs/submission/video/`. 1920x1080, 60 fps, Polish captions, no audio.
Every version is a list of scenes in `src/timeline.ts` (`CUTS`); a new version is a new list, not new code.
Nothing here is part of the product build.

```bash
pnpm install --ignore-workspace
pnpm exec playwright install chromium     # once
pnpm data                                 # live numbers from /api/analytics/headline -> src/data.json
pnpm capture                              # screen captures of exante.linek.dev -> public/captures/ (~25 min)
pnpm studio                               # edit and preview
pnpm render                               # ../ex-ante-demo-<A|B|C|D>.mp4 and ../preview/*-720p.mp4
pnpm render C                             # just one cut
```

## Captures

`scripts/shots.ts` is the shot list; `scripts/capture.ts` runs each shot logged in as "Ekspert (demo)" in a
1440x810 viewport at device scale 4/3 (frames are 1920x1080).

- Motion is recorded in **virtual time**: the page clock (performance.now, Date.now, requestAnimationFrame,
  timers) only moves when the recorder steps it 1/60 s, so the footage is exactly 60 fps on any machine.
  Requests complete while the clock is frozen, so data appears without the loading gaps a real visitor sees.
- Waits marked `record: false` (the AI reading a PFU, an agent answering) advance the clock without saving
  frames, so the clip jumps there. The manifest lists those frames under `cuts`; the timeline trims around them.
- A drawn cursor glides to each click target and shows a click ring (headless screenshots have no pointer).
- Shots marked `writes` change the live database (a new analysis, a document upload, one review decision).
  They run once without a warm-up pass and are listed in `../created_records.md`.
- Organizer files are never uploaded as-is: the `docs` shot appends one byte to a copy.

## Licences

- Remotion: free for individuals and companies of up to 3 people (Remotion licence); the team is one person.
- Geist and Geist Mono fonts: SIL Open Font License 1.1, copied from the app's `@fontsource` packages.
- Playwright (Apache-2.0), React (MIT), TypeScript (Apache-2.0), tsx (MIT).
