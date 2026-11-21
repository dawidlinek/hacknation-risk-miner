# ex ante: project plan (HackNation 2026, MFiPR challenge "Risk Miner")

> **Product name: ex ante** (wordmark `ex [ante]`). Tagline: *„Wiedza ex post, decyzje ex ante."* Pitch opener: *„W funduszach mówimy ex post i ex ante. My wreszcie łączymy jedno z drugim."* The challenge name "Risk Miner" stays in the subtitle: "ex ante: Risk Miner dla inwestycji publicznych".

> Status: v1, 2026-11-21 ~12:30. Built from the full challenge pack (`materials/text/`) and five research reports (`docs/research/01–05`).
> Coding window: **Sat 21.11 11:00 → Sun 22.11 11:00 (24 h)**. Hard checkpoint **Sat 20:00 in HackTribe** (create the project, pick Risk Miner, team, repo, table number, draft description; no changes allowed after that).

---

## 0. One-paragraph pitch

**ex ante is the digital institutional memory for public water and sewage investments: it turns ex post experience into ex ante decisions.** It automatically turns scattered public records into a linked, source-backed case base: BZP notices, TED, KPO/EU project lists, NIK audits, KIO rulings, BIP documents and uploaded files. It extracts documented risk events (delays, cost increases, contract changes and their causes) and puts every AI conclusion through an expert approval loop. For a new investment it produces an evidence-based brief: similar finished cases and why they are similar, cost and time deviation ranges computed from a **nationwide reference class of ~27 000 completed water/sewage contracts** (sample size and uncertainty shown), red flags, a preparation checklist, mitigations and proposed contract clauses. Every number links to its source.

## 1. What wins this challenge (judging criteria → our answer)

| Criterion (weight) | What the jury will test | Our winning move |
|---|---|---|
| Automated acquisition, linking, organisation (20%) | Live run of public-source queries; correct record counts; re-runnable without manual input; links compared against the reference set | Idempotent connectors with a run log. Identifier-first linking (BZP no. / OCID tenderId / NIP / KPO no.) with a fuzzy fallback that shows its score and features. **Chain reconstruction** ContractNotice → TenderResultNotice → AgreementUpdateNotice* → ContractPerformingNotice by `tenderId`. Bulk ingest of the whole 113k-notice BZP copy proves scale |
| Document analysis, event identification, credibility (20%) | Do events, causes and effects match the documents? Are sources cited? Are limits communicated? | Structured BZP fields (deterministic, labelled "source"), plus LLM extraction with **server-verified verbatim quotes** and page numbers, plus a 4-state evidence status ("not in package" / "doc doesn't mention" / "unconfirmed" / "confirmed absent"). Confidence is split into data quality × completeness × signal strength |
| Usefulness of the new-investment analysis (25%) | Comparison group and its justification; cost estimate and schedule assessment; risks, red flags, mitigations, clause proposals | Two-tier evidence: **deep cases** (22+ fully linked projects with approved events) for "similar cases", and a **broad reference class** (all BZP performance/change notices) for distributions with n, P10/P50/P90 and bootstrap CIs. Feature-contribution bars explain the similarity. A checklist comes from the expert guide (9 items). Clause proposals cite the cases that motivate them |
| Expert control, editable assumptions, modularity (20%) | Approve/correct/reject every AI conclusion; manage expert knowledge without code; reuse for other sectors | Review queue for links, events, facts and catalogue proposals. Catalogue, subsectors, CPV map, checklists and clause templates are **data** (a sector pack), editable in the UI and versioned. Approved items become few-shot "gold examples". Full audit history. An `/admin` editor covers every table |
| UX/UI, technical quality, growth potential (15%) | Clarity for a non-programmer; data model; stability; reports and export | Polish-language SPA. "📄 Źródło / 🧮 Obliczenie / 🤖 Wniosek AI" badges on every value. JSON/CSV/PDF export. Clean relational model. Docker compose deploy. Monitoring module as a bonus |

**Explicit "must" items that are easy to forget** (see §11 for the full traceability table):
- Results stored as filterable, exportable records; chat-only answers fail.
- Model set in config, a sample config file, a statement of where data is processed, and a licence list.
- Distinguish source data / calculations / model conclusions visibly.
- Show n and uncertainty for every range; say "not enough data" when n is small.
- Net vs gross: only compare like with like.
- Every important record → source id + link + retrieval date + page/fragment + approval status + edit history.

## 2. Key research findings that shape the plan

1. **The organizers' offline BZP copy is the backbone.** `materials/bzp_kopia/` holds 113,278 water/sewage works notices from 2021-01 to 2026-11-12: ContractNotice 40,904, TenderResultNotice 40,453, AgreementUpdateNotice 5,079, ContractPerformingNotice 26,842. Each record is the raw API JSON, including `tenderId` (OCID), `organizationNationalId` (NIP), `contractors[]` and `htmlBody`, the official form with numbered fields.
   - **ContractPerformingNotice** gives the contract date (4.1), planned period (4.2), contract value (4.4), result notice no. (4.5), contract notice no. (3.2.1), EU co-financing (3.3), executed? (5.1), completion date (5.2), on time? (5.3), number of changes (5.4.1), **total paid** (5.5) and properly performed? (5.6). That is planned vs actual cost and time for ~27k contracts.
   - **AgreementUpdateNotice** gives the change date (5.1), **legal basis** (art. 455 ust. 1 pkt 1–4 / ust. 2), a **free-text cause** (5.3), a description (5.4, e.g. "330 → 371 days") and the value of the change (5.5).
   - The copy is selected by CPV, so it contains non-water projects with a water CPV as a secondary code (e.g. a gym renovation). We need a relevance/subsector classifier.
2. **Live API.** Path `GET /mo-board/api/v1/notice` on `https://ezamowienia.gov.pl` (30 req/min/IP) or the unlimited mirror `https://bzp.cytr.us`.
   - Parameters: `NoticeType` (required), `PublicationDateFrom/To`, `PageSize` ≤500 (≤100 from 11.01.2027), `SearchAfter` = last objectId, `OrderType`, `CpvCode` fragment, `OrganizationProvince` (PL02…), `OrganizationName` fragment, `OrganizationCity`, `OrderObject` fragment, `NoticeNumber` (with/without /01).
   - **There is no NIP or tenderId filter in production; filter client-side.** Our connector must work against prod by swapping the base URL ("test integracji").
   - Details: `docs/research/01_bzp_api.md`.
