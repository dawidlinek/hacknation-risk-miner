# LLM layer: implementation plan (session L)

Written 2026-11-21 19:30 for the LLM session. Inputs: `docs/PLAN.md` §4a, `docs/research/04_tech_stack.md` §4,
`docs/flow1_build_plan.md`, `design/README.md` §3 and §6, the mockups A1, A2, A3, A6, B1, C1, C2, `catalogue/wod-kan/*.yaml`,
`config/config.example.yaml`, the gold set, the live DB, and the sibling plans `docs/impl/api_contract.md` (task names,
`Answer` type, migration branches, file ownership) and `docs/impl/verification.md` (replay cassettes, live smoke).
Everything marked **measured** was run tonight against the Gemini Developer API with the team key (spend below $0.50).
Scripts and raw outputs: `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/llm/`
(scratch, not in the repo; the verifier prototype `verify.py` there is the starting point for `llm/verify.py`).

## 0. Verdict and live-check results

**Gemini covers every task we need, today, with the key we have.** Structured JSON, PDF input with page numbers,
function calling, explicit caching, the OpenAI-compatible endpoint and the Batch API all work. Quotes come back verbatim
and on the right page. The only hard gap is EU data location (Vertex is blocked for the key), which the sovereign route
(Bielik/PLLuM on WCSS) covers for confidential documents.

| Check | Result (measured) |
|---|---|
| (a) JSON-schema output | Works on `gemini-3.5-flash-lite` (1.5 s, 114 in / 318 out tokens) and `gemini-3.8-flash` via `generationConfig.responseJsonSchema` (REST) and `response_json_schema` / Pydantic `response_schema` (SDK 3.6.1, `.parsed` filled). "ok. 6 km" was marked uncertain by both; `przylacza` correctly listed as missing. **Gotchas**: flash-lite rejects `thinkingBudget: 0` (HTTP 400; omit thinking config or use `thinkingLevel`); flash thinks by default (463 thought tokens, 8.4 s; `thinkingLevel: low` 5.7 s, `thinkingBudget: 0` 4.6 s). Money parsing is inconsistent ("7 mln" came back as 7000000 in one run and 7 + unit "mln zł" in another), so code parses numbers from quotes |
| (b) PDF input + page quotes | Inline PDF and Files API both work (upload 2.3 s, state ACTIVE at once, file expires after 48 h, deleted after the test). Steklin PFU (doc 30011, 26 pages): 14,451 prompt tokens as PDF vs 19,140 as page-tagged text. Sulmierzyce PPU (doc 30606, 14 pages): 8,067 vs 15,496. **86 quotes over 8 runs: 76 exact on the stated page (88.4%), 78 exact or fuzzy (90.7%), 85 after the cross-page and table-cell rules (98.8%), 1 unverified, 0 on a wrong page.** Numeric check: only 4 of 13 numeric chips had their number inside the quote; the 9 failures were totals the models computed from tables (network length 945, 1,015 and 1,175 mb in three runs, none printed in the PFU). See §3 |
| (c) Function calling | A 4-tool import loop (`list_archive` → `sample_rows` → `ask_user` netto/brutto → `propose_mapping` → summary) ran correctly on both models. flash-lite: 5 turns, 3.0 s, 3,893 tokens. flash: 18.3 s, 7,204 tokens. Every turn carries a `thoughtSignature`; echo model parts back verbatim |
| (d) Context caching | Explicit `cachedContents` works on both. **Minimum 1,024 tokens** (`HTTP 400 ... min_total_token_count=1024`). 18,402-token catalogue cache: create 1.2 s, cached call 0.8 s on flash-lite, `cachedContentTokenCount` 18,422. Implicit caching was not observed on two back-to-back identical 18k prefixes; do not budget on it |
| (e) OpenAI-compatible `/v1beta/openai/` | `GET /models` lists 65 models. `chat.completions` with `response_format: json_schema, strict: true` works (flash-lite 0.7 s, flash 2.3 s with `reasoning_effort: "low"`); `tools` return `tool_calls` (0.5 s). Responses carry `extra_content.google.thought_signature`, which must be sent back in multi-turn tool use |
| (f) Batch API | `models/gemini-3.5-flash-lite:batchGenerateContent` with inlined requests works; two 3-request jobs took 123 s and 168 s (PENDING → RUNNING → SUCCEEDED). Half price. **Gotcha**: inside inlined batch requests the camelCase `responseJsonSchema` is silently ignored (output came back as `{"kod_ryzyka": ...}`); snake_case `response_json_schema` and `responseSchema` are honoured. Always Pydantic-validate |
| (g) Licences (PyPI, today) | `google-genai` 3.6.1 **Apache-2.0**; deps anyio MIT, google-auth Apache-2.0, **httpx2 2.16.2 BSD-3**, pydantic MIT, requests Apache-2.0, tenacity Apache-2.0, websockets BSD-3, typing-extensions PSF-2.0, distro Apache-2.0, sniffio MIT/Apache. It pins `tenacity<9.2.0`, so `uv` moves our lock from 9.2.1 to 9.1.4 (our spec is `>=9.0`, fine). `openai` 3.57.0 Apache-2.0, `sqlglot` 30.33.0 MIT, `rapidfuzz` 3.14.6 MIT (already a dependency) |
| (h) Latency and tokens | Table below |
| Billing | `gemini-3.1-pro-preview` answered (2.3 s); the pricing page lists no free tier for it, so the project is on the paid tier (prompts not used for training). Rate-limit tier unknown: check AI Studio before the bulk run |

**Latency and tokens (measured, single requests from the dev box):**

| Shape | flash-lite 3.5 | flash 3.8 (thinking low) |
|---|---|---|
| Chips from a one-line description | 1.5 s, 114 in / ~320 out | 4.6 to 5.7 s |
| Chips + signals, 26-page PFU as PDF | 5.4 s, 14.5k in / 1.1k out | 13.7 s, 14.5k in / 1.6k out |
| Same, page-tagged text | 3.1 s, 19.1k in | 14.8 s |
| 14-page PPU via Files API | 3.9 s, 8.1k in | 18.3 s |
| Report chat over a 6-fact JSON | 0.8 s, 580 in / ~100 out | 2.2 to 2.7 s |
| NL→SQL (view description in prompt) | 0.7 to 0.8 s, 350 in / ~95 out | 2.2 s |
| Tool loop, 5 turns | 3.0 s total | 18.3 s total |
| Cause classification, 1 item | median 0.74 s, ~800 in / ~63 out | median 2.7 s |
| Cause classification, 20 items packed | 3.5 s, 5,061 in / 1,713 out | 12.5 s |
| Cached 18k prefix, short answer | 0.8 s | 2.7 s |

Without a thinking cap, flash spent 15 to 41 s and 1,274 to 4,761 thought tokens on a one-word question over a partial
catalogue, and invented R04/R05 for "weather" where flash-lite answered "brak". **Always set `thinking_level: low` on
flash and always give the full label set with an explicit "none of these" option.**

**Prices** (paid tier, USD per 1M tokens, aistudio.google.com/docs/pricing today; flash prices double on 2027-01-01):

| Model | Input | Output (incl. thinking) | Cached input | Batch in / out | Cache storage per 1M per hour |
|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 0.30 | 2.50 | 0.03 | 0.15 / 1.25 | 1.00 |
| gemini-3.1-flash-lite | 0.25 | 1.50 | 0.025 | 0.125 / 0.75 | 1.00 |
| gemini-3.8-flash | 0.75 | 3.75 | 0.075 | 0.375 / 1.875 | 0.50 |
| gemini-3.1-pro-preview | 2.00 (≤200k) | 12.00 | 0.20 | 1.00 / 6.00 | 4.50 |

**Mini accuracy probe** (20 stratified gold causes, zero-shot, 21 label definitions, details in §4):
flash-lite 3.5 **14/20** single-item and 15/20 packed; flash-lite 3.1 15/20 and 15/20; flash 3.8 16/20 and 14/20;
keyword rules had the gold primary among their codes for 11/20. Quotes in the classification output: 20/20 exact for
flash-lite 3.5 single-item.

## 1. Gateway design

### 1.1 One entry point, three backend kinds

