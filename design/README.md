# Risk Miner: UI design hand-off

Status: 2026-11-21 ~15:00. Direction chosen by the user: **F, the zgrai.pl style**, built from the Steklin project-card artboard of direction F. Every screen below uses it.

- **Screens and flows (clickable prototype):** https://claude.ai/artifact/Uw6gRiCAmtK7DHyrg6tKX7
- **Style exploration (A–G and F1–F3, for the record):** https://claude.ai/artifact/35XSPsu3ACZX9AiYEQraBY
- **Tokens:** [`tokens.json`](tokens.json) (light and dark). The Tailwind 4 theme is in §5.

Both canvases are private until the owner shares them from the page's Share menu.

## 1. Product name

The product is called **ex ante** (decided on 2026-11-21 in the lead session). The wordmark is always lowercase and has two parts: "ex" in plain text, "ante" in a black box (`radius 8`, white text). Each artboard keeps the `brandA`/`brandB` tweaks, now defaulting to `ex` / `ante`.
- Tagline: „Wiedza ex post, decyzje ex ante.”
- Descriptor, where one is needed: "Risk Miner dla inwestycji publicznych".

In code, keep the name in a single place (`src/config/brand.ts`: `{ name: 'ex ante', wordA: 'ex', wordB: 'ante' }`) and never hard-code it in copy.

## 2. Look in one paragraph

The look is close to monochrome:
- white page, black ink (`#0A0A0A`), light grey panels (`#F6F6F6`) with large radii (28 / 22 / 18), pill buttons, Geist for text and Geist Mono for anything a machine produced (IDs, notice numbers, dates, `n =`, provenance lines);
- one accent, orange `#EA580C`, which means only **"needs your attention"** (an item waiting for review, an unsure value, the P90 bar). It is never decoration;
- each page opens with a **black summary card** holding one plain-language sentence, then soft stat cards, then the detail;
- no gradients as decoration, no shadows except on the composer and popovers, and no emoji.

## 3. Screens → artboards

Links open the artboard on the screens canvas (append to `https://claude.ai/artifact/Uw6gRiCAmtK7DHyrg6tKX7`).

