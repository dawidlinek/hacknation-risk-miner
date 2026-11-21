# New project documents: from upload to re-analysis

Written 2026-11-21 ~21:00 after the organizers released three extra case documents. They are stored locally (gitignored) in `materials/organizer_cases/`. Expect the jury to upload exactly these (brief §3: "W przypadku pojawienia się lub wgrania nowych dokumentów, system powinien mieć możliwość ponownej analizy wpływu na stan inwestycji i wniosków"; expert material §6 "Aktualizacja analizy": show which facts, contradictions and risks were confirmed, changed or closed).

## 1. The three documents and the expected result (golden expectations)

### A. `Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf` (1 page, text layer)
- **Type and phase:**
  - type: protokół konieczności aneksowania umowy
  - phase: realizacja
  - date: 05.05.2026
- **Links:**
  - project **RM-2026-002** via the exact KPO number `KPOD.03.15-IW.13-0004/25` (confidence 1.0)
  - contract "IR.271.1.2026 z dnia 05.03.2026" → match to the BZP contract of the Zagrodno sewer procedure by buyer + signing date + scope, with a score and features (no contract number in BZP, so it's a proposal for review)
- **Change (proposed, `contract_change`, source = this document, page 1):**
  - kind: termin, +1 miesiąc
  - new term: "3 miesiące od dnia zawarcia umowy" → planned end 05.06.2026 (CALC)
  - legal basis: not stated → evidence state "dokument nie wspomina"
- **Causes → risk events (AI or rule proposals, verified quotes):**
  - R03: "kolizji z siecią wodociągową uniemożliwiające posadowienie pompowni numer PM2"
  - R02: "wysoki poziom wód gruntowych przy wykopie pod pompownię PM2"
- **Project-level effect:**
  - usable effect delayed about 4 months because of the Modlikowice WWTP (a linked investment)
  - → risk event on the project, code **R18 (proposed: zależność od powiązanej inwestycji)**
  - → catalogue proposal if R18 isn't approved yet

### B. `Risk_Miner_protokol_koniecznosci_zlawies.docx`
- **Type and phase:**
  - type: protokół konieczności nr 1 (roboty dodatkowe)
  - date: 28.10.2025
  - phase: realizacja
- **Links:**
  - project **RM-2026-005** (task title, buyer)
  - contract "nr 272.4.27.1.0.2025 z dnia 14.02.2025", contractor **WIMAX Sp. z o.o.**
  - → match to the BZP contract (buyer + contractor + date); review if not exact
- **Change (proposed):**
  - kinds: zakres + wynagrodzenie + termin
  - **+151 481,54 zł brutto** (VAT basis gross, from the text)
  - term **30.10.2025 → 05.12.2025 (+36 dni, CALC)**
  - legal basis **art. 455 ust. 1 pkt 3** (stated)
- **Flag:** the justification also argues "okoliczności, których nie można było przewidzieć" (pkt 4 wording) → note "uzasadnienie miesza przesłanki pkt 3 i pkt 4" for the expert.
- **Causes:**
  - R02: condition of existing assets; "stan techniczny dwóch filtrów… nie pozwala na ich dalsze użytkowanie po ich odkryciu"
  - R07: additional works
  - R01/R05 candidate: the investor's declaration that the filters would stay in service turned out wrong
- **Mitigation lesson:** inspect existing assets before the tender (SUW Pędzewo).

### C. `Risk_Miner_pismo_termin_grodzisko.pdf` (1 page, **scan, no text layer → OCR needed**)
- **Type, date, recipient:**
  - type: pismo do instytucji pośredniczącej (Urząd Marszałkowski Województwa Podkarpackiego), wniosek o wydłużenie terminu realizacji **projektu KPO**
  - date: 2025-11-06, sign RI.041.1.2025
- **Links:** project **RM-2026-010** via `KPOD.03.15-IW.21-0025/25` (exact).
- **Change:** this is a **grant-agreement** schedule change, not a works-contract change. Request: end date → 31.12.2025. Store it as a project/funding event (`kind: termin_projektu`), not as a `contract_change`.
- **Causes:**
  - R01/R09: design prepared "kilkanaście lat wcześniej"
  - R03: residents, new buildings and vegetation, route modifications
  - R13: funding deadline
- **Planted discrepancy:**
  - the letter header shows **NIP 8161571014, which fails the NIP checksum** (weights 6,5,7,2,3,4,5,6,7 → 9 ≠ 4)
  - the dataset and VAT register have 8161570014 (valid)
  - → review item "NIP w piśmie niepoprawny (suma kontrolna); w rejestrze 8161570014". Never relink or "fix" silently.

## 2. Best-case pipeline (what the jury should see)

1. **Upload** on the project card (Dokumenty tab drop zone) or through the import agent. The sensitivity label is chosen by the expert (default confidential).
2. **Text:**
   - text layer, or **OCR** (Tesseract `pol` inside the backend image; WCSS batch for bulk), stored per page with the OCR flag
   - for a confidential document with no sovereign model, OCR is still local (Tesseract), so it's allowed
3. **Classification:** doc type + phase with a "why" (rules on title and opening text; LLM only if allowed).
4. **Identity and linking:**
   - extract identifiers: KPO number, contract number + date, NIP/REGON, BZP number, buyer, contractor
   - **validate** them: NIP/REGON checksums, KPO `IW.nn` = 12 + woj TERYT/2, existence in our DB
   - link to project / procedure / contract with method + score + features
   - mismatches → review items
5. **Fact extraction (rules first, LLM second):**
   - **Rules** (always available, even when confidential and Bielik is down): dates, durations ("o 1 miesiąc", "do 05.12.2025"), money with VAT basis, `art. 455 ust. 1 pkt N`, change kind keywords, cause keywords → R-codes.
   - **LLM** (public, or sovereign when up): structured change + causes + mitigation with **verbatim quotes verified on the page**.
   - All outputs are `proposed`.
6. **Records:**
   - `contract_change` (contract-level) or a project/funding schedule event (grant-level)
   - `risk_event`s with evidence (document id, page, quote)
   - possible catalogue proposals (R18)
7. **Review:** items appear in Przegląd as plain questions, e.g. "Czy zmiana terminu o 1 miesiąc z protokołu z 05.05.2026 dotyczy umowy IR.271.1.2026?", "Czy przyczyną jest kolizja z siecią wodociągową (R03)?".
8. **Re-analysis after approval (or immediately, as preview):**
   - recompute the project's plan vs actual, timeline and events
   - produce a **"Co się zmieniło"** diff record for the project, listing facts **potwierdzone** (also in BZP), **zmienione** (planned end date, value), **nowe** (risks, dependency) and **zamknięte**
   - raise a **Monitoring alert** for ongoing contracts
   - mark analyses that used this project as a similar case with "nowe dane w przypadku podobnym, uruchom ponownie"
9. **Learning:** approved events become gold examples; the approved causes enter the case base for future simulations.
10. **Privacy:** never store signatories' names or phone numbers in normalised tables; keep raw files access-controlled.

## 3. Work split

| Gap | Owner | Deliverable |
|---|---|---|
| G1 OCR on upload | **data-db (D)** | job `document_ocr`: Tesseract `pol` run inside the backend Docker image (`docker run` of the already-built image if the host has no tesseract), pages written with `ocr=true` + confidence, re-chunk for search. Ask be-contract to add `tesseract-ocr tesseract-ocr-pol` (Apache-2.0) to `infra/Dockerfile.backend`. Enqueue automatically when `text_status=needs_ocr` |
| G2 fact extraction | **be-llm (L)** | task `document_facts`: rules pass + LLM pass under sensitivity routing, schema for change (kind, old/new dates, delta days, delta value + VAT basis, legal basis, causes → R-codes, mitigation, contract ref, project ref) with verified quotes; job `document_extract` enqueued on upload (after OCR); writes proposals |
| G3 linking + validation | **be-records (B)** | resolve the extracted identifiers to project/procedure/contract with method, score and features; NIP/REGON/KPO checks; discrepancy review items; contract-level vs grant-level routing |
| G4 re-analysis + diff | **be-records (B)** | `GET /api/projects/{rm_id}/changes-since?document_id=` → "Co się zmieniło" (potwierdzone / zmienione / nowe / zamknięte) after the new records; project aggregates refreshed (with data-db's derive); a Monitoring alert row (data-db's table) |
| G5 UI | **be-records (B)** for 2.5 Dokumenty (upload, processing status, extracted facts with quotes, diff panel); **fe-screens (F2)** for the Karta "Przebieg" new step + Przegląd items rendering | |
| G6 e2e | **be-contract (S0)** | a test that uploads the three files (skipped if `materials/organizer_cases/` is absent) and asserts the golden expectations in §1, using the fake LLM for the AI part |

## 4. User direction (21:10): full best case, LLM-driven, learning

The user wrote: "of course we should support the best case, because we want the platform to learn and grow, you have llms to achieve that".

Decisions taken from it:
- **Sensitivity default by context:**
  - execution-phase documents uploaded to an existing project → **public** (Gemini, with the OpenRouter fallback)
  - pre-tender drafts in a Flow 1 analysis → **confidential** (sovereign only)
  - the expert can override either
- **LLM pass mandatory** whenever sensitivity allows; rules remain the first pass and the fallback.
- **Learning loop:**
  - approved or edited extractions become gold few-shot examples for `document_facts`
  - rejections with reasons feed a "typowe błędy" prompt list
  - accept/edit/reject rates are tracked per doc type and model (`learning_loop` view)
  - new cause patterns become catalogue proposals (R18)
  - approved causes feed `cause_codes_ai` and therefore the simulations
- **Visible growth:** each document shows what it added to the base, e.g. "+1 zmiana umowy, +2 zdarzenia ryzyka, 1 propozycja do katalogu".