```python
class LLMRequest(BaseModel):
    task: str                       # "extract_features", "redpen_scan", ... (catalogue in §2)
    sensitivity: Literal["public", "confidential"]
    input_refs: list[str] = []      # "document:30011", "analysis:AN-2026-0014": the gateway re-reads sensitivity from them
    subject: str | None = None      # logged, e.g. "analysis:AN-2026-0014"
    prompt: PromptRef               # name + version; system text loaded from llm/prompts/<name>.md
    parts: list[Part]               # Text | PageText(doc_id, page, text) | PdfFile(doc_id, path) | Json(obj)
    output: type[BaseModel] | None  # Pydantic schema → JSON schema
    tools: list[ToolSpec] | None = None
    alias: str | None = None        # override; default from llm.tasks[task][sensitivity]
    cache_prefix: bool = False      # explicit cache for a shared prefix ≥ 1,024 tokens
    max_output_tokens: int = 4096

class LLMResult(BaseModel, Generic[T]):
    data: T | None; text: str; tool_calls: list[ToolCall]
    llm_call_id: int; provider: str; model: str; alias: str; data_location: str
    tokens_in: int; tokens_out: int; tokens_cached: int; tokens_thought: int
    cost_usd: float; latency_ms: int; attempts: int; fallback_from: str | None

async def run(req: LLMRequest) -> LLMResult            # route → call → validate → log
async def run_tools(req, impls: dict[str, Callable], max_steps=12) -> LLMResult
async def run_many(reqs, concurrency=16) -> list[LLMResult]   # online fan-out with adaptive concurrency
async def submit_batch(reqs) -> BatchRef; async def collect_batch(ref) -> list[LLMResult]   # Gemini Batch API
```

| Kind | Library | Used for | Notes from the live checks |
|---|---|---|---|
| `google_genai` | `google-genai` 3.6.1 (Apache-2.0) | Gemini Developer API now; Vertex EU later with `vertexai: true, project, location` (config only) | `response_json_schema=Model.model_json_schema()`; `ThinkingConfig(thinking_level="low")` on flash, no thinking config on flash-lite; PDF via `Part.from_bytes` or Files API; `caches.create` for prefixes ≥ 1,024 tokens; batch with snake_case keys; keep `thought_signature` by appending the returned `Content` unchanged |
| `openai_compatible` | `openai` 3.57.0 (Apache-2.0) | vLLM (Bielik, PLLuM) on WCSS; Gemini `/v1beta/openai/` as a no-lock-in demo | `response_format={"type":"json_schema", "json_schema": {..., "strict": true}}` (vLLM uses guided decoding); `reasoning_effort` only for Gemini; preserve `extra_content` on tool calls; health via `GET /v1/models` |
| `replay` | none | CI and demo fallback (`verification.md` §2.5) | Looks up `tests/fixtures/llm/<task>/<request_hash>.json`; strict mode fails on a miss; `RISKMINER_LLM_FAKE=1` forces it, `RISKMINER_LLM_RECORD=1` records real calls |

We call the SDK rather than raw REST because the Vertex EU switch is one constructor flag. A raw-REST fallback exists
in the scratch prototype (`g.py`) if the SDK misbehaves. Claude/OpenAI stay commented out in config. No LiteLLM.

