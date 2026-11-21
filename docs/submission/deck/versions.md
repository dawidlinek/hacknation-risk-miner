# Pitch deck: versions and hand-off

Status 2026-11-21 ~21:50. The background deck agent stopped on the lead's instruction. A dedicated pitch-deck session takes over from this file.

## Versions created so far

| Version | Artifact | Style reference | State |
|---|---|---|---|
| A, product design system | https://claude.ai/artifact/RUkSbfTocR6XFtK316WQYE | `design/README.md` §1, §2, §5, `design/tokens.json` (monochrome, orange = needs attention, Geist + Geist Mono, `ex [ante]` wordmark) | draft: `deck.json` (10-slide order), `deck.css` and slide 1 (`hook`) published; slides 2 to 10 not written yet |

No other version was started. No PDF exported yet.

Local working copy of version A (scratchpad, may be cleared): `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/decks/A/project/`. The same files can be read back from the artifact (`action: "read"`, `path: "project/deck.css"` etc.).

## Style references found

| Reference | Where | What could be read |
|---|---|---|
| Rogatka | artifacts: "Rogatka Pitch" https://claude.ai/artifact/WSSymeaCun1yFHQ7BCcTnn, also "Rogatka – AI Tinkerers" https://claude.ai/artifact/WCapjHcY2KD4Nk7QbLh6nZ and "Rogatka Pitch Styles" https://claude.ai/artifact/67ntw5fn6dG5UbvWEgo4Ch | Full HTML. White paper, ink `#111`, one red `#e3322b`; Instrument Sans + IBM Plex Mono; team name top left, event top right, thin red rule from mid-top to right edge and bottom-left; huge hero word repeated 3 times (solid, outlined, red-outlined); full-red "Problem" slide with a giant word bleeding off the bottom and a 2x2 grid of items with border-top and mono numbers; a red card with stacked big numbers; rising "staircase" columns for escalation; mono page number bottom right. |
| Prawo dla Ciebie | Drive: Google Doc "Prawo dla Ciebie" (notes and slide drafts) and "Prawo dla Ciebie (Ścieżka prawa).pdf" (the deck, text only, 9.8 MB) | Text structure only: giant title word "PRAWO" with team names, footer "HackNation2025! Solvrownicy w piaskownicy" on every slide, text left + product UI mock right (chat bubbles, status card "Na żywo"), "Dwie twarze prawa" two-column split, "Standardy" slide with A A A tiles. Product palette from the live site CSS: white, red `#de3b3d`, navy `#000335`, orange `#f99c00`, font Onest, radius 6 px. The PDF visuals were not viewed (downloading needs the user's OK). |
| Jak doczłapię | Drive: "JakDoczłapie.pdf" (27.9 MB) and "JakDoczlapiePREZENTACJA.pdf" (19 MB, image-only) | Text only from the first: "PROBLEM" slide in caps, footer "Solvrownicy z Piaskownicy HackYeah 2025", and a "Skala projektu" stat wall of 9 big numbers (100%, 30+, 24, 10, 6, 5+, 3, 1, 0) each with a short caption. Colours and layout unknown without downloading the PDF. Not in artifacts or Canva. |

## Storyline (10 slides, same for every version)

`hook, problem, solution, demo, data, trust, expert, sovereign, scale, ask`. Slide 1 is both cover and hook. Each slide has Polish speaker notes in `<aside>`.

## Verified numbers (use these, not the brief's older ones)

| Claim | Value | n / basis | Source |
|---|---|---|---|
| Completed wod-kan contracts since 2021 | 11 222 | n = 11 222 | `GET /api/analytics/headline` (data 20.11.2026) |
| Late | 30,3% | n = 11 198 | headline |
| Days of delay, total | 265 tys. (264 971) | n = 3 025 late contracts | headline. The brief's 261 tys. is the older research figure. |
| Paid above contract values | 586 mln zł brutto | n = 11 112 | headline |
| ≥1 contract change | 41,6% | n = 11 222 | headline |
| Median delay when late / P90 | 58 / 190 dni | n = 3 025 | headline |
| Design-build late vs build-only | 45,3% vs 28,1% | n = 1 443 / 9 755 | headline `chips` |
| Late share by province | 23,3% kujawsko-pomorskie to 43,6% lubuskie | n per province 225 to 1 702 | `GET /api/monitoring/regions` |
| Data sources | 23 (24 kinds incl. `upload`) | | `GET /api/sources/summary` |
| BZP notices in DB | 248 642 (113 278 wod-kan copy, 134 287 roads, 1 077 live API) | | `GET /api/stats` |
| Contracts in DB (auto card per contract) | 128 051 | | `GET /api/stats` |
| Evidence rows | 860 286 | | `GET /api/stats` |
| Pilot projects linked | 22 z 22 | hand-checked | `/api/stats`, `docs/test_report_sources.md` |
| Review queue | 147 items | live | `GET /api/stats` |
| Organizer documents through the full chain | 3 z 3 golden values pass | Zagrodno, Zlawies, Grodzisko | `docs/submission/overnight_log.md` 21:14, 21:19 |
| Quotes verified on the page | 98,8% (85 z 86) | 2 documents, PDF + text input; PDF input alone 43 z 43 | `docs/impl/llm.md` §3 table |
| Red Pen quotes verified | 43 z 43 (+ 16 z 16 chip quotes) | 4 public documents | overnight_log 20:48 |
| Backtest inside P10–P90 | delay 85%, delay % of plan 88%, cost 80% | train n = 4 422 (before 2024), test n = 6 143 (cost n = 6 332) | `GET /api/analytics/backtest` |
| Cause classification, gold set | AI 80,0% (CI 73–86%) vs keyword rules 37,3%; stronger model 82,7%; EU fallback Mistral 78,0% | n = 150 | `model_eval` table, `exports/eval/*.json` |
| Contracts > 90 days past planned end, no performance notice | 3 397 (of 3 803 signals) | live 21.11.2026 | `v_monitor_signal`. Brief's 3 321 is the research figure. |
| Roads sector | `catalogue/drogi/*.yaml` pack + 134 287 roads notices | | repo, `/api/stats` |
| Report generation time | about 7 s | AN-2026-0004 | overnight_log 21:10 |

Still `[do sprawdzenia]`: the public demo URL (exante.linek.dev not created yet), team names and table number, the "ask" items (pilot scope), whether WCSS/Bielik is live for the demo (overnight log: job pending, confidential uploads currently show an honest 503 message, so the sovereignty slide should describe the routing rule, not claim a live run).

## What is left

1. Deck A: write slides 2 to 10 (content plan above; `deck.css` already has the classes: `.top`, `.wm`, `.sum`, `.stats`/`.stats4`/`.stat`, `.grid3` `.tile`, `.panel` `.item` `.dot`, `.panel-grid` `.gitem` `.ring`, `.chips` with `.mk-src/.mk-calc/.mk-case/.mk-ai`, `.lane` `.arrow` `.ink-card`, `.foot`).
2. Versions B (Rogatka style), C (Prawo dla Ciebie style), D (Jak doczłapię structure with own palette): not started.
3. Pick the recommended version (planned: A, because it matches the app the jury sees in the demo and its orange "needs attention" and mono provenance lines carry the trust story), polish, export PDF (≤10 slides) to `docs/submission/deck/`.
4. `docs/submission/deck/deck_notes.md`: 2-minute speaker notes mapped to slides (not written yet; slide 1's notes are in its `<aside>`).

Local render note: a Playwright script is at `.../scratchpad/tools/render.mjs`. Launching needs the headless shell binary `~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell` (the frontend's playwright-core 1.65.1 expects build 1255, not installed). Launch works; the full render still hung before page load and was not debugged.
