# 02: Public sources other than BZP: TED, KPO lists, BK2021, CRU, KPOŚK, NIK, KIO, BIP, entity registers

Research date: 2026-11-21. Scope: every public source **except BZP / e-Zamówienia**, which is covered in `01_bzp_api.md`. All claims marked *tested* come from real requests made today, at modest volume (≈250 requests in total across all hosts). Items marked **(unverified)** come from documentation, third parties or search snippets only.

Working request examples for every source are in one script: `/tmp/claude-1000/-home-dawid-home-pc--claude-spares-spare-uEjJKS/b5542eb7-66ed-4bf2-9e43-7258f9c7db4f/scratchpad/sources/examples.sh` (run `bash examples.sh ted|ted_modif|wl|bir|bip|cru|bk|kio|nik|bdl|mapa|kposk`). Raw responses, the TED field list (`ted_fields.txt`, 1 830 fields), the TED OpenAPI spec (`ted_api_v3.yaml`), NIK PDFs + extracted text (`nik/`) and the KPOŚK 2024 xlsx (`dl_kposk/`) are in the same directory. They are scratch files and can be deleted.

---

## 0. TL;DR

**BZP is the backbone.** Per `01_bzp_api.md`, BZP already gives 22/22 procedures, contractors, values, change notices and performance notices. The sources below should be chosen to (a) satisfy the brief's "additional sources" test, (b) add risk evidence that BZP does not have (appeals, audit findings, grant-level data), (c) build a comparator corpus for "analyse a new investment", and (d) power the optional monitoring module.

**Recommended integration order for a 24–36 h hackathon.** Effort: S ≤ 3 h, M ≈ 3–8 h, L > 8 h.

| # | Source | Why | Effort | Hits on our 22 projects (tested) |
|---|---|---|---|---|
| 0 | **Biała lista VAT API** (+ BIP-register TERYT dictionary) | Mandatory plumbing: NIP → official name, REGON, KRS, address; REGON is needed for TED matching. | S | **19/20 buyer NIPs resolve** in one batch request. Zagrodno shows `statusVat: Niezarejestrowany` (removed 2023) but is still returned. **WZDW Poznań (9720914891) is not in the VAT register**: it is a voivodeship budgetary unit under VAT centralisation, so use BIR/REGON for it. |
| 1 | **TED API v3** | Named source with a clean, keyless JSON API. Buyer-NIP search works. **≈1 070 Polish wod-kan contract-modification notices** (eForms `can-modif`, since 11/2023) come with free-text reasons and legal-basis codes: a ready-made risk-event corpus. | S | **0/22** dataset procurements are on TED; all are below the EU threshold. That is a correct, documentable "not found". The check covered plain NIP and REGON / "NIP …" / hyphenated variants; the variants add 0–12 extra notices per buyer, none of them wod-kan. The same gminas have other TED notices; Kleszczewo and Nowogard have other wod-kan procedures. |
| 2 | **Mapa Dotacji (KPO B3.1.1 list)** | Project-level grant data: title, beneficiary, total value, EU co-financing, description. **631 B3.1.1 projects** for the comparator set. Exact-value match to the dataset's "Adnotacja instytucji". | S–M (HTML scrape, 64 list pages + detail pages) | 2/2 tested KPO projects (Zagrodno, Kamionka) matched exactly on value and co-financing. 10 dataset rows carry a KPO B3.1.1 annotation: 7 with a KPO number, plus Biecz, Zakrzew and Bobrowniki with BZP numbers. Expect most of them to match. |
| 3 | **KIO rulings (orzeczenia.uzp.gov.pl)** | Named source and the only one with documented **appeals (R11)**. Detail pages carry structured `Zamawiający`, `Miejscowość`, outcome, articles and full PDF text. | S–M | Exact-phrase search on buyer name gives 0–119 hits per buyer, with heavy noise. Wod-kan-relevant candidates: Biecz (KIO 2722/25, WWTP PFU), Kamionka, Zakrzew, Kleszczewo, Zduny. Every hit must be verified against the Details `Zamawiający` field. |
| 4a | **CRU JSFP (Centralny Rejestr Umów), new since 1 July 2026** | Keyless public JSON search over all public-sector contracts **with annex history** (`Aneks`, `Rozwiązanie`, `Wypowiedzenie`, `Odstąpienie`). Ideal for the bonus **monitoring module**. | S | Covers only contracts signed on or after 2026-07-01, so it will mostly miss our completed projects. It works: Nowogard has 6 sewer-related contracts, and an annex "WYDŁUŻENIE TERMINU" was found for a sewer contract in Krzemieniewo. |
| 4b | **NIK audit results** | Named source. Seeds the risk catalogue with authoritative causes and effects (§8). A keyless JSON search exists and PDFs have a text layer. | M (PDF chunking + LLM extraction) | NIK audits single gminas only rarely. None of our 20 buyers was found. Use NIK as **sector knowledge**, not as per-project evidence. |

**Cheap add-ons if time allows:** **KPOŚK annual report xlsx** (S; CC BY 4.0; per-agglomeration planned/ongoing investments with completion dates, which allows year-over-year slippage detection). **GUS BDL API** (S; gmina-level km of sewer/water network per year, to cross-check "investment completed"). **BK2021** (M; works via an undocumented JSON API, but few hits for our gminas because KPO projects run under Pzp).

**Do not build in the hackathon:** generic BIP crawling (L, heterogeneous; do only targeted lookups, §9), OpenTender OCDS (2006–08/2022, CC BY-NC-SA, no amendments), GUS BIR production (needs a key by e-mail, though the test env works with a public key), the FE 2021-27 project-list xlsx (41 MB; KPO coverage not verified).

---

## 1. Comparison table