Every request is turned into the backend call by one adapter per kind: system prompt, parts (page text wrapped as
`<page n="14" doc="30011">…</page>`), schema, tools, generation parameters from `llm.model_params`. Output handling is
common: parse JSON, validate with Pydantic, run task verifiers (§3), sanitise user-visible strings (U+2014 em dash → ", ",
U+00B7 middle dot removed, design copy rule), strip personal contact data from quotes (e-mail and phone regex,
`CLAUDE.md` invariant 9; the Steklin PFU title page carries a designer's phone and e-mail).

### 1.2 Config (proposed `llm:` block for the lead to merge into `config.example.yaml`)

```yaml
llm:
  providers:
    gemini:      {kind: google_genai, api_key_env: GEMINI_API_KEY, data_location: "global (Gemini Developer API)"}
    # gemini_eu: {kind: google_genai, vertexai: true, project: "114919147642", location: europe-west4, data_location: "EU (Vertex AI)"}
    gemini_oai:  {kind: openai_compatible, base_url: https://generativelanguage.googleapis.com/v1beta/openai/, api_key_env: GEMINI_API_KEY, data_location: "global (Gemini Developer API)"}
    wcss_bielik: {kind: openai_compatible, base_url: http://127.0.0.1:8001/v1, api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wrocław)", sovereign: true}
    wcss_pllum:  {kind: openai_compatible, base_url: http://127.0.0.1:8002/v1, api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wrocław)", sovereign: true}
    replay:      {kind: replay, dir: tests/fixtures/llm, data_location: "lokalnie (nagrane odpowiedzi)"}
  models:                      # alias -> provider:model
    fast:          gemini:gemini-3.5-flash-lite
    strong:        gemini:gemini-3.8-flash
    best:          gemini:gemini-3.1-pro-preview      # nothing defaults to it; manual upgrade only
    bulk:          gemini:gemini-3.5-flash-lite       # or gemini-3.1-flash-lite after the 150-item eval (§4)
    sovereign:     wcss_bielik:bielik-11b              # served name; weights speakleash/Bielik-11B-v3.1-Instruct
    sovereign_alt: wcss_pllum:pllum-12b                # weights CYFRAGOVPL/PLLuM-12B-instruct-2512 (Apache-2.0)
  model_params:
    gemini-3.8-flash:      {thinking_level: low}
    gemini-3.1-pro-preview: {thinking_level: low}
    bielik-11b:            {temperature: 0.1, max_tokens: 2048}
    pllum-12b:             {temperature: 0.1, max_tokens: 2048}
  tasks:                       # task -> alias per sensitivity; a missing confidential entry means "refuse"
    extract_features:    {public: strong, confidential: sovereign}
    redpen_scan:         {public: strong, confidential: sovereign}
    classify_causes:     {public: bulk}
    chat:                {public: strong, confidential: sovereign}
    nl2sql:              {public: strong}
    import_mapping:      {public: fast, confidential: sovereign}
    catalogue_proposals: {public: strong}
    review_phrasing:     {public: fast}
    rescore_gold:        {public: bulk}
  fallback:                    # tried in order after retries; confidential keeps only sovereign targets
    strong: [fast]
    fast: [strong]
    bulk: [fast]
    sovereign: [sovereign_alt]
  demo_replay_fallback: false  # true only for the recorded demo: last resort, shown as "odtworzenie nagranej odpowiedzi"
  budget: {usd_per_day: 40, usd_per_run: {classify_causes: 15, eval: 5}, warn_at: 0.8}
  retries: {max_attempts: 3, backoff_s: [1, 4, 15], on: [429, 500, 502, 503, 504, timeout], repair_on_invalid_json: 1}
  timeouts_s: {interactive: 30, document: 120, batch_call: 300}
  concurrency: {gemini: 16, wcss_bielik: 64, wcss_pllum: 64}
  health: {interval_s: 30, kat_on_first_use: true}
  prices_usd_per_mtok:         # update when Google changes them; flash doubles on 2027-01-01
    gemini-3.5-flash-lite: {in: 0.30, out: 2.50, cached: 0.03, batch_in: 0.15, batch_out: 1.25}
    gemini-3.1-flash-lite: {in: 0.25, out: 1.50, cached: 0.025, batch_in: 0.125, batch_out: 0.75}
    gemini-3.8-flash:      {in: 0.75, out: 3.75, cached: 0.075, batch_in: 0.375, batch_out: 1.875}
    gemini-3.1-pro-preview: {in: 2.00, out: 12.00, cached: 0.20, batch_in: 1.00, batch_out: 6.00}
    bielik-11b: {in: 0, out: 0}   # GPU-hours tracked separately
    pllum-12b:  {in: 0, out: 0}
  eval:
    gold_set: research/bzp_corpus/data/gold_change_reasons.csv
    models: [fast, bulk, strong, sovereign, sovereign_alt]
```

Change versus PLAN §4a: `fast` becomes flash-lite (0.7 to 1.5 s measured, 3 to 5 times faster than flash with thinking
low); `strong` stays flash with thinking low. Routing overrides set in Ustawienia go to `app_setting` (migration 0008,
contract §6) and are validated by the same rules.

### 1.3 Routing by sensitivity

```
route(req):
  sens = max(req.sensitivity, sensitivity(r) for r in req.input_refs)   # caller cannot downgrade
  alias = req.alias or cfg.tasks[req.task][sens]          # KeyError → RefusedForSensitivity
  chain = [alias] + cfg.fallback.get(alias, [])
  targets = [resolve(a) for a in chain]
  if sens == "confidential":
      targets = [t for t in targets if t.provider.sovereign and t.provider.data_location.startswith("PL")]
      if not targets: raise SovereignUnavailable          # API answers 503 sovereign_unavailable, job stays queued
  targets = [t for t in targets if health.ok(t.provider)] or raise ProviderDown
  budget.check(estimate(req, targets[0]))                  # BudgetExceeded before any network call
  return targets
```

- Public sources (BZP, TED, NIK, KIO, BIP, the 22 pilot packages) may use any provider. Uploaded pre-tender documents
  are `confidential` by default (contract §2.2); the demo PFU is a public BZP document marked `public`.
- `confidential` never reaches a provider without `sovereign: true`, including via fallback, replay or the
  OpenAI-compatible Gemini route. Tested in CI (§6.2). The PDF part kind (Gemini file upload) is refused for
  confidential input: sovereign models get page-tagged text only.
- Every response carries `processing: {provider, model, data_location}` for the "przetworzono w Polsce" badge.

### 1.4 `llm_call` logging

One row per backend attempt (retries and fallbacks are separate rows), written in its own short transaction so failures
are logged even when the caller's transaction rolls back. Existing columns: `task, provider, model, alias, data_location,
sensitivity, request_hash, tokens_in, tokens_out, cost_usd, latency_ms, status, error, request, response, created_at`.
Add in migration `0008` (L's branch, contract §6):

| Column | Type | Why |
|---|---|---|
| `prompt_version` | varchar(80) | `<name>@v<front-matter version>+<sha256(prompt)[:8]>`; joins quality numbers to the exact prompt |
| `tokens_cached`, `tokens_thought` | int | cached input is billed at 10%; thinking is billed as output |
| `attempt` | smallint | 1..n within one `run()` |
| `fallback_from` | varchar(60) | alias that failed before this target |
| `batch_ref` | varchar(120) | Gemini batch name or our run id |
| `subject` | varchar(120) | `analysis:AN-2026-0014`, `run:classify_causes:7` |
| `price_basis` | varchar(10) | `standard`, `batch`, `cached` |

`request_hash = sha256(json(provider, model, prompt_version, system, parts, schema, params), sort_keys)`; it keys the
replay cassettes and lets bulk reruns reuse identical successful calls. `request`/`response` hold the JSON payloads;
for `confidential` they stay in our DB (never exported, excluded from `/api/export`), for PDFs only the document id is
stored. Keys never appear in rows or logs (the helper redacts `AIza…` patterns from error texts).

### 1.5 Budget, retries, fallbacks

- **Budget**: before each call, `sum(cost_usd) where created_at::date = today` (cached 60 s in process) plus the estimate
  must stay under `usd_per_day`; bulk runs pre-estimate with `countTokens` on a 400-item sample and refuse to start above
  `usd_per_run`. At 80% the Ustawienia view shows a warning. Public chat and ask routes also have the per-IP token bucket
  from the contract.
- **Retries** (tenacity): 429/5xx/timeouts with backoff 1, 4, 15 s plus jitter, honouring `Retry-After`; on 429 the
  provider's concurrency halves for 60 s (adaptive fan-out). Invalid JSON or a Pydantic error: one repair retry that
  appends the validation error. Unverified quote (Red Pen): one re-quote retry for that item only.
- **Fallbacks**: after retries, the next alias in `fallback`. Public: `strong → fast`, `bulk → fast`. Confidential:
  `sovereign → sovereign_alt` only, then `SovereignUnavailable`. `replay` is a fallback only when `demo_replay_fallback`
  is on, and the answer is labelled as recorded.
- **Health**: `openai_compatible` providers are pinged (`GET /v1/models`, 2 s timeout) every 30 s; a sovereign provider
  is marked usable only after the known-answer test (§5.5) passed for the current job id.

## 2. Task catalogue

Common rules for every task: Polish prompts in `llm/prompts/<task>.md` with YAML front matter (`version`, `alias`,
`output`); AI rows are inserted with `origin = 'AI'`, `review_status = 'proposed'`, `llm_call_id`; the LLM layer never
updates rows it did not create in the same run (trigger `rm_protect_approved` is the backstop); numbers shown to users
come from code or are checked against a verified quote.

### 2.1 `extract_features`: chips from text + PFU/PPU (screen 1.1)

- **Input**: the user's description; uploaded documents as page-tagged text from `document_page` (primary, works for
  Bielik too); Gemini PDF part only for public scans whose text layer is empty. Long documents: chip-relevant pages first
  (table of contents, "opis przedmiotu", "parametry", "termin", "wynagrodzenie" found by FTS), max 40 pages per call.
- **Order**: regex first (lexicon `quantities`, money, months, programme names from `funding_programmes.yaml`) →
  `origin = CALC`, `method = regex`; then the LLM for everything, then merge: agreement keeps the regex value with the
  LLM quote as evidence, disagreement marks the chip uncertain.
- **Prompt outline**: role (expert wod-kan), the chip keys with definitions mapped to `similarity.yaml` features, "quote
  verbatim from the page, give the file page number, not the printed one", "uncertain when approximate (ok., około,
  orientacyjnie) or when two places disagree", "for quantities given as table rows, return the rows, do not add them",
  "do not quote personal data", "if absent, list the key under missing".
- **Output**:

```python
ChipKey = Literal["podsektor", "podsektory_dodatkowe", "rodzaj_robot", "formula", "budzet", "dlugosc_km",
                  "przepompownie", "przylacza", "rlm", "przeplyw_m3d", "technologie", "termin_mies",
                  "finansowanie", "wynagrodzenie", "zamawiajacy", "lokalizacja"]
class Chip(BaseModel):
    key: ChipKey
    value_text: str                          # as written: "ok. 6 km"
    value_num: float | None                  # model's reading; code re-parses from the quote
    unit: str | None
    vat_basis: Literal["net", "gross", "unknown"] | None   # money only
    source: Literal["opis", "dokument"]
    document_id: int | None; page: int | None; pkt: str | None
    quote: str                               # verbatim, ≤ 300 chars
    uncertain: bool; uncertain_reason: str | None
class QuantityRow(BaseModel):
    key: Literal["dlugosc_km", "przylacza", "przepompownie"]; label: str; value_text: str; page: int; quote: str
class Features(BaseModel):
    chips: list[Chip]; rows: list[QuantityRow]; missing: list[ChipKey]
```

- **Verification**: quote verifier (§3) per chip; number check (every number of `value_num` must appear in the verified
  quote after Polish normalisation, with unit multipliers mln/tys./km/mb); failures set `uncertain = true` and
  `needs_review`. Totals are computed by code from verified `rows` (`origin = CALC`, inputs AI): the live check showed
  three different invented totals for one table. Enum values map to catalogue codes (subsector → `SAN/WOD/DESZ/SUW/OCZ`).
  Missing required features trigger the template follow-up ("Ile będzie przyłączy?"), no LLM.
- **Alias**: `strong` public, `sovereign` confidential; `fast` as fallback.
- **Cost/time**: description only < $0.001, 2 to 5 s. Description + 38-page PFU + 22-page PPU (two parallel calls,
  ~55k tokens in, 3k out): flash ≈ $0.05, 15 to 20 s; flash-lite ≈ $0.02, ~5 s.
- **Failure/fallback**: timeout or invalid JSON → repair → `fast`; still failing → regex chips only plus the note
  "Odczyt AI niedostępny, uzupełnij ręcznie". Confidential with Bielik down → regex chips now, AI chips when the queue
  drains (503 `sovereign_unavailable` for the AI part only).

### 2.2 `redpen_scan`: signals per page (screen 1.3, flags in 1.2)

- **Input**: page-tagged text in windows of 6 pages with 1 page overlap (a 38-page PFU = 7 calls in parallel).
- **Cached prefix** (explicit cache when ≥ 1,024 tokens and ≥ 3 windows, TTL 10 min): system prompt, the approved risk
  catalogue R01 to R18 with sub-risk names and their document `signals` patterns from `risks.yaml` (as hints, not rules),
  2 to 4 approved examples from `gold_example where task = 'redpen_scan'`, and the "common false positives" list built
  from rejected notes.
- **Prompt outline**: "find passages that signal a catalogue risk before the tender; one note per passage; quote 1 to 2
  sentences verbatim; page = file page; pkt = section number if visible; title in Polish ≤ 60 chars, a plain statement
  ('Ryczałt przy „ok. 6 km” sieci'); why = one sentence; do not report missing clauses (code does that)".
- **Output**:

```python
class Note(BaseModel):
    code: str                       # R01..R18 or a sub-risk R01.2; must exist in catalogue_risk
    page: int; pkt: str | None
    quote: str                      # verbatim, ≤ 300 chars
    title: str                      # Polish UI copy
    why: str
    strength: Literal["słaby", "średni", "silny"]
    clause_hint: str | None         # clause code from clauses.yaml, e.g. "R01.2-K1"
class RedPenWindow(BaseModel):
    notes: list[Note]
```

- **Missing-clause checks are code rules, not LLM** (analytics session A owns `flags.py`; L supplies the passage search):
  art. 439 indexation (works > 6 months and no `waloryzac|zmian\w* wynagrodzenia .{0,80}(cen|koszt)|wskaźnik\w* cen|GUS`
  in the PPU → "Brak: klauzula waloryzacyjna", evidence state "dokument nie wspomina"), the doc-type checklist versus the
  uploaded package ("nie ma w paczce"), red flags F1 to F15 whose triggers are structured.
- **Verification**: quote verifier per note, page must match, `code` and `clause_hint` must exist and match each other,
  dedupe across overlapping windows by (code, overlapping char span). Unverified after one re-quote retry: stored with
  `verification = 'unverified'`, red in the UI, never bulk-approvable, hidden in public mode.
- **Alias**: `strong`; `sovereign` for confidential (6-page windows ≈ 6 to 8k tokens fit the 32k context we serve).
- **Cost/time**: 38-page PFU ≈ 48k in (prefix billed at 10% after the first window) + 8k out → flash ≈ $0.07, wall
  ≈ 15 s; 22-page PPU ≈ $0.04. About **$0.10 to $0.15 per analysis**. flash-lite is a third of that if quality holds.
- **Failure/fallback**: a failed window is retried, then sent to `fast`; a window that still fails is listed as
  "strony 13 do 18 nieprzeczytane" in the limitations, never silently dropped. Job kind `llm_redpen` so the report can
  show `status: running`.

### 2.3 `classify_causes`: national change-cause classification

- **Population** (DB today): 58,562 changes with cause text, **45,051 unique texts** (44,702 when PLAN was written),
  **42,095 after normalised dedupe** (lowercase, whitespace collapsed, digits masked). ~160 tokens per item
  (3.19 chars per token measured on a 400-text sample; 22.7M chars with the description capped at 600 chars).
- **Keyword prefilter** (`change_keywords.keyword_categories`, already in `cause_codes_kw`), used for ordering and
  agreement, not to replace the LLM:

| Bucket (unique texts) | n | Order |
|---|---|---|
| no keyword hit | 9,433 | 1 |
| several keyword codes | 15,937 | 2 |
| one low-precision code (R07, R04, R08, R06, R01, N-SCOPE-RED, N-CLIENT ...) | 14,235 | 3 |
| one high-precision code (N-COVID 1.0, R12 1.0, R03 0.87, N-WEATHER 0.85, R02 0.82 precision on gold) | 5,446 | 4, skippable: keyword code kept with `origin = CALC` if time or budget runs out |

- **Label set**: catalogue R01 to R18 plus the gold's N-* codes (N-PRICE, N-COVID, N-WEATHER, N-CLIENT, N-SCOPE-RED,
  N-LAW, N-FORMAL, N-UNSPEC). N-WEATHER maps to R16 once R16 is approved. Definitions go to a new
  `catalogue/wod-kan/cause_labels.yaml` (L drafts, data session D commits, invariant 8).
- **Prompt outline**: "classify the root cause (why), not the effect (what changed); R07 only when extra works are named
  without a reason; N-UNSPEC when no reason is given; secondary only when the text names a second cause; quote ≤ 120
  chars verbatim from the text". 25 items per call as `<item id="…">` (packing measured: same accuracy, 3.1 times fewer
  input tokens).
- **Output**:

```python
CauseCode = Literal["R01", ..., "R18", "N-PRICE", "N-COVID", "N-WEATHER", "N-CLIENT", "N-SCOPE-RED",
                    "N-LAW", "N-FORMAL", "N-UNSPEC"]
class CauseItem(BaseModel):
    id: str; primary: CauseCode; secondary: CauseCode | None
    quote: str; confidence: float = Field(ge=0, le=1)
class CauseBatch(BaseModel):
    items: list[CauseItem]          # ids missing from the answer are re-queued single-item
```

- **Storage**: new table `change_cause_ai` (migration 0008): `norm_md5, text_md5, primary_code, secondary_code, quote,
  verification, confidence, kw_codes, agrees_kw, method (llm|rule), provider, model, prompt_version, llm_call_id,
  origin 'AI', review_status 'proposed', created_at`, unique `(norm_md5, model, prompt_version)`, joined to
  `contract_change` by the same normalisation in SQL. **No 45k `risk_event` rows**: risk_event proposals are created only
  for (a) the 22 pilot projects' 59 changes and (b) a review sample of ≤ 40 items per run (lowest confidence, keyword
  disagreement, largest `delta_value`) that B's `review_sync` turns into Przegląd questions. Request to D: add
  `cause_codes_ai` (confidence ≥ 0.6, quote verified) when `rc_contract` is recreated in 0010, so Monte Carlo can use
  `approved expert > AI > keyword` with origin carried.
- **Verification**: quote exact or fuzzy inside the item's own text (flash-lite 3.5: 20/20 exact single, 20/20 exact or
  fuzzy packed); code in the enum; ids round-trip; confidence calibrated on the gold set (reported, not trusted).
- **Cost and time for all unique texts** (7.8M input tokens incl. prompt overhead for 1,684 calls, 2.5 to 3.6M output
  tokens depending on quote length):

| Model | Standard | Batch API | Wall time, standard, 16 parallel |
|---|---|---|---|
| gemini-3.5-flash-lite | **$8.6 to $11.3** | $4.3 to $5.7 | ~6 to 12 min (3.5 s per 20-item call) |
| gemini-3.1-flash-lite | $5.7 to $7.4 | $2.9 to $3.7 | ~6 to 12 min |
| gemini-3.8-flash (low) | $15 to $19 | $7.6 to $9.7 | ~20 to 25 min |
| Bielik 11B, 1 H100 | GPU-hours only (~0.5 to 1) | | ~30 to 45 min, est. |

  Skipping bucket 4 saves 12%. The Batch API halves cost, but its turnaround is not guaranteed (2 to 3 min for tiny jobs,
  SLA 24 h): submit it only if the run starts before 22:00; otherwise run online.
- **Failure/fallback**: 429 → halve concurrency; resumable and idempotent per `(norm_md5, model, prompt_version)`;
  per-run cap $15; malformed batch → re-queue missing ids single-item; `bulk → fast` fallback.

### 2.4 `chat`: report chat and project chat (1.2 "Zapytaj o tę analizę", 2.3 "Zapytaj o ten projekt")

- **Input**: a fact sheet built by code, never raw tables: for the report, the analysis record's items (each a `Num`
  or text with `prov`: id, role calc/case/source/ai, display text, n, refs); for the project chat, the project's facts
  and events (public callers: approved and edited only). Plus the last 6 turns.
- **Prompt outline**: "answer only from the facts; copy every number from a fact and list its id; do not compute new
  numbers; role calc when you only restate calc facts, ai when you combine or explain, no_data when the facts do not
  cover it, and then name the missing source; for 'co jeśli' questions return a scenario request instead of a number".
- **Output**:

```python
class ChatAnswer(BaseModel):
    answer: str                                   # Polish, answer first ("Raczej nie.")
    role: Literal["calc", "ai", "no_data"]
    fact_ids: list[str]
    missing: list[str]                            # e.g. ["słownik TERYT powiatów"]
    apply: WhatIf | None = None                   # {metric: termin|koszt|konkurencja, param, value} from an enum
    follow_ups: list[str] = Field(max_length=2)
```

- **Verification** (code decides the label, the model only proposes): `fact_ids ⊆ provided`; every number in `answer`
  (Polish normalisation) must occur in a cited fact, else one repair retry naming the number, then the template
  "Nie odpowiem rzetelnie z danych tej analizy." with `no_data`; final `role_label` = "obliczenie" only if all cited facts
  are calc and the model said calc, "brak danych" if no facts, otherwise "wniosek AI". `apply` is validated against the
  simulation's parameter enum and executed by analytics code, whose numbers then come back as calc.
  Measured: both models answered the A2 mockup question from the facts with correct ids and labelled the missing
  "przyłącza" question as no data.
- **Alias**: `strong` (2.2 to 2.7 s), fallback `fast` (0.8 s); `sovereign` when the analysis is confidential.
- **Cost**: ~3k in, 200 out ≈ $0.003 per turn. Stored as `question` rows (migration 0008) and returned as the contract's
  `Answer` with `method.kind = "llm"` and `processing`.

### 2.5 `nl2sql`: "Zapytaj pamięć" (1.6, Pulpit)

- **Views and role**: D's migration 0011 creates `v_ask_contract`, `v_ask_change`, `v_ask_signal`, `v_ask_procedure`
  and role `riskminer_ro` (SELECT on those views only). Requests to D, from the live check: (1) put them in a schema `ask`
  so the whitelist is one schema; (2) `v_ask_contract` = core wod-kan only, with Polish voivodeship and subsector names,
  plus `v_ask_contract_all` for wider questions. Both models wrote correct SQL for "wielkopolskie po terminie" but forgot
  `relevance = 'core'`, so the default must live in the view. Until 0011 lands, develop against a temporary whitelist of
  `rc_contract`.
- **Execution guard** (code, in order):
  1. Parse with **sqlglot 30.33.0 (MIT)**, dialect postgres. Exactly one statement; root `Select`, `Union` of selects or
     `With` ending in a select.
  2. Walk the tree: reject any `Insert, Update, Delete, Merge, Create, Drop, Alter, Command, Copy, Set, Transaction,
     Into, Lock` node, `FOR UPDATE`, comments, and any table not in `ask.*` (CTE names excluded).
  3. Function whitelist (count, sum, avg, min, max, percentile_cont, percentile_disc, round, coalesce, nullif, extract,
     date_part, lower, upper, abs, greatest, least, stddev, cast); reject `pg_*`, `dblink*`, `lo_*`, `set_config`,
     `current_setting`, `query_to_xml`, `pg_sleep`.
  4. Force `LIMIT 200` (add or lower) and require an `n` column or compute n from the rows.
  5. Run in its own connection: `BEGIN READ ONLY; SET LOCAL ROLE riskminer_ro; SET LOCAL statement_timeout = '3s';
     SET LOCAL work_mem = '32MB'; SET LOCAL search_path = ask;` then the query, then `ROLLBACK`.
- **Prompt outline**: view descriptions with column meanings and value lists (voivodeship names, subsectors, value
  buckets), 6 approved question→SQL examples from saved `Q-2026-…` records, "always return n", "if the views cannot
  answer, return cannot_answer with the missing source".
- **Output**:

```python
class SqlPlan(BaseModel):
    sql: str
    answer_template: str            # Polish sentence with {column} placeholders, e.g. "Po terminie skończyło się {pct}% z {n} umów."
    bars: BarSpec | None            # {label_col, value_col}
    title: str                      # for the saved record
    cannot_answer: str | None       # names the missing source
```

- **Answer**: code fills the template from row 0 with Polish number formatting and builds bars from the rows; role calc,
  `method = {kind: "sql", sql}`, n shown; `n < 10` → "za mało danych". The model never writes the numbers. `cannot_answer`
  → role no_data with `missing` (measured: both models refused the powiat question correctly).
- **Failure**: validator rejection or Postgres error → one repair retry with the error text; then no_data with the SQL
  shown. **Alias**: `strong` (2.2 s), fallback `fast` (0.7 s). **Cost** ≈ $0.002 per question.

### 2.6 `import_mapping`: the import agent (2.1) as a tool loop in a sandbox

- **Tools** (D implements them in `imports/sandbox.py`; L owns the loop and prompt in `llm/tasks/import_mapping.py`):

| Tool | Returns (to the model) | LLM inside? |
|---|---|---|
| `list_archive(upload_id)` | file names, sizes, types, counts per type | no |
| `sample_rows(path, sheet?, n≤20)` | headers + n rows, personal contact data masked | no |
| `profile_column(path, column)` | type guess, null share, regex hits and checksum pass rate for NIP/REGON/BZP/KPO/TED, money format | no |
| `match_schema(headers)` | best saved importer and header overlap ("zestaw organizatora, 16 z 18") | no |
| `classify_docs(sample≤40)` | doc types from `doc_types.yaml` filename/first-page rules; undecided first pages go to `fast` | partly |
| `propose_mapping(mapping[])` | rule results per column (checksums, formats, vat basis present) | no |
| `ask_user(question, options[])` | ends the turn; the UI shows buttons, the answer resumes the loop | no |
| `write_importer(spec)` | validates a **declarative** spec (column → field, transforms from a whitelist: strip, parse_pln, parse_date, nip_normalise, split), stores `importer` vN | no |
| `test_run(n=50)` | ok/failed counts, failures (they become review items), would-insert/update/protected counts | no |
| `finish(summary)` | final Polish summary | no |

- **Sandbox**: uploads unpacked into a per-session directory in the worker; tools are path-jailed, the model sees only
  tool outputs (truncated to 4k chars), never a whole file or ZIP. The agent writes a spec, never code, so nothing it
  produces is executed. Strict rules (NIP/REGON checksums, BZP/KPO/TED formats, vat basis on every amount, sha256 dedupe,
  never overwrite approved rows) are enforced in `imports/rules.py`; the model can only ask.
- **Loop**: max 12 steps, 40k tokens per session; Gemini uses native function calling (echo parts for thought
  signatures). For confidential uploads on Bielik/PLLuM the same tools run as a schema-action loop
  (`{"action": "<tool>", "args": {...}}` via `response_format`), because vLLM tool parsing for Bielik is unverified.
- **Output**: tool calls are logged into `import_session.tool_calls` with `llm: true|false` and ms (contract J9).
- **Cost/time**: measured 5-turn loop 3.0 s / 3.9k tokens (flash-lite), 18 s / 7.2k (flash): **$0.002 to $0.03 per
  import**. **Failure**: step cap reached → the session stops with the mapping so far and an "ask the expert" state;
  the deterministic importer only runs after "Zatwierdź i importuj".

### 2.7 `review_phrasing`: Przegląd items as plain questions (3.1)

The design needs questions ("Dlaczego w Steklinie dopłacono 100 325,44 zł?"), and **templates cover them** without an
LLM: per kind and event type (`event`: "Dlaczego w {miejsce} dopłacono {kwota}?" / "Dlaczego w {miejsce} przesunięto
termin o {dni} dni?"; `link`: "Czy projekt {nazwa} to to postępowanie w BZP?"; `discrepancy`: "Którą część przetargu
łączymy z projektem {nazwa}?"; `fact`: "Czy {miejsce} oddano {data}?"; `catalogue`: "Czy {nazwa} ma być osobnym
ryzykiem w katalogu?"). Numbers come from the row, so they are exact. The model pick and confidence come from
`classify_causes`. Optional LLM use (`fast`, after 03:00): one-line `sub` texts per answer option paraphrasing the
quote ("w trasie były rury azbestowe, których nikt nie opisał"), with the number check (numbers ⊆ quote numbers) and a
fallback to the catalogue risk name. Cost < $0.001 per item.

### 2.8 `catalogue_proposals`: new categories (3.1 kind "Propozycje do katalogu", 3.2 "Propozycje AI")

- **Input**: after `classify_causes`, a sample of up to 200 texts labelled N-* or with confidence < 0.5, grouped by
  code with counts computed by SQL, plus the current catalogue names and definitions.
- **Prompt outline**: "propose at most 5 new categories or merges; each with a Polish name, a one-sentence definition,
  3 example item ids, and the closest existing code".
- **Output**: `Proposal {name, definition, example_ids[3], merge_with: str | None, rationale}`.
- **Verification**: example ids exist; counts recomputed by code (re-classifying the sample with the proposal added),
  never taken from the model; names deduped against the catalogue with rapidfuzz `token_set_ratio ≥ 85` (suggest merge
  instead). R16 (weather), R17, R18 already exist as `proposed`, so the first proposals will mostly be merges and counts.
  Result: `catalogue_risk status = 'proposed'` + a review item ("Czy pogoda ma być osobnym ryzykiem w katalogu?", options
  "Dodaj jako R…", "Połącz z R06", "Odrzuć").
- **Alias**: `strong`. **Cost**: one call, ~40k in, 2k out ≈ $0.04.

### 2.9 `rescore_gold`: learning loop (contract §3, decision `gold: true`)

Re-runs `classify_causes` with the new gold example in the prompt on up to 20 similar `proposed` items (similar = same
keyword bucket and code, ranked by trigram similarity of the text), updates only rows still `proposed`, and reports
`{rescored, unchanged, changed, requeued_item_ids}` for the toast "Model przeliczył 7 podobnych propozycji". `bulk`,
< $0.01 per decision, ~5 s.

## 3. Quote and number verifier (`llm/verify.py`)

**Normalisation** (both quote and page text; the page side keeps a map from normalised to original offsets so spans
point into `document_page.text`):
1. remove soft hyphens (U+00AD); join `-\n` + lowercase letter (line-break hyphenation);
2. NFKC per character; typographic quotes `„ ” “ « » ‘ ’ ‚` → `"`; dashes U+2010 to U+2014 and U+2212 → `-`;
3. lowercase; bullets (• ● ▪) and all whitespace runs → one space; trim; strip leading/trailing `."` from the quote.

**Matching**, first hit wins:

| Step | Rule | `verification` |
|---|---|---|
| 1 | exact substring on the stated page | `exact` |
| 2 | exact substring on another page | `exact`, page corrected, `page_mismatch` flag |
| 3 | `rapidfuzz.fuzz.partial_ratio_alignment(quote, page) ≥ 90` on the stated page, then other pages | `fuzzy` (score kept) |
| 4 | cross-page: last 1,500 chars of page p−1 + first 1,500 of p (and p with p+1) | `fuzzy` with both pages |
| 5 | table cells read out of order: ≥ 90% of quote tokens (multiset) inside a window of 1.6× the quote length on the stated page | `fuzzy`, reason `table`, shown as "cytat z tabeli" |
| 6 | otherwise | `unverified` (best score kept) |

Quotes shorter than 4 tokens cannot pass steps 3 to 5. Spans are written to `evidence.char_start/char_end` (or
`risk_signal`, `analysis_item`), `evidence.verification` takes `exact|fuzzy|unverified`.

**Number check**: extract numbers from the claimed value and from the verified quote with the Polish rules
(`1 234 567,89` and `1.234.567,89` → 1234567.89, NBSP as thousands separator, `,` decimal, unit multipliers `mln` ×10⁶,
`tys.` ×10³, `km` vs `m/mb` normalised to metres, dates `dd.mm.rrrr`, `rrrr-mm-dd`, "14 miesięcy" → 14 months). Every
claimed number must equal (tolerance 0.5% for money, exact for counts and dates) a number in the quote; otherwise the
field gets `needs_review` and its chip or note becomes uncertain. For chat answers the same check runs against the cited
facts' display texts.

**Measured on tonight's runs** (prototype `verify.py`, Steklin PFU 26 pages + Sulmierzyce PPU 14 pages, both models,
PDF and text input):

