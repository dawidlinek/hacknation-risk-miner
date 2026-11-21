# Verification, deployment and submission plan

Written Sat 21.11 19:20 for "ex ante" (Risk Miner, MFiPR). Inputs: brief `materials/text/01_tresc_zadania.txt` §4 to §8, `docs/PLAN.md` §8 to §12, `docs/research/04_tech_stack.md` §14 to §16, `docs/scrape.md` §7, `docs/test_report_sources.md`, `design/README.md` §4 and §8, `backend/` and the live DB. Every number marked "measured" was read from `riskminer-db` or a test run at 19:10 to 19:20.

Hard times: feature freeze Sun 07:00, submission complete 10:45, coding ends 11:00 (HackTribe closes), finalists 14:45, pitch 15:15 (about 2 min of demo).

---

## 0. Baseline (measured)

**Repo.** `main` = `b3f366f` + `b20c761` (249 files, pushed 18:13 UTC, repo **private**). No `LICENSE` file, `README.md` is 23 bytes, no `frontend/` yet, no `.github/`. Tracked files contain no key patterns (`AIza…`, `sk-…`, `hf_…`, private keys).

**Tests.** 28 tests in `backend/tests/`:

| Group | Tests | Touches DB | Ran today |
|---|---|---|---|
| Pure (ids, annotation, gmina rules, value rules, chunking, snippets, tsquery) | 15 | no | 15 passed |
| Read-only DB (API smoke 4, search API 4, `test_bzp_copy_counts`, `test_pilot_linked_22_and_discrepancies`) | 10 | reads the national DB | 8 + 2 passed |
| **Mutating** (`test_reference_pairs`, `test_candidate_shape`, `test_rerun_idempotent_and_keeps_expert_rows`, `test_audit_log_append_only`, `test_approved_rows_protected`) | 5 | writes `link_candidate`, `ingestion_run`, `audit_log`, `project` | **not run** |

Result: `23 passed, 5 deselected in 4.6 s` (`uv run --no-sync pytest -p no:cacheprovider --deselect …`). The 5 mutating tests were skipped on purpose: the link tests re-run the `link_national` stage on the shared DB, and the audit test inserts rows into the append-only `audit_log` that can never be deleted. **The main DB already holds 14 `actor='test'` audit rows** from earlier runs; they would show up in the jury's Historia view (handled in §4.3).

Other findings from the run:
- All DB tests hard-code national counts (40 904 contract notices etc.), so none can run in CI as they are.
- `test_search.py` re-includes the search router, which produces duplicate operationId warnings **in tests only**. The live app is clean: 37 paths, 38 operations, unique operationIds.
- No tests yet for connector `parse()` offline, review write paths (there are no review endpoints yet, only `POST /api/jobs`), LLM, analytics or frontend.

**Data quality (measured).**

| Check | Result |
|---|---|
| `source_id IS NULL` on notice, procedure, contract, contract_change, contract_performance, evidence, risk_event | 0 everywhere |
| Money amount without `_vat` basis (procedure, contract_performance, risk_event) | 0 |
| `contract.value_vat` | gross 128 051 / 128 051 |
| `procedure.estimated_value_vat` | net 46 498, null 54 518 (all with null amount) |
| `contract.planned_end_on < signed_on` | **71 rows** |
| `rc_contract`: `planned_days < 0` / `actual_days < 0` / `planned_days = 0` (of 67 562) | **31 / 79 / 17** |
| Pilot contracts whose change rows differ from the declared count (field 5.4.1) | **7 of 27** (RM-002, 003, 006, 015, 020, 021, 022): more rows than declared, likely change notice + performance-notice list double count |
| Structured-field quotes found verbatim in the tag-stripped source notice (seeded sample of 400) | **399 / 400 (99.75%)** |
| `review` rows / `audit_log` rows | 0 / 45 (14 of them `actor='test'`) |

**Host.** 60 GB RAM, swap 19/19 GB used, 39 running containers (three unrelated `tt-iso-*` stacks of ~10 containers each), 239 GB disk free. DB `riskminer` = **9.05 GB** (notice 6.0 GB, external_record 0.7, chunk 0.5, evidence 0.5). `data/` = 56 GB (raw 28, archive 19, ocr 6.9).

---

## 1. Jury test matrix

### 1a. Tests from brief §6

