# Scope check: ex ante build vs planned scope

Audit date 2026-11-21 (evening). Read-only: GET calls against the local API (127.0.0.1:8000) and the deployed host, code and test greps, flag state in `config/config.example.yaml`. Nothing was edited, no POST/PUT/DELETE was sent, the full test suite was not run.

Limits of this audit:
- Endpoints behind login (review items, catalogue edit, settings, jobs, nav counts, dashboard) answer 401 to anonymous GET. For these the evidence is code, tests (`backend/tests/api/*`, `frontend/src/**/*.test.tsx`) and the flag state, not a live response.
- `GET /api/analyses` is empty (demo reset), so analysis endpoints were checked through tests and the sample exports in `exports/sample/`, not live.
- PLAN.md has no literal SHOULD/COULD labels. Scope is read as: the 10 "Must" items, the "Stretch" line, W1 to W18, the traceability table R1 to R22 and the §7 screens. The brief (`materials/text/01_tresc_zadania.txt`) is read for required deliverables and the 5 criteria. Expert material is `03_porady_...txt` (phases, documents, R01 to R15, "porady") and `04_poradnik_...txt`; `02_regulamin.txt` and `05_dane_projekty.txt` give rules and the 22 rows.

Status legend: done, partial, missing, flag off (built or designed but the flag is false).

## 1. Matrix