| | n | exact (stated page) | + fuzzy | + cross-page | + table rule | unverified | wrong page |
|---|---|---|---|---|---|---|---|
| PDF input (inline or Files API) | 43 | 39 (90.7%) | 39 | 40 | 43 (100%) | 0 | 0 |
| Page-tagged text input | 43 | 37 (86.0%) | 39 | 39 | 42 (97.7%) | 1 | 0 |
| **All** | **86** | **76 (88.4%)** | **78 (90.7%)** | **79** | **85 (98.8%)** | **1 (1.2%)** | **0** |
| Cause classification quotes (3 models × single/packed × 20) | 120 | 110 | 114 | | | 6 | |

The non-exact cases were all explainable: the PFU's quantity table (the PDF text layer reads cells column by column),
one sentence crossing pages 5→6, and a blank-line placeholder (`____` vs `-----`). Caveats: two born-digital documents
only; OCR'd scans will verify less often (verify against the OCR text, expect more `fuzzy`). Verbatim does not mean
relevant: a few chips quoted the title page or a section heading; relevance is the reviewer's call, helped by the number
check.

## 4. Evaluation plan

**Gold set**: 150 hand-labelled causes (75 completion notices, 75 change notices), primary + optional secondary over
R01 to R15 and 8 N-* codes. Distribution is skewed (R07 33, R02 19, N-UNSPEC 16, R03 11, R01 11, N-WEATHER 9, R04 9 ...;
R05, R06, R11, R14, R15 have no primary examples).

