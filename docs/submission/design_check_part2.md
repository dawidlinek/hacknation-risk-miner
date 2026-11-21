# Design check, part 2 (read-only)

Method: Playwright, Chromium 1440x900, demo login (juror; ekspert for Przeglad, Katalog, Ustawienia), nothing written. Pilot project RM-2026-002; drill-down followed app links (08/12 wojewodztwo, 12/1211 powiat, umowa 137484).
Caveat: the mockups render as unfilled templates (`{{...}}` placeholders), so comparison is of structure, copy that is static in the mockup, and tokens. Data differences ignored.
Screenshots: `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/design_check2/shots/m_<name>.png` (mockup) and `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/design_check2/shots/a_<code>.png` (app).
Checks: no em dash (U+2014) or middle dot (U+00B7) found in the rendered text of any of these screens. Wordmark "ex [ante]" correct on all. Console: no app errors; one transient "Worker failed to load" from maplibre plus ERR_NETWORK_CHANGED on first monitoring load (see D2s-Wojewodztwo).

| Mockup | Route | Verdict | Screenshots |
|---|---|---|---|
| B6-HistoriaProjektu | /projekty/RM-2026-002/historia | minor | m_B6-HistoriaProjektu.png, a_B6.png |
| B7-Dokumenty | /projekty/RM-2026-002/dokumenty | minor | m_B7-Dokumenty.png, a_B7.png |
| C1-Przeglad | /przeglad | minor | m_C1-Przeglad.png, a_C1.png |
| C2-Katalog | /katalog | major | m_C2-Katalog.png, a_C2.png |
| D2-Monitoring | /monitoring | minor | m_D2-Monitoring.png, a_D2.png |
| D2s-Wojewodztwo | /monitoring/12 | major | m_D2s-Wojewodztwo.png, a_D2s-woj.png, a_D2s-woj2.png |
| D2s-Powiat | /monitoring/12/1211 | minor | m_D2s-Powiat.png, a_D2s-pow.png |
| D2s-Inwestycja | /monitoring/12/1211/umowa/137484 | minor | m_D2s-Inwestycja.png, a_D2s-inw.png |
| D3-Historia | /historia | major | m_D3-Historia.png, a_D3.png |
| D4-Ustawienia | /ustawienia | major | m_D4-Ustawienia.png, a_D4.png |

Counts: OK 0, minor 6, major 4. Every app screen also shows a floating "mocks: 0/19" badge bottom left (frontend/src/mocks/MockPanel.tsx, mounted in app/AppShell.tsx:198). It is a dev panel visible on every screen and in every screenshot; hide it when VITE_MOCKS is none.

## Cross-cutting
1. "mocks: 0/19" dev badge on all screens (above). Fix: render MockPanel only when VITE_MOCKS != none.
2. Orange is used for ordinary list rows and many data values (every Wehikul czasu signal row on a tinted orange background, all signal days, "reguly wylapuja" pills, Powiaty counts), not only "needs attention". Dilutes the one-accent rule. Fix: neutral soft rows, keep orange for the single worst/pending item.
3. Header differs from the mockups by design (full logged-in nav plus "tryb tylko do odczytu" pill); matches README §4 logged-in mode, not a defect.