3. **Provided dataset**: 22 projects (gminas plus one regional roads authority) with NIP and either a BZP notice number (13) or a KPO project number `KPOD.03.15-IW.xx-xxxx/yy` (9). The organizers say it **contains deliberate errors/gaps**. Our importer must validate (NIP checksum, BZP format, cross-check the name/NIP/CPV with the notice) and surface discrepancies as review items. Per-project findings: `docs/research/01_bzp_api.md`.

   **Proven in research: all 22/22 rows link to their BZP procedure, and 27/27 contracts have a performance notice.**
   - 13 rows linked by notice number.
   - 1 (Wolin, row 22) linked via cross-references: its contract notice is missing from the API, but later notices cite its number.
   - 8 KPO-only rows linked by NIP + name + CPV + date. All titles were identical; 7 notices name KPO; the Kamionka notices contain the exact KPO number.

   Signals already visible in the 22:
   - 20/27 contracts finished late (up to +395 days)
   - 19/27 were paid more than the contract value (up to +40%)
   - 4 were not performed properly
   - 48 changes are listed in the performance notices, plus 10 change notices

   **Deliberate dataset errors found** (our test report must show these):
   - row 9 Zakrzew says "część 2" but the description is część 1 (część 2 is a water treatment plant upgrade)
   - row 8 Biecz says "część 1" but the description covers all 4 parts (11.871 km)
   - the KPO project value deviates from the contract amounts on row 7 (−52%) and row 14 (−25%)
   - row 22's notice number is genuine but missing from the source

   **Parser pitfalls:**
   - result-notice estimates are net, while prices, contract values and amounts paid are gross
   - "Wartość zmiany" is sometimes the delta and sometimes the new total
   - periods are often durations ("13 miesiące"), not end dates
   - the on-time flag and the legal basis can contradict each other across notices
   - payments can be interim ("stan na dzień")
   - contractor IDs mix NIP and REGON formats
   - ~3.4% of performance notices reference TED, not BZP
   - never truncate old `tenderId`s: they share suffixes across unrelated procedures
   - the JSON `contractors[]` is often empty, so read contractors from the HTML

   The official API manual (OpenAPI yaml with `/notice` and `/notice/stats`, plus the enum dictionaries for `tenderType` / `clientType` / provinces) is in `docs/research/bzp_api_official/`. Production also serves PDFs at `/mo-board/api/v1/Board/GetNoticePdfById?noticeId=<objectId>` and human links at `/mo-client-board/bzp/notice-details/id/<objectId>`. Use the latter for every citation.
4. **Expert materials** define the vocabulary we must use. They give:
   - 8 investment phases with their typical documents
   - 6 subsectors (main + secondary) and works type as a separate attribute
   - risk catalogue R01–R15 in the form "signal → event → impact → mitigation"
   - art. 455 change bases
   - the 4 evidence states
   - the PPU/SWU-as-contract-substitute label "warunki kontraktowe odtworzone; brak podpisanego egzemplarza umowy"
   - a 9-item preparation checklist for water networks
5. **Tech constraints**: the winners transfer copyright to MFiPR, so dependencies must be permissive only. Banned: PyMuPDF (AGPL), OCRmyPDF/Ghostscript (AGPL), jina-v3 (NC), marker/surya, MinerU. LiteLLM is out (PyPI compromised twice in 2026). Details: `docs/research/04_tech_stack.md`.
6. **Other sources** (`docs/research/02_other_sources.md`, all tested live).

   Ranked:

   | # | Source | What we get |
   |---|---|---|
   | 0 | Biała lista VAT | NIP → REGON/KRS; 19/20 buyers resolve |
   | 1 | **TED API v3** | 0/22 on TED (all below threshold); a documented "searched, not found" + ~1,070 PL water/sewage `can-modif` notices as an above-threshold risk corpus |
   | 2 | **Mapa Dotacji KPO B3.1.1** | 631 projects; matched to the grosz on Zagrodno/Kamionka; no KPO number shown, so link on beneficiary + exact value |
   | 3 | **KIO** | national corpus ≈971 rulings for "kanalizacji sanitarnej"; candidate KIO 2722/25 Biecz |
   | 4a | **CRU** (Centralny Rejestr Umów, since 2026-07-01) | live annexes/terminations: ideal for monitoring |
   | 4b | **NIK** | sector knowledge; 6 audits seeded |

   Extras: KPOŚK xlsx (CC BY 4.0), GUS BDL, NFOŚiGW (CC0).

   KPO number check: `IW.nn = 12 + woj TERYT/2`. **Name-only matching is unsafe** (Elbląg rural vs city, Kamionka vs Kamionka Wielka, two Bobrowniki): use NIP/REGON/TERYT.

   **What to scrape and how: `docs/scrape.md`.**
7. **Domain and method** (`docs/research/03_domain_methodology.md`, ~1,780 lines; YAML blocks parse).
   - Pzp law and form fields.
   - R01–R15 extended with 36 water/sewage sub-risks (signals, events, effects, causes, mitigations, Polish clause wording), 26 event types with detection rules and 15 red-flag rules.
   - **Proposed new top-level R16 weather/seasonality, R17 coordination with roads/other networks, R18 dependence on a linked project**: these need expert approval, which makes a good live demo of "catalogue proposals".
   - Forecasting: hurdle model (P(any overrun) + log-normal size) shrunk to the BZP baseline, tiered display by effective n, no percentiles below n=5.
   - Similarity: 12 features, structured 0.87 + text 0.13, per-feature contributions, weights learnable from expert feedback.
   - 8 evidence states.
   - CPV and keyword classification rules; the 22 projects hand-classified (6 ambiguous).
   - Use the YAML blocks as the seed **sector pack**.
8. **Corpus statistics and change-cause taxonomy** from the full copy: `docs/research/05_bzp_corpus_stats.md`. Reusable code is in `research/bzp_corpus/`: `bzp_parse.py` (field-code parser + normalisers) and `wodkan_classify.py` (relevance + 6 subsectors with a "why"). Gold labels: `data/gold_change_reasons.csv`.
   - **One HTML template from 2021 to 2026.** Parse by field code, not label. Codes repeat per lot/change and differ per notice type (contract value is 4.4 in performance notices, 8.2 in result notices).
   - **Chains**: `tenderId` is never missing. 19,353 full chains exist (contract notice → result → performance), 2,368 of them with change notices. Match a performance notice to its lot by result-notice number + contractor NIP. Keep the latest notice version; drop 213 re-published duplicates.
   - **Relevance**: only **42% of "completed" contracts are really water/sewage works** (11,254 / 26,612). The rest are roads/buildings with a water element (23%) or unrelated (34%). The classifier is mandatory.
   - **National reference class: n = 11,184 completed water/sewage contracts.**

     | Measure | Value |
     |---|---|
     | Finished late | 30.3% |
     | Median delay when late | 58 days |
     | P90 delay when late | 188 days |
     | Contracts with ≥1 change | 41% |
     | Paid above contract value | 21.5% |
     | Cost deviation P90 | +6.9% |

     Size is the strongest driver: 19% late below PLN 0.5m vs 52% above PLN 10m. Treatment plants (39%) and water treatment stations (40%) run late more often than water networks (24%). **Design-build is late 47% vs 28%, and the gap holds within every size bucket.**
   - **Caveats to state on screen.** Recent years are right-censored, and the performance-notice contract value is sometimes already the annexed value, so overruns are understated. Use the result notice's planned end and value as the baseline when they match. Minimum n: 30 for shares/medians, 50–100 before showing P80/P90, otherwise widen the class.
   - **Changes**: 80% are visible only inside performance notices, mostly art. 455 ust. 1 pkt 1 (60%) and ust. 2 (19%). Separate change notices exist only for pkt 3/4.

     Hand-labelled causes (n=150):

     | Cause | Share |
     |---|---|
     | "Additional works" with no stated cause | 22% |
     | Ground / groundwater / condition of existing assets | 13% |
     | No real cause stated | 11% |
     | Utility collisions + land access | 7% |
     | Documentation gaps | 7% |
     | Permits / utility operators | 6% |
     | Weather | 6% |

     Keywords reliably catch COVID, weather, collisions/land and ground conditions; the rest needs the LLM.
   - **Wow feasibility (all confirmed):**
     - **W2**: length is extractable for 42% of contracts. Median **PLN 0.89m/km for sanitary sewer**, 0.39 for water networks; sewer PLN/km rose 41% from 2021 to 2022.
     - **W3**: pre-2024 bands hold **80–88% of later outcomes inside P10–P90**; the late share is under-predicted by ~6 pp because of censoring.
     - **W6**: 4,873 awarded contracts have no performance notice; **3,321 are >90 days past their planned end; 234 are past it with a change notice already**.
     - **W15**: offers count, lowest/highest and winning price are available, but no intended budget, only the net estimate (64% filled). Competition effects are weak, while cancelled tenders show the 2022 inflation shock clearly: **33% cancelled in 2022 (20% because offers exceeded the budget) vs 14% in 2026**.
   - **Pitch numbers:** PLN 20.7bn of contracts covered, **PLN 582m paid above contract values, 261,000 days of delay**. By-year and by-province tables: `research/bzp_corpus/out/wow_pitch_*.csv`.