### 1a. PLAN §3 Must items

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| M1 import of organizer XLSX + CSV/XLSX/DOCX/PDF uploads, ID normalisation and validation | MUST | done | `ingest/xlsx_import.py`, `ingest/ids.py`, `validators.py`; `imports/*` (agent), `documents/upload.py` (.pdf .docx .doc .odt via LibreOffice); `GET /api/importers`, `POST /api/documents/upload`; `source` kind `xlsx` 22 records; tests `test_imports.py`, `test_documents_upload.py` | none |
| M2 BZP connector (live API + offline copy bulk) chained by tenderId | MUST | done | `connectors/bzp_api.py`; `GET /api/sources/summary` shows `bzp_copy` 113 278 and `bzp_api` 1 077 records; `/api/health` notices 248 642; `/api/procedures`, `/api/notices`, `/api/changes`, `/api/performance` | none |
| M3 at least one more public source end to end (KPO/CST + VAT whitelist, then TED/NIK) | MUST | done | summary: `fe_projects`, `mapa_dotacji`, `bk2021`, `vat_whitelist`, `ted` 18 325, `nik` 522, `kio` 2 084, `kposk`, `cru`, `krs`; flags `ted/kio/nik/cru/mapa_dotacji` true | `krs` 106 of 214 blocked, `docs_22` 416 blocked (logged as `blocked`, by design) |
| M4 linking with method/score/explanation + expert accept/fix/reject screen | MUST | done | `ingest/linking.py`, `link_national.py`; `GET /api/link-candidates`; 22/22 pilot, 3 589 national candidates (test_report); `review/service.py`, `frontend/src/features/review/ReviewScreen.tsx`; tests `test_review.py`, `test_link_national.py` | none |
| M5a deterministic risk events from BZP fields | MUST | done | `ingest/events.py`; `GET /api/risk-events` total 126 137; 109 events on the 22 pilots | none |
| M5b LLM extraction from documents and change-cause texts, R-codes with verified quotes | MUST | partial | cause classification: `llm/tasks/classify_causes.py`, 20 694 texts, 96.4% quotes verified (test_report); new-document extraction `llm/tasks/document_facts.py`. BUT the 22 pilots' own tender documents are not scanned: `GET /api/documents/29895/analysis` and `/29912` show extraction `pending`; `GET /api/risk-events?origin=AI` returns 0 | no batch document-risk extraction over the 2 258 fetched pilot documents (SWZ/PPU/PFU/annexes); risk events on pilots are 106 CALC auto + 3 proposed |
| M5c expert review queue | MUST | done | `GET /api/review-items*`, `review/queue_sync.py`, flag `review_queue`; 152 review_item rows in `/api/stats` | none |
| M6 project case view: timeline, planned vs actual, events with evidence, completeness checklist | MUST | done | `GET /api/projects/{rm_id}/card` (steps, timeline, plan_vs_actual, events, gaps with evidence states), `.../timeline`, `.../graph`; `frontend/src/features/projects/ProjectCardScreen.tsx` | none |
| M7 new-investment analysis: features, similar cases explained, ranges (n, P10/P50/P90), flags, gaps, clauses, saved record, JSON/CSV/PDF export | MUST | done | `analysis/service.py`, `analysis/report.py`, `analytics/similarity.py`, `refclass.py`, `flags.py`; `POST/GET /api/analyses`, `GET /api/analyses/{code}/pack.{docx,pdf,csv,json}`; `frontend/src/features/analysis`, `report`; samples in `exports/sample/AN-2026-0009_*`; tests `test_analyses.py`, `test_pack.py` | none |
| M8 catalogue editor (risks incl. AI-proposed, subsectors, checklist, clauses) + gold marking | MUST | done | `api/routers/catalogue_edit.py`, `review/catalogue.py`, `frontend/src/features/catalogue/CatalogueScreen.tsx` tabs (risks, proposals, podsektory, listy, zapisy, wagi), `review/service.py` `gold` flag; `GET /api/catalogue/versions`; flag `catalogue_edit` | none |
| M9 config-driven LLM provider; `config.example.yaml`, `.env.example`, DATA_PROCESSING and LICENSES docs | MUST | partial | `config/config.example.yaml` (routing, providers, data_location), `.env.example`, `llm/config.py`; data location in `docs/submission/technical.md` §6, licences in §8 and `licenses_backend.md`, `licenses_frontend.md` | no standalone DATA_PROCESSING doc and no `LICENSE` file in the repo root (content exists inside technical.md) |
| M10 deployed online, HTTPS, pre-ingested | MUST | done | `https://exante.linek.dev/api/health` returned 200; `infra/docker-compose.prod.yml`, `Caddyfile`; demo personas `GET /api/auth/demo-personas` (juror, expert) | deploy is current as of the probe only; not re-verified after the latest local commits |
| Stretch: OCR of scans (Tesseract pol) | SHOULD | done | `infra/Dockerfile.backend`, `Dockerfile.ocr`, `ingest/ocr_doc.py`; doc 33962 steps ocr done; Grodzisko scan in G6 | none |
| Stretch: NIK/KIO/BIP connectors beyond the first extra source | SHOULD | done | `connectors/nik.py` 522, `kio.py` 2 084, `bip_22.py` 78 records (111 errors) | BIP has 111 fetch errors out of 1 912 |
| Stretch: Claude Citations "strict grounding" mode | COULD | missing | no hit for "citations" in `backend/riskminer` | own verbatim-quote verifier (`llm/verify.py`) covers the need; low value |