| Jury test | What the jury does | Automated check and pass criterion | Manual demo step | Evidence we hand in |
|---|---|---|---|---|
| **Demonstracja dwóch ścieżek** | Watches (or runs) import + auto-enrichment of ≥1 project, then a new-investment analysis with export | Playwright `@path1` and `@path2` (§2.6) green on the fixture stack in CI and against the live URL after deploy | Path 1: log in, Import i źródła, upload a 1-row XLSX with a project **not** in the 22 (prepare 3 rows, rehearse tonight), "Uruchom wzbogacanie", chain appears on the card in < 2 min. Path 2: §1c new-investment input I1, export JSON + CSV | Video 0:25 to 2:30; screenshots `path1_*.png`, `path2_*.png`; `exports/sample/AN-*.json/.csv` |
| **Errors in the provided set** (implicit: "dane mogą zawierać błędy") | Checks whether we noticed them | `test_pilot_linked_22_and_discrepancies`: review items `part_mismatch` (RM-009), `part_scope_wider` (RM-008), `value_deviation` (RM-007, RM-014), `contract_notice_missing` (RM-022). Pass: all 5 present | Przegląd, tab "Rozbieżności w danych": open Zakrzew, show the quote that proves część 1 | Test report §3 "Rozbieżności wykryte" |
| **Test integracji** | Starts fetching from public sources; judges query correctness, records found, re-runnability | `riskminer scrape bzp_api --since D --limit 50` exits 0, writes `ingestion_run` with queries, fetched, empty, blocked, errors; `report` regenerates `exports/sources_summary.csv`. Pass: 0 errors on the run, every query URL logged | Import i źródła: "Uruchom ponownie" on BZP API, watch the run log fill (job via `SKIP LOCKED` worker), open one fetched notice | Test report §1 (22 sources, queries/fetched/blocked/errors), run-log screenshot |
| **Re-run without manual input** | Runs it twice | Second run of the same window: 0 new `notice` rows for identical bytes (sha256 dedupe), procedure/contract/change counts unchanged, a second `ingestion_run`, expert rows untouched (`test_rerun_idempotent_and_keeps_expert_rows`). Pass: all four | Click re-run, show "0 nowych, N bez zmian" | Run-log table in the test report |
| **Test łączenia** | Compares selected links with its reference set | §1c reference-link check. Pass today: 22/22 correct, 0 uncertain, 0 wrong; KPO reference pairs 10/10 at rank 1 | Project card header: method, score, features, explanation for one exact, one fuzzy and Wolin (cross-reference 0.95) | Test report §4 + `exports/sample/pilot_links.csv` |
| **Test kompletności przypadku** | Checks project → procedures → notices → result → changes → performance, proposed risk events, preserved relations | §1c completeness view. Pass: 22/22 complete chains, every gap is a labelled review item, ≥1 event with evidence per project | Karta projektu Przebieg + Graf powiązań for Biecz (4 contracts) and Wolin (gap) | Test report §3 + completeness table + graph screenshot |
| **Test nowej inwestycji** | Gives a description or documents; expects similar projects, why, comparisons, flags, recommendations, deviation ranges | §1c new-investment suite on inputs I1 to I4 | Path 2 live, with an uploaded PFU | Test report "Analiza nowego projektu" + `AN-*` exports |
| **Test źródłowy** | Picks links and conclusions and checks the cited data or fragment really supports them | `riskminer verify-evidence` (§1c). Pass: ≥ 99% structured quotes found (baseline 99.75%), 100% of approved AI quotes verified, ≥ 95% of sampled URLs answer | Click any number on a project card → BZP notice field (e.g. 5.5) with the quote; click an AI event → PDF page with the highlighted quote | Test report "Weryfikacja źródeł" with the sample list |
| **Test pracy eksperta** | Accepts, corrects or rejects an uncertain match; judges if the basis and uncertainty are clear | §1c expert round trip. Pass: review row + audit row with before/after/reviewer, later results change, AI re-run keeps the decision | Przegląd → Powiązania: one 0.6 to 0.9 KPO candidate (179 are queued), approve one, correct one, reject one; show "Co zmieni Twoja odpowiedź" and Historia | Screenshots + audit-log export `exports/sample/audit_log.csv` |
| **Test założeń** | Judges universality and scalability | (1) `drogi` pack: 55 669 procedures / 133 773 notices loaded by the same code; (2) model switch is a config change (`llm.models.*`); (3) inventory of sector literals in code (today CPV literals live in 7 files: `wodkan_classify.py`, `bzp_api.py`, `bzp_roads.py`, `ted.py`, `bk2021.py`, `link_national.py`, `linking.py`): move to `catalogue/<sector>/` or list them as defaults in the docs | Katalog: switch sector; Ustawienia: provider/location per alias | Architecture doc "Rozszerzanie o sektory", config example |
| **Optional features** (bonus) | Monitoring of unfinished projects, OCR, other formats | Seeded new AgreementUpdateNotice → re-run → alert + card diff (fixture test); OCR import count > 0 | Monitoring map → one late contract → "Obserwuj" | Screenshot + description section "Funkcje dodatkowe" |

### 1b. Criteria from brief §8

| Criterion (weight) | Measurable proof we show | Where |
|---|---|---|
| Acquisition, linking, organisation (20%) | 22 sources with query/fetch/error counts; 248 642 notices, 101 016 procedures, 128 051 contracts; 22/22 pilot links; KPO 10/10; idempotent re-run | Test report §1, §2, §4; Path 1 |
| Document analysis, events, credibility (20%) | 126 134 deterministic events, all with field-code evidence; source check 99.75%; evidence states; limitations section | Test report §4b, §5, "Weryfikacja źródeł" |
| New-investment usefulness (25%) | Similar cases with feature bars; reference class with n and P10/P50/P90; backtest coverage (W3); flags, checklist gaps, clauses each citing cases | Path 2, `AN-*` export, report section |
| Expert control, editable assumptions, modularity (20%) | Approve/correct/reject on links, events, facts, catalogue proposals; audit trail; catalogue edited in UI; second sector pack | Przegląd, Katalog, Historia |
| UX/UI, technical quality, growth (15%) | axe 0 serious/critical; performance budgets met; clean OpenAPI; JSON/CSV export; docker compose deploy; CI green | CI badge, tech docs, screenshots |

### 1c. Detailed checks

**Reference links (Test łączenia).**
- Pilot (22): methods exact_id 14, fuzzy 7 (all score 1.00), cross_reference 1 (Wolin, 0.95). Against our hand-verified set (`research/bzp_linking`): **correct 22, uncertain 0, wrong 0**.
- National KPO → BZP: 578 projects with a candidate: auto-accept 296, review 179, reject 103; 82 exact to the grosz. Reference pairs: beneficiary 10/10, rank 1 10/10, auto-accepts 7/7 correct.
- National CRU → BZP: auto-accept 462, review 52, reject 7.
- Definitions for the report: **correct** = matches the reference or approved by an expert; **uncertain** = decision `review` (0.6 to 0.9) and not yet reviewed; **wrong** = expert-rejected or reference mismatch.
- To add by 07:00 (owner S1): an expert audit of **30 national auto-accepts** (15 KPO, 15 CRU, seeded random) done in Przegląd, reported as precision with a Wilson 95% interval. Optional blind set: 10 Mapa Dotacji projects outside the 22, written as organizer-style rows with 3 injected errors (bad NIP check digit, wrong część, missing BZP number), run through import; report rank-1 accuracy.
- Ask the MFiPR mentors on Discord (PLAN §13 Q6) which identifiers their reference set uses, and mirror that column in `pilot_links.csv`.

**Source test (Test źródłowy).** New CLI `riskminer verify-evidence --n 400 --seed 2211` (owner S1), output into the test report:
1. Structured-field evidence: the quote (first 80 chars, lower-cased, whitespace-normalised) occurs in the tag-stripped, entity-decoded `notice.html_body`. Baseline 399/400. Target ≥ 99%, every miss listed.
2. Document evidence: the quote occurs on `document_page.text` of the cited page, exact or `rapidfuzz.partial_ratio ≥ 95`. Target 100% for approved, ≥ 95% for proposed. DB rule: `verification='unverified'` can never be approved.
3. URL check: 20 random evidence URLs at ≤ 1 req/s per host. Target ≥ 95% HTTP 200; platform blocks are reported as `blocked`, not failures.
4. API contract (fixture DB): every fact in the project card and every `analysis_item` carries `origin`, `review_status`, `source.url`, `retrieved_at`, and either evidence ids or a calculation reference.

