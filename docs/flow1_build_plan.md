# Flow 1 "Nowa inwestycja": what it needs and how we build it

Written 2026-11-21 16:50 from `design/README.md` §3–§4, the mockups `design/mockups/A1…A6, Main`, the live database (`riskminer-db`) and `backend/`.
Flow 1 is judging criterion 3 (25%). It is the path: Pulpit → 1.1 Start → 1.2 Raport (`AN-…` record) → 1.3 Czerwony długopis → 1.4 Symulacja → 1.5 Podział ryzyk i pakiet, plus the chats (report chat, 1.6 Zapytaj pamięć).

## 0. Verdict

**Data: yes, almost all of it. Code: no.** Three layers do not exist yet:

| Layer | State today |
|---|---|
| Frontend app | **Missing entirely.** There is no `frontend/` folder; only the design canvas and mockups exist |
| LLM layer | **Missing.** `llm_call` = 0 rows, no gateway code. **Key resolved 18:00:** Gemini key in `.env` (`GEMINI_API_KEY`), tested on `gemini-3.8-flash` and `gemini-pro-latest` with structured Polish extraction (see PLAN §4a) |
| Analytics + analysis service | **Missing.** `analysis` and `analysis_item` tables exist but are empty; no reference-class, forecast, similarity or simulation code in `backend/`; the API is read-only (no POST except jobs) |

On top of that, Flow 1 needs **3 small catalogue additions** (expert assumptions) and **4 decisions** from the team (§4).

What we already have that Flow 1 runs on:
- `rc_contract`: 67,562 rows, of which **11,808 are core water/sewage**, with subsector, design-build, value bucket, planned/actual days, delay, cost deviation, changes count, legal bases and cause codes. Demo class check: SAN + design-build = 503 contracts.
- `lot`: offers count, min/max/winning price, estimate, cancellation and reason. This covers the "Konkurencja" metric and the tender forecast.
- `contract_change`: 60,293 changes, 58,562 with cause text (44,702 unique texts), 46,025 with keyword cause codes.
- `document`: 9,549 fetched documents for 205 procedures (431 PFU, 309 PPU, 418 SWZ…). **Update 18:20: full-text search is live** (`/api/search`, 182k chunks over 6.7k documents, `prefix=true` for inflected Polish). `chunk.embedding` is still empty. OCR of ~3.2k scanned PDFs is running on WCSS and re-indexes automatically.
- Catalogue: similarity weights, 15 red-flag rules, 29 clauses, 9-item checklist, R01–R15 risks with sub-risks, evidence states.
- 22 pilot projects fully linked (the "deep cases" shown in the report: Tanibórz, Janów, Konarzewo, Steklin…).

## 1. Screen by screen: what each element needs

Status: **HAVE** = exists and usable, **PART** = data exists but the code to use it is missing, **MISS** = needs to be built.

### 1.1 Start (`A1-Start`)
| Element | Needs | Status |
|---|---|---|
| Description + file drop (PDF/DOCX) | `POST /documents/upload` storing a `document` with `sensitivity=confidential`, sha256, text per page | MISS (text extraction code exists for scraped docs, reuse it) |
| "Rozumiemy to tak" chips (podsektor, formuła, długość, przepompownie, budżet brutto, termin, finansowanie), each with its source (opis / PFU s.6) and an unsure state | LLM structured extraction with page refs + regex fallbacks (km, zł, months) | MISS |
| Follow-up question ("Ile będzie przyłączy?") when a key feature is missing | rule: required features from `similarity.yaml` not found | MISS (small) |
| Funding programme list (KPO, FEnIKS, …) with **end dates** | new catalogue file `funding_programmes.yaml` | MISS (catalogue) |

### 1.2 Raport (`A2-Raport`)
| Element | Needs | Status |
|---|---|---|
| Funnel 11,184 → kanalizacja → 5–10 mln → ZiW = n | reference-class builder with progressive widening (min n from 05 report: 30 for shares, 50–100 for P80/P90) | PART |
| Q1 "Czy zdążysz w 14 mies.?" (chance, P10–P90 band, median, your marker) | empirical quantiles + bootstrap CI on `actual_days`; P(actual ≤ plan) | PART |
| Q2 "Czy 7 mln wystarczy?" (zł/km vs P25/P50/P75) | **network length per contract is not in `rc_contract`**: port the length regex from `research/bzp_corpus/07_wow_features.py` into a `length_km` column | PART |
| Q3 "Czy zdążysz przed końcem programu?" | programme end date (catalogue) + forecast distribution | MISS |
| "W skrócie" sentence | template filled from computed numbers (design rule: never written by an LLM) | MISS (small) |
| Flags: calculated ("termin krótszy niż typowy") | rule engine over features vs reference class | MISS |
| Flags: AI from PFU/PPU with page and code (R02/R13/R08/R03) | LLM signal scan + server-side quote verifier + `red_flags.yaml` predicates | MISS |
| Similar cases (score, why, feature split, delay, cost) | similarity engine with catalogue weights and per-feature contributions; pool = 22 deep cases + national core procedures; text part via pg_trgm/tsvector first, bge-m3 later | MISS |
| "Co dopisać do umowy" with case evidence | clause recommender: risk codes → `clauses.yaml`, evidence from similar cases' change causes | PART |
| Limitations list | template | MISS (small) |
| "Zapytaj o tę analizę" chat | LLM over the analysis record + its computed numbers, answers labelled obliczenie / wniosek AI | MISS |
| Saved as `AN-2026-…` with versions + export | `analysis` + `analysis_item` rows, `POST /analyses`, `GET /analyses/{id}` | PART (tables only) |

