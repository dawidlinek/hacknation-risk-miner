# 04: Tech stack recommendation and event logistics (Risk Miner, HackNation 2026)

Research date: 2026-11-21. Versions and licences of Python/npm packages and HF models were read from the PyPI, npm and Hugging Face registry APIs on that day. Cloud availability and pricing claims come from vendor docs (links at the end); items marked **(verify)** could not be confirmed from a primary source.

---

## 0. TL;DR

| Layer | Pick |
|---|---|
| Backend | **Python 3.12 + FastAPI + SQLAlchemy 2.1 (async, asyncpg) + Alembic + Pydantic v2** |
| DB | **PostgreSQL 18 + pgvector + pg_trgm + unaccent** (docker image `pgvector/pgvector:pg18`). One DB for the relational case base, vectors, lexical search, job queue and audit log |
| LLM | **Own thin adapter (~150 LOC), 3 backend kinds**: `anthropic` (Claude API, and Bedrock through `base_url`), `anthropic_vertex`, `openai_compatible` (Mistral EU, Azure, OVH, Ollama/vLLM with Bielik). Model aliases (`fast/strong/best`) are set per task in `config.yaml`. **No LiteLLM**: its PyPI releases were compromised twice in 2026 |
| Default models | Claude Sonnet 5.5 for extraction, Haiku 5.5 for triage, Opus 5.5 for the new-investment report. Served EU-only via **Bedrock `eu.anthropic.*` geo profile** or **Vertex `eu` multi-region**. Bielik 11B v3.1 via Ollama as the local fallback |
| Grounding | Structured output (Pydantic schema) where every claim carries `evidence[{chunk_id, quote}]`. The server then **verifies each quote against the stored page text** (exact match, then rapidfuzz alignment) and checks that numbers in the claim appear in the quote. Unverified claims never reach "approved" |
| Parsing | **pypdfium2** for page text (fast, exact page numbers). **docling** (MIT) for DOCX/XLSX/tables/scans. **LibreOffice headless** for .doc→.docx. **Tesseract `pol`** OCR. **python-calamine** for xls/xlsx. Avoid PyMuPDF (AGPL) |
| Embeddings | **BAAI/bge-m3** (MIT) run locally on CPU. Alternatives: Qwen3-Embedding-0.6B (Apache-2.0), sdadas/mmlw-retrieval-roberta-large (Apache-2.0). Optional reranker bge-reranker-v2-m3 (Apache-2.0) |
| Entity resolution | Deterministic identifier normalisation (NIP/REGON checksums, BZP/TED/OCID/CST/KPO regexes), then a **rapidfuzz** weighted score whose features are stored as the explanation. Splink (MIT) is the scale-up path |
| Jobs | **Procrastinate** (MIT, Postgres-backed queue with periodic tasks and locks), separate `worker` container. No Redis |
| Frontend | **React 19 + Vite + shadcn/ui + TanStack Query/Table + react-pdf**, Polish UI. Plus **SQLAdmin** at `/admin` as the "edit any record" fallback |
| Audit | Append-only `audit_log` written by a SQLAlchemy session hook, `review_decision` rows with before/after JSON, `status` + `origin` on every AI record, versioned risk catalogue |
| Deploy | **Hetzner Cloud VM (DE/FI)** with docker compose: caddy (auto-HTTPS, basic auth), api, worker, db. Images built in GitHub Actions and pushed to GHCR. sslip.io hostname if there is no domain |

---

## 1. What in the challenge text drives the tech choices

Source: `materials/text/01_tresc_zadania.txt`, sections 5, 6 and 8.

| Requirement (Polish source) | Consequence for the stack |
|---|---|
| "Model ustawiamy w konfiguracji… plik z przykładową konfiguracją… gdzie przetwarzane są dane… licencja" | `config.example.yaml` + `.env.example`. Provider and model are selected by alias, never hard-coded. Each provider entry declares its `data_location`, and the UI footer and exports show which model and location produced each AI record |
| "unikać trwałego uzależnienia od jednego dostawcy" | Adapter with ≥3 interchangeable backends, demonstrated live by switching `LLM_PROVIDER`. A local Bielik profile proves the system runs fully on-prem |
| Model danych: projekty, postępowania, ogłoszenia, kontrakty, zmiany kontraktów, zdarzenia, koszty/terminy, dokumenty/źródła | Relational schema in Postgres with FKs (§3.3), not a document store |
| "Każdy rekord, powiązanie i kluczowy wniosek… identyfikator źródła, link, datę pobrania… stronę lub fragment… zatwierdzenie… historię edycji" | `source` (url, fetched_at, sha256), `evidence` (document, page, char span, quote, verification status), `review_decision`, `audit_log` |
| "Wyniki… jako rekordy możliwe do filtrowania, aktualizacji i eksportu (JSON/CSV); odpowiedź wyłącznie w oknie rozmowy nie spełnia wymagania" | The analysis is stored as `analysis` + `analysis_item` rows, never chat-only. Export endpoints produce JSON (nested case) and CSV (per table) |
| "Test integracji… możliwość ponownego uruchomienia procesu bez ręcznego wpisywania" | Idempotent, re-runnable pipeline stages keyed by content hash, run as background jobs. "Re-run" buttons per project and source |
| "Test źródłowy… Wynik bez możliwego do sprawdzenia źródła jest traktowany jako nieudokumentowany" | Server-side quote verification and a side-by-side viewer that highlights the quote on the cited page |
| "Test pracy eksperta… akceptuje, poprawia lub odrzuca niepewne dopasowanie" | Review queue covering links, events, facts and catalogue proposals, with confidence and "why" features |
| Kontrola ekspercka 20%: "zarządzanie wiedzą ekspercką bez zmian w kodzie… kolejne sektory" | Catalogue, rules, linking weights and sector configs are DB rows editable in the UI (versioned), not code |
| UX 15%: non-programmer users | A real SPA, not Streamlit. Clear visual separation of "dane źródłowe / obliczenia / wniosek AI" (explicitly required) |
| OCR = bonus; DOCX + PDF text layer = must | pypdfium2/docling for must-haves, Tesseract `pol` for the bonus |
| Winning team transfers economic copyright to MFiPR | Only permissive dependencies (MIT/BSD/Apache/PostgreSQL/MPL), plus an auto-generated licence list (`pip-licenses`, `license-checker`). Flags in §11 |

---

## 2. Recommended stack