## 3. Scope: everything, national

**Team decision (12:20): we build all must, should and could items, at national scope, plus the extra features in §3b.**

"National" means:
- **National for structured data:** every BZP water/sewage notice (113k, plus a live delta since 2026-11-12), every TED water/sewage notice for Poland, national KPO/CST project lists, national KIO rulings and NIK reports on the sector.
- **National for AI classification:** all ~5k change-cause texts and all performance-notice free-text sections.
- **Deep document analysis (SWZ/PFU/PPU/annexes)** for the 22 pilot projects plus a national sample: largest overruns, longest delays, and random controls, ~100–300 procedures. Every buyer runs a different procurement platform, so scraping all documents nationally doesn't fit in 24 h. The pipeline is batch-scalable, and we say so on the slides.

The tiers below are now a **build order**, not a cut line. Everything ships behind feature flags, so an unfinished item is hidden rather than broken. Whatever misses the 07:00 freeze moves to the "designed, not yet working" section of the description with a mockup. The brief explicitly asks for that split, so it costs little.

**Must (demoable at Sun 09:00):**
1. Import of the organizer XLSX (+ CSV/XLSX/DOCX/PDF uploads) with identifier normalisation and validation.
2. BZP connector (live API/mirror) plus bulk loader (offline copy) → notices → parsed fields → procedure/contract/change/performance rows, chained by tenderId.
3. At least one more public source wired end-to-end. Default pick is the KPO/CST project list (to resolve the 9 KPO rows) plus a VAT-whitelist NIP check. Then TED or NIK, by `02_other_sources.md`.
4. Linking with method/score/explanation, plus an expert accept/fix/reject screen.
5. Risk events: (a) deterministic events from BZP fields (late completion, overrun, change notices with basis/cause); (b) LLM extraction from documents and change-cause texts → R-codes with verified quotes; (c) expert review queue.
6. Project case view: timeline (notices, changes, completion), money/time planned vs actual, events with evidence, completeness checklist ("missing document X → limits analysis Y").
7. New-investment analysis: free text or an uploaded PDF/DOCX → features → similar cases (explained) → reference-class ranges (n, P10/P50/P90) → red flags + checklist gaps + mitigations + clause proposals → saved `analysis` record → JSON/CSV/PDF export.
8. Catalogue editor (risk types incl. AI-proposed categories awaiting approval, subsectors, checklist, clause templates) and gold-example marking.
9. Config-driven LLM provider; `config.example.yaml`, `.env.example`, DATA_PROCESSING and LICENSES docs.
10. Deployed online with HTTPS and basic auth, pre-ingested.

**Stretch** (after the wow tiers in §3a): OCR for scans (Tesseract `pol`); NIK/KIO/BIP connectors beyond the first extra source; Claude Citations "strict grounding" mode.

## 3a. Wow layer: how we stand out among ~2,000 participants

Other teams will have the same 22 rows and an LLM. Our edge has three parts:
- **(1)** we use the *whole country* (113k notices), not 22 projects;
- **(2)** we **measure our own accuracy** instead of asking the jury to trust us;
- **(3)** we turn the analysis into things an official can *see and use tomorrow*.

Every wow item below maps to a scoring criterion; none is decoration.

**Tier 1: part of the MVP, build these no matter what:**

| # | Feature | What the jury sees | Criterion | Effort |
|---|---|---|---|---|
| W1 | **"Czerwony długopis" (Red Pen): tender-document review** | Upload a draft SWZ/PFU/PPU. It opens in the viewer with **risky passages highlighted inline**, like a linter for tenders. Each highlight carries an R-code, a plain-language why, "in N similar contracts this kind of clause preceded a change notice" with clickable cases, and a **suggested replacement clause**. Also flags **missing** clauses (e.g. no indexation clause in a >6-month works contract, art. 439 Pzp; no geotechnical documentation in design-build) | 3 (25%) | M: LLM signal scan with verified quotes + react-pdf highlights |
| W2 | **"Czy budżet jest realny?" (is the budget realistic?): unit-cost benchmark** | PLN per km of network from thousands of contracts, inflation-adjusted. A gauge shows "your budget is at the 18th percentile of comparable contracts → high risk of underestimation / overpriced offers / cancelled tender" | 3 (explicitly "ocena kosztorysu" – cost-estimate assessment) | S–M: km regex over descriptions + rc table |
| W3 | **"Sprawdziliśmy się sami" (we checked ourselves): backtest and calibration** | Forecast every 2024–2026 completion using only pre-2024 data. Chart: "82% of actual outcomes fell inside our P10–P90 band". Honest uncertainty is something almost no hackathon team shows | 2 (credibility) + 3 | S: reuse the rc engine with a time cut-off |
| W4 | **Case graph** | Interactive graph per project: project → procedures → notices → contract → changes → events → evidence documents. Nodes are coloured by origin (source/calculation/AI) and review status; click a node to open its source | 1 + "Test kompletności" | S: cytoscape.js / react-flow |

**Tier 2: start after the 00:00 check-in if the MVP is on track:**

| # | Feature | What the jury sees | Criterion | Effort |
|---|---|---|---|---|
| W5 | **Monte Carlo S-curve + tornado** | For the new investment: per-risk probabilities and impact distributions from the classified nationwide change notices → 10k simulations → S-curves of completion date and final cost (P50/P80/P90). The **tornado chart** shows which risks drive the spread. **Live toggles** such as "do the geotechnical survey before the tender" or "add an indexation clause" shift the curve | 3 | M |
| W6 | **"Radar Polski" (Poland radar) + time machine** | Map of Poland: completed contracts' delay/overrun heat by province/gmina, plus **ongoing contracts with early-warning signals** (past planned end without a performance notice, change notices piling up). A **date slider replays** notices from the offline copy and alerts fire live: this is the monitoring bonus made visible | 5 + monitoring bonus | M |
| W7 | **Visible learning loop** | After an expert correction: "your decision became a model example; 7 similar proposals were re-scored", with before/after. Quality panel: acceptance rate per category/model, link precision vs the reference set | 4 (20%) | S–M |

**Tier 3: cheap extras if hours remain:**

| # | Feature | Pitch line | Criterion |
|---|---|---|---|
| W8 | **Sovereign-AI switch**: run the same extraction on Claude (EU region) and on **Bielik** (Polish open model, local); show the outputs side by side with an agreement score | "Data can stay inside the ministry" | 4 + tech req. (no lock-in, data location) |
| W9 | **Sector pack in 60 s**: "Dodaj sektor: drogi" (add sector: roads) → AI drafts subsectors, CPV map, risk adaptations and a checklist as *proposals* → the expert approves → bulk ingest of road notices by CPV | "Multi-sector by configuration, not code" | 4 |
| W10 | **Contracting-authority memory and contractor load**: "your gmina: 7 contracts, 5 late, top cause utility collisions"; "the chosen contractor currently holds 9 ongoing water contracts worth PLN 84m" (R12 capacity signal; neutral facts with sources, no rankings) | "Institutional memory per office" | 3 |
| W11 | **MCP server / open API**: any AI assistant in the administration can query Risk Miner cases with citations | "Plugs into the ministry's tools" | 5 (growth) |
| W12 | **"Zapytaj pamięć" (ask the memory)**: natural-language question → shown SQL over the case base → chart + sources, **saved as a record** (not chat-only) | "Ask the memory of 27k contracts" | 5 |