### 1.3 Czerwony długopis (`A3-Dlugopis`)
| Element | Needs | Status |
|---|---|---|
| PDF viewer with page text and highlights | page text + char offsets of the uploaded document (`document_page`), react-pdf in the frontend | PART |
| Notes found in the text (R-code, page, pkt, verified quote) | same LLM scan as 1.2 flags; per-note `review_status` | MISS |
| Missing items ("Brak: klauzula waloryzacyjna", "Brak: dokumentacja geotechniczna") | rules: art. 439 (works > 6 months need indexation), doc-type checklist vs uploaded package, evidence states | MISS |
| "W 2 z 4 podobnych przypadków…" with case links | similar cases × their change causes with the same R-code | MISS |
| Proposed clause + "Dodaj do PPU" / "Popraw zapis" | clauses catalogue + an action that adds the clause to the analysis pack | PART |

### 1.4 Symulacja (`A4-Symulacja`)
| Element | Needs | Status |
|---|---|---|
| Time curve (share completed by month), cost curve, competition curve | Monte Carlo over the reference class: per-risk P(r) and empirical impact distributions from classified changes; competition from `lot` | PART (keyword cause codes cover ~76%; the rest needs LLM classification) |
| Toggles (badania gruntu, plan 18 mies., K-07, cena za metr) with per-option lines and "Razem" | **mitigation effects as expert assumptions**: new catalogue file `mitigations.yaml` (option → risk codes → probability/impact multipliers, flagged "założenie eksperta") | MISS (catalogue) |
| KPIs in pp, tornado "co najbardziej przesuwa termin" | simulation outputs | MISS |
| "Zapytaj: co jeśli" (przetarg +2 mies., jedna oferta, ceny +10%) | parameterised scenarios on the same simulation | MISS |

### 1.5 Podział ryzyk i pakiet (`A5-Podzial`)
| Element | Needs | Status |
|---|---|---|
| Per-risk expected cost and P80 impact | simulation output (prob × impact × budget) | MISS |
| 3 positions per risk with the recommended one, "jak" text per position, control and premium coefficients | **allocation block per risk** in the catalogue (recommended position, 3 how-texts, controllability, premium factor), flagged as expert assumptions | MISS (catalogue) |
| Case-based warning per risk | similar cases' events with that code | MISS |
| Live balance bar | frontend computation from the above | MISS |
| Pack: risk register, allocation matrix, checklist gaps, proposed PPU clauses, annex of sources and quotes; DOCX + PDF + CSV + JSON; only approved AI items | `python-docx` (MIT) for DOCX, LibreOffice headless (MPL, separate binary) for PDF, existing export layer for CSV/JSON, review gating | MISS |

### 1.6 Zapytaj pamięć + Pulpit chat (`A6-Czat`, `Main`)
| Element | Needs | Status |
|---|---|---|
| NL question → answer with SQL shown, n, sources, bars | LLM NL→SQL over whitelisted read-only views (`rc_contract`, `procedure`, …), a read-only DB role, result → template answer | MISS |
| Save as `Q-2026-…` record, export CSV, "Pokaż umowy" | small `question` table (or `analysis` with kind=question) | MISS |
| Pulpit headline, tiles, sources, discrepancies | `/stats`, `/sources/summary`, `/review-items` | HAVE |

## 2. Build plan: four workstreams

Contract first: the analytics session publishes the endpoint list and response schemas (below) within its first hour, so the frontend can build against the mockup data meanwhile.

**Endpoints to add** (all write an `audit_log` line; every number carries `origin` + `n` + `source`):
- `POST /documents/upload` (multipart, `sensitivity`) → document id, pages, detected doc type
- `POST /analyses` (text + document ids) → `AN-2026-NNNN` with extracted features (chips)
- `PATCH /analyses/{id}/features` (chip corrections) → re-run
- `GET /analyses/{id}` → report: funnel, questions Q1–Q3, flags, similar cases, clauses, limits, summary
- `GET /analyses/{id}/redpen/{document_id}` → page texts + notes with offsets + missing items
- `POST /analyses/{id}/simulate` (metric, toggles, what-if params) → curves, KPIs, tornado
- `GET|PUT /analyses/{id}/allocation` → risks with expected cost, positions, warnings, balance
- `GET /analyses/{id}/pack.{docx|pdf|csv|json}`
- `POST /analyses/{id}/chat`, `POST /ask` (+ `GET /questions`)
- `POST /review-items/{id}/decision` (approve / edit / reject / mark_gold), needed for "do przeglądu" items in the report