| Component | Choice (version seen 2026-11-21) | Licence | Why | Alternative |
|---|---|---|---|---|
| Language/runtime | Python 3.12, `uv` for env/lock | PSF / MIT-Apache | Best ecosystem for docs/NLP/embeddings. 3.12 has the safest wheel coverage for torch/docling/OCR | 3.13 (fine), TypeScript-only backend (weaker parsing/NLP) |
| Web API | FastAPI 0.165 + uvicorn 0.54 | MIT / BSD-3 | Async, auto OpenAPI that generates the TS client, Pydantic-native. Claude Code is very fluent with it | Litestar (MIT), Django+DRF (heavier, but its built-in admin is tempting) |
| ORM/migrations | SQLAlchemy 2.1 (async) + Alembic 1.20 | MIT | Mature. Session events power the audit log. Alembic gives reproducible schema | SQLModel 0.0.50 (MIT, thinner but still 0.0.x) |
| DB driver | asyncpg | Apache-2.0 | Fast, permissive | psycopg 3.3 (**LGPL-3.0**; acceptable when used unmodified, but Procrastinate pulls it in anyway, see §11) |
| Database | PostgreSQL 18 (`pgvector/pgvector:pg18`) | PostgreSQL Licence | Relational integrity + JSONB + FTS + trigram + vectors in one engine, with concurrent API and worker writes | SQLite + sqlite-vec 0.1.9 (zero-ops, but single-writer and pre-1.0 vectors), DuckDB (analytics only). PG 19 was released 2026-11-19 with a built-in `polish` FTS config, but it is 2 days old and official pgvector images lag, so treat it as the upgrade path |
| Vector search | pgvector (HNSW, cosine) | PostgreSQL Licence | No extra service. Thousands of chunks is a trivial scale | Qdrant (Apache-2.0) if scale grows |
| Lexical search (Polish) | `simple` config + `unaccent` + `pg_trgm`, optional lemmas via **simplemma** 2.0 | PostgreSQL / MIT | PG ≤18 has no Polish stemmer. Embeddings handle morphology, trigram handles names and typos, lemmatised tsvector improves keyword hits | Hunspell pl_PL dictionary via `ispell` template (sjp.pl files are multi-licensed; pick Apache-2.0/MPL **(verify)**). PG19 `polish` Snowball config. Avoid spaCy `pl_core_news_*` models (GPL-3.0 **(verify)**) |
| LLM SDKs | `anthropic` 2.12 (Apache-2.0), `openai` 3.57 (Apache-2.0) used only as an OpenAI-compatible client | Apache-2.0 | Two SDKs cover every target provider (Claude API/Bedrock/Vertex; Mistral/Azure/OVH/Ollama/vLLM) | pydantic-ai 2.71 (MIT, good multi-provider structured output), Instructor 1.17 (MIT), any-llm (Apache-2.0). **LiteLLM 1.110 (MIT core) not recommended** (§4.1) |
| Extraction schema | Pydantic v2 models → JSON Schema → native structured outputs (`messages.parse(output_format=...)` on Claude, `response_format=json_schema` on OpenAI-compatible). Pydantic re-validation + 1 repair retry | MIT | Typed, provider-neutral, and the same schema documents the export | Claude Citations API as an optional "strict grounding" mode (§4.4) |
| Fuzzy quote verification | rapidfuzz 3.14 (`partial_ratio_alignment`) | MIT | Gives the aligned span offsets for highlighting | difflib (slow) |
| PDF text | pypdfium2 5.15 | BSD-3 / Apache-2.0 | Fast per-page text, exact page numbers, renders pages to PNG for OCR (no poppler/ghostscript) | pdfplumber 0.11 (MIT, slower, better for tables), pypdf 7.1 (BSD-3) |
| Rich parsing | docling 2.151 (+ docling-core/parse) | MIT (code). Models: Apache-2.0 / CDLA-Permissive-2.0 | DOCX/XLSX/PPTX/HTML/PDF to one document model with page/bbox provenance. Table structure. OCR hooks | unstructured 0.27 (Apache-2.0), markitdown 0.1.9 (MIT, no provenance) |
| .doc / .xls legacy | LibreOffice headless (`soffice --convert-to docx/xlsx/pdf`) | MPL-2.0 (separate binary) | Docling does not read .doc. LibreOffice also converts DOCX→PDF if you want page numbers and a pdf.js viewer for Word files | antiword (GPL, avoid) |
| Spreadsheets | python-calamine 0.9 (xls/xlsx/ods), openpyxl 3.1 | MIT | Calamine reads old .xls fast; openpyxl for writing exports | pandas `read_excel(engine="calamine")` |
| OCR | Tesseract 5 + `tesseract-ocr-pol` via pytesseract 0.3.13, pages rendered with pypdfium2 | Apache-2.0 | Good Polish support, CPU-only, small | RapidOCR 3.10 / EasyOCR 1.7 / PaddleOCR 3.7 (all Apache-2.0) via docling. Claude PDF/vision for hard scans (cost). **Not OCRmyPDF in the image** (needs Ghostscript, AGPL) |
| Embeddings | BAAI/bge-m3 via sentence-transformers 6.3 (CPU torch wheels) | MIT / Apache-2.0 | Multilingual incl. Polish, 8k tokens, 1024-dim, robust. Runs locally, so it adds no data-location question | Qwen3-Embedding-0.6B (Apache-2.0; Qwen3-Embedding-8B tops PL-MTEB on average), sdadas/mmlw-retrieval-roberta-large (Apache-2.0, Polish-specific, 512 tokens), multilingual-e5-large-instruct (MIT). Hosted EU: Mistral embed, OVHcloud AI Endpoints (bge-m3, Qwen3-Embedding-8B) |
| Reranker (optional) | BAAI/bge-reranker-v2-m3 | Apache-2.0 | Better top-k for "similar cases" evidence | Qwen3-Reranker-0.6B (Apache-2.0), sdadas/polish-reranker-large-ranknet (Apache-2.0) |
| Entity resolution | Own rules + rapidfuzz scoring, features stored as JSON | MIT | 22 projects × hundreds of records: transparent scores beat ML. Explanations come for free | Splink 5.0 (MIT, Fellegi-Sunter on DuckDB) when records reach thousands. recordlinkage 0.16 (BSD-3) |
| HTTP fetching | httpx 0.28 + tenacity 9.2. selectolax/BeautifulSoup for HTML. trafilatura 2.3 for BIP article text. Playwright 1.65 only if JS is required | BSD-3 / Apache-2.0 / MIT | Polite, cached, retrying connectors | Scrapy (BSD-3), overkill here |
| Jobs + scheduler | Procrastinate 3.12 (periodic tasks, retries, locks) | MIT (depends on psycopg, LGPL) | Queue lives in Postgres: no Redis, jobs visible to the UI, per-project locks prevent double re-analysis | DIY `SELECT … FOR UPDATE SKIP LOCKED` job table + APScheduler 3.11 (MIT), ~80 LOC. RQ (BSD-2)/arq (MIT)/Celery (BSD-3) need Redis. Prefect/Dagster (Apache-2.0) too heavy for 24h. Dramatiq is **LGPL** |
| Settings | pydantic-settings 2.16 (YAML + env) | MIT | One typed config object. Env overrides YAML | dynaconf (MIT) |
| Frontend | React 19.3 + Vite 8.3 + TypeScript, shadcn/ui (CLI 4.23) + Tailwind 4.3, TanStack Query 5 / Table 9 / Router 1, react-hook-form + zod, lucide icons, sonner toasts, recharts | MIT (lucide: ISC) | High UX ceiling at low cost. Claude Code is extremely fluent in this stack. Static build served by Caddy, so one origin with no CORS or SSR runtime | Next.js 16.4 (MIT; SSR not needed). Refine 5 / react-admin 5 (MIT; quick CRUD but harder to make pretty). Streamlit/Gradio/NiceGUI/Reflex (see §8) |
| API client | openapi-typescript 7.13 + openapi-fetch 0.17 (or orval 8.48) | MIT | Type-safe client generated from FastAPI's OpenAPI. Contract-first parallel work | Hand-written fetch |
| Document viewer | react-pdf 11 (pdf.js 6.5) + text-layer search highlight. react-pdf-highlighter-extended 8.1 if bbox highlights are wanted | MIT / Apache-2.0 | Side-by-side "claim ↔ highlighted quote on page N" | Show snippet text only (fallback for HTML/JSON sources) |
| Generic data editor | SQLAdmin 0.32 mounted at `/admin` | BSD-3 | Covers "przegląd, wpis, edycja… wszystkich danych wejściowych" for every table in ~30 LOC. The audit hook still records its edits | starlette-admin 1.0 (MIT) |
| Reverse proxy/TLS/auth | Caddy 2 | Apache-2.0 | Automatic Let's Encrypt, `basic_auth`, forwards the authenticated user to the app as the reviewer identity | Traefik (MIT), nginx + certbot |
| Local LLM (optional profile) | Ollama + `SpeakLeash/bielik-11b-v3.1-instruct:Q4_K_M` (~6.7 GB, 32K ctx) or vLLM | MIT / Apache-2.0. Bielik weights Apache-2.0 (gated) | Demonstrates "dane przetwarzane lokalnie" and the Polish sovereign-model story | Bielik 4.5B v3.0 (Apache-2.0) for CPU-only boxes (slow) |
| Licence inventory | pip-licenses 5.5 (MIT), `npx license-checker` | MIT | Required deliverable: "lista wykorzystanych modeli, usług, bibliotek i licencji" | Syft SBOM (Apache-2.0) |