## 3b. Extra features (added 12:20, in priority order)

| # | Feature | Why it matters to this jury | Effort |
|---|---|---|---|
| W13 | **Risk-allocation matrix (macierz podziału ryzyk)** for the new investment. Each identified risk gets: who should carry it (buyer / contractor / shared), the mechanism (clause, contingency, insurance, pre-tender study) and residual impact. Export to XLSX/DOCX | The challenge owner is MFiPR's **PPP Department**; allocating risk between parties is their core method. Speaks their language directly | S–M |
| W14 | **Funding-deadline risk**: P(completion after the programme deadline) read from the W5 S-curve for KPO/EU-funded projects, e.g. "34% chance of missing the KPO deadline → PLN 4.3m of subsidy at risk" | Losing EU/KPO money is the ministry's biggest pain | S (after W5) |
| W15 | **Tender-outcome forecast**: P(cancelled / repeated procedure), expected number of bids, expected winning price vs budget, and seasonality ("tenders published in March get more bids than in October"). Uses national ContractNotice → TenderResultNotice outcomes | Helps before the tender even starts; uses data nobody else will mine | M |
| W16 | **Document pack export**: one DOCX with the risk register, allocation matrix, checklist with gaps, and proposed PPU clauses with their supporting cases, ready to add to the procurement file | Turns analysis into a deliverable an official can file tomorrow | S |
| W17 | **Sector lessons digest**: auto-drafted "lessons learned" page per subsector, every lesson citing cases. Only expert-approved lessons are published | The "institutional memory" made readable | S–M |
| W18 | **Accessibility and plain-language mode**: WCAG 2.1 AA basics (contrast, keyboard, labels; legally required for public-sector apps), and an "explain like I'm not an engineer" toggle on every chart | The jury is public administration; UX is 15% | S |

## 3c. How we build all of it in 24 h: parallel sessions, contract first

This only works if the first ~90 minutes produce a shared contract, so that 5–6 Claude Code sessions can work without stepping on each other:
- `CLAUDE.md` with the invariants
- DB schema v1 + Alembic
- OpenAPI stubs
- a sector-pack format
- feature flags

| Session (own git worktree) | Owns | Starts |
|---|---|---|
| S0 lead / integrator | scaffold, schema, contracts, deploy, merges every ~2 h, demo DB snapshot | now |
| S1 data | BZP bulk + live connectors, form parser, chains, linking, national ingest, test-report generator | after scaffold |
| S2 scraping | everything in `docs/scrape.md`: TED, KPO/CST lists, NIK, KIO, BIP, procurement-platform documents, reference data (TERYT, GUS index, map shapes). Writes raw files + manifest only; S1 loads them | **can start now**, independent of the scaffold |
| S3 LLM | gateway, extraction + quote verifier, national change-cause classification, Red Pen, catalogue proposals, learning loop | after scaffold |
| S4 analytics | reference class, unit cost, backtest, Monte Carlo, tender forecast, early warning, similarity | after scaffold (can prototype on the corpus parser now) |
| S5 frontend | all screens, charts, map, graph, exports UI, accessibility | after OpenAPI stubs |

Integration checkpoints at 16:00, 20:00 (also HackTribe), 00:00, 04:00. Feature freeze 07:00.

**Pitch hook** (real numbers, from `05_bzp_corpus_stats.md`): *"Od 2021 r. w Polsce zakończono 11 184 umowy wodno-kanalizacyjne. Co trzecia skończyła się po terminie: łącznie 261 tysięcy dni opóźnień i 582 mln zł wypłacone ponad wartość umów. Dziś 3 321 trwających umów jest już ponad 90 dni po terminie."* ("Since 2021, 11,184 water/sewage contracts have been completed in Poland. One in three finished late: 261,000 days of delay in total and PLN 582m paid above contract values. Today 3,321 ongoing contracts are already more than 90 days past their deadline.") Use it on slide 1 and in the first 10 seconds of the video. Re-check the numbers after the production pipeline recomputes them.

## 4. Architecture

```
Browser (expert / juror) ── React SPA (PL): Projekty, Przegląd (review queue), Katalog, Nowa inwestycja, Monitoring, Eksport
        │ HTTPS + basic auth (Caddy)
FastAPI (api) ── CRUD, review actions, exports, job enqueue/status, /admin (SQLAdmin)
        │
PostgreSQL 18 + pgvector + pg_trgm + unaccent ── case base, reference class, chunks+embeddings, jobs, audit log
        ▲
worker (same image) ── connectors (xlsx, bzp_api, bzp_bulk, kpo/cst list, ted, nik, kio, bip, vat-whitelist)
                    ── parsers (pypdfium2, docling, LibreOffice .doc, Tesseract pol, calamine)
                    ── htmlBody form parser (field codes → typed values)
                    ── linker (ID rules → rapidfuzz scoring)
                    ── LLM gateway (config: anthropic | anthropic_vertex | openai_compatible) + quote verifier
                    ── analytics (reference class, bootstrap, similarity)
                    ── scheduler (monitoring)
```

### 4a. LLM providers and sovereign hosting on WCSS (added 12:35)

We have Claude, Gemini and OpenAI API keys, plus WCSS HPC access. Checked with the read-only `discover.sh`:
- three SLURM services with **~4,976 and ~4,053 GPU-hours left** on the two main grants
- `lem-gpu-short` = 73 nodes × 4 H100 (95 GB each), 3-day wall limit
- compute nodes have outbound internet, so they can pull HF weights
- PD storage is ample

**Which grant is billed is the account owner's decision**, and the pools are shared and never refill. Our expected use is ~30–150 GPU-hours in total.

**Decision (18:05, replaces the 14:00 Claude decision): one cloud provider, Gemini (Google Cloud project `hacknation`, no. 114919147642), plus two Polish models on WCSS (Bielik, PLLuM).**
- The team has a Gemini key; no Anthropic key is needed. Key in `.env` as `GEMINI_API_KEY` (gitignored, mode 600). **Rotate the key after the hackathon**: it was pasted into a chat transcript.
- **Tested 18:00:**
  - The key works on the **Gemini Developer API** (`generativelanguage.googleapis.com/v1beta`): 49 models listed.
  - Structured JSON extraction in Polish worked on `gemini-3.8-flash` (7.5 s), `gemini-3.1-pro-preview` (6.6 s) and `gemini-pro-latest` (resolves to `gemini-3.1-pro-preview`). All three marked "ok. 6 km" as uncertain.
  - The key is **blocked for Vertex AI** (`aiplatform.googleapis.com`, `API_KEY_SERVICE_BLOCKED`).
- **Data location today: global (Developer API), not EU-guaranteed.** To make it EU-only:
  1. In Google Cloud console → APIs & Services, enable "Vertex AI API" for project `hacknation`.
  2. Under Credentials, add "Vertex AI API" to this key's API restrictions.
  3. Switch the provider's base URL to the EU endpoint.

  That is a config change, not a code change, and it doubles as the "no lock-in" demo. Re-test after enabling.
- **Paid tier.** Billing must be enabled on the project. On the free tier, Google may use prompts to improve its products. That matters little for public BZP data, and confidential uploads go to Bielik anyway, but state it in DATA_PROCESSING.
- **Adapter:**
  - Gemini via the native `google-genai` SDK (Apache-2.0), which gives PDF input, JSON-schema output and context caching.
  - Alternatively the OpenAI-compatible endpoint `…/v1beta/openai/` through the existing `openai_compatible` kind.
  - Claude/OpenAI stay as commented-out config examples.