**Protocol**:
1. Zero-shot, label definitions only (headline numbers, no leakage). A second row "few-shot" uses expert-approved
   `gold_example` rows from Przegląd, excluding the evaluated item, to show the learning-loop effect.
2. Same prompt (`classify_causes@vN`), single-item and packed-25 variants, temperature default (Gemini) / 0.1 (vLLM).
3. Systems: keyword rules, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-3.8-flash (low), optionally
   gemini-3.1-pro-preview as a ceiling (≈ $0.10), Bielik-11B-v3.1, PLLuM-12B-instruct-2512.
4. Cost: Gemini runs < $0.30 in total; Bielik/PLLuM a few GPU-minutes through the tunnel.

**Metrics** (script `llm/eval/gold.py`, results as a `model_eval` row in migration 0008: `task, gold_sha256, alias,
provider, model, prompt_version, variant, n, metrics jsonb, per_class jsonb, confusion jsonb, cost_usd, created_at`,
plus `exports/eval/<run>.json|csv`):
- primary accuracy, and "primary in {gold primary, gold secondary}" (the secondary is often defensible);
- macro-F1 over primary classes with support ≥ 3 (and over all classes, reported separately), per-class
  precision/recall (feeds the Katalog notes);
- Cohen's κ model vs gold; pairwise κ between models and Fleiss' κ across the three LLMs ("zgodność modeli");
- JSON validity, quote verification rate, p50/p95 latency, cost per 1,000 items;
- 95% bootstrap CIs (1,000 resamples). With n = 150 the accuracy CI is about ±7 pp: say so in the UI and on slides.
- National agreement without gold: LLM vs keyword codes per category on all texts, and Gemini vs Bielik on a 500-item
  random sample.