### 1b. Wow layer W1 to W18

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| W1 Red Pen tender-document review | WOW | done | `analysis/redpen.py`, `llm/tasks/redpen_scan.py`, `GET /api/analyses/{code}/redpen/{document_id}`, `frontend/src/features/redpen`; flag `red_pen` true; test_report Red Pen section | text view only, no original-PDF overlay (stated in description §5) |
| W2 unit-cost benchmark (PLN/km) | WOW | done | `analytics/unit_cost.py`, `GET /api/analytics/unit-cost` (n 1 962, coverage 54%); flag `unit_cost` | length known for about half of contracts, nominal prices (stated) |
| W3 backtest and calibration | WOW | done | `analytics/backtest.py`, `GET /api/analytics/backtest` (85.0% inside P10 to P90, n_test 6 143) | none |
| W4 case graph | WOW | done | `api/project_graph.py`, `GET /api/projects/{rm_id}/graph`, `frontend/src/features/graph`, route `projekty/$id/graf`; flag `case_graph` | none |
| W5 Monte Carlo S-curve + tornado | WOW | done | `analytics/montecarlo.py`, `analysis/simulation.py`, `GET /api/analyses/{code}/simulation`, `POST .../simulate`; `frontend/src/features/simulation` | none |
| W6 Radar Polski + time machine | WOW | done | `monitoring/service.py`, `GET /api/monitoring/regions|signals|alerts`, `geo/{level}.geojson`, `frontend/src/features/monitoring`, `replay/TimeMachine.tsx`; flags `radar`, `radar_drill`, `monitoring_replay` | none |
| W7 visible learning loop | WOW | done | `llm/learning.py`, `GET /api/settings/llm/learning`, job `rescore_gold`; flag `learning_loop` | auth-gated, checked through tests `llm/test_learning.py` only |
| W8 sovereign-AI switch (Claude vs Bielik side by side, agreement) | WOW | flag off | flag `sovereign_switch: false`; sovereign routing exists in `llm/routing.py`, eval in `llm/eval/gold.py`; `SettingsScreen.tsx` hides the switch | WCSS Bielik job still pending (DEPLOY.md); no side-by-side agreement view shipped |
| W9 sector pack in 60 s (wizard) | WOW | flag off | flag `sector_pack_wizard: false`; second sector done by YAML (`catalogue/drogi/*`, flag `sector_roads` true, `connectors/bzp_roads.py`, `test_analyses.py` road case) | no wizard UI; drogi catalogue not expert-approved |
| W10 contracting-authority memory and contractor load | WOW | missing | `GET /api/organizations/{nip}` returns identity only; project card `buyer` has name, nip, nip_valid only; no contractor portfolio or buyer history code | R12 capacity signal not produced |
| W11 MCP server / open API | WOW | missing | no `mcp` package or server in `backend/`; open REST API exists (`/openapi.json`, `/api/export/*`) | no MCP surface |
| W12 "Zapytaj pamiec" (NL question, shown SQL, saved record) | WOW | done | `llm/tasks/nl2sql.py`, `llm/sqlguard.py`, `POST /api/ask`, `GET /api/ask/suggestions`, `POST/GET /api/questions`, `GET /api/questions/{code}/rows.{fmt}`; `frontend/src/features/ask`; flag `ask_memory` | `/api/questions` empty now (no saved demo record) |
| W13 risk-allocation matrix | WOW | done | `analysis/allocation.py`, `GET/PUT /api/analyses/{code}/allocation`, `frontend/src/features/allocation`; flag `allocation` | none |
| W14 funding-deadline risk (P of missing KPO deadline) | WOW | done | `analysis/simulation.py` uses `programme_deadline`, `catalogue/wod-kan/funding_programmes.yaml`, `GET /api/catalogue/funding-programmes` | PLN of subsidy at risk not confirmed in the output (not checked live) |
| W15 tender-outcome forecast (cancel, bids, price vs budget, seasonality) | WOW | done | `analytics/competition.py`, `GET /api/analytics/tenders` (per-year cancelled %, single offer %, median offers); competition metric in simulation | none |
| W16 document pack export (DOCX with register, matrix, checklist, clauses) | WOW | done | `analysis/pack.py` formats docx, pdf, csv, json; `POST /api/analyses/{code}/pack/clauses`; `exports/sample/AN-2026-0009_pakiet.docx`; flag `pack_export` | none |
| W17 sector lessons digest per subsector | WOW | missing | only per-project `lessons` in `/api/projects/{rm_id}/card` (4 lessons for RM-2026-001); no subsector digest endpoint or route | "institutional memory made readable" page absent |
| W18 accessibility and plain-language mode | WOW | partial | `frontend/e2e/a11y.spec.ts` + `a11y.ts` (axe), aria-labelled charts, keyboard hotkeys (`review/hotkeys.ts`) | no "explain simply" toggle on charts; a11y run not re-verified here |