---

## 3. Architecture

### 3.1 Containers (docker compose)

```
                 Browser (ekspert / juror)
   React SPA: Projekty, Kolejka przeglądu, Katalog ryzyk, Nowa inwestycja, Monitoring, Eksport
                              │ HTTPS + basic auth
┌─────────────────────────────▼──────────────────────────────────────────────────────────────┐
│ caddy  ── /            → SPA static files                                                    │
│        ── /api/*, /admin → api (FastAPI)  [header X-Remote-User = basic-auth user]          │
│                             │  CRUD, review actions, exports, enqueue jobs, job status       │
│                             ▼                                                                │
│        db: PostgreSQL 18 + pgvector + pg_trgm + unaccent                                     │
│            case base, chunks+embeddings, procrastinate queue, audit log                   │
│                             ▲                                                                │
│        worker (same image as api, `procrastinate worker`)                                    │
│            connectors: organizer XLSX, BZP/e-Zamówienia, TED, KPO lists, NIK, KIO, BIP │
│            parsers: pypdfium2, docling, LibreOffice, Tesseract(pol), calamine            │
│            embeddings: bge-m3 (CPU)                                                          │
│            LLM gateway ──► provider from config (Bedrock EU / Vertex EU / Mistral EU / ...)  │
│            periodic: monitor unfinished projects every N hours                               │
│  volume /data: raw/ (immutable downloads, named by sha256), parsed/, uploads/, exports/   │
│  [profile local-llm] ollama (Bielik), only on a GPU box or a team laptop                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Pipeline (each stage idempotent, re-runnable per project or source)

| # | Stage | Input → output | Idempotency key |
|---|---|---|---|
| 1 | `seed` | organizer XLSX → `project` rows (+ `source` row for the file, cell/row provenance) | file sha256 + row id (`RM-2026-001`) |
| 2 | `discover` | per project: query connectors by identifiers (BZP no., NIP, CST/KPO no.) → raw responses cached in `/data/raw` + `source` rows (url, fetched_at, http status, sha256) | (connector, query) + response sha256 |
| 3 | `normalize` | raw JSON/HTML → typed `procurement / notice / contract / contract_change / fact` rows | source sha256 + parser_version |
| 4 | `link` | deterministic ID joins → fuzzy candidates → `entity_link` (method, score, features, status) | pair + linker_version |
| 5 | `parse_docs` | PDFs/DOCX/… → `document`, `document_page` (text, ocr flag), `chunk` (page-bounded, offsets, tsvector, embedding) | document sha256 + parser_version + embed model |
| 6 | `extract` | triage chunks (cheap model) → extract events/facts with evidence (strong model) → verify quotes → `risk_event`/`fact` rows with `status=proposed` | (chunk set hash, task, model alias, prompt_version) |
| 7 | `review` | expert approve/edit/reject → `review_decision` + `audit_log`. Approved items feed few-shot examples and rules | n/a (human) |
| 8 | `aggregate` | per project: planned vs actual cost and time, change counts, event summary (each number labelled *obliczenie* with its inputs) | inputs hash |
| 9 | `analyze` (new investment) | text/docs → structured features (LLM) → hybrid retrieval of similar approved cases → explanation → empirical ranges (n, P10–P50–P90) → flags, recommendations, clause proposals with evidence → `analysis_item` rows | input hash + config hash |
| 10 | `monitor` | periodic re-discover for `status != zakończone` → diff against known notices → `alert` rows → enqueue 5–8 for the project | (project, since) |

Every LLM call is logged in `llm_call` (provider, model, data_location, prompt_version, token counts, latency, cost), which satisfies "rejestrować źródła i operacje".

### 3.3 Data model (core tables)

```
sector ─┬─< risk_category (versioned catalogue; status: approved|proposed; parent_id)
        └─< sector_config (feature weights, CPV prefixes, units – JSON, versioned)

project ─┬─< procurement (postępowanie: bzp_tender_id, ocid, cpv[], buyer_nip, procedure_type)
         │      ├─< notice (BZP/TED number normalised, type, published_at, source_id)
         │      └─< contract (contractor_nip, value_net/gross, signed_at, planned_end)
         │              └─< contract_change (date, Δvalue, Δdays, reason_text, notice_id)
         ├─< fact (kind: planned_cost|actual_cost|planned_end|actual_end|…, value, unit, as_of)
         ├─< risk_event (category_id, summary, cause, effect_days, effect_cost, mitigation,
         │               mitigation_effectiveness, confidence)
         └─< alert (monitoring)

source (kind, url, fetched_at, http_status, sha256, raw_path, connector_version)
document (source_id, title, mime, sha256, n_pages, ocr_used, is_exemplary)
document_page (document_id, page_no, text, ocr_conf)       chunk (document_id, page_no, start, end, text, tsv, embedding vector(1024))

evidence (target_type, target_id, field, document_id|source_id, page_no, start_char, end_char,
          quote, verification: exact|fuzzy|unverified|n/a, score)
entity_link (from_type, from_id, to_type, to_id, method: identifier|fuzzy|llm|manual,
             score, features jsonb, status)

-- common columns on every AI/derived row:
origin: import|connector|ai|expert   status: proposed|approved|edited|rejected|superseded
run_id → pipeline_run(kind, params, config_snapshot, started/finished, stats)
llm_call(run_id, provider, model, data_location, prompt_version, tokens_in/out, cost, latency)

review_decision (target_type, target_id, decision, before jsonb, after jsonb, reviewer, comment, at)  -- append-only
audit_log (at, actor: user:<name>|system|llm:<model>, action, entity, entity_id, diff jsonb, prev_hash, hash)  -- append-only
expert_rule (sector_id, condition jsonb, flag/recommendation text, status, version)
analysis (input_text, input_docs, features jsonb, config_snapshot) ─< analysis_item
         (kind: similar_case|range|flag|recommendation|clause, payload, evidence refs, status)
```

Extensibility: `sector` + `sector_config` + `risk_category` are data, so a new sector means new rows (and maybe a new connector), never schema changes.

---

## 4. LLM layer

### 4.1 Provider abstraction: thin own adapter

```python
class LLMClient(Protocol):
    async def structured(self, task: str, system: str, messages: list[Msg],
                         schema: type[BaseModel]) -> tuple[BaseModel, CallMeta]: ...
    async def text(self, task: str, system: str, messages: list[Msg]) -> tuple[str, CallMeta]: ...