| Workstream | Owner | Scope |
|---|---|---|
| **F: frontend** | new session | Scaffold `frontend/` (React 19 + Vite + TS + shadcn/ui + Tailwind 4, tokens from `design/README.md` §5, `brand.ts`). AppHeader, SummaryCard, StatCard, ProvenanceTag, RangeBar, SimilarityBar, QuoteCard, StepList, ChipsEditor, FileDrop, Composer. Screens 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 + Pulpit. Typed client from `/openapi.json`; a mock layer serving the mockup data until each endpoint lands |
| **L: LLM** | new session | Gateway (`google_genai` for Gemini + `openai_compatible` for Bielik/PLLuM, aliases and sensitivity routing from config, `llm_call` logging, prompt caching), quote + number verifier (rapidfuzz). Tasks: feature extraction (chips with page refs); Red Pen signal scan with verified quotes; national change-cause classification (Gemini Flash-Lite now, Bielik on WCSS later) writing `cause_codes_ai`; report chat; NL→SQL for Zapytaj pamięć. Benchmark on the 150 gold causes |
| **A: analytics + analysis service** | new session | Reference class + funnel + widening; forecast (quantiles, bootstrap CI, n tiers); unit cost; similarity with contributions; Monte Carlo (time, cost, competition) with mitigation multipliers; tender-outcome stats; allocation balance; flag rules (subset of `red_flags.yaml` as Python predicates: F1 geotech, F2 private land, F5 funding deadline, art. 439 indexation, short term vs median, lump sum with uncertain length); clause recommender; analysis records; all endpoints above; DOCX/PDF pack |
| **D: data** | existing `data-db` session | Load the 9,096 extracted texts into `document_page` (+ `chunk` without embeddings for now); add `rc_contract.length_km` (port from `07_wow_features.py`); catalogue additions `funding_programmes.yaml`, `mitigations.yaml`, allocation block per risk (values labelled as expert assumptions, editable in Katalog); fetch the demo PFU/PPU (§4.2) |

**Timeline** (now 16:50):

| When | F | L | A | D |
|---|---|---|---|---|
| 17:00–19:30 | scaffold, tokens, shared components, 1.1 + 1.2 on mock data | gateway, verifier, chip extraction | reference class, forecast, unit cost, similarity, `POST/GET /analyses` | document_page load, length_km, catalogue additions, demo PFU |
| 19:30–20:00 | **HackTribe checkpoint** (team, repo, table, draft description) | | | |
| 20:00–00:00 | 1.3 Red Pen viewer, 1.4 Symulacja charts, wire to real endpoints | Red Pen scan, change-cause batch, report chat | simulation + what-ifs, clause recommender, Red Pen rules, review decisions | WCSS: Bielik serving (after §4.3) |
| 00:00 check | Is 1.1 → 1.2 → 1.3 end-to-end on real data? If not, fix before 1.4/1.5 | | | |
| 00:00–03:00 | 1.5 allocation + pack, 1.6 chat, Pulpit | NL→SQL, sovereign routing to Bielik | allocation, pack DOCX/PDF/CSV/JSON | support, data fixes |
| 03:00–07:00 | integration, demo run-through, polish; freeze 07:00 | | | |

## 3. Risks

| Risk | Mitigation |
|---|---|
| No frontend yet, and it is the biggest piece | Start F immediately on mock data; screens are fully specified in the mockups |
| LLM blocked without a key | Put `ANTHROPIC_API_KEY` in `.env` now (§4.1) |
| Monte Carlo inputs are thin where keyword codes are weak (R01, R08) | Batch-classify the 44,702 unique cause texts with the fast model tonight; show "n" per risk and fall back to "za mało danych" |
| Text similarity without embeddings | MVP with pg_trgm/tsvector on titles + descriptions (weight 0.13 only); bge-m3 on WCSS as an upgrade |
| Expert assumptions look like data | Every multiplier/coefficient lives in the catalogue with status "założenie eksperta" and is shown with that label (the design already does this) |
| "Confidential uploads only in Poland" claim without Bielik running | Either deploy Bielik on WCSS tonight, or mark the demo PFU as a public document and show the sovereign route as configured but not demoed |

## 4. Decisions needed now

1. ~~API key~~ **Done (18:00):** Gemini key in `.env`, works on the Gemini Developer API (global). Open: enable Vertex AI for the key to get EU-only processing (PLAN §4a), and confirm billing is on (paid tier).
2. **Demo input document.** Recommended: a **real public PFU + PPU of an ongoing 2026 design-build sanitary-sewer tender** taken from the BZP corpus (credible, citable, no invented quotes). The mockup's fictional `PFU_kanalizacja_v2.pdf` is the fallback.
3. **WCSS for sovereign mode.** Which grant to bill and an HF token with Bielik's licence accepted, so confidential uploads really stay in Poland. Without it, the demo PFU is processed as a public document.
4. **Sessions.** Start three new sessions now (frontend, LLM, analytics), each with a brief written from this file, and send the data additions to the existing `data-db` session.