### 1c. Brief (01_tresc_zadania) requirements and deliverables

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| B1 working prototype link for the jury | brief §4 | done | `https://exante.linek.dev` health 200; local web 5173 returns 200 | none |
| B2 detailed description and title | brief §4 | done | `docs/submission/description.md` (about 2 000 words, 9 sections, working vs designed split) | none |
| B3 PDF presentation, max 10 slides | brief §4 | done | `docs/submission/deck/ex-ante-pitch.pdf` has 10 pages (+3 alternatives) | none |
| B4 code repository | brief §4 | partial | origin `github.com/dawidlinek/hacknation-risk-miner`, visibility PRIVATE (gh); `README.md` is 23 bytes; no `LICENSE`; working tree has uncommitted changes | repo must be public or shared with jury; README has no run instructions (they live in technical.md §7 and CLAUDE.md) |
| B5 video up to 3 min at an open link | brief §4 | missing | only `docs/submission/video_script.md`; no mp4/webm in repo; no link in `hacktribe_draft.md` | recording not done |
| B6 screenshots, mockups of unfinished features | brief §4 (optional) | partial | mockups in `design/`, deck screens | no consolidated screenshot set for submission |
| B7 model in config, sample config, data location, licence | brief §5 | done | `config/config.example.yaml`, `.env.example`, technical.md §6, §7.3, §8 | no repo `LICENSE` (see M9) |
| B8 integrations: organizer file, .doc .xls .pdf .csv, BZP + TED/BK2021/KPOSK/NIK/KIO | brief §5 | done | sources summary (23 kinds incl. `kposk` 15 950, `bk2021` 110, `ted`, `nik`, `kio`); upload accepts .doc/.docx/.pdf/.odt/.xlsx/.csv | none |
| B9 ID-first linking, normalised and verified formats | brief §5 | done | `ingest/ids.py`, `validators.py` (NIP, REGON, KPO checks); `organizations.nip_valid` | none |
| B10 data model (project, procedure, notice, contract, change, event, cost/dates, document, source) | brief §5 | done | `/api/stats` tables incl. project 22, procedure 101 016, notice 248 642, contract 128 051, contract_change 60 294, risk_event 126 234, document 11 072, source 47 252 | none |
| B11 tabular data + DOCX and PDF with text layer; OCR bonus | brief §5 | done | `documents/pipeline.py`, `convert.py`, `ocr_doc.py`; G6 test on 3 organizer files | none |
| B12 similarity combining structured data and description text, explaining features | brief §5 | partial | `analytics/similarity.py` (BM25 + structured, contribution bars); `GET /api/projects/{rm_id}/similar` | text part is BM25 only; `chunk.embedding` column unused (description §5) |
| B13 ranges, flags, recommendations with n and uncertainty | brief §5 | done | `analytics/refclass.py` (bootstrap, Wilson), `forecast.py`, `flags.py`; "za malo danych" rule at n < 10 | none |
| B14 traceability: source id, link, retrieval date, page/quote, approval, edit history | brief §5 | done | `GET /api/evidence`, `/api/audit`, `/api/reviews`, `project history` route, `source` table (url, sha256, retrieved_at); `prov` on every API value | none |
| B15 results as filterable, exportable records (JSON/CSV) | brief §5 | done | `GET /api/export` lists 13 datasets; `/api/export/{dataset}.{csv,json}` verified for `risk_events` | analyses are not in the `/api/export` dataset list (exported through `pack.{fmt}` instead) |
| B16 scalability: no manual import of test data, proposals created automatically | brief §5 | done | `riskminer load-all`, `scrape` CLI, job worker, national 113k copy; `docs_sample` (19 812 files) | none |
| B17 demo of two paths (import + enrich; new investment + export) | brief §6 | done | e2e `frontend/e2e/demo-a-projects.spec.ts`, `demo-b-analysis.spec.ts`; flags `import_agent`, `project_docs` | rehearsal on the live host not evidenced here |
| B18 test integracji (re-runnable fetch without manual entry) | brief §6 | done | `GET /api/runs`, `ingestion_run` 208 rows, `riskminer scrape`; idempotent re-run test `test_pipeline.py` | none |
| B19 test laczenia (reference set) | brief §6 | done | test_report: 22/22 correct, KPO pairs 10/10 | none |
| B20 test kompletnosci przypadku | brief §6 | done | card `gaps`, `steps`, chain counts in test_report table | none |
| B21 test nowej inwestycji | brief §6 | done | `AN-2026-0009` samples, test_report "Analiza nowego projektu" | no analysis stored in the live DB right now (`/api/analyses` total 0); jury creates it live |
| B22 test zrodlowy | brief §6 | done | `exports/source_test_sample_seed2026.csv`, `llm/eval/source_test.py` (81/81), quote verifier | none |
| B23 test pracy eksperta (accept/correct/reject) | brief §6 | done | `POST /api/review-items/{id}/decision`, undo, skip, bulk; `GET /api/reviews`; juror persona is read-only, expert persona writes | none |
| B24 test zalozen (universality, scalability) | brief §6 | partial | second sector `drogi` by YAML; model switch by config | CPV literals still in 7 code files (verification.md §1a: `wodkan_classify.py`, `bzp_api.py`, `ted.py`, `bk2021.py`, `link_national.py`, `linking.py`, `bzp_roads.py`); not re-audited |
| B25 deliverable: short description, 10 pages max | brief §6 | done | `description.md` | none |
| B26 deliverable: technical docs (architecture, data model, sources, matching, run, licences) | brief §6 | done | `docs/submission/technical.md` (9 sections) | architecture and data-model diagram: no standalone image checked |
| B27 deliverable: test report (correct/uncertain/wrong links, new-project results) | brief §6 | done | `docs/submission/test_report.md` | none |
| B28 deliverable: sample structured export | brief §6 | done | `exports/sample/*` (JSON + CSV + DOCX + PDF) | none |
| B29 optional functions demonstrated | brief §6 | done | W1 to W7, W12 to W16 on, monitoring, time machine | see W8 to W11, W17, W18 |
| B30 re-analysis after new documents (brief §3, expert "Aktualizacja analizy") | brief §3 | done | `GET /api/projects/{rm_id}/changes-since?document_id=`, `monitoring/alerts` (alert id 239 for Zagrodno), flag `new_document_reanalysis`; `test_new_documents.py` | none |
| B31 open catalogue: AI proposes categories, expert approves | brief §3 | done | `llm/tasks/catalogue_proposals.py`, `POST /api/catalogue/proposals/{id}/decision`; R18 proposal in G6 | none |
| B32 effects in days/cost, causes, remedies and their effectiveness | brief §3 | partial | events carry `impact_days`, `impact_value`, `cause`; `mitigations.yaml`, `clauses.yaml` | measured effectiveness of remedies is not computed from cases (only proposed per risk) |
| B33 distinguish source / calculation / AI conclusions | brief §3 | done | `prov` roles on every value (`origin` SOURCE/CALC/AI), badges in UI | none |
| B34 understandable for non-programmers (Polish UI) | brief §3 | done | Polish copy, `copy.test.ts`; no code-level terms in UI (checked by test) | none |
| B35 security: log sources and operations, limit processing, avoid vendor lock-in | brief §5 | done | `llm/calllog.py`, `audit_log` append-only, routing public vs confidential, fallback chain | none |