| Source | Access | Auth / key | Rate limits (observed / documented) | Format | Key fields | Link keys to our projects | Licence / reuse | Reliability | Effort |
|---|---|---|---|---|---|---|---|---|---|
| **TED API v3** `POST api.ted.europa.eu/v3/notices/search` | REST JSON (expert query) + per-notice XML/PDF/HTML | none | Not documented. ~45 requests, no throttling. ≤250 notices/page, ≤10 000 fields/page, 15 000 results in page mode, unlimited in `ITERATION` mode | JSON; eForms XML (UBL) | notice-type, buyer ids, CPV, values, winners, `modification-*`, `procedure-identifier`, `internal-identifier-proc`, `document-url-lot` (contains e-Zamówienia **OCID**) | buyer NIP/REGON (`organisation-identifier-buyer`, free-text formats!), OCID from `document-url-lot`, znak sprawy, FT search for KPO numbers | EU reuse (Decision 2011/833/EU), attribution | High; official, stable | **S** |
| **Mapa Dotacji** `mapadotacji.gov.pl/projekty/` | HTML (WordPress), GET params | none (CSV export protected by reCAPTCHA, so **do not use**) | none observed | HTML | title, beneficiary, total value, EU co-financing, voivodeship/powiat, programme, action, description | beneficiary name + exact value + title. **No KPO number on the page.** | public information; attribution | Medium-high (official MFiPR portal; layout may change) | **S–M** |
| **KIO** `orzeczenia.uzp.gov.pl` | HTML form → `POST /Home/GetResults` (HTML fragment); `/Home/Details/{id}`; `/Home/PdfContent/{id}?Kind=KIO` | none | none observed | HTML + PDF (text layer) | sygnatura, date, Zamawiający, Miejscowość, outcome (oddalone/uwzględnione/…), tryb, Pzp articles, thematic index, full text | buyer name (exact phrase), place, BZP no. / title in text (fuzzy); verify via Details | public information; natural persons are pseudonymised in rulings | Medium: search mixes lexical and semantic hits (noise) | **S–M** |
| **CRU JSFP** `rejestrumow.gov.pl/api-dp/v1/…` | JSON (internal API of the public SPA) | none for reading; X-API-KEY only for publishing JSFP | none documented for reads. Imperva/Incapsula WAF in front, so be gentle (≤1 req/s). Maintenance windows announced weekly | JSON | contract no., date, end date, period, subject, value, parties (NIP/REGON from REGON register), **`zmianyUmowy[]` (rodzaj, data, komentarz)** | NIP/REGON of JSFP and of contractor, subject text, value | public information (art. 34a u.f.p.) | Medium (new system, undocumented read API; official) | **S** |
| **NIK** `nik.gov.pl/kontrole/wyniki-kontroli-nik/` | JSON search (`fmax,,strona,N.html`, POST) + static HTML pages + PDFs | none | none observed | JSON with embedded XML list; HTML; PDF (text layer) | kontrola id, number (P/S/I/K/…), title, unit, date; per-entity "wystąpienie" PDFs | audited-entity name (rarely our gminas); topic | public information | High (content), Low (per-project coverage) | **M** |
| **BK2021** `bazakonkurencyjnosci.funduszeeuropejskie.gov.pl/api/…` | JSON (internal API of the SPA) | none for public reads | none observed | JSON | announcement, advertiser NIP, CPV, places, **project `full_number`** (e.g. FEDS.02.01-IZ.00-0015/25), attachments, `/settlement` (chosen offer comment, offer ids) | advertiser NIP, project number, place | public information; **contact persons = personal data (do not store)** | Medium (undocumented API) | **M** |
| **KPOŚK reports** (dane.gov.pl dataset 3213) | bulk xlsx (2020–2024), 3 MB/year | none | n/a | XLSX (187 columns per agglomeration) | agglomeration id (PLxx…), gminas, RLM, km built/modernised in year, spending by source, **ongoing & planned investments with cost and completion date** | gmina name + województwo/powiat (→ TERYT) | **CC BY 4.0** | High (official annual reporting) | **S** |
| **Biała lista VAT** `wl-api.mf.gov.pl` | REST JSON | none | **100 search requests/day, ≤30 NIPs each** (KAS); `check` endpoint has higher limits | JSON | name, NIP, REGON, KRS, statusVat, addresses, accounts | NIP | public register | High | **S** |
| **GUS BIR1.1** (REGON) | SOAP (WS-Addressing, session `sid`) | **key required for production** (free, e-mail to GUS). The test env accepts public key `abcde12345abcde12345` | not published | XML in SOAP | REGON, NIP, name, **TERYT woj/pow/gmina/miejsc. symbols**, legal form, **website URL**, e-mail | NIP/REGON | public register | High; test env has anonymised streets | **S** (test) / **S+wait** (prod) |
| **Central BIP register** `aplikacje.gov.pl/app/bip-back/api/…` | JSON (internal API of gov.pl/web/bip) | none | none observed | JSON | subject name, **BIP URL**, ancestry; TERYT dictionaries (woj→pow→gmina, 7-digit codes) | name substring, TERYT | public information | **Low** for BIP URLs (missing/null/mis-coded entries). TERYT dictionary is fine | **S** |
| **GUS BDL API** `bdl.stat.gov.pl/api/v1` | REST JSON | optional key | anonymous: header shows 10 000 req / 7 days | JSON | gmina-year indicators (e.g. var 494 km of active sewer network, 9153 population connected) | TERYT-based BDL unit id (12 digits) | GUS open data, attribution | High (1-year lag) | **S** |
| **OpenTender PL (OCDS)** via data.open-contracting.org/publication/73 | bulk jsonl.gz / csv / xlsx per year | none | n/a | OCDS 1.1 (OCID prefix `ocds-70d2nz`) | tenders, awards, bids; **no contracts/amendments** | buyer name/id | **CC BY-NC-SA 4.0** | covers 2006–08/2022 only | skip |
| **NFOŚiGW wod-kan grants** (dane.gov.pl dataset 2037) | bulk xlsx per year | none | n/a | XLSX (≈400 KB) | contract no., beneficiary, project, NFOŚ grant, total cost | beneficiary name | **CC0** | High; mostly utilities/agglomerations | S (optional) |

---

## 2. Cross-source linking keys and normalisation

