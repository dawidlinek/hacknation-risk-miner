# scrape.md: data acquisition spec for Risk Miner

> For the session that builds the database and the importers/scrapers. Written 2026-11-21 ~13:15 from `docs/research/01–05`.
> Scope decision: **national**. Structured sources are scraped for the whole country. Documents are scraped for the 22 pilot projects plus a national sample. Read `docs/PLAN.md` §3, §4, §5 for the product context and the data model.

---

## 0. Ground rules (non-negotiable)

1. **Provenance first.** Every fetched byte lands in `data/raw/<source>/…` **unchanged**, with one line per fetch in `data/raw/<source>/manifest.jsonl`. Nothing is edited in place. Normalised tables are derived from raw and can be rebuilt. The jury's "test źródłowy" (source test) and "test integracji" (integration test) depend on this.
2. **Idempotent and re-runnable.** Each scraper takes `--since/--until/--limit/--only <ids>`, skips URLs whose manifest entry is fresh (same params, `http_status=200`, within TTL), and can resume after a crash. No manual steps.
3. **Polite.**
   - Rate: ≤1 req/s per host unless stated otherwise; prod e-Zamówienia API ≤25 req/min.
   - Exponential backoff on 429/5xx (tenacity); respect `robots.txt`.
   - **Approved exception (team decision, 2026-11-21 afternoon):** for `platformazakupowa.pl` and `logintrade.net` only, the document fetcher ignores `robots.txt`, throttled to 1 request per 5 s. Every such manifest line carries an approval note. CAPTCHA/WAF challenges are still never bypassed. List this exception in the technical documentation.
   - User-Agent: `RiskMiner-hackathon/0.1 (research prototype; HackNation 2026)`. **Do not put any personal name or e-mail in headers.**
4. **Never bypass protections.** No CAPTCHA solving, no WAF/Cloudflare challenge evasion, no login-only content. If a page is gated, record `blocked` in the manifest and move on. Example: the Mapa Dotacji CSV export is behind reCAPTCHA; use the HTML pages instead.
5. **Personal data minimisation (RODO).** Notices and portals contain contact persons, phones and e-mails. Keep raw as fetched (it is public), but **do not copy personal contact fields into normalised tables, the UI or exports**. This applies to: BK2021 contact persons, CRU natural-person parties (`SU02`), and names in KIO/NIK texts (KIO already pseudonymises natural persons).
6. **Licences.** Record `licence` per source in the manifest (see the table in §2). Skip OpenTender (CC BY-NC-SA).
7. **Big files stay out of git.** `data/` is gitignored, except tiny fixtures under `data/fixtures/`. Keep the raw tree also on WCSS PD for GPU batch jobs: `rsync -avh --partial data/raw/ wcss:$PDDIR/riskminer/raw/` via the `wcss` SSH alias. The `wcss-slurm` skill has the rules.

### Manifest line schema (`manifest.jsonl`)
```json
{"source":"bzp_api","fetched_at":"2026-11-21T13:20:05Z","method":"GET","url":"https://ezamowienia.gov.pl/mo-board/api/v1/notice","params":{"NoticeType":"ContractPerformingNotice","PublicationDateFrom":"2026-11-12","PageSize":"500"},
 "http_status":200,"content_type":"application/json","bytes":812345,"sha256":"…","path":"data/raw/bzp_api/2026-11-21/ContractPerformingNotice_2026-11-12_p1.json",
 "licence":"public information","run_id":"…","status":"ok|empty|blocked|error","note":""}
```
`run_id` ties to the `ingestion_run` table. The loader creates one `source` row per manifest line; that `source.id` is what every record cites.

### Directory layout
```
data/
  raw/<source>/<YYYY-MM-DD>/…      immutable responses (json/html/xml/pdf/docx/xlsx)
  raw/<source>/manifest.jsonl
  ref/                             reference data (TERYT, GeoJSON, price index, CPV)
  fixtures/                        tiny committed samples for tests
```

---

## 1. What we already have (no scraping needed, just load it)