```

Backend kinds:

* `anthropic`: `anthropic.Anthropic(api_key=..., base_url=...)`. Covers the Claude API and also **Bedrock's Messages endpoint**: the AWS model card shows `Anthropic(base_url="https://bedrock-runtime.<region>.amazonaws.com/anthropic", api_key=<Bedrock API key>)` with geo profile IDs like `eu.anthropic.claude-sonnet-5-5`. The same code path works with a different config. (`AnthropicBedrockMantle(aws_region=…)` with SigV4 is the other documented Bedrock route.)
* `anthropic_vertex`: `AnthropicVertex(project_id=…, region="eu")`, Google ADC.
* `openai_compatible`: `openai.OpenAI(base_url=…, api_key=…)` → Mistral EU (`api.eu.mistral.ai`), Azure OpenAI (or `AzureOpenAI`), OVHcloud AI Endpoints, Ollama `/v1`, vLLM.

Structured output strategy per backend: Claude uses `client.messages.parse(model=…, output_format=PydanticModel)`, or `output_config={"format": {"type": "json_schema", …}}`, and is supported on 1P, Bedrock and Vertex. OpenAI-compatible backends use `response_format={"type":"json_schema",…}` (Mistral documents it; Ollama honours it). For any backend lacking it, the fallback is `json_object` / prompt-JSON. **Always re-validate with Pydantic** and do one repair retry with the validation error.

Claude 5.x API notes for the implementer:
* Thinking cannot be disabled on Opus 5.5 / Sonnet 5.5; control cost with `output_config.effort` (`low` for triage, `medium`/`high` for extraction). Opus 5.5 defaults to `medium`.
* Forced `tool_choice` (`any`/`tool`) returns 400 on Opus 5.5 / Sonnet 5.5. Use structured outputs instead of "forced tool" JSON tricks.
* Don't send `temperature`/`top_p` (rejected on current models / API version 2026-10-21).
* Handle `stop_reason == "refusal"` (unlikely on procurement text). Use client-side fallback to another alias on Bedrock/Vertex, where server-side `fallbacks` is unavailable.
* Prompt caching: put the static system prompt + risk catalogue + few-shot approved examples first and mark it with `cache_control`. They repeat across hundreds of chunks.

Why not LiteLLM: it is MIT and convenient, but its PyPI releases were **compromised twice in 2026**: 1.82.7/1.82.8 in March (credential stealer, TeamPCP) and 1.107.0 in October (RAT; Docker images affected too). It is also a large dependency surface for a two-SDK problem. If someone insists, pin with hashes. pydantic-ai (MIT) is the acceptable "framework" alternative if the team prefers not to write the adapter.

### 4.2 Model tiering (aliases, all swappable in config)

| Task | Alias | Default Claude model | Notes |
|---|---|---|---|
| Chunk triage ("does this page mention delays, annexes, cost changes, penalties, disputes…?") | `fast` | `claude-haiku-5-5` | $0.10/$0.50 per MTok (1P list price) |
| Event/fact extraction with evidence, link tie-breaks | `strong` | `claude-sonnet-5-5` | $2/$10 per MTok |
| New-investment report (similarity explanation, flags, recommendations, clauses) | `best` | `claude-opus-5-5` | $4/$20 per MTok. 25% of the score rides on this output |

Rough cost: even 5–10 M input tokens of extraction comes to ~tens of USD on Sonnet. Bedrock/Vertex regional or EU endpoints carry ~10% premium. Set `budget_usd_per_day` in config and enforce it in the gateway.

### 4.3 Grounded extraction with provenance (provider-neutral, primary method)

1. **Chunk by page**: chunks never cross page boundaries. `chunk_id = "D{doc}:p{page}:c{n}"`, and `start/end` are offsets into `document_page.text`. DOCX without pages: either convert to PDF via LibreOffice (uniform viewer + page numbers) or use docling's heading path as the locator.
2. **Prompt** with the open risk catalogue (codes + definitions, approved categories only; the model may propose `NEW:<name>`), 2–4 **expert-approved examples** (the `is_exemplary` / approved events of the same category), and chunks wrapped as `<chunk id="D12:p7:c3">…</chunk>`. Instruct the model: every claim must cite ≥1 chunk with a **verbatim** 1–3 sentence quote; numbers (PLN, days, dates) must appear in the quote; write "brak danych" rather than guess.
3. **Schema** (sketch):

```python
class Evidence(BaseModel):
    chunk_id: str
    quote: str  # verbatim, 1–3 sentences

class RiskEventDraft(BaseModel):
    category_code: str                     # catalogue code or "NEW:<proposal>"
    summary: str
    cause: str | None
    effect_delay_days: int | None
    effect_cost_pln: float | None
    mitigation: str | None
    mitigation_effectiveness: Literal["skuteczne", "częściowo", "nieskuteczne", "brak danych"]
    confidence: float                      # model's own 0–1, shown but not trusted alone
    evidence: list[Evidence]               # validate len >= 1 client-side

class ExtractionResult(BaseModel):
    events: list[RiskEventDraft]
    facts: list[FactDraft]                 # cost/date facts, same evidence pattern
```

4. **Verify on the server**, never trusting the model:

```python
def verify(quote: str, page_text: str) -> Verification:
    nq, nc, back = normalize(quote), *normalize_with_map(page_text)  # NFKC, lower, join "-\n",
    i = nc.find(nq)                                                  # strip soft hyphens, unify quotes/dashes,
    if i >= 0:                                                       # collapse whitespace
        return Verification("exact", 100, back[i], back[i + len(nq)])
    al = rapidfuzz.fuzz.partial_ratio_alignment(nq, nc)
    if al.score >= cfg.fuzzy_min_score:  # ~90
        return Verification("fuzzy", al.score, back[al.dest_start], back[al.dest_end])
    return Verification("unverified", al.score, None, None)