**Mini probe tonight** (20 items stratified R07 4, R02 3, N-UNSPEC 2, R03 2, R01 2, R04 2, and one each of N-WEATHER,
R12, N-CLIENT, N-COVID, R09; seed 7):

| System | Primary, single | Primary, packed 20 | Primary in {gold p, s}, single | Quotes verified, single | Latency |
|---|---|---|---|---|---|
| keyword rules | 11/20 have the gold primary among their codes | | | | |
| gemini-3.5-flash-lite | **14/20** | 15/20 | 18/20 | 20/20 exact | median 0.74 s; 20 in 3.2 s at 5 parallel |
| gemini-3.1-flash-lite | 15/20 | 15/20 | 17/20 | 18/20 | median 0.89 s |
| gemini-3.8-flash (low) | 16/20 | 14/20 | 17/20 | 20/20 exact | median 2.7 s |

Typical errors: R02 → R07 and R01 → R07 (the text names "roboty dodatkowe" while the root cause is ground or design),
N-COVID → R12 (a COVID-caused delivery delay), R12 → N-PRICE (war-driven supply), N-UNSPEC → N-WEATHER, R09 → R01.
Several match the gold secondary. The R07-versus-root-cause rule is the main prompt lever. n = 20 cannot separate the
models; the 150-item run decides `bulk`.

**How results feed the quality view** (there is no separate quality screen, design §4 Flow 3):
- Katalog (3.2): each risk row's orange note gains the model next to the rules, e.g. "reguły wyłapują 2 z 14, model
  9 z 14" (per-class recall from the latest `model_eval`), linking to that code's review items.
- Ustawienia → LLM (J14 in the contract): a benchmark table per model (accuracy, macro-F1, κ, cost, latency, data
  location) and the routing decision it justified ("bulk = 3.1-flash-lite: najtańszy przy tej samej trafności").
- Przegląd (3.1): the model pick and confidence per item; low-confidence and model-disagreement items are what the
  review sample selects; approved items become `gold_example` and trigger `rescore_gold`.
- Slides and the submission: one honest sentence, e.g. "Na 150 opisanych przyczynach zmian: Gemini x%, Bielik y%,
  PLLuM z% (przedział ±7 pp)".

## 5. Sovereign mode on WCSS (Bielik and PLLuM)

Nothing below has been submitted. Every step that spends a grant or touches the cluster is the user's (or a session
using the `wcss-slurm` skill) to run, after `preflight.sh`.

### 5.1 Model choice and licences (HF API, today)

| Model | Licence | Gated | Size (bf16) | Verdict |
|---|---|---|---|---|
| `speakleash/Bielik-11B-v3.1-Instruct` | Apache-2.0 | **auto** (accept terms with an HF account, token needed) | 22.3 GB | **primary sovereign** |
| `speakleash/Bielik-11B-v3.0-Instruct-FP8-Dynamic` | Apache-2.0 | no | ~12 GB | fallback if no HF token tonight (FP8 is native on H100) |
| `speakleash/Bielik-11B-v2.3-Instruct` | Apache-2.0 | no | ~22 GB | older fallback |
| `CYFRAGOVPL/PLLuM-12B-instruct-2512` | Apache-2.0 | no | 24.5 GB | **sovereign_alt** (Mistral-Nemo arch, 32 heads / 8 KV heads, 128k context) |
| `CYFRAGOVPL/PLLuM-*-nc-*` (12B, 8x7B, 2412 and 2507) | CC-BY-NC-4.0 / other | | | **avoid** (non-commercial) |
| `CYFRAGOVPL/Llama-PLLuM-8B/70B-*` | Llama 3.1 community licence | | | avoid (not on our permissive list) |
| `speakleash/Bielik-7B-Instruct-v0.1`, `Bielik-11B-v2.2-Instruct-onnx-fp16` | CC-BY-NC-4.0 | | | avoid |

Model weights are used as served tools, not linked code, but we keep to Apache-2.0 so the copyright transfer to MFiPR
raises no questions.

### 5.2 What the user must provide

1. **Which GPU grant/service to bill** (`--account`). The OCR job uses a CPU service (`hpc-dawlin1140-…`, bem2); the GPU
   pools (~4,976 and ~4,053 GPU-hours) are shared and never refill. Decision is the account owner's (skill invariant 3).