## D4-Ustawienia (major)
1. Raw internal keys and English leak into Polish UI: task names "document_facts" (twice), a row with empty label ", gemini-3.5-flash-lite (fast)", "global", "replay", "routed to upstream providers", "sovereign/strong/fast/bulk" tags. Source: frontend/src/features/settings/SettingsScreen.tsx (task label map). Fix: map every task key to a Polish label, hide empty parts.
2. Missing from mockup: the green "Tryb suwerenny" card (with today's call count) and the dark "Fragment config.yaml" block. Fix: add both right-hand cards.
3. Layout is a flat 17-row list repeating each task twice (chmura and Polska); mockup has a compact "Kto wykonuje ktore zadanie" table plus "Dostawcy". Fix: group tasks, one row per task with both locations.
4. Heading is "Ustawienia"; mockup H1 is "Modele i miejsce przetwarzania". Minor copy.

## D3-Historia (major)
1. Sentence generation is broken/garbled for many events: "Ekspert zalogowal sie rekord", "Uzytkownik anonimowy analysis.run analize analize", "document.upload dokument dokument", raw dotted action codes and "role: expert; read_only: False" key-value dumps in the before/after chip. Source: backend/riskminer/api/audit_read.py (label templates) and the audit feature in frontend/src/features/audit/. Fix: map action codes to Polish verbs, drop the object-type word duplication, format values.
2. Page is about 20 000 px tall (no pagination or "load more"). Fix: paginate or virtualise, 50 rows per page.
3. "ekspert zalogowal sie" events from demo logins dominate the log; filter out login noise by default.
4. Mockup subtitle "dziennik tylko do dopisywania, nic nie znika" is replaced by a sentence; fine. Mockup shows "tryb suwerenny" dot (README says removed): app correct.

## C2-Katalog (major)
1. Right column "Propozycje modelu" and "Wagi podobienstwa" from the mockup are moved to tabs (Propozycje AI, Wagi); the default view is a single full-width R01-R15 list. Layout and hierarchy differ. Source: frontend/src/features/catalogue/. Fix: if tabs are intended, update the mockup; otherwise restore the side column.
2. Orange "reguly wylapuja X z Y" pill on 12 of 15 risks (R01-R13 except R05, R11); README says only the poorly handled ones (R01, R02, R04, R08) carry it, and R06 shows "0 z 1". Orange loses meaning. Fix: show the pill only when recall is below a threshold.
3. "Nowe ryzyko" button from the mockup is absent (arguably correct for the juror/ekspert; confirm feature flag).
4. Version string "wersja 1.1, 21.11.2026 19:32" is not monospace (mockup uses mono). Minor.

## D2s-Wojewodztwo (major)
1. On first load the map showed no region polygons and overlapping text labels piled at the centre (a_D2s-woj.png); console had "Worker failed to load" (maplibre). After a longer wait (a_D2s-woj2.png) the map rendered correctly. Risk of a broken first impression on a slow or reloaded session. Source: frontend/src/features/monitoring/ (map component). Fix: show a skeleton until the map is idle, retry the worker, do not draw labels before polygons.
2. Left panel lacks the black "Pokaz umowy" button after the 4 key numbers (mockup has it); "Powiaty z sygnalami" list is shown before Sygnaly, matching the mockup. Source: DrillPanels.tsx.
3. Signals list is cut off at the fixed panel height with the floating toolbar overlapping its last row; "Pobierz CSV" for the region sits at DrillPanels.tsx:118 but is not visible in the first screen. Fix: make the list scroll inside its own box and keep the CSV button in the sticky header.
4. Toolbar reads "Pokaz sygnaly: 240" while the card says 265 signals (data difference, but visible; check the count source).
5. Filter bar lacks the Podsektor / Wartosc / Lata dropdowns (all monitoring screens).

## D2-Monitoring (minor)
1. Filter bar: no Podsektor, Wartosc, Lata dropdowns (only search and Zakonczone / W toku). Source: features/monitoring/. 
2. Bottom toolbar button is truncated "Pokaz sygnaly: ..." in a_D2.png until data loads.
3. Added "Wehikul czasu" panel with orange-tinted rows (README prototype note lists a date slider, so acceptable) but it pushes the page to about 1520 px; mockup is a fixed 860 px board. Region list is clipped at the toolbar at about 12 of 16 voivodeships.
4. Map, ranking, metric switch, legend and wordmark match.

## D2s-Powiat (minor)
1. No "+N d" pills on contracts and no gmina tint on the powiat map; only gmina names and borders (mockup shows pills on each late contract). Source: features/monitoring map layer.
2. Key numbers and Sygnaly list match; map sits vertically off-centre with large empty area below.

## D2s-Inwestycja (minor)
1. "Obserwuj" and "Zgloś jako przypadek" (DrillPanels.tsx:318-331) are not visible in the first screen; the explanatory note under "Otworz karte umowy" is cut off by the fixed panel height. Fix: let the panel scroll or reduce spacing so the actions are visible.
2. Plan vs overdue bar and the comparison sentence are present; the "dzis" end label sits right. The orange bar is full width (fine: attention).
3. Gmina outline and filled "+1 871 d" pill are present as in the mockup.

## B7-Dokumenty (minor)
1. Construction documents are rows with "mamy dokument" / "nie ma w paczce" (green mono for the present state) instead of the mockup's tile cards; README evidence-state label "nie ma w paczce" is used correctly. Green "mamy dokument" adds a second accent colour.
2. "Ze zrodel publicznych" list is long (about 24 rows) with unhelpful titles ("expected: qa", "expected: pfu", GUID filenames) and duplicate title/subtitle lines. Source: frontend/src/features/documents/. Fix: collapse after 8 rows; hide technical placeholders.
3. "Dodaj dokumenty" header button is absent (read-only juror; expected). Side panel shows summary stats rather than detail, as the mockup before selection.
4. Black summary card, section order and drop zone match.

## B6-HistoriaProjektu (minor)
1. Order and components match (tabs, filter pills, mono summary line, version compare, append-only footer). Row avatars AI (violet) and S (grey) are an addition; violet is the AI provenance colour, acceptable.
2. "Porownaj wersje: wybierz" select is not styled like the mockup (native chevron). Restore ("Przywroc") buttons are hidden for the juror (expected).
3. Summary line counts "decyzje ekspertow 0" etc. in mono; fine.

## C1-Przeglad (minor)
1. For this item type (data discrepancy) the source quote card with chips is absent and there is no "Wzorcowy przyklad" checkbox; mockup has both. Confirm they appear for risk-event items.
2. Kind pills: app shows 5 kinds with counts; the first active is "Rozbieznosci w danych", not the first pill. Header count "1 z 152" vs mockup "z 37" is data.
3. Right-hand "Co zmieni Twoja odpowiedz" panel, radio cards with number keys and "Zapisz i dalej" / "Pomin" match the mockup.
