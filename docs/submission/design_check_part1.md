# Design check, part 1 (ex ante, implementation vs mockups)

Scope: Main, A1 to A6, B1, B2, B3, B4e. Chromium 1440x900, full-page screenshots, juror persona, read-only (nothing written).
Screenshots: `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/design_check/shots/<Name>-mock.png` and `<Name>-app.png` (text dumps `-mock.txt`, `-app.txt` beside them).

Method notes:
- The mockups load `./support.js`, which is not in the repo, so opened as-is they show raw `{{...}}` placeholders. I rendered them with a small stand-in runtime (`design_check/support.js` in the scratchpad: evaluates the inline `Component.renderVals()`, expands `sc-for` / `sc-if`, interpolates `{{}}`). Tables inside `<table>` (B2) did not expand because the HTML parser moves `sc-for` out of `<table>`, so the B2 table was compared against README 3 and the column spec instead.
- AN-2026-0004 has no documents, and the doc route for AN-2026-0011 returns 404 ("Ten dokument nie należy do analizy"). A3 was compared on AN-2026-0009 / doc 2076.
- Project routes take the `RM-` id (`/projekty/RM-2026-001`), not the numeric id.
- Em dash (U+2014) and middle dot (U+00B7): 0 occurrences in rendered text of all 11 app screens and in all 11 mockups. Body font is Geist everywhere. Wordmark `ex [ante]` is correct on every screen.

## Summary table

| Mockup | Route | Verdict | Screenshots (mock / app) |
|---|---|---|---|
| Main | `/` | minor | Main-mock.png / Main-app.png |
| A1-Start | `/analizy/nowa` | minor | A1-Start-mock.png / A1-Start-app.png |
| A2-Raport | `/analizy/AN-2026-0004` | minor | A2-Raport-mock.png / A2-Raport-app.png |
| A3-Dlugopis | `/analizy/AN-2026-0009/dokumenty/2076` | minor | A3-Dlugopis-mock.png / A3-Dlugopis-app.png |
| A4-Symulacja | `/analizy/AN-2026-0004/symulacja` | minor | A4-Symulacja-mock.png / A4-Symulacja-app.png |
| A5-Podzial | `/analizy/AN-2026-0004/pakiet` | minor | A5-Podzial-mock.png / A5-Podzial-app.png |
| A6-Czat | `/zapytaj` | minor | A6-Czat-mock.png / A6-Czat-app.png |
| B1-Import | `/zrodla` | minor | B1-Import-mock.png / B1-Import-app.png |
| B2-Projekty | `/projekty` | major | B2-Projekty-mock.png / B2-Projekty-app.png |
| B3-Karta | `/projekty/RM-2026-001` | minor | B3-Karta-mock.png / B3-Karta-app.png |
| B4e-Przeplyw | `/projekty/RM-2026-001/graf` | major | B4e-Przeplyw-mock.png / B4e-Przeplyw-app.png |

Counts: OK 0, minor 9, major 2. Console errors: none on any screen under normal data. One reproducible error in an error state (see "Cross-cutting").

## Cross-cutting (affects most screens)

1. Soft vs white card treatment. Mockups use soft grey (`#F6F6F6`) for stat cards and KPI tiles, and white bordered cards with a shadow for chat panels and side lists. The app does the reverse in many places: A2 question cards are white bordered (mock: soft), A4 KPI tiles are soft inside a white card (mock: white tiles in a soft panel), chat panels on Main, A2, A4, A6, B3 are soft grey panels (mock: white card, radius 22, shadow). Likely source: shared `Card`/`Panel` components in `frontend/src/components/common/` and the chat panel in `frontend/src/features/ask/ChatPanel.tsx`. Fix hint: give ChatPanel the white bordered + shadow variant, and make stat/KPI cards `bg-soft`.
2. Analysis layout order (A2 to A5): the app puts a mono meta line and actions row first, then the tabs, then the H1. Mockups put title (and meta line under it), then tabs. On A4 and A5 the app also adds an H1 where A4 has none. Source: `frontend/src/features/report/AnalysisLayout.tsx` and `features/simulation/AnalysisHeader.tsx`. Fix hint: render H1 + meta, then tabs; drop the extra H1 on A4.
3. Container width: app content is 1192 px wide (24 px gutters inside a ~1240 box), mockups 1240 px. Visible as slightly narrower content on every page. Source: `frontend/src/app/AppShell.tsx`. Fix hint: make the page container `max-w-[1240px]` content width, not including gutters.
4. Dev-only `mocks: 0/19` badge shows bottom left on every screen (`frontend/src/mocks/MockPanel.tsx`). Make sure it is hidden in the build used for the demo.
5. A "tryb tylko do odczytu" chip in the header (`frontend/src/app/AppShell.tsx:120`) is not in the mockups. Probably intentional for the juror persona, listed for completeness.
6. Error state bug: in the dev server, `SectionError` (`frontend/src/features/report/Skeletons.tsx`) threw `ReferenceError: useRouter is not defined` when a route loader returned 404 (A3 with a wrong document id). The source file does import `useRouter`, and the served module appeared to lack it, so this may be a stale Vite dev transform; verify on a production build. Result in the browser: generic "Nie udało się wczytać danych." box.

