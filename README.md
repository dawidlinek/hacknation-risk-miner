# ex [ante]

**Wiedza ex post, decyzje ex ante.**

**Podsumowanie dla jury (PL).** ex ante to cyfrowa pamięć instytucjonalna inwestycji wodno-kanalizacyjnych (zadanie MFiPR „Risk Miner”, HackNation 2026). System automatycznie łączy publiczne źródła (BZP, TED, KIO, NIK i inne) w bazę zrealizowanych umów ze źródłem, zdarzeniami ryzyka i dowodami, a dla nowej inwestycji pokazuje, jak kończyły się podobne: z liczebnością próby, przedziałem i odnośnikiem do źródła każdej liczby. Wnioski AI są tylko propozycjami, o których decyduje ekspert. Wersja demonstracyjna: https://exante.linek.dev (logowanie jednym kliknięciem jako „juror”, tylko do odczytu). Interfejs jest po polsku.

Live demo: **https://exante.linek.dev** (one-click login as a demo persona: juror, expert or administrator, no password; the juror persona is read-only).

ex ante is a source-backed case base and risk analytics tool for public water and sewage investments in Poland. It turns scattered public records into linked, evidenced cases, then answers one question for a new investment: how did similar projects really end, and what should the contract say so that it does not happen again.

## What it does

The two jury paths:

**Path A: import and automatic enrichment**
- Import the organiser XLSX (or any sheet or document pack). An import agent proposes a column mapping, validates NIP, REGON, BZP and KPO numbers, runs a 50-row trial and imports only after approval. Data errors become review items, nothing is fixed silently.
- The system reconstructs the chain procedure, notices, contracts, changes and performance, and links TED, KIO, NIK, Central Contract Register and Grants Map records. Each link carries a method, a score and an explanation.
- Project card and source graph: planned vs actual time and cost, contract changes with legal basis (art. 455 Pzp) and cause mapped to risk codes R01 to R18, every fact with a notice field code or a document page and quote.
- New project documents (text PDF, DOCX, OCR for scans) become proposed facts, with a "what changed" view and a monitoring alert.
- Expert review queue: approve, edit or reject AI events, uncertain links, discrepancies and catalogue proposals, with undo and a full history.

**Path B: analysis of a new investment**
- Describe the investment in plain language; features are read as editable chips and the system asks follow-up questions.
- Report: a reference-class funnel, three answered questions with ranges (will you make the deadline, will the budget suffice, will you finish before the programme ends), red flags from rules, similar cases with a feature breakdown, contract clauses from the catalogue, stated limits and a backtest result.
- Red Pen: tender or contract text with highlighted passages, missing clauses and a proposed wording.
- Simulation (20 000 draws of whole contracts, "what if" switches), risk allocation matrix, and a dossier export (DOCX, PDF, CSV, JSON with a source annex).
- Ask the memory: natural-language questions turned into a database query, each answer labelled as calculation, AI conclusion or no data, with the SQL shown.

## Headline numbers

From `GET /api/analytics/headline` on the live database (data as of 2026-11-20). Scope: completed water and sewage works contracts with a BZP performance notice, from 2021.

| Figure | Value | n |
|---|---:|---:|
| Completed contracts | 11 222 | 11 222 |
| Finished after the deadline | 30,3% | 11 198 |
| Delay days in total | 265 tys. | 3 025 late contracts |
| Median delay when late | 58 days | 3 025 |
| 90th percentile of delay when late | 190 days | 3 025 |
| Contracts with at least one change | 41,6% | 11 222 |
| Paid above the contract value | 21,6% | 11 112 |
| Total paid above contract value | 586 mln zł (gross) | 11 112 |

Cost deviation is computed against the contract value in the performance notice, so it is a lower bound. About 25% of contracts never get a performance notice (see `docs/submission/description.md` §8).

## Architecture

```
public sources ──> connectors (fetch, raw + manifest, parse) ──> ingest (load, derive, link) ──> Postgres 18 + pgvector
                                                                                                    │
                          analytics, LLM tasks, review, monitoring  <───────────────────────────────┤
                                                                                                    v
                                                                          FastAPI  ──>  React SPA (Polish UI)
```

- Backend: Python 3.12, FastAPI, SQLAlchemy and asyncpg, a SKIP LOCKED job queue and a worker. Frontend: React with Vite. Database: Postgres 18 with pgvector.
- Module boundaries: connectors only fetch, write raw files and a manifest, and parse; ingest loads, derives and links; the API reads and handles review actions; analytics and LLM live in their own packages. Sector specifics live in `catalogue/<sector>/*.yaml` (a sector pack), not in code. Roads (`catalogue/drogi/`) were added as a second sector with data only.
- Model and provider are set in `config/config.example.yaml`; changing them needs no code change.

**Sovereignty routing.** Each LLM request carries a sensitivity level, the maximum of the declared level and that of every input document. Confidential documents (for example SWZ or PFU before publication, and uploads by default) go only to Polish models: Bielik and PLLuM on WCSS Wroclaw infrastructure, with a local Bielik fallback. If no Polish model answers, the AI part waits in the queue and the rule-based part keeps working; a confidential document never reaches a cloud. Public data goes to Gemini, with Mistral models via OpenRouter as the EU-routed fallback, used only for public data. Every response reports the provider, model and data location. Details: `docs/submission/technical.md` §6. The in-UI sovereign switch is hidden until Bielik is permanently available on WCSS.