| Asset | Where | Notes |
|---|---|---|
| Organizer dataset, 22 projects | `materials/starter/Risk_Miner_dane_projekty.xlsx` | Contains deliberate errors (see PLAN §2.3). Load via the importer, not by hand |
| **National BZP copy, 113,278 notices** (2021-01-13 → 2026-11-12) | `materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl` (2.7 GB) | 4 types: ContractNotice, TenderResultNotice, AgreementUpdateNotice, ContractPerformingNotice. Register it as source `bzp_copy` with the manifest sha256 `af0e37f5…8654`. **Do not re-download it from the API** |
| htmlBody field parser + normalisers | `research/bzp_corpus/bzp_parse.py` | Field codes, money, durations, Tak/Nie, art. 455 bases. Reuse it in production code |
| Relevance + subsector classifier | `research/bzp_corpus/wodkan_classify.py` | Only 42% of "completed" contracts are really water/sewage works |
| 22-project linking script + matrix | `research/bzp_linking/link_projects.py`, `matrix.md`, `chains.json` | 22/22 linked; reproduce in the pipeline (no manual import) |
| Gold change-reason labels (150) | `research/bzp_corpus/data/gold_change_reasons.csv` (gitignored, regenerate with the corpus scripts) | Few-shot + eval set |
| Official BZP API spec + enums | `docs/research/bzp_api_official/` | `/notice`, `/notice/stats`; enums for tenderType/clientType/provinces |
| Working curl for every other source | `research/sources/examples.sh` | `bash research/sources/examples.sh ted|ted_modif|wl|bir|bip|cru|bk|kio|nik|bdl|mapa|kposk` |
| NIK audit PDFs + text (6 audits) | `research/sources/nik/` | Seed for the risk catalogue |
| KPOŚK 2024 report xlsx | `research/sources/dl_kposk/` | CC BY 4.0 |
| TED API spec + field list | `research/sources/ted_api_v3.yaml`, `ted_fields.txt` | |
| CRU read API notes | `research/sources/cru_api.md`, `cru_openapi.json` | |

---

## 2. Scrape list, by priority

Effort: S ≤ 2 h, M 2–5 h, L > 5 h. "Demo" = needed for the two demo paths the jury runs live.