| # | Screen (route) | Artboard | Scope (PLAN §) | Notes |
|---|---|---|---|---|
| 0 | Pulpit `/` | `#artboard-Main` | §7.1, W12 | national headline (real), work tiles; "Zapytaj pamięć" chat in the centre (composer, 3 suggestion chips that swap a real answer with bars, source and n); compact source status and data discrepancies on the right |
| 1.1 | Nowa analiza `/analizy/nowa` | `#artboard-A1-Start` | §7.6 | text + files → "we understood it like this" chips (editable, unsure = dashed orange). Above the question a small building site with the zgrai.pl jelly bots in builder style: four bots wearing yellow hard hats sleep (grey, eyes closed), wake up 1,6 s after the page opens or when the pointer enters the strip, carry black blocks from a pile and stack a 4-3-2-1 pyramid over a dashed outline, bounce when it is done, then start again; a fifth (pink) jelly drives a koparka that digs at the pile. Only on this screen. With reduced motion they wake but do not move and the pyramid shows finished. Rendering: three.js r128 (MIT) and `jelly-scene.js` (ZgraiJelly overlay, from the zgrai.pl Jelly agents artifact) loaded as canvas assets (a copy of the renderer is in [`assets/jelly-scene.js`](assets/jelly-scene.js); in the app install `three@0.128.0` from npm); the hard hat is part of the 3D model (`data-hat="hard"` on a `data-jelly` span, or `hat: 'hard'` on a field bot): dome, brim and ridge squash and sway with the body and the antenna comes out of the top. This option exists only in our copy of the renderer. Blocks and the koparka are DOM/SVG over the WebGL canvas |
| 1.2 | Raport `/analizy/:id` | `#artboard-A2-Raport` | §7.6, W2, W14 | three minimal question cards (question, verbal answer, one key number, a range bar with end labels only: grey band = similar projects, white tick = median, black "Ty" marker = this project, orange tick = programme end); flags and the "Zapytaj o tę analizę" chat in the main column; similar cases (score, name, why, delay, cost) and clauses on the right. Before the project name: the black master jelly driving a small koparka with the arm digging (same assets as 1.1) |
| 1.3 | Czerwony długopis `/analizy/:id/dokumenty/:doc` | `#artboard-A3-Dlugopis` | W1 | PDF with highlighted passages, missing clauses, suggested clause |
| 1.4 | Symulacja `/analizy/:id/symulacja` | `#artboard-A4-Symulacja` | W5, W14, W15 | one chart with real axes (labelled x and y, ticks, 25% grid) and a Termin / Koszt / Konkurencja switch; every checked change draws its own line, two or more add a "Razem" line; KPIs show the change in pp; "Zapytaj: co jeśli" chat in the side panel (canned what-ifs: tender 2 months later, one offer only, prices +10%), whose answer can be shown on the chart (extra programme-end marker) or switch the metric |
| 1.5 | Podział ryzyk i pakiet `/analizy/:id/pakiet` | `#artboard-A5-Podzial` | W13, W16 | live balance bar (expected risk cost on the buyer, on the contractor, and the premium contractors add for risks they cannot control); 3-position control per risk with the recommended position marked; a case-based warning when the choice differs; compact pack checklist and export |
| 1.6 | Zapytaj pamięć `/zapytaj` | `#artboard-A6-Czat` | W12 | chat over the database; every answer shows how it was computed (SQL), its sources and n, and can be saved as a record (`Q-2026-…`) |
| 2.1 | Import i źródła `/zrodla` | `#artboard-B1-Import` | §7.2 | import agent in a sandbox (see pattern 12): tool calls on samples, column mapping under strict rules, questions, test run on 50 rows, approval, then a deterministic full import |
| 2.2 | Projekty `/projekty` | `#artboard-B2-Projekty` | §7.3 | real table: sortable headers, contract value, delay and cost as plain numbers (orange when bad), changes, performance, review state, row selection for export. Shown in public mode, so there is no "Dodaj dane"; logged-in users import from "Więcej" → Import i źródła |
| 2.3 | Karta projektu `/projekty/:id` | `#artboard-B3-Karta` | §7.3 | summary, plan vs actual, Przebieg and the "Zapytaj o ten projekt" chat in the main column; similar cases, lessons (risk events), what we don't know and identifiers on the right |
| 2.4 | Graf powiązań `/projekty/:id/graf` | `#artboard-B4e-Przeplyw` | W4, W3 | flow (Sankey) from sources (organiser set, BZP notices, model reading, calculations) through fact groups to conclusions; band width = number of facts; click a conclusion to trace its path; for a conclusion still waiting for review the side panel links to Przegląd. Chosen from five variants (swimlanes, chain, context network, matrix, proof tree), which were dropped |
| 2.5 | Dokumenty projektu `/projekty/:id/dokumenty` | `#artboard-B7-Dokumenty` | §7.3, §7.2 | the "Dokumenty (0 z 4)" tab: construction documents expected by the Katalog checklist (PFU, contract, water-law permit, acceptance protocol) with what each would confirm, a drop zone for the import agent, public-source documents with extracted fields, and a detail panel with field codes, quotes, status and provenance (source, retrieved, hash, licence) |
| 2.6 | Historia zmian projektu `/projekty/:id/historia` | `#artboard-B6-HistoriaProjektu` | §7.8 | project-scoped audit log (the summary cards were removed) with before/after, filters, version compare, restore |
| 3.1 | Przegląd `/przeglad` | `#artboard-C1-Przeglad` | §7.4, W7 | each item is a plain question the expert answers (e.g. "Dlaczego w Steklinie dopłacono 100 325,44 zł?"), not a claim to accept. Kind pills on top (Zdarzenia ryzyka 16, Powiązania 12, Rozbieżności w danych 3, Fakty z dokumentów 4, Propozycje do katalogu 2), the source quote with chips, then answer options as radio cards (the model's pick marked "propozycja modelu" with its confidence; options that reject or override ask for a reason or value), an optional "Wzorcowy przykład" checkbox and "Zapisz i dalej" / "Pomiń". The side panel "Co zmieni Twoja odpowiedź" lists, for the selected answer, each place that changes with before → after (project card, catalogue counts, reports, public view, the model). After saving: a bar with "Cofnij", and with Wzorcowy przykład a line saying what the model re-scored |
| 3.2 | Katalog wiedzy `/katalog` | `#artboard-C2-Katalog` | §7.5, W7 | no "Dodaj sektor" flow: every sector and the whole country are loaded from the start, so the catalogue is edited, never "created". R01–R15, AI proposals, subsectors, CPV, doc types, checklists, clauses, weights, versions. Risks the keyword rules handle badly on the 150-cause gold set carry an orange note in their row (R01 "reguły wyłapują 2 z 14", R02 14 z 25, R04 "fałszywe alarmy: 12 z 24", R08 17 z 22); expanding the risk explains it and links to its review items |
| 4.1 | Monitoring `/monitoring` (Polska) | `#artboard-D2-Monitoring` | W6 | list + map layout (inspired by Mieszkaniownik), fixed 860 px tall with a scrolling list so the bottom toolbar always shows: filter bar (Zakończone / W toku, search, podsektor, wartość, lata, total count); left panel ranks the 16 voivodeships (outline, count, big value); full-height map with name and value inside each region; floating bottom toolbar (metric switch Po terminie / Opóźnienie / Dopłaty, "⋯" menu with plain-language metric descriptions incl. Zmiany umów and Nienależyte wykonanie, gradient legend, "Sygnały" toggle that shows or hides contract markers on every level and says how many are in view). Click a region to drill down: breadcrumb "← Polska", 4 key numbers, "Pokaż umowy" button, ranked signals list, map zooms to the region with "+N d" pills on real contracts (172 radar contracts matched to gmina centroids) |
| 4.1a | Monitoring, województwo `/monitoring/12` | `#artboard-D2s-Wojewodztwo` | W6 | małopolskie: breadcrumb, 4 key numbers, "Powiaty z sygnałami" list, signals list with "Pobierz CSV" (all signals in the region, with BZP numbers); map zooms to the region with powiat borders tinted by signal count and dots on contracts |
| 4.1b | Monitoring, powiat `/monitoring/12/1209` | `#artboard-D2s-Powiat` | W6 | powiat myślenicki: gmina borders and names, "+N d" pills on each late contract (5 contracts in Dobczyce and Raciechowice), key numbers (signals, total value, longest delay, gminy with signals) |
| 4.1c | Monitoring, jedna inwestycja | `#artboard-D2s-Inwestycja` | W6 | one contract (Raciechowice, 2022/BZP 00195927, 10,59 mln zł, +1 060 d): plan vs overdue bar, comparison with the voivodeship, sources (result notice, 2 change notices, no completion notice), actions "Otwórz kartę umowy" (every BZP contract already has an automatic, unverified card), "Obserwuj", "Zgłoś jako przypadek" (sends it to expert review before it joins the case base); the gmina is outlined and its pill filled |

Rejected variants (1.2b similar cases, 1.4b scenario cards, 1.5b risk board, the other four graph layouts, the three earlier maps) were removed from the canvas and from `mockups/`; older artifact versions still hold them.

Earlier explorations of the same screens in F (start, project card, review) are on the style canvas, `#artboard-F-Start`, `#artboard-F-Projekt`, `#artboard-F-Przeglad`.

**Prototype.** Every artboard is clickable (Play on the canvas). The nav, tabs, buttons and case rows link between screens. These parts actually work:
- Symulacja: the metric switch and the checkboxes; each checked change adds a line.
- Podział ryzyk: the balance bar recalculates on every choice.
- Pulpit: the suggestion chips swap the chat answer.
- Podział ryzyk: the buyer / shared / contractor choice.
- Graf powiązań: click a node to see its evidence.
- Przegląd: the decisions advance the queue and show a "cofnij" toast.
- Monitoring: the date slider replays the alerts.

**Sources.** The source of every artboard (inline styles = exact values) is copied to [`mockups/`](mockups/), e.g. `mockups/B3-Karta.dc.html`. Treat it as a spec, not code to paste: rebuild it with the components in §7.

## 4. Information architecture and flows

**Top navigation**: one header on every screen, pills, active = black. It has two modes (in the mockups: `const AUTH` in each board's script):
- **Not logged in** (default `/` = Monitoring, the map): `Monitoring, Nowa inwestycja, Projekty`. Right side: "Zapytaj" pill and a black "Zaloguj się" pill. No "Więcej" menu, no count badges. The logo goes to the map.
- **Logged in** (default after login = Pulpit): `Pulpit, Monitoring (12), Nowa inwestycja, Projekty, Przegląd (37), Katalog`, then `Więcej` with `Import i źródła, Historia, Ustawienia`. Right side: "Zapytaj" pill and the account button. The logo goes to Pulpit.
- Count badges show only for work waiting on the user.
- "Zapytaj" is always on the right and opens 1.6. The "tryb suwerenny" dot was removed from the header; data location lives in Ustawienia.
- Boards with the public header: Flow 1 (1.1–1.6), 2.2 Projekty (without "Dodaj dane") and Flow 4 (4.1–4.1c). Boards with the logged-in header: Pulpit, 2.1, 2.3–2.6, 3.1, 3.2.

**Flow 1: Nowa inwestycja** (criterion 3, 25%):
1. Pulpit → "Nowa analiza".
2. Describe the investment and drop the PFU/PPU.
3. Correct the chips.
4. "Uruchom analizę" → the report (saved as record `AN-…`).
5. Red Pen, then Symulacja, then the Podział ryzyk + pakiet DOCX.

**Flow 2: Dane → pamięć** (criterion 1, 20%):
1. Import i źródła: upload the XLSX, then "Uruchom wzbogacanie".
2. The run log shows what was found and what failed.
3. Projekty → Karta projektu, with tabs Przebieg (2.3), Graf powiązań (2.4), Dokumenty (2.5) and Historia zmian (2.6). The separate timeline screen was dropped: Przebieg on the card covers it. The contractor context on the card links to Projekty filtered by contractor.

**Flow 3: Kontrola eksperta** (criterion 4, 20%; the brief requires recording expert decisions and reusing approved examples). There is no separate quality screen: the user found the Jakość tab (former 3.2b) gave them nothing to act on, so each part moved to where the decision is made:
1. Przegląd: approve, correct, reject, or mark as a model example. Marking a model example shows at once what the model re-scored.
2. Katalog wiedzy: edit the catalogue, approve AI proposals. Risks the rules recognise poorly are flagged in their row, with a link to their review items.

**Flow 4: Monitoring** (bonus):
1. Monitoring: Polska (4.1) → województwo (4.1a) → powiat (4.1b) → one investment (4.1c). The earlier map variants (dark map with pins, bubbles, tiles) were dropped.
2. The Historia and Ustawienia boards were taken off the canvas; their sources stay in `mockups/D3-Historia.dc.html` and `mockups/D4-Ustawienia.dc.html`, and the routes stay under `Więcej`.

**Header "Zapytaj" button**: on every screen, logged in or not. It opens 1.6 Zapytaj pamięć; the project card has the same chat docked in its side panel, scoped to the project.

**Who sees what (public vs login):**

| Access | Screens | Why |
|---|---|---|
| Public, no login | Monitoring 4.1–4.1c (the start page; "Obserwuj" and "Zgłoś jako przypadek" ask to log in), Nowa inwestycja 1.1–1.6 (uploaded pre-tender documents are read only by the model in Poland), Projekty 2.2 without "Dodaj dane", project cards showing **approved** events only, Zapytaj on public data (rate-limited), the methodology | All of it is built from public BZP data; publishing it is the transparency story. Unreviewed AI conclusions are never public; in public mode "do przeglądu" links become an "niezweryfikowane" label |
| Login (expert / official) | Pulpit (start page after login), Przegląd 3.1, Katalog 3.2, Import 2.1, uploads on the project card (Dokumenty 2.5), Graf "Popraw powiązanie", project Historia zmian 2.6 with restore, global Historia and Ustawienia under "Więcej" | Confidential inputs, decisions that change the data, audit trail |
| Admin | Ustawienia (providers, routing), import rules, catalogue versions | Changes how the system behaves for everyone |

## 5. Tokens and Tailwind 4 theme

Source of truth: [`tokens.json`](tokens.json). Paste this into `src/index.css` and adjust shadcn's variables to point at it:

```css
@import "tailwindcss";

:root {
  --bg: #ffffff; --surface: #ffffff; --soft: #f6f6f6; --soft-2: #f0f0f0;
  --border: #e5e5e5; --divider: #f0f0f0;
  --ink: #0a0a0a; --on-ink: #ffffff;
  --text: #0a0a0a; --text-secondary: #404040; --text-body-muted: #525252; --text-muted: #6b6b6b; --text-on-ink-muted: #a3a3a3;
  --attention: #ea580c; --attention-text: #c2410c; --attention-soft: #fff3eb;
  --success: #16a34a; --success-text: #166534; --success-soft: #dcfce7;
  --prov-source: #525252; --prov-calc: #0f766e; --prov-ai: #7c3aed; --prov-case: #2563eb;
  --prov-calc-soft: #e6f6f3; --prov-ai-soft: #f3eeff; --prov-case-soft: #eef4ff;
  --sev-high: #b91c1c; --sev-medium: #a16207; --sev-low: #525252;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --bg: #0a0a0a; --surface: #111111; --soft: #171717; --soft-2: #1f1f1f;
  --border: #2a2a2a; --divider: #1f1f1f;
  --ink: #fafafa; --on-ink: #0a0a0a;
  --text: #fafafa; --text-secondary: #d4d4d4; --text-body-muted: #bdbdbd; --text-muted: #a3a3a3; --text-on-ink-muted: #525252;
  --attention: #fb923c; --attention-text: #fdba74; --attention-soft: #2a1708;
  --success: #4ade80; --success-text: #86efac; --success-soft: #0b2615;
  --prov-source: #a3a3a3; --prov-calc: #2dd4bf; --prov-ai: #a78bfa; --prov-case: #60a5fa;
  --prov-calc-soft: #082a27; --prov-ai-soft: #1e1433; --prov-case-soft: #0d1b33;
  --sev-high: #f87171; --sev-medium: #fbbf24; --sev-low: #a3a3a3;
  color-scheme: dark;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { /* same values as [data-theme="dark"] */ } }

@theme inline {
  --color-bg: var(--bg); --color-surface: var(--surface); --color-soft: var(--soft); --color-soft-2: var(--soft-2);
  --color-border: var(--border); --color-divider: var(--divider);
  --color-ink: var(--ink); --color-on-ink: var(--on-ink);
  --color-text: var(--text); --color-text-secondary: var(--text-secondary); --color-text-body-muted: var(--text-body-muted); --color-muted: var(--text-muted);
  --color-attention: var(--attention); --color-attention-text: var(--attention-text); --color-attention-soft: var(--attention-soft);
  --color-success: var(--success); --color-success-text: var(--success-text); --color-success-soft: var(--success-soft);
  --color-prov-source: var(--prov-source); --color-prov-calc: var(--prov-calc); --color-prov-ai: var(--prov-ai); --color-prov-case: var(--prov-case);
  --color-sev-high: var(--sev-high); --color-sev-medium: var(--sev-medium); --color-sev-low: var(--sev-low);
  --font-sans: "Geist", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
  --radius-pill: 999px; --radius-panel: 28px; --radius-card: 22px; --radius-item: 18px; --radius-inner: 14px; --radius-chip: 8px;
}
@layer base {
  body { background: var(--bg); color: var(--text); font-family: var(--font-sans); font-size: 16px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
  :focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
}
```

**Type scale** (px / weight / tracking):
- display 44/600/−0.04em; h1 36/600/−0.035em; stat 28–34/600/−0.04em
- h2 20/600/−0.02em; h3 18/600/−0.015em; summary 20–24/500
- item title 15/600; body 16/1.55; small 14; caption 13; mono 12/500
- eyebrow 11/600/0.08em uppercase, only on the black card

**Layout and controls**:
- Spacing is a 4 px scale (4 6 8 10 12 14 16 18 22 24 28 36 48 72).
- Container max-width is 1240 with a 24 gutter. The two-column layout is `main` (flex 999 1 560px) plus `aside` (flex 1 1 360px), and it stacks on a phone.
- Control height is 40, primary CTA 44–48, nav pill 36, step dot 22.

**Charts** (recharts):
- Light: plan `#D4D4D4`, P50 `#A3A3A3`, P80 `#525252`, P90 / highlight `#EA580C`, grid `#F0F0F0`, axis text `#6B6B6B`.
- Similarity contribution segments: podsektor `#0A0A0A`, formuła `#7C3AED`, zakres `#0F766E`, wartość `#EA580C`, tekst `#A3A3A3`. Always show a legend; values also appear in the tooltip.
- Dark equivalents are in `tokens.json`.

## 6. Patterns (use these everywhere)

1. **Summary card.**
   - What it is: a black card (`ink` bg, radius 22) holding one sentence in plain Polish, plus a mono provenance line under it.
   - The sentence is **filled from a template with computed numbers, never written by an LLM**. Say so in the provenance line when that helps, e.g. "obliczenie na 84 umowach z BZP".
2. **Stat card.**
   - A soft card (`soft` bg, radius 22) with a label (14, muted), a value (28–34/600) and a mono provenance line (`obliczenie, n = 84`, `źródło: BZP 2024/BZP 00349631/01`).
   - Every number shows its `n`. When `n < 10`, show "za mało danych" instead of a range.
3. **Provenance.** Four roles, always as text plus a shape, never colour alone.
   | Role | Label | Marker | Colour |
   |---|---|---|---|
   | Źródło | "źródło" | grey square, r 4 | `--prov-source` |
   | Obliczenie | "obliczenie" | teal circle | `--prov-calc` |
   | Pamięć przypadków | "przypadek" | blue circle | `--prov-case` |
   | Wniosek AI | "AI" | violet square with a **dashed** outline while unreviewed | `--prov-ai` |

   Clicking any value opens its evidence (popover → source link, field code or page, retrieval date, review status).
4. **Review status.**
   | Status | Label | Marker |
   |---|---|---|
   | auto | (no label) | none |
   | proposed | "do przeglądu" | orange ring with a dot |
   | approved | "zatwierdzone" | black filled check |
   | edited | "poprawione" | blue |
   | rejected | "odrzucone" | struck-through, red text |
5. **Step list.**
   - A soft panel (radius 28) with white items (radius 18). Each item has a 22 px dot: done = black filled with a check, now / needs attention = orange ring, missing or expected = dashed grey ring.
   - Use it for the Przebieg timeline, "do zrobienia przed przetargiem" and "czego nie wiemy".
6. **Evidence quote.**
   - A white bordered card (radius 18) showing the verbatim quote with the matched span in `<mark>` (orange-soft, or violet-soft for AI), then a mono line: `PFU s. 14, pkt 2.4, cytat zgodny ze źródłem`.
   - Unverified quotes cannot be bulk-approved.
7. **Range bar** (P10–P90): track `soft`, band P10–P90 `#E5E5E5`, band P10–P80 `#A3A3A3`, median tick `ink`, plan marker an orange triangle. The labels sit under it in mono. Plain-language mode replaces the labels with "połowa umów / 8 na 10 / 9 na 10".
8. **Similarity "why" bar.** A stacked bar of feature contributions summing to the score (0–1), plus one line of "dlaczego" text. Weights live in the Katalog.
9. **Evidence states** (missing documents). Use exactly these four labels: "nie ma w paczce", "dokument nie wspomina", "brak potwierdzenia", "potwierdzono brak". Each always comes with what it limits ("Nie potwierdzimy, czego PFU nie opisywał").
10. **Plain-language toggle.** On every chart (`Switch` "Prostym językiem"): P50 → "połowa umów", P80 → "8 na 10", percentile → "tańsze niż X% umów".
11. **Records, not chat.** Every analysis, decision and import is a record with an ID (`AN-2026-0014`, `RM-2026-003`, run `#42`), visible version and export. Free text is for correcting assumptions, expert notes, the import agent and Zapytaj pamięć. Even there, every answer is saveable as a record (`Q-2026-…`) and shows its computation.
12. **Import agent in a sandbox** (2.1).
    - Uploads go to a sandbox with no network. The agent first uses cheap tools (`list_archive`, `sample_rows`, `match_schema`, `classify_docs` on samples) and never sends a whole ZIP to the model.
    - It proposes a column → field mapping. **Strict rules are enforced by code, not by the model**: NIP/REGON checksums, BZP/KPO/TED formats, net or gross on every amount, sha256 dedup, never overwrite approved data.
    - When a rule can't decide (net or gross), the agent asks with buttons.
    - It writes a versioned importer, runs it on 50 rows, shows failures (they go to Przegląd), and asks "Zatwierdź i importuj".
    - The full run is deterministic code. Documents go to the parsing queue, and the model later sees only the chunks it needs. Saved importers are reused for the next file of the same kind.
13. **Chat answers are evidence.** Each answer in 1.6 and in the project chat carries a role label (obliczenie / wniosek AI / brak danych), source chips, n, a "Jak to policzyłem" disclosure (SQL or method), and actions (save as record, open the underlying list). When data is missing it says so and names the missing source.

## 7. Component inventory → shadcn/ui

| Component | shadcn/ui base | Notes |
|---|---|---|
| `AppHeader` + `NavPills` + `MoreMenu` | `NavigationMenu` or plain links + `DropdownMenu` | active pill `bg-ink text-on-ink`; badge counts mono |
| `Wordmark` | custom | from `brand.ts` |
| `SummaryCard` | `Card` | ink background; `eyebrow`, `sentence`, `provenance` props |
| `StatCard` | `Card` | `label`, `value`, `provenance`, optional `href`, `attention` dot |
| `ProvenanceTag` | `Badge` + `Tooltip`/`Popover` | role `source/calc/case/ai`, `reviewStatus`, `evidence` |
| `EvidencePopover` | `Popover` | source link, field/page, retrieved_at, review history |
| `StepList` / `StepItem` | custom + `Collapsible` | states `done/now/missing`; used for timeline and checklists |
| `QuoteCard` | `Card` | verbatim quote with `<mark>`, verification line |
| `RangeBar` | custom (SVG/div) | P10/P50/P80/P90 + plan marker; plain-language labels |
| `SimilarityBar` | custom (div) + `Tooltip` | per-feature segments |
| `PercentileGauge` | custom | budget per km, zones P25/P75 |
| `QuestionCard` (raport) | `Card` | question, one-word answer, sentence, mini-chart, provenance |
| `CaseRow` | `Card`/link | score tile, title, why, outcome mono |
| `ChipsEditor` (extracted features) | `Badge` + `Popover` + `Input` | unsure = dashed `attention` border |
| `FileDrop` | `Input type=file` + custom | file chips with detected doc type |
| `Composer` | `Textarea` + `Button` | radius 28, shadow `composer` |
| `ReviewCard` + `DecisionBar` | `Card`, `Button`, `RadioGroup` (reason), `Kbd` | hotkeys A/E/R/G, J/K (scoped to the page, not global) |
| `ConfidenceBreakdown` | `Progress` ×3 | data quality × completeness × signal strength |
| `DataTable` (projekty, historia, katalog) | `Table` + TanStack Table | filters as pills (`ToggleGroup`), export `DropdownMenu` |
| `Tabs` (report sections) | `Tabs` | pill style |
| `RunLog` | `Table` + `Collapsible` | query, found, errors, duration, re-run |
| `RiskMatrix`, `RiskBalance` | `Table` + `RadioGroup` per row, stacked bar | buyer / shared / contractor with the recommended position marked, mechanism text, case warning; balance bar of expected cost and premium |
| `ExportMenu` | `DropdownMenu` | DOCX, PDF, CSV, JSON |
| `PdfViewer` + `Highlight` | react-pdf + absolutely positioned marks | numbered orange markers linked to the side list |
| `SCurve`, `ScenarioLines`, `Tornado`, `Histogram`, `Calibration` | recharts | palette §5; `ScenarioLines` = baseline black, one line per checked change (`chart.scenario` in tokens), "Razem" orange, end labels with the value |
| `MapRadar` | MapLibre GL + voivodeship/gmina GeoJSON | `map-heat` ramp; date slider = `Slider` |
| `CaseGraph` | react-flow (preferred) or cytoscape.js | node shape = type, border = review status, fill = provenance soft colour |
| `ProviderTable` + `SovereignBadge` | `Table`, `Select`, `Badge` | data location per provider from config, read-only in UI unless admin |
| `Toaster` | `Sonner` | "Decyzja zapisana. Cofnij" |
| `ImportAgentThread`, `ToolCallRow`, `MappingTable`, `AgentQuestion`, `ApprovalCard` | `Card`, `Table`, `Button`, `Progress`, `Collapsible` (importer code) | pattern 12; the agent streams tool calls as compact rows |
| `ChatThread`, `ChatAnswer`, `SourceChip`, `SuggestionChips` | `Card`, `Badge`, `Collapsible` (SQL), `Button` | pattern 13; also docked variant `ProjectChat` in the project card side panel |
| `ScenarioCard` + `IconArray` (20 squares) | `Card`, `RadioGroup` semantics | 1.4b; three states per square: on time, late before programme end, after programme end |
| `RiskBoard` (3 columns) + `PackPagePreview` | custom; dnd-kit optional | 1.5b; arrow buttons are the accessible fallback to drag |
| `LinkGraph` (swimlanes × time order) | react-flow with fixed lanes | 2.4; edge labels are buttons; ghost nodes for missing documents |
| `ChoroplethMap`, `RegionList`, `MapToolbar`, `MetricMenu`, `ValuePill` | MapLibre GL + `data/ref/geo/*.geojson`; list as `Card` buttons with region outline SVG | 4.1; continuous single-hue ink scale for completed-contract metrics, orange only for signals; mockup uses simplified voivodeship SVG paths |

## 8. Accessibility (WCAG 2.1 AA)

- **Contrast**: body text `#0A0A0A`, muted `#6B6B6B` (5.3:1 on white, 4.9:1 on `#F6F6F6`). Orange `#EA580C` only for non-text marks or text ≥ 24 px; small orange text uses `#C2410C` (5.2:1).
- **Never colour alone**: provenance and status always carry a text label and a shape (square / circle / dashed outline).
- **Controls**: real `<button>`, `<a>`, `<input>` and `<label>`. Icon-only buttons get an `aria-label`. Focus is a 2 px ink outline. Hit targets are ≥ 40 px.
- **Charts** carry `role="img"` with an `aria-label` sentence, and the plain-language toggle doubles as a text alternative.
- **Hotkeys** only on the review page, listed visibly, and never steal focus from inputs.
- **Motion**: the attention-ring animation stops under `prefers-reduced-motion`.

## 9. Copy rules

- Polish throughout. Short sentences, one idea per line, and the answer first ("Raczej nie.").
- **Numbers and dates**:
  - Money as `2 131 590,00 zł` (non-breaking spaces), always gross or net stated where it matters ("brutto").
  - Dates as `dd.mm.rrrr`.
  - Percentages with a comma (`+40,3%`).
  - Notice numbers in full (`2024/BZP 00349631/01`), in mono.
- Name the rule or code: `R02`, `art. 455 ust. 1 pkt 3`, `K-07`.
- Unknowns stay `[n]` or `[do uruchomienia]` placeholders; never invent figures.
- **No em dashes (U+2014) and no middle dots (U+00B7)** anywhere in UI copy, labels or titles. Use a comma, colon, period or parentheses instead; for an empty value write "brak". En dashes in ranges (2021–2026, 0,54–1,48) are fine.

## 10. Data used in the mockups

All figures are real, from `docs/research/05_bzp_corpus_stats.md`, `research/bzp_corpus/` and `docs/research/01_bzp_api.md`, unless shown as `[placeholder]`:
- **National** (05 §11):
  - 11 184 completed wod-kan works contracts (2021–2026) worth PLN 20,7 bn; 30% late, 261 000 days of delay in total, median 58 days when late, P90 188.
  - 41% had ≥1 change. 21,5% were paid above contract value: PLN 582 mln over in total, cost deviation P90 +6,9%.
  - Late share: 19% below PLN 0,5 mln vs 52% above PLN 10 mln; design-build 47% vs build-only 28%; treatment plants 39% / water treatment 40% vs water networks 24%.
  - 113 278 notices in the copy.
- **Backtest** (no screen since the Jakość tab was dropped; candidate for one line in 1.2): train before 2024, test 2024–11.2026. Inside P10–P90:
  - delay days 85%, delay % 88%, cost 80% (target 80%);
  - the late probability runs low by about 5 pp (27% predicted vs 33% observed).
- **Tender outcomes (Symulacja)**: cancelled wod-kan tenders 33% (2022) → 14% (2026); median offers 2 → 6; single offer 8,5% in 2026.
- **Map (Monitoring)**: late share of completed contracts by voivodeship, from `research/bzp_corpus/out/wow_pitch_by_province.csv`. Lowest kujawsko-pomorskie 23% and podkarpackie 24%; highest lubuskie 43% and dolnośląskie 40%.
- **Demo reference class**: kanalizacja sanitarna, 5–10 mln zł, zaprojektuj i wybuduj, n = 84.
  - 64% late; ≥1 change 77%.
  - Delay P50/P80/P90 +69/+148/+184 days (n = 79).
  - Cost P80/P90 +4,1/+11,8% (n = 83).
  - Planned-duration median 548 days.
- **Unit cost** for kanalizacja sanitarna: n = 1 734, P25/P50/P75 = 0,54/0,89/1,48 mln zł/km (nominal). The demo budget of 7 mln / 6 km = 1,17 → 64th percentile.
- **Steklin (RM-2026-003)**:
  - CN 2024/BZP 00349631/01 (04.06.2024); result 2024/BZP 00418711/01 (18.07.2024); contract 2 131 590,00 zł, due 18.08.2025.
  - Changes 2024/BZP 00554831/01 (+758 084,56 zł) and 2024/BZP 00618384/01 (+100 325,44 zł), both art. 455 ust. 1 pkt 3.
  - Performance notice 2026/BZP 00276065/01: completed 22.05.2026, paid 2 990 000,00 zł (+277 days, +40,3%).
- **Radar (Monitoring)**:
  - 4 873 awarded contracts have no performance notice. 3 321 are more than 90 days past the planned end; 234 are past it with a change notice already.
  - About 25% of contracts never get a performance notice, so the UI says "sygnał, nie dowód".
  - The five alerts are real notices from that "past end + change notice" group: Jeżów Sudecki 2024/BZP 00544853, Potworów 2024/BZP 00029259, Lędziny 2024/BZP 00504346, Kąty Wrocławskie 2024/BZP 00494115, Mogilno 2025/BZP 00334708.
- **Gold set** (notes on weak risks in 3.2): 150 hand-labelled change causes (`research/bzp_corpus/out/keyword_vs_gold.csv`). Keyword classifier precision/recall:
  - R03 0,87/0,72; weather 0,85/1,00; R02 0,82/0,56; R04 0,50/0,80; R07 0,55/0,66; R08 0,23/0,62; R01 0,40/0,14.
  - The weather category (11 of 150) backs the catalogue proposal "Warunki atmosferyczne".
- **Still placeholders** (`[x]`, `[n]`):
  - acceptance rates
  - Bielik-vs-Claude agreement
  - expected number of bids
  - KPO/TED/NIK source counts
  - the live API delta
  - cloud region
- **Demo-only values** (the analysis input is hypothetical):
  - the PFU/PPU quotes and the PFU page text in Red Pen
  - the 28% funding-deadline risk and the 31.08.2028 programme deadline
  - the S-curve shape, the tornado days and the toggle effects
  - the similarity scores and feature splits
  - the confidence components 0,95 / 0,60 / 0,80
  - the "7 proposals re-scored" learning-loop example

  Replace them with engine output.