## Data sources

23 sources, each re-runnable with `uv run riskminer scrape <source>`: the organiser XLSX (22 pilot projects) and BZP copy (113 278 notices), the live BZP / e-Zamowienia API, TED, KIO rulings, NIK audits, the Central Contract Register, Grants Map (KPO), KPOSK, NFOSiGW, the EU funds project lists, GUS BDL and price index, GUS BIR, the VAT whitelist, KRS, TERYT, GUGiK boundaries, Baza Konkurencyjnosci, municipal BIPs and procurement documents. The database holds 248 642 BZP notices, 101 016 procedures, 128 051 contracts, 60 293 contract changes and 68 755 performance notices. Fetch rules: at most 1 request per second per host, backoff, robots.txt, a fixed user agent without personal data, and CAPTCHAs or WAFs are never bypassed (recorded as `blocked`). Full table with licences: `docs/submission/technical.md` §3.

## Trust

- **Provenance on every record:** `source_id` (URL, retrieval date, sha256, path to the unchanged raw file, licence), origin (source, calculation, AI) and review status. Claims have evidence rows (notice field code, or document page and quote).
- **AI proposes, the expert decides.** AI output is stored as `proposed`; quotes are checked against the page text. A database trigger keeps approved rows from being overwritten by AI.
- **Append-only audit log:** updates and deletes are rejected by trigger; approvals are `review` rows.
- **Nothing fixed silently:** 10 dataset discrepancies were found automatically (8 in the organiser set) and wait in the expert queue.
- **Linking:** 22 of 22 pilot projects linked to BZP, 22 correct against the hand-checked reference, 0 wrong. 3 589 national link candidates with features and explanation.
- **Source test:** 81 of 81 sampled conclusions confirmed by a quote or source field (seed 2026).
- **Backtest** (forecasts from pre-2024 data against 6 143 later contracts): 85,0% of delays fall inside P10 to P90; Brier 0,217 vs 0,227 for the global forecast; the late share is under-predicted by about 6 pp.
- **Gold eval:** cause-code accuracy on a 150-item gold sample is 80,0% (interval 73,3 to 86,0%) against 37,3% for dictionary rules; 96,4% of AI quotes on 20 694 distinct cause texts were verified.

Full figures and method: `docs/submission/test_report.md`.

## Quick start

Requirements: Docker, Python 3.12 with `uv`, Node.js. Big data (`data/`, `materials/bzp_kopia/`) is not in git; see `docs/submission/technical.md` §7 for the files to provide.

```bash
cp .env.example .env                                         # add GEMINI_API_KEY
cp config/config.example.yaml config/config.yaml
docker compose -f infra/docker-compose.yml up -d db          # Postgres 18 + pgvector on :5434
cd backend && uv sync && uv run alembic upgrade heads        # the schema has two heads; `head` fails
uv run riskminer load-all                                    # catalogue → XLSX → BZP copy → derive → link 22/22 → scraped → report
uv run uvicorn riskminer.api.main:app --port 8000            # /docs, /openapi.json
uv run riskminer scrape <source> [--since D --limit N --only a,b]   # see `uv run riskminer sources`
uv run riskminer worker                                      # job queue (SKIP LOCKED)
cd ../frontend && npm ci && npm run dev                      # http://localhost:5173, proxies /api to :8000
```

Production deployment: `docs/DEPLOY.md`.

## Repository layout

| Path | Contents |
|---|---|
| `backend/riskminer/` | `connectors`, `ingest`, `api`, `analytics`, `analysis`, `llm`, `documents`, `imports`, `review`, `monitoring`, `jobs`, `db`, `parsing` |
| `backend/alembic/`, `backend/tests/` | migrations and backend tests |
| `frontend/` | React SPA (`src/features/*`), unit tests and Playwright e2e |
| `catalogue/` | sector packs as YAML: `wod-kan`, `drogi` |
| `config/config.example.yaml` | models, providers, routing, feature flags |
| `infra/` | Dockerfiles, compose files (dev and prod), Caddyfile |
| `scripts/` | load, scrape, deploy and freeze scripts |
| `exports/` | sample exports, eval results, source summary |
| `docs/` | `PLAN.md`, `scrape.md`, `DEPLOY.md`, `impl/`, `submission/` (description, technical doc, test report, licence annexes) |

## Tests

```bash
cd backend && uv run pytest -q          # 276 passed, 3 skipped by design (tests that write to the database)
cd frontend && npm test                 # 157 of 157 in 23 files
cd frontend && npm run e2e              # Playwright
```

Counts are from `docs/submission/test_report.md` (state of 2026-11-21).

## Licences of dependencies

Only permissive licences are used (MIT, BSD, Apache, PSF, MPL as a tool); no GPL, LGPL, AGPL, SSPL or CC-BY-NC packages.
- Backend (Python): [docs/submission/licenses_backend.md](docs/submission/licenses_backend.md)
- Frontend (npm): [docs/submission/licenses_frontend.md](docs/submission/licenses_frontend.md)

Licence of this repository's own code: [do sprawdzenia]. Under the task rules, winners transfer the economic copyright to the Ministry of Funds and Regional Policy (MFiPR).

## Team

Solvro Dawid: Dawid Linek.