## Per-screen differences (most visible first)

### Main `/` (minor)
1. Layout: the "Do wyjaśnienia" list sits in the left column under the chat and "Źródła danych" is the right column. Mock: chat left, sources then "Do wyjaśnienia" stacked in the right aside. Source: `features/dashboard/PulpitScreen.tsx`.
2. "Do wyjaśnienia" items lack the orange ring marker (attention), and the title is one long generated sentence with no short title + description. Mock: ring marker, short title ("Kamionka: wartość KPO o 52% wyższa"), one-line description, mono ref. Fix hint: use the step-list item (pattern 5) and a short title field.
3. "Źródła danych" shows all 9 sources as tall cards with dot, description and timestamp; mock is a compact list (name left, mono count right, grey dot for not-run). Fix hint: compact rows.
4. Chat: suggestion chips above the input and no answer shown; mock has chips below with one answer preview and bars. Panel is soft grey instead of white shadowed card.
5. Summary card has the "W SKRÓCIE" eyebrow and a mono provenance line (good, extra vs mock).

### A1-Start `/analizy/nowa` (minor)
1. Jelly building site (koparka + bots) absent. It is flag-gated (`jelly: false` in `frontend/src/config/features.ts`), so it is hidden, not broken. Hero is left-aligned.
2. Mockup is centered (H1 centered, narrow 780 px composer card, chips "Rozumiemy to tak", centered black "Uruchom analizę" button). App is left-aligned full width, with a label "Opis inwestycji", a flat textarea, dashed drop zone, a "Dokument jest publiczny" checkbox and a disabled grey button. The "Rozumiemy to tak" chip block only appears after a draft, so it is not visible in the empty state (state difference, not a defect). Source: `features/analysis/NewAnalysisScreen.tsx`. Fix hint: center the hero and constrain width to about 780 px; make the composer a single rounded card with attached documents inside.

### A2-Raport `/analizy/AN-2026-0004` (minor)
1. Order and header: see cross-cutting 2; the project name has no koparka (flag).
2. Flags list "Na co uważać przed przetargiem": app items are grey cards with only teal dots; mock uses white bordered rows with status markers (teal, black check, orange ring for "needs attention"). With zero orange markers the page has no attention accent in the main column. Source: `features/report/ReportScreen.tsx`. Fix hint: use the step-list markers; orange ring for flags that need action.
3. The three question cards are white bordered (mock: soft grey) and add range labels in the middle ("8 na 10 podobnych umów"). The extra labels are fine, the surface colour differs.
4. Similar cases: app uses a soft panel with a stacked "why" bar per case (matches README pattern 8), mock is a white card with a compact list. Case titles are truncated with an ellipsis. Acceptable, listed for completeness.
5. Chat card soft grey instead of white shadowed card. Extra sections in app (group comparison, backtest note, "Ograniczenia analizy") are additions.

### A3-Dlugopis (minor)
1. Right-panel heading "Uwagi do dokumentów" is rendered at display size (about 36 px, wraps to two lines); mock is 20 px h2 with the counts on the same line. Source: `features/redpen/RedPenScreen.tsx`. Fix hint: use the h2 style.
2. Document header (file name, page pager, "tylko strony z uwagami") is a soft strip above the page, mock puts the pager in the same row as the file name inside the soft panel; the page text is sans-serif on a bordered white page (mock: serif "document" look with a clear orange highlight and numbered badge). Highlights are weak (thin underline, no orange fill).
3. Notes are soft cards; mock uses white bordered cards with the first one expanded (status, evidence chips, "Proponowany zapis", buttons "Dodaj do PPU" / "Popraw zapis"). Because the juror is read-only, the action buttons may be hidden on purpose.