**Completeness (Test kompletności).** SQL view `v_pilot_completeness` (owner S1) with one row per pilot contract: contract notice (or flagged cross-reference), result notice, contract, performance, change rows vs declared 5.4.1, events with evidence.
- Measured: every one of the 22 has 1 procedure, 3 to 9 notices, 1 to 4 contracts, a performance notice and 2 to 10 risk events.
- Must fix or flag before freeze: the 7 contracts with more change rows than declared (dedupe change notice vs performance list, or write a `review_item`).
- Known gaps, listed in the report and on the card ("Czego nie wiemy"): **Wolin RM-022** contract notice missing from BZP (linked through 3 later notices, 0.95); RM-019 is a regional roads authority, not found on the VAT whitelist (0/0) and only partly water/sewage; RM-007 Kamionka value −52% vs contracts and 0 changes; RM-008 Biecz 4 parts and wider scope; RM-009 Zakrzew wrong część; RM-014 value −24.5%; signed contracts are generally not public (terms reconstructed from PPU, labelled); `docs_22` 417 blocked downloads; 3 200 scans waiting for OCR; TED 0 matches (all below threshold, recorded as "szukano, nie znaleziono").

**Re-run (Test integracji).** Two runs of the same connector window plus `scripts/scrape_all.sh` on the VM. Pass: run 2 adds no duplicate rows, writes its own `ingestion_run`, keeps expert decisions, needs no input, and respects ≤ 25 req/min on BZP prod (fixed UA, no personal data). Re-analysis on new data: a seeded AgreementUpdateNotice for a watched contract produces an alert and a card diff.

**New investment (Test nowej inwestycji).** Four fixed inputs, run as snapshot tests with replayed LLM responses (§2.5) and once live:

| Input | Content | Expected |
|---|---|---|
| I1 | PLAN §9 text: 6 km sanitary sewer, 3 pumping stations, design-build, PLN 7m, 14 months, KPO | ≥ 3 similar cases with feature bars; reference class n ≥ 30 with P10/P50/P90 and bootstrap CI; budget gauge percentile with n; flags, checklist gaps, clauses each citing ≥ 1 case or catalogue rule |
| I2 | A public PFU from `docs_sample` with a known outcome | Same as I1, plus Red Pen highlights with page quotes; **its own procedure must not appear among similar cases** (exclude by OCID, leakage check) |
| I3 | "Budowa wodociągu w gminie" (almost nothing) | Follow-up question for missing key features; wide ranges and an explicit low-confidence label |
| I4 | "Termomodernizacja budynku szkoły" | "Poza zakresem sektora" message, no fake ranges |

Pass for all: saved as an `AN-…` record, export JSON validates against the published schema, CSV opens in Excel with Polish characters, every value has a source / calculation / AI badge, n < 10 shows "za mało danych", P80/P90 only when n ≥ 50. Runtime < 5 s with replay, < 30 s live. Backtest (W3) coverage reported (target band 80 to 88% inside P10 to P90).

**Expert work (Test pracy eksperta).** `tests/test_review_roundtrip.py` on the fixture DB (owner: whoever builds the review endpoints):
1. Approve a 0.6 to 0.9 link candidate → `review` row, `audit_log` row with before/after and reviewer, status `approved`; re-running `link_national` leaves it unchanged.
2. Reject a link → the procedure leaves the project chain and its card; correct a link → the chain shows the new procedure, status `edited`.
3. Approve a proposed risk event → it appears on the public card (public mode shows approved events only); reject one → it disappears and stays rejected after an AI re-run (`rm_protect_approved`).
4. Mark gold → the next LLM call of that task includes the example (assert on `llm_call` prompt metadata).
5. Change a similarity weight in the catalogue → I1 ranking changes deterministically (snapshot diff).
6. "Cofnij" writes a new review row; `audit_log` UPDATE/DELETE still raises.

---

## 2. Test pyramid

### 2.1 Markers and databases (do this first, owner S0)

Add to `pyproject.toml`: `markers = unit, fixturedb, fulldb, mutates, live, live_llm` and `addopts = "-m 'not mutates and not live and not live_llm'"`.