- **Model aliases** (verify again before the demo, previews change):
  - `fast` = `gemini-3.8-flash`
  - `strong` = `gemini-3.8-flash` (upgrade to Pro where quality matters)
  - `best` = `gemini-pro-latest`
  - `bulk_classify` = `gemini-3.5-flash-lite`, or Bielik on WCSS once it is served

**Polish models, evaluated for real (W8 upgraded).** We already have **150 expert-style hand-labelled change causes** (`research/bzp_corpus/data/gold_change_reasons.csv`). Run Gemini, Bielik and PLLuM on the same set and show accuracy and agreement in the quality view. Example claim: "on 150 labelled change causes: Gemini x%, Bielik y%, PLLuM z%". This is an honest benchmark of Polish models on the ministry's own domain, not just "we plugged one in".

**One adapter, two backend kinds; the original provider list** (OpenAI/Gemini rows are config-only, see above):

| Provider id | Backend kind | Endpoint | Where data is processed (verify before slides) | Use |
|---|---|---|---|---|
| `claude` | `anthropic` | Claude API (Bedrock/Vertex EU via `base_url` if we get access) | Claude API: global routing, may leave the EU. Bedrock `eu.*` / Vertex `eu`: EU | Default `strong`/`best` for public-source extraction and the new-investment report |
| `openai` | `openai_compatible` | api.openai.com (EU data residency only for eligible projects, verify) | US by default | Alternative / cross-check |
| `gemini` | `openai_compatible` | `generativelanguage.googleapis.com/v1beta/openai/` (Vertex for EU regions) | Global via AI Studio; EU via Vertex | Alternative / cross-check; long-context PDF reading |
| `wcss_bielik` | `openai_compatible` | vLLM on a Lem H100 node, reached through an SSH tunnel via `ui.wcss.pl` | **Poland (WCSS Wrocław), nothing leaves the country** | **Sovereign mode**: all confidential uploads; national batch classification |
| `wcss_pllum` | `openai_compatible` | vLLM on a Lem H100 node (second job or the same node), same tunnel pattern | **Poland (WCSS Wrocław)** | Second Polish model: benchmark on the gold set + fallback sovereign model. **Licence per variant: avoid the `-nc` (non-commercial) ones; check Llama-licence variants before use** |
| `local` | `openai_compatible` | Ollama on a laptop | Local machine | Offline fallback demo |

**Data-sensitivity routing (wow + security):**
- Every input carries a `sensitivity` label.
- Public sources (BZP, TED, NIK, KIO, BIP) may use any provider.
- **Uploaded pre-tender documents** (draft SWZ/PFU before publication) are confidential, because leaking them would advantage bidders. They are routed **only** to `wcss_bielik`, enforced in the gateway, logged in `llm_call`, and shown in the UI as a 🇵🇱 "processed in Poland" badge.
- This answers "gdzie przetwarzane są dane" (where data is processed) and "unikać uzależnienia od dostawcy" (avoid vendor lock-in) in one demo moment.

```yaml
# config.example.yaml (excerpt)
llm:
  providers:
    gemini:      {kind: google_genai,      base_url: https://generativelanguage.googleapis.com/v1beta, api_key_env: GEMINI_API_KEY, data_location: "global (Gemini Developer API)"}
    # EU-only after enabling Vertex AI for the key: kind google_genai, vertexai: true, project: "114919147642", location: europe-west4 (or eu), data_location: "EU (Vertex AI)"
    wcss_bielik: {kind: openai_compatible, base_url: http://127.0.0.1:8001/v1, api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wrocław)"}
    wcss_pllum:  {kind: openai_compatible, base_url: http://127.0.0.1:8002/v1, api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wrocław)"}
    # Supported by config, not used in the demo:
    # claude:    {kind: anthropic,         api_key_env: ANTHROPIC_API_KEY, data_location: "global (EU via Bedrock/Vertex profile)"}
    # openai:    {kind: openai_compatible, base_url: https://api.openai.com/v1, api_key_env: OPENAI_API_KEY, data_location: "US"}
  models:            # alias -> provider:model, per task (verify exact ids before the demo; previews change)
    fast:      gemini:gemini-3.8-flash
    strong:    gemini:gemini-3.8-flash
    best:      gemini:gemini-pro-latest
    bulk:      gemini:gemini-3.5-flash-lite
    sovereign: wcss_bielik:speakleash/Bielik-11B-v3.1-Instruct
    sovereign_alt: wcss_pllum:CYFRAGOVPL/<PLLuM variant, licence-checked>
  routing:
    public:       {default: strong, triage: fast, bulk_classify: bulk}   # switch bulk_classify to sovereign once Bielik is served
    confidential: {default: sovereign}   # enforced: never leaves PL
  fallback: {wcss_bielik: wcss_pllum}    # sovereign → sovereign; cloud fallback only for public data
  eval:
    gold_set: research/bzp_corpus/data/gold_change_reasons.csv
    models: [strong, sovereign, sovereign_alt]
```

