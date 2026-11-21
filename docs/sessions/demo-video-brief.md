# Session brief: demo video, max 2 min, several versions (`demo-video`)

Start a fresh session in `/home/dawid-home-pc/Desktop/hacknation-risk-miner` (shared checkout, no worktree), Opus, effort high.

## Background
ex ante is a HackNation 2026 (MFiPR "Risk Miner") submission: a source-backed case base and risk analytics for public water and sewage investments in Poland.
- **Live:** https://exante.linek.dev (Coolify on the user's server).
- **Deadlines:** submission is due Sunday 10:45 in HackTribe and needs a demo video at an open link. There is a live organizer test at 11:00.
- **Pitch deck:** final, style D "Jak doczłapię" (blue #3056F5), in `docs/submission/deck/ex-ante-pitch.pdf`.
- **Team:** "Solvro Dawid", one member, Dawid Linek.
- **Repo:** shared by several sessions. Only the lead session (`local_82c8f33d-4c6d-4615-a1aa-86c2488b1828`) commits, with no AI attribution.
- **Language:** code and docs in English; UI copy and captions in Polish.

## Task
Prepare the demo/walkthrough video, **at most 2 minutes**, in **several versions** the user can pick from. The user's request:

> skup się na przygotowaniu max 2 min filmiku z demo/walkthrough. możesz przygotować kilka wersji, i potem wybiorę końcową

### 1. Start
1. Load the `product-promo-video` skill and follow it: Remotion, real screen captures of the live app at 60 fps, frame-by-frame QA.
2. Read `docs/submission/video_script.md`, `docs/submission/deck/deck_notes.md`, `docs/submission/description.md`, `README.md` and `docs/submission/test_1100_runbook.md`.

### 2. The app
- **Login:** one click, "Zaloguj się" on /zaloguj, which logs in "Ekspert (demo)".
- **Look:**
  - blue #3056F5 as the main colour, yellow #FFD23F for "wymaga uwagi"
  - the `ex [ante]` wordmark with "ante" in a blue box
  - Geist font
  - jelly builder bots on /analizy/nowa
- **Path (b):**
  1. Nowa inwestycja ("Wypełnij przykładem" or upload a PFU), then Uruchom.
  2. Raport: similar cases with n, chances, budget per km.
  3. Czerwony długopis: notes with verified quotes.
  4. Symulacja, then Podział ryzyk.
  5. The PDF/DOCX pack.
- **Path (a):**
  1. Projekty, then a project card: Przebieg, Podobne przypadki, the chat, Eksportuj rekord.
  2. The graph.
  3. Dokumenty: "Co się zmieniło" after an organizer document is uploaded.
  4. Monitoring: the coloured map and the drill-down region → powiat → contract.
  5. Przegląd: the expert approves AI proposals with quotes.
  6. Katalog.
  7. Zapytaj: an agent with visible steps.
- **Numbers:** only from the live API (`/api/analytics/headline`), with n. Never invent numbers.

### 3. Versions
Make 3–4 versions, all ≤ 2:00:

| Version | Angle |
|---|---|
| A | problem-first pitch, then both jury paths |
| B | pure walkthrough: path (b) end to end, then a quick path (a) |
| C | a 60–75 s teaser |
| D | your own best idea |

- Polish on-screen captions; each version must work muted.
- Write a narration script per version, in case the user records a voiceover.

### 4. Output
Under `docs/submission/video/`:
- `ex-ante-demo-<A|B|C|D>.mp4`, each under about 50 MB. Otherwise put the render in the gitignored `data/video/` and link it.
- the Remotion sources, without `node_modules`
- `versions.md`: the length and angle of each version, your recommendation, the narration scripts, and a note on Remotion's licence (free for teams of 3 or fewer)

Send the rendered videos to the user with SendUserFile.

## Rules
- No em dashes (U+2014) or middle dots (U+00B7). Never mention Claude, Anthropic or any AI assistant. No emoji.
- **Records on the live site:** a Flow 1 capture creates analyses on live. List everything you create in `docs/submission/video/created_records.md` and tell the lead when you're done, so the demo baseline can be reset. Approve nothing except in the Przegląd shot, and record that approval.
- **Organizer files:** never upload `materials/organizer_cases/*` as-is. Use a copy with one appended byte.
- **The site may redeploy mid-work:** retry after a few minutes. Don't push to git; the lead commits.
- **RAM is tight:** one render at a time, close browsers, low Remotion concurrency.
- **Never block:** ask the user only about the final choice.
