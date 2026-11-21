# 01: BZP / e-Zamówienia notice API: endpoints, fields, linking, and the 22 dataset projects

Research date: 2026-11-21. Every claim below comes from real requests to the HackNation mirror `https://bzp.cytr.us` (unlimited rate) and, sparingly, to production `https://ezamowienia.gov.pl` (30 req/min/IP), plus the organisers' offline copy (`materials/bzp_kopia/…/notices.jsonl`, 113 278 notices) and the mirror server source (`bzp_mirror.py` v1.5). Items marked **(unverified)** come from third-party sources only.

Working scripts, cached responses and raw samples are in the session scratchpad (paths in §11). They are throwaway research code. Copy the ideas, not the files.

---

## 0. TL;DR

* **There is one public read endpoint: `GET /mo-board/api/v1/notice`.** It returns a JSON array of notices, and every notice carries the **full notice as HTML in `htmlBody`**. Production and the mirror share the path and parameters. On the mirror every other path returns nginx 404. Production also has a PDF endpoint, `GET /mo-board/api/v1/Board/GetNoticePdfById?noticeId=<objectId>` (verified: 200, `application/pdf`).
* **Filters:** `NoticeType` (required), `PublicationDateFrom/To`, `PageSize` (≤500 now, **≤100 from 11.01.2027**), `SearchAfter` (an objectId cursor), `NoticeNumber`, `OrganizationName` (substring), `OrganizationCity`, `OrganizationProvince`, `CpvCode` (substring), `OrderObject` (substring) and `OrderType`. **You cannot filter by NIP or tenderId.** Those parameters are silently ignored today and will return **404 from 11.01.2027**. Pull an organisation's notices by name substring, then filter client-side on `organizationNationalId` and `tenderId`.
* **The linking key is `tenderId`** (`ocds-148610-<uuid>`, which the notices call "Identyfikator postępowania"; it is also the OCDS OCID). All 4 notice types carry it. For our 22 projects, grouping by `tenderId` reproduced **100 % of the chain present in the offline copy**. No notice in the copy cites a chain number under a different tenderId. The bodies also cross-reference by number: a result notice cites the CN, and change and performance notices cite the CN and the result notice. That covers the case where the CN itself is missing (row 22).
* **The mirror holds only 4 types:** `ContractNotice` (ogłoszenie o zamówieniu), `TenderResultNotice` (o wyniku), `AgreementUpdateNotice` (o zmianie umowy) and `ContractPerformingNotice` (o wykonaniu umowy). It covers wod-kan works only, 2021-01-13 → 2026-11-12.
* **Hit rate on the 22 rows: 22/22 procedures identified.**
  * CN found for 21/22 and result notice for 21/22. Row 22 (Wolin): CN and result notice are absent from both the mirror and production.
  * Contractor and contract value found for 22/22 projects, which make up **27 contracts** because of multi-part procedures.
  * **Performance notice found for 27/27 contracts.** Change notices: 10, across 6 projects.
  * All 8 KPO-only rows were matched by NIP + name + CPV + date with an exact title match. 7/8 are corroborated by KPO funding text in the notice body. One even contains the exact KPO project number.
* **The data is rich in risk signals:**
  * 20/27 contracts finished after the planned date (max +395 days).
  * 19/27 were paid more than the contract value (max +40 %).
  * 3 contracts were reduced by penalties, and 4 are marked "not performed properly".
  * The performance notices list 48 contract changes with legal basis (29× art. 455 ust. 1 pkt 1, 12× ust. 2, 5× pkt 4, 3× pkt 3), with reasons in free text.
* **Dataset errors found:**
  * Row 9 (Zakrzew) says "część 2", but the description matches **część 1**.
  * Row 8 (Biecz) says "część 1", but the description covers **all 4 parts**.
  * Row 22: the CN number is genuine (cited by follow-up notices) but cannot be retrieved from the API.
  * KPO value mismatches on rows 7 and 14.
  * All NIPs pass the checksum and match the notices.

---

## 1. Sources and environment