### 1d. Expert material (03/04) mechanics

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| E1 R01 to R15 catalogue (+ AI-proposed R16+) | expert | done | `catalogue/wod-kan/risks.yaml`, `catalogue_risk` 71 rows, R18 proposal | none |
| E2 subsector classification (6 subsectors, main + additional) | expert | done | `catalogue/wod-kan/subsectors.yaml`, `parsing/wodkan_classify.py`, `subsector_main` in export | none |
| E3 four evidence states (not in package, not mentioned, unconfirmed, confirmed absent) | expert | done | `evidence_states.yaml`, card `gaps` with `BRAK_W_PACZCE`, `POTWIERDZONO` | none |
| E4 net vs gross compare like with like | expert | done | `_vat` basis columns, money value object, `vat_basis` in every API money field | none |
| E5 contract change legal basis (art. 455) | expert | done | `change_keywords.py`, `GET /api/changes` filter `legal_basis`, G6 pkt 3/pkt 4 flag | none |
| E6 PPU/SWU as labelled contract substitute | expert | done | `contract.terms_source` per PLAN R22; doc type `ppu` in documents (doc 29912) | not re-verified in the UI |
| E7 missing document explained, with what limits analysis | expert | done | card `gaps[].limits` ("Ogranicza ocene ryzyka R02") | none |
| E8 cancelled / repeated procedures as risk signal | expert | done | `analytics/tenders` cancelled % by year; `EV_*` cancellation events | none |
| E9 hierarchy of documents, chronology and versions, contradiction detection | expert | partial | `data discrepancy` review items (10), `part_mismatch`, `value_deviation` etc. | no explicit document-hierarchy or superseded-version handling for SWZ modifications |