| Key | Where it appears | Pitfalls found today |
|---|---|---|
| **NIP** (10 digits) | Biała lista, CRU, BK2021 (`advertiserIdentificationNumber`), TED `organisation-identifier-buyer`, KIO text (rarely) | TED stores it as **free text**: `8590012007`, `NIP 1132316427`, `113-23-16-427`, `NIP 8130008613 NIP 8133734188` (two NIPs in one value), or **only a REGON** (`170747715` = Gmina-Miasto Elbląg). Exact-match only: no wildcard prefix, no phrase search on this field. → Query several variants (`{nip}`, `NIP {nip}`, `{3-3-2-2}`, `{3-2-2-3}`, `{regon}`) and add a `buyer-name~"…"` fallback with post-filtering. |
| **REGON** (9/14 digits) | Biała lista, BIR, CRU, TED (sometimes) | Get it from Biała lista first, then reuse it in TED/CRU queries. |
| **TERYT** (woj 2 / pow 4 / gmina 7 digits incl. type) | BIR full report (`praw_adSiedz*_Symbol`), BIP-register dictionary (`/api/dictionaries/voivodeships/{w}/districts/{p}/communes` → e.g. `3204043 Nowogard`), KPOŚK (names only), BDL unit ids | Name-only matching is unsafe. Examples: **Gmina Elbląg (rural, NIP 5783105254) ≠ Gmina-Miasto Elbląg**; **Gmina Sanok (rural) ≠ Urząd Miasta Sanoka**; **Kamionka (lubelskie) ≠ Kamionka Wielka (małopolskie)**; **Bobrowniki** exists in śląskie and kujawsko-pomorskie. |
| **KPO project number** `KPOD.03.15-IW.{nn}-{nnnn}/{yy}` | dataset, TED full text (`FT~"KPOD.03.15"`: 13 notices), BZP notice bodies (per 01), BK2021 `full_number` (for other programmes) | **Decoded and validated on the 7 dataset rows with a KPO number plus 2 call numbers:** `03.15` = KPO component/investment slot for B3.1.1; `IW.nn` = implementing institution = marshal office, with **nn = 12 + (voivodeship TERYT / 2)** (IW.13 dolnośląskie (02), IW.14 kuj-pom (04), IW.15 lubelskie (06), IW.16 lubuskie (08), IW.21 podkarpackie (18), IW.22 podlaskie (20), IW.27 wielkopolskie (30), IW.28 zachodniopomorskie (32)); `/yy` = year of the call. → A cheap consistency check against the beneficiary's TERYT. Mapa Dotacji does **not** show the number, so match there on beneficiary + value. |
| **OCID** `ocds-148610-<uuid>` (e-Zamówienia) | BZP (`tenderId`), **TED `document-url-lot`** for notices sent via e-Zamówienia | TED `procedure-identifier` equals the OCID uuid only sometimes (2 of 5 checked). Always parse the OCID out of `document-url-lot`. Buyers using other platforms (e.g. `platformazakupowa.pl`, Kleszczewo/Nowogard) have **no OCID**. Use `internal-identifier-proc` (znak sprawy, e.g. `ZP.271.13.2025`) + NIP + title instead. |
| **Znak sprawy** (`ZP.271.x.yyyy`) | TED `internal-identifier-proc`, BZP body, KIO text, BIP | Re-used across a cancelled and repeated procedure. Kleszczewo `ZP.271.6.2025` appears with **two different TED procedure UUIDs**, which suggests an unieważnienie + repeat (an R11 signal). |
| **Exact amounts** | dataset annotation, Mapa Dotacji, CRU, BZP | Exact match on grosze (e.g. `5 350 782,65`) is a high-confidence link. Mind netto/brutto (BZP: estimated value netto; contract value brutto). |

Suggested match-confidence scheme: **1.0** identifier equality (NIP+OCID / NIP+KPO no. / exact value+beneficiary NIP); **0.8** NIP + znak sprawy or NIP + title similarity ≥ 0.85; **0.6** buyer name + place + CPV + date window; **< 0.5** semantic only (KIO semantic hits, BIP search). Show the basis in the UI. The jury tests this ("Test łączenia", "Test pracy eksperta").

---

## 3. TED (Tenders Electronic Daily): API v3

**Endpoint.** `POST https://api.ted.europa.eu/v3/notices/search`. No key. Body: `query` (expert syntax), `fields` (required, from 1 830 supported names; an invalid name returns the full list in the error), `limit` (≤250), `page` or `paginationMode: "ITERATION"` + `iterationNextToken`, `scope` (`ALL`|`ACTIVE`|`LATEST`), `onlyLatestVersions`, `checkQuerySyntax`. Per-notice documents: `https://ted.europa.eu/en/notice/{pub-no}/xml` (eForms UBL), `/pdf`, HTML. Spec: `https://api.ted.europa.eu/api-v3.yaml` (saved as `ted_api_v3.yaml`).

**Query syntax (tested).**
* `organisation-identifier-buyer=8590012007`: exact match only. `~` (phrase) and leading wildcards are rejected.
* `buyer-name~"Gmina Nowogard"` (phrase), `FT~"KPOD.03.15"` (full text).
* `classification-cpv IN (45231300 45232400 …)`, `buyer-country=POL`, `notice-type=can-modif`, `publication-date>=20250101`.

**Useful fields.**
* Identity: `publication-number`, `notice-type` (`cn-standard`, `can-standard`, `can-modif`, `corr`, `pin-*`, `veat`), `procedure-identifier`, `internal-identifier-proc`, `contract-identifier`.
* Values and winners: `result-value-notice`, `tender-value-lowest/highest`, `received-submissions-type-val` (number of offers), `winner-name`, `winner-identifier`, `contract-conclusion-date`, `contract-duration-*`.
* Change and modification: `change-reason-code`/`description`, `modification-description`, `modification-reason-description`, `modification-justification`, `modification-previous-notice-identifier`.
* Funding: `eu-funds-name`/`identifier`.
* Links: `document-url-lot`, `buyer-profile`.

**eForms XML paths for modifications** (from notice 300185-2025, Gmina Wierzbica sewer relining):
* `efac:ContractModification/efbc:ChangedNoticeIdentifier` (previous notice) and `efbc:ModifiedContractIdentifier` (`CON-0001`).
* `efac:Change/efbc:ChangeDescription`.
* `efac:ChangeReason/cbc:ReasonCode` (list `modification-justification`: **`add-wss`** = additional works/supplies/services ≈ art. 455 ust. 1 pkt 3; **`mod-cir`** = unforeseeable circumstances ≈ pkt 4), with `efbc:ReasonDescription`.
* Contract value: `efac:LotTender/cac:LegalMonetaryTotal/cbc:PayableAmount`.
* Contract date: `efac:SettledContract` + `cbc:IssueDate`/`cbc:AwardDate`.
* Parties: `cac:PartyLegalEntity/cbc:CompanyID` (NIPs of the buyer and contractors).

**Test results.**
* **All 20 buyer NIPs** were queried. They returned 3–54 notices each, mostly waste collection, energy, IT and vehicles. A second pass with REGON, `NIP {nip}`, `NIP: {nip}` and both hyphenated forms found 0–12 additional notices per buyer (e.g. Gmina Elbląg +12, Grodzisko Dolne +9), **none with wod-kan CPVs**. **None of the results is one of the 22 dataset procurements**, as expected for below-threshold BZP procedures.
* Wod-kan TED activity of the same buyers:
  * **Kleszczewo**: 2024–2025 sewer works and supervision. Includes CAN 641807-2025, 12.24 mln PLN, 5 offers, consortium WUPRINŻ + Kubiaczyk. `ZP.271.6.2025` appears under two procedure UUIDs.
  * **Nowogard**: CN 644337-2026, 722831-2026 and 757336-2026, "Przebudowa i rozbudowa istniejącej oczyszczalni ścieków w Nowogardzie" (3 CN versions within 2 months, worth checking for changes).
  * Czernikowo: KPO B3.1.1-related monitoring system, 194457-2025.
