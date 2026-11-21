# Session brief: Risk Miner database, importers and scrapers (`data-db`)

Paste this as the first message of a new Claude Code session in `/home/dawid-home-pc/Desktop/hacknation-risk-miner`, or let the lead session start it.

## Context
HackNation 2026 hackathon (Bydgoszcz), challenge "Risk Miner" from the Polish Ministry of Funds and Regional Policy (MFiPR, PPP Department).

- **Timeline:** 24 h coding window, Sat 21.11 11:00 → Sun 22.11 11:00. Hard checkpoint Sat 20:00 in HackTribe; final submission Sun 11:00.
- **Team decision:** build all must/should/could features at NATIONAL scope.
- **Product:** a "digital institutional memory" of public water/sewage investments.
  - It builds a linked, source-backed case base from public data: the national BZP copy (113,278 notices), TED, the KPO B3.1.1 list on Mapa Dotacji, KIO, NIK, CRU, BIP, the VAT whitelist and GUS.
  - It extracts risk events with verified quotes for expert approval.
  - It analyses new investments against a national reference class of 11,184 completed water/sewage contracts.
- **Stack:** Python 3.12 FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 18/pgvector; React/Vite/shadcn frontend later; own thin LLM adapter (Claude/OpenAI/Gemini + Bielik on WCSS).
- **Licences:** permissive only. The winners transfer copyright to MFiPR, so no PyMuPDF/AGPL and no LiteLLM.
- **What the jury tests:**
  - re-runnable public-source queries
  - links compared against a reference set
  - case completeness
  - traceability of every record
  - exportable records
- **Already proven:** 22/22 pilot projects link to their BZP chains.

## Task
Build the database and the whole data-ingestion layer, then run the imports and scrapers defined in `docs/scrape.md`.

**Read first:**
- `docs/scrape.md` (all of it; this is your spec)
- `docs/PLAN.md` §3, §4, §4a, §5, §6, §11
- `docs/research/01_bzp_api.md`, `05_bzp_corpus_stats.md`, `02_other_sources.md`
- `docs/research/04_tech_stack.md` §2–§3, §9, §11
- `docs/research/03_domain_methodology.md` §2 (catalogue YAML) and §6 (evidence states)

**Steps:**
1. **Scaffold (contract-first):**
   - `backend/` with uv, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, httpx/tenacity.
   - `infra/docker-compose.yml` with `pgvector/pgvector:pg18` (pgvector, pg_trgm, unaccent).
   - `config/config.example.yaml` + `.env.example`, with the LLM section exactly as PLAN §4a.
   - `catalogue/wod-kan/` seed sector pack. R16–R18 go in as status=proposed.
   - A concise root `CLAUDE.md` with the invariants:
     - provenance on every record
     - AI never overwrites approved data
     - append-only audit log
     - money net/gross value object
     - permissive licences + the banned list
     - Polish UI copy
     - feature flags
     - module boundaries
2. **DB schema v1 via Alembic**, covering PLAN §5. Evidence states per 03 §6.
3. **Job table + worker loop** (`SKIP LOCKED`). Every connector/importer is a job and writes `ingestion_run` + `source` rows.
4. **Importers:**
   - **Organizer XLSX**, with validation. Discrepancies become review items:
     - row 9 Zakrzew część
     - row 8 Biecz część
     - rows 7/14 KPO value vs contract
     - row 22 missing contract notice
   - **BZP national copy:**
     - Read it from `/home/dawid-home-pc/Desktop/hacknation-risk-miner/materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl`. Stream it; don't move it.
     - Reuse `research/bzp_corpus/bzp_parse.py` and `wodkan_classify.py`.
     - Chain by `tenderId` plus cross-cited notice numbers. The latest version wins; drop the 213 re-published duplicates.
   - **22/22 linking** reproduced in the pipeline from `research/bzp_linking/link_projects.py`. No manual linking.
5. **Scrapers** per `docs/scrape.md` §2: P0 → P1 → P2 (→ P3), with raw files + `manifest.jsonl`, following the §0 ground rules.
6. **Read API**, published with OpenAPI so frontend and analytics can start:
   - projects, project detail with chain/timeline
   - notices, contracts, changes, performance
   - sources, link candidates, runs
   - JSON/CSV export endpoints
7. **Scrape report:** `docs/test_report_sources.md` + `exports/sources_summary.csv` per scrape.md §7.

**Checkpoints:**
- ~16:00: schema + XLSX + BZP copy loaded, and the 22 chains visible through the API.
- ~19:30: P0+P1 done, plus a counts summary (needed for the 20:00 HackTribe description).

**WCSS:** rsync of `data/raw` to PD is allowed via the `wcss` alias (follow the wcss-slurm skill; never allow a password prompt). Do NOT submit GPU jobs.

**Shared checkout:** the design session writes `design/`; the lead session writes `docs/PLAN.md`, `docs/scrape.md`, `docs/research/`.
- Touch only: `backend/`, `infra/`, `config/`, `catalogue/`, `data/`, `exports/`, `scripts/`, root `CLAUDE.md`, `.env.example`, `docs/test_report_sources.md`, and append-only edits to `.gitignore`.
- Commit nothing and switch no branch unless the user says so.

**Done when:**
- `docker compose up` gives Postgres with the schema.
- One CLI/make target loads the XLSX + BZP copy and links 22/22.
- P0+P1 scrapers have run with manifests.
- The read API + exports work.
- The scrape report exists.
- The user has been told the counts per source and what's left.