**WCSS jobs** (use the `wcss-slurm` skill; run `preflight.sh` before every new job shape; `--time` is mandatory; `--gres=gpu:hopper:N` only; ≤16 cores and ≤250 GB per GPU):
1. **Serving job (S3 owns it)**:
   - Bielik 11B on **1 × H100** (`lem-gpu-short`, `--time` ~28 h, `-c 16`, `--mem 250gb`), vLLM OpenAI server.
   - Weights are pre-downloaded to PD by a short job; the HF token needs Bielik's gated licence accepted.
   - Cost ≈ 28 GPU-h + 450 core-h.
   - **Read a known-answer reply before trusting it**: a broken layout serves nonsense at normal speed.
   - Optionally a second job serves **PLLuM** (the Polish government-backed LLM; check each variant's licence, some are non-commercial) or the best open-weight model that fits one 4×H100 node in FP8, as a sovereign `strong` tier.
2. **Batch jobs (S3/S4)**, offline vLLM / sentence-transformers on 4 × H100 for ~1–3 h:
   - bge-m3 embeddings of all 113k notices + all document chunks
   - national classification of ~5k change causes + ~27k performance-notice free texts into R-codes
   - Claude classifies a 300-item sample of the same texts for the **agreement score (W8)**
   - Results go to PD and are then rsynced into our DB as `origin=AI, provider=wcss_bielik` rows
3. **Tunnel**:
   - The app host keeps `autossh -N -L 8001:<gpu-node>:8000 wcss`, where the node name comes from `squeue`. Rebuild it when the job moves.
   - The gateway health-checks `/v1/models` and fails over to the cloud **only for public data**; confidential calls queue and show "sovereign model unavailable".
   - Putting a WCSS key on a cloud VM is a security decision for the account owner. Use a dedicated key, or run the app host on a team machine for the demo.

**Pipeline stages** (each idempotent, keyed by content hash, re-runnable per project or source, logged in `ingestion_run`):
`seed → discover → normalize → link → parse_docs → extract → review(human) → aggregate → analyze → monitor`.

**Stack** (details and licences in `docs/research/04_tech_stack.md`):
- Backend: Python 3.12, uv, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, httpx + tenacity.
- DB: Postgres 18 (`pgvector/pgvector:pg18`).
- Jobs: a simple `job` table with `SELECT … FOR UPDATE SKIP LOCKED` worker loop (~80 LOC), visible in the UI. This replaces Procrastinate: fewer deps and no LGPL psycopg.
- LLM: own thin adapter over the `anthropic` + `openai` SDKs, with model aliases `fast` / `strong` / `best` per task in `config.yaml`. Dev on the Claude API; switch to the Bedrock EU (`eu.anthropic.*`) or Vertex `eu` profile by config. Showing that switch live is the "no code change" proof.
- Embeddings: BAAI/bge-m3 (MIT), locally. Precompute on a dev box if the VM CPU is slow.
- Frontend: React 19 + Vite + TypeScript + shadcn/ui + TanStack Query/Table + react-pdf + recharts. API client generated from OpenAPI.
- Deploy: one Hetzner VM (EU) with docker compose: caddy, api, worker, db. Use a sslip.io hostname if there's no domain.

## 5. Data model (core)

Principles:
- Every fact row has provenance (`source_id`, `evidence_id`), `origin` ∈ {SOURCE, CALC, AI}, and `review_status` ∈ {auto, proposed, approved, edited, rejected}.
- **AI never overwrites approved data.**
- Approvals are rows, and every write goes to an append-only `audit_log`.
- Money is a value object `{amount, currency, vat_basis: net|gross|unknown}`.
- Sector specifics live in catalogue tables (a sector pack), not in code.

| Table | Purpose / key fields |
|---|---|
| `organization` | nip, regon, name, type, teryt, city, verified_by_source |
| `project` | rm_id, external ids {kpo, cst, bzp}, title, description, beneficiary, funding programme, value, subsidy, subsector_main/extra, works_type (build/rebuild), delivery_model (build / design-build), quantities {km, connections, PE, m³/d}, status, sector |
| `procedure` | ocid (`tenderId`), contract-notice no., TED no., title, CPV main/extra, mode, estimated_value_net, budget_gross, below-EU flag, EU-funded flag, lots |
| `project_procedure` | link method, score, explanation, review_status (one project → many procedures) |
| `notice` | number, version, type, procedure, published_at, raw_json, parsed_fields (jsonb), source |
| `lot`, `offer` | parts; bidders and prices from result notices |
| `contract` | procedure/lot, contractor org, signed_on, planned_duration_days, planned_end_on, value_gross, remuneration_type, terms_source (signed / reconstructed_from_PPU), result_notice |
| `contract_change` | contract, notice/document, changed_on, legal_basis, change_types[], delta_days, delta_value, price_increase, cause_text, description_text |
| `contract_performance` | contract, notice, completed, completed_on, on_time, changes_count, total_paid_gross, properly_performed |
| `risk_event` | project/contract, catalogue_code (R01–R15 or proposed), summary, cause, impact_days, impact_value/pct, mitigation, mitigation_effectiveness, phase, confidence {data_quality, completeness, link_strength}, origin, review_status, llm_call |
| `risk_signal` | document fragments suggesting risk *before* it materialises (SWZ/PFU/PPU) with quote and location |
| `document`, `document_page`, `chunk` | file sha256, doc_type (catalogue), phase, version, pages with text and OCR flag; chunks are page-bounded with offsets, tsvector and embedding |
| `evidence` | claim (table, id, field) → chunk/page/char span or notice field code, quote, url, retrieved_at, verification (exact/fuzzy/unverified), evidence_state (4 states) |
| `source`, `ingestion_run`, `llm_call` | url, retrieved_at, sha256, licence; connector runs with stats/errors; provider, model, data_location, tokens, cost |
| `link_candidate` | left/right refs, method (exact_id / normalised_id / fuzzy), features, score, explanation, review_status. Feeds the "test report" automatically |
| `review`, `audit_log` | action (approve/edit/reject/mark_gold/comment), before/after JSON, reviewer, timestamp, comment |
| `catalogue_risk`, `catalogue_subsector`, `catalogue_cpv_map`, `catalogue_doc_type`, `catalogue_checklist`, `catalogue_clause` | versioned and status-tracked (approved / proposed); sector column |
| `gold_example` | approved items used as few-shot examples per task |
| `rc_contract` (materialised) | reference-class row per completed contract: subsector, value bucket, year, region, design-build, EU-funded, planned_days, actual_days, delay_days, overrun_pct, changes_count, legal_bases[], cause_codes[] |
| `analysis`, `analysis_item` | new-investment input, extracted features, reference-class definition + n, similar cases + per-feature contributions, forecasts, flags, checklist gaps, recommendations, clauses. Each item has evidence, origin and review status |
| `monitor_watch`, `alert` | ongoing contracts being watched; detected changes |

## 6. Core algorithms

1. **Identifier normalisation and validation.**
   - BZP `YYYY/BZP 0000NNNN/VV` (strip spaces, pad to 8 digits, split version).
   - OCID `ocds-148610-<uuid>`.
   - NIP: 10 digits with checksum; strip `NIP:` and dashes as seen in `contractorNationalId`.
   - REGON 9/14 with checksum.
   - KPO `KPOD.03.15-IW.\d{2}-\d{4}/\d{2}`.
   - TED `NNNNNN-YYYY`.
   - Every mismatch between the organizer row and the source (name, NIP, scope, status) becomes a review item, not a silent fix.
2. **Chain reconstruction.**
   - Group notices by `tenderId`.
   - Inside a group, link performance and change notices to contracts via fields 4.5 (result notice no.), 3.2.1 / 3.1.1 (contract notice no.), contractor NIP and contract value.
   - Handle multiple lots and contracts per procedure, and repeated procedures after cancellation: same org + similar title + later date gives a "repeated procedure" signal.
3. **Linking project ↔ procedures** when there's no BZP number (KPO rows).
   - Candidate search on NIP (client-side filter), `OrganizationName`, CPV 4523*, title tokens and the date window.
   - Weighted score: name token-set ratio, NIP exact, place names overlap, CPV overlap, value proximity (net/gross aware), date plausibility.
   - Store the feature breakdown as the explanation. Thresholds are auto-accept ≥0.9 (still reviewable), review 0.6–0.9, reject <0.6.
4. **Deterministic events from structured fields** (origin = SOURCE/CALC, high confidence):
   - late completion (5.3 = Nie, or actual > planned)
   - payment above contract value (5.5 > 4.4)
   - each change notice, with basis and its delta days/value
   - not properly performed (5.6 = Nie)
   - cancelled / repeated procedure
   - KIO appeal (if the KIO source is integrated)
5. **LLM extraction** (origin = AI, status = proposed):
   - (a) Classify each change-notice cause text into R-codes, plus new-category proposals. Run a keyword pre-classifier first, then the `fast` model on the rest. The ~5k change notices are cheap enough to do in bulk, which gives a nationwide cause distribution.
   - (b) Extract events, causes, effects and mitigations from documents (SWZ/PFU/PPU/annexes/NIK reports) with chunk-cited verbatim quotes.
   - (c) Scan new-investment documents for risk *signals*, e.g. lump-sum fee + design-build + no geotechnical survey → R02/R08.
   - Every output passes the server-side quote and number verifier before entering the queue.
   - Prompts include the approved catalogue plus 2–4 approved gold examples of the same category, and are prompt-cached.
6. **Reference-class forecast.**
   - Filter `rc_contract` by subsector (+ value bucket, + delivery model, + period), widening progressively until n ≥ 30. Show the chosen class and n.
   - Report the share of late contracts, delay-day quantiles (P50/P80/P90), overrun % quantiles, share with ≥1 change, and the top causes, with bootstrap 90% CIs.
   - n < 10 → show individual cases only and an "insufficient data" badge.
   - Apply the uplift to the user's budget and schedule: "your 12-month plan → P80 = 15.1 months".
   - Method write-up: `03_domain_methodology.md`.
7. **Similarity (deep cases).**
   - Hybrid score = Σ wᵢ×simᵢ over structured features (subsector main/extra, works type, delivery model, log value, km of network, region, beneficiary type, funding source, year), plus the cosine of bge-m3 embeddings of title/description/documents.
   - Show the top-k with per-feature contribution bars, and why each was chosen ("same subsector, design-build, value within ±30%, also KPO-funded").
   - Weights are editable in the catalogue.
8. **Wow-layer algorithms.**
   - **W2 unit cost.**
     - Extract network length from the title or the "Krótki opis" description: a regex for `km|mb|m` plus context words (sieć / kanał / przewód / tłoczny / grawitacyjny = network / sewer / pipe / pressure / gravity; exclude przyłącza = service connections). Use the LLM `fast` model only for ambiguous cases.
     - PLN/km = contract value (gross) / km, indexed to today by the GUS construction-price index for the contract year. The index is a tiny editable table in the catalogue.
     - Percentile of the user's budget within the reference class, with n shown.
   - **W3 backtest.**
     - For each contract completed in 2024–2026, build its reference class from contracts completed before 2024-01-01 and compute P10–P90.
     - Report coverage % (target ~80%), the pinball loss, and a reliability diagram. Store it as a `model_eval` record and show it on the forecast page.
   - **W5 Monte Carlo.**
     - Each risk *r* in the reference class has P(r) (share of contracts with ≥1 change classified as *r*) and an impact distribution (empirical delta-days / delta-% from those change notices).
     - Simulate N=10,000 draws: delay = Σ Bernoulli(P(r)) × sample(impact_r), applied to the planned duration and budget. Correlation is ignored in the MVP; state that as a limitation.
     - The tornado ranks risks by contribution to P80 − P50.
     - Mitigation toggles scale P(r) by a factor stored in the catalogue (expert-editable, labelled as an expert assumption, not data).
   - **W6 early warning.**
     - An ongoing contract is one with a result notice but no performance notice.
     - Signals: days past the planned end, number of change notices, extension days already granted, art. 455 ust. 1 pkt 4 changes.
     - Rule-based score with explained components. Replay mode = treat notices published after the slider date as unseen.
9. **Completeness.**
   - For each project, check the expected documents per phase (catalogue) against what was found.
   - Each missing item is labelled with an evidence state and the analysis it limits.

## 7. UI screens (Polish)

1. **Pulpit (dashboard)**: counts per source, last runs, open review items, alerts.
2. **Import i źródła (import & sources)**: upload XLSX/CSV/DOCX/PDF; "Uruchom wzbogacanie" (start enrichment) per project or all; run log with query, records found and errors; re-run buttons.
3. **Projekty (projects)**: filterable table (subsector, status, region, completeness, risk count) with export. **Karta projektu (project card)**:
   - header with IDs and their sources
   - a "Przebieg" (history) timeline
   - planned-vs-actual money/time with badges
   - procedures/contracts/changes tree
   - events with evidence
   - completeness checklist
   - linked documents with a viewer
4. **Przegląd (review queue)**: tabs for links / events / facts / catalogue proposals / data discrepancies.
   - Side-by-side view: the claim and the highlighted quote on page N, or the BZP field.
   - Actions: approve / edit / reject (with a reason) / mark as model example.
   - Confidence and its components. Keyboard shortcuts.
5. **Katalog wiedzy (knowledge catalogue)**:
   - risk types (R-codes, signals, effects, mitigations, clauses)
   - subsectors and CPV map
   - document types per phase
   - checklists
   - similarity weights
   - AI-proposed categories awaiting approval
   - version history
6. **Nowa inwestycja (new investment)**: a form or free text plus file upload → report with these sections:
   - Extracted features (editable)
   - Similar cases (why)
   - Reference class (n, distributions, ranges)
   - Red flags (with quotes from the uploaded docs)
   - Checklist gaps
   - Recommendations and contract clauses (with the cases that motivate them)
   - Limitations and data gaps

   Save, compare and export to JSON/CSV/PDF.
7. **Monitoring**: watched ongoing contracts, alerts, replay control (stretch).
8. **Historia (history)**: audit log browser with filters.

Every value shows a badge **📄 Źródło / 🧮 Obliczenie / 🤖 AI** plus its review status, and a click opens the source.

## 8. 24-hour schedule

Now: Sat ~12:30. Assumes 2–3 people, each driving Claude Code in its own worktree. With one person, follow the same order and drop stretch items.

| When | Workstream A: data & linking | Workstream B: documents, LLM, analytics | Workstream C: frontend & ops |
|---|---|---|---|
| **12:30–14:00** | Repo scaffold (backend/, frontend/, catalogue/, config/, infra/), `CLAUDE.md` with invariants, DB schema v1 + Alembic | LLM gateway + config + `llm_call` log; htmlBody form parser (reuse `research/bzp_corpus/`) | Compose + Caddy on VM, HTTPS hello world; SPA shell + routing + API client gen. **Get API keys / request Bedrock or Vertex EU access now** |
| **14:00–17:00** | XLSX seed + ID validation; BZP bulk loader (offline copy → notice/procedure/contract/change/performance); chain builder (tenderId + cross-cited notice numbers) | `rc_contract` materialisation + subsector classifier + **km/unit-cost extraction (W2)**; change-cause pre-classifier + LLM batch (fast model) | Projects list + project card (timeline, planned vs actual); review queue skeleton |
| **17:00–19:30** | Live BZP API connector (mirror ↔ prod base URL) + discover for the 22 rows; linker + link candidates | Document parsing (pypdfium2/docling) → pages/chunks/embeddings; risk extraction with quote verifier | Review queue actions + evidence viewer; audit hook; **case graph (W4)** |
| **19:30–20:00** | **HackTribe checkpoint: project, Risk Miner, team, repo URL, table no., draft description (use §0)** | | |
| **20:00–00:00** | Second source (KPO/CST list + VAT whitelist), then TED or NIK; completeness checklist | New-investment analysis: feature extraction, similarity + explanations, reference-class forecast with bootstrap; **Red Pen signal scan (W1)** | Nowa inwestycja wizard + report page with **budget gauge (W2)** and **Red Pen highlights (W1)**; catalogue editor; exports JSON/CSV |
| **00:00 check-in** | Is the MVP (§3) demoable end-to-end? If yes, start Tier 2. If not, fix gaps first | | |
| **00:00–03:00** | Re-analysis on new document (diff confirmed/changed/closed); data-discrepancy review items; **backtest (W3)** | Recommendations + clause proposals from catalogue + cases; gold-example loop; **Monte Carlo + tornado (W5)** | PDF export of analysis; dashboard; badges everywhere; **calibration chart (W3)**; Polish copy pass |
| **03:00–06:00** | Full ingestion on the VM; **test report** generator (links correct / uncertain / wrong); **ongoing-contract early-warning query (W6)** | **Learning-loop panel (W7)**; Tier 3 picks if ahead (W8 Bielik, W10 authority/contractor memory) | **Map + time-machine replay (W6)**; bug bash, loading/empty states |
| **06:00–07:30** | **Feature freeze 07:00.** Expert-review a demo subset (approve, correct, reject a few) so the DB shows the human loop | Write docs: ARCHITECTURE, DATA_PROCESSING, LICENSES (pip-licenses + license-checker), run instructions | Screenshots; record a fallback demo |
| **07:30–10:00** | Description ≤10 pages (works vs designed) | 10-slide PDF | 3-min video → public link (YouTube unlisted / Drive public) |
| **10:00–10:45** | **Submit everything in HackTribe**, then only polish edits until 11:00 | | |
| Sun 11:00–15:15 | Prepare a ≤2-min live pitch path in case we make the top 5 (14:45 announcement, 15:15 pitches) | | |

## 9. Demo script (≤3 min video and live pitch)

0. *Hook* (10 s): the national number on screen (see §3a pitch hook), over the "Radar Polski" map if W6 exists.
1. *Problem* (15 s): public bodies repeat the same mistakes; the knowledge is scattered across BZP, BIP, NIK and annexes.
2. *Path 1, import & auto-enrichment* (60 s):
   - Upload the organizer XLSX. The system validates IDs and flags 2–3 deliberate dataset errors.
   - Click "wzbogać" (enrich): live BZP queries find the contract → result → change → performance chain; the KPO row is matched by NIP + name with 0.87 confidence and explanation.
   - Show the project card timeline: planned 8 months, actual 11; +12% paid vs contract; 2 change notices (art. 455 ust. 1 pkt 4, "kolizja z siecią gazową") → R03 event with the verified quote.
   - The expert approves one event and corrects one link.
3. *Path 2, new investment* (75 s):
   - Paste "Budowa kanalizacji sanitarnej 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł, 14 miesięcy, KPO" (6 km of sanitary sewer with 3 pumping stations, design-build, PLN 7m, 14 months, KPO funding) or upload a PFU.
   - Show the similar cases with "why" bars.
   - Reference class, e.g. design-build sanitary sewer at PLN 5–10m: real n with late share, P80 delay and overrun with CIs. Nationally, design-build is late 47% vs 28%.
   - The budget gauge: PLN 7m / 6 km = PLN 1.17m/km against the national sewer median of 0.89 → above median. Show its percentile with n.
   - The **Red Pen** view of the PFU: 3 highlighted passages with suggested clauses, plus 1 missing indexation clause.
   - (W5) Drag the "geotechnical survey before tender" toggle and watch the S-curve shift.
   - Export JSON/CSV/PDF.
4. *Trust* (20 s): every number clicks through to its source; the calibration chart "80–88% of later outcomes inside our P10–P90 band"; switch the LLM provider in config to the EU region (or Bielik); audit history.
5. *Scale* (10 s): 113k notices ingested automatically; a new sector is just a new catalogue pack.

(The hook and trust numbers are real, from `05_bzp_corpus_stats.md`. The demo-investment figures get filled in by the live system.)

## 10. Submission checklist (Sun 11:00, HackTribe)

- [ ] Working prototype link (+ basic-auth credentials in the description) and local run instructions
- [ ] Title + detailed description
- [ ] PDF presentation ≤10 slides
- [ ] Code repository (public)
- [ ] Video ≤3 min at an open link
- [ ] Description ≤10 pages: problem, scope, main user scenario, **what works vs what is designed**
- [ ] Technical docs: architecture and data-model diagram, sources and matching methods, run instructions, **models/services/libraries/licences list**
- [ ] `config.example.yaml` + `.env.example` + where data is processed (local / EU / outside EU) + licence
- [ ] Test report: correct / uncertain / wrong links; new-project analysis results
- [ ] Sample structured export (JSON + CSV)
- [ ] Optional: screenshots, mockups of unfinished features
- [ ] Every team member has a Discord account

## 11. Requirements traceability

| # | Requirement (brief §) | Feature | Jury test |
|---|---|---|---|
| R1 | Import organizer .xls + batch files (.doc .xls .pdf .csv) | Upload + importers + parsers | Demo path 1 |
| R2 | Auto-fetch BZP + ≥1 more source, re-runnable | Connectors + run log | Test integracji |
| R3 | ID-first linking, normalise/verify formats, fuzzy fallback with basis + confidence | Linker + review | Test łączenia, pracy eksperta |
| R4 | Model separates projects/procedures/notices/contracts/changes/events/cost-date facts/documents/sources; reconstruct history | Schema §5 + timeline | Test kompletności |
| R5 | Source id, link, date, page/fragment, approval, edit history on every record/link/conclusion | evidence + review + audit_log | Test źródłowy |
| R6 | Risk events per catalogue; open catalogue with proposals; effects in days/cost; causes; mitigations + effectiveness | Extraction + catalogue proposals | Criterion 2 |
| R7 | Expert approves every event/conclusion; edit all inputs incl. sector descriptions, choice tables, links, credibility, "wzorcowe" | Review queue + catalogue + /admin + gold examples | Criterion 4 |
| R8 | New investment from text/docs → similar cases + why, cost/time forecast + deviations, issues, actions, clauses; separate source/calc/AI | Analysis wizard + report | Demo path 2, Criterion 3 |
| R9 | Similarity = structured + text, explain deciding features | Hybrid scorer + contribution bars | Test nowej inwestycji |
| R10 | Ranges/flags/recommendations from data + cases; n and uncertainty | Reference class + bootstrap + case citations | Test nowej inwestycji |
| R11 | Results as filterable/updatable/exportable records (JSON/CSV) | Tables + export API | Struktura wyniku |
| R12 | Re-analysis when new documents appear | Re-run + diff | Aktualizacja |
| R13 | Model in config, sample config, data location, licences, no lock-in | Adapter + config + docs | Test założeń |
| R14 | Log sources and operations; limit data processing | source/ingestion_run/llm_call; send only needed chunks | Bezpieczeństwo |
| R15 | Scalable to projects/sectors; entries created automatically, not manually | Sector packs + bulk ingest | Test założeń |
| R16 | Understandable for non-programmers | Polish UI, plain language | Criterion 5 |
| R17 | Bonus: monitoring of unfinished projects | Watch + replay + alerts | Extra |
| R18 | Bonus: OCR and other formats | Tesseract pol | Extra |
| R19 | Recognise missing data, multiple procurements, ambiguous matches | Completeness + link review | Test kompletności |
| R20 | 4 evidence states | evidence_state enum | Criterion 2 |
| R21 | Net vs gross | Money value object | Criterion 2 |
| R22 | PPU/SWU as contract substitute, labelled | contract.terms_source | Test kompletności |

## 12. Risks to the build and mitigations

| Risk | Mitigation |
|---|---|
| Venue Wi-Fi / prod API limits | Bulk copy + unlimited mirror; prod base URL only for the live "integration" proof; cache every response by sha256 |
| LLM access delays (Bedrock/Vertex approval) | Develop on the Claude API; EU profile is a config switch; local Bielik as a fallback demo |
| Hallucinated quotes/numbers | Server-side verbatim + number verification; unverified items can't be bulk-approved |
| Scope creep | MVP list §3 is the contract; stretch only after the 00:00 check-in |
| Demo breaks live | Pre-ingested DB snapshot, fallback video, seeded "new document" for the monitoring demo |
| Licence surprise at IP transfer | Banned list in CLAUDE.md; licence report generated in CI |
| Dataset deliberate errors | Validation-first importer; discrepancies are review items, shown in the test report |

## 13. Open decisions for the team

1. Team size and who takes sessions S0–S5.
2. ~~LLM account~~ **Decided:** Claude + Gemini + OpenAI keys plus WCSS self-hosting (§4a). Open: which WCSS grant to bill (owner's call), and the HF token with Bielik's gated licence accepted.
3. Hosting: Hetzner (or other EU VM) account and a domain, or sslip.io. Also whether a WCSS SSH key may live on that VM (tunnel), or whether the app host runs on a team machine.
4. ~~Product name~~ **Decided (16:10): "ex ante"**. Still open: the team name for HackTribe (20:00).

**Questions for the MFiPR mentors** (stand / Discord). Ask early; the answers change classification rules:
1. Do home treatment plants (przydomowe oczyszczalnie) count as "Oczyszczalnia ścieków" or "Inne obiekty wod-kan"?
2. When a project separates combined sewers, is the main subsector sanitary or stormwater?
3. Is the "dominant scope" that decides the main subsector measured by value or by length?
4. Would they accept R16 (weather/seasonality), R17 (coordination with roads/other networks), R18 (dependence on a linked project) as new top-level risks?
5. Are KPO project values gross, or net of recoverable VAT?
6. Is there a reference set of "correct links" for "Test łączenia" (the linking test), and which identifiers does it use?