* **Risk corpus:** Polish `can-modif` notices with wod-kan CPVs: **1 072 since 2023-11-01**, **597 since 2025-01-01**; 44 of them are from buyers named "Gmina…" since 2025. Free text such as "roboty zamienne… protokół konieczności… art. 455 ust 1 pkt 4" is directly usable for event extraction. The CPV filter also catches rail and road contracts with sewer sub-CPVs, so post-filter on the main CPV.

**Pitfalls.** Buyer identifier formats vary (§2). Older (pre-eForms, before 25 Oct 2023) notices lack most `modification-*` fields in search results, so parse the XML. Titles are multilingual objects (`notice-title.pol`). Results include all language links (bulky); request only the fields you need.

---

## 4. KPO project lists (B3.1.1) and EU project lists

**Where `KPOD.03.15-IW.xx-xxxx/yy` projects are published.**
1. **Mapa Dotacji UE** (`mapadotacji.gov.pl`, MFiPR) includes KPO.
   * Filter: `search-program=29425` (KPO) and `search-number-name-activity=30818` ("3.15. B3.1.1. Inwestycje w infrastrukturę kanalizacyjną i wodociągową"). The older action id `29620` (same B3.1.1 name, "na terenach wiejskich") returns 0 results.
   * **631 projects**, 10 per page, `page_no=1..64`.
   * The list card shows title, beneficiary, total value, EU co-financing and voivodeship. The detail page (`/projekty/{id}/`) adds powiat, programme, action, fund and a long description (subject, location, plots, goals).
   * Tested: Zagrodno → `/projekty/1801476/` (5 350 782,65 / 4 333 677,17 zł; description identical to the dataset); Kamionka → `/projekty/1807940/` (3 096 863,90 / 2 517 775,52 zł).
   * **The project number is not shown.** Link on beneficiary + exact value.
   * The CSV export link (`/eksport/eksportDoPlikuCsv/…`) returns 404 without a reCAPTCHA token. **Do not try to bypass it.** Scrape the HTML at ≤1 req/s instead: ≈700 requests in total, ≈15 min.
   * Search params: `search-s` (free text), `search-beneficiary`, `search-title-of-project`, `search-voivodeship`, `search-county`, `search-program`, `search-fund`, `search-years`, `search-number-name-activity`.
2. **Marshal offices (IW)** publish call results and ranking lists for B3.1.1 as PDFs (e.g. lubuskie call `KPOD.03.15-IW.16-001/24`, podlaskie `KPOD.03.15-IW.22-001/24`). Not machine-friendly; useful only as a citation.
3. **CST2021** itself is not public. The ministry says it will be added later (expert material §3).
4. **FE 2021-2027 project list** ("Lista projektów realizowanych z Funduszy Europejskich w Polsce w latach 2021-2027", status 01.11.2026): `https://funduszeeuropejskie.gov.pl/wp-content/uploads/2026/11/Lista_projektow_FE_2021_2027_01112026.xlsx`, **41.2 MB (not downloaded; over the 20 MB guideline)**. It contains project number, beneficiary, NIP, values and dates for cohesion programmes (FEnIKS, FEW, FEDS…). **Whether it includes KPO is unverified.** The 2014-2020 list is on gov.pl (≈59 MB xlsx, monthly). Use these only if a non-KPO project row appears (none in our dataset, apart from 2 PROW rows).
5. **PROW 2014-2020 rows** (Gościeradów, Bestwina): the ARiMR beneficiary list (`beneficjenci.arimr.gov.pl`) was **unreachable** today. Mapa Dotacji has no EFRROW fund filter, so these two rows rely on BZP plus the BIP.

**Comparator value.** The 631 B3.1.1 records (value, subsidy, description with km of network, pumping stations, connections) are the natural "similar past cases" set for the new-investment analysis. They are planned values, though; actual outcomes come from BZP performance notices.

---

## 5. Baza Konkurencyjności 2021 (BK2021)

No official public API is documented. The SPA uses a JSON API that works without login (tested):
* Search: `GET /api/announcements/search?page=1&limit=20&sort=default&query=…&advertiserIdentificationNumber={NIP}&full_number={project no.}&status[0]=PUBLISHED&status[1]=RESOLVED&status[2]=CANCELLED&status[3]=CLOSED`. Arrays are encoded as `status[0]=…` and the header is `Content-type: application/json`. Without `status[…]` the API returns HTTP 500.
* Detail: `GET /api/announcements/{id}`. It returns orders → items → CPV, places (to locality), participation conditions, criteria, attachments (`/api/files/{id}`), version ids, **projects[] with `full_number`**, `planned_sign_date`, `terms_of_contract_change`.
* Award: `GET /api/announcements/{id}/settlement`. Returns `comment` (e.g. "Dokonano wyboru oferty WMB Project Sp. z o.o. na kwotę 47 970,00 zł brutto…") and the offer ids, so you get the **offer count**.
* Status values: `PUBLISHED, RESOLVED, CANCELLED, CLOSED, LOCKED, DRAFT`.

**Tests.**
* Kleszczewo: 12 announcements, none wod-kan.
* Nowogard: 11, mostly eco-education.
* **Zagrodno: 1**, "Pełnienie funkcji inspektora nadzoru inwestorskiego" (2026-04, RESOLVED, 4 offers, places Zagrodno + **Modlikowice**). It is linked to project FEDS.02.01-IZ.00-0015/25 (energy efficiency), **not** to the KPO sewer project.
* Czernikowo: 0.
* `full_number=KPOD.03.15-IW.13-0004/25`: 0.

**Assessment.** KPO B3.1.1 gminas procure under Pzp (BZP), so BK2021 coverage of our projects is near zero. BK2021 matters for sub-threshold side orders (supervision, design) of FE-funded projects. Treat it as optional. **Contact persons (name, phone, e-mail) are personal data. Drop those fields at ingest.**

---

## 6. CRU JSFP: Centralny Rejestr Umów (new, highly relevant for monitoring)

Live since **1 July 2026** (art. 34a–34b u.f.p.). Every public-finance-sector unit (gminas included) must publish contracts concluded from 2026-07-01 together with updates.
* Public portal: `https://rejestrumow.gov.pl`. Publisher API docs: `https://jsfp.rejestrumow.gov.pl/api-gw/docs/int/api.html`. The OpenAPI spec covers only `/v1/api/publish/*` and needs an X-API-KEY issued to JSFP users.
* **Read access (tested, no key):** the public SPA calls:
  * `POST https://rejestrumow.gov.pl/api-dp/v1/agreements/search?offset=0&limit=20` with body sections `menuGlowne` (nip, regon, nazwa, przedmiotUmowy, wartoscOd/Do, dataZawarciaOd/Do, statusUmowy…), `jsfp` (buyer address incl. woj/powiat/gmina), `daneUmowy`, `zmianyUmowy` (`rodzajZmiany`, `dataZmianyOd/Do`, `komentarz`), `inneStronyUmowy` (contractor NIP/REGON/name), `inne`. Response: `content[]` (idUmowy, nazwa, regon, dates, value, subject, status) + `totalElements`.
  * `GET https://rejestrumow.gov.pl/api-dp/v1/agreement/{idUmowy}` returns parties with NIP/REGON/address (from REGON), period, value, `opisWartosciPrzedmiotu`, `finansowanaZeSrodkow`, **`zmianyUmowy[]`**, `dataPublikacji`, `dataModyfikacji`.
  * Change types (`rodzajZmiany`): TSU01 korekta danych, **TSU02 aneks**, TSU03 jawność, TSU04 zmiana danych strony, **TSU05 rozwiązanie, TSU06 wypowiedzenie, TSU07 odstąpienie**.
