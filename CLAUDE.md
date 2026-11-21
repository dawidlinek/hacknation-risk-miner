# Risk Miner: project invariants

HackNation 2026, MFiPR challenge. Source-backed case base + risk analytics for public water/sewage (wod-kan)
investments, national scope. Plan: `docs/PLAN.md`; data spec: `docs/scrape.md`. Winners transfer copyright to MFiPR.

## Invariants (do not break)
1. **Provenance on every record.** Every fact row has `source_id` (→ `source`: url, retrieved_at, sha256, path, licence),
   `origin` ∈ SOURCE | CALC | AI and `review_status` ∈ auto | proposed | approved | edited | rejected. Claims get
   `evidence` rows (notice field code / document page + quote). Raw bytes live unchanged in `data/raw/<source>/` with one
   `manifest.jsonl` line per fetch; normalised tables are derived and rebuildable.
2. **AI never overwrites approved data.** DB trigger `rm_protect_approved` keeps approved/edited rows; only the expert
   review path may change them (`SET LOCAL riskminer.expert_write = 'on'`). AI output is inserted as `proposed`.
3. **Append-only audit log.** `audit_log` rejects UPDATE/DELETE (trigger). Approvals are `review` rows.
4. **Money is a value object**: `{amount, currency, vat_basis: net|gross|unknown}` (`<x>_amount/_currency/_vat`).
   Compare only like with like: BZP estimates are net; contract values, prices and payments are gross.
5. **Permissive licences only** (MIT/BSD/Apache/PSF/MPL-as-tool). Banned: PyMuPDF/fitz, OCRmyPDF, Ghostscript (AGPL),
   jina-embeddings-v3 (NC), marker/surya, MinerU, LiteLLM, psycopg (LGPL; we use asyncpg), OpenTender data (NC).
   Check the licence before adding any dependency.
6. **Polish UI copy** (labels, review-item titles, flags). Code, comments and docs in English.
7. **Feature flags** in `config/config.yaml` → `features:`; unfinished features are hidden, not broken.
8. **Module boundaries**: `riskminer/connectors/*` only fetch + write raw/manifest + `parse()` records (no DB);
   `riskminer/ingest/*` loads/derives/links (DB); `riskminer/api/*` reads + review actions; analytics/LLM in their own
   packages. Sector specifics live in `catalogue/<sector>/*.yaml` (sector pack), not in code.
9. **Scraping rules** (`docs/scrape.md` §0): ≤1 req/s per host (BZP prod ≤25/min), backoff, robots.txt, fixed UA without
   personal data, never bypass CAPTCHA/WAF (record `blocked`), no personal contact data in normalised tables/exports.
10. Nothing is fixed silently: dataset discrepancies become `review_item` rows for the expert.

## Run
```bash
docker compose -f infra/docker-compose.yml up -d db          # Postgres 18 + pgvector on :5434
cd backend && uv sync && uv run alembic upgrade head
uv run riskminer load-all                                    # catalogue → XLSX → BZP copy → derive → link 22/22 → scraped → report
uv run uvicorn riskminer.api.main:app --port 8000            # /docs, /openapi.json
uv run riskminer scrape <source> [--since D --limit N --only a,b]   # see `uv run riskminer sources`
uv run riskminer worker                                      # job queue (SKIP LOCKED)
uv run pytest -q
```
Big data stays out of git (`data/`, `materials/bzp_kopia/`). Commit nothing unless asked.