### 1e. Organizer documents and golden expectations (`docs/impl/new_documents.md`)

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| G1 OCR on upload (Grodzisko scan) | brief | done | `ingest/ocr_doc.py`, `test_document_ocr.py` | none |
| G2 fact extraction rules + LLM with verified quotes | brief | done | `llm/tasks/document_facts.py`, `test_document_facts.py` | none |
| G3 linking + validation (KPO, NIP checksum 8161571014, R18) | brief | done | `review/doclink.py`, `test_doclink.py`; test_report "G6 3/3" | none |
| G4 re-analysis diff "Co sie zmienilo" + monitoring alert | brief | done | `GET /api/projects/RM-2026-002/changes-since?document_id=33962` returns growth (+1 zmiana, +3 zdarzenia), groups; alert 239 `document_change` | none |
| G5 UI (Dokumenty tab, status, facts, diff) | brief | done | `frontend/src/features/documents`, route `projekty/$id/dokumenty`; flag `project_docs`, `new_document_reanalysis` | none |
| G6 e2e on the three files | brief | done | `backend/tests/api/test_new_documents.py` | test skips when `materials/organizer_cases/` is absent |

### 1f. UI screens (PLAN §7) and remaining flags

| id / name | priority | status | evidence | gap |
|---|---|---|---|---|
| S1 Pulpit | SHOULD | done | `features/dashboard/PulpitScreen.tsx`, `GET /api/dashboard`, flag `dashboard` | auth-gated, not probed live |
| S2 Import i zrodla | SHOULD | done | `features/import/ImportScreen.tsx`, `/api/imports*`, `/api/sources*` | none |
| S3 Projekty + Karta | SHOULD | done | routes `projekty/*`, `GET /api/projects`, `/projects/stats` | none |
| S4 Przeglad | SHOULD | done | `routes/przeglad.tsx` | none |
| S5 Katalog wiedzy | SHOULD | done | `routes/katalog.tsx` | none |
| S6 Nowa inwestycja | SHOULD | done | `routes/analizy/*` (index, symulacja, pakiet, dokumenty) | none |
| S7 Monitoring | SHOULD | done | `routes/monitoring/*` | none |
| S8 Historia | SHOULD | done | `routes/historia.tsx`, `GET /api/audit` | none |
| S9 Ustawienia (data location, routing) | SHOULD | done | `routes/ustawienia.tsx`, flag `settings_view` | read-only |
| F1 flag `jelly` (3D builder bots) | COULD | flag off | `features/jelly/*`; held because it animates under prefers-reduced-motion | needs reduced-motion fix before enabling |
| F2 flag `docs_sample` | COULD | flag off | `connectors/docs_sample.py`, 19 812 files already in sources summary | flag false while data is loaded; confirm intent |
| F3 flag `sector_roads` | COULD | done | on; `catalogue/drogi/*` | catalogue not expert-approved |