* **Tests.** Nowogard NIP + "kanaliz": 6 contracts (design of a storm connection, sewer inspections), with contractor NIPs. A national search for "budowa kanalizacji sanitarnej" ≥ 500 000 zł with an annex found Gmina Krzemieniewo (540 345,70 zł, 53 days) with "ANEKS NR 1 DO UMOWY – WYDŁUŻENIE TERMINU" dated 06.11.2026, which is exactly a monitoring-module event.
* **Side finding:** Nowogard's BIP "Rejestr umów" (`bip.nowogard.pl/umowy`, DataTables endpoint `umowy/ajax`) now mirrors CRU (`prefix_url: "cru"`, 136 records since July 2026). BIP contract registers are converging on CRU.
* **Limits.** Contracts before 2026-07-01 are not included, so the completed dataset projects are mostly absent. The read API is undocumented and sits behind the Incapsula WAF, with weekend maintenance announced weekly on gov.pl. Keep it as the **live-monitoring** source: poll by buyer NIP, diff `zmianyUmowy`, raise "new annex / termination" events.

---

## 7. KPOŚK / AKPOŚK (urban wastewater programme)

* **Annual implementation reports (per agglomeration):** dane.gov.pl dataset **3213** "Sprawozdanie Krajowego Programu Oczyszczania Ścieków Komunalnych", **CC BY 4.0**, xlsx for 2020–2024. 2024: `https://api.dane.gov.pl/resources/1491599,sprawozdanie-kposk-za-2024-rok/file` (3.2 MB; 2023: resource 67894; 2022: 63049). API: `https://api.dane.gov.pl/1.4/datasets/3213/resources`.
* Sheet `Aglomeracje 2024 r.` (1 536 rows × 187 columns):
  * Identity: agglomeration id (e.g. `PLZA019` Nowogard), status, woj/powiat/RZGW, lead gmina + all gminas, the council resolution designating the agglomeration, RLM, connected population.
  * Network: **km of network built and modernised in the year**.
  * Money: spending by funding source.
  * **Ongoing and planned investments ("w trakcie realizacji" / "planowane"): name, km, cost in tys. zł, completion date, "czy ujęta w VI AKPOŚK?"**
  * Compliance with directive 91/271.
  * Sheet `Oczyszczalnie 2024 r.` (1 656 rows) has WWTP data including **"data odbioru technicznego zrealizowanej inwestycji"**.
* **Use.**
  1. Context features for a gmina/agglomeration (size, connection rate, tariff).
  2. **Schedule-slip signal:** compare the planned completion date and cost of the same investment across the 2022 → 2023 → 2024 reports.
  3. Evidence that a WWTP investment was technically accepted in year X.
* **Caveat:** KPO B3.1.1 projects are by definition **outside agglomerations** (see the Grodzisko description: "poza aglomeracją"). KPOŚK is relevant mainly for the agglomeration projects: Nowogard (700-lecia), Kartuzy, Wolin, Miłakowo, Elbląg/Janów, Czernikowo/Steklin WWTP.
* The AKPOŚK itself (VI 2022/23; VII in preparation per Wody Polskie RZGW pages, 2025–26) is a programme document (PDF plus annex tables). The reports above are the machine-readable part. A GIS layer of agglomeration boundaries exists on Wody Polskie portals **(unverified, not needed)**.

---

## 8. NIK (Supreme Audit Office)

**Access (tested).**
* Search: `POST https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/fmax,,strona,{N}.html` with form fields `numer`, `temat`, `jednjednostka` (audited-entity text), `jednostka` (NIK unit id), `rodzaj` (Informacja / Wystąpienie), `dataodx`, `datadox`, `zakres=dowolny`, `dzialy`. Returns JSON `{ilosc, xml}`, where `xml` lists `<kontrola>` entries (id, slug, title, number, date).
* `temat=ściek` → 43 audits; `temat=kanalizac` → 20.
* Pages: `/kontrole/wyniki-kontroli-nik/kontrole,{id}.html` → 302 to `/kontrole/{P|S|I}/{yy}/{nnn}/{UNIT}/`. Static HTML lists the audited entities and links to PDFs (`…pobierz,{unit}~{slug}~id{n}~01,typ,kj.pdf` for a wystąpienie, `…typ,kk.pdf` for the Informacja).
* All PDFs read today have a text layer. Use `pdftotext` **without** `-layout` for two-column Informacje.
* No API key, no published licence beyond public-information reuse. No dane.gov.pl dataset for audit results.

**Per-project coverage is low.** NIK audits a few dozen entities per topic, and none of our 20 buyers appeared. Use NIK as **sector knowledge**: seed the risk catalogue (cause → event → effect → recommendation) and attach as "similar documented cases".

**Audits read today (seed for the risk catalogue).** All figures were checked in the PDFs by the sub-agent. Selected figures were re-checked by grep in the extracted text.