### A4-Symulacja (minor)
1. Extra H1 "Symulacja: co jeśli" (mock has none); summary card is narrower (left column) than in the mock where it spans full width. Source: `features/simulation/SimulationScreen.tsx`.
2. "Co najbardziej przesuwa termin" labels are truncated ("R07 roboty dodat...", "decyzje zamawia...", a bare "R16"); mock has short labels with a risk code. Fix hint: widen the label column or use code plus short name.
3. Scenario checkboxes start unchecked, mock has all four checked (shows the multi-line chart). State difference, but the first view in the app shows a single line. Scenario rows carry "założenie eksperta, do zatwierdzenia" text (extra, fine).
4. Chat panel and KPI tiles: surface colours swapped (cross-cutting 1). "Skąd te linie" text is much longer than in the mock.

### A5-Podzial (minor)
1. Balance bar: app renders only two segments (black, grey); the orange "dolicza w ofertach" segment is not visible when the premium is small (+6 tys. zł), and the three figures are a plain list instead of three white stat tiles with markers. Source: `features/allocation/AllocationScreen.tsx`. Fix hint: three tiles under the bar, min visible width for the orange segment.
2. Recommendation control: mock marks the recommended position per risk and turns the chosen position orange when it departs from the recommendation, with an orange case-based warning row below ("Ryczałt przy nieustalonej długości..."). App shows all recommended positions in black and no warning row (data: every choice equals the recommendation, so this may be a state difference).
3. Pack list in the aside: "Źródła i cytaty" label wraps one word per line (narrow label column). The mockup's orange "3 wnioski AI czekają na przegląd" notice with an arrow is absent. Source: `AllocationScreen.tsx` pack list.
4. Footer paragraphs about expected cost and AI classification are extra text (fine).

### A6-Czat `/zapytaj` (minor)
1. App shows the empty state (composer on top with chips, "Zapisane pytania" empty), mock shows a conversation with a bottom composer, an answer with role label, bars, source chips, "Jak to policzyłem" and actions. Layout of the conversation could not be compared live without writing (asking a question creates a record), so it was not exercised. Source: `features/ask/AskScreens.tsx`, `ChatAnswer.tsx`. Fix hint: confirm the answer component shows role label, "Jak to policzyłem", n chips and "Zapisz jako rekord" as in the mock.
2. Composer is inside a soft panel with a grey send button; mock is a white pill with shadow and a black round send button. The grey (disabled) send button also appears on Main, A2 and B3 chat inputs.

### B1-Import `/zrodla` (minor)
1. Idle state vs mid-flow mock; expected. The agent transcript (tool calls, mapping table, orange question card with "Brutto / Netto / Pokaż te 7 wierszy", composer "Napisz do agenta") is not visible without an upload, which was not done.
2. Right column order is reversed: app shows "Ostatnie uruchomienia" first, then "Reguły, których agent nie obejdzie", then "Zapisane importery"; mock is rules, saved importers, runs. "Ostatnie uruchomienia" lists internal job names in English ("anchors: derive", "cru: fetch", "link_national: link"); mock uses readable source names ("BZP: kopia ogłoszeń") with a green/orange dot. Fix hint: map job names to Polish labels. Source: `features/import/ImportScreen.tsx`.
3. "Wzbogacanie" block with a disabled grey button is an addition not in the mock.

### B2-Projekty `/projekty` (major)
1. Table overflows its container: the last column "Stan" is clipped at the right edge ("6 do przegl...", "rozbie..." cut off). Source: `features/projects/ProjectsScreen.tsx`. Fix hint: reduce the Projekt column min width or let the table scroll inside the card with a visible scroll affordance.
2. The "Projekt" column is narrow so every title wraps to 4 to 6 lines and the rows are 130 to 170 px tall; the mock row is a single compact line. Fix hint: give the title column more width and clamp to 2 lines.
3. Stat cards have an extra sub-line (fine); label "Wykonane nienależycie" vs mock "Nienależycie wykonane" (copy difference, trivial). The mock table could not be rendered (see Method notes), so column order was compared to README 3 and matches (sortable headers, value, delay, cost, changes, performance, state, selection).