2. **HF token** with Bielik v3.1's terms accepted, in a mode-600 file on WCSS (`~/.hf_token`), read inside the job only.
   Without it we serve the ungated FP8 v3.0 fallback (no token needed; the token also speeds downloads from ~50 MB/s to
   ~1 GB/s, irrelevant at 22 GB).
3. **`WCSS_VLLM_KEY`**: a random key (`openssl rand -hex 24`), in the repo `.env` (gateway) and in `~/.riskminer_vllm_key`
   (mode 600) on WCSS. vLLM reads it from `VLLM_API_KEY`, so it never appears in `ps` or logs. Other cluster users can
   reach the node's port, so the key is required.
4. A working `ssh wcss` alias with `BatchMode yes` and `NumberOfPasswordPrompts 0` (three failed password logins lock
   the account for 24 h).
5. Whether the sovereign model should stay up during judging (after Sunday 11:00). A 1-GPU job costs 24 GPU-hours and
   384 core-hours per day; otherwise the live link answers confidential uploads with "Model w Polsce jest niedostępny,
   dokument czeka w kolejce" and the video shows the sovereign path.

### 5.3 Steps

1. **Stack**: if `$PD/llm-stack/vllm.tar` exists (built earlier with the skill), reuse it. Otherwise a CPU job builds it
   (`python -m venv`, `pip install vllm`, tar to PD; large-models.md "Building the stack"; ~15 to 20 min). The site's
   vLLM container (0.9.0.1) is too old.
2. **Weights**, CPU job (no GPU hours on the network): `HF_HUB_DISABLE_XET=1 hf download <repo> --local-dir
   $PD/models/<name> --max-workers 16` for Bielik and PLLuM; loop until the safetensors shard count and total size match
   (22.3 GB, 24.5 GB). ~5 to 10 min.
3. **Serving job**: the shape below; `preflight.sh serve.sbatch`, then `sbatch --parsable`.
4. **Wait for the node**: `squeue -u $USER -o "%.10i %.20P %.18j %.8T %R"`; an idle node takes ~5 min to power up,
   loading 22 GB takes 1 to 3 min. Poll `/health`, never sleep a fixed time.
5. **Tunnel** (5.5), **known-answer test** (5.6), then flip `health` to up in Ustawienia.
6. **Use**: gold eval (150 items each), the confidential demo PFU (chips + Red Pen through Bielik), optionally Bielik on
   the national causes or a 500-item agreement sample.

### 5.4 vLLM job shape (adapted from `templates/job-vllm.sbatch`)

Two small models, one GPU each, one job, one tunnel host. Both fit one H100 each with room for KV cache; tensor
parallelism is unnecessary. Economy option: both on one GPU with `--gpu-memory-utilization 0.45` each, started one after
the other (halves GPU-hours, slightly riskier start).

```bash
#!/bin/bash
#SBATCH --job-name=riskminer-sovereign
#SBATCH --account=<GPU_SERVICE_ACCOUNT>            # user's decision
#SBATCH --partition=lem-gpu-short                  # 3 d wall limit
#SBATCH --gres=gpu:hopper:2,storage:local:200g
#SBATCH --cpus-per-task=32                         # ≤ 16 per GPU, billed as core-hours
#SBATCH --mem=500gb                                # ≤ 250 GB per GPU; memory is free
#SBATCH --time=15:00:00                            # e.g. 20:45 Sat → 11:45 Sun; extend only if judging needs it
#SBATCH --output=/lustre/pd03/<GPU_SERVICE_ACCOUNT>/riskminer/llm/logs/%x_%j.out   # directory must exist
#SBATCH --error=/lustre/pd03/<GPU_SERVICE_ACCOUNT>/riskminer/llm/logs/%x_%j.err

set -uo pipefail
source /usr/local/sbin/modules.sh
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/13.0.0
PD="/lustre/pd03/${SLURM_JOB_ACCOUNT}"
LOG="$PD/riskminer/llm/logs"
export HF_HOME="$TMPDIR/hf"
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=8
export TRITON_CACHE_DIR="$PD/llm-stack/triton-cache"
export VLLM_CACHE_ROOT="$PD/llm-stack/vllm-cache"
export VLLM_API_KEY="$(cat "$HOME/.riskminer_vllm_key")"
mkdir -p "$TRITON_CACHE_DIR" "$VLLM_CACHE_ROOT" "$LOG"
tar -xf "$PD/llm-stack/vllm.tar" -C "$TMPDIR"
for f in "$TMPDIR"/venv/bin/*; do
    [ -f "$f" ] && [ "$(head -c2 "$f" 2>/dev/null)" = '#!' ] && sed -i "1s|.*|#!$TMPDIR/venv/bin/python|" "$f"
done
export PATH="$TMPDIR/venv/bin:$PATH"
hostname > "$PD/riskminer/llm/node_${SLURM_JOB_ID}"

COMMON="--host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.90 --max-num-seqs 128 --dtype bfloat16"
CUDA_VISIBLE_DEVICES=0 vllm serve "$PD/models/bielik-11b-v3.1-instruct" --served-model-name bielik-11b \
    --port 8000 $COMMON > "$LOG/bielik_${SLURM_JOB_ID}.log" 2>&1 &
CUDA_VISIBLE_DEVICES=1 vllm serve "$PD/models/pllum-12b-instruct-2512" --served-model-name pllum-12b \
    --port 8001 $COMMON > "$LOG/pllum_${SLURM_JOB_ID}.log" 2>&1 &
wait
```

Cost: 2 GPUs × 15 h = **30 GPU-hours** + 32 cores × 15 h = **480 core-hours** (PLAN budgeted ~28 GPU-hours for Bielik
alone). Logs go to files (piping through `head` kills the engine). For the FP8 fallback add nothing: vLLM reads the
compressed-tensors config.

### 5.5 Tunnel

On the app host (the dev box tonight; on the VM only if the account owner approves a dedicated, revocable key):

```bash
NODE=$(ssh wcss "squeue -h -j $JOBID -o %N")           # e.g. a lem-gpu node name
autossh -M 0 -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:8001:$NODE:8000 -L 127.0.0.1:8002:$NODE:8001 wcss
```

`scripts/wcss/tunnel.sh <jobid>` wraps this (L writes it, the user runs it). Rebuild when the job moves. Reconnects back
off at least 60 s and stop on an authentication failure (repeated connections read as a scan on `ui.wcss.pl`). Inside
docker the gateway reaches the tunnel via `host.docker.internal` (config `base_url`).

### 5.6 Health checks and the known-answer test

- `GET http://127.0.0.1:8001/v1/models` with `Authorization: Bearer $WCSS_VLLM_KEY` every 30 s (`health.interval_s`),
  latency recorded; `POST /api/settings/llm/providers/{id}/health` triggers it on demand.
- **Known-answer test** (`llm/eval/kat.py`, job `llm_kat`), run before first use for each new job id and on demand,
  **without** `response_format` (schema-constrained decoding produces valid JSON from a broken server, LLM-19):
  1. "Jaka jest stolica Polski? Odpowiedz jednym słowem." → must match `/warszaw/i`;
  2. "Ile to 17 razy 3? Podaj tylko liczbę." → `51`;
  3. a cause text ("Termin wydłużono z powodu intensywnych opadów deszczu…") with "Odpowiedz wyłącznie JSON-em
     {"code": "..."}" → must parse without a schema and equal `N-WEATHER` or `R16`;
  4. every reply `finish_reason == "stop"` and < 64 completion tokens (it stops by itself).
  Pass → provider usable, result stored as `llm_call` rows with task `kat` and shown in Ustawienia. Fail → provider
  stays down, confidential work stays queued.

### 5.7 Timeline (if the user answers 5.2 by 20:15)

| Time | Step |
|---|---|
| 20:15 | user: account, HF token/terms (or choose the FP8 fallback), vLLM key file |
| 20:20–20:50 | stack check or build job, weights job (CPU, parallel) |
| 20:50 | preflight + submit the serving job |
| 21:00–21:20 | node up, models loaded, tunnel, KAT |
| 21:30 | gateway `openai_compatible` against Bielik (L), sovereign routing test |
| 22:00–22:30 | gold-150 on Bielik and PLLuM |
| 22:30–00:00 | confidential demo: upload the PFU as confidential → chips and Red Pen via Bielik |
| overnight | optional national classification or 500-item agreement sample on Bielik |
| Sun ~11:45 | job ends by its time limit, unless the user extends it for judging |

## 6. Module layout, tests, work breakdown

### 6.1 Module layout (`backend/riskminer/llm/`, owned by L per contract §7)

