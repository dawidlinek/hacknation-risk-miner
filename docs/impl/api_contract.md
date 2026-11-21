# Backend API contract and build plan (ex ante)

Written Sat 21.11.2026 19:20 from `CLAUDE.md`, `docs/PLAN.md` §5–§6, `docs/flow1_build_plan.md`, `design/README.md`, the
mockup scripts in `design/mockups/*.dc.html`, `backend/` and the live DB (`riskminer-db`, read-only queries).
Coding ends Sun 22.11 11:00, feature freeze 07:00. This file is the contract the frontend generates its client from.

**Verdict.** The read side for the case base exists (37 GET endpoints, streamed JSON/CSV exports, full-text search).
Everything the designs add on top is missing: no auth, no write endpoint except `POST /api/jobs`, no analysis, LLM,
analytics, review, catalogue editing, monitoring or import-agent code. `analysis`, `review`, `llm_call`, `risk_signal`,
`gold_example`, `monitor_watch` are empty. The plan below is contract first: at 20:45 every endpoint in §2 exists as a
typed stub serving mockup-shaped fixtures, so the frontend never waits; sessions then replace fixtures with real code.

---

## 1. What exists today

### 1.1 Endpoints (`backend/riskminer/api`, FastAPI, no auth, CORS from config)

| Router | Method + path | Purpose |
|---|---|---|
| main | `GET /api/health`, `GET /api/config/features` | liveness (+ notice count), feature flags from `config.yaml` |
| data | `GET /api/stats` | `count(*)` of 21 tables, notices by type/channel, pilot linking, sources, last runs |
| data | `GET /api/sources/summary`, `GET /api/sources`, `GET /api/sources/{id}` | fetched artefacts (manifest rows) per source |
| data | `GET /api/projects` (q, province, subsector, pilot), `GET /api/projects/{rm_id}`, `GET /api/projects/{rm_id}/timeline` | 22 pilot projects; detail = org, links, candidates, procedure chains, review items, source checks, documents, risk events |
| data | `GET /api/procedures`, `GET /api/procedures/{ocid}` | 101 016 procedures; detail with lots, contracts, notices, timeline |
| data | `GET /api/notices`, `GET /api/notices/{object_id}`, `GET /api/notices/{object_id}/html` | BZP notices, parsed fields by code, official HTML |
| data | `GET /api/contracts`, `GET /api/contracts/{id}`, `GET /api/changes`, `GET /api/performance` | contracts with performance and changes |
| data | `GET /api/organizations`, `GET /api/organizations/{nip}` | buyers and contractors |
| data | `GET /api/runs`, `GET /api/link-candidates`, `GET /api/review-items`, `GET /api/evidence`, `GET /api/external-records[/{id}]`, `GET /api/source-checks`, `GET /api/documents`, `GET /api/risk-events` | run log, linking, review queue (read), evidence per claim, other sources, documents, events |
| data | `GET /api/catalogue/{table}` (risk, subsector, cpv_map, doc_type, checklist, clause, entry) | raw catalogue rows |
| search | `GET /api/search`, `GET /api/documents/{id}/pages`, `GET /api/documents/{id}/pages/{page_no}` | tsvector search over 182k chunks with `<mark>` snippets; page text |
| exports | `GET /api/export`, `GET /api/export/{dataset}.{json\|csv}` | 15 streamed datasets (projects, procedures, contracts, performance, changes, notices, organizations, link_candidates, review_items, sources, runs, external_records, source_checks, risk_events, documents) |
| jobs | `GET /api/jobs`, `POST /api/jobs`, `GET /api/jobs/{id}` | job queue (SKIP LOCKED worker) |

### 1.2 Schemas (`api/schemas.py`)
`Money {amount: Decimal (JSON string), currency, vat_basis}`, `Provenance {source_id, origin SOURCE|CALC|AI, review_status}`,
`Page[T] {total, limit, offset, items}`, and `*Out` models for organization, project (+detail), lot, performance, change,
contract, notice (+detail), procedure (+detail, timeline), link candidate, review item, source (+summary), run, job,
external record, source check, evidence, document, risk event, stats. Search has its own models in `routers/search.py`.
There is no `n`, no method, no `case` role and no unified number type yet.

### 1.3 Tables (live row counts, 19:10)

| Table | Rows | Note |
|---|---:|---|
| notice | 248 435 | BZP copy + live |
| procedure | 101 016 | relevance: core 19 053, component 16 727, none 65 194 |
| contract / lot / offer | 128 051 / 112 733 / 0 | |
| contract_change | 60 293 | 46 025 with keyword cause codes |
| contract_performance | 68 755 | |
| rc_contract (materialised view) | 67 562 | core wod-kan completed: **11 574**, 29,8% late |
| risk_event | 126 134 | all `CALC`/`auto` (11 event types); **0 AI proposals** |
| evidence | 861 467 | field-code and page evidence |
| document / document_page / chunk | 11 061 / 49 308 / 182 381 | `chunk.embedding` empty |
| external_record / source_check / source | 354 791 / 892 / 45 097 | |
| organization | 18 641 | `teryt` filled for **0** rows |
| project / project_procedure | 22 / 22 | 22/22 linked |
| link_candidate | 3 589 | auto-accept 1 324, review 1 234, reject 1 031 |
| review_item | 6 | all `discrepancy`, open |
| catalogue_risk / clause / checklist / doc_type / cpv_map / subsector / entry | 53 / 29 / 9 / 28 / 58 / 6 / 55 | clause codes like `R08.1-K1`; entry = red flags, event types, evidence states, similarity, lexicon |
| ref_teryt | 4 360 | woj 16, pow 380, gmi 2 479, part 1 485 |
| audit_log | 45 | 14 of them `actor='test'` (written by `test_pipeline.py`) |
| ingestion_run / job | 188 / 1 | |
| analysis, analysis_item, review, gold_example, llm_call, risk_signal, monitor_watch, alert, fetch_queue | 0 | tables exist, no code writes them |

Reference data on disk: `data/ref/geo/{woj,pow,gmi}.geojson` (properties `terc`, `name`, `level`), `teryt_terc.csv`,
`price_index_construction.csv`, `pilot_projects.json`. `procedure.province` is `PL` + TERYT woj code (`PL12` = małopolskie).

### 1.4 Jobs (`jobs/worker.py`)
Kinds: `scrape:<source>`, `load:<source>`, `import_xlsx`, `import_bzp_copy`, `derive_bzp`, `derive_events`, `doc_text`,
`link_pilot`, `link_national`, `seed_catalogue`, `load_all`, `report`, `noop`. Dispatch is an `if` chain in one function.

### 1.5 Auth, triggers, config
- **Auth: none.** `config.example.yaml` names `api.basic_auth_env: RISKMINER_BASIC_AUTH` but nothing reads it; no Caddyfile in `infra/`.
- `rm_protect_approved` (15 tables incl. `analysis_item`, `risk_event`, `project_procedure`): on UPDATE of an approved/edited row without `riskminer.expert_write = 'on'` it **silently returns OLD**; DELETE raises. Not on `link_candidate`, `review_item`, `catalogue_*`, `analysis`.
- `rm_audit_log_append_only`: UPDATE/DELETE on `audit_log` raise.
- Packages: `python-multipart` and `itsdangerous` are **not** in `uv.lock` (needed for uploads and session cookies). `soffice` and `pdftotext` are installed on the dev box.

### 1.6 Traps found while reading
1. `/api/export/*` serves review items, runs, sources and link candidates to anyone. Gate them (§5).
2. `/api/search` and `/api/documents` have no `sensitivity` filter: a confidential upload would be searchable publicly. Add `d.sensitivity = 'public'` for anonymous callers before uploads go live.
3. Because the trigger returns OLD silently, any write endpoint must check `RETURNING review_status` and answer 409 when the row did not change; otherwise the UI shows "zapisano" for a write that never happened.
4. Existing tests mutate the main DB (`test_audit_log_append_only` inserts permanent audit rows; `test_approved_rows_protected` flips `RM-2026-001`; `test_link_national` reruns a stage). New tests must not (§8).
5. Mockup numbers are research numbers, the DB has moved on: core wod-kan completed is 11 574 (design 11 184); the demo class SAN + 5–10 mln + ZiW is n = 82 (design 84), 63,4% late, P(≤ 14 mies.) = 15% (design "36%" was demo-only). The UI must render API values only.
6. The 37-item review queue in the design needs AI proposals that do not exist yet (risk_event AI = 0). The change-cause classification batch (session L) is on the critical path for Flow 3.
7. Gmina/powiat map levels need buyer TERYT codes; `organization.teryt` is empty.

---

## 2. The API contract

### 2.0 Conventions (apply to every new endpoint)

- Base `/api`, JSON, snake_case. Lists return `Page[T]`. Errors: `{"detail": "<Polish message>", "code": "<machine_code>"}` with 400/401/403/404/409/422/429/503.
- **Access**: `public` = anyone; `owner` = the anonymous session or user that created the analysis/question, plus any logged-in user for non-confidential records, plus admin; `login` = role expert or admin; `admin` = admin.
- **Public mode rule**: for anonymous callers every AI item with `review_status` not in (`approved`, `edited`) is dropped and replaced by a count `unverified_hidden: n` (design: "niezweryfikowane").
- **Fixtures**: until an endpoint is real it returns its fixture with header `X-Fixture: true`; contract tests fail on that header after 07:00 for flagged-on features.
- Writes need header `X-Requested-With: ex-ante` (CSRF guard with SameSite=Lax cookies) and accept `X-Request-ID` (stored in `audit_log.request_id`).
- Money stays the value object; `amount` is a decimal string. BZP estimates are net, contract values, payments and the user budget are gross.

**Common types** (new file `api/prov.py`, owned by the lead, frozen after 20:45):

```ts
Ref   = { kind: "notice"|"document"|"query"|"project"|"procedure"|"contract"|"catalogue"|"llm_call"|"source"|"input_text"|"file",
          id: string, label: string, url?: string, page_no?: int, field_code?: string, quote?: string,
          verification?: "exact"|"fuzzy"|"unverified"|"structured_field", retrieved_at?: datetime }
Prov  = { role: "source"|"calc"|"case"|"ai", review_status: "auto"|"proposed"|"approved"|"edited"|"rejected",
          n?: int, method?: string, refs: Ref[], ci90?: [number, number], insufficient?: bool, assumption?: bool,
          llm?: { provider, model, data_location, llm_call_id } }
Num   = { value: number|null, display: string, unit: "days"|"months"|"pct"|"share"|"pln"|"mln_pln_per_km"|"count"|"offers"|"score",
          prov: Prov }
Range = { unit, axis: [lo, hi], p10?, p25?, p50, p75?, p80?, p90?, you?: number, marker?: {x, label}, n: int, plain: string }
Answer = { id, code: string|null, role: "calc"|"ai"|"no_data", role_label: "obliczenie"|"wniosek AI"|"brak danych", text,
           bars: {label, value, display, highlight}[], numbers: Num[], method: {kind: "sql"|"template"|"llm", sql?, view?, template?},
           sources: Ref[], n: int|null, missing: string[], actions: {kind, label, href?}[], apply?: object,
           processing: {provider, model, data_location}|null }
```