## 2. Counts

Rows: 95. done 77, partial 9, missing 5, flag off 4.

## 3. Ranked gaps that matter for the jury

Ordering: brief requirements and evaluation criteria first (formal deliverables are gating, then the 20/20/25/20/15 criteria), then wow items. Effort: S under 30 min, M under 2 h, L longer.

| # | gap | why it matters | effort | files a fix would touch |
|---|---|---|---|---|
| 1 | Demo video missing (B5). Brief §4 lists it as a submission item, 3 min max, open link | formal completeness, jury sees it before the live run | L (recording, narration, upload) | `docs/submission/video_script.md` (exists), `docs/submission/hacktribe_draft.md` (add link) |
| 2 | Repository is private, `README.md` is 23 bytes, no `LICENSE` (B4, M9) | repo is a required deliverable; run instructions and licence are explicitly asked for; winners transfer copyright, so licence file matters | S (README with run steps copied from `CLAUDE.md` and technical.md §7; add LICENSE; the visibility switch is the owner's action) | `README.md`, `LICENSE`, GitHub repo settings |
| 3 | No risk-passage extraction over the 22 pilots' own tender documents (M5b). 2 258 fetched documents (SWZ, PPU, annexes) have extraction `pending`; AI-origin risk events are 0; pilot events are 106 deterministic CALC rows. Criterion 2 (20%) asks for "fragmenty dokumentow mogace swiadczyc o ryzyku" with sources | brief §2 bullet 2 and the "complete case" test: jury opens a pilot project and expects document-based risk proposals with page quotes, not only BZP fields | M to L (batch job over PPU/SWZ/PFU of the 22, public sensitivity so cloud models are allowed; output lands as `proposed` rows + review items; cost to budget) | `backend/riskminer/llm/jobs.py` (new batch kind next to `document_extract`), `llm/tasks/redpen_scan.py` or `document_facts.py`, `review/queue_sync.py`, `documents/jobs.py`; run via worker, no UI change |
| 4 | Authority and contractor memory missing (W10). `GET /api/organizations/{nip}` returns identity only; project card buyer block has no history; no R12 capacity signal | criterion 3 (25%) "wskazanych ryzyk, czerwonych flag"; PPP-department users think in contractor capacity; cheap neutral facts from existing contracts | M (SQL aggregate per buyer NIP and per contractor: contracts, late share, ongoing value; endpoint; card block; flag R12 in `flags.py`) | `backend/riskminer/api/routers/data.py` (organizations), `api/project_views.py`, `analytics/flags.py`, `frontend/src/features/projects/ProjectCardScreen.tsx`, `frontend/src/api/contracts/projects.ts` |
| 5 | Plain-language / "explain simply" mode missing (W18 partial). Brief criterion 5 and §3 "zrozumiale dla specjalisty bez kompetencji programistycznych" | UX 15% and the human-process test; a11y base exists, only the toggle is absent | S to M (a header toggle that swaps a short explanation line under each chart/KPI; copy lives in `copy`) | `frontend/src/app/AppHeader.tsx`, `frontend/src/components/common/SummaryCard.tsx`, `frontend/src/copy*` strings, `frontend/src/config/features.ts` |
| 6 | Sector lessons digest missing (W17). Only per-project lessons exist | "digital institutional memory" made readable; also answers "wnioski" for a whole subsector, only approved lessons | M (aggregate approved events and clauses per subsector into one page; endpoint + route; show only approved items) | `backend/riskminer/analytics/` (new `lessons.py`), `api/routers/data.py` or `analyses.py`, `frontend/src/routes/` (new route), `frontend/src/features/catalogue` or new feature |
| 7 | Similarity text part is BM25 only; embeddings not used (B12). Brief §5 wants structured data combined with description/document content, with explanation | works and is explained, but a semantic miss on paraphrased descriptions can lower "dobor grupy porownawczej" in the 25% criterion | L (embedding model with permissive licence, backfill `chunk.embedding`, blend into `score_pool`); licence check first (invariant 5) | `backend/riskminer/analytics/similarity.py`, `ingest/doctext.py`, `config/config.example.yaml` (`embeddings:`), migration if the column differs |
| 8 | MCP server / open API for assistants missing (W11) | growth potential and "plugs into ministry tools" in criterion 5; the REST API and exports already exist | M (thin MCP wrapper over `/api/search`, `/api/projects`, `/api/risk-events` with citations; MIT-licensed SDK) | new `backend/riskminer/mcp/`, `backend/pyproject.toml`, `docs/submission/technical.md` |
| 9 | Sovereign switch and sector-pack wizard off (W8, W9). The sovereign route exists in code, the UI hides it because Bielik on WCSS is not stable (job pending, DEPLOY.md) | criterion 4 "wykorzystanie systemu w kolejnych sektorach" and the "data stays in the ministry" claim; description already lists both as designed, so honest, but demo value is lost | M for W8 (agreement view over `llm/eval/gold.py` results, enable flag once WCSS is up), L for W9 | `frontend/src/features/settings/SettingsScreen.tsx`, `backend/riskminer/llm/eval/gold.py`, `api/routers/settings.py`, `config/config.example.yaml` |
| 10 | Remedy effectiveness not measured (B32). Mitigations and clauses are proposed from the catalogue, but their effect on delay or cost is not computed from cases | brief §3 "okreslic ich skutecznosc (jesli mozliwe)" and criterion 2; honest "n too small" output is acceptable | M (compare outcomes of cases with and without a clause or study, show n and CI, say "za malo danych" otherwise) | `backend/riskminer/analytics/templates.py`, `refclass.py`, `analysis/report.py`, `frontend/src/features/report` |
| 11 | Standalone DATA_PROCESSING and LICENSES docs (M9) | PLAN names them, brief §5 asks for data location and licence; content exists inside technical.md §6 and §8 | S (extract the two sections into `docs/DATA_PROCESSING.md` and `LICENSES.md`, link from README) | `docs/`, `README.md` |
| 12 | Red Pen shows text view only, not the original PDF page (W1) | polish for the "wow" moment; not a requirement | M | `frontend/src/features/redpen/RedPenScreen.tsx`, `routes/analizy/$id/dokumenty.$doc.tsx`, `GET /api/documents/{id}/file` already exists |
| 13 | Assumptions test (B24): CPV literals in 7 code files plus the drogi catalogue unapproved and no stored demo analysis or saved question in the live DB | jury "test zalozen"; a demo reset leaves `/api/analyses` and `/api/questions` empty, so a first click shows an empty state | S for seeding one analysis and one saved question after the reset (use `demo-baseline`), M for moving CPV literals into packs | `backend/riskminer/api/routers/` (admin demo baseline), `parsing/wodkan_classify.py`, `catalogue/wod-kan/cpv_map.yaml` |

Other observations (not gaps against scope):
- One national risk event has `occurred_on` 2029-08-03 (event id 301068, procedure 704147): a source date problem. Under invariant 10 it should be a review item, not silently kept; worth a quick query for future-dated events.
- `git status` shows uncommitted edits (CI workflow, `project_views.py`, e2e specs, deck PDFs). The submission needs a clean pushed commit; per CLAUDE.md nothing is committed without the user asking.
- Frontend unit tests: 23 files; backend tests: 37 files in `backend/tests` (counts in test_report: 276 pass, 3 skipped). Not re-run here.