| Audit | Year | URL | Key findings → risk type |
|---|---|---|---|
| **P/11/148** "Realizacja przez małe gminy zadań inwestycyjnych w zakresie infrastruktury wodno-ściekowej" (33 gminas + 2 companies, 2007–2011) | 2012 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,9005.html, PDF https://www.nik.gov.pl/plik/id,3662,vp,4667.pdf | **R11/R13:** Gmina Darłowo awarded the Rusko WWTP (12.19 mln zł brutto) to the only bidder at **≈4.58 mln zł above the kosztorys inwestorski**, without budget cover (contract 30.05.2008); NIK says the tender should have been cancelled. **R07/R05:** Długołęka (Mirków WWTP): 6 contracts for additional/substitute works worth 1.04 mln zł, overstated by ≈0.26 mln zł; the inspector-coordinator was also the plant designer with a contract with the builder (conflict of interest). **R06:** Nowe Miasto Lubawskie charged no penalties (183 tys. zł) for design documents 106–821 days late. **R13:** Braniewo let building permits expire for lack of funds, and redesign cost 134.6 tys. zł. |
| **P/20/046** "Zbieranie i oczyszczanie ścieków komunalnych" | 2021/22 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,22264.html (regional sub-pages `/kontrole/P/20/046/LWR/`, `/LKR/`) | **R06:** Wrocław city: 3 of 33 sewer investments finished **148, 148 and 1 461 days late** (attributed to COVID-19). Agglomeration Psary–Wrocław: **620 days late**, part of the site was unavailable inside flood-embankment works (**R03/R04**). Miękinia stage II: **1 095 days late** (no funding, local plan needed, **R13/R04**). Nowy Targ (MZWiK): **14 of 50** investments late, due to landowner refusals (**R03**), slow power connections (**R04**), contractor quality problems (**R12**) and weather. National level: 162 of 184 AKPOŚK investments (88 %) on time or harmlessly late; delays mainly from missing own funds or grants, long tenders, land acquisition and contractor fault. |
| **S/22/002/LKI** "Rozbudowa i przebudowa oczyszczalni ścieków oraz sieci wodno-kanalizacyjnej na terenie Aglomeracji Bogoria" | 2022 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,22650.html | Positive overall, finished on time, but **cost growth from 3 132 810 to 3 826 886,33 zł (+22 %)** via a grant-agreement annex (4 grant annexes, 7 application updates) (**R13/R01**). Pump-station tanks found sound once uncovered, so **substitute works** (65 tys. zł netto) replaced their replacement at no extra cost (**R02/R07**). Persistent odour defect after acceptance (**R10/R15**). |
| **S/23/003/LSZ** "Realizacja zadań w zakresie gospodarki ściekowej na terenie Gminy Miasto Stargard" | 2024 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,24611.html | **R13:** a >60 mln zł overflow-retention scheme was rejected in the 2021 Polski Ład call and funded only on resubmission in 2023; now moving to design-and-build. **R04/R15:** storm overflows discharged without water permits; 2023 limits exceeded at 2 overflows. |
| **I/19/001/KSI** kolektor "Czajka" (Warsaw) | 2022 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,22446.html | **R09/R12:** design changes during construction (different steel–GRP joint, foam concrete instead of the specified lightweight concrete, ballast slab on a dimple membrane) most likely caused the 2019 failure; contract engineer poorly supervised. **Cost:** repairs 56 386,9 tys. zł, plus an emergency pontoon pipeline at 35 mln zł netto. |
| **I/25/001/DLO** water/sewage obligations in rural gminas of łódzkie | 2026 | https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/kontrole,26070.html | Operational rather than investment-focused: Tuszyn had no long-term development/modernisation plan for the network (planning risk, R14); Zelów had 9 supply interruptions from pipe failures. |

Further candidates from the same search, not read: S/12/012/LBY (Gmina Brzuze wod-kan investments), S/14/005/LOL (Olsztynek), S/12/007/LKA (Mikołów EU-funded wod-kan), P/15/053 (gminas increasing sewer connections), P/21/066 (protection against sewage from non-sewered areas), P/24/084/LSZ (water losses, zachodniopomorskie). Local copies are in `…/scratchpad/sources/nik/` (`*.pdf` + `*.txt`).

Related (not researched in depth): **RIO** (Regionalne Izby Obrachunkowe) audit every gmina roughly every 4 years and publish "wystąpienia pokontrolne" on each RIO's BIP. These are more likely than NIK to mention a specific gmina's investment procurement, but each of the 16 RIO sites is different (effort L).

---

## 9. KIO (National Appeal Chamber) rulings

**Access (tested).** `https://orzeczenia.uzp.gov.pl`.
* Search (AJAX the page uses): `POST /Home/GetResults` with `Phrase` (exact phrase in quotes is supported), `Fle=1` (word forms), `SCnt=1` (search content), `Sign` (sygnatura), `Dt` (`DD-MM-YYYY - DD-MM-YYYY`), `Kind=KIO|SO|SA|SN`, `Pg`, `Srt`, plus filters `KIO.Purchaser`, `KIO.City`, `KIO.Outcome`, `KIO.DecT`, `KIO.Proc`, `KIO.CtrT`, `KIO.ThIdx`, `KIO.Art`, `KIO.Chairman`. The response is an HTML fragment: "Liczba znalezionych dokumentów: N" + items (organ, type, sygnatura, date, snippet, **lexical relevance and semantic relevance**, link `/Home/Details/{id}`).
* Details: `/Home/Details/{id}` has structured metadata (**Zamawiający, Miejscowość, sygnatura / sposób rozstrzygnięcia (e.g. "oddalone")**, tryb, rodzaj zamówienia, key Pzp articles, thematic index). Full text: `/Home/PdfContent/{id}?Kind=KIO` (PDF with text layer, ~70 KB). Autocomplete dictionaries: `/Dictionary/SearchPurchaser`, `/Dictionary/SearchCity`.
* No key and no documented limit. Natural persons are pseudonymised.

**Linking.** Query by exact buyer name, then **verify `Zamawiający` on the Details page**, then match the procurement by title, BZP number or date. Ruling text usually cites "ogłoszenie… opublikowane w Biuletynie Zamówień Publicznych nr 2024/BZP 00…/01" or the OJEU date, but a search for `"BZP 00349631"` returned 0. Do not rely on BZP-number search alone.

**Tests (exact phrase, page 1):**

| Buyer | Hits | Comment |
|---|---|---|
| Gmina Oława | 51 | |
| Gmina Zagrodno | 4 | |
| Gmina Czernikowo | 2 | |
| Zławieś Wielka | 0 | |
| Gościeradów | 1 | |
| Kamionka | 24 | mixed with Kamionka Wielka |
| Biecz | 11 | incl. **KIO 2722/25** (13-08-2025) on a Biecz WWTP procurement with PFU: an R11 candidate |
| Zakrzew | 14 | |
| Grodzisko Dolne | 8 | |
| Sanok | 36 | |
| Kartuzy | 28 | |
| Bestwina | 3 | |
| Bobrowniki | 16 | |
| Elbląg | 89 | mixed with the city |
| Miłakowo | 0 | |
| Kleszczewo | 7 | |
| Zduny | 12 | |
| WZDW Poznań | 119 | |
| Nowogard | 16 | incl. KIO 3904/26, services, not wod-kan |
| Wolin | 12 | |

Semantic matching adds noise: e.g. a ruling about Modliborzyce surfaced for Biecz with lexical relevance 0. **Filter out items with "Trafność wyszukiwania: 0"** and require the buyer match on the Details page. Nationally, "kanalizacji sanitarnej" returns 971 rulings, a good corpus for R11 patterns (experience conditions, abnormally low price, PFU ambiguities).

---

## 10. BIP (Biuletyn Informacji Publicznej) of gminas