**Provenance rules** (tested, §8):
1. Every metric in a new response is a `Num` (or `Range`/`Money` inside an object that carries `prov`). Bare numbers are allowed only for ids, ranks, page numbers, offsets, versions, pagination and chart point coordinates inside a series that has its own `prov`.
2. `role` maps from DB `origin`: SOURCE → `source`, CALC → `calc`, AI → `ai`. The API sets `case` when the value is a fact of another project/procedure shown as evidence (a similar case's delay), keeping the underlying refs.
3. `calc` requires `n` and `method` (`rc_quantiles`, `bootstrap_ci90`, `monte_carlo`, `sql`, `template:<name>` ...) and a `query` ref describing the filter. If `n < analytics.insufficient_n` (10) then `value = null`, `insufficient = true`, `display = "za mało danych"`.
4. `source` requires at least one ref with a notice number + field code, a document + page, or a URL with `retrieved_at`.
5. `ai` requires `llm` and a `review_status`; quotes carry `verification`. Numbers extracted by AI are accepted only if the number verifier finds them in the quoted text.
6. Expert assumptions (mitigation multipliers, allocation premiums, programme end dates) are `role: "source"` with a `catalogue` ref and `assumption: true`; the UI labels them "założenie eksperta".

Reusable payloads:
- `SimilarCase = {rank, score: Num, rm_id|null, ocid, title, why, contributions: [{feature, label, value}], outcome: {delay_days: Num, cost_dev_pct: Num}, href}`
- `Signal = {contract_id, ocid, bzp_number, lot_no, n_parts, buyer_name, title, value: Money, signed_on, planned_end_on, days_overdue: Num, n_change_notices, has_performance: false, woj, pow, gmi, lon, lat, location_method, watched}`

### 2.1 Auth and meta

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `POST /api/auth/login` | `{username, password}` | `{user: {name: "ekspert", role: "expert"}}` + `Set-Cookie: rm_session` | env users | NEW | public | none |
| `POST /api/auth/logout` | none | `204` | | NEW | login | none |
| `GET /api/auth/me` | none | `{user: {name, role}\|null, anon_id: "a7f3c2d1"}` | | NEW | public | none |
| `GET /api/nav/counts` | none | `{review_open: 37, monitoring_new: 12}` | review_item, v_monitor_signal | NEW | login | counts only (badges) |
| `GET /api/health`, `GET /api/config/features` | | as today | | EXISTS | public | |

### 2.2 Pulpit (`/`, Main)

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `GET /api/dashboard` | none | J0 | review_item, v_monitor_signal, analysis, source, ingestion_run, rc_contract | NEW | login | each tile value is `Num` calc with `n` = rows counted; headline numbers calc over rc_contract |
| `GET /api/national/headline` | `?sector=wod-kan` | `{sentence, completed: Num, late_share: Num, delay_days_total: Num, overpaid: {money: Money, prov}, ongoing_overdue_90: Num, as_of}` | rc_contract, v_monitor_signal | NEW | public | calc, n = 11 574; sentence `template:headline_v1` |
| `GET /api/sources/summary` | none | today's `SourceSummaryOut` + `label`, `what`, `state: ok\|pending\|blocked` | source, ingestion_run | EXTEND | public | source rows |
| `GET /api/review-items?kind=discrepancy&limit=4` | | `Page[ReviewItemOut]` | review_item | EXISTS | login | source refs in `detail` |
| `GET /api/ask/suggestions` | `?context=pulpit\|zapytaj\|analysis\|project` | `[{key: "zw", label: "Zaprojektuj i wybuduj a samo wykonanie"}]` | static intents | NEW | public | none |
| `POST /api/ask` | see 2.3 (1.6) | `Answer` | | NEW | public, rate-limited | see 1.6 |

J0 `GET /api/dashboard`:
```json
{"tiles": [
  {"key": "review_open", "label": "Czeka na Twoją decyzję", "value": {"value": 37, "display": "37", "unit": "count",
   "prov": {"role": "calc", "review_status": "auto", "n": 37, "method": "count", "refs": [{"kind": "query", "id": "review_item:open", "label": "kolejka"}]}},
   "sub": "16 zdarzeń, 12 powiązań, 3 rozbieżności", "href": "/przeglad", "attention": true},
  {"key": "monitoring_new", "label": "Nowe sygnały w monitoringu", "value": {"value": 12, "display": "12", "unit": "count", "prov": {"...": "..."}}, "href": "/monitoring", "attention": true},
  {"key": "my_analyses", "label": "Twoje analizy", "value": {"value": 2, "display": "2", "unit": "count", "prov": {"...": "..."}},
   "sub": "AN-2026-0014 szkic, AN-2026-0011 gotowa", "href": "/analizy", "attention": false}],
 "sources": [{"kind": "bzp_copy", "label": "BZP: kopia ogłoszeń", "what": "ogłoszenia o zamówieniu, wyniku, zmianie i wykonaniu umowy",
              "count_label": "248 435 ogłoszeń", "last_retrieved_at": "2026-11-12T00:00:00Z", "state": "ok"}],
 "issues": [{"id": 7, "rm_id": "RM-2026-007", "code": "value_deviation",
             "title": "Wartość przedsięwzięcia 3 096 863,90 zł odbiega od kwot z BZP (najbliższa: suma wartości umów 1 478 460,00 zł, -52,3%)"}]}
```

### 2.3 Flow 1: Nowa inwestycja (1.1–1.6, public)

| Screen | Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|---|
| 1.1 | `POST /api/documents/upload` | multipart `file`, `sensitivity=confidential\|public` (default confidential), `analysis_code?`, `project_rm_id?` (login only) | `{document_id: 11062, filename, sha256, pages: 38, doc_type: {code: "PFU", confidence: 0.9, method: "filename+keywords"}, sensitivity, text_status: "ok"\|"needs_ocr", processing: {data_location}}` | source (kind `upload`), document, document_page, chunk, audit_log; bytes in `data/raw/upload/` + `manifest.jsonl` | NEW | public | document row origin SOURCE, `source_id` with sha256 |
| 1.1 | `POST /api/analyses` | `{title?, input_text, document_ids: [], sensitivity}` | J1 (chips) | analysis, analysis_version, analysis_item(section `feature`), llm_call, audit_log | NEW | public (creates owner) | chip from regex on user text: calc, method `regex`; from LLM: ai proposed + verified quote and page |
| 1.1 | `PATCH /api/analyses/{code}/features` | `{features: {length_km: 6.2, design_build: true}, answers: {connections: 120}}` | J1 with `version+1`, `stale_sections: ["report"]` | analysis_item (owner edit → `edited`), analysis_version, audit_log | NEW | owner | corrected chip: `review_status: "edited"`, ref `input_text:user` |
| 1.1 | `GET /api/catalogue/funding-programmes` | `?active=true` | `[{code: "FENIKS", name, end_date, prov}]` | catalogue_entry (`funding_programme`) | NEW | public | source, `assumption: true` |
| 1.2 | `POST /api/analyses/{code}/run` | `{}` | `{code, version: 2, status: "ready", sections: {report: "done", redpen: "queued"}, redpen_job_id: 812}` | analysis_version, analysis_item, job | NEW | owner | |
| 1.2 | `GET /api/analyses/{code}` | `?version=` | J2 (report) | analysis, analysis_version, analysis_item, rc_contract, project, catalogue_* | NEW | owner | every number `Num`/`Range` (calc n, case refs, ai llm) |
| 1.2 | `GET /api/analyses` | `?mine=true&status=&limit=&offset=` | `Page[{code, title, version, status, sensitivity, updated_at}]` | analysis | NEW | owner (own), admin (all) | none |
| 1.2 | `GET /api/analyses/{code}/versions` | none | `[{version, created_at, created_by, reason, catalogue_version, data_as_of}]` | analysis_version | NEW | owner | |
| 1.2 | `GET /api/analyses/{code}/reference-class/contracts` | `?step=final&limit=&offset=` | `Page[{ocid, title, buyer_name, province, value_gross: Money, planned_days, actual_days, delay_days, cost_dev_pct, notice_number}]` | rc_contract, notice | NEW | owner | rows are source/calc; one ref per notice |
| 1.2 | `POST /api/analyses/{code}/chat` | `{message, context: "report"\|"simulation"\|"redpen"}` | `Answer` (+ `apply: {metric, whatif}` for what-ifs) | question, llm_call | NEW | owner | numbers come from the analysis record (calc refs to its items); text role `ai` |
| 1.3 | `GET /api/analyses/{code}/redpen/{document_id}` | none | J3 | document_page, analysis_item(`redpen_note`, `missing`), catalogue_clause, risk_event of similar cases | NEW | owner | notes ai + quote `verification`; missing items calc (rule id) + `evidence_state` |
| 1.3 | `GET /api/documents/{id}/file` | none | the original bytes (`application/pdf`) | document, source | NEW | owner for confidential, public otherwise | |
| 1.3 | `POST /api/analyses/{code}/items/{item_id}/decision` | `{action: "approve"\|"edit"\|"reject", value?, reason?, add_clause?: "R08.1-K1"}` | `{item_id, review_status, in_pack: true}` | analysis_item, review, audit_log | NEW | owner | owner decision on own analysis, not expert review |
| 1.4 | `POST /api/analyses/{code}/simulate` | `{metric: "time"\|"cost"\|"competition", toggles: ["geo","plan18","k07","r08"], whatif: {tender_delay_months: 2, single_offer: false, price_shock_pct: 10}, draws: 10000, save: false}` | J4 | rc_contract, contract_change, lot, catalogue_entry (`mitigation`), analysis_item(`simulation` when save) | NEW | owner | series calc (n, draws, seed); toggles `assumption: true`; tornado calc |
| 1.5 | `GET /api/analyses/{code}/allocation` | none | J5 | analysis_item(`allocation`), catalogue_entry (`allocation`), simulation output | NEW | owner | expected cost calc (p × impact × budget, n); positions and premiums assumption; warnings case |
| 1.5 | `PUT /api/analyses/{code}/allocation` | `{choices: {R02: "buyer", R04: "shared", R08: "shared"}}` | J5 recomputed, `version+1` | analysis_item, analysis_version, audit_log | NEW | owner | as above |
| 1.5 | `GET /api/analyses/{code}/pack` | none | `{items: [{key: "risk_register", label: "Rejestr ryzyk", count_label: "6 ryzyk"}], excluded: [{item_id, reason: "wniosek AI niezatwierdzony"}], formats: ["docx","pdf","csv","json"]}` | analysis_item | NEW | owner | |
| 1.5 | `GET /api/analyses/{code}/pack.{docx\|pdf\|csv\|json}` | `?version=` | file | analysis_version, analysis_item | NEW | owner | annex lists every ref with URL/page/sha256 |
| 1.6 | `POST /api/ask` | `{question, scope?: {rm_id?, analysis_code?, terc?}}` | `Answer` (`id` = draft question id) | question, llm_call, ask views | NEW | public (10/min per anon id + IP) | calc when SQL ran (n = result rows aggregated, `method.sql` shown); ai for explanations over approved events; `no_data` names the missing source |
| 1.6 | `POST /api/questions` | `{question_id, title?}` | `{code: "Q-2026-0004", title, saved_at}` | question, audit_log | NEW | public (owner) | snapshot of the answer incl. SQL and rows |
| 1.6 | `GET /api/questions` | `?mine=true` | `Page[{code, title, saved_at, role, n}]` | question | NEW | public (own + expert-saved) | |
| 1.6 | `GET /api/questions/{code}`, `POST /api/questions/{code}/rerun`, `GET /api/questions/{code}/rows.{csv\|json}` | | `Answer` / new version / rows | question, ask views | NEW | public (owner) | rerun keeps the old snapshot, returns both |

J1 `POST /api/analyses` (values from the demo PFU are illustrative until the real PFU is chosen):
```json
{"code": "AN-2026-0014", "version": 1, "status": "draft", "sensitivity": "public",
 "documents": [{"id": 11062, "filename": "PFU_kanalizacja.pdf", "doc_type": "PFU", "pages": 38, "sensitivity": "public"}],
 "features": [
  {"key": "subsector_main", "label": "podsektor", "value": "SAN", "display": "kanalizacja sanitarna", "unsure": false,
   "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "input_text", "id": "opis", "label": "opis"}],
            "llm": {"provider": "gemini", "model": "gemini-3.8-flash", "data_location": "global (Gemini Developer API)", "llm_call_id": 17}}},
  {"key": "design_build", "label": "formuła", "value": true, "display": "zaprojektuj i wybuduj", "unsure": false,
   "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "document", "id": "11062", "label": "PFU s. 2", "page_no": 2,
            "quote": "w formule zaprojektuj i wybuduj", "verification": "exact"}]}},
  {"key": "length_km", "label": "długość", "value": 6.0, "display": "ok. 6 km?", "unsure": true,
   "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "document", "id": "11062", "label": "PFU s. 6", "page_no": 6,
            "quote": "ok. 6 km, ostateczna długość wynikać będzie z dokumentacji projektowej", "verification": "exact"}]}},
  {"key": "budget", "label": "budżet", "value": {"amount": "7000000.00", "currency": "PLN", "vat_basis": "gross"}, "display": "7 mln zł brutto",
   "unsure": false, "prov": {"role": "calc", "review_status": "auto", "method": "regex:money", "refs": [{"kind": "input_text", "id": "opis", "label": "opis"}]}},
  {"key": "planned_months", "label": "termin", "value": 14, "display": "14 mies.", "unsure": false, "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "document", "id": "11063", "label": "PPU §3", "page_no": 2}]}},
  {"key": "funding_programme", "label": "finansowanie", "value": "FENIKS", "display": "FEnIKS", "unsure": false, "prov": {"role": "calc", "review_status": "auto", "method": "regex:programme", "refs": [{"kind": "input_text", "id": "opis", "label": "opis"}]}}],
 "questions": [{"key": "connections", "text": "Ile będzie przyłączy?", "why": "zakres i ilości liczą się do podobieństwa", "input": "count"}],
 "funding_programmes": [{"code": "FENIKS", "name": "FEnIKS 2021–2027", "end_date": "2029-12-31",
   "prov": {"role": "source", "review_status": "approved", "assumption": true, "refs": [{"kind": "catalogue", "id": "funding_programme:FENIKS", "label": "Katalog v1.3"}]}}]}
```
Feature keys follow `catalogue/wod-kan/similarity.yaml`: `subsector_main, subsectors_all, works_type, design_build, budget, length_km, pumping_stations, connections, tech_tags, planned_months, funding_programme, province`.

J2 `GET /api/analyses/{code}` (numbers are real DB values for SAN + 5–10 mln + ZiW unless the line says otherwise):
```json
{"code": "AN-2026-0014", "version": 2, "status": "ready", "catalogue_version": "v1.3", "data_as_of": "2026-11-21T18:40:00Z",
 "features": ["...J1 features..."],
 "summary": {"sentence": "Raczej nie zdążysz w 14 miesięcy: tak krótko trwało 15% podobnych umów. Budżet na kilometr jest typowy.",
             "prov": {"role": "calc", "review_status": "auto", "n": 79, "method": "template:summary_v1", "refs": [{"kind": "query", "id": "rc:SAN|5-10m|db", "label": "klasa: kanalizacja sanitarna, 5–10 mln zł, ZiW"}]}},
 "reference_class": {"funnel": [
    {"label": "wszystkie wykonane umowy wod-kan", "filter": {"sector": "wod-kan", "relevance": "core"}, "n": 11574},
    {"label": "kanalizacja sanitarna", "filter": {"subsector_main": "SAN"}, "n": 4339},
    {"label": "wartość 5–10 mln zł", "filter": {"value_bucket": "5-10m"}, "n": 374},
    {"label": "zaprojektuj i wybuduj", "filter": {"design_build": true}, "n": 82}],
   "final": {"n": 82, "widened": false, "min_n": {"share": 30, "tail": 50}}},
 "questions": [
  {"key": "on_time", "question": "Czy zdążysz w 14 miesięcy?", "answer": "Nie", "answer_step": 0,
   "key_number": {"value": 0.15, "display": "15% szans", "unit": "share",
                  "prov": {"role": "calc", "review_status": "auto", "n": 79, "method": "rc_share+bootstrap_ci90", "ci90": [0.08, 0.22], "refs": [{"kind": "query", "id": "rc:SAN|5-10m|db", "label": "82 umowy z BZP"}]}},
   "range": {"unit": "months", "axis": [6, 36], "p10": 10.0, "p50": 20.3, "p80": 26.7, "p90": 30.9, "you": 14, "n": 79,
             "plain": "8 na 10 podobnych umów trwało do 26,7 miesiąca"}, "href": "/analizy/AN-2026-0014/symulacja"},
  {"key": "unit_cost", "question": "Czy 7 mln zł wystarczy?", "answer": "Tak", "answer_step": 3,
   "key_number": {"value": 1.17, "display": "1,17 mln zł/km", "unit": "mln_pln_per_km",
                  "prov": {"role": "calc", "review_status": "auto", "n": 1734, "method": "unit_cost_percentile", "refs": [{"kind": "query", "id": "rc:SAN|length_km", "label": "umowy z długością sieci"}]}},
   "range": {"unit": "mln_pln_per_km", "axis": [0, 2], "p25": 0.54, "p50": 0.89, "p75": 1.48, "you": 1.17, "n": 1734, "plain": "64. percentyl"}},
  {"key": "programme_end", "question": "Czy zdążysz przed końcem programu?", "answer": "Raczej tak", "answer_step": 2,
   "key_number": {"value": 0.72, "display": "72% szans", "unit": "share", "prov": {"role": "calc", "review_status": "auto", "n": 79, "method": "rc_quantiles+programme_end", "refs": [{"kind": "catalogue", "id": "funding_programme:FENIKS", "label": "koniec programu"}]}},
   "range": {"unit": "months", "axis": [6, 36], "p10": 10.0, "p50": 20.3, "p80": 26.7, "p90": 30.9, "you": 20.3, "marker": {"x": 38, "label": "koniec programu"}, "n": 79, "plain": "..."}}],
 "flags": [
  {"id": 5531, "kind": "calc", "rule": "term_shorter_than_class", "title": "Termin krótszy niż typowy",
   "text": "14 mies. wobec mediany 18,0 mies. planowanych terminów w tej klasie.", "risk_codes": ["R06"],
   "number": {"value": 18.0, "display": "18,0 mies.", "unit": "months", "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "rc_median(planned_days)", "refs": [{"kind": "query", "id": "rc:SAN|5-10m|db", "label": "82 umowy"}]}}},
  {"id": 5532, "kind": "ai", "title": "W PPU brak klauzuli waloryzacyjnej", "text": "Roboty trwają dłużej niż 6 mies. (art. 439 Pzp), a dokument o tym nie wspomina.",
   "risk_codes": ["R08"], "evidence_state": "DOKUMENT_NIE_WSPOMINA", "review_status": "proposed",
   "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "document", "id": "11063", "label": "PPU (22 s.)"}], "llm": {"provider": "gemini", "model": "gemini-3.8-flash", "data_location": "global (Gemini Developer API)", "llm_call_id": 21}}}],
 "similar_cases": [
  {"rank": 1, "score": {"value": 0.82, "display": "0,82", "unit": "score", "prov": {"role": "calc", "review_status": "auto", "method": "similarity_v1", "refs": [{"kind": "catalogue", "id": "similarity:default", "label": "wagi v1.3"}]}},
   "rm_id": "RM-2026-017", "ocid": "ocds-148610-...", "title": "Budowa sieci kanalizacji sanitarnej wraz z przyłączami w miejscowości Tanibórz, Gmina Kleszczewo",
   "why": "ten sam podsektor, przepompownie, podobna wartość",
   "contributions": [{"feature": "subsector_main", "label": "podsektor", "value": 0.26}, {"feature": "design_build", "label": "formuła ZiW", "value": 0.0},
                     {"feature": "length_km", "label": "zakres i ilości", "value": 0.22}, {"feature": "budget", "label": "wartość", "value": 0.16}, {"feature": "text", "label": "opis (tekst)", "value": 0.18}],
   "outcome": {"delay_days": {"value": 53, "display": "+53 dni", "unit": "days", "prov": {"role": "case", "review_status": "auto", "refs": [{"kind": "project", "id": "RM-2026-017", "label": "Tanibórz"}, {"kind": "notice", "id": "<performance notice no.>", "label": "ogł. o wykonaniu", "field_code": "5.2"}]}},
               "cost_dev_pct": {"value": 26.8, "display": "+26,8%", "unit": "pct", "prov": {"role": "case", "review_status": "auto", "refs": ["..."]}}},
   "href": "/projekty/RM-2026-017"}],
 "clauses": [{"code": "R08.1-K1", "title": "Waloryzacja (art. 439)", "why": "77% podobnych umów miało co najmniej jedną zmianę.", "risk_codes": ["R08"],
              "evidence_cases": ["RM-2026-003"], "number": {"value": 0.77, "display": "77%", "unit": "share", "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "rc_share(changes_count>0)", "refs": ["..."]}}}],
 "limitations": ["Ryzyka liczone niezależnie, bez korelacji między nimi.", "Koszt kilometra w cenach nominalnych (bez indeksacji GUS).", "Brak SWZ i kosztorysu w paczce."],
 "processing": [{"task": "features", "provider": "gemini", "data_location": "global (Gemini Developer API)"}],
 "unverified_hidden": 0}
```
Unit cost uses the research numbers (n 1 734, P25/P50/P75 0,54/0,89/1,48 mln zł/km, `05_bzp_corpus_stats.md`) until `rc_contract.length_km` lands; the programme-end question (72%, marker at 38 months), the AI flag and the similarity split are illustrative until the engine and `funding_programmes.yaml` exist.

J3 `GET /api/analyses/{code}/redpen/{document_id}`:
```json
{"document": {"id": 11062, "filename": "PFU_kanalizacja.pdf", "doc_type": "PFU", "pages": 38, "sensitivity": "public", "file_url": "/api/documents/11062/file"},
 "pages": [{"page_no": 6, "chars": 3120, "text": "..."}],
 "notes": [{"item_id": 901, "n": "3", "kind": "found", "title": "Ryczałt przy „ok. 6 km” sieci", "text": "Długość ustali dopiero projekt wykonawcy.",
            "risk_codes": ["R08"], "page_no": 6, "char_start": 1840, "char_end": 1912, "clause_ref": "pkt 1.1",
            "quote": "ok. 6 km, ostateczna długość wynikać będzie z dokumentacji projektowej", "verification": "exact",
            "review_status": "proposed", "suggested_clause": "R01.2-K1", "prov": {"role": "ai", "review_status": "proposed", "refs": ["..."], "llm": {"...": "..."}}}],
 "missing": [{"item_id": 905, "n": "A", "kind": "missing", "title": "Brak: klauzula waloryzacyjna w PPU", "rule": "art_439_indexation",
              "evidence_state": "DOKUMENT_NIE_WSPOMINA", "state_label": "dokument nie wspomina", "limits": "Nie ocenimy podziału ryzyka cen materiałów.",
              "suggested_clause": "R08.1-K1", "prov": {"role": "calc", "review_status": "auto", "method": "rule:art_439", "refs": [{"kind": "catalogue", "id": "red_flag:F5", "label": "Katalog"}]}},
             {"item_id": 906, "n": "B", "kind": "missing", "title": "Brak: dokumentacja geotechniczna", "evidence_state": "BRAK_W_PACZCE", "state_label": "nie ma w paczce", "limits": "Ogranicza ocenę ryzyka R02."}],
 "case_hints": [{"risk_code": "R02", "text": "W 2 z 4 podobnych przypadków grunt zbadano dopiero po umowie.", "cases": ["RM-2026-020", "RM-2026-003"],
                 "number": {"value": 2, "display": "2 z 4", "unit": "count", "prov": {"role": "case", "review_status": "approved", "n": 4, "refs": ["..."]}}}],
 "status": "done"}
```
`status: "queued"|"running"` while the LLM scan job runs; confidential documents with no sovereign model answer `503 {"code": "sovereign_unavailable", "detail": "Model w Polsce jest niedostępny, dokument czeka w kolejce."}`.

J4 `POST /api/analyses/{code}/simulate`:
```json
{"metric": "time", "axis": {"x_label": "miesiące od podpisania umowy", "y_label": "odsetek ukończonych umów", "unit": "months", "domain": [6, 36]},
 "series": [
  {"key": "baseline", "label": "Teraz", "points": [[10.0, 0.1], [14, 0.15], [20.3, 0.5], [26.7, 0.8], [30.9, 0.9]],
   "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "monte_carlo", "refs": [{"kind": "query", "id": "rc:SAN|5-10m|db", "label": "82 umowy"}]}, "draws": 10000, "seed": 1914},
  {"key": "geo", "label": "Badania gruntu", "points": [[9.4, 0.1], [14, 0.19]], "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "monte_carlo+mitigation:geo", "refs": [{"kind": "catalogue", "id": "mitigation:geo", "label": "założenie eksperta"}]}},
  {"key": "combined", "label": "Razem", "points": ["..."], "prov": {"...": "..."}}],
 "markers": [{"key": "plan", "x": 14, "label": "Twój plan"}, {"key": "programme_end", "x": 38, "label": "koniec programu", "prov": {"role": "source", "review_status": "approved", "assumption": true, "refs": [{"kind": "catalogue", "id": "funding_programme:FENIKS", "label": "Katalog"}]}}],
 "kpis": [{"key": "p_on_time", "label": "W terminie z planu", "value": {"value": 0.15, "display": "15%", "unit": "share", "prov": {"...": "..."}}, "delta_pp": 4}],
 "tornado": [{"risk_code": "R06", "label": "R06 harmonogram", "value": {"value": 34, "display": "+34 d", "unit": "days", "prov": {"role": "calc", "review_status": "auto", "n": 310, "method": "mc_contribution(P80-P50)", "refs": ["changes classified R06 in class"]}}}],
 "toggles": [{"key": "geo", "label": "Badania gruntu przed przetargiem", "description": "Dokumentacja geotechniczna jako załącznik do SWZ.", "risk_codes": ["R02"],
              "checked": true, "affects_metric": true, "effect_text": "R02, krzywa w lewo",
              "prov": {"role": "source", "review_status": "approved", "assumption": true, "refs": [{"kind": "catalogue", "id": "mitigation:geo", "label": "założenie eksperta"}]}}],
 "summary": {"sentence": "Teraz skończysz w terminie z planu w 15% przypadków. Z zaznaczonymi zmianami: 19%.", "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "template:sim_summary_v1", "refs": []}}}
```
Only the baseline curve uses real class quantiles; the toggle line, KPI delta and tornado values are illustrative. Competition (`metric: "competition"`) reads `lot.n_offers` for the class and year; cost uses `rc_contract.cost_dev_pct` and changes classified by risk code. Same seed + same inputs + same catalogue version = identical output.

J5 `GET /api/analyses/{code}/allocation`:
```json
{"risks": [{"code": "R02", "title": "Nierozpoznany grunt",
   "impact": {"value": 28, "display": "P80 +28 dni", "unit": "days", "prov": {"role": "calc", "review_status": "auto", "n": 64, "method": "mc_risk_p80", "refs": ["..."]}},
   "expected_cost": {"money": {"amount": "210000.00", "currency": "PLN", "vat_basis": "gross"}, "prov": {"role": "calc", "review_status": "auto", "n": 82, "method": "p(r)*impact*budget", "refs": ["..."]}},
   "controllability": "buyer", "recommended": "buyer", "chosen": "buyer",
   "positions": [{"key": "buyer", "label": "Zamawiający", "how": "badania geotechniczne przed ogłoszeniem; reszta wg protokołu konieczności"},
                 {"key": "shared", "label": "Wspólnie", "how": "..."}, {"key": "contractor", "label": "Wykonawca", "how": "..."}],
   "premium_factor": {"shared": 0.1, "contractor": 0.6, "prov": {"role": "source", "review_status": "approved", "assumption": true, "refs": [{"kind": "catalogue", "id": "allocation:R02", "label": "założenie eksperta"}]}},
   "warning": {"text": "W Konarzewie grunt badano dopiero po umowie i budowa się wydłużyła.", "cases": ["RM-2026-020"], "prov": {"role": "case", "review_status": "approved", "refs": ["..."]}}}],
 "balance": {"buyer": {"amount": "720000.00", "currency": "PLN", "vat_basis": "gross"}, "contractor": {"amount": "340000.00", "currency": "PLN", "vat_basis": "gross"},
             "premium": {"amount": "95000.00", "currency": "PLN", "vat_basis": "gross"}, "off_recommendation": 1, "note": "1 ryzyko podzielone inaczej niż zalecamy."}}
```
Demo values above are illustrative; positions, how-texts and factors come from `catalogue/wod-kan/allocation.yaml` (data session).

### 2.4 Projects (2.1–2.6)

| Screen | Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|---|
| 2.1 | `GET /api/sources/summary`, `GET /api/runs`, `GET /api/jobs[/{id}]` | | as today | source, ingestion_run, job | EXISTS | login | |
| 2.1 | `POST /api/jobs` | `{kind: "load_all"}` ("Uruchom wzbogacanie") | `JobOut` | job | EXTEND (gate) | admin | run writes ingestion_run |
| 2.1 | `POST /api/imports` | multipart `files[]` | `{code: "IMP-2026-0003", status: "uploaded", files: [{name: "projekty_2026.xlsx", bytes, sha256, kind: "xlsx", duplicate_of_source_id: null}]}` | import_session, source | NEW | login | sha256 per file |
| 2.1 | `POST /api/imports/{code}/inspect` | none | J9 `tool_calls[]` | import_session | NEW | login | tool outputs are calc |
| 2.1 | `POST /api/imports/{code}/propose-mapping` | none | J9 `mapping[]`, `questions[]`, `importer` | import_session, importer, llm_call | NEW | login | mapping rows ai proposed; rule results calc |
| 2.1 | `POST /api/imports/{code}/answers` | `{value_vat_basis: "gross"}` | J9 | import_session, audit_log | NEW | login | |
| 2.1 | `POST /api/imports/{code}/test-run` | `{rows: 50}` | `{ok: 47, failed: 3, failures: [{row: 12, column: "NIP odbiorcy", rule: "nip_checksum", value_masked: "912***754"}], would: {insert: {project: 47}, update: 0, protected_skipped: 0}, review_items_created: 3}` | import_session, review_item | NEW | login | counts calc n = 50 |
| 2.1 | `POST /api/imports/{code}/approve` | `{importer_name: "zestaw organizatora"}` | `{importer_id, version: "v3"}` | importer, review, audit_log | NEW | login | |
| 2.1 | `POST /api/imports/{code}/run` | none | `{job_id, run_id}` | job, ingestion_run, source, target tables | NEW | login | every imported row gets `source_id` of the file |
| 2.1 | `GET /api/imports/{code}`, `GET /api/importers` | | full state / `[{name, format_label: "XLSX, 23 kolumny", uses: 3, version: "v2"}]` | import_session, importer | NEW | login | |
| 2.2 | `GET /api/projects` | today's filters + `late`, `has_discrepancy`, `to_review`, `contractor_nip`, `sort=delay_days\|-cost_dev_pct\|value`, `rm_ids=a,b` | `Page[ProjectOut + metrics]`, `metrics = {contract_value: Money, delay_days: Num, cost_dev_pct: Num, changes: Num, properly_performed: bool\|null, state: {code: "to_review"\|"approved"\|"discrepancy"\|"partial_payment", label: "2 do przeglądu"}}` | project, project_procedure, contract, contract_performance, contract_change, review_item | EXTEND | public | delay/cost calc n = 1 with notice refs (fields 4.2, 5.2, 4.4, 5.5) |
| 2.2 | `GET /api/projects/stats` | same filters | `{late: Num ("20 z 27"), overpaid: Num + median, improper: Num, changes: Num}` | same | NEW | public | calc, n = contracts in the 22 projects |
| 2.2 | `GET /api/export/projects.{csv\|json}` | `rm_ids=` selection, `sep=semicolon` | file | | EXTEND | public | adds metric + origin columns |
| 2.3 | `GET /api/projects/{rm_id}/card` | none | J7 | project, procedure chain, risk_event, evidence, document, catalogue_checklist | NEW | public (AI filtered) / login | per field (J7) |
| 2.3 | `GET /api/projects/{rm_id}`, `/timeline` | | as today | | EXISTS | public | |
| 2.3 | `GET /api/projects/{rm_id}/similar` | `?k=5` | `SimilarCase[]` | project, rc_contract, catalogue_entry | NEW | public | score calc, outcomes case |
| 2.3 | `POST /api/projects/{rm_id}/chat` | `{message}` | `Answer` | question, llm_call | NEW | public (approved facts only) / login | |
| 2.4 | `GET /api/projects/{rm_id}/graph` | `?include_proposed=true` (login) | J8 | evidence, project_procedure, link_candidate, contract, contract_change, contract_performance, risk_event, source | NEW | public / login | node `role`, link `value` = fact count, `fact_ids` for tracing |
| 2.4 | `POST /api/projects/{rm_id}/links` | `{action: "replace"\|"add"\|"remove", bzp_number: "2025/BZP 00307948/01", lots: [1], reason}` | `{project_procedure: ProjectLinkOut, review_id, closed_review_items: [12]}` | project_procedure, link_candidate, review, review_item, audit_log | NEW | login | link becomes method `expert`, review_status `approved` |
| 2.5 | `GET /api/projects/{rm_id}/documents` | none | `{expected: [{doc_type: "PFU", label, evidence_state: "BRAK_W_PACZCE", state_label: "nie ma w paczce", unlocks: "Potwierdzi R01: ...", where_to_find}], public: [{kind: "notice", ref: "2024/BZP 00554831/01", title, date, facts: 2, risk_codes: ["R01"], review_status: "approved", object_id}], have: 0, expected_total: 4}` | document, catalogue_checklist, catalogue_doc_type, notice, evidence, risk_event | NEW | public / login | evidence states from catalogue |
| 2.5 | `GET /api/notices/{object_id}/facts` | none | `{rows: [{field_code: "4.4", label: "wartość zmiany", value: "+758 084,56 zł brutto", prov}], meta: {url, retrieved_at, sha256, licence: "informacja publiczna"}}` | evidence, notice, source | NEW | public | source per field code |
| 2.5 | `POST /api/documents/upload` with `project_rm_id` | as 1.1 | as 1.1 + `jobs: ["doc_text","extract_events"]` | document, job | NEW | login | |
| 2.6 | `GET /api/projects/{rm_id}/history` | `?actor_kind=expert\|model\|system` | `{record_version: "v7", items: [{audit_id, at, actor_kind: "model", actor_label: "Model Bielik 11B (Polska)", action_label: "zaproponował zdarzenie R04", before, after, why, version: "v6", can_restore: false}]}` | audit_log, review, llm_call | NEW | login | actor is the provenance |
| 2.6 | `GET /api/projects/{rm_id}/history/compare` | `?from=v3&to=v7` | `{changes: [{table, row_id, field, before, after}]}` | audit_log | NEW (stretch) | login | |
| 2.6 | `POST /api/audit/{audit_id}/restore` | `{reason}` | `{review_id, restored: {table, row_id, fields}}` | review, target table, audit_log | NEW | login | restore = new edit, never a delete |

J7 `GET /api/projects/RM-2026-003/card` (Steklin, values from the BZP chain):
```json
{"rm_id": "RM-2026-003", "title": "Budowa oczyszczalni ścieków w miejscowości Steklin w formule zaprojektuj i wybuduj",
 "summary": {"sentence": "Skończono 277 dni po terminie i zapłacono o 40,3% więcej niż w umowie.", "prov": {"role": "calc", "review_status": "auto", "method": "template:card_v1", "refs": []}},
 "plan_vs_actual": [
  {"key": "time", "label": "Termin", "planned": {"value": 396, "display": "396 dni", "unit": "days", "prov": {"role": "source", "review_status": "auto", "refs": [{"kind": "notice", "id": "2024/BZP 00418711/01", "label": "ogł. o wyniku", "field_code": "4.2"}]}},
   "actual": {"value": 673, "display": "673 dni", "unit": "days", "prov": {"role": "calc", "review_status": "auto", "n": 1, "method": "completed_on - signed_on", "refs": [{"kind": "notice", "id": "2026/BZP 00276065/01", "label": "ogł. o wykonaniu", "field_code": "5.2"}]}},
   "delta": {"value": 277, "display": "+277 dni", "unit": "days", "prov": {"role": "calc", "review_status": "auto", "n": 1, "method": "actual - planned", "refs": []}}},
  {"key": "cost", "label": "Koszt", "planned_money": {"amount": "2131590.00", "currency": "PLN", "vat_basis": "gross"}, "actual_money": {"amount": "2990000.00", "currency": "PLN", "vat_basis": "gross"},
   "delta": {"value": 40.3, "display": "+40,3%", "unit": "pct", "prov": {"role": "calc", "review_status": "auto", "n": 1, "method": "paid/contract - 1", "refs": ["4.4", "5.5"]}}}],
 "steps": [{"state": "done", "title": "Dopłata +758 084,56 zł", "text": "Roboty nieprzewidziane w PFU. Art. 455 ust. 1 pkt 3.", "date": "2024-10-09",
            "ref": {"kind": "notice", "id": "2024/BZP 00554831/01", "label": "ogł. o zmianie"}, "review_status": "auto"},
           {"state": "now", "title": "Nowy termin: 26.05.2026", "text": "Pozwolenie wodnoprawne trwało dłużej.", "review_status": "proposed", "href": "/przeglad?item=812"}],
 "events": [{"id": 1187, "title": "PFU nie opisał całego zakresu", "text": "Dopłata 758 tys. zł za roboty spoza PFU.", "risk_code": "R01",
             "prov": {"role": "source", "review_status": "approved", "refs": [{"kind": "notice", "id": "2024/BZP 00554831/01", "label": "pole 5.3", "field_code": "5.3"}]}}],
 "gaps": [{"doc_type": "PFU", "evidence_state": "BRAK_W_PACZCE", "state_label": "nie ma w paczce", "limits": "Nie potwierdzimy, czego w nim brakowało."}],
 "identifiers": [{"k": "BZP", "v": "2024/BZP 00349631/01"}, {"k": "OCID", "v": "ocds-148610-6b092479-223f-11ef-87ba-8eb060fd7bb8"}, {"k": "NIP", "v": "8792466869", "verified": true}],
 "similar": ["SimilarCase..."], "unverified_hidden": 0}
```

J8 `GET /api/projects/{rm_id}/graph` (Sankey, three columns):
```json
{"columns": [{"key": "sources", "label": "Źródła"}, {"key": "facts", "label": "Fakty"}, {"key": "conclusions", "label": "Wnioski"}],
 "nodes": [{"id": "src:xlsx", "column": 0, "label": "Zestaw organizatora", "sub": "XLSX, 1 wiersz", "role": "source", "value": 2},
           {"id": "src:bzp", "column": 0, "label": "Ogłoszenia BZP", "sub": "5 ogłoszeń", "role": "source", "value": 9},
           {"id": "src:ai", "column": 0, "label": "Odczyt modelu", "sub": "tekst ogłoszeń", "role": "ai", "value": 3},
           {"id": "src:calc", "column": 0, "label": "Obliczenia", "sub": "z faktów powyżej", "role": "calc", "value": 2},
           {"id": "fact:changes", "column": 1, "label": "Zmiany", "sub": "2 dopłaty", "value": 2},
           {"id": "concl:R04", "column": 2, "label": "R04 decyzja organu", "sub": "wniosek AI", "role": "ai", "review_status": "proposed", "review_item_id": 812, "value": 2}],
 "links": [{"source": "src:bzp", "target": "fact:changes", "value": 2, "fact_ids": ["evidence:551203", "evidence:551204"]},
           {"source": "fact:reasons", "target": "concl:R04", "value": 2, "fact_ids": ["..."]}],
 "details": {"concl:R04": {"kind": "wniosek, odczyt modelu", "title": "R04: decyzja organu przesunęła termin",
             "rows": [{"k": "skąd", "v": "2 z 2 faktów pochodzą z odczytu tekstu sekcji zmian ogłoszenia o wykonaniu."}, {"k": "pewność", "v": "0,32, do przeglądu"}],
             "evidence": ["Ref..."], "cta": {"label": "Sprawdź w Przeglądzie", "href": "/przeglad?item=812"}}},
 "summary": {"facts": 16, "conclusions": 6, "by_role": {"source": 11, "ai": 3, "calc": 2}}}
```
Fact grouping rule (fixed table in code): `project`, `organization`, `project_procedure` → Identyfikacja; `contract`, `lot` → Umowa; `contract_change` (value, basis) → Zmiany; `contract_performance` → Wykonanie; `contract_change.cause_text`, `risk_event.cause` → Przyczyny; CALC rows → Wyniki. Source column from `evidence.source_id → source.kind` (xlsx, bzp_*), `origin = AI` → Odczyt modelu, `origin = CALC` → Obliczenia. Conclusions: project link, delay, cost, one per `risk_event.catalogue_code`.

J9 import agent state (`GET /api/imports/{code}`):
```json
{"code": "IMP-2026-0003", "status": "awaiting_answer",
 "files": [{"name": "paczka_powiat.zip", "bytes": 1932735283, "sha256": "...", "kind": "zip"}, {"name": "projekty_2026.xlsx", "kind": "xlsx"}],
 "tool_calls": [{"call": "list_archive(\"paczka_powiat.zip\")", "out": "2 341 plików, 14 typów", "ms": 410, "llm": false},
                {"call": "sample_rows(\"projekty_2026.xlsx\", n=20)", "out": "18 kolumn, arkusz Projekty", "ms": 95, "llm": false},
                {"call": "match_schema(known_formats)", "out": "„zestaw organizatora”, 16 z 18", "ms": 12, "llm": false},
                {"call": "classify_docs(sample=40)", "out": "SWZ 12, PFU 9, PPU 8, protokoły 11", "ms": 5200, "llm": true}],
 "mapping": [{"column": "NIP odbiorcy", "field": "organization.nip", "rule": "nip_checksum", "status": "ok", "valid": 309, "total": 312},
             {"column": "Kwota", "field": "project.value", "rule": "money_requires_vat_basis", "status": "question"},
             {"column": "Uwagi", "field": "project.note", "rule": "text_no_analysis", "status": "proposal"}],
 "questions": [{"key": "value_vat_basis", "text": "Kwota: netto czy brutto?", "options": [{"value": "gross", "label": "Brutto, z VAT."}, {"value": "net", "label": "Netto, bez VAT."}]}],
 "rules": ["Każdy NIP i REGON przechodzi sumę kontrolną.", "Numery BZP, KPO i TED tylko w znanym formacie.", "Kwota zawsze z rodzajem: netto albo brutto.",
           "Ten sam plik po sha256 nie wchodzi dwa razy.", "Import nigdy nie nadpisuje danych zatwierdzonych przez eksperta."],
 "importer": {"name": "zestaw organizatora", "version": "v3", "spec_preview": {"sheet": "Projekty", "columns": {"Nr ogłoszenia": {"field": "procedure.bzp_number", "rule": "bzp_format"}}}},
 "test_run": null, "job_id": null}
```

### 2.5 Review 3.1 (`/przeglad`, login)

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `GET /api/review-items` | today + `kind=event\|link\|discrepancy\|fact\|catalogue\|import\|case_candidate`, `code`, `rm_id` | `Page[ReviewItemOut]` + `question`, `context`, `model_pick` | review_item (queue filled by `review_sync`) | EXTEND | login | `detail.evidence` refs |
| `GET /api/review-items/counts` | none | `{event: 16, link: 12, discrepancy: 3, fact: 4, catalogue: 2, total: 37}` | review_item | NEW | login | |
| `GET /api/review-items/{id}` | none | J10 | review_item + target row + evidence + similar proposals | NEW | login | quote `verification`, model confidence |
| `POST /api/review-items/{id}/decision` | `{option: "R02", action: "approve"\|"edit"\|"reject", value?: {catalogue_code: "R04"}, reason?: "...", gold: false}` | `{review_id, applied: [{table: "risk_event", id: 9911, field: "catalogue_code", before: null, after: "R02"}], effects: [{where, before, after}], gold: {job_id, similar_pending: 7}\|null, undo_until: "2026-11-21T21:15:00Z", next_item_id: 813}` | review, review_item, target table, gold_example, audit_log, job | NEW | login | target row `review_status` approved/edited/rejected |
| `POST /api/review-items/{id}/skip` | none | `{next_item_id}` | review_item (`detail.skipped_at`) | NEW | login | |
| `POST /api/reviews/{review_id}/undo` | none | `{review_id: 44, restored: [...]}` | review, target, review_item, audit_log | NEW | login | |
| `GET /api/reviews` | `?target_table=&target_id=&reviewer=` | `Page[{id, action, option_key, before, after, reviewer, comment, created_at}]` | review | NEW | login | |
| `GET /api/jobs/{id}` (gold rescore) | | `result: {rescored: 7, unchanged: 5, changed: 2, requeued_item_ids: [820, 822]}` | job | EXISTS | login | |
| `POST /api/review-items/bulk-decision` | `{ids: [], action: "approve"}` | `{done: [], refused: [{id, reason: "cytat niezweryfikowany"}]}` | as decision | NEW (stretch) | login | only `exact`/`structured_field` evidence |

J10 `GET /api/review-items/{id}`:
```json
{"id": 812, "kind": "event", "kind_label": "Zdarzenie ryzyka", "context": {"label": "Steklin, RM-2026-003", "href": "/projekty/RM-2026-003"},
 "question": "Dlaczego w Steklinie dopłacono 100 325,44 zł?", "sub": "To druga zmiana umowy. Od przyczyny zależy, przy którym ryzyku ten przypadek będzie liczony w raportach.",
 "target": {"table": "risk_event", "id": 9911, "review_status": "proposed"},
 "evidence": {"title": "Ogłoszenie o zmianie umowy, opis zmiany", "ref": {"kind": "notice", "id": "2024/BZP 00618384/01", "label": "pole 5.3", "field_code": "5.3"},
              "pre": "…robót dodatkowych nieprzewidzianych w PFU, a niezbędnych do prawidłowej realizacji przedmiotu Umowy polegających w szczególności na ",
              "hit": "wymianie odcinków sieci wodociągowej wykonanych z rur azbestowych na sieć wodociągową wykonaną z rur polimerowych", "post": "”", "verification": "exact"},
 "chips": [{"text": "kwota zgodna ze źródłem", "tone": "ok"}, {"text": "art. 455 ust. 1 pkt 3", "tone": "neutral"}, {"text": "brak PFU w paczce", "tone": "warn"}],
 "options": [
  {"key": "R02", "action": "approve", "label": "R02 Nierozpoznany stan istniejący", "sub": "w trasie były rury azbestowe, których nikt nie opisał",
   "model_pick": true, "confidence": 0.8, "badge": "propozycja modelu, 0,80", "needs_input": null,
   "effects": [{"where": "Katalog, ryzyko R02", "before": "2 zatwierdzone przypadki", "after": "3 zatwierdzone przypadki"}, {"where": "Widok publiczny", "before": "zdarzenie ukryte", "after": "zdarzenie widoczne na karcie"}]},
  {"key": "other", "action": "edit", "label": "Inne ryzyko z katalogu", "needs_input": "value", "input_placeholder": "Kod ryzyka i krótkie uzasadnienie", "effects": ["..."]},
  {"key": "not_risk", "action": "reject", "label": "To nie jest zdarzenie ryzyka", "needs_input": "reason", "effects": ["..."]}],
 "gold": {"label": "Podobne propozycje w kolejce", "before": "7 czeka na przegląd", "after": "zostaną przeliczone według Twojej decyzji"},
 "llm": {"provider": "wcss_bielik", "model": "speakleash/Bielik-11B-v3.1-Instruct", "data_location": "PL (WCSS Wrocław)", "llm_call_id": 311}}
```
Effects are computed server-side from real counts (catalogue case counts, public visibility, similar pending proposals), so the "Co zmieni Twoja odpowiedź" panel is not decoration.

### 2.6 Catalogue 3.2 (`/katalog`, read login, edit login, version restore admin)

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `GET /api/catalogue/{table}` | `sector`, `status` | raw rows | catalogue_* | EXISTS | public (approved only), login (all) | |
| `GET /api/catalogue/view` | `?sector=wod-kan` | J11 | catalogue_*, catalogue_version, review_item, risk_event | NEW | login | quality notes calc (n = 150 gold causes) |
| `PATCH /api/catalogue/{table}/{code}` | `{patch: {name?, description?, data?: {signals: [...]}}, comment}` | `{code, version: 3, status: "approved", catalogue_version: "v1.4"}` | catalogue_*, catalogue_version, audit_log | NEW | login | edited rows origin SOURCE, `approved_by` |
| `PUT /api/catalogue/similarity/weights` | `{weights: {subsector_main: 0.26, design_build: 0.22, scope: 0.22, budget: 0.16, text: 0.14}, comment}` | `{weights, catalogue_version: "v1.4", summary: "wagi: zakres 18 → 22"}` | catalogue_entry (`similarity`), catalogue_version | NEW | login | |
| `POST /api/catalogue/proposals/{id}/decision` | `{action: "approve"\|"merge"\|"reject", merge_into?: "R06", reason?}` | as review decision | catalogue_risk, review_item, review, catalogue_version | NEW (thin wrapper over 2.5 decision) | login | AI proposal → approved SOURCE row |
| `GET /api/catalogue/versions` | none | `[{label: "v1.3", summary: "wagi: zakres 18 → 22", actor: "ekspert", at}]` | catalogue_version | NEW | login | |
| `GET /api/catalogue/versions/{label}/diff` | `?against=v1.2` | `{changes: [{table, code, before, after}]}` | catalogue_version | NEW | login | |
| `POST /api/catalogue/versions/{label}/restore` | `{reason}` | `{catalogue_version: "v1.5"}` | catalogue_*, catalogue_version, audit_log | NEW | admin | restore = new version |
| `GET /api/catalogue/pack.{json\|yaml}` | `sector` | sector pack export | catalogue_* | NEW | public | |

J11 `GET /api/catalogue/view`:
```json
{"version": "v1.3", "risks": [{"code": "R01", "name": "Niepełny lub niespójny zakres", "effects": "Błędna wycena, roboty dodatkowe, spór o wynagrodzenie",
   "parts": [{"k": "sygnał w dokumentach", "v": "PFU bez inwentaryzacji; „ok.” przy ilościach"}, {"k": "środki zaradcze", "v": "inwentaryzacja przed ogłoszeniem; ceny jednostkowe"}],
   "counts": {"approved": 1, "proposed": 3},
   "quality": {"note": "reguły wyłapują 2 z 14", "precision": {"value": 0.4, "display": "0,40", "unit": "share", "prov": {"role": "calc", "review_status": "auto", "n": 150, "method": "keyword_vs_gold", "refs": [{"kind": "file", "id": "research/bzp_corpus/out/keyword_vs_gold.csv", "label": "zbiór wzorcowy"}]}},
               "recall": {"value": 0.14, "display": "0,14", "unit": "share", "prov": {"...": "..."}}, "review_href": "/przeglad?kind=event&code=R01"}}],
 "proposals": [{"id": 41, "review_item_id": 830, "title": "Warunki atmosferyczne", "description": "Przedłużenie terminu z powodu pogody.", "evidence_text": "11 ze 150 przyczyn w zbiorze wzorcowym (7%)", "merge_suggestion": "R06", "origin": "AI", "status": "proposed"}],
 "weights": [{"feature": "subsector_main", "label": "podsektor", "w": 0.26}],
 "subsectors": ["..."], "doc_types": ["..."], "checklists": ["..."], "clauses": ["..."],
 "versions": [{"label": "v1.3", "summary": "wagi: zakres 18 → 22", "actor": "ekspert", "at": "2026-11-21T13:20:00Z"}]}
```

### 2.7 Monitoring 4.1–4.1c (public start page)

| Screen | Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|---|
| 4.1 | `GET /api/monitoring/regions` | `level=woj\|pow\|gmi`, `parent=12`, `mode=done\|open`, `metric=late\|delay\|over\|chg\|imp\|sig`, `subsector`, `value_min`, `value_max`, `year_from`, `year_to`, `q`, `as_of?` | J12 | rc_contract (+ `buyer_terc`), v_monitor_signal | NEW | public | each region value `Num` calc with n = contracts in region |
| 4.1a/b | `GET /api/monitoring/regions/{terc}` | same filters | J13 | as above | NEW | public | kpis `Num` |
| 4.1a/b | `GET /api/monitoring/signals` | `terc`, `level`, `limit`, `offset`, `sort=-days_overdue`, `geo=true`, `as_of?` | `Page[Signal]` | v_monitor_signal, contract, procedure, notice, organization | NEW | public | `days_overdue` calc n = 1, refs to the result notice and change notices |
| 4.1a | `GET /api/export/signals.{csv\|json}` | `terc`, `level` | all signals incl. those without map location, with BZP numbers | v_monitor_signal | EXTEND (new dataset) | public | `origin`, `source_url` columns |
| 4.1c | `GET /api/monitoring/contracts/{contract_id}` | none | `{signal: Signal, plan: {planned_days: Num, overdue_days: Num}, compare: {region_late_pct: Num, region_median_delay: Num, sentence}, sources: [{k: "ogłoszenie o wyniku", v: "2022/BZP 00195927", url}, {k: "ogłoszenia o zmianie", v: "2"}, {k: "ogłoszenie o wykonaniu", v: "brak", missing: true}], actions: {card_href: "/umowy/123", can_watch: false, can_report: false}}` | contract, notice, rc_contract | NEW | public | |
| 4.1 | `GET /api/geo/{level}.geojson` | `parent=12`, `simplify=true` | GeoJSON (props `terc`, `name`), ETag, 1 day cache | `data/ref/geo/*.geojson` | NEW | public | source: TERYT / PRG (licence in `source`) |
| 4.1c | `POST /api/monitoring/watches`, `DELETE /api/monitoring/watches/{id}` | `{contract_id, reason?}` | `{id, contract_id, active}` | monitor_watch, audit_log | NEW | login | |
| 4.1c | `POST /api/monitoring/contracts/{id}/report-case` | `{note}` | `{review_item_id}` (kind `case_candidate`) | review_item, audit_log | NEW | login | |
| 4.1c | `GET /api/contracts/{id}`, `GET /api/procedures/{ocid}` | | automatic, unverified contract card | | EXISTS | public | |

J12 `GET /api/monitoring/regions?level=woj&mode=done&metric=late`:
```json
{"level": "woj", "parent": null, "mode": "done",
 "metric": {"key": "late", "label": "Po terminie", "description": "odsetek umów zakończonych po terminie z umowy", "unit": "pct"},
 "total": {"label": "11 574 umów zakończonych, 30% po terminie", "n": 11574},
 "legend": {"min": {"value": 23.1, "display": "23,1%"}, "max": {"value": 43.1, "display": "43,1%"}},
 "regions": [{"terc": "12", "name": "małopolskie",
   "value": {"value": 29.3, "display": "29,3%", "unit": "pct", "prov": {"role": "calc", "review_status": "auto", "n": 1072, "method": "rc_share(late) by province", "refs": [{"kind": "query", "id": "rc:core|PL12", "label": "ogłoszenia o wykonaniu umowy, BZP"}]}},
   "metrics": {"n_completed": 1072, "late_pct": 29.3, "median_delay_days_late": 62, "overpaid_pln": "51162876.58", "value_pln": "...", "changes_pct": 44.6, "improper_pct": 0.5, "signals": 217}}]}
```
`metrics` is the compact per-region table (mockup `ST`/`BY`) for the list and the metric switch; its provenance is the `value.prov` of the same row (same filter, same n). `n_completed`, `late_pct` and `overpaid_pln` for PL12 are DB values; the other metrics and the legend are the mockup's research values.

J13 `GET /api/monitoring/regions/12`:
```json
{"terc": "12", "name": "małopolskie", "level": "woj", "breadcrumb": [{"terc": null, "name": "Polska"}, {"terc": "12", "name": "małopolskie"}],
 "kpis": [{"key": "late_pct", "label": "PO TERMINIE", "value": {"value": 29.3, "display": "29,3%", "unit": "pct", "prov": {"...": "..."}}},
          {"key": "signals", "label": "SYGNAŁY TERAZ", "attention": true, "value": {"value": 217, "display": "217", "unit": "count", "prov": {"...": "..."}}}],
 "children": [{"terc": "1209", "name": "powiat myślenicki", "signals": 5, "buyers": ["Dobczyce", "Raciechowice"]}],
 "signals": {"total": 217, "on_map": 12, "items": ["Signal..."], "csv_href": "/api/export/signals.csv?terc=12&level=woj",
             "note": "Na mapie 12 z 217 sygnałów: te, które da się przypisać do gminy po nazwie zamawiającego. Plik CSV ma wszystkie."},
 "list_href": "/projekty?province=12"}
```

### 2.8 History (`/historia`, login)

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `GET /api/audit` | `category=expert\|import\|catalogue\|model\|system`, `table`, `row_id`, `actor`, `since`, `limit`, `offset` | `Page[{id, at, actor_kind: "expert"\|"model"\|"system", actor_label, action_label: "zmienił wagę podobieństwa w", object: {label: "Katalogu wiedzy", href: "/katalog"}, before, after, note: "katalog v1.2 → v1.3", ref: "kat-v1.3"}]` | audit_log, review, llm_call | NEW | login | the actor line is the provenance |
| `GET /api/export/audit.{csv\|json}` | same filters | file | audit_log | EXTEND (new dataset) | login | |

Category mapping: actor `user:*` → expert; actions `import.*`, `link.*`, `derive.*`, `seed` → import; `catalogue.*` → catalogue; actor `model:*` → model; other `system:*` → system.

### 2.9 Settings and providers (`/ustawienia`, view login, change admin)

| Endpoint | Request | Response | Tables | Status | Access | Provenance |
|---|---|---|---|---|---|---|
| `GET /api/settings/llm` | none | J14 | config.yaml, app_setting, llm_call | NEW | login | usage numbers calc from llm_call |
| `PUT /api/settings/llm/routing` | `{models: {strong: "gemini:gemini-pro-latest"}, routing: {public: {bulk_classify: "sovereign"}}}` | J14 | app_setting, audit_log | NEW | admin | refuses confidential routes whose provider `data_location` does not start with `PL` (422) |
| `POST /api/settings/llm/providers/{id}/health` | none | `{id, status: "up"\|"down", latency_ms, models: [...]}` | | NEW | admin | |
| `GET /api/config/features` | | flags | config.yaml | EXISTS | public | |

J14 `GET /api/settings/llm` (keys are never returned, only `configured`):
```json
{"tasks": [{"task": "classify_changes", "label": "Klasyfikacja przyczyn zmian", "data_label": "dane publiczne, ok. 5 tys. ogłoszeń", "sensitivity": "public",
            "alias": "bulk", "provider": "gemini", "model": "gemini-3.5-flash-lite", "data_location": "global (Gemini Developer API)", "sovereign": false},
           {"task": "confidential_documents", "label": "Poufne dokumenty przed publikacją", "sensitivity": "confidential", "alias": "sovereign",
            "provider": "wcss_bielik", "model": "speakleash/Bielik-11B-v3.1-Instruct", "data_location": "PL (WCSS Wrocław)", "sovereign": true, "enforced": true}],
 "providers": [{"id": "gemini", "kind": "google_genai", "data_location": "global (Gemini Developer API)", "configured": true, "health": {"status": "up", "checked_at": "...", "latency_ms": 640}},
               {"id": "wcss_bielik", "kind": "openai_compatible", "data_location": "PL (WCSS Wrocław)", "configured": false, "health": {"status": "unknown"}}],
 "usage_24h": {"calls": {"value": 412, "display": "412", "unit": "count", "prov": {"role": "calc", "review_status": "auto", "n": 412, "method": "count(llm_call)", "refs": []}}, "tokens_in": 1830000, "tokens_out": 210000, "cost_usd": 3.12}}
```

---

## 3. Write actions and their rules

General rules for every write:
- One DB transaction on the request session (`get_session`), never `raw_conn()` inside a request path (keeps tests rollback-able).
- Each write inserts at least one `audit_log` row: `actor` = `user:<name>` | `anon:<8 chars>` | `system:<component>` | `model:<provider>/<model>`, `action` = `<area>.<verb>` (`review.approve`, `analysis.run`, `catalogue.edit`, `import.approve`), `table_name`, `row_id`, `before`, `after`, `request_id`.
- `SET LOCAL riskminer.expert_write = 'on'` appears only in `riskminer/review/` (decisions, undo, restore, link correction, catalogue). A test greps for the literal elsewhere.
- After an UPDATE the service checks `RETURNING review_status` (or the changed field) and raises 409 `protected_row` when the trigger kept OLD.
- AI output is inserted with `origin = 'AI'`, `review_status = 'proposed'`, `llm_call_id`; the LLM layer never issues UPDATEs on rows it did not create in the same run.

### 3.1 Review decisions (approve / edit / reject / mark_gold)
`POST /api/review-items/{id}/decision`, service `riskminer/review/service.py::decide()`:
1. `SELECT ... FROM review_item WHERE id = :id FOR UPDATE`; 409 if `status <> 'open'`.
2. Load the target (`target_table`, `target_id`); snapshot `before` = the fields the chosen option changes + `review_status`.
3. Validate input: `reject` needs `reason` (422); `edit` needs `value` valid for the target (catalogue code exists and is approved, BZP number resolves to an OCID, date parses, money has `vat_basis`).
4. `SET LOCAL riskminer.expert_write = 'on'`, then apply per kind:
   - event (`risk_event`): approve sets `catalogue_code` to the model pick and `review_status = 'approved'`; edit sets the expert's code/summary/impact and `'edited'`; reject `'rejected'`.
   - link (`link_candidate`): approve sets `review_status = 'approved'` and upserts `project_procedure` (method `expert`, `'approved'`); "inne postępowanie" creates a new candidate (method `expert`) and link; "brak w BZP" rejects all candidates and writes `review_item.detail.resolution`.
   - discrepancy: options map to resolution codes in `review_item.detail.resolution`; part choices update `project_procedure.lots`; the organiser dataset is never changed.
   - fact (AI-read value, e.g. `contract_performance.completed_on`): approve keeps the value and sets `'approved'`; edit writes the expert value, `'edited'`, plus an `evidence` row (`verification = 'structured_field'`, `note = 'ekspert: <source>'`).
   - catalogue proposal: see 3.2.
5. Insert `review` (`target_table`, `target_id`, `review_item_id`, `action`, `option_key`, `before`, `after`, `reviewer`, `comment`).
6. `review_item.status = 'resolved'`, `resolved_by`, `resolved_at`.
7. `audit_log` row.
8. `gold: true` (only with approve/edit): insert `gold_example` (`task` from kind, `input_text` = quote, `output` = decided value, `review_id`), record a second `review` row with `action = 'mark_gold'`, and enqueue job `rescore_gold` (session L). The job re-runs the classifier with the gold example in the prompt on up to 20 similar `proposed` items, updates only `proposed` rows, and stores `{rescored, unchanged, changed, requeued_item_ids}` in `job.result`.
9. Response: applied changes, effects, gold job id, `undo_until` (now + 15 min), next item id.

Undo (`POST /api/reviews/{id}/undo`): same reviewer, within `undo_until`; writes a new `review` (`action = 'edit'`, comment `cofnięcie decyzji #<id>`, before/after swapped), restores the target with expert_write, reopens the `review_item`, audit `review.undo`. Nothing is deleted; gold examples created by the undone decision get `output.retracted = true`.

Queue sync (job `review_sync`, session B, idempotent by `review_item.key`): `risk_event` with `origin = 'AI' AND review_status = 'proposed'` → kind `event`; `link_candidate` with `decision = 'review'` → kind `link`; AI-read facts with `evidence.verification <> 'exact'` → kind `fact`; `catalogue_* status = 'proposed'` → kind `catalogue`; import failures → kind `import`. Runs after every LLM batch and on startup.

### 3.2 Catalogue edits with versioning; link correction
- Rows are immutable per version. An edit inserts a new row with the same `(sector, code)`, `version = max + 1`, `status = 'approved'`, `origin = 'SOURCE'`, `approved_by = user`; the previous approved row becomes `status = 'retired'`. Readers always filter `status = 'approved'`.
- Every edit also writes one `catalogue_version` row (pack label `v1.3` → `v1.4`, `summary` generated in Polish, `changes = [{table, code, from_version, to_version, before, after}]`) and an audit row. Several edits in one request share one pack version.
- The YAML seeder already refreshes only rows with `version = 1 AND approved_by IS NULL`, so expert edits survive `seed_catalogue`.
- Similarity weights are validated (all ≥ 0, sum = 1 ± 0,001, known feature keys) and stored as a new version of `catalogue_entry(similarity, default)`.
- Expert assumptions (`mitigation`, `allocation`, `funding_programme` entries) carry `data.assumption = true`; editing them is a normal catalogue edit.
- AI proposals (`R16 Warunki atmosferyczne`) are inserted `status = 'proposed', origin = 'AI'` with a `review_item` kind `catalogue`; approve = insert approved version 1 (or merge into the target risk's `data.signals`) + pack version; reject = `status = 'rejected'` with reason.
- Restore (admin): re-applies a snapshot as new versions; never rewinds ids.
- Each `analysis_version` stores the `catalogue_version` it used, so old reports stay reproducible.
- **Link correction** (`POST /api/projects/{rm_id}/links`): resolve the BZP number to an OCID (404 if unknown), expert_write, upsert `project_procedure` (`method = 'expert'`, `review_status = 'approved'`, lots), insert `link_candidate` (method `expert`, `reference_verdict` untouched), `review` (`action = 'edit'`, target `project_procedure`), close related `review_item`s (`part_mismatch`, `contract_notice_missing`), audit `link.correct`.

### 3.3 Analysis create / patch / re-run; document upload with a sensitivity label
- **Upload**: bytes to `data/raw/upload/<sha256>.<ext>` + one `manifest.jsonl` line (invariant 1); `source` row (`kind = 'upload'`, `licence = 'user-upload'`, sha256, path); dedup by sha256 (returns the existing `document_id`). `document` (`origin = 'SOURCE'`, `sensitivity`, `fetch_state = 'found'`, `doc_type` guess). Text: PDF with pypdfium2 (already a dependency), DOCX/DOC via `soffice --convert-to pdf` then the same path; pages into `document_page`, chunks via `ingest/doctext.py`. Scans set `text_status = 'needs_ocr'` (no OCR in the request path). Max 50 MB, PDF/DOCX/DOC/ODT only.
- **Sensitivity**: `confidential` is the default for anonymous uploads. Confidential documents are routed only to `sovereign` (gateway enforces; queue + 503 when Bielik is down), excluded from `/api/search`, `/api/documents`, exports and other users' views, and their file is served only to the owner/admin. The demo uses a public BZP PFU marked `public`.
- **Create** `POST /api/analyses`: `code` from `record_counter('AN', 2026)`; `owner` = user or anon id; `sensitivity` = max of body and documents; feature extraction: regex first (money, km, months, pumping stations, programme names), then the LLM `extract_features` task with page refs and quote verification; each chip is an `analysis_item(section = 'feature', key)`. Writes `analysis_version` v1 and audit `analysis.create`.
- **Patch features**: owner only; changed chips become `review_status = 'edited'` with `ref input_text:user`; `analysis.version += 1`; computed sections marked stale; audit.
- **Run**: computes every section for the current version in one transaction and stores an immutable `analysis_version` snapshot (`features`, `reference_class`, `results`, `catalogue_version`, `data_as_of` = rc_contract refresh time, `seed`). Items the owner approved or edited are carried to the new version by `item.key` (the trigger already protects them); everything else is regenerated. The Red Pen LLM scan runs as job `analysis_redpen` and fills `analysis_item(section in ('redpen_note','missing'))`.
- **Owner decisions** on AI items (`/items/{id}/decision`) write `review` + audit with actor `anon:*` or `user:*`. Only `approved`/`edited` AI items and all calc/source items go into the pack.
- **Simulation** is computed on request (deterministic, seed = hash(code, version)); `save: true` stores it as `analysis_item(section = 'simulation')`. **Allocation** `PUT` stores choices as `analysis_item(section = 'allocation')` and bumps the version.

### 3.4 Saving chat answers as records (`Q-…`)
- Every `/api/ask`, analysis chat and project chat answer is stored as a `question` row (`status = 'draft'`, no code) with the full `Answer`, the executed SQL, parameters, a snapshot of result rows (≤ 200), `n`, `llm_call_id`, `scope`, `data_as_of`.
- `POST /api/questions {question_id}` assigns `Q-2026-NNNN` from `record_counter('Q', 2026)`, sets `status = 'saved'`, `saved_at`, `title`; audit `question.save`. Drafts older than 7 days may be purged (they are not records).
- `rerun` executes the stored SQL again (same read-only path) and stores a new version (`parent_id`), returning both snapshots so the UI can show what changed.
- NL→SQL safety: SQL only against whitelisted views (`v_ask_contract`, `v_ask_change`, `v_ask_signal`, `v_ask_procedure`), parsed with sqlglot (MIT) to allow a single SELECT with whitelisted tables/functions, run in `BEGIN READ ONLY; SET LOCAL ROLE riskminer_ro; SET LOCAL statement_timeout = '3s'`, `LIMIT 1000`. The sentence for `role = calc` is filled from a template or checked by the number verifier against the result rows; a curated intent set (the suggestion chips plus 6 more) runs without the LLM as fallback.

### 3.5 Import agent sandbox steps
1. **Upload** (`POST /api/imports`): files to `data/imports/<code>/` (outside `data/raw` until approved), sha256 per file, duplicate check against `source.sha256`.
2. **Inspect**: only registered Python tools run (`list_archive`, `sample_rows(n ≤ 20)`, `match_schema`, `classify_docs(sample ≤ 40)`); no shell, no network, no file goes to the model whole; each call is logged in `import_session.tool_calls`.
3. **Propose mapping**: the LLM sees headers + ≤ 20 sample rows (personal-data columns such as e-mail, phone, PESEL are dropped before) and proposes `column → field`; the proposal is validated against a target-field registry; unknown fields stay `proposal` and are not imported. Strict rules are code (`riskminer/imports/rules.py`): NIP/REGON checksums (`ingest/ids.py`), BZP/KPO/TED formats, `vat_basis` required for every money column, sha256 dedup, never overwrite approved rows. When a rule cannot decide (net or gross) a `question` with buttons is returned.
4. **Test run on 50 rows**: the deterministic importer (declarative spec, not generated code) runs inside a transaction that is rolled back; counts and failures are returned; failures are then written as `review_item(kind = 'import', key = 'imp:<code>:row:<n>')` in a separate transaction.
5. **Approve**: saves `importer` (name, version, spec, spec sha256, approved_by) + `review` + audit; the next file whose headers match ≥ 80% reuses it.
6. **Full run**: job `import_mapped {import_code, importer_id}`, same code path with `dry_run = false`, upserts through `upsert_copy` (trigger protects approved rows), one `ingestion_run`, one `source` row per file + manifest line, documents found go to the `doc_text` queue. Progress via `GET /api/jobs/{id}` and the run log.

---

## 4. Exports

- **Lists**: every list screen has a dataset in `/api/export/{dataset}.{json|csv}` (EXISTS, streamed). Add datasets: `signals`, `regions`, `analyses`, `analysis_items` (`?code=`), `reference_class` (`?code=` → the n contracts behind a funnel step), `similar_cases` (`?code=`), `questions`, `question_rows` (`?code=`), `review_decisions` (review table), `audit`, `catalogue_risk`, `catalogue_versions`. Add multi-value `rm_ids`, `sep=semicolon` for Polish Excel (default comma for machines; UTF-8 BOM kept) and access gating: login for `review_items`, `review_decisions`, `audit`, `runs`, `sources`, `link_candidates`, `analyses`; public datasets drop unapproved AI rows. Every export keeps `origin`, `review_status`, `source_id` and money as `_amount/_currency/_vat`.
- **Analysis pack** (`/api/analyses/{code}/pack.*`, `riskminer/analysis/pack.py`):
  - DOCX built with **python-docx 1.2.0 (MIT, verified on PyPI)**: cover (code, version, date, catalogue version, data as-of), summary sentence, reference class + forecast table with n, flags (calc + accepted AI), risk register (code, probability, impact, expected cost, owner), allocation matrix, checklist gaps with evidence states, proposed PPU clauses (catalogue text), annex of sources and quotes (notice number + field code or document + page, URL, retrieved_at, sha256), limitations, method note.
  - PDF: **LibreOffice headless (MPL-2.0, separate binary, installed at `/usr/bin/soffice`)**: `soffice -env:UserInstallation=file:///tmp/lo_<uuid> --headless --convert-to pdf --outdir <tmp> <docx>`, timeout 60 s, one process per call (isolated profile avoids the lock), cached as `exports/packs/AN-2026-0014-v3.{docx,pdf}` keyed by version + hash of included items. Add `libreoffice-writer-nogui` to `infra/Dockerfile.backend`.
  - CSV = risk register rows; JSON = the `analysis_version` snapshot + items.
- **Rejected**: WeasyPrint 70.0 is BSD but pulls Pyphen (GPL/LGPL/MPL 1.1 tri-licence) and needs Pango (LGPL system library); docxtpl 0.20.2 is **LGPL-2.1** (banned).
- Licences checked on PyPI/npm today: python-docx MIT, python-multipart Apache-2.0, itsdangerous BSD-3, google-genai Apache-2.0, sqlglot MIT, schemathesis MIT (dev only; depends on hypothesis MPL-2.0, acceptable as a dev tool), openapi-typescript MIT (frontend).

---

## 5. Auth (recommendation)

**Signed session cookie in the API, demo users from env.** Starlette `SessionMiddleware` (needs `itsdangerous`, BSD-3) with cookie `rm_session` (HttpOnly, SameSite=Lax, Secure in prod, 12 h). Users from `RISKMINER_USERS` in `.env`, format `name:role:scrypt_hash;...` (roles `expert`, `admin`), hashed with stdlib `hashlib.scrypt`; a CLI `riskminer hash-password` prints the hash; no user table. Anonymous visitors get `anon_id` (random) in the same cookie: it owns their analyses/questions and keys the rate limit.

FastAPI dependencies in `api/auth.py`: `current_user()` (User or None), `require_login`, `require_admin`, `owner_or_login(analysis)`, `public_filter(user)` (SQL fragment `(origin <> 'AI' OR review_status IN ('approved','edited'))`). Same-origin deployment removes CORS cookie issues: Vite dev proxy `/api → :8000`; in prod Caddy serves the SPA and proxies `/api`. CSRF: SameSite=Lax + required `X-Requested-With: ex-ante` on non-GET. Rate limit on `/api/ask` and chats: in-process token bucket (10/min per anon id and IP), 429 "Za dużo pytań, spróbuj za minutę.".

Why not Caddy basic auth + `X-Remote-User`: the browser prompt cannot express "public site, optional login" in one SPA, logout is impossible, and a header-trusting API is spoofable if port 8000 is ever reachable. Keep Caddy for TLS (and optional whole-site basic auth during private preview via `RISKMINER_BASIC_AUTH`).

---

## 6. DB migrations

Parallel sessions would fork a linear Alembic chain, so each session owns a **branch off `0006`** (own file, own `branch_labels`, raw `op.execute` SQL like 0003–0006, no autogenerate). Run `uv run alembic upgrade heads` (plural) until the lead adds a merge revision at the 07:00 freeze (`alembic merge -m freeze heads`). `CLAUDE.md` "Run" needs `heads` until then. No edits to `db/models.py` (new tables are used through raw SQL); the lead mirrors them at freeze if needed.

| Rev (branch) | Owner | Change | Alembic note |
|---|---|---|---|
| `0007_analysis` (`analysis`) | A | `record_counter(prefix, year, n, PK(prefix, year))` + function `rm_next_code(prefix)` → `AN-2026-0014` (gapless, rolls back with the transaction, unlike a sequence); `analysis` + `code` UNIQUE, `version int default 1`, `owner text`, `visibility`, `updated_at`; new `analysis_version(analysis_id, version, features, reference_class, results, catalogue_version, data_as_of, seed, reason, created_by, created_at, UNIQUE(analysis_id, version))` with a trigger rejecting UPDATE/DELETE; `analysis_item` + `version`, `key`, `document_id`, `page_no`, `char_start`, `char_end`, `quote`, `verification`, index `(analysis_id, version, section)` | `down_revision = "0006"`, `branch_labels = ("analysis",)`; other branches that issue codes set `depends_on = "0007_analysis"` |
| `0008_question` (`ask`) | L | `question(id, code UNIQUE NULL, status draft\|saved, parent_id, title, question_text, scope jsonb, answer jsonb, sql text, params jsonb, rows jsonb, role, n, llm_call_id, owner, data_as_of, created_at, saved_at)`; `app_setting(key PK, value jsonb, updated_by, updated_at)` for routing overrides; index `llm_call(created_at)` | `depends_on = "0007_analysis"` |
| `0009_review` (`review`) | B | `review_item` + `question text`, `options jsonb`, `model_pick text`, `confidence float`, `target_field text`, index `(status, kind)`; `review` + `option_key`, `undo_of bigint`, `request_id`; `catalogue_version(id, sector, label UNIQUE per sector, summary, changes jsonb, actor, created_at)` seeded with `v1.1` from the current pack; trigger `rm_protect_approved` also on `link_candidate` | the trigger reads `OLD.review_status`, which link_candidate has |
| `0010_data_geo` (`data`) | D | `procedure` + `length_km numeric`, `conn_km numeric`, `length_method text` (regex\|ai\|expert); fill `organization.teryt` (existing column) via job `geo_buyers`; `ref_geo_centroid(terc PK, level, lon, lat)`; recreate `rc_contract` adding `length_km`, `unit_cost_pln_per_km`, `buyer_terc`, `buyer_woj` (DROP + CREATE following `0005`, then both indexes + `ix_rc_contract_geo (buyer_terc)`); view `v_monitor_signal` (core contracts with planned end < `current_date`, no performance notice, `days_overdue`, change-notice count, gmina/powiat/woj, centroid) plus SQL function `monitor_signals(as_of date)` for replay | refresh order: `derive_lengths` → `geo_buyers` → `REFRESH MATERIALIZED VIEW rc_contract` (already in `derive.py`) |
| `0011_ask_views` (`data`) | D | views `v_ask_contract` (rc_contract + Polish woj names + subsector names), `v_ask_change`, `v_ask_signal`, `v_ask_procedure`; `CREATE ROLE riskminer_ro NOLOGIN; GRANT SELECT ON v_ask_* TO riskminer_ro; GRANT riskminer_ro TO riskminer` | `down_revision = "0010_data_geo"` |
| `0012_imports` (`imports`) | D | `import_session(id, code UNIQUE, status, files jsonb, sandbox_path, tool_calls jsonb, mapping jsonb, questions jsonb, answers jsonb, test_result jsonb, importer_id, job_id, created_by, created_at, updated_at)`; `importer(id, name, version, format, spec jsonb, spec_sha256, status, uses int, created_by, approved_by, created_at, UNIQUE(name, version))` | `depends_on = "0007_analysis"` (IMP codes) |

Region aggregates for the map are computed on the fly from `rc_contract` (11 574 core rows, a GROUP BY takes milliseconds, and the filter bar would defeat a materialised view); add `mv_region_stats` only if p95 exceeds 200 ms. Signals stay a plain view because `as_of` replay needs a parameter.

Catalogue additions are YAML, not migrations (data session): `funding_programmes.yaml`, `mitigations.yaml`, `allocation.yaml`, loaded into `catalogue_entry` (`table_name` = `funding_programme`, `mitigation`, `allocation`) by extending `ingest/catalogue.py`.

---

## 7. Module boundaries and file ownership

Package layout (follows `CLAUDE.md` §8: connectors fetch, ingest loads, api reads + review actions, analytics/LLM in their own packages):

```
riskminer/
  api/prov.py               common types (lead, frozen 20:45)
  api/auth.py               session cookie, deps, rate limit (B)
  api/fixtures/*.json       stub responses from the mockups (lead)
  api/routers/
    analyses.py             1.1–1.5, upload, pack endpoints (A; pack handlers call B's pack.py)
    ask.py                  /ask, /questions, chats (L)
    settings.py             /settings/llm (L)
    auth.py, review.py, catalogue_edit.py, projects.py, audit.py, dashboard.py   (B)
    monitoring.py, geo.py, imports.py                                          (D)
    data.py, exports.py, search.py, jobs.py   EXISTS; EXTEND only: data.py projects list (B), exports.py datasets + gating (B), search.py sensitivity filter (D)
  analytics/                pure functions, no FastAPI, no writes (A): refclass.py, forecast.py, unit_cost.py, similarity.py,
                            montecarlo.py, competition.py, allocation.py, flags.py, clauses.py, templates.py (Polish sentences)
  analysis/                 service (A): service.py (create/patch/run/versions), items.py, codes.py; pack.py (B)
  llm/                      (L): gateway.py (google_genai + openai_compatible, routing by sensitivity, llm_call log, caching),
                            verify.py (quote + number verifier, rapidfuzz), tasks/{extract_features, redpen_scan, classify_causes,
                            rescore_gold, nl2sql, chat, import_mapping}.py, prompts/*.md
  review/                   (B): service.py (decide, undo, restore, link correction), queue_sync.py, catalogue.py (versioned edits)
  monitoring/               (D): signals.py, regions.py (SQL), geo.py
  imports/                  (D): sandbox.py (tools), rules.py, runner.py (deterministic importer); LLM call via llm/tasks/import_mapping.py (L)
```

| Session | Owns (only these files change) | Delivers |
|---|---|---|
| **S0 lead** | `pyproject.toml`, `uv.lock`, `api/main.py`, `api/prov.py`, `api/fixtures/`, stub router files (created once, then handed over), `jobs/worker.py` (turns dispatch into a registry each package fills from its own `jobs.py`), `config/config.example.yaml` merges, Alembic merge at freeze | contract online 20:45 |
| **A analytics / Flow 1** | `analytics/**`, `analysis/` except `pack.py`, `api/routers/analyses.py`, `api/schemas_analysis.py`, migration `0007`, `tests/analytics/**`, `tests/api/test_analyses.py` | 1.1–1.5 real |
| **L LLM** | `llm/**`, `api/routers/ask.py`, `api/routers/settings.py`, `api/schemas_ask.py`, migration `0008`, `tests/llm/**`, `tests/fixtures/llm/**`, config `llm:` section | extraction, Red Pen scan, cause classification batch, chats, NL→SQL, gold rescore |
| **B records** | `api/auth.py`, routers `auth/review/catalogue_edit/projects/audit/dashboard`, `review/**`, `analysis/pack.py`, EXTEND in `routers/data.py` (projects list) and `routers/exports.py`, migration `0009`, `tests/api/test_review.py`, `test_auth.py`, `test_exports.py` | login, review, catalogue, card, graph, documents, history, pack |
| **D data-db** (existing) | `ingest/**`, `monitoring/**`, `imports/**`, routers `monitoring/geo/imports`, `search.py` filter, `catalogue/wod-kan/*.yaml`, migrations `0010`–`0012` | length_km, buyer TERYT, signals, map, ask views, import agent |

Shared-file rules: new Pydantic models go in `api/schemas_<area>.py`, not `schemas.py`; nobody edits another session's router; `main.py` includes every router once at 20:45 (stubs), so later work never touches it; job kinds register in `<package>/jobs.py`.

---

## 8. Test plan

**Today** (`backend/tests`): in-process ASGI (`httpx.ASGITransport`) against the loaded main DB; `asyncio_mode = auto`, session loop. `test_api_smoke.py` and `test_search.py` are read-only; `test_pipeline.py` writes permanent `audit_log` rows and toggles `RM-2026-001` approval; `test_link_national.py` reruns the linking stage. Not run for this plan.

**New tests (must not mutate the main DB):**
1. **Transactional fixture** `tests/api/conftest.py`: open one SQLAlchemy connection, `BEGIN`, build `AsyncSession(bind=conn, join_transaction_mode="create_savepoint")`, override `get_session` in `app.dependency_overrides`, roll back at teardown. Works because writes use the request session (rule in §3) and codes come from `record_counter` (rolls back, unlike sequences). Background jobs are tested by calling the service function with the same session. LLM calls use `RISKMINER_LLM_FAKE=1`: the gateway returns recorded responses from `tests/fixtures/llm/<task>/<request_hash>.json`, no network.
2. **Test DB for job/migration tests only**: `CREATE DATABASE riskminer_test TEMPLATE riskminer` (9 GB, minutes; needs no open connections on the template), selected by `DATABASE_URL`; run `alembic upgrade heads` there first. Mark with `@pytest.mark.testdb`.
3. **Contract tests**: (a) `test_contract_paths.py` asserts every path in §2 is in `/openapi.json` with the documented method; (b) schemathesis (MIT; `uv add --dev schemathesis`) on GET endpoints against the running API on the main DB (read-only): `schemathesis run http://127.0.0.1:8000/openapi.json --include-method GET --checks not_a_server_error,response_schema_conformance --max-examples 15` (check flag names on install, v4 renamed several), write endpoints only against the test DB; (c) after 07:00 fail on `X-Fixture: true` for flags that are on.
4. **Provenance assertions**: a recursive walker over responses of `/analyses/{code}`, `/simulate`, `/allocation`, `/projects/{rm_id}/card`, `/graph`, `/monitoring/regions`, `/dashboard`, `/ask` (fake LLM): every object with a numeric `value` has `prov.role` in the four roles; `calc` has integer `n` and `method`; `n < 10` implies `value is None` and `insufficient`; `source` has a ref with notice/field, document/page or url; `ai` has `llm` and a quote `verification`; bare numeric keys outside the whitelist fail the test. Anonymous calls contain no AI item with `review_status` outside approved/edited.
5. **Audit and trigger assertions** (parametrised over every write endpoint): `audit_log` count +≥1 with `actor = 'user:test'` (or `anon:*`) and matching `table_name/row_id`; decisions add a `review` row with `before/after`; undo adds a second `review` and no delete; after approve, an AI-path UPDATE on the same row leaves it unchanged and the API answers 409 for a non-expert write; `UPDATE/DELETE audit_log` raises; the literal `riskminer.expert_write` appears only under `riskminer/review/` (grep test).
6. **Golden numbers** (read-only): demo class SAN + 5–10m + ZiW: funnel 11 574 / 4 339 / 374 / 82 within ±3% (data refreshes), late share 0,63 ± 0,03; simulation output identical for the same seed; Steklin card: +277 days, +40,3%.
7. **Security checks**: `/api/search` and `/api/documents` hide confidential uploads from anonymous callers; `/api/export/review_items.json` returns 401 anonymously; confidential analysis with Bielik down returns 503 and no `llm_call` row with a cloud provider.

---

## 9. Work breakdown and order (now 19:20)

Frontend first: the lead's stubs make the whole contract available at 20:45; each session then swaps fixtures for real code in the order below. Flow 1 (25%) has priority in A and L.

| When | S0 lead | A analytics (Flow 1) | L LLM | B records | D data-db |
|---|---|---|---|---|---|
| 19:45–20:45 | deps (python-multipart, itsdangerous, python-docx, google-genai, sqlglot; dev schemathesis), `prov.py`, fixtures from mockups, all stub routers, job registry (1 h) | `0007` + codes + `analysis/service.py` skeleton (1 h) | gateway: Gemini + openai_compatible, routing, `llm_call` log, fake mode (1.5 h, to 21:15) | `api/auth.py` + login/me/logout (1 h) | `derive_lengths` + `0010` part 1 (length_km) (1 h) |
| 20:45–22:00 | upload endpoint + text extraction (1 h), HackTribe | refclass, funnel, widening, forecast Q1 with bootstrap CI, summary template (1.25 h) | verifier (0.5 h), `extract_features` with page refs (1 h, to 22:45) | review decision service + `0009` + `review_sync` (2.5 h, to 23:30) | `funding_programmes.yaml`, `mitigations.yaml`, `allocation.yaml` (1 h) |
| 22:00–00:00 | integration, frontend support | analysis create/patch/run/get/list/versions real (1.25 h), similarity on structured features (0.75 h; pg_trgm text part after 00:00) | `redpen_scan` with verified quotes + job `analysis_redpen` (1.5 h, to 00:15) | projects list EXTEND + stats (1 h, to 00:15) | `geo_buyers`, `ref_geo_centroid`, rc_contract recreate, `v_monitor_signal`, regions woj + signals endpoints (2.5 h) |
| **00:00 check** | **Minimum cut must be real** (below) | | | | |
| 00:00–03:00 | export gating, CSV `sep` | flags (calc rules), missing items, clauses, Q2 unit cost, Q3 programme end (1.5 h); similarity text part with pg_trgm (0.5 h); Monte Carlo + competition + toggles + tornado (2 h, to 04:00) | `classify_causes` batch on 44 702 unique causes → AI `risk_event` proposals (1 h + runtime), report/project chat (1 h), `/ask` NL→SQL + questions (2 h) | project card (1.5 h), graph Sankey (1.5 h) | powiat/gmina levels, contract detail, geo endpoint (1.5 h); `0011` ask views + ro role (0.5 h) |
| 03:00–06:00 | pack PDF in Docker image | allocation GET/PUT (1 h), reference-class contracts list (0.5 h), what-if params (0.5 h), contract + golden tests (1 h, to 07:00) | `rescore_gold` (1 h), settings endpoints (0.5 h), import mapping prompt (0.5 h) | pack DOCX/PDF/CSV/JSON (2 h), catalogue view + versioned edits + weights (1.5 h) | import agent: `0012`, sandbox tools, rules, test run, approve, `import_mapped` (3 h) |
| 06:00–07:00 | freeze: Alembic merge, fixtures off for flagged-on features, run full tests | documents tab, history, audit, link correction (B, 1.5 h, whichever is left) | | | |

**Minimum by 00:00 (real data, no fixtures):**
1. `POST /api/auth/login`, `GET /api/auth/me` (public/login split works).
2. `POST /api/documents/upload` (public PFU, text pages), `POST /api/analyses` (regex chips; LLM chips with page refs if L is on time), `PATCH /features`, `POST /run`, `GET /api/analyses/{code}` with funnel, Q1 (+ CI, n), similar cases (structured score + contributions), summary sentence, limitations; `analysis_version` snapshot and `AN-2026-NNNN` codes.
3. `GET /api/analyses/{code}/redpen/{doc}` with page text (notes may still be `status: running`).
4. `POST /api/review-items/{id}/decision` + undo for the existing discrepancy and link items, writing `review` + `audit_log`.
5. `GET /api/monitoring/regions?level=woj` + `GET /api/monitoring/signals` (public start page).
6. `GET /api/projects` with metrics.

Everything else keeps serving fixtures behind feature flags until it lands; unfinished features are hidden at freeze (`CLAUDE.md` invariant 7).

**Riskiest parts:** the AI-dependent pieces (Red Pen quotes, the review queue, which today holds 6 items and 0 AI proposals, and NL→SQL safety); buyer → gmina mapping for map levels 4.1a–c (`organization.teryt` empty); `length_km` for the unit-cost question; confidential routing without a running Bielik (demo on a public PFU); parallel Alembic branches; the silent-ignore trigger turning failed writes into fake successes; one LibreOffice process per PDF under load.

**Blockers:** none hard. Needed before 20:45: the lead adds `python-multipart` and `itsdangerous` (uploads and cookies fail without them) and decides the demo PFU (public BZP document recommended). The WCSS/Bielik decision only affects the sovereign-mode demo.