```

   Plus a **numeric check**: every number in `effect_cost_pln` / `effect_delay_days` / dates must be found (after normalising `1 234 567,89 zł`) in the verified quote. Otherwise mark the field `needs_review`.
5. **Outcome**: exact/fuzzy-verified items enter the review queue as `proposed` with the highlight span. Unverified items enter it flagged red, can never be bulk-approved, and get a single automatic "re-quote" retry.
6. **Learning loop**: approved and edited events become few-shot examples and catalogue usage stats. Rejections with a reason feed a "common false positives" list in the prompt. This meets "wykorzystywać zatwierdzone przykłady oraz reguły w kolejnych analizach".

### 4.4 Optional Claude-only "strict grounding" mode (Citations API)

Claude's Citations feature returns `cited_text` plus a location for every cited claim. Supported on Claude API, Bedrock and Vertex for all current models. The location is `page_location` for PDFs, `char_location` for plain text, or block index for **custom-content documents**, where each of your chunks is one citable block, matching the `chunk_id` design. `cited_text` doesn't count toward output tokens.

**Constraint**: citations **cannot be combined with structured outputs** (400 error). So this is a 2-pass option: (a) citations-enabled free-text pass "list each risk event with citations", then (b) a structured pass that normalises it into the schema, carrying the citation spans. It also cannot cite scanned PDFs without a text layer. Use it only if time permits. The §4.3 method works for every provider including Bielik, so it is the primary.

---

## 5. Document parsing (Polish PDF/DOCX/XLS/DOC/CSV)

Decision flow in the worker:

```
file → sniff mime + sha256 (dedupe)
 ├─ .pdf  → pypdfium2 page text
 │          ├─ page has ≥ N chars → keep (fast path, exact page numbers)
 │          └─ else (scan) → render 300 dpi (pypdfium2) → Tesseract `pol` → page text (ocr_used=true, conf)
 │          (complex tables / layout needed → docling with do_ocr only on scanned pages)
 ├─ .docx/.xlsx/.pptx/.html → docling (structure + provenance)   [optionally soffice → PDF for viewer/pages]
 ├─ .doc/.xls/.odt/.rtf → soffice --headless --convert-to docx/xlsx → as above
 ├─ .csv/.xls/.xlsx tabular data → python-calamine / pandas → typed import (with row provenance)
 └─ HTML/JSON from connectors → selectolax/trafilatura → stored as text "pages" (page_no = null, locator = URL#section)
```

Notes:
* Docling on CPU with layout models runs at seconds per page. Use it selectively and keep pypdfium2 as the default for text PDFs.
* Install **CPU-only torch** wheels (`--index-url https://download.pytorch.org/whl/cpu`) to keep images ~1–2 GB instead of 5+ GB.
* Debian package `libreoffice-writer-nogui` (+ calc) keeps LibreOffice smaller **(verify size)**.
* Pre-download models (bge-m3, docling layout) at image build time. Hackathon Wi-Fi is the bottleneck.
* Avoid: **PyMuPDF / pymupdf4llm (AGPL-3.0 or commercial)**, **marker/surya weights** (code Apache-2.0 now, weights under modified OpenRAIL-M with revenue thresholds), **MinerU** (custom licence with thresholds), **OCRmyPDF in the image** (depends on Ghostscript, AGPL), **poppler-utils / pdf2image's poppler** (GPL).

---

## 6. Search, embeddings, similarity for "new investment analysis"

* **Hybrid retrieval**: `score = w_struct×S_struct + w_vec×cos(emb) + w_lex×ts_rank/trigram`, weights in `sector_config` and editable in the UI.
* **Structured features** (extracted from the user's free text/docs by the LLM into a schema, shown for confirmation): investment type (sieć kanalizacyjna / wodociąg / oczyszczalnia / SUW / przepompownia), scope quantities (km, RLM/PE, m³/d), formula (zaprojektuj i wybuduj vs buduj), procedure (Pzp krajowe/unijne), CPV, value bracket, region (TERYT), funding (KPO/FEnIKS/RPO), terrain hints.
* **Explanation = per-feature contributions** stored with each `similar_case` item ("typ: zgodny +0.30; długość 2.4 vs 3.1 km +0.12; formuła Z&W +0.20; podobieństwo opisu 0.78 +0.19"). The required "które cechy przesądziły o podobieństwie" is just the stored score breakdown.
* **Ranges**: empirical distribution over the comparison group of approved facts (cost overrun %, delay days). Show n, median, P10–P90. If n < `min_sample_for_range` (e.g. 5), show min–max and a "mała próba" warning. Every number is labelled *obliczenie* and links to the cases and facts used.
* **Flags/recommendations/clauses**: LLM (`best` alias) gets *only* approved events and facts from the selected cases + expert rules. Each output item must reference case/event IDs, and the server verifies the referenced IDs exist and belong to the comparison group.
* bge-m3 at 1024-dim with HNSW index. Query = feature summary + raw description. Optional rerank of the top-50 chunks with bge-reranker-v2-m3.

---

## 7. Entity resolution / linking

1. **Normalise identifiers** (unit-tested utilities): NIP (10 digits, checksum weights 6-5-7-2-3-4-5-6-7), REGON (9/14, checksum), BZP notice (`(\d{4})/BZP\s*0*(\d+)/(\d{2})` → canonical `2022/BZP 00058537/01`), TED (`\d{4}/S \d{3}-\d{6}` and the newer `NNNNNN-YYYY` publication numbers), OCID, KPO (`KPOD.03.15-IW.13-0004/25`), CST/FEnIKS project numbers. Mismatched checksums produce a data-quality flag. The organiser warned the data "mogą zawierać błędy".
2. **Deterministic links** (confidence 1.0, `method=identifier`).
3. **Candidate blocking** when no key exists: same buyer NIP (or buyer name trigram ≥ 0.6) AND date window AND CPV prefix (e.g. 4523xxxx).
4. **Scoring**: weighted sum of title similarity (rapidfuzz `token_set_ratio` on normalised Polish text: lowercase, unaccent, drop boilerplate words like "budowa", "gmina", "w miejscowości"), locality/TERYT match, CPV overlap, value ratio, date proximity. Store `features` JSON + final score.
5. **Thresholds** (config): ≥0.90 auto-propose as "pewne", 0.60–0.90 goes to the review queue as "niepewne", <0.60 is discarded but logged. Expert decisions are stored as labelled pairs and feed a future Splink model (MIT; Fellegi-Sunter with EM on DuckDB).
6. **Test report deliverable**: export `entity_link` grouped by status (correct / uncertain / wrong after review). This is literally the requested "Raport z testu".

---

## 8. Frontend and UX

Options weighed (UX 15% + expert control 20%):

| Option | Build speed | UX ceiling | Review workflows / PDF highlight | Verdict |
|---|---|---|---|---|
| Streamlit 1.67 / Gradio 6.32 (Apache-2.0) | fastest first screen | low, "prototype" look | rerun model fights multi-step review; weak viewer | No (fine for internal debug pages) |
| NiceGUI 4.0 (MIT) / Reflex 0.11 (Apache-2.0) | fast, Python-only | medium | doable, smaller ecosystem, Claude Code less fluent | Fallback if nobody does React |
| Next.js 16 (MIT) | medium | high | yes | Works, but SSR/server runtime adds nothing here |
| **React + Vite + shadcn/ui + TanStack** | fast with Claude Code | high | yes (react-pdf, DataTable, keyboard shortcuts) | **Recommended** |

Screens (Polish UI):
1. **Projekty**: table with filters (status, region, type, # events, data completeness %). Project page shows a timeline (procurement → notices → contract → changes → events), "Źródła" tab, and buttons "Odśwież źródła" / "Analizuj ponownie".
2. **Kolejka przeglądu**: one queue for links, events, facts, catalogue proposals and alerts. Split view: left the claim with editable fields, right the document page with highlighted quote + source URL + fetched_at. Keys `A` approve, `E` edit, `R` reject (reason required), `J/K` next/prev. Badges: *Propozycja AI*, *Zatwierdzone*, *Edytowane*, *Odrzucone*, verification badge *cytat zweryfikowany / przybliżony / niezweryfikowany*.
3. **Katalog ryzyk**: tree editor, versions, "proposed by AI" inbox, usage counts, mark examples as wzorcowe.
4. **Nowa inwestycja**: free-text box + file upload → confirm extracted features (editable) → results: similar cases with "dlaczego podobne" bars, ranges with n and uncertainty, red flags, recommendations, clause proposals. Every item has evidence chips and its own review status. Export JSON/CSV.
5. **Monitoring**: unfinished projects, last check, new notices/alerts, "Sprawdź teraz".
6. **Ustawienia**: active LLM provider (read-only display + data location), sector config weights, expert rules editor.
7. `/admin` (SQLAdmin): raw edit of any table, for power users.

Visual grammar (explicitly required): three colours/icons for **Dane źródłowe** (from a document or registry), **Obliczenie** (computed, with formula tooltip) and **Wniosek AI** (model output, with model + data location tooltip).

---

## 9. Audit log, provenance, versioning

* `origin` + `status` + `run_id` on every derived row. AI never overwrites expert-approved values: a re-run creates new `proposed` rows and marks older AI rows `superseded`.
* `review_decision` is append-only with `before`/`after` JSON. The UI shows the edit history per record ("historia edycji zatwierdzeń").
* `audit_log`: a SQLAlchemy `before_flush` hook writes a row for every insert/update/delete from any path (API, worker, SQLAdmin), with actor (`user:<X-Remote-User>`, `system`, `llm:<model>`). Make it tamper-evident cheaply: the DB role used by the app has `INSERT` only on audit tables (`REVOKE UPDATE, DELETE`), plus a `prev_hash → hash` chain.
* Catalogue/rules/sector configs are versioned rows (`version`, `valid_from`, `superseded_by`), and each analysis stores `config_snapshot` so results are reproducible.
* Prompts are files in the repo (`prompts/extract_events.v3.md`), and their hash is stored on each `llm_call`.

---

## 10. Background jobs and monitoring module

* Procrastinate tasks: `discover_project(project_id)`, `parse_document(doc_id)`, `extract_project(project_id)`, `link_project(project_id)`, `analyze_investment(analysis_id)`. Use the lock `project:<id>` so two re-analyses never race.
* Periodic: `@app.periodic(cron=cfg.monitoring.cron)` → for each unfinished project, query BZP/TED since `last_checked_at` by buyer NIP + CPV/identifiers. New notices (e.g. contract change, result, annex) create `alert` rows and enqueue parse→extract→aggregate.
* For the demo: a "Sprawdź teraz" button + a seeded "new document" upload. Show that the project's events and conclusions update and the diff appears in the review queue.
* UI shows job progress by polling the `procrastinate_jobs` table (status, attempts, error) through an API endpoint.

---

## 11. Licence audit (copyright transfer to MFiPR)

Permissive and OK: FastAPI, SQLAlchemy, Alembic, Pydantic, pydantic-settings, SQLAdmin (BSD-3), asyncpg, pgvector, PostgreSQL, docling (+ models Apache-2.0/CDLA-Permissive-2.0), pypdfium2, pdfplumber, pypdf, python-docx, openpyxl, python-calamine, rapidfuzz, splink, sentence-transformers, bge-m3 (MIT), Qwen3-Embedding (Apache-2.0), mmlw-retrieval-roberta-large (Apache-2.0), bge-reranker-v2-m3 (Apache-2.0), Tesseract/pytesseract, RapidOCR/EasyOCR/PaddleOCR, anthropic/openai SDKs, Procrastinate, trafilatura, Playwright, httpx, React, Vite, shadcn, Tailwind, TanStack, react-pdf, pdf.js, Caddy, Ollama, vLLM, Bielik v3.x (Apache-2.0, gated download).

**Flags:**

| Item | Licence | Action |
|---|---|---|
| PyMuPDF, pymupdf4llm | **AGPL-3.0** / commercial | Do not use |
| Ghostscript (via OCRmyPDF), MinIO, Grafana, Metabase, ParadeDB pg_search | **AGPL-3.0** | Do not use (OCRmyPDF itself is MPL-2.0 but pulls Ghostscript) |
| poppler-utils (pdftotext, pdf2image backend), antiword, unoconv | **GPL** | Avoid; pypdfium2 + LibreOffice cover these |
| psycopg 3 (pulled in by Procrastinate), Dramatiq | **LGPL-3.0** | psycopg used unmodified as a library is generally fine, but list it. If MFiPR wants zero copyleft, swap Procrastinate for the DIY asyncpg queue |
| marker-pdf / surya-ocr | code Apache-2.0, **weights modified OpenRAIL-M (revenue thresholds)** | Avoid |
| MinerU | **custom "MinerU Open Source License"** | Avoid |
| sdadas/mmlw-retrieval-roberta-large-v2, sdadas/polish-reranker-roberta-v3, google/embeddinggemma | **Gemma licence** | Avoid (use the Apache-2.0 v1 / ranknet variants) |
| jinaai/jina-embeddings-v3 (and jina rerankers) | **CC-BY-NC-4.0** | Do not use |
| ipipan/silver-retriever-base-v1.1 | **CC-BY-SA-4.0** | Avoid |
| spaCy Polish pipelines `pl_core_news_*` | GPL-3.0 **(verify)** | Use simplemma (MIT) instead |
| Hunspell pl_PL dictionaries (sjp.pl) | multi-licensed (GPL/LGPL/MPL/Apache-2.0/CC-BY) **(verify)** | If used, take them under Apache-2.0/MPL |
| LiteLLM | MIT, but **2026 supply-chain compromises** | Avoid, or pin with hashes |

Third-party services (Claude via AWS/Google, Mistral, Azure) are services, not code, so they don't affect the copyright transfer. Document them in the "services" list with ToS links.

---

## 12. Example configuration

`config/config.example.yaml` (copy to `config/config.yaml`; secrets only in `.env`):

```yaml
app:
  name: "Risk Miner"
  language: pl
  public_base_url: "https://riskminer.example.eu"
  data_dir: /data                    # raw/, parsed/, uploads/, exports/

database:
  url_env: DATABASE_URL

llm:
  active_provider: bedrock_eu        # env LLM_PROVIDER overrides. Options below.
  budget_usd_per_day: 30
  defaults: { max_tokens: 16000, timeout_s: 300, max_retries: 2 }
  tasks:                             # logical task -> model alias (+ optional effort)
    triage:                 { alias: fast,   effort: low }
    extract_events:         { alias: strong, effort: medium }
    link_tiebreak:          { alias: fast,   effort: low }
    extract_new_investment: { alias: strong, effort: medium }
    analyze_new_investment: { alias: best,   effort: high }
  providers:
    anthropic:                       # Claude API (Anthropic, global routing)
      kind: anthropic
      api_key_env: ANTHROPIC_API_KEY
      data_location: "Poza UE możliwe (routing globalny Anthropic)"
      models: { fast: claude-haiku-5-5, strong: claude-sonnet-5-5, best: claude-opus-5-5 }
    bedrock_eu:                      # Claude in Amazon Bedrock, EU geo inference profile
      kind: anthropic
      base_url: "https://bedrock-runtime.eu-central-1.amazonaws.com/anthropic"
      api_key_env: AWS_BEARER_TOKEN_BEDROCK          # Bedrock API key (short-term preferred)
      data_location: "UE (AWS: Frankfurt, Sztokholm, Mediolan, Hiszpania, Irlandia, Paryż)"
      models: { fast: eu.anthropic.claude-haiku-5-5, strong: eu.anthropic.claude-sonnet-5-5,
                best: eu.anthropic.claude-opus-5-5 }   # verify IDs in console / GetInferenceProfile
    vertex_eu:                       # Claude on Google Cloud (Google managed), EU multi-region
      kind: anthropic_vertex
      project_id_env: GCP_PROJECT_ID
      region: eu
      data_location: "UE (Vertex AI multi-region eu)"
      models: { fast: claude-haiku-5-5, strong: claude-sonnet-5-5, best: claude-opus-5-5 }
    mistral_eu:
      kind: openai_compatible
      base_url: "https://api.eu.mistral.ai/v1"
      api_key_env: MISTRAL_API_KEY
      structured_output: json_schema
      data_location: "UE (Mistral AI, centra danych UE/EFTA)"
      models: { fast: mistral-small-latest, strong: mistral-medium-latest, best: mistral-large-latest }
    azure_openai_eu:
      kind: openai_compatible
      base_url_env: AZURE_OPENAI_BASE_URL            # resource in an EU region, Data Zone EU deployment
      api_key_env: AZURE_OPENAI_API_KEY
      structured_output: json_schema
      data_location: "UE (Azure OpenAI Data Zone EU)"
      models: { fast: <deployment-name>, strong: <deployment-name>, best: <deployment-name> }
    local_bielik:
      kind: openai_compatible
      base_url: "http://ollama:11434/v1"
      api_key_env: null
      structured_output: json_schema                 # fallback: prompt_json
      data_location: "Lokalnie (serwer aplikacji)"
      models: { fast: "SpeakLeash/bielik-11b-v3.1-instruct:Q4_K_M",
                strong: "SpeakLeash/bielik-11b-v3.1-instruct:Q8_0",
                best: "SpeakLeash/bielik-11b-v3.1-instruct:Q8_0" }

embeddings:
  kind: local                        # local | openai_compatible
  model: BAAI/bge-m3
  dim: 1024
  device: cpu
  batch_size: 16
  data_location: "Lokalnie (serwer aplikacji)"
reranker: { enabled: false, model: BAAI/bge-reranker-v2-m3 }

parsing:
  pdf_fast_path: pypdfium2
  rich_parser: docling
  legacy_converter: libreoffice
  ocr: { enabled: true, engine: tesseract, languages: [pol], min_chars_per_page: 40, dpi: 300 }
  chunk: { max_chars: 3500, overlap_chars: 300, never_cross_pages: true }

grounding:
  fuzzy_min_score: 90
  require_numbers_in_quote: true
  max_requote_retries: 1

linking:
  thresholds: { auto: 0.90, review: 0.60 }
  weights: { title: 0.30, buyer: 0.25, cpv: 0.15, location: 0.10, value: 0.10, dates: 0.10 }

sources:                              # connectors (details: see data-sources research doc)
  organizer_xlsx: { path: /data/seed/Risk_Miner_dane_projekty.xlsx }
  bzp:  { enabled: true, rate_limit_rps: 2 }
  ted:  { enabled: true, rate_limit_rps: 2 }
  kpo:  { enabled: true }
  nik:  { enabled: true }
  kio:  { enabled: false }
  bip:  { enabled: true, user_agent: "RiskMiner-prototype/0.1" }

monitoring: { enabled: true, cron: "0 */6 * * *", statuses: ["w realizacji", "nieukończone"] }

analysis:
  similar_cases_k: 8
  min_sample_for_range: 5
  quantiles: [0.1, 0.5, 0.9]
  weights: { structured: 0.5, vector: 0.35, lexical: 0.15 }

auth:
  mode: proxy_header                 # reviewer identity from Caddy basic auth
  header: X-Remote-User
```

`.env.example`:

```dotenv
# --- core ---
RISKMINER_CONFIG=/app/config/config.yaml
DATABASE_URL=postgresql+asyncpg://riskminer:change-me@db:5432/riskminer
POSTGRES_PASSWORD=change-me
LLM_PROVIDER=bedrock_eu            # anthropic | bedrock_eu | vertex_eu | mistral_eu | azure_openai_eu | local_bielik

# --- set only the provider you use ---
ANTHROPIC_API_KEY=
AWS_BEARER_TOKEN_BEDROCK=          # Bedrock API key, region eu-central-1
GCP_PROJECT_ID=
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-sa.json
MISTRAL_API_KEY=
AZURE_OPENAI_BASE_URL=
AZURE_OPENAI_API_KEY=
HF_TOKEN=                          # only to download gated Bielik weights

# --- deployment ---
DOMAIN=riskminer.203-0-113-10.sslip.io
BASIC_AUTH_USERS="ekspert:$2a$14$...bcrypt...,jury:$2a$14$...bcrypt..."   # caddy hash-password
```

---

## 13. Where data is processed (per provider option)

| Option | Config | App/DB | LLM inference | Embeddings | Notes |
|---|---|---|---|---|---|
| **A. Recommended EU cloud** | `bedrock_eu` | Hetzner DE/FI (EU) | **EU** – AWS EU geo profile from eu-central-1 routes only to Frankfurt, Stockholm, Milan, Spain, Ireland, Paris | Local (EU server) | AWS-operated, "zero operator access" for Anthropic staff. Regional/geo ≈ +10% price. Model access for Sonnet/Opus/Haiku 5.5 may need enabling in the console, so request it immediately |
| B. EU cloud alt. | `vertex_eu` | EU | **EU** – Vertex multi-region `eu` (regional endpoints serve only Sonnet 4.6 and older) | Local | +10% vs global. Users report quotas starting at 0, so request early |
| C. EU-native vendor | `mistral_eu` | EU | **EU** – `api.eu.mistral.ai` (EU/EFTA DCs) | Local or Mistral embed (EU) | EU company. Some features may use non-EU subprocessors under SCCs |
| D. Microsoft | `azure_openai_eu` | EU | **EU** – Data Zone EU deployment in an EU region | Local | US parent company (note CLOUD Act exposure, as for AWS/Google) |
| E. Fully local / on-prem | `local_bielik` | Local server | **Local** (Ollama/vLLM, Bielik 11B v3.1, Apache-2.0) | Local | No data leaves the host. Lower extraction quality; GPU recommended (Q4_K_M ≈ 6.7 GB) |
| F. Fastest setup | `anthropic` | EU | **Possibly outside EU** (Anthropic API: global routing; `inference_geo` offers only `global`/`us`) | Local | Use for development only, or state it plainly |
| Public sources (BZP, TED, KPO, NIK, KIO, BIP) | – | fetched to EU server | – | – | Public data. Minimise personal data (names in protocols): don't extract persons, keep raw files access-restricted |

The active provider's `data_location` is printed in the UI footer, stored on every `llm_call`, and included in exports.

---

## 14. Deployment for jury testing

* **Hetzner Cloud** (Falkenstein/Nuremberg/Helsinki, EU), hourly billing. After the June 2026 price change a CX33 (4 vCPU/8 GB) lists around €9/mo, but CX availability is patchy, so take a CPX/CAX class with **8–16 GB RAM** (docling + bge-m3 + Postgres). The hackathon costs only a few euros. New Hetzner accounts can require ID verification, so use an existing team account. Alternatives: OVHcloud (has a Warsaw region, so data stays in Poland **(verify)**), Scaleway (Paris), or PaaS (Fly.io/Railway/Render EU regions), which need extra work for pgvector + worker + volume.
* `docker compose up -d` with services `caddy`, `api`, `worker`, `db`, and an optional `ollama` profile.
* **HTTPS without a domain**: `DOMAIN=<ip-with-dashes>.sslip.io` works with Caddy's automatic Let's Encrypt.
* **Auth**: Caddy `basic_auth` with bcrypt users (`ekspert`, `jury`), `header_up X-Remote-User {http.auth.user.id}` so review decisions record who approved. Put jury credentials in the HackTribe submission.
* **Build**: GitHub Actions builds the image (CPU torch, models pre-downloaded) → GHCR → `docker compose pull` on the VM. Don't push GBs over venue Wi-Fi.
* **Demo safety net**: commit a `pg_dump` of the fully ingested and reviewed demo DB (`data/demo_seed.sql.gz`) + `make demo` for local runs. The challenge allows local runs only "w przypadku uzasadnionego braku możliwości", so online is the target. Optional Cloudflare Tunnel as a last resort (traffic via Cloudflare, so note it).
* Protect LLM spend: daily budget in the gateway, and "analyze" endpoints rate-limited per user.

---

## 15. Event logistics: HackNation 2026

**Facts (hacknation.pl, participant guide and FAQ, read 2026-11-21):**

* **When/where**: 21–22 Nov 2026, **onsite only** ("udział jest tylko stacjonarny"), BCTW – Bydgoskie Centrum Targowo-Wystawiennicze, ul. Gdańska 187, Bydgoszcz. Wi-Fi + RJ45 at desks. 15 partner tasks; Risk Miner (MFiPR) main prize 25 000 PLN gross (single prize).
* **Agenda Sat 21.11**: 08:00 registration/breakfast, 10:30 opening, **11:00 full task texts published, coding starts**, 13:00 lunch, 16:00 talk (J. Laskowski), 18:00 pizza, 20:00 quiz.
* **Agenda Sun 22.11**: 07:00 breakfast, **11:00 end of coding, stage-1 judging starts**, 11:30 talk, 13:00 lunch, **14:45 finalists announced** (top 5 per task, also on Discord), **15:15 pitching / stage 2**, 17:15 awards and closing.
* **Total coding time: 24 h** (Sat 11:00 → Sun 11:00).
* **Checkpoint 1 – Sat 21.11, 20:00 (hard)**: in **HackTribe**, create the project, pick the Partner Task (Risk Miner), and fill project name, team name, repository you'll work in, table number, preliminary description. After 20:00 no new projects and no task change.
* **Checkpoint 2 – Sun 22.11, 11:00 (hard, "Termin to termin")**: HackTribe submission window is 21.11 11:00 → 22.11 11:00. Complete all required fields + presentation + materials. You can upload early and keep editing until the deadline. Every member needs a Discord account before submission; the team leader manages members (first name, last name, email).
* **Stage 2 pitch**: finalists present live; preliminary scores don't carry over. The guide recommends a demo of **≤2 min**, since judges have only a few minutes per team.
* **Mentoring**: no fixed slots published. "Strefa Mentorska" onsite + Discord (mentors have a "MENTOR |" prefix). Discord: discord.gg/VtqwHWNnz7 (`#zapytaj-organizatora`). Task text: MFiPR mentors at the challenge stand and on Discord. The mentor page lists MFiPR people from the PPP Department (incl. its director) and the IT-systems department.
* **Teams**: 1–6 people, max 2 tasks per team, one project per category. Pre-existing code/resources are allowed if cited.
* **IP**: winners must sign an economic-copyright transfer to MFiPR (art. 74 ust. 4 and art. 50 fields) within 7 days of receiving it. The prize is paid within 14 days after signing. All co-authors sign.

**Risk Miner submission package** (task text sections 4 and 6):
* Required: **link to the running prototype** (jury tests it themselves), **title + detailed description**, **PDF presentation ≤10 slides**, **code repository**, **video ≤3 min** at an open, accessible link.
* Optional: screenshots, mock-ups or descriptions of unfinished features.
* Also evaluated: short description ≤10 pages (problem, scope, main user scenario, **clear split between working and designed elements**), technical docs (architecture + data model diagram, sources and matching methods, run instructions, **list of models/services/libraries/licences**), **test report** (correct/uncertain/wrong cross-source links; new-project analysis results), repo + config needed to run + **sample structured export**, sample config showing what to set, where data is processed, and the licence (sect. 5).
* Live test scenario to rehearse: import + auto-enrichment of ≥1 project, then a new-investment analysis in the UI with export.

**Suggested internal timeline** (24 h; 3 devs + Claude Code):

| Time | Milestone |
|---|---|
| Sat 11:00–13:00 | Read the task, fix scope, write `CLAUDE.md` (architecture contract), DB schema v1 + Alembic, OpenAPI skeleton, compose skeleton. **Deploy "hello world" to the VM with HTTPS now.** Request Bedrock/Vertex model access |
| 13:00–20:00 | Dev A: seed XLSX + BZP connector + normalise + link. Dev B: parsing → chunks → embeddings → extraction + quote verification. Dev C: SPA shell, Projekty, review queue with viewer. **19:30 HackTribe draft** (buffer before the 20:00 hard stop) |
| 20:00–03:00 | TED/KPO/NIK/BIP connectors, catalogue editor, new-investment analysis, exports, monitoring job, audit/history UI |
| 03:00–07:00 | Full ingestion of the 22 projects on the VM, expert-review a demo subset, generate test report, fix bugs, freeze features at ~07:00 |
| 07:00–10:00 | Record the ≤3 min video, 10-slide PDF, README / technical docs / licence list / config sample, sample export. **Submit complete by ~10:15**, then only polish edits until 11:00 |
| Sun 11:00–15:15 | Prepare the ≤2 min live pitch demo path (and a fallback recording) in case of finals |

Claude Code tips: keep module boundaries strict (connectors / parsing / llm / linking / api / web) so 3 sessions can work in parallel worktrees. Generate the TS client from OpenAPI after each API change. Put the grounding rules and the "AI never overwrites approved data" invariant in `CLAUDE.md`.

---

## 16. Build risks and mitigations

| Risk | Mitigation |
|---|---|
| Cloud model access delays (Bedrock "See Access", Vertex quota 0) | Request both in hour 1. Develop on `anthropic` and switch to the EU profile by config. That switch is itself the "no code change" demo |
| Slow parsing on CPU | pypdfium2 fast path; docling/OCR only where needed; cache by sha256; ingest overnight |
| Hallucinated quotes/numbers | Server-side quote + number verification; unverified items can't be bulk-approved |
| Venue Wi-Fi vs multi-GB images | Build in CI, pull on the VM; pre-download models at build time |
| Demo breaks live | Pre-ingested DB snapshot, a recorded fallback video, a seeded "new document" for the monitoring demo |
| Licence surprises at IP transfer | Auto-generated licence list in CI; banned-list check (§11) |

---

## Sources

Event: [hacknation.pl](https://hacknation.pl/), [Przewodnik uczestnika](https://hacknation.pl/przewodnik-uczestnika), [FAQ](https://hacknation.pl/faq), [Zadania](https://hacknation.pl/zadania), [Mentorzy](https://hacknation.pl/mentorzy), task text and regulations in `materials/text/01_tresc_zadania.txt`, `02_regulamin.txt`.

Claude / clouds: [Claude in Amazon Bedrock (Mantle)](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock), [AWS Bedrock model card – Claude Sonnet 5.5 (EU geo profile routing)](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html), [AWS Bedrock model card – Claude Haiku 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html), [AWS blog – Claude Opus 5.5 on AWS](https://aws.amazon.com/blogs/machine-learning/claude-opus-5-5-is-now-available-on-aws/), [Claude on Google Cloud (Google managed) – endpoints/eu multi-region](https://platform.claude.com/docs/en/build-with-claude/claude-models-on-google-cloud/google-managed), [Vertex user report: Sonnet 5.5 quota 0](https://discuss.google.dev/t/claude-sonnet-5-5-quotas-stuck-at-0-despite-active-billing-manual-access-review-requested/412427), [Claude Citations docs](https://platform.claude.com/docs/en/build-with-claude/citations), [Structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support), [Mistral regional inference](https://docs.mistral.ai/studio/regional-inference), [Mistral custom structured outputs](https://docs.mistral.ai/capabilities/structured-output/custom_structured_output/), [Azure model region availability (Data Zones)](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability), [Azure Data Zones blog](https://azure.microsoft.com/blog/enterprise-trust-in-azure-openai-service-strengthened-with-data-zones), [OVHcloud AI Endpoints catalog](https://www.ovhcloud.com/en-gb/public-cloud/ai-endpoints/catalog/).

LiteLLM incidents: [Snyk – poisoned scanner backdoored LiteLLM (Mar 2026)](https://snyk.io/articles/poisoned-security-scanner-backdooring-litellm), [JFrog – TeamPCP](https://research.jfrog.com/post/litellm-compromised-teampcp/), [OX Security – LiteLLM 1.107.0](https://www.ox.security/blog/litellm-1-107-0-compromised-with-a-rat-infostealer/), [StepSecurity – 1.107.0](https://www.stepsecurity.io/blog/litellm-1-107-0-compromised-pypi-backdoored-wheels-credential-stealer).

Models / NLP: [Bielik 11B v3.0 Instruct (HF)](https://huggingface.co/speakleash/bielik-11b-v3.0-instruct), [Bielik 11B v3.1 on Ollama](https://ollama.com/SpeakLeash/bielik-11b-v3.1-instruct), [PL-MTEB paper (ACL 2026 Findings)](https://aclanthology.org/2026.findings-acl.1773/), [PL-MTEB on HF](https://huggingface.co/PL-MTEB), HF API licence tags for bge-m3, Qwen3-Embedding, mmlw, rerankers, docling models (queried 2026-11-21).

Parsing / licences: [docling GitHub](https://github.com/docling-project/docling), [MinerU / marker licence comparison](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser), [MarkTechPost – PDF-to-JSON models 2026](https://www.marktechpost.com/2026/07/04/structured-pdf-to-json-a-guide-to-open-source-extraction-models-in-2026/), PyPI/npm registry metadata (queried 2026-11-21).

Postgres Polish FTS: [depesz – Polish configuration for TSearch (PG18 hunspell vs PG19 built-in)](https://www.depesz.com/?p=4454), [PostgreSQL 19 released (2026-11-19)](https://postgresql.org/about/news/postgresql-19-released-3449), [Railway PG19+pgvector note](https://railway.com/deploy/postgresql-19-pgvector).

Hosting: [Hetzner price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Northflank – Hetzner 2026 increases](https://northflank.com/blog/hetzner-cloud-server-price-increases), [Procrastinate docs](https://procrastinate.readthedocs.io/).