**Discovering the BIP URL (tested).**
1. **Central BIP register.** The JSON behind `gov.pl/web/bip` works: `GET https://aplikacje.gov.pl/app/bip-back/api/subjects?archive=false&hasContactCard=true&name={substring}&terytCode={7-digit}` returns name, `url` (BIP address) and ancestry. **Data quality is poor:**
   * Zagrodno, Czernikowo, Miłakowo, Zakrzew, Kartuzy, Zduny, Zławieś and Grodzisko are missing.
   * Oława, Sanok, Bobrowniki and Wolin have `url: null`.
   * Some entries are mis-coded: Urząd Miejski w Nowogardzie is filed under Goleniów, so TERYT filtering misses it.
   * Name hits are often the wrong unit (city vs rural gmina).
   * Found correctly: Nowogard → `http://bip.nowogard.pl`, Kleszczewo → `http://bip.kleszczewo.pl/`, Gościeradów → `https://bip.goscieradow.pl/`, Bestwina, Biecz (`bip.malopolska.pl/umbiecz`).
   * The same API also gives a clean **TERYT dictionary** (`/api/dictionaries/voivodeships`, `…/{w}/districts`, `…/{w}/districts/{wp}/communes`).
2. **GUS BIR** full report → `praw_adresStronyinternetowej` (e.g. `www.nowogard.pl`). Probe `bip.{domain}`, `{domain}/bip`, `bip.{gmina}.pl`.
3. Common hosting patterns: `*.bip.gov.pl`, `bip.malopolska.pl/{code}`, `*.naszbip.pl`, `*.ibip.pl`, `bip.{gmina}.pl`, `bip.ug{gmina}.pl`, `*.biuletyn.net`, `bip.wrota.*`.
4. Fallback: a web-search API query such as `"Gmina X" BIP` (note it as low-confidence).

**What is typically there and useful for risk:**
* **WPF resolutions** ("uchwała w sprawie zmian WPF", załącznik nr 2 "wykaz przedsięwzięć" with period and limits). Successive versions reveal **cost increases and period extensions** of a named investment, a strong R06/R13 signal.
* Budget resolutions and changes.
* **Zarządzenia wójta**, e.g. appointing a tender committee for a named sewer project (Kleszczewo zarządzenie 9/2025, found in the sitemap).
* Contract registers (now moving to CRU).
* Zamówienia publiczne pages (often just links to the purchase platform).
* Audit protocols (RIO/NIK), raport o stanie gminy, "studium wykonalności".

**Pragmatic retrieval for the hackathon:**
1. Store a manually confirmed BIP base URL per gmina as config (22 rows), auto-suggested by steps 1–3 with a confidence score. The expert confirms it in the panel, which counts as human-in-the-loop.
2. Read `robots.txt` → `Sitemap:`. Kleszczewo exposes `https://bip-api.kleszczewo.pl/sitemap.xml` with 1 019 URLs. Nowogard and Gościeradów have no sitemap.
3. Filter sitemap or search results by project keywords (place names from the title such as "Tanibórz", "kanalizac", "WPF", "przedsięwzię") and fetch only those pages and attachments (PDF/DOCX, often scans → OCR).
4. Without a sitemap, use the BIP's own search page or a few menu sections ("Uchwały Rady", "Zarządzenia", "Budżet", "WPF", "Rejestr umów").

Effort is L for a generic crawler and M for "sitemap + keyword + 3 menu sections" on 2–3 demo gminas. BIP is **not** a central API. Each gmina runs one of roughly a dozen CMS vendors.

---

## 11. Entity verification registers

* **Biała lista VAT (MF).**
  * Endpoint: `GET https://wl-api.mf.gov.pl/api/search/nips/{nip1,…,nip30}?date=YYYY-MM-DD` (also `/nip/{nip}`, `/regon/{regon}`).
  * No key. **100 search requests/day per IP, ≤30 entities each** (KAS; older sources say 10/day). After the limit you are blocked until midnight.
  * Returns `name, nip, regon, krs, statusVat, residenceAddress/workingAddress, accountNumbers, registrationLegalDate, removalDate`.
  * Tested with all 20 buyer NIPs in one request: **19/20 found**, with REGONs. Examples: Gmina Elbląg REGON 170747738, which differs from Gmina-Miasto Elbląg's 170747715 seen in TED. **WZDW Poznań 9720914891 is not found**; it is a budgetary unit of the voivodeship under VAT centralisation, so fall back to BIR. Gmina Zagrodno is `Niezarejestrowany` (removed 2023-09-30, art. 96 ust. 7ba) but still found. Contractor NIPs from TED XML also resolved, with KRS numbers. **A missing VAT status does not mean an invalid NIP.** Validate the NIP checksum locally (weights 6,5,7,2,3,4,5,6,7).
* **GUS BIR1.1 (REGON).**
  * SOAP 1.2 with WS-Addressing. `Zaloguj(key)` → `sid` header → `DaneSzukajPodmioty(Nip|Regon|Krs)` → `DanePobierzPelnyRaport(regon, "BIR11OsPrawna")`.
  * **Production needs a free key requested by e-mail from GUS** (allow 1–3 working days, **unverified**).
  * The **test environment** `https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc` with the public test key `abcde12345abcde12345` **worked today**. It returns real NIP/REGON/name/powiat/gmina and TERYT symbols (Nowogard: woj 32, pow 04, gmina 044, simc 0979389), legal form and website, but **anonymised street names** ("ul. Test-Wilcza"). Good enough for TERYT and website discovery in a demo. State this in the docs.
* **TERYT.** Full TERC/SIMC files from eTERYT (`eteryt.stat.gov.pl` → "Pliki pełne", ASP.NET postback download, no key; TERC < 1 MB). API TERYT (SOAP) needs an account. **Easiest:** the BIP-register dictionaries (JSON, §10) or BDL units.
* **KRS API (MS).** `https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json`. No key. **It returned a "Przerwa techniczna" page today** (Saturday maintenance). Useful for contractor checks (KRS from Biała lista → status, liquidation/bankruptcy in dział 6 → R12 signal). The Krajowy Rejestr Zadłużonych (insolvency register, `krz.ms.gov.pl`) has public search but no confirmed API **(unverified)**.
* **OCDS.**
  * e-Zamówienia uses OCIDs `ocds-148610-<uuid>` (see 01). TED exposes them in `document-url-lot`.
  * The only Polish publication in the OCDS Data Registry is **OpenTender PL** (`https://data.open-contracting.org/en/publication/73`): 2006–Aug 2022, every 6 months, bulk `{year}.jsonl.gz|csv.tar.gz|xlsx`, OCID prefix `ocds-70d2nz`, **CC BY-NC-SA 4.0**. It has 2.39 M tenders and 3.06 M awards but **0 contracts and 0 amendments**.
  * `opentender.eu` returns 403 to scripts.
  * Not useful for 2023–2026 projects, but could give historical baselines (number of offers, price vs estimate) for wod-kan CPVs before 2022.