### B3-Karta `/projekty/RM-2026-001` (minor)
1. Header: the long project title takes two lines and pushes "Wzbogać ponownie" / "Eksportuj" to a row below (mock: buttons right of the title). Source: `features/projects/ProjectCardScreen.tsx`. Fix hint: clamp the title or put actions in a flex row with `shrink-0`.
2. Termin and Koszt cards show the figure in orange text (+77 dni, +6,6%) and the bar is dark with an orange tail; the mock uses black figures with a black/orange bar (orange only for the overrun share). Orange on a number that is merely a delay dilutes "needs attention".
3. Przebieg is wrapped in a soft panel of white items and shows only 3 steps; mock uses white bordered rows with a date and BZP link right-aligned (underlined). Dates in the app are not a mono right-aligned column with the BZP number underneath.
4. Right column is very long: "Lekcje z tej umowy" lists 9 near-duplicate "Zmiana umowy: przyczyna według modelu N-UNSPEC (Brak faktycznej przyczyny)" items with "do przeglądu" tags, and the title is the raw model label. Mock shows 3 short lessons with plain titles. Source: `features/projects/parts.tsx`. Fix hint: group repeated lessons, hide the "N-UNSPEC" label from the title.
5. Similar cases: five cases, every one with score 1,00 and "0 dni" (data). Cards include stacked bars (OK per pattern 8).

### B4e-Przeplyw `/projekty/RM-2026-001/graf` (major)
1. The third column ("Wnioski") is missing: flows run off the right edge of the diagram at about x = 920 and no conclusion nodes or header are visible, so the user cannot click a conclusion to trace its path (the point of the screen). Source: `features/graph/EvidenceFlow.tsx`. Fix hint: the SVG viewBox or container width cuts the last column; widen the viewBox or reduce the column x positions so the Wnioski nodes and labels fit.
2. The side panel is a static "Podsumowanie: 18 faktów, 7 wniosków" instead of the conclusion detail card (skąd, czego brakuje, pewność, black "Sprawdź w Przeglądzie" button). It should appear after clicking a conclusion, which is not possible while the column is missing.
3. Flows are grey and not tinted per source (mock: violet for model reading, teal for calculations, orange for attention); the "Obliczenia" source node is teal (good) but the legend shows "źródło" grey, which does not match the dark grey node of BZP. Minor.
4. Title is long and wraps to two lines (see B3).

## Top fixes
1. B4e: show the "Wnioski" column in the flow (viewBox clipping).
2. B2: fix clipped "Stan" column and over-tall rows.
3. Cross-cutting: chat panels and stat cards use the wrong surface (white shadow card vs soft grey).
4. Analysis layout: order H1, meta, tabs as in the mockups; remove the extra H1 on A4.
5. Main and B3 side lists: compact source list, short titles with the orange attention marker, group the repeated "Lekcje" items.


## Po poprawkach

| Item | Before | Po poprawkach |
|---|---|---|
| B4e Przepływ, column "Wnioski" | clipped (fixed min width 1000 in a scroll box) | fixed: SVG and label geometry follow the container width (ResizeObserver, pixel columns), Wnioski visible and clickable at 1440; no horizontal scroll |
| B2 Projekty, "Stan" clipped, tall rows | major | fixed: column sizing only (title 34%, titles clamped to 2 lines, nowrap numeric columns, narrower Stan chip); DataTable untouched |
| Chat panels (Main, A2, A4, A6, B3) | soft grey | fixed: white card, radius 22, border and shadow (ChatPanel and A4 WhatIfPanel); answers inside are soft |
| Stat cards (A2 question cards, A4 KPI tiles) | white / swapped | fixed: A2 cards soft grey; A4 chart section soft panel with white KPI tiles |
| Analysis layout A2 to A5 | meta, tabs, H1 | fixed: H1, mono meta line, tabs (AnalysisLayout owns the H1; A2 and A4 no longer render their own; A5 heading demoted to h2; A3 shows the title as a non-heading to keep its own h1) |
| Pulpit "Do wyjaśnienia" | long sentence, no marker | fixed: orange ring marker (StepDot), short Polish title per code, API sentence as clamped description |
| B3 "Lekcje z tej umowy" | 9 near-duplicates, raw N-UNSPEC | fixed: grouped row with count ("5 zdarzeń"), N-UNSPEC shown as "przyczyna nieustalona" |
| SectionError "useRouter is not defined" | error | not a source bug: Skeletons.tsx imports useRouter; stale Vite HMR transform |
| Not done | | container width 1192 vs 1240, A1 centering, A3 right-panel heading (redpen owned by another session), Pulpit sources compact list, A5 balance bar tiles, B1 right column order and job labels, B3 header actions and orange figures, mocks badge |
