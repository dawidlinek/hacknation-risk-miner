# Pitch deck: versions

All four versions share the same 10 slides, the same Polish copy and the same verified numbers. Only the design
differs. Each deck is a Slides artifact: it opens in the browser, presents full screen and exports to PDF or PPTX
(Share, Export). The artifacts are private: share them from the deck's Share menu before sending the link to anyone.

**All four on one canvas:** https://claude.ai/artifact/DtZxEqZY6EmXAcfZ6Wf9RB (one row of 10 slides per version, for
side-by-side comparison; the decks below stay the editable, presentable and exportable copies).

| Version | Link | Look | PDF |
|---|---|---|---|
| A, product design system | https://claude.ai/artifact/RUkSbfTocR6XFtK316WQYE | White page, black ink, black summary cards, soft grey stat cards, one orange accent meaning "needs attention", Geist + Geist Mono, `ex [ante]` wordmark. Same language as the app (`design/README.md` §1, §2, §6). | `alternatives/ex-ante-pitch-A.pdf` |
| B, in the style of Rogatka | https://claude.ai/artifact/S8B743dxr4VVrspdzZaPKw | Rogatka's system: white paper, ink `#111`, red `#e3322b`, red rules as chrome, Instrument Sans + IBM Plex Mono, cover with the name stacked three times next to a red number panel, a full-red Problem slide with the word bleeding off the bottom, numbers on black top rules. | `alternatives/ex-ante-pitch-B.pdf` |
| C, in the style of Prawo dla Ciebie | https://claude.ai/artifact/5qm8Q3utQ1dWdFxyJokXc2 | Prawo dla Ciebie's system: white page, navy `#000234`, red `#e43838` rules top right and bottom left, heavy Onest, a giant pale title word behind the cover, "Zadanie" title centred, team names right-aligned in caps, navy statement cards. | `alternatives/ex-ante-pitch-C.pdf` |
| **D, in the style of Jak doczłapię (chosen)** | https://claude.ai/artifact/BfVLCCc7921WcFRb6mPhuS | Jak doczłapię's system: solid blue `#3056f5`, white Onest type, the name stacked three times across the cover, team names in a caps row, white "paper" cards held by tape strips, one yellow accent for "needs attention". | `ex-ante-pitch.pdf` |

## Chosen version: D

The user picked D (Jak doczłapię style) on 21.11.2026: solid blue `#3056f5`, white Onest, taped paper cards,
yellow for "needs attention". The title slide is a taped collage (report screen + the 30,3% note) over the
name stacked three times; the closing slide carries the team card: **Solvro Dawid, Dawid Linek**, exante.linek.dev,
the repo. `ex-ante-pitch.pdf` is D. A, B and C stay as alternatives.

The screens were recaptured at 1280x800 from https://exante.linek.dev (the local API was down) and are shown
whole, never cropped. Path b comes from analysis AN-2026-0009 on the live site.

## Style references

- **Rogatka**: found in artifacts ("Rogatka Pitch", "Rogatka Pitch Styles", "Rogatka, AI Tinkerers"). Version B
  follows it.
- **Prawo dla Ciebie**: "Prawo dla Ciebie (Ścieżka prawa).pdf" in Google Drive, viewed page by page in Drive's own
  viewer (nothing downloaded). Version C follows it; colours sampled from the rendered pages.
- **Jak doczłapię**: "JakDoczlapiePREZENTACJA.pdf" in Google Drive, viewed the same way. Version D follows it.
- An earlier draft of C ("Akta", serif report) and D ("Radar", dark) remains in each artifact's version history.

## Storyline (all versions)

1 Hook (national numbers), 2 Problem (six scattered sources), 3 Rozwiązanie (three points + Pulpit screen),
4 Ścieżka b, kroki 1 i 2 (Nowa inwestycja and Raport screens), 5 Ścieżka b, kroki 3 do 5 (Czerwony długopis,
Symulacja, Podział ryzyk i pakiet), 6 Ścieżka a (Projekty, karta Steklin, graf powiązań + 23 / 249 tys. / 128 tys. /
3 z 3), 7 Zaufanie (98,8%, 43 z 43, 80–88%, 80% vs 37%), 8 Kontrola eksperta i suwerenność (Przegląd and Ustawienia
screens), 9 Skala (Monitoring map, 3 397, roads), 10 Prośba i zespół.

All screens are real captures of the live app at exante.linek.dev (1280x800, shown whole), path b from analysis AN-2026-0009.
Sources: `scratchpad/screens` capture script driven by the app's own demo-login personas.

## Verified numbers

Checked on 21.11.2026 against the live API and the docs. The brief's older research figures are replaced where the
live system differs.

| Claim on the slides | Value | n / basis | Source |
|---|---|---|---|
| Completed wod-kan contracts since 2021 | 11 222 | | `GET /api/analytics/headline` (data 20.11.2026) |
| Late | 30,3% | n = 11 198 | headline |
| Days of delay, total | 265 tys. (264 971) | n = 3 025 late | headline; the brief's 261 tys. is the older research figure |
| Paid above contract values | 586 mln zł gross | n = 11 112 | headline |
| Contracts changed | 41,6% | n = 11 222 | headline |
| Design-build vs build-only late | 45% vs 28% (45,3% / 28,1%) | n = 1 443 / 9 755 | headline `chips` |
| Public sources | 23 | 24 kinds minus `upload` | `GET /api/sources/summary` |
| Notices in the DB | 249 tys. (248 642) | | `GET /api/stats` |
| Pilot projects linked | 22 z 22 | | `GET /api/stats` |
| Contracts with an automatic card | 128 tys. (128 051) | | `GET /api/stats` |
| Quotes verified on the stated page | 98,8% (85 z 86) | 8 runs, a PFU and a PPU | `docs/impl/llm.md` §3 |
| Red Pen quotes verified | 43 z 43 | 4 public documents | `overnight_log.md` 20:48 |
| Backtest inside P10–P90 | 80–88% | test n = 6 143 (cost 6 332), train n = 4 422 | `GET /api/analytics/backtest` |
| Cause classification, gold set | AI 80%, keyword rules 37% | n = 150 | be-llm eval, `exports/eval/` |
| Ongoing contracts > 90 days past planned end | 3 397 | of 3 803 with a signal, 21.11.2026 | `GET /api/monitoring/signals`; the brief's 3 321 is the research figure, and the live value moves daily |
| Roads notices | 134 tys. (134 287) | | `GET /api/stats` |
| Path b report (AN-2026-0009) | 82 similar contracts, P(on time) about 34%, cost per km above 68% of contracts | n = 82 | live report screen |
| Example road analysis | n = 893, 73% on time, 0,83 mln zł/km | one analysis | `overnight_log.md` 21:27 |

Still `[do sprawdzenia]` or placeholders: team names on slide 10, and the ask
items (pilot scope) are a proposal for the team to confirm.

## How the PDF was made

`ex-ante-pitch.pdf` is a print of the deck's own slide files at 1920x1080 (10 pages, fonts from Google Fonts).
The deck's own export (Share, Export, PDF) gives the same slides and is the safer choice for the final upload.