---

## 12. Other open datasets with completion dates or final values

* **GUS BDL API** (`https://bdl.stat.gov.pl/api/v1`, anonymous 10 000 req/7 days per response headers).
  * Gmina-level series: `494` length of active sewer network (km), `9153` population using the sewer network, plus water-network equivalents.
  * Find units with `/units/search?name=…&level=6` (Zagrodno = `030210126052`) and variables with `/variables/search?name=…`.
  * Tested: Zagrodno sewer network = 13.1 km every year 2020–2025, so the 2.38 km KPO extension is not yet reflected (data has a 1-year lag).
  * Use: corroborate "completed" status and physical scale. Add a gmina context feature: network km per capita.
* **KPOŚK reports** (§7): "data odbioru technicznego" for WWTP investments, km built per agglomeration-year.
* **NFOŚiGW** "Gospodarka wodno-ściekowa w aglomeracjach" contracts (dane.gov.pl dataset 2037, CC0, xlsx per year 2019–2025): contract no., beneficiary, project, NFOŚ grant, total cost. Mostly utilities; a small comparator add-on.
* **Rządowy Fundusz Polski Ład / RFIL** (KPRM/BGK): result lists per edition (gov.pl pages, xlsx/pdf **unverified**) with gmina, investment name and grant amount. Many gmina wod-kan projects, but planned values only.
* **Purchase platforms** (platformazakupowa.pl, ezamawiajacy, e-ProPublico…), linked from TED `buyer-profile`/`document-url-lot` and BZP. They host SWZ/PFU/PPU, Q&A, offer-opening information and the amount allocated: the richest **documents** for risk extraction. platformazakupowa.pl is behind Cloudflare; the page loads with a normal user agent but expect bot checks. **Never solve challenges automatically.** Download per-procedure attachments only, at low rate.

---

## 13. Suggested build plan (fits ~1 dev-day on top of BZP)

1. **Entity step (S):** NIP checksum → Biała lista batch (≤30 NIPs) → REGON, KRS, address → TERYT via the BIP-register dictionary (or the BIR test env). Cache it, because the daily limit is tight.
2. **TED connector (S):** per buyer: query the NIP/REGON variants plus a CPV-filtered `buyer-name~` fallback. Store notices with `procedure-identifier`, `internal-identifier-proc` and the OCID parsed from `document-url-lot`. Record "searched, 0 wod-kan matches" explicitly as a source-check record with timestamp, for the jury. Separately, pull the national `can-modif` wod-kan corpus with `ITERATION` (≈1 100 notices; fetch XML only for selected ones) into the risk-event extractor.
3. **KPO connector (S–M):** scrape the B3.1.1 list on Mapa Dotacji (64 pages + details). Link the dataset's KPO rows by beneficiary + exact value (confidence 1.0). Validate `IW.nn` against TERYT. Keep the 631 rows as comparators.
4. **KIO connector (S–M):** per buyer exact phrase → drop lexical-relevance-0 items → Details → keep where `Zamawiający` ≈ buyer and the title/date overlaps a known procurement. Store sygnatura, outcome and articles, plus the PDF text for LLM event extraction (R11).
5. **NIK seed (M):** pre-ingest the 6 audits in §8 (PDF text) as "sector evidence" documents. LLM extraction into catalogue entries (cause → event → effect → measure) with page citations. The expert approves them.
6. **Monitoring demo (S):** CRU poll by buyer NIP + "kanaliz|wodoci|oczyszcz" → new contract / new `zmianyUmowy` item → event "annex: extension" → expert queue.
7. Optional: KPOŚK xlsx (S), BDL (S), BIP targeted lookup for 2–3 gminas (M).

---

## 14. Open questions and caveats

* TED has no published rate limit. We saw no throttling at ~45 requests. Use `ITERATION` for bulk work and cache.
* The CRU, BK2021, KIO, NIK and BIP-register endpoints are **internal APIs of public web apps**: undocumented and subject to change. Wrap each behind an adapter and keep raw snapshots (with fetch timestamp and URL) for traceability.
* The Mapa Dotacji CSV export requires reCAPTCHA and is intentionally not used. HTML pages are public.
* Not downloaded: FE 2021-27 list (41.2 MB), 2014-20 list (≈59 MB). Whether the FE list includes KPO projects is unverified.
* ARiMR beneficiary search was unreachable and the KRS API was in maintenance during testing. Re-test before relying on them.
* Personal data: BK2021 contact persons, CRU natural-person parties (`SU02`), names in KIO and NIK documents. Minimise and avoid storing them (RODO), as the brief asks ("ograniczać przetwarzanie danych").

---

## Appendix A. Buyer NIP → REGON (Biała lista, 2026-11-21)

Use these REGONs as extra TED and CRU query keys. For TERYT, use the BIP-register dictionary or BIR.

| NIP | Name (VAT register) | REGON | statusVat |
|---|---|---|---|
| 9121715754 | GMINA OŁAWA | 931934868 | Czynny |
| 6941566139 | GMINA ZAGRODNO | 390647676 | Niezarejestrowany |
| 8792466869 | GMINA CZERNIKOWO | 910866761 | Czynny |
| 8792469951 | GMINA ZŁAWIEŚ WIELKA | 871118767 | Czynny |
| 7151863553 | GMINA GOŚCIERADÓW | 830409643 | Czynny |
| 7141896261 | GMINA KAMIONKA | 431019690 | Czynny |
| 7381973883 | GMINA BIECZ | 370440614 | Czynny |
| 7962959318 | GMINA ZAKRZEW | 670224077 | Czynny |
| 8161570014 | GMINA GRODZISKO DOLNE | 690581710 | Czynny |
| 6871783356 | GMINA SANOK | 370440749 | Czynny |
| 5890010583 | GMINA KARTUZY | 191674902 | Czynny |
| 6521708710 | GMINA BESTWINA | 276258144 | Czynny |
| 6252446477 | GMINA BOBROWNIKI | 276257877 | Czynny |
| 5783105254 | GMINA ELBLĄG | 170747738 | Czynny |
| 7412025674 | GMINA MIŁAKOWO | 510743692 | Czynny |
| 7773157115 | GMINA KLESZCZEWO | 631258715 | Czynny |
| 6211694095 | GMINA ZDUNY | 250855430 | Czynny |
| 9720914891 |, (not in VAT register) | - | - |
| 8590012007 | GMINA NOWOGARD | 811684278 | Czynny |
| 9860164852 | GMINA WOLIN | 811685510 | Czynny |