| Marker | Database | Who runs it |
|---|---|---|
| `unit` | none | CI + everyone |
| `fixturedb` | `riskminer_ci`, loaded from `data/fixtures/` in about 1 min (CI service container, or `riskminer-db-test` on :5435 locally) | CI + local |
| `fulldb` | the national DB, **read-only** (today's 10 read-only tests, re-marked) | local, VM after restore |
| `mutates` | fixture DB, or the national copy on the VM **rehearsal** restore; **never `riskminer` on the host** | local / VM rehearsal |
| `live`, `live_llm` | real network / real model, opt-in via `RISKMINER_LIVE=1` | manual, `workflow_dispatch` |

Rule from now on: no test writes to the shared host DB. A fixture guard raises if a `mutates` test sees `DATABASE_URL` pointing at `riskminer` on :5434.

### 2.2 Backend unit and API

- Unit: ids/NIP/REGON/KPO/BZP normalisers, form-field parser per notice type (one recorded `htmlBody` per type, including a TED-referencing performance notice and a multi-lot result notice), money parser (net/gross, "stan na dzień", delta vs new total), duration parser ("13 miesiące"), chain builder, linker scoring, catalogue loader, change-cause keyword classifier against the 150 gold labels (accuracy recorded, not gated).
- Connector `parse()` offline: each connector gets 1 to 3 recorded raw responses in `data/fixtures/raw/<source>/` with a manifest line; test that `parse()` yields records with `source_id`-ready provenance and no personal contact fields (RODO rule).
- API (`fixturedb`): every GET route returns 200 and validates against its `response_model`; exports for every dataset in JSON and CSV; 404s; review write routes with and without auth (401/403).

### 2.3 Data-quality SQL assertions

`scripts/dq_checks.sql` (owner S1): each query returns `(check, violations)`. CI runs it on the fixture DB (all 0), the release checklist runs it on the national DB and the VM. Non-zero rows that are real-world data problems must be turned into `review_item` rows and excluded from statistics, not fixed silently.

```sql
-- provenance on fact rows
SELECT 'provenance:'||t, n FROM (
  SELECT 'contract' t, count(*) FILTER (WHERE source_id IS NULL OR origin IS NULL OR review_status IS NULL) n FROM contract
  UNION ALL SELECT 'contract_change', count(*) FILTER (WHERE source_id IS NULL) FROM contract_change
  UNION ALL SELECT 'risk_event', count(*) FILTER (WHERE source_id IS NULL) FROM risk_event
  UNION ALL SELECT 'evidence', count(*) FILTER (WHERE source_id IS NULL) FROM evidence) x;
-- money value object and like-with-like
SELECT 'vat:missing_basis', count(*) FROM contract_performance WHERE total_paid_amount IS NOT NULL AND total_paid_vat IS NULL;
SELECT 'vat:contract_not_gross', count(*) FROM contract WHERE value_amount IS NOT NULL AND value_vat <> 'gross';
-- durations (today 71 and 115: must be excluded from rc statistics or carry a review_item)
SELECT 'dur:planned_end_before_signed', count(*) FROM contract WHERE planned_end_on < signed_on;
SELECT 'dur:rc_negative_in_stats', count(*) FROM rc_contract WHERE (planned_days <= 0 OR actual_days < 0) AND late IS NOT NULL;
-- AI safety
SELECT 'ai:unverified_approved', count(*) FROM evidence e JOIN risk_event r ON e.claim_table='risk_event' AND e.claim_id=r.id
  WHERE r.origin='AI' AND r.review_status='approved' AND e.verification='unverified';
-- audit hygiene for the demo snapshot (baseline 14)
SELECT 'audit:test_rows', count(*) FROM audit_log WHERE actor='test';
-- pilot coverage
SELECT 'pilot:unlinked', 22 - count(DISTINCT project_id) FROM project_procedure;
SELECT 'notice:latest_not_unique', count(*) FROM (SELECT notice_number FROM notice WHERE is_latest GROUP BY 1 HAVING count(*) > 1) x;
```

All 12 checks ran read-only against today's national DB at 19:25. Output: every check 0 except `dur:planned_end_before_signed` 71, `dur:rc_negative_in_stats` 115 and `audit:test_rows` 14. These three are the pre-freeze to-dos for S1: exclude the rows from statistics or attach review items; the test rows are handled in §4.3.

### 2.4 Contract tests (OpenAPI ↔ frontend)

- `scripts/export_openapi.py` writes `frontend/openapi.json` from `app.openapi()` (no server needed).
- `openapi-typescript` (MIT) generates `frontend/src/api/schema.d.ts`; CI regenerates and fails on `git diff --exit-code`, then `tsc --noEmit` catches every broken call site.
- Backend test: operationIds unique, every route has a `response_model` and Polish `summary`, every fact schema has `origin`, `review_status`, `source`.
- Optional: Schemathesis (MIT) over GET routes on the fixture stack.

### 2.5 LLM tests

- Gateway provider `kind: replay` (config only, no code path differences): looks up `tests/fixtures/llm/<task>/<sha256(alias, prompt, schema)>.json`; strict mode fails on a missing cassette. `RISKMINER_LLM_RECORD=1` records with a real key locally. The same replay provider is the **demo fallback** when the Gemini quota or network fails.
- CI tests on cassettes: JSON schema conformance; the **quote verifier rejects a fabricated quote** and a changed number (negative cassettes); confidential input is never routed to a non-PL provider (gateway raises); every call writes `llm_call` with provider, model, data_location, tokens; AI rows are inserted as `proposed` and never overwrite approved rows.
- Opt-in live smoke `pytest -m live_llm`: one known-answer call per configured alias (`fast`, `strong`, `sovereign`): valid JSON, the expected R-code for a fixed change cause, latency < 30 s. For Bielik/PLLuM, also a known-answer sanity reply, because a broken vLLM layout returns fluent nonsense.
- Gold-set benchmark (150 change causes, Gemini vs Bielik vs PLLuM): offline script, results stored as a `model_eval` record and quoted in the report; not a CI gate (costs money and needs WCSS).

### 2.6 End-to-end, accessibility, performance (owner S5)

- Playwright (Apache-2.0), tagged specs:
  - `@path1`: login, upload 1-row XLSX, enrich (connectors in offline/replay mode on the fixture stack), card shows chain and sources, export CSV.
  - `@path2`: I1 text, run, report shows similar cases, n, ranges, flags; export JSON and CSV downloaded and schema-validated.
  - `@expert`: approve / correct / reject one item each, Historia shows three entries.
  - `@public`: logged out, an unapproved AI event is not visible; write routes answer 401.
  - `@smoke`: health, Projekty, one card, one search; this subset also runs against the live URL after every deploy.
  - Every spec saves full-page screenshots at 1440×900; the live run produces the submission screenshots.
- axe: `@axe-core/playwright` (MPL-2.0, dev tool only) on Pulpit, Monitoring, Nowa inwestycja, Raport, Projekty, Karta, Przegląd, Katalog with WCAG 2.1 A/AA tags. Pass: 0 critical or serious violations; keyboard-only run through Przegląd.
- Performance budgets (checked on the VM with the national DB):
  - API p95: list routes < 300 ms, project card < 500 ms, search < 1 s (locally 16 GETs took 1.1 s in total).
  - Analysis: < 5 s replay, < 30 s live with visible progress.
  - Initial JS < 300 KB gzip; three.js and the jelly scene lazy-loaded on 1.1 only; Monitoring geometry payload < 1.5 MB (simplified).
  - LCP < 2.5 s on the Monitoring start page.
  - Measure with Playwright navigation timings and a small `httpx` loop (no k6: AGPL).

### 2.7 CI vs local

| Runs in CI (every push) | Runs locally or on the VM only |
|---|---|
| ruff, `unit`, `fixturedb`, DQ SQL on fixtures, OpenAPI drift + `tsc` + eslint + vitest + build, LLM cassette tests, Playwright `@path1 @path2 @expert @public` + axe on the fixture stack, licence gate, secret scan, Docker builds | `fulldb` read-only suite, `mutates` on the VM rehearsal copy, DQ SQL on the national DB, `verify-evidence`, link audit sample, blind set, backtest, live BZP re-run, `live_llm`, performance budgets, `@smoke` against the live URL |

---

## 3. CI

### 3.1 Keeping the big data out

- CI never sees `data/raw` (28 GB), `materials/bzp_kopia` (2.8 GB) or the national DB.
- `riskminer make-fixtures` (owner S1) writes `data/fixtures/` (target < 20 MB):
  - the organizer XLSX (already tracked);
  - BZP notices of the 22 pilot chains (~110 notices) plus a deterministic slice of ~3 000 completed core contracts (enough for n ≥ 30 in the I1 class);
  - 1 to 3 recorded raw responses per connector with manifest lines;
  - 3 small public PDF/DOCX files;
  - LLM cassettes and catalogue YAML (already tracked).
- `riskminer load-all --fixtures` loads them into an empty DB.
- **`.gitignore` trap:** the global `*.jsonl` and `*.jsonl.xz` rules beat `!data/fixtures/`. Add `!data/fixtures/**` after those rules (append-only edit), or store fixtures as `.jsonl.gz`.

### 3.2 Workflow outline (`.github/workflows/ci.yml`)

```yaml
name: ci
on: {push: {branches: [main]}, pull_request: {}, workflow_dispatch: {}}
concurrency: {group: ci-${{ github.ref }}, cancel-in-progress: true}
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      db:
        image: pgvector/pgvector:pg18
        env: {POSTGRES_USER: riskminer, POSTGRES_PASSWORD: riskminer, POSTGRES_DB: riskminer_ci}
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U riskminer" --health-interval 5s --health-retries 20
    env:
      DATABASE_URL: postgresql+asyncpg://riskminer:riskminer@localhost:5432/riskminer_ci
      PGURL: postgresql://riskminer:riskminer@localhost:5432/riskminer_ci
    defaults: {run: {working-directory: backend}}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run pytest -m unit
      - run: psql "$PGURL" -f ../infra/initdb/01_extensions.sql && uv run alembic upgrade head && uv run riskminer load-all --fixtures
      - run: uv run pytest -m fixturedb
      - run: psql "$PGURL" -At -F'|' -v ON_ERROR_STOP=1 -f ../scripts/dq_checks.sql | tee dq.txt && ! grep -E '\|[1-9]' dq.txt
      - run: uv run python ../scripts/export_openapi.py > ../frontend/openapi.json
      - uses: actions/upload-artifact@v4
        with: {name: openapi, path: frontend/openapi.json}
  frontend:
    needs: backend
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: frontend}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: 22, cache: npm, cache-dependency-path: frontend/package-lock.json}
      - uses: actions/download-artifact@v4
        with: {name: openapi, path: frontend}
      - run: npm ci && npx openapi-typescript openapi.json -o src/api/schema.d.ts && git diff --exit-code src/api/schema.d.ts
      - run: npx tsc --noEmit && npx eslint . && npx vitest run && npm run build
  e2e:
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f infra/docker-compose.ci.yml up -d --build --wait   # db + fixtures loader + api(replay LLM) + caddy(web)
      - run: cd frontend && npm ci && npx playwright install --with-deps chromium
      - run: cd frontend && BASE_URL=http://localhost:8080 npx playwright test --grep "@path1|@path2|@expert|@public|@a11y"
      - uses: actions/upload-artifact@v4
        if: always()
        with: {name: playwright-report, path: frontend/playwright-report}
  licences:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: cd backend && uv sync --frozen --no-dev && uvx pip-licenses --python .venv/bin/python --from=mixed --partial-match --fail-on="GPL;AGPL;LGPL;SSPL;Commons Clause;NonCommercial;CC-BY-NC" --format=markdown --with-urls > ../LICENSES_python.md
      - run: "! grep -iE '^name = \"(pymupdf|pymupdf4llm|fitz|ocrmypdf|litellm|psycopg|psycopg2|psycopg-binary|marker-pdf|surya-ocr|mineru|magic-pdf)\"' backend/uv.lock"
      - run: cd frontend && npm ci && npx license-checker-rseidelsohn --production --onlyAllow "MIT;ISC;BSD-2-Clause;BSD-3-Clause;Apache-2.0;0BSD;CC0-1.0;Python-2.0;BlueOak-1.0.0;Unlicense;CC-BY-4.0;OFL-1.1" --markdown --out ../LICENSES_js.md
      - uses: gitleaks/gitleaks-action@v2   # secret scan before the repo goes public
      - uses: actions/upload-artifact@v4
        with: {name: licences, path: "LICENSES_*.md"}
  images:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f infra/Dockerfile.backend -t api:ci . && docker build -f infra/Dockerfile.web -t web:ci .
```

Notes:
- `OFL-1.1` is in the allowlist only for the Geist fonts. Grep `jina-embeddings-v3` and OpenTender in the model and data lists by hand: they are not packages.
- The image ships `poppler-utils` (GPL, used as the `pdftotext` binary in `nik.py`). Either switch to pypdfium2 text extraction (already a dependency) or list it in `LICENSES.md` as an unmodified system tool. Decide before submission.
- `design/assets/jelly-scene.js` needs a stated origin and licence.
- Images are built in CI only to prove the Dockerfiles. The VM builds from the git tag itself (no registry auth, no GB uploads over venue Wi-Fi). Pushing to GHCR is optional once the repo is public.
- A second workflow `live.yml` (`workflow_dispatch`) runs `live_llm` with a `GEMINI_API_KEY` secret and `@smoke` against the live URL.

---

## 4. Deployment for the jury's live link

### 4.1 Options

| Option | Verdict |
|---|---|
| **(a) EU VM + docker compose + Caddy** | **Recommended.** 16 GB RAM, 8 vCPU, ≥ 160 GB disk. Pick **Google Compute Engine `europe-central2` (Warsaw)** if project `hacknation` already has billing (no new account, hosting in Poland, which also helps the data-location story), otherwise **Hetzner** (existing team account, Falkenstein/Nuremberg/Helsinki; new accounts may need ID checks). Cost: a few euros for the weekend. Use a reserved/primary IP so the URL survives a server rebuild |
| **(b) Local Coolify** | **Not viable as the public target.** Checked read-only: the host runs `coolify-proxy` (Traefik v3.6) on :80/:443/:8080 with an **empty `acme.json`** (no certificate ever issued) and no routed apps. The host is `192.168.5.19` on a private LAN (plus `wg0 10.8.0.3` and a `solvro` VPN), so it has no public ingress without router port forwarding. The `coolify-node` VM is 6 vCPU / **4 GB RAM** on libvirt NAT (`192.168.122.240`); its :8000 (Coolify UI) did not answer and :80 returns 404. It is too small for a 9 GB DB, and the host itself is swap-bound. Coolify would add nothing that a tunnel cannot. Also, ports 80/443 on the host are taken, so a host-side Caddy must not try to bind them |
| (b') Host + Cloudflare quick tunnel | **Hot standby only.** `cloudflared tunnel --url http://localhost:8080` (Apache-2.0, outbound only, no account, random `trycloudflare.com` URL, no SLA, traffic via Cloudflare). Pre-test tonight. If `wg0` peers with a public VPS you control, that VPS could reverse-proxy instead |
| (c) Local only | Allowed by §4 only "w przypadku uzasadnionego braku technicznej możliwości"; a weak case for us. Last resort: run instructions + video + screenshots |

### 4.2 Target layout (owner S0)

- `infra/docker-compose.prod.yml` with services `caddy` (serves the built SPA from `/srv` and proxies `/api/*`), `api`, `worker`, `db`.
- **No published DB port.** The dev compose publishes 5434 on `0.0.0.0` with password `riskminer`; prod must not.
- `infra/Dockerfile.web`: node build stage, then the `dist/` folder copied into the caddy image.
- Postgres on 16 GB: `shared_buffers=4GB`, `effective_cache_size=10GB`, `work_mem=32MB`, `shm_size=2gb`.
- Firewall: only 22 (keys only), 80 and 443.

```caddyfile
{$DOMAIN} {
  encode zstd gzip
  header { Strict-Transport-Security "max-age=31536000"; X-Robots-Tag "noindex, nofollow" }
  handle /api/* { reverse_proxy api:8000 }
  handle { root * /srv; try_files {path} /index.html; file_server }
  log
}
```

- HTTPS: `DOMAIN=exante.<ip-with-dashes>.sslip.io`, or a team subdomain. Caddy falls back from Let's Encrypt to ZeroSSL on its own.
- **A domain is better than sslip.io**: after 11:00 the submitted link cannot be edited, but DNS can be repointed to the standby host.

### 4.3 Shipping the DB

1. **Freeze snapshot** on the host, after expert seeding:
   ```
   docker exec riskminer-db pg_dump -U riskminer -Fc --compress=zstd:3 --exclude-table-data=job riskminer > data/snapshots/demo_freeze.dump
   ```
2. **Size estimate.** A 0.45% notice sample compresses 42 MB → 4.1 MB, which puts the notice table at ~0.9 GB. Whole DB: **about 1.5 GB today, about 2.3 GB once `chunk.embedding` (182k × 1024) is filled.** Measure in the rehearsal.
3. **Time estimate.** Dump 10 to 15 min; transfer at the home uplink (`rsync --partial`); restore `pg_restore -j 6 --no-owner --no-privileges` 15 to 30 min including index and HNSW builds.
4. **Post-restore SQL**, one transparent step:
   - disable the audit trigger, delete the 14 `actor='test'` rows, re-enable it;
   - insert one audit row `demo snapshot: removed 14 rows written by automated tests`;
   - `ANALYZE`;
   - `alembic current` must equal head.
5. **Do not trim the national data**: national scale is the pitch. Optional saving: `UPDATE notice SET html_body=NULL WHERE channel='bzp_roads'` (about 1 GB on disk, little in the dump).
6. **Files to ship next to the DB:**
   - **Must:** `data/ref` (8 MB) and `data/raw/docs_22` (3.1 GB, PDFs for the viewer and Red Pen on the 22), plus the demo PFU.
   - **Optional:** the other small raw sources (~2.9 GB) so re-parse works.
   - **Never:** `docs_sample` (18 GB), `bzp_roads` raw (3.4 GB), `data/archive` (19 GB), `data/ocr` (6.9 GB), `materials/bzp_kopia` (2.8 GB).
   - The viewer falls back to page text plus the source URL when a file is absent. rsync `docs_22` during the rehearsal so the morning only syncs the delta.
7. **Embedding model:** `bge-m3` weights (MIT) are downloaded on the VM into a volume at first start, not baked into the image.

### 4.4 Env and secrets

- `/opt/exante/.env`, mode 600, copied with `scp`, never in the image or the repo. It holds:
  - a strong `POSTGRES_PASSWORD` and the matching `DATABASE_URL`;
  - `DOMAIN` and `TAG` (git sha);
  - user hashes `RISKMINER_USERS=jury:<bcrypt>,ekspert:<bcrypt>,admin:<bcrypt>`;
  - **a separate Gemini key for the VM**, restricted to the Generative Language API, with a budget alert. The current key was pasted into a chat: rotate it after the event.
- WCSS (Bielik for confidential uploads) means a tunnel from the VM. Either a dedicated, revocable SSH key on the VM (user's decision), or none: confidential uploads then queue with "model suwerenny niedostępny", and the video shows the sovereign path recorded on the host.
- Gateway: daily token budget, plus a per-IP rate limit on public LLM routes (Zapytaj, analysis).
- CI holds no LLM key except the opt-in `live.yml` secret.

### 4.5 Public vs login (design §4)

- **Public, no login:** Monitoring, Nowa inwestycja, Projekty, cards with **approved** events only, rate-limited Zapytaj.
- **Login:** Przegląd, Katalog, Import, uploads, Historia, Ustawienia.
- Accounts:
  - `jury` (expert role; credentials only in the HackTribe description, never in the repo);
  - `ekspert` (team);
  - `admin` (team).
- The reviewer name comes from the login and lands in `review.reviewer` and `audit_log.actor`.
- Implementation preference: app-level login (cookie session, bcrypt users from env). If that is not ready by 07:00, fall back to Caddy `basic_auth` on the write routes and expert paths, with Caddy passing `X-Remote-User`.
- Jury edits persist. **No reset during judging**: their decisions are the evidence. Seed enough uncertain items: 179 KPO and 52 CRU candidates are already in review.

### 4.6 Health page and smoke

- `GET /api/health` already returns `status` + notice count. Extend `GET /api/health?deep=1` with:
  - DB latency;
  - alembic revision vs head;
  - counts (notices, pilot projects = 22, `rc_contract` core n, chunks);
  - last `ingestion_run` per source;
  - LLM providers reachable (model list call, cached 60 s, no tokens spent);
  - WCSS tunnel up/down;
  - `git_sha`, `built_at`, snapshot name, feature flags.
- The SPA `/status` page ("Stan systemu") shows the same in Polish.
- `scripts/smoke_live.sh $BASE_URL` checks: deep health, `projects?pilot=true` total 22, `RM-2026-022` detail, `export/projects.csv`, `search?q=umowa`, and 401 on a write route without login. Then Playwright `@smoke`.
- An external uptime check (any free monitor) every 1 to 5 min from 08:00 Sunday.

### 4.7 Rollback and fallback ladder

1. Bad code deploy: set `TAG=<previous sha>`, then `docker compose up -d --build` (the VM keeps the previous build; 2 to 3 min).
2. Bad data: `scripts/restore_demo.sh` restores `demo_freeze.dump` (20 to 30 min). Only if the data is broken, never to undo jury actions.
3. VM down: move the reserved IP (or the DNS) to a new VM from the same dump; or start the cloudflared standby on the host and post the URL on Discord and in the HackTribe description (editable until 11:00 only).
4. Everything down: the video (GitHub release asset + YouTube unlisted), screenshots, and the run instructions in the README.

### 4.8 Deployment timeline

| When | Step | Owner |
|---|---|---|
| Sat 20:00-21:00 | User decides (a) GCE vs Hetzner, domain vs sslip.io; VM created; Docker; Caddy hello world on HTTPS | S0 + user |
| 21:00-00:00 | `docker-compose.prod.yml`, `Dockerfile.web`, Caddyfile, `smoke_live.sh`, deep health, CI skeleton | S0 |
| Sun 00:00-02:00 | **Rehearsal:** dump the current DB → restore on the VM → smoke; record dump/transfer/restore times; rsync `docs_22`; test the cloudflared standby | S0 |
| 02:00-03:00 | `mutates` suite + Playwright against the VM rehearsal DB; performance budgets | S0 + S5 |
| 07:30-08:15 | Final dump → restore → post-restore SQL → smoke → live | S0 |

### 4.9 What the user must decide or provide

1. **Hosting account:** GCE in project `hacknation` (is billing enabled?) or an existing Hetzner account, plus a budget (≈ €10).
2. **Domain:** a team subdomain (recommended, repointable) or sslip.io.
3. **Credentials:** passwords for `jury` / `ekspert` / `admin`; a separate restricted Gemini key for the VM.
4. **WCSS on the VM:** a dedicated SSH key, yes or no.
5. **Unrelated containers:** may the three `tt-iso-*` stacks be stopped during the dump/restore and recording window, to relieve RAM?
6. **Commits:** a standing "yes" for the integrator's checkpoint commits and pushes (CLAUDE.md says "commit nothing unless asked").
7. **Making the repo public** at 10:30, after the secret scan.
8. **Two open licence questions:** `poppler-utils` in the image, and the origin of `jelly-scene.js`.

---

## 5. Submission deliverables

Owner roles: **Lead** (human team lead, HackTribe account), **S0** integrator/ops, **S1** data, **S2** scraping, **S3** LLM, **S4** analytics, **S5** frontend, **Presenter** (human).

| Deliverable | Owner | Slot (Sun) | Source |
|---|---|---|---|
| Prototype link + jury login | S0 | live 08:15, re-check 10:15 | §4; credentials go in the HackTribe description only |
| Title + description | Lead | 09:30-10:00 | `docs/submission/hacktribe_draft.md`, numbers refreshed from `/api/stats` and the test report |
| PDF ≤ 10 slides | Presenter + S4 | 07:30-09:30 | PLAN §9 storyline, live numbers, 3 to 4 screenshots → `docs/submission/ex_ante_prezentacja.pdf` |
| Repo | S0 | public at 10:30, tag `submission` | gitleaks clean, `LICENSE` (MIT), README with run steps and the live link |
| Video ≤ 3 min | Presenter + S5 | record 08:15-09:00 on the live VM, edit 09:00-09:45 | PLAN §9 script with Polish captions. **Uploaded as a GitHub release asset in the public repo** (literally an open repository, as §4 asks) **and YouTube unlisted** |
| Description ≤ 10 pages, working vs designed | Lead (each session writes its half page) | 07:30-09:30 | Feature flags at freeze (`true` = works, `false` = designed), design mockups exported as PNG (the design canvases are private artifacts) → `docs/submission/opis.pdf` |
| Technical docs | S0 (architecture), S1 (data model, sources, matching), S3 (models, data location) | 07:30-09:30 | `docs/ARCHITECTURE.md` (PLAN §4 diagram as mermaid), ER diagram generated from `information_schema` as mermaid, `docs/SOURCES_AND_LINKING.md` (scrape.md + PLAN §6), `docs/RUN.md` (CLAUDE.md Run), `docs/LICENSES.md` (CI artefacts + models: bge-m3 MIT, Bielik Apache-2.0, PLLuM variant + services: Gemini, WCSS, VM provider), `docs/DATA_PROCESSING.md` (local / PL / EU / global per component) |
| Test report | S1 (links, sources, completeness), S4 (analysis, backtest) | 07:00-08:00 | `riskminer report` → `docs/test_report_sources.md` + new sections: link quality correct/uncertain/wrong, audit sample, verify-evidence, completeness table, DQ results, I1 to I4 results, backtest; also as PDF |
| Sample structured export | S1 + S4 | 08:00 | `exports/sample/`: `projects.json/.csv` (22), `pilot_links.csv`, `review_items.json`, `risk_events.csv`, `audit_log.csv`, `AN-*.json/.csv`; < 5 MB, committed |
| Config example | S0 + S3 | 07:00 | `config/config.example.yaml` + `.env.example`: final model ids, flags matching the freeze, `data_location` per provider, licence line |
| Screenshots | S5 | 08:15-08:45 | Playwright run against the live URL → `docs/submission/screenshots/` (10 to 12 screens, Polish UI) |

**HackTribe and Discord.**
1. **Before 20:00 today (hard):** create the project, choose Risk Miner, fill team name, repo URL, table number and the preliminary description from `hacktribe_draft.md`. After 20:00 no new project and no task change.
2. The Lead adds every member (first name, last name, email).
3. **Every member needs a Discord account** on the HackNation server before the final submission. Check it now, not at 10:40.
4. Ask mentors on Discord (`#zapytaj-organizatora`, MFiPR mentors) about the linking reference set (PLAN §13 Q6).
5. By 10:45: every field filled, PDF uploaded, links for prototype, repo, video and docs. Then open every link in a private window, logged out.
6. 11:00: the submission locks. Leave the VM untouched. 14:45: finalists on Discord. 15:15: ≤ 2 min live pitch, using the same demo path with `@smoke` run at 15:00.

---

## 6. Release checklist and git strategy

### 6.1 Git strategy: one shared checkout, path ownership, single committer

Recommendation: **stay in the shared checkout on `main`**; do not move running sessions to worktrees tonight. Reasons:
- `data/` (56 GB), `materials/`, `.env`, `config/config.yaml` and `backend/.venv` are untracked and shared. Worktrees would need symlinks for each.
- All sessions share one Postgres anyway, so worktrees do not isolate the main hazard (schema and data).

Rules:
1. Each session edits only its owned paths (as in `docs/sessions/*.md`). Shared files (`main.py` router list, `pyproject.toml`, `config.example.yaml`, `.gitignore`) get small appended edits only.
2. **Single committer** (S0) commits path-scoped (`git add <paths>`, never `git add -A`), with the message prefixed by the session (`data:`, `ui:`, `llm:`), then pushes.
3. **Alembic:** one owner (S1). Others ask for a migration. `alembic heads` must print one head before any upgrade.
4. Only S0 runs `uv add` / `npm install` on shared manifests. Everyone else uses `uv run --no-sync`.
5. **Cadence:** a commit and push after every checkpoint (20:00, 00:00, 04:00), plus whenever a feature turns green; at the latest every 90 min. Tags: `rehearsal`, `freeze-0700`, `submission`.
6. One worktree is acceptable only for a self-contained throwaway experiment, never for a running session.

### 6.2 Checklist 06:30 to 10:45

| Time | Item | Owner |
|---|---|---|
| 06:30 | Last merges; every unfinished feature flag set to `false` in config | all → S0 |
| 07:00 | **Freeze.** Commit + tag `freeze-0700`; after this only fixes for failing checks, copy, docs | S0 |
| 07:00 | CI green (unit, fixturedb, DQ, contract, e2e, axe, licences, gitleaks) | S0 |
| 07:00 | `fulldb` read-only suite and DQ SQL on the national DB; every non-zero result is either a review item or a fix | S1 |
| 07:00-07:30 | Expert seeding through the UI: approve 10, correct 3, reject 3, mark 2 gold; audit sample of 30 links done | team expert |
| 07:15 | `riskminer report`, `verify-evidence`, completeness table, I1 to I4 analyses saved, sample exports written | S1 + S4 |
| 07:30 | Final dump → VM restore → post-restore SQL → `smoke_live.sh` + Playwright `@smoke` green | S0 |
| 08:15 | Live link confirmed in a private window, logged out and logged in as `jury` | S0 + Lead |
| 08:15-09:00 | Screenshots (Playwright) and video recording on the live VM | S5 + Presenter |
| 09:00-10:00 | Slides PDF, description PDF, tech docs, LICENSES, DATA_PROCESSING; numbers cross-checked against `/api/stats` | Lead + S0 + S3 |
| 10:00 | Video uploaded (release asset + YouTube); README links final; `exports/sample` committed | Presenter + S0 |
| 10:15 | gitleaks clean → **repo public** → tag `submission` → push | S0 (user approves) |
| 10:30 | HackTribe: all fields, PDF, links, jury credentials; Discord accounts confirmed for every member | Lead |
| 10:45 | **Submitted.** Re-open every link logged out. Until 11:00 only text edits in HackTribe | Lead |
| after 11:00 | No deploys. Uptime monitor on; `@smoke` at 14:30 and 15:00 before the pitch | S0 |

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Demo breaks live (bug, empty state, slow query) | Freeze at 07:00; `@smoke` after every deploy; rehearsed demo path with prepared inputs (3 XLSX rows, I1, the PFU); replay LLM provider as a switch; fallback video. Pitch from a pre-loaded browser tab with the analysis already saved |
| Network (venue Wi-Fi, home uplink for the dump) | VM builds from git, not from uploaded images; `docs_22` rsynced during the rehearsal; morning transfer is only the dump (~1.5 to 2.3 GB, `rsync --partial`); phone hotspot as backup for the presenter |
| Host is a home PC behind NAT (power or ISP loss kills dev and standby) | The jury link lives on the VM, which is independent of the host after the restore; keep the freeze dump on the VM and on WCSS |
| LLM quota or cost (Gemini rate limits, jury traffic, public Zapytaj) | Pre-computed analyses for the demo inputs; response cache by prompt hash; daily token budget + per-IP limit; budget alert on the key; replay fallback; deterministic parts (reference class, similarity, flags) do not need the LLM |
| BZP prod limit (25 req/min) hit while the jury runs Test integracji | Jobs are serialised by the worker with visible progress; `--limit` defaults small; the mirror `bzp.cytr.us` is a config switch |
| WCSS unavailable (Bielik/PLLuM jobs end, tunnel drops, OCR unfinished) | Sovereign mode degrades to a visible "model suwerenny niedostępny" queue, never to a cloud model for confidential data; Bielik → PLLuM fallback; OCR results imported before freeze and the remaining count stated; the sovereign path is in the video |
| Host RAM (swap full, 39 containers, Postgres + dump + Playwright + video capture) | Ask to stop the unrelated `tt-iso-*` stacks during 07:00 to 09:00; run the dump before recording; record on the VM, not the host; no `mutates` runs on the host |
| Tests or sessions write junk into the shared DB | `mutates` marker + DB-name guard; the 14 test audit rows are removed transparently in the snapshot; DQ check `audit:test_rows = 0` on the VM |
| Jurors' concurrent edits clash, or one bad edit | Per-action review rows and "Cofnij"; the audit trail shows who did what; restore only if the data is broken |
| Secrets leak when the repo goes public | `.env` and `config/config.yaml` are ignored; gitleaks in CI and before 10:15; separate restricted VM key; rotate the chat-exposed Gemini key after the event |
| Licence surprise at the copyright transfer | CI licence gate + banned-name grep; decide on `poppler-utils` and `jelly-scene.js`; models and services listed by hand |
| Certificate issuance fails (sslip.io limits, DNS) | Caddy falls back from Let's Encrypt to ZeroSSL; a team subdomain as plan B; test the certificate at 21:00 Saturday, not Sunday |
| Link cannot be changed after 11:00 | A repointable domain or a reserved IP; the standby is reachable at the same name |
| Missing pieces at freeze (no frontend today, no review endpoints, no LLM gateway) | Feature flags hide them; the description's "zaprojektowane" section with mockups; the matrix in §1 tells each owner which jury test depends on their piece |