| Item | Value |
|---|---|
| Production endpoint | `https://ezamowienia.gov.pl/mo-board/api/v1/notice` (no auth; "odczyt ogłoszeń i statystyk nie wymaga integracji") |
| Production limit | 30 req/min per IP since 06.10.2026. Exceeding it returns **HTTP 403** (HTML page) |
| Planned change (production, 11.01.2027; test env `edu.ezamowienia.gov.pl` from 15.10.2026) | `PageSize` max **100** (now 500). **Unknown/invalid query params → HTTP 404** (e.g. `pageNumber`). Source: <https://ezamowienia.gov.pl/pl/planowane-zmiany-w-api-bzp/> |
| Mirror | `https://bzp.cytr.us/mo-board/api/v1/notice` (same interface, no limit). `https://bzp.cytr.us/info` returns JSON with counts. Response header `x-data-source: kopia BZP - serwer lustrzany HackNation`. Any other path returns nginx 404 |
| Mirror content | 113 278 notices: ContractNotice 40 904, TenderResultNotice 40 453, ContractPerformingNotice 26 842, AgreementUpdateNotice 5 079. Dates 2021-01-13 → 2026-11-12. "Wod-kan works only". Other types return `[]` plus the header **`X-Mirror-Missing-Type`** |
| Offline copy | `materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl` (2.7 GB, one API record per line, including `htmlBody`). Streaming the whole file in Python takes ~10 s. `bzp_mirror.py` serves it locally on `http://127.0.0.1:8010` (flags `--api-2027`, `--order asc`, `--rate-limit N`). **Use `--api-2027` in CI** to catch bad params early |
| Official docs | "Załącznik 3 – Instrukcja integracji z API BZP": `https://media.ezamowienia.gov.pl/pod/2022/08/Zalacznik-3-Instrukcja-integracji-z-API-BZP.zip` (ZIP, 263 KB, dated 2022-08). **Not downloaded** (needs the user's OK). No public Swagger was found: `/mo-board/swagger/...` returns 404 on production. Everything in this report was established by probing |

---

## 2. Endpoint catalogue

### 2.1 `GET /mo-board/api/v1/notice`, the only notice endpoint

| Param | Prod | Mirror | Semantics (verified) |
|---|---|---|---|
| `NoticeType` | **required** | required | Exact enum (§3). An invalid value returns 400 `{"errors":{"NoticeType":["Pole 'Notice Type' ma zakres wartości, który nie obejmuje X."]}…}` |
| `PublicationDateFrom` / `PublicationDateTo` | **required** | optional | See the date pitfall in §9.3: prod and mirror **interpret the time part differently** |
| `PageSize` | **required** (>0) | default 10 | Max 500 today on both. Prod drops to 100 on 11.01.2027. **Use 100 now** |
| `SearchAfter` | ✓ | ✓ | `objectId` of the last item of the previous page (keyset paging). Verified on prod. There is no page number or total count |
| `NoticeNumber` | ✓ | ✓ | `2022/BZP 00115288` (any version) or `2022/BZP 00115288/01` (exact version). URL-encode the space (`%20`) |
| `OrganizationName` | ✓ | ✓ | **Case-insensitive substring.** On prod, `oława` matched both "Gmina Oława" and "Gmina Miasto Oława". `Wolin` also matches "GARWOLIN". Always post-filter by NIP |
| `OrganizationCity` | ✓ | ✓ (exact, case-folded) | City of the buyer |
| `OrganizationProvince` | ✓ | ✓ | `PL02` … `PL32` = `PL` + 2-digit TERYT voivodeship code |
| `CpvCode` | ✓ | ✓ | **Substring of the `cpvCode` string**, so it matches main *and* additional codes. `45231300` and `452313` both work. On prod, `CpvCode=45231300` returned notices whose main CPV is `45000000-7`. Main CPV must be taken from the body |
| `OrderObject` | ✓ | ✓ | Substring of the title. On prod, `OrderObject=Godzikowice` returned 2 hits |
| `OrderType` | ✓ | ✓ | `Works` / `Services` / `Delivery`. Can be `null` in the data for some types |
| `OrganizationNationalId`, `TenderId`, `BzpNumber`, `OrganizationId`, `pageNumber` | **ignored** (verified for NIP and TenderId on prod) | ignored | Returns an unfiltered page, which is a silent failure. **From 11.01.2027 this returns 404** |

Ordering differs. **Prod returns results ascending by `objectId`**: publication dates are not monotonic inside a page, as verified. The **mirror defaults to descending `publicationDate`**. Don't rely on either. Dedupe by `objectId`.

```bash
# 1) Notice by number (mirror; swap host for production)
curl -s "https://bzp.cytr.us/mo-board/api/v1/notice?NoticeType=ContractNotice&NoticeNumber=2022/BZP%2000058537/01"

# 2) Production needs dates + PageSize; date-only params = whole days inclusive
curl -s "https://ezamowienia.gov.pl/mo-board/api/v1/notice?NoticeType=TenderResultNotice&NoticeNumber=2022/BZP%2000115288&PublicationDateFrom=2022-01-01&PublicationDateTo=2022-12-31&PageSize=100"

# 3) All notices of one buyer (substring), then filter NIP/tenderId client-side, keyset paging
curl -s "https://bzp.cytr.us/mo-board/api/v1/notice?NoticeType=ContractPerformingNotice&OrganizationName=Czernikowo&PublicationDateFrom=2021-01-01&PublicationDateTo=2026-12-31&PageSize=100"
curl -s "https://bzp.cytr.us/mo-board/api/v1/notice?NoticeType=ContractPerformingNotice&OrganizationName=Czernikowo&PublicationDateFrom=2021-01-01&PublicationDateTo=2026-12-31&PageSize=100&SearchAfter=<objectId-of-last>"

# 4) Wod-kan works in one voivodeship in a time window
curl -s "https://bzp.cytr.us/mo-board/api/v1/notice?NoticeType=ContractNotice&CpvCode=45232&OrganizationProvince=PL30&PublicationDateFrom=2025-01-01&PublicationDateTo=2025-12-31&PageSize=100"

# 5) Mirror metadata
curl -s https://bzp.cytr.us/info
```

### 2.2 Other production paths

| Path | Status | Use |
|---|---|---|
| `/mo-board/api/v1/Board/GetNoticePdfById?noticeId=<objectId>` | **verified** 200 `application/pdf` (87 KB). With a notice *number* instead it returns 404 | Archive the official PDF as the citation document (store `retrieved_at` and sha256) |
| `https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/<objectId>` | 200 (SPA shell) | Human-readable link for the UI and citations |
| `/mo-board/api/v1/notice/stats?PublicationDateFrom&PublicationDateTo` | **(unverified)**, reported by third parties; 404 on the mirror | Counts per type |
| `/mo-board/api/v1/Board/Search`, `mp-readmodels/api/Search/GetTenderLinkedNotices?tenderId=` | **(unverified)**. An open-contracting issue reports that `GetTenderLinkedNotices` returns `[]` and `Board/Search` has no tenderId filter | Don't build on these |

---

## 3. Notice types

The production enum, verified by sending each value: valid values return data, invalid ones return 400.

| `NoticeType` | Polish name | In mirror | Role for Risk Miner |
|---|---|---|---|
| `ContractNotice` | Ogłoszenie o zamówieniu | ✓ | Procedure start: scope, parts, CPV, duration, criteria, planned contract changes (7.4), deadlines |
| `TenderResultNotice` | Ogłoszenie o wyniku postępowania | ✓ | Estimate (net), offers count, min/max/winning price, contractor, contract date, value, period. **Cancellation reason** |
| `AgreementUpdateNotice` | Ogłoszenie o zmianie umowy | ✓ | One change: legal basis (art. 455), reason, description, value. Published only for art. 455 ust. 1 pkt 3/4 changes |
| `ContractPerformingNotice` | Ogłoszenie o wykonaniu umowy | ✓ | **Actual end date, on-time flag, ALL changes with basis/reason/value, total paid, "performed properly", free-text extra info (penalties, permits, acceptance dates)** |
| `NoticeUpdateNotice` | Ogłoszenie o zmianie ogłoszenia | ✗ (prod only) | Changes to the CN during tendering (deadline extensions, SWZ changes). Useful for R01/R09/R11 signals |
| `AgreementIntentionNotice` | Ogłoszenie o zamiarze zawarcia umowy | ✗ | Non-competitive awards |
| `SmallContractNotice` | Ogłoszenie o zamówieniu (art. 2 ust. 1 pkt 1) / small contracts | ✗ | Below 130 k PLN |
| `CompetitionNotice`, `CompetitionResultNotice` | Konkurs | ✗ | Design contests |
| `ConcessionNotice`, `ConcessionAgreementNotice`, `ConcessionUpdateAgreementNotice`, `NoticeUpdateConcession` | Koncesje | ✗ (the mirror rejects them as invalid) | Out of scope |

Rejected on prod (400): `ContractAwardNotice`, `ConcessionResultNotice`, `ConcessionAgreementUpdateNotice`, `ConcessionPerformingNotice`, `TransportServiceNotice`, plan-type names.

**Procurement plans** (`plan postępowań`) are **not** served by this endpoint. They only appear as references in the CN and result notice: field `2.9.) Numer planu postępowań w BZP: 2024/BZP 00068732/03/P`, plus `2.10` (position).

**Recognising the type.** Use `noticeType`. The HTML title line (`Ogłoszenie o wyniku postępowania`, `Ogłoszenie o zmianie umowy`, `Ogłoszenie o wykonaniu umowy`) is a fallback. `procedureResult` is set only on result notices (`zawarcieUmowy`, `uniewaznienie`), with one value per part joined by `;` (e.g. `zawarcieUmowy;zawarcieUmowy;zawarcieUmowy;zawarcieUmowy`).

---

## 4. Response schema (top-level JSON)

One API record. Example: `samples/api_list_page_ContractNotice_default.json`.

| Field | Example | Notes / pitfalls |
|---|---|---|
| `objectId` | `08dca708-fd21-83c3-ba4f-e10001de327b` | Unique per notice. Cursor for `SearchAfter`, id for PDF and SPA links. **Primary key of the notice table** |
| `noticeType` | `TenderResultNotice` | Enum §3 |
| `noticeNumber` | `2024/BZP 00418711/01` | Notice number + **version** (`/01`, `/02`…). A different version is a correction of the same notice |
| `bzpNumber` | `2024/BZP 00418711` | Number without the version. Each notice type has **its own** number. It is *not* a procedure id |
| `tenderId` | `ocds-148610-6b092479-223f-11ef-87ba-8eb060fd7bb8` | **Procedure id** (Identyfikator postępowania) = OCDS OCID (prefix `ocds-148610`). Same across all notices of a procedure. Always compare the **full** string: older ids are UUIDv1 and share the last 12 hex chars across unrelated procedures |
| `publicationDate` | `2024-07-18T08:21:01.33Z` | UTC ISO, 1–7 fractional digits |
| `orderObject` | title | The CN title. Other types repeat the procedure title. Quotes, `„…”` and stray spaces are common |
| `cpvCode` | `45231300-8 (Roboty…),45232410-9 (…)` | **Comma-joined string of main + additional codes with labels.** The label text contains commas and `\xa0`, so split with the regex `\d{8}-\d`. The main CPV is only in the body (`4.2.6` CN, `4.5.3` result notice) |
| `orderType` | `Works` | `null` for some types |
| `clientType`, `tenderType` | `1.2`, `1.1.1` | Internal codes (buyer kind, procedure mode). Undocumented; use the body text instead |
| `isTenderAmountBelowEU` | `true` | `false` means the CN and result notice are in **TED** and the follow-ups reference `2023/S 123-456789` or eForms numbers |
| `submittingOffersDate` | `2024-06-21T07:00:00Z` | CN only |
| `procedureResult` | `zawarcieUmowy;uniewaznienie` | Result notice only. One value per part |
| `organizationName`, `organizationCity`, `organizationProvince` (`PL04`), `organizationCountry` | | The name varies between notices of the same buyer (Kartuzy has 2 variants) |
| `organizationNationalId` | `8792466869` | **NIP for 99 % of the copy.** 967 notices use a 9-digit REGON and 174 a 14-digit REGON. The body field `1.4` may show `REGON 910866761` even when the top-level value is the NIP |
| `organizationId` | `14540` | Platform buyer id. Stable, but not a filter on the mirror |
| `contractors` | `[{"contractorName","contractorCity","contractorProvince","contractorCountry","contractorNationalId"}]` | One entry per part on result notices. Often **`[{all null}]`** on performance and change notices (rows 8 and 22). `contractorNationalId` mixes NIP/REGON, with or without dashes, or `NIP:PL …`. **Parse the body instead** |
| `htmlBody` | `<html>…` 15–60 KB | **The full notice.** UTF-8; well-formed and regular (§5). The API has no structured value, date or change fields. Everything below comes from the HTML |

---

## 5. Notice body (`htmlBody`): structure and field map

The markup is regular. Each field is `<h3 class="mb-0">N.N.) Label: <span class="normal">value</span></h3>`, or `<h3>Label:</h3><p class="mb-0">long value</p>`. Sections are `<h2 class="bg-light …">SEKCJA …</h2>`. A footer line `YYYY-MM-DD Biuletyn Zamówień Publicznych…` closes the body (strip it). The field codes are stable per notice type, so a robust parser is: HTML → lines → `^(\d+(\.\d+)*)\.?\)\s*label: value` with continuation lines → ordered list of `(code, label, value)`. **Codes repeat** (per part, per change), so keep the order and segment it. Multi-part markers:

* CN section IV: a plain line `Część N` before each part's `4.2.x` block.
* Result notice section IV: `Część N` before each `4.5.5) Wartość części`. Section V+ per part: `SEKCJA V ZAKOŃCZENIE POSTĘPOWANIA (dla części N)`.
* Performance notice: one notice **per contract**. Repeated `5.4.2) Numer zmiany` blocks.
* Change notice: one notice per change. Part shown as text in 3.6 (`… Umowa dla części nr 1`).

### 5.1 ContractNotice: key codes (tryb podstawowy form; the EU-threshold forms are in TED)
| Code | Field | → model |
|---|---|---|
| 1.2 / 1.4 / 1.5.x | buyer name / national id (`REGON …` or `NIP …`) / address, NUTS3 | Buyer |
| 2.3 / 2.4 / 2.5 / 2.6 / 2.7 | title / **tenderId** / number / version / date | Procurement, Notice |
| 2.9 / 2.10 | procurement plan number (`…/P`) / plan position | Procurement.plan_ref |
| 2.14 (+2.15) | EU co-financing Tak/Nie (+ programme/project name: KPO, PROW, FEnIKS…) | Funding link |
| 2.16 | procedure mode + legal basis (`art. 275 pkt 1/2`) | Procurement.mode |
| 3.1 | **URL of the procurement platform** (platformazakupowa.pl, ezamowienia…): where SWZ, PFU and PPU live | Document discovery |
| 4.1.2 / 4.1.4 / 4.1.8 / 4.1.9 | reference no. / parts are separate procedures / partial offers / **number of parts** | Procurement |
| per part: 4.2.2 / 4.2.6 / 4.2.7 / 4.2.8 / 4.2.10 | description / **main CPV** / extra CPV / options / **duration** (`13 miesiące`, `160 dni`, `do 2026-04-27`) | Lot |
| 4.3.x | criteria + weights (price 60 %, warranty 40 %) | Lot.criteria |
| 6.4 / 6.5 / 6.7 | wadium / performance bond / **cancellation if funds not granted** (R13 signal) | Procurement flags |
| 7.1 / 7.3 / **7.4** | advances / contract changes foreseen / **type and scope of foreseen changes** (the art. 455 ust. 1 pkt 1 clauses) | Contract terms (R05/R07/R08) |
| 8.1 / 8.3 / 8.4 | offer deadline / opening / bid validity | Procurement timeline |

There is **no estimated value in the BZP contract notice.** The estimate appears in the result notice (4.3, net) and per part (4.5.5).

### 5.2 TenderResultNotice
| Code | Field | → model |
|---|---|---|
| 2.4 / 2.5 / 2.7 | tenderId / number / date | Notice |
| 2.11 (+2.12) | EU funding (+ programme) | Funding |
| 2.13 / **2.14** | preceded by a notice / **CN number** (no version) | link → CN |
| 4.2 | parts are separate procedures | |
| **4.3** | **Wartość zamówienia: estimate, NET, whole procedure** | Procurement.estimate_net |
| per part **4.5.5** | Wartość części (net estimate of the part) | Lot.estimate_net |
| per part 5.1 / **5.2 / 5.2.1** | outcome (contract / cancelled) / **legal basis of cancellation** (e.g. `art. 255 pkt 3`: price above budget) / **reason text** | Lot.outcome, RiskEvent (R11/R13) |
| per part 6.1, 6.1.3, 6.1.6, 6.1.7 | offers received, from SMEs, rejected, abnormally low | Lot.competition |
| per part **6.2 / 6.3 / 6.4** | lowest / highest / **winning price (GROSS)** | Lot.prices |
| per part 7.1 / 7.2 / **7.3.1 / 7.3.2** / 7.3.3-7 / 7.4.1 | joint bidders / SME size / **contractor name / id** / address / subcontractors | Contractor |
| per part **8.1 / 8.2 / 8.3** | **contract date / contract value (GROSS) / period** | Contract |

### 5.3 AgreementUpdateNotice (one change)
| Code | Field | → model |
|---|---|---|
| 2.2 / 2.3 / 2.5 | tenderId / number / date | Notice |
| **3.1.1** / 3.6 | **CN number** / title (+ `Umowa dla części nr N`) | link → CN, Lot |
| 4.1 / 4.2 / 4.3.1 / 4.3.2 / **4.4** / **4.5** | contract date / period / contractor / id / **contract value** / **result notice number with version** | link → Contract |
| **5.1** | date of the change | ContractChange.date |
| **5.2** | legal basis (`art. 455 ust. 1 pkt 3/4`) | ContractChange.legal_basis |
| **5.3** | reasons (free text) | ContractChange.reason → risk extraction |
| **5.4** | description (often the new end date or the new gross price as text) | ContractChange.description |
| **5.5.1 / 5.5.2 / 5.5.3** | value of change / currency / price increased Tak/Nie | ContractChange.value |
| 5.6 | earlier changes requiring a notice | |

### 5.4 ContractPerformingNotice (one per contract): the most valuable notice
| Code | Field | → model |
|---|---|---|
| 2.1 / 2.2 / 2.4 | tenderId / number / date | Notice |
| 3.1 | contract class (`klasyczne poniżej progów UE` …) | |
| **3.2.1** | **CN number: BZP *or TED*** (`2021/S 066-170270`, `2024-OJS001-002017`, also typos like `2021/BZ00084006/01`). Copy-wide: 24 962 BZP, 921 TED, 59 other, 900 missing | link → CN |
| 3.3 (+3.4) | EU funding (+ programme name) | Funding |
| 4.1 / **4.2** / 4.3.1 (4.3.1.1 consortium) / 4.3.2 / **4.4** / **4.5** | contract date / **original period** / contractor / id / **original value** / **result notice number** | Contract (original) |
| **5.1** (5.1.1) | executed Tak/Nie (+ reason if not) | Performance.executed |
| **5.2** | **actual completion date** | Performance.end_date |
| **5.3** | completed within the *original* term Tak/Nie. Self-reported and **inconsistent**: Elbląg says "Tak" after a +4-month extension, so compute the delay yourself | Performance.on_time_reported |
| **5.4.1** | number of changes | |
| per change **5.4.2 / 5.4.3 / 5.4.4 / 5.4.5 / 5.4.6 / 5.4.7 / 5.4.8** | no / **legal basis** / **reasons** / description after change / **value** / currency / price increase | ContractChange (complete list, including art. 455 ust. 1 pkt 1 and ust. 2 changes that have no separate notice) |
| **5.5** | **total paid to the contractor** | Performance.paid_total |
| **5.6** | performed properly Tak/Nie | Performance.properly |
| 5.7 | requirements checked (art. 95) | |
| **SEKCJA VI** | free text: **penalties** ("kary umowne … 455 372,57 zł za 28 dni opóźnienia"), permit numbers, final acceptance dates, "stan na dzień …" (paid total still interim!) | RiskEvent evidence |

---

## 6. Linking: project → procurement → notices → contracts

### 6.1 Identifiers
* **Notice number normalisation.** Parse `(\d{4})\s*[/\-_ ]\s*BZP\s*[/\-_ ]?\s*0*(\d{1,8})(?:\s*[/\-_ ]\s*(\d{1,2}))?` (also `BZP 2022/…`). Normalise to `YYYY/BZP NNNNNNNN` (8 digits, zero-padded, one space) plus an optional 2-digit version. Query `NoticeNumber=<base>/<ver>`. If that returns nothing, query `<base>` without the version for each of the 4 types: the dataset number might be a result or performance notice. Tested on `2022/BZP 58537/1`, `BZP 2022/00058537/01`, `2022-BZP-00058537-01` and `2022 / BZP 00058537 / 02`.
* **Procedure** = `tenderId` (OCID). **Notice** = `objectId`, with business key `noticeNumber`.
* **Cross-references in bodies** (verified):
  * result notice `2.14` → CN base number
  * change notice `3.1.1` → CN, `4.5` → result notice (with `/01`)
  * performance notice `3.2.1` → CN (BZP or TED), `4.5` → result notice
  * CN and result notice `2.9` → plan
* **Contract (lot) ↔ follow-up notice.** Performance and change notices exist per contract but carry no part number field. Match on the **contract value (4.4 == result notice per-part 8.2, ±1 PLN) + contractor name/id + contract date**. Change notices sometimes say `Umowa dla części nr N` in 3.6. In Biecz (4 parts) and Zakrzew (2 parts) this matched every performance notice uniquely.

### 6.2 Algorithm used (works on mirror and production)
1. **BZP row:** normalise the number → `NoticeType=ContractNotice&NoticeNumber=…` → take `tenderId` and `organizationName`. Check the NIP (dataset vs `organizationNationalId`), the province (`PL`+TERYT), the title token overlap, and the part/scope (§7).
2. **Pull the buyer's notices:** for each of the 4 types, `OrganizationName=<stem>` (the longest word of the buyer name, stemmed: `Kartuz`, `Grodzis`, `Zagrod`), unioned with the CN's exact `organizationName`, using `PublicationDateFrom=2021-01-01` and keyset paging. Keep the records where `organizationNationalId == NIP`. Across the 22 rows this took 154 uncached calls on the mirror. On production the buyer pulls return all sectors, so allow ~6–10 minutes at 30 req/min, or reuse the cache.
3. **Chain:** take all notices with the same `tenderId`. Add any notice whose body contains a chain number (catches re-keyed procedures; none were needed for these 22).
4. **Number not found (row 22):** search the buyer's notice bodies for the base number. The follow-up notices' `3.2.1` and `3.1.1` fields gave the `tenderId`. The CN is "missing from the source", **not** "doesn't exist".
5. **KPO-only rows:** group the NIP-filtered buyer notices by `tenderId`. Score = token overlap between {project name + KPO description} and the procedure title (Polish diacritics folded, 6-char stems, stop-words removed), +0.1 for a wod-kan CPV (`4523*`, `45252*`…), +0.1 for a first notice ≥ 2024 (KPO B3.1.1 era). Then corroborate:
   * a funding mention in the body: `Krajow\w+ Plan\w* Odbudowy`, or the exact project number via `KPOD\.\d{2}\.\d{2}-IW\.\d{2}-\d{4}/\d{2}`. **The Kamionka notices contain `KPOD.03.15-IW.15-0081/25` verbatim, which makes an exact key possible.**
   * the KPO "Wartość przedsięwzięcia" vs the sum of contract values or of paid totals. Exact for rows 2 and 5, within 6 % for rows 9, 10, 17, 18 and 20.
   * Report the top 3 candidates with scores. Here, all 8 top candidates had exact titles (score 1.2). The runner-ups were 0.41–0.87 and were mostly real sibling procedures (another sewer stage, an SUW tender), so **show the expert the runner-up** and do not auto-approve below a margin.
6. **Repeated or cancelled earlier procedures** for the same scope (same NIP, title Jaccard ≥ 0.5, result notice `uniewaznienie`). Found examples:
   * Row 6 Gościeradów: cancelled twice (2022/BZP 00498890 → 2023/BZP 00015415; 2023/BZP 00243364 → 2023/BZP 00262901) before the 2024 award.
   * Row 15 Elbląg/Janów: 2023/BZP 00086866 cancelled 2023-03-23.
   * Row 12 Kartuzy: a sister procedure, "Smętowo Chmieleńskie network", was cancelled 2025-02.
   * Row 5 Zławieś: SUW tenders cancelled twice in 2022.

   These are R11/R13 risk events that the dataset alone never shows.

---

## 7. Results on the 22 dataset rows

Produced by `link_projects.py` (mirror) and cross-checked against the offline copy. One row per **contract**. "~" means the planned end was computed from a duration (`N miesiące/dni`) plus the contract date. Δ cost = (5.5 paid − 8.2 contract) / contract, both gross. "Changes (AUN/CPN)" = number of separate change notices / changes listed in the performance notice.

| # | Dataset key | Method | CN | TRN | Part | Contractor (ID) | Contract PLN | Planned end | Actual end | Delay d | Changes (AUN/CPN) | Paid PLN | Δ cost | Done properly |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BZP 2022/BZP 00058537/01 | number | 2022/BZP 00058537/01 | 2022/BZP 00115288/01 | – | COMPLEX-BUD Leon Szuturma (9120005157) | 2 107 348 | ~2023-04-06 | 2023-06-22 | ~77 | 0/6 | 2 246 178 | +6.6% | Tak |
| 2 | KPO KPOD.03.15-IW.13-0004/25 | search 1.2 | 2026/BZP 00089794/01 | 2026/BZP 00143366/01 | – | PTB … (8992507768) | 5 350 783 | ~2026-05-05 | 2026-06-01 | ~27 | 0/1 | 5 350 783 | 0.0% | Tak |
| 3 | BZP 2024/BZP 00349631/01 | number | 2024/BZP 00349631/01 | 2024/BZP 00418711/01 | – | ZUMiG Piotr Rojek (870113012) | 2 131 590 | 2025-08-18 | 2026-05-22 | 277 | 2/3 | 2 990 000 | +40.3% | Tak |
| 4 | BZP 2025/BZP 00569258/01 | number | 2025/BZP 00569258/01 | 2026/BZP 00061193/01 | – | Instalcompact (004780325) | 3 918 954 | 2026-07-22 | 2026-10-28 | 98 | 0/4 | 4 134 920 | +5.5% | Tak |
| 5 | KPO KPOD.03.15-IW.14-0032/25 | search 1.2 | 2025/BZP 00245492/01 | 2025/BZP 00342797/01 | – | Wimar (9670644141) | 2 936 010 | 2025-10-30 | 2025-12-05 | 36 | 0/1 | 3 087 492 | +5.2% | Tak |
| 6 | BZP 2024/BZP 00067908/01 | number | 2024/BZP 00067908/01 | 2024/BZP 00245620/01 | – | EKOMEL (8620002084) | 2 499 110 | ~2024-07-11 | 2024-09-30 | ~81 | 2/2 | 2 604 551 | +4.2% | Tak |
| 7 | KPO KPOD.03.15-IW.15-0081/25 | search 1.2 (+exact KPOD no. in body) | 2026/BZP 00139226/01 | 2026/BZP 00204390/01 | – | HYDRO-SYSTEM M. Kwiatkowski + Energopol (946 210 51 81) | 1 478 460 | 2026-04-30 | 2026-05-19 | 19 | 0/0 | 1 468 960 | −0.6% | **Nie** |
| 8 | BZP 2026/BZP 00084760/01 (część 1) | number | 2026/BZP 00084760/01 | 2026/BZP 00166534/01 | 1 | Multikop (NIP 7380005265) | 1 952 121 | 2026-04-27 | 2026-04-27 | 0 | 0/1 | 2 375 309 | +21.7% | Tak |
| 8 | 〃 | 〃 | 〃 | 〃 | 2 | PBWS „POTOK” (NIP 7381000991) | 1 200 000 | 2026-04-27 | 2026-04-27 | 0 | 0/0 | 1 200 000 | 0.0% | Tak |
| 8 | 〃 | 〃 | 〃 | 〃 | 3 | Multikop (NIP 7380005265) | 1 113 624 | 2026-04-27 | 2026-04-27 | 0 | 0/1 | 1 174 747 | +5.5% | Tak |
| 8 | 〃 | 〃 | 〃 | 〃 | 4 | PBWS „POTOK” (NIP 7381000991) | 205 000 | 2026-04-27 | 2026-04-27 | 0 | 0/0 | 205 000 | 0.0% | Tak |
| 9 | BZP 2025/BZP 00307948/01 (część 2) | number | 2025/BZP 00307948/01 | 2025/BZP 00422149/01 | 1 | INSBUD-KLWÓW (6010052935) | 420 935 | 2025-11-15 | 2025-12-25 | 40 | 0/1 | 420 935 | 0.0% | Tak |
| 9 | 〃 | 〃 | 〃 | 〃 | 2 | AQUA SEEN (113-285-55-84) | 1 810 534 | 2025-11-15 | 2025-11-13 | −2 | 0/1 | 1 881 383 | +3.9% | Tak |
| 10 | KPO KPOD.03.15-IW.21-0025/25 | search 1.2 | 2025/BZP 00211437/01 | 2025/BZP 00347687/01 | – | HYDRO-MONT ŻĄDŁO (NIP 8181738304) | 3 348 882 | 2025-11-15 | 2025-12-30 | 45 | 0/1 | 3 348 882 | 0.0% | Tak |
| 11 | BZP 2023/BZP 00271948/01 | number | 2023/BZP 00271948/01 | 2023/BZP 00328063/01 | – | ZIB Edward K. (8191004590) | 2 880 536 | ~2023-12-27 | 2023-12-21 | ~−6 | 0/1 | 3 134 219 | +8.8% | Tak |
| 12 | BZP 2025/BZP 00119683/01 | number | 2025/BZP 00119683/01 | 2025/BZP 00245411/01 | – | PI Drewa (5882257375) | 3 616 200 | ~2025-10-26 | 2025-12-23 | ~58 | 0/2 | 3 650 944 | +1.0% | **Nie** |
| 13 | BZP 2023/BZP 00206497/01 | number | 2023/BZP 00206497/01 | 2023/BZP 00261764/01 | – | EKOINSTAL (070448938) | 5 991 656 | ~2024-10-15 | 2024-11-15 | ~31 | 0/2 | 6 397 551 | +6.8% | Tak |
| 14 | BZP 2026/BZP 00130634/01 | number | 2026/BZP 00130634/01 | 2026/BZP 00195507/01 | – | ALFA B. Habrajska (6250001699) | 1 193 100 | 2026-05-13 | 2026-06-23 | 41 | 0/2 | 1 294 008 | +8.5% | **Nie** |
| 15 | BZP 2023/BZP 00135041/01 | number | 2023/BZP 00135041/01 | 2023/BZP 00198087/01 | – | ENERGO-EKO (5932607246) | 3 744 316 | ~2025-04-28 | 2025-09-25 | ~150 | 2/2 | 4 703 040 | +25.6% | Tak |
| 16 | BZP 2022/BZP 00308854/01 | number | 2022/BZP 00308854/01 | 2022/BZP 00377000/01 | – | Iławskie PI (NIP 7440003354) | 4 879 410 | ~2025-01-04 | 2025-02-04 | ~31 | 0/2 | 5 067 267 | +3.9% | Tak |
| 17 | KPO KPOD.03.15-IW.27-0013/25 | search 1.2 | 2025/BZP 00358528/01 | 2026/BZP 00000230/01 | – | COMPLEX INSTAL M. Grygier (7851634441) | 4 275 776 | ~2026-04-23 | 2026-06-15 | ~53 | 0/1 | 5 422 833 | +26.8% | Tak |
| 18 | KPO KPOD.03.15-IW.27-0107/25 | search 1.2 | 2025/BZP 00620692/01 | 2026/BZP 00194260/01 | – | PW TOR (6210006578) | 3 665 400 | ~2026-05-08 | 2026-06-17 | ~40 | 0/1 | 4 194 313 | +14.4% | Tak |
| 19 | BZP 2024/BZP 00354928/01 | number | 2024/BZP 00354928/01 | 2024/BZP 00451447/01 | – | Brukarstwo i Handel W. Kasprzak (6211268694) | 3 154 933 | 2024-11-22 | 2025-12-22 | **395** | 0/6 | 4 186 736 | +32.7% | Tak |
| 20 | KPO KPOD.03.15-IW.28-0003/24 | search 1.2 | 2025/BZP 00113651/01 | 2025/BZP 00206455/01 | – | Konsorcjum „Starkan” (REGONs 369467516, 320468735) | 1 969 611 | ~2025-10-24 | 2026-04-27 | ~185 | 2/2 | 1 719 611 | −12.7% (penalties) | Tak |
| 21 | BZP 2025/BZP 00364116/01 | number | 2025/BZP 00364116/01 | 2025/BZP 00434530/01 | – | „STARKAN” (8542420234) | 5 421 102 | ~2026-07-22 | 2026-09-28 | ~68 | 1/1 | 2 979 984 | −45.0% (interim; penalty 455 372,57 zł) | **Nie** |
| 22 | BZP 2023/BZP 00110672/01 | refs in CPN/AUN | **missing in API** | **missing** (2023/BZP 00178669/01 cited) | 1 | PPH Artex (NIP 6690503086) | 2 230 851 | ~2023-09-11 | 2023-08-31 | ~−11 | 1/2 | 2 827 552 | +26.7% | Tak |
| 22 | 〃 | 〃 | 〃 | 〃 | 2 | ZUBWIT RESKO (NIP 8570210827) | 7 098 003 | ~2024-05-11 | 2024-05-23 | ~12 | 0/2 | 7 869 565 | +10.9% | Tak |

**Hit rate:**

| Measure | Result |
|---|---|
| Procedure (tenderId) identified | **22/22**: 13 BZP rows by number, 1 BZP row via references, 8 KPO rows by search |
| Contract notice | 21/22 |
| Result notice | 21/22 |
| Contractor + contract value | 22/22 (27 contracts; for row 22 rebuilt from the performance and change notices) |
| Change notices | 10 notices in 6 projects (rows 3, 6, 15, 20, 21, 22) |
| Performance notice | **27/27 contracts** |
| Planned vs actual end | 27/27 (13 exact dates, 14 computed from a duration) |
| Planned vs paid value | 27/27 |
| Completeness vs offline copy | 100 % (identical notice sets per tenderId). No foreign-tenderId notice cites a chain number |
| Risk-signal yield | 20/27 contracts late. 19/27 overrun (median of overruns +8.5 %, max +40.3 %). 3 below contract value (penalties or interim). 4 "not properly performed". 48 changes in performance notices (art. 455 ust. 1 pkt 1 ×29, ust. 2 ×12, ust. 1 pkt 4 ×5, ust. 1 pkt 3 ×3) |

Examples of what the notices tell us (good demo material, all with source):

* **Row 3, Steklin oczyszczalnia (design-and-build).**
  * Change 1 (2024/BZP 00554831): +758 084,56 zł, art. 455 ust. 1 pkt 3, "zwiększenie zakresu robót w stosunku do … PFU". Points to R01 (incomplete scope in the PFU).
  * Change 2: +100 325,44 zł, replacing asbestos-cement water pipes. Points to R02 (unknown existing state).
  * Change 3: deadline moved to 2026-05-26 because of a slow water-law permit from Wody Polskie. Points to R04 (third-party permits).
  * Paid 2 990 000,00 zł = 2 131 590 + 758 084,56 + 100 325,44 exactly. 277 days late.
* **Row 20, Konarzewo.** Two art. 455 ust. 1 pkt 4 extensions: a missing transmission easement on plot 3/39 (R03, land rights) and adverse ground and groundwater conditions (R02). The final payment was reduced by penalties ("pomniejszona o kary umowne").
* **Row 21, Nowogard ul. 700-lecia.** Extension due to the regional road administration's (ZZDW) roundabout works (R03/R05, coordination). Penalty 455 372,57 zł for 28 days of delay. Marked "not performed properly". Paid total is "stan na dzień 21.10.2026", i.e. **interim**.
* **Row 9, Zakrzew część 1.** Weather delay. Note that its "5.4.6 Wartość zmiany" = 420 935,30 = the **whole contract value**, not a delta (pitfall §9.6).
* **Row 7, Kamionka.** The contract is signed 2026-04-09 with an end date of 2026-04-30. A **21-day schedule** (R06) leads to a 19-day delay and "not performed properly".
* **Row 19, WZDW Sulmierzyce.** +395 days, +32.7 %, 6 changes under art. 455 ust. 1 pkt 1.

---

## 8. Dataset errors and anomalies found

| Row | Finding | Evidence | Suggested handling |
|---|---|---|---|
| 9 Zakrzew | **Wrong part.** The record says "część 2", but the KPO description (water-main sections in Natalin, Dąbrówka Podłężna, Podlesie Mleczkowskie, plot numbers 85, 100/1, 59, 61, 63, 98, 99/1, 97, 237/1) is CN 2025/BZP 00307948 **część 1** ("budowa sieci wodociągowej (trzy zadania)"). Część 2 is the "modernizacja stacji uzdatniania wody w Zakrzewie". The KPO value 2 329 043,45 ≈ the **sum of both parts paid** (2 302 318,45; −1.2 %), so the KPO project may span both parts | CN section IV per-part 4.2.2; performance notices 2025/BZP 00568576, 00568661 | Flag "scope mismatch". Propose część 1 as primary and both parts as candidates for expert decision |
| 8 Biecz | **Wrong scope.** "część 1", but the KPO description lists all 4 localities with lengths 4529 + 3794 + 2907 + 641 m = 11.871 km, which is exactly CN parts 1–4. The KPO value 6 188 345,13 vs the 4 parts' paid sum 4 955 056,04 (−20 %) | CN 2026/BZP 00084760 parts I–IV | Link the project to all 4 contracts |
| 22 Wolin | CN **2023/BZP 00110672/01 not retrievable**: not on the mirror and not on production (`NoticeNumber`, all types, 2023). Its result notice 2023/BZP 00178669/01 is also absent. The number is **genuine**: performance notices 2023/BZP 00580488 and 2024/BZP 00621519 cite it in 3.2.1. Production has a `NoticeUpdateNotice` 2023/BZP 00121965/01 for the same tenderId. The procedure had 2 contracts (parts) despite "całe postępowanie" | §6.2 step 4 | Mark the CN "missing from source, referenced by 2 notices". Don't report the number as wrong |
| 7 Kamionka | KPO value 3 096 863,90 vs contract 1 478 460 (−52 %). The link itself is certain because the notice body contains `KPOD.03.15-IW.15-0081/25` | result notice/CN 2.14+ | Flag a value inconsistency (the KPO value includes more, or there is another contract outside wod-kan CPV) |
| 14 Bobrowniki | KPO value 1 714 989 vs paid 1 294 008 (−25 %) | | Informational |
| 2 Zagrodno | KPO value = contract value = paid = 5 350 782,65. Also = result notice estimate 4 350 229,80 × 1.23 | | Plausible (bid at budget). Informational |
| 3, 4, 15, 16, 22 | No funding annotation in the dataset, but the notices name the source: Polski Ład (3, 16, 22), FEnIKS/FEdKP 2021-27 (4), PROW 2014-20 (15) | 2.14/3.3 text | Enrich the funding field automatically |
| all | All 20 distinct NIPs pass the checksum and equal `organizationNationalId`. All provinces match TERYT. No wrong-NIP case was found in these 22 rows (the check is implemented anyway) | | Keep the checks; they will catch errors in new rows |

---

## 9. Pitfalls

1. **No NIP or tenderId filter.** Silent today, 404 from 2027-01-11. Filter by `OrganizationName` substring, then client-side. A substring over-matches ("Wolin" ⊂ "Garwolin") and an exact name under-matches (name variants), so stem the name and union the queries.
2. **Paging.** Keyset only (`SearchAfter=objectId`). No total count. Stop when `len(page) < PageSize`. Use `PageSize=100` (the 2027 cap). Dedupe by `objectId`. Don't assume any sort order: prod sorts by objectId ascending, the mirror by date descending.
3. **Date params differ between production and the mirror.**
   * Production: with time-stamped params (`To=2022-03-01T23:59:59`), production returned notices published up to **2022-03-02T21:06Z** (302 of 500 outside the window). With **date-only** params (`From=To=2022-03-01`) it returned exactly that day (335).
   * Mirror: compares strings, so `To=2022-03-01` (date-only) **excludes** that whole day, and `To=2022-03-01T23:59:59` works.
   * Portable approach: query `From=D` and `To=D+1` (date-only), then filter `publicationDate` client-side and dedupe.
4. **Numbers.** `2022/BZP 00058537/01` = year / 8-digit zero-padded number / 2-digit version. Each notice type has its own number. Versions `/02`+ are corrections, so keep the latest per base number but store all. References inside bodies come with and without the version (`2.14` without, `4.5` with). Free-text typos occur (`2021/BZ00084006/01`).
5. **Net vs gross.** Result notice `4.3 Wartość zamówienia` and per-part `4.5.5 Wartość części` are **net** estimates. Offer prices (6.2–6.4), contract value (8.2/4.4), change values (5.5.1/5.4.6) and paid total (5.5) are **gross**. Compare like with like: estimate × 1.23 (VAT on works) for budget-vs-price. The KPO "wartość przedsięwzięcia" is a project value, not a contract value.
6. **"Wartość zmiany" is ambiguous.** Usually a delta (row 3: +758 084,56). Sometimes buyers enter the **new total** (row 9 part 2: 1 881 383,15 vs contract 1 810 533,92) or the **whole contract value** (row 9 part 1: 420 935,30). It is empty for time-only changes. Heuristic: if value ≥ 0.9 × contract value, treat it as the new total; otherwise as a delta. Cross-check against `5.5` paid minus `4.4`.
7. **Duration vs date.** The period is `do 2025-08-18`, `13 miesiące`, `160 dni` or `80 dni`. Compute the planned end = contract date (8.1/4.1) + duration and mark it as derived. Changes extend the term, but the performance notice keeps the *original* `4.2`, so the delay vs original is (5.2 − original end).
8. **Self-reported flags are unreliable.** `5.3` on-time "Tak" after a 4-month extension (row 15), and "Nie" when on the planned date. Inconsistent legal bases: change notices said art. 455 ust. 1 pkt 4 while the performance notice for the same changes says ust. 2 (row 6). Always keep both values with their source.
9. **Interim totals.** `5.5` may say "stan na dzień …" (row 21). Parse SEKCJA VI for "stan na dzień", "kary umowne", amounts and dates.
10. **Multi-part procedures.** One CN and one result notice cover N parts. Then there are N contracts, N performance notices, and change notices per contract. `procedureResult` and `contractors[]` are per part. Section markers are listed in §5. Part numbers in the dataset can be wrong (§8).
11. **IDs of contractors and buyers.** NIP/REGON-9/REGON-14 with prefixes and formatting (`NIP 7380005265`, `113-285-55-84`, `NIP:PL 6690503086`, `946 210 51 81`, `REGON 910866761`). Consortia list several ids and add `4.3.1.1` members. `contractors[]` can be all-null on performance and change notices. Normalise to digits, classify by length (10 = NIP with checksum, 9/14 = REGON with checksum), and keep the raw value.
12. **CPV string.** Labels contain commas and NBSP (`\xa0`), so split on the `\d{8}-\d` regex, not on commas. The main CPV is only in the body.
13. **Encoding.** UTF-8 JSON. Bodies contain `\xa0`, `\r\n` (production) vs `\n` (mirror), curly quotes `„”`, and `,,` used as quotes. Normalise the whitespace before regex. Polish diacritics: fold for matching (ł→l is not a Unicode decomposition, so handle it explicitly).
14. **TED procedures** (`isTenderAmountBelowEU=false`). CN and result notice are in TED, not BZP. Performance notice `3.2.1` holds a TED number (`2021/S 066-170270`, `2024-OJS001-002017`, `123456-2024`). That is 921 performance notices in the copy (~3.4 %). The TED linker needs these formats.
15. **Coverage gaps.** The mirror holds wod-kan works only and 4 types. A KPO project's other contracts (e.g. electrical or supervision services) or its `NoticeUpdateNotice`s are absent; production has them. A missing notice is a "missing from source" state, never "did not happen" (expert rule from material 03).
16. **Rate limit (production).** 30 req/min, then HTTP 403 HTML (not JSON). Back off ≥ 20 s and cache every response on disk keyed by URL.
17. **The UUIDv1 tenderId suffix collides** (e.g. `…-06954b8c6cb9` is shared by unrelated procedures). Never shorten tenderIds.

---

## 10. Data model mapping and ingestion recommendations

### 10.1 Entities (BZP-sourced fields)

```
Project (dataset row / CST / KPO)          project_id, kpo_no, nip, name, description, kpo_value, scope_part
  └─< ProjectProcurementLink                project_id, tender_id, part_no|null, method(number|refs|search),
  │                                         score, evidence[], status(proposed|approved|rejected), approved_by
Procurement (tenderId)                     tender_id(OCID), buyer_nip, buyer_name, title, mode(2.16), plan_ref(2.9),
  │                                         platform_url(3.1), parts_count(4.1.9), estimate_net(TRN 4.3),
  │                                         eu_funding(2.14/2.11 + programme), cpv_main, cpv_all[], cancelled_prior[]
  ├─< Lot (part)                           part_no, description(4.2.2), cpv_main(4.2.6), duration_text(4.2.10),
  │                                         estimate_net(4.5.5), outcome(5.1), cancel_basis(5.2), cancel_reason(5.2.1),
  │                                         offers(6.1), price_min/max/winner(6.2-6.4, gross)
  ├─< Notice                               object_id(PK), notice_type, notice_number, version, bzp_number,
  │                                         published_at, html (raw), pdf_url, spa_url, retrieved_at, sha256,
  │                                         source_api(base url), refs{cn,trn,plan}
  └─< Contract (per lot)                   contractor_name, contractor_ids[], consortium[], signed_on(8.1/4.1),
        │                                   value_gross(8.2/4.4), period_text, planned_end(+derived flag)
        ├─< ContractChange                 source_notice, change_no, date(5.1), legal_basis(5.2/5.4.3),
        │                                   reason(5.3/5.4.4), description(5.4/5.4.5), value_raw, value_kind(delta|total|?),
        │                                   price_increase(Tak/Nie)
        └── Performance (CPN)              executed(5.1), end_date(5.2), on_time_reported(5.3), changes_count(5.4.1),
                                            paid_total(5.5), paid_is_interim, properly(5.6), extra_text(VI),
                                            penalties[] (parsed from VI), delay_days(derived), cost_delta(derived)
```

Every extracted value should carry `{notice object_id, field code (e.g. "5.4.4"), char span in html2text}`. That is the "fragment uzasadniający" the jury will check (Test źródłowy). Field codes make the citations precise and human-checkable: "Ogłoszenie o wykonaniu umowy 2026/BZP 00276065/01, pkt 5.4.4".

### 10.2 Ingestion code recommendations

1. **One client, two base URLs.** `BZP_BASE_URL` in config: mirror for development and the demo, production in config for the jury. Respect the 2027 rules now: `PageSize=100`, only known params, keyset paging. In tests, run `bzp_mirror.py --api-2027` locally against the offline copy.
2. **Cache everything** (raw JSON per request URL plus raw `htmlBody` per objectId, with `retrieved_at`). Re-runs become idempotent and offline-capable. The offline JSONL is also a perfect bulk seed: load it once into Postgres (≈113 k rows, ~10 s to stream), then use the API only for incremental updates, i.e. a "monitoring" job that polls `PublicationDateFrom=<last run>` per type and picks up new change and performance notices for open procedures. That last part is the challenge's bonus "moduł monitorowania".
3. **Linker order:** exact number → body references → tenderId chain → search (NIP + name stem + CPV + date + funding text + KPO number regex + value check). Persist candidates with scores and evidence. Auto-accept only exact-key matches (number, KPOD in body). Everything else is "proposed" for the expert.
4. **Parser:** HTML → text (stdlib `html.parser` is enough) → `(code, label, value)` list → per-type extractors keyed by **code** (not label; labels vary slightly between form versions) → segment by `Część N` and `(dla części N)` → money parser (`1 234 567,89 PLN`, no thousands separator in most fields) → dates (ISO, sometimes `dd.mm.yyyy` in free text) → duration parser. Keep the raw text for LLM risk extraction from 5.3, 5.4.4, 5.4.5, VI and 5.2.1.
5. **Derived facts** (store separately from source facts, as the challenge requires):
   * delay_days = 5.2 − planned_end
   * cost_delta = 5.5 − 8.2
   * changes by art. 455 point
   * competition (offers count, spread max/min)
   * estimate gap (winner gross vs estimate_net × 1.23)
   * prior cancellations
6. **Validation flags** surfaced in the expert panel: NIP checksum and match, province vs TERYT, title similarity, part/scope check (part-exclusive terms vs project description), KPO value vs contract/paid sums, CN-missing-but-referenced, interim payment, inconsistent legal basis, "Wartość zmiany" kind.
7. **Don't use** `contractors[]` or `cpvCode` as authoritative. Use body fields. Don't truncate tenderIds. Don't treat a missing notice as a non-event.

---

## 11. Artifacts (session scratchpad, not in repo)

Base: `/tmp/claude-1000/-home-dawid-home-pc--claude-spares-spare-uEjJKS/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/bzp/linking/`

* `link_projects.py`: the linker (stdlib only). `python3 link_projects.py [--base https://bzp.cytr.us] [--delay 2.1 for production]`. Writes `chains.json` (full per-project chains with extracted fields and URLs), `matrix.csv`, and `cache/`.
* `make_matrix.py`: renders `matrix.md` (the table in §7).
* `html2text.py`: the minimal HTML → lines converter used by the parser.
* `build_slim.py`: streams the 2.7 GB JSONL into `slim.jsonl` (all records without htmlBody) and `dataset_full.jsonl` (all notices of the 20 dataset NIPs, with htmlBody).
* `samples/`: raw API JSON and text renderings:
  * one per type for the Steklin chain: `ContractNotice_2024_BZP_00349631_01`, `TenderResultNotice_2024_BZP_00418711_01`, `AgreementUpdateNotice_2024_BZP_00554831_01`, `ContractPerformingNotice_2026_BZP_00276065_01`
  * multi-part `TenderResultNotice_multipart_2026_BZP_00166534_01.json`
  * performance notices with penalties: `ContractPerformingNotice_penalty_2026_BZP_00498447_01.json` and `…penalty2_2026_BZP_00291637_01.json`
  * an API list page: `api_list_page_ContractNotice_default.json`
  * the 400 error: `api_error_400_bad_NoticeType.json`

Third-party pages consulted (for unverified items only): [open-contracting/collect-generic#40](https://github.com/open-contracting/collect-generic/issues/40), [Apify bzp-scraper](https://apify.com/mrarcode/bzp-scraper.md), [Apify pl-public-tenders](https://apify.com/matikitli/pl-public-tenders.md), [e-Zamówienia integracja](https://ezamowienia.gov.pl/pl/integracja/), [planowane zmiany w API BZP](https://ezamowienia.gov.pl/pl/planowane-zmiany-w-api-bzp/).