| P | Source id | What | Scope | Volume (est.) | Effort | Licence | Done when |
|---|---|---|---|---|---|---|---|
| **P0** | `bzp_api` | **Live delta** of the 4 types since 2026-11-12 + **`NoticeUpdateNotice`** (tender modifications, not in the copy) for water/sewage CPVs, from **production** `ezamowienia.gov.pl` (the mirror holds only the copy) | national | ~1–3k notices | S | public information | Re-runnable `--since`; the same client works against the mirror and prod by base URL; the 22 projects' chains re-fetched live (integration test) |
| **P0** | `vat_whitelist` | Biała lista: NIP → name, REGON, KRS, statusVat, address | 22 buyers + their contractors first, then national buyers and contractors in daily batches | ≤100 req/day × 30 NIPs | S | public register | 22 buyers + contractors resolved; WZDW Poznań falls back to `gus_bir`; national backlog queued under the daily cap |
| **P0** | `teryt` | Gmina/powiat/woj dictionary with codes (TERC) | national | ~2.5k gminas | S | public | `data/ref/teryt_terc.csv` |
| **P0** | `geo` | Boundaries GeoJSON: województwa, powiaty, gminy (simplified for the web) | national | ~5–20 MB after simplification | S | PRG/GUGiK is public; **verify the licence of any GitHub mirror** | `data/ref/geo/{woj,pow,gmi}.geojson` simplified with mapshaper |
| **P1 demo** | `mapa_dotacji` | **KPO B3.1.1 project list**: `search-program=29425&search-number-name-activity=30818`, 64 list pages + 631 detail pages | national (631) | ~700 req | S–M | public; attribution | 631 projects with title, beneficiary, total value, co-financing, woj/powiat, description. Dataset KPO rows linked on beneficiary + **exact value** (Zagrodno, Kamionka verified) |
| **P1 demo** | `ted` | (a) Per-buyer check for the 20 buyer NIPs with variants (`{nip}`, `NIP {nip}`, `3-3-2-2`, `3-2-2-3`, REGON) → an explicit **"searched, 0 water/sewage matches"** record per buyer. (b) **National PL water/sewage corpus**: `buyer-country=POL` + water/sewage CPVs, notice types cn/can/**can-modif** since 2021, XML for every `can-modif` | national | (a) ~150 req; (b) ~1,100 can-modif since 2023-11 + CN/CAN (thousands) via `paginationMode=ITERATION` | S–M | EU reuse (Decision 2011/833/EU) | Per-buyer check records stored; can-modif XML stored with change reason code (`add-wss`/`mod-cir`) + description; OCID parsed from `document-url-lot` |
| **P1 demo** | `kio` | KIO rulings: (a) per-buyer exact phrase for the 20 buyers, **verify `Zamawiający` on the Details page**; (b) **national water/sewage corpus**: phrases "kanalizacji sanitarnej" (≈971), "sieci wodociągowej", "oczyszczalni ścieków", "stacji uzdatniania wody" → Details + PDF text | national | ~2–3k rulings × (details + PDF ~70 KB) | M | public; natural persons pseudonymised | Drop items with lexical relevance 0; store sygnatura, date, Zamawiający, Miejscowość, outcome, articles, thematic index, PDF text. Candidate R11 case: KIO 2722/25 (Biecz WWTP PFU) |
| **P1 demo** | `nik` | NIK audit results: search `temat` ∈ {ściek, kanalizac, wodociąg, oczyszczal, wodno-ściek} → audit pages → Informacja PDFs (`typ,kk.pdf`) + wystąpienia PDFs (`typ,kj.pdf`) | national | ~60–120 audits, ~300–600 PDFs (text layer) | M | public information | PDFs + `pdftotext` (no `-layout` for two-column) stored. The 6 already-read audits are seeded first (P/11/148, P/20/046, S/22/002/LKI, S/23/003/LSZ, I/19/001/KSI, I/25/001/DLO) |
| **P1** | `cru` | Centralny Rejestr Umów (since 2026-07-01): water/sewage contracts nationally (`przedmiotUmowy` ~ kanaliz/wodoci/oczyszcz/uzdatn) + detail with **`zmianyUmowy[]`** (TSU02 aneks, TSU05–07 rozwiązanie/wypowiedzenie/odstąpienie) | national | ~1–5k contracts | S | public (art. 34a u.f.p.) | Stored + a polling mode (`--since`) for the **monitoring module**; ≤1 req/s (Incapsula WAF); skip weekend maintenance windows |
| **P1 demo** | `docs_22` | **Procurement documents for the 22 pilot projects**: SWZ, PFU/OPZ, PPU/SWU, Q&A, modifications, kwota (amount allocated), otwarcie ofert (offer opening), wybór (award). Use the "Adres strony internetowej prowadzonego postępowania" URL from each ContractNotice | 22 procedures | ~200–600 files | M | public information | Files + manifest per procedure; missing/blocked documents recorded with an evidence state (§4) |
| **P2** | `docs_sample` | Same documents for a **national sample of 150–300 procedures**, stratified (§4) | national sample | ~5–15k files | L | public information | Sample list saved as `data/ref/doc_sample.csv` with the selection reason per procedure |
| **P2** | `kposk` | KPOŚK annual reports 2020–2024 (dane.gov.pl dataset 3213), sheets `Aglomeracje`, `Oczyszczalnie` | national | 5 × ~3 MB xlsx | S | **CC BY 4.0** | Files stored; schedule-slip signal (same investment's planned date/cost across years) computed by the loader |
| **P2** | `gus_bdl` | BDL: km of sewer network (var 494), water network equivalents, population connected (9153) per gmina-year 2015–2025, via `data/by-variable` with `unit-level=6` | national | ~10 vars × ~25 pages | S | GUS open data, attribution | Gmina context features + "was it built" corroboration |
| **P2** | `gus_price_index` | Construction price index ("wskaźnik cen produkcji budowlano-montażowej"), yearly/quarterly 2015–2026 | national | tiny | S | GUS | `data/ref/price_index_construction.csv`, used by W2 unit-cost indexation (expert-editable in the catalogue) |
| **P2** | `fe_projects` | FE 2021–2027 project list xlsx (41 MB, status 01.11.2026) + FE 2014–2020 list (~59 MB): project no., beneficiary NIP, values, dates | national | 2 files | S | public | Stored; loader keeps water/sewage-related rows; **check whether KPO is included** (unverified) |
| **P2** | `nfosigw` | NFOŚiGW water/sewage agglomeration grants (dane.gov.pl dataset 2037) | national | ~7 × 400 KB | S | **CC0** | Stored |
| **P2** | `bip_22` | Targeted BIP lookups for the 22 gminas: WPF resolutions (załącznik nr 2, the list of multi-year investments), zarządzenia (tender committees), rejestr umów. Use robots → sitemap → keyword filter (place names from the titles, "kanalizac", "wodociąg", "WPF", "przedsięwzię") | 22 gminas | ~100–500 pages/files | M | public information | BIP base URL per gmina stored with confidence (central BIP register API + GUS BIR website + patterns); expert-confirmable in the panel |
| **P2** | `gus_bir` | GUS REGON BIR **test env** (public key `abcde12345abcde12345`): TERYT symbols + website per buyer; anonymised streets (say so in the docs) | 22 buyers → national buyers | ~3k SOAP calls at ≤1/s | S | public register | TERYT for every buyer that Biała lista can't give |
| **P3** | `krs` | KRS API odpis aktualny for contractors (liquidation/bankruptcy in dział 6 → R12 capacity signal) | 22 contractors → top national contractors | ~100–2k | S | public register | Re-test after the Saturday maintenance |
| **P3** | `bk2021` | Baza Konkurencyjności per-buyer check (expected ≈0 hits for KPO/Pzp projects) | 22 buyers | ~25 req | S | public; **drop contact persons** | "Searched" records for completeness |
| **P3** | `bzp_roads` | BZP live API slice for **roads** (CPV 45233*) 2024–2026, for the "sector pack in 60 s" demo (W9) | national slice | ~5–10k notices | S | public | Stored under a separate `sector=drogi` tag |

**Not scraped (decided):**
- OpenTender PL (NC licence, ends 2022)
- generic national BIP crawling (heterogeneous, L)
- RIO audit sites (16 different sites, L)
- the Mapa Dotacji CSV export (reCAPTCHA)
- ARiMR PROW beneficiaries (unreachable today; retry only if time allows)

---

## 3. Per-source notes (endpoints, pagination, pitfalls)

Full details and tested examples: `docs/research/01_bzp_api.md` (BZP), `docs/research/02_other_sources.md` (all others), `research/sources/examples.sh`.

### 3.1 `bzp_api` (e-Zamówienia)
- `GET {base}/mo-board/api/v1/notice`, where base is `https://ezamowienia.gov.pl` (prod, ~30 req/min/IP) or `https://bzp.cytr.us` (mirror of the copy, unlimited).
- Parameters: `NoticeType` (required), `PublicationDateFrom/To`, `PageSize` ≤500 (**≤100 from 2027-01-11**, and unknown params → 404 then, so send only documented params), `SearchAfter=<objectId of last item>`, `CpvCode` (fragment), `OrganizationName`, `OrganizationCity`, `OrganizationProvince` (PL02…), `OrderObject`, `NoticeNumber`, `ClientType`, `TenderType`, `OrderType`.
- **No NIP or tenderId filter**: filter client-side.
- Date params: prod wants date-only; the mirror needs a time part or the end day is excluded. Normalise in the client.
- Water/sewage CPV prefixes to sweep: `452313` (water/sewage pipelines), `452324` (sewers), `4523241`/`4523242` (sewerage/sewage works), `452321` (water mains), `452524` (sewage treatment), `452521`/`452522` (water treatment), `452321` and `452324` stormwater. Confirm the list with `docs/research/03_domain_methodology.md` §7.
- Notice types for the delta: ContractNotice, TenderResultNotice, AgreementUpdateNotice, ContractPerformingNotice, **NoticeUpdateNotice** (new for us: SWZ/deadline modifications during tendering; an R01/R09 signal). AgreementIntentionNotice is optional.
- Citation link per notice: `https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/<objectId>`. PDF: `/mo-board/api/v1/Board/GetNoticePdfById?noticeId=<objectId>`. Fetch PDFs only for the 22 + the doc sample (not national).
- `/mo-board/api/v1/notice/stats`: one call per run, for the dashboard.

### 3.2 `vat_whitelist`
- `GET https://wl-api.mf.gov.pl/api/search/nips/{nip1,…,nip30}?date=YYYY-MM-DD`.
- **Hard cap: 100 search requests/day/IP**, blocked until midnight after that. Cache forever, and put the national backlog in a queue table.
- Validate the NIP checksum locally first (weights 6,5,7,2,3,4,5,6,7).
- A missing VAT status ≠ invalid NIP (e.g. Zagrodno `Niezarejestrowany`, still returned).

### 3.3 `mapa_dotacji` (KPO B3.1.1)
- List: `https://mapadotacji.gov.pl/projekty/?search-program=29425&search-number-name-activity=30818&page_no={1..64}`. Detail: `/projekty/{id}/`.
- The **KPO number is not shown**. Link on beneficiary + exact total value (to the grosz) = confidence 1.0.
- Validate the KPO number in the dataset: `KPOD.03.15-IW.{nn}-{nnnn}/{yy}`, with **nn = 12 + voivodeship TERYT/2**.

### 3.4 `ted`
- `POST https://api.ted.europa.eu/v3/notices/search`, JSON body `{query, fields[], limit≤250, paginationMode:"ITERATION", iterationNextToken}`.
- Query syntax: `organisation-identifier-buyer=<exact>`, `buyer-name~"…"`, `FT~"…"`, `classification-cpv IN (…)`, `buyer-country=POL`, `notice-type=can-modif`, `publication-date>=YYYYMMDD`.
- Per-notice XML: `https://ted.europa.eu/en/notice/{pub-no}/xml`.
- For eForms modifications: `efac:ContractModification`, `efac:Change/efbc:ChangeDescription`, `efac:ChangeReason/cbc:ReasonCode` (`add-wss`≈art. 455 ust. 1 pkt 3, `mod-cir`≈pkt 4) + `efbc:ReasonDescription`. Pre-Oct-2023 notices need XML parsing (older forms).
- The CPV filter catches rail/road contracts with sewer sub-CPVs: keep all, and let the classifier decide relevance (same as BZP).

### 3.5 `kio`
- `POST https://orzeczenia.uzp.gov.pl/Home/GetResults` (form fields: `Phrase`, `Fle=1`, `SCnt=1`, `Kind=KIO`, `Dt`, `Pg`, filters `KIO.Purchaser`, `KIO.City`, …). The response is an HTML fragment with lexical and semantic relevance per item.
- Details: `/Home/Details/{id}`. Full text PDF: `/Home/PdfContent/{id}?Kind=KIO`.
- **Drop "Trafność wyszukiwania: 0"** (relevance 0) hits. For per-buyer use, require a `Zamawiający` match on Details (name collisions: Elbląg city vs rural gmina, Kamionka vs Kamionka Wielka, two Bobrowniki).

### 3.6 `nik`
- `POST https://www.nik.gov.pl/kontrole/wyniki-kontroli-nik/fmax,,strona,{N}.html` (form: `temat`, `jednjednostka`, `rodzaj`, `dataodx`, `datadox`, `zakres=dowolny`) returns JSON `{ilosc, xml}`.
- Audit page `/kontrole/wyniki-kontroli-nik/kontrole,{id}.html` → PDFs `…typ,kk.pdf` (Informacja) and `…typ,kj.pdf` (wystąpienie).

### 3.7 `cru`
- `POST https://rejestrumow.gov.pl/api-dp/v1/agreements/search?offset=&limit=` with body sections `menuGlowne` (nip, regon, nazwa, przedmiotUmowy, wartoscOd/Do, dataZawarciaOd/Do), `zmianyUmowy` (rodzajZmiany, dataZmianyOd/Do), `inneStronyUmowy`, …
- Detail: `GET /api-dp/v1/agreement/{idUmowy}`.
- Undocumented internal API behind a WAF: be gentle, cache, and keep raw snapshots.

### 3.8 `kposk`, `gus_bdl`, `nfosigw`, `fe_projects`
- KPOŚK: `https://api.dane.gov.pl/1.4/datasets/3213/resources` → resource files (2024: resource 1491599; 2023: 67894; 2022: 63049).
- BDL: `https://bdl.stat.gov.pl/api/v1/data/by-variable/{var}?unit-level=6&year=…&page-size=100` (anonymous limit ~10k req/7 days).
- FE 2021–27 list: `https://funduszeeuropejskie.gov.pl/wp-content/uploads/2026/11/Lista_projektow_FE_2021_2027_01112026.xlsx`.
- NFOŚiGW: dane.gov.pl dataset 2037.

---

## 4. Procurement documents (`docs_22`, `docs_sample`)

**Where documents live.** We measured the "Adres strony internetowej prowadzonego postępowania" URL on 40,441 national ContractNotices:

| Platform | Share | Adapter priority |
|---|---|---|
| `ezamowienia.gov.pl` (e-Zamówienia platform itself) | 28.2% | **1**: public procedure pages keyed by OCID `ocds-148610-…`. Find the public read endpoint for the documents list in the browser network tab, then use it |
| `platformazakupowa.pl` | 27.9% | **2**: `…/transakcja/{id}` pages with public attachments. **Behind Cloudflare: normal UA, low rate; if challenged, record `blocked` and skip (no evasion)** |
| `ezamawiajacy.pl` (Marketplanet) | 11.7% | **3**: `{buyer}.ezamawiajacy.pl/pn/{buyer}/demand/{id}/notice/public/details` |
| `uzp.gov.pl` (old miniPortal) | 7.2% | Likely dead links (miniPortal was retired); record the state and don't chase them |
| `logintrade.net` | 5.5% | 4, if time allows |
| others (eb2b, e-propublico, smartpzp, BIPs…) | ~19% | Generic: fetch the page, follow same-host links to pdf/docx/doc/zip/xlsx, max depth 2 |

**What to collect per procedure:**
- SWZ, PFU or OPZ, PPU/SWU
- dokumentacja projektowa/STWiORB/przedmiar (the design files are often huge zips: download the archive, list its contents, extract only text documents, and cap the size at e.g. 200 MB per procedure)
- Q&A ("wyjaśnienia treści SWZ")
- modifications
- "informacja o kwocie" (amount allocated), "informacja z otwarcia ofert" (offer opening), "informacja o wyborze" (award)

Classify the document type by filename and first page (catalogue `doc_type`).

**Evidence states** (the brief insists on them; record one per expected document per procedure):

| State | Meaning |
|---|---|
| `found` | document retrieved |
| `not_in_package` | expected, platform reachable, not present |
| `blocked` | platform gate / Cloudflare |
| `link_dead` | the URL no longer resolves |
| `not_applicable` | e.g. no PFU in a build-only procedure |

Never record "absent" as "didn't happen". See `docs/research/03_domain_methodology.md` §6.

**National sample (`docs_sample`, 150–300 procedures)**, stratified from the corpus. Save the list with its reason:
- 50 with the **largest cost overrun** (paid vs contract value)
- 50 with the **longest delays**
- 30 with **art. 455 ust. 1 pkt 4 change notices** (unforeseeable circumstances)
- 30 **design-build**, all 6 subsectors represented
- 50 **random controls** (on time, no changes): we need negatives
- prefer procedures hosted on adapters 1–3

---

## 5. Reference data (`data/ref/`)

| File | Source | Use |
|---|---|---|
| `teryt_terc.csv` | eTERYT TERC full file, or the BIP-register dictionary API `aplikacje.gov.pl/app/bip-back/api/dictionaries/voivodeships…` | Joins, map |
| `geo/{woj,pow,gmi}.geojson` | PRG (GUGiK) simplified with mapshaper (≤1 MB for woj, ≤10 MB for gmi) | Radar Polski map (W6) |
| `price_index_construction.csv` | GUS | W2 unit-cost indexation |
| `cpv_2008.csv` | EU CPV vocabulary (SIMAP/TED) | Labels, subsector map |
| `buyers_bip.csv` | §3 BIP discovery | BIP base URL per gmina + confidence |
| `doc_sample.csv` | §4 | Sample list with selection reasons |

---

## 6. Order of work (fits the 24 h plan in `docs/PLAN.md` §8)

1. **13:30–15:00 (P0)**:
   - BZP live client (mirror/prod switch) + delta + NoticeUpdateNotice
   - Biała lista for the 22 buyers + contractors
   - TERYT, GeoJSON
   - Load the BZP copy + the organizer XLSX into the DB through the importer
2. **15:00–19:00 (P1)**: Mapa Dotacji (631), TED per-buyer checks + national can-modif, KIO per-buyer + national corpus, NIK, CRU, `docs_22`.
3. **19:00–20:00**: scrape report v1 (see §7) for the HackTribe draft description.
4. **20:00–03:00 (P2)**:
   - `docs_sample`, KPOŚK, BDL, price index, FE lists, NFOŚiGW, BIP for the 22, GUS BIR
   - rsync raw to WCSS PD for embedding/classification batch jobs
5. **03:00+ (P3)**: KRS, BK2021 checks, roads slice for W9.

---

## 7. Output for the jury: scrape report (auto-generated)

The loader writes `docs/test_report_sources.md` + `exports/sources_summary.csv` from the manifests and DB. It feeds the required **"Raport z testu"** (test report).

**Per source:**
- queries run, records fetched, records loaded, errors, blocked, last run
- licence and data location

**Per pilot project (22 rows):**
- found/not-found per source with timestamp: BZP chain, Mapa Dotacji, TED ("searched, 0 water/sewage matches"), KIO, NIK, CRU, BIP, documents
- the link confidence and its basis
- dataset discrepancies detected: row 9 Zakrzew część, row 8 Biecz część, rows 7/14 KPO value vs contract, row 22 missing contract notice

**Link quality:** correct / uncertain / wrong counts (after expert review in the panel) vs the reference set.
