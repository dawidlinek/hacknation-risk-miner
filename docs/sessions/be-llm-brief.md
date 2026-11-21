# Session brief: L (LLM layer), name `be-llm`

Start as a fresh session in `/home/dawid-home-pc/Desktop/hacknation-risk-miner` (shared checkout, no worktree), model Opus, effort high.

You are session **L (LLM layer)** of the "ex ante" build.

## Specs
- **`docs/impl/llm.md`**: gateway, task catalogue (prompts, schemas), quote + number verifier, live-check results and gotchas, costs, eval plan, WCSS sovereign plan. Scratch evidence is in `/tmp/claude-1000/-home-dawid-home-pc-Desktop-hacknation-risk-miner/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/llm/`.
- **`docs/impl/api_contract.md`**:
  - §2: `/ask`, `/questions`, chats, `/settings/llm`, and the Red Pen scan job feeding `/analyses/{code}/redpen`.
  - §7: your ownership row "L LLM": `llm/**`, `api/routers/ask.py`, `api/routers/settings.py`, `api/schemas_ask.py`, migration **0008** on its own Alembic branch, `tests/llm/**`, `tests/fixtures/llm/**`, and the `llm:` section of `config/config.example.yaml`.
  - §8: fake mode `RISKMINER_LLM_FAKE=1` with recorded fixtures; no network in tests.
  - §9: your column.
- `docs/PLAN.md` §4a, `CLAUDE.md`, `design/README.md` patterns 12 and 13.

## Gotchas from the live checks
- Gemini Developer API, `GEMINI_API_KEY` from `.env`. Never print it.
- `fast` is flash-lite.
- Flash needs `thinking_level: low`; otherwise a call takes 8–41 s.
- flash-lite rejects `thinkingBudget: 0`.
- Function calling must echo thought signatures back.
- The Batch API ignores camelCase `responseJsonSchema`. Use snake_case.
- Explicit caching needs at least 1,024 tokens.
- Models invent table totals, so code computes sums. Numeric chips must pass the number check.
- Vertex EU is blocked for this key, so `data_location` is "global".

## Order
**Minimum by 00:00:**
- Gateway:
  - `google_genai` + `openai_compatible` backends
  - aliases and sensitivity routing
  - `llm_call` logging, a budget cap, fake mode
- Verifier.
- `extract_features`: chips with page refs and an uncertain flag.
- `redpen_scan` with verified quotes, as job `analysis_redpen`. be-analytics owns `/analyses` and the missing-clause rules.

**Then:**
1. `classify_causes` over ~42k unique change causes: keyword prefilter, then flash-lite (Batch if quick).
   - Writes `cause_codes_ai`, plus AI `risk_event` proposals with `review_status=proposed` for the review queue.
   - This is the critical path for criterion 4 and for the Monte Carlo inputs.
2. Report and project chat: grounded on computed facts, answer roles obliczenie / wniosek AI / brak danych.
3. `/ask` NL→SQL:
   - sqlglot validation and the read-only role
   - core-only views from data-db, migration 0011 (`relevance='core'` enforced)
   - saved questions `Q-…`
4. `rescore_gold` on the 150 gold causes.
5. Settings endpoints.
6. The import-agent mapping prompt.

## WCSS / Bielik
Prepare the vLLM job script and tunnel plan, but do not submit any WCSS job until the user picks the GPU account and provides an HF token in this session.

Without Bielik:
- Confidential uploads return 503 "model suwerenny niedostępny" and never fall back to the cloud.
- The demo PFU is processed as a public document.

## Dependencies and data requests
- **Dependencies:** ask be-contract (owns `pyproject.toml`) for `google-genai`, `openai`, `sqlglot`, `rapidfuzz`. Note that `google-genai` pins tenacity below 9.2.
- **From data-db:**
  - core-only ask views
  - `cause_labels.yaml`
  - a `cause_codes_ai` column or table that analytics can read
- Tell be-analytics where the codes land.

## Session ids
| Session | Id |
|---|---|
| be-contract (S0) | `local_aa6b757b-fee2-46ce-a143-a14d7a2b4060` |
| be-analytics (A) | `local_b01f41fc-7787-42ed-90bc-d3ded878fa67` |
| be-records (B) | `local_0bc1d0cd-d408-4cc4-ba43-3a935ecd70f2` |
| data-db (D) | `local_4944697c-bc19-479d-9b3c-57161af2c987` |
| fe-flow1 (F1) | `local_a3ef2fc9-6d61-4f30-9ed2-b60b001cca52` |
| lead | `local_82c8f33d-4c6d-4615-a1aa-86c2488b1828` |

## Rules
- Edit only your own files. Commit nothing and switch no branch; the lead commits.
- Never add Claude attribution.
- No em dashes or middle dots in UI copy, user-facing prompts or docs.
- AI output is always `proposed`.
- Tests must not mutate the main DB and must make no live calls.
- One API instance on port 8000 (data-db's).
- Keep live spend small.
- RAM is tight.
- Report to the user at 00:00 and 04:00. Freeze is 07:00.