```
llm/
  __init__.py            get_gateway(), LLMRequest, LLMResult
  config.py              Pydantic models for the llm: config block (providers, models, tasks, fallback, budget, prices)
  gateway.py             run(), run_tools(), run_many(), submit_batch()/collect_batch()
  routing.py             sensitivity rules, alias resolution, fallback chain, health cache
  backends/
    base.py              Backend protocol: generate(), cache_create(), batch_submit/poll(), health(), count_tokens()
    google_genai.py      google-genai SDK
    openai_compat.py     openai SDK (vLLM, Gemini /openai/)
    replay.py            cassettes; record mode
  calllog.py             llm_call insert in its own transaction; redaction
  pricing.py, budget.py  cost per call, daily and per-run caps
  verify.py              quote + number verifier (§3), Polish number parser
  sanitize.py            copy rules (no em dash, no middle dot), contact-data scrub
  schemas.py             output models per task (§2)
  sqlguard.py            sqlglot validation + read-only execution (§2.5)
  prompts/*.md           extract_features, redpen_scan, classify_causes, chat_report, chat_project, nl2sql,
                         import_mapping, catalogue_proposals, review_phrasing (Polish, versioned front matter)
  tasks/
    extract_features.py  redpen_scan.py  classify_causes.py  chat.py  nl2sql.py  import_mapping.py
    catalogue_proposals.py  review_phrasing.py  rescore_gold.py
  eval/
    gold.py              benchmark → model_eval + exports/eval/
    kat.py               known-answer test for sovereign providers
  jobs.py                job kinds: llm_redpen, llm_classify_causes, llm_eval, llm_kat, llm_rescore_gold
```

Plus `api/routers/ask.py`, `api/routers/settings.py`, `api/schemas_ask.py`, migration `0008` (question, app_setting,
llm_call columns, `change_cause_ai`, `model_eval`), `scripts/wcss/serve.sbatch` and `scripts/wcss/tunnel.sh`.
New dependencies for the lead's `pyproject.toml`: `google-genai>=3.6`, `openai>=3.57`, `sqlglot>=30.33`
(rapidfuzz, tenacity, pydantic, httpx already present).

### 6.2 Test plan

- **Unit, no network** (`tests/llm/`):
  - verifier: soft hyphen, `-\n` join, NFKC, typographic quotes and dashes, whitespace, exact, fuzzy ≥ 90, cross-page,
    table rule (the real Steklin page-10 table as a fixture), fabricated quote rejected, changed number rejected,
    page correction; Polish numbers (`1 234 567,89 zł`, `7 mln zł`, `ok. 6 km`, `14 miesięcy`, `22.05.2026`);
  - routing: confidential never resolves to a non-PL provider, also through fallback, replay and the PDF part;
    `SovereignUnavailable` when Bielik is down; `BudgetExceeded` before any call; caller cannot downgrade sensitivity;
  - sqlguard: DML/DDL, two statements, `pg_sleep`, `set_config`, non-whitelisted table, CTE shadowing a table name,
    comments, missing/large LIMIT, `SELECT … INTO`, `FOR UPDATE`;
  - schemas: Pydantic → Gemini JSON schema conversion accepted (recorded), packed batch id round-trip and re-queue;
  - chat: number not in cited facts → repair → no_data; role label computed by code;
  - sanitize: em dash and middle dot removed, e-mail/phone scrubbed from quotes;
  - calllog: one `llm_call` row per attempt with provider, model, data_location, tokens, cost, prompt_version.
- **Recorded fixtures**: cassettes `tests/fixtures/llm/<task>/<request_hash>.json` recorded tonight with
  `RISKMINER_LLM_RECORD=1` (chips and Red Pen on the Steklin PFU and Sulmierzyce PPU, 20 gold causes, the two chat
  questions, the two NL→SQL questions, one tool loop), plus hand-edited negative cassettes (fabricated quote, wrong
  number, missing id).
- **CI**: `RISKMINER_LLM_FAKE=1`; a conftest guard fails any test that opens a connection to
  `generativelanguage.googleapis.com` or a vLLM port; no key in CI.
- **One opt-in live smoke**: `pytest -m live_llm` (local or the `live.yml` workflow with its own secret): per configured
  alias one known-answer classification (fixed cause → `N-WEATHER`), valid JSON, latency < 30 s; for sovereign
  providers the KAT of §5.6.
- The gold benchmark is a script, not a CI gate.

### 6.3 Work breakdown (L session; Flow 1 first)

| When | Task | Hours | Depends on |
|---|---|---|---|
| 19:45–21:15 | gateway: config, `google_genai` + `openai_compatible` + `replay`, routing, `llm_call` log, budget, retries, migration 0008 | 1.5 | lead's deps |
| 21:15–21:45 | `verify.py` + `sanitize.py` from the prototype, unit tests | 0.5 | |
| 21:45–22:45 | `extract_features` (chips, rows, regex merge, number check) → hand J1 to A | 1.0 | D's `document_page` for uploads |
| 22:45–00:00 | `redpen_scan` (windows, cached prefix, dedupe, re-quote) + job `llm_redpen`; record cassettes for the demo PFU | 1.25 | |
| **00:00** | **minimum cut (below)** | | |
| 00:00–00:45 | `chat` (report + project) → `POST /analyses/{code}/chat`, `/projects/{rm_id}/chat` | 0.75 | A's analysis record |
| 00:45–01:45 | `classify_causes`: packer, buckets, `change_cause_ai`, start the national run (runtime 10 to 20 min), review sample for B | 1.0 | `cause_labels.yaml` (D) |
| 01:45–03:15 | `nl2sql` + sqlguard + `/ask`, `/questions` | 1.5 | D's 0011 views (temp whitelist until then) |
| 03:15–03:45 | gold-150 eval on all systems → `model_eval`; Katalog/Ustawienia numbers | 0.5 | Bielik up (§5) |
| 03:45–04:45 | `rescore_gold` (1 h) | 1.0 | B's decision endpoint |
| 04:45–05:15 | settings endpoints (`/settings/llm`, health, KAT) | 0.5 | |
| 05:15–06:00 | `import_mapping` loop + prompt (D's sandbox tools), `catalogue_proposals` | 0.75 | D's 0012 |
| 06:00–06:45 | live smoke, re-record cassettes, demo replay set, `review_phrasing` option texts if time | 0.75 | |

In parallel, outside the L hours: the user's WCSS steps (§5.7, about 30 minutes of their attention).

**Minimum by 00:00** (real calls, no fixtures):
1. Gateway with Gemini (`strong`, `fast`), the replay kind, sensitivity routing that refuses confidential input
   without a sovereign provider, and `llm_call` rows with provider, model, data_location, tokens, cost, latency,
   prompt_version.
2. Quote + number verifier with unit tests.
3. `extract_features` returning chips with page refs, verified quotes and the uncertain flag for the demo PFU/PPU.
4. `redpen_scan` returning verified notes (R-code, page, pkt, quote) for the demo PFU, as a job.
5. The gold-150 run on flash-lite started from a script (numbers for Katalog by morning).

If 00:00 slips: Red Pen runs on the demo PFU only, from cassettes recorded before midnight; report chat moves first in
the next block because it is on the Flow 1 demo path.

## 7. Risks and open points

| Risk | Mitigation |
|---|---|
| Rate limits unknown (tier) for the bulk run | Adaptive concurrency on 429; Batch API if started before 22:00; skip bucket 4 |
| Preview model ids change (pro-preview) | Aliases in config; live smoke before the demo; nothing defaults to `best` |
| flash latency with default thinking (8 to 41 s) | `thinking_level: low` in `model_params`, tested in the live smoke |
| Batch API ignoring camelCase schema keys | Build batch payloads with the SDK (snake_case); Pydantic validation; ids re-queued |
| Model-computed totals (km, przyłącza) | Rows + code sums; number check forces `uncertain` |
| Scanned PDFs | Verify against OCR text; more `fuzzy`; Gemini PDF part only for public scans |
| Data location "global" for public data | Stated in Ustawienia and DATA_PROCESSING; EU via Vertex is a config switch once the user enables Vertex AI for the key; confidential goes to Bielik only |
| Bielik not served tonight | Confidential uploads queue with 503; demo uses a public PFU; video shows the sovereign path if it comes up later |
| Key exposure | Key only in `.env` (600); rotate after the event (it was pasted into a chat); a separate restricted key for the VM with a budget alert |

Requests to other sessions: **D**: `cause_labels.yaml`, `ask` schema with core-only `v_ask_contract`, `cause_codes_ai`
in the recreated `rc_contract`, sandbox tools per §2.6. **A**: report fact sheet (items with ids and `prov`) for chat,
art. 439 and checklist rules in `flags.py` using L's passage search. **B**: review sample → questions via the §2.7
templates, `gold: true` → `rescore_gold`. **Lead**: deps (`google-genai`, `openai`, `sqlglot`), the `llm:` config block
(§1.2), accept the tenacity downgrade to 9.1.4.
