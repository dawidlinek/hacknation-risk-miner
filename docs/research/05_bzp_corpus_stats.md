# 05: BZP corpus, field parser, procedure chains, reference-class statistics and change causes

Corpus: the organisers' offline BZP copy (`materials/bzp_kopia/.../notices.jsonl`): 113,278 notices
published 2021-01-13 to 2026-11-12, selected by CPV so they cover water/sewage (wod-kan) works.
The analysis ran on 2026-11-21. All code is in `research/bzp_corpus/`. It uses the standard library
plus pandas and numpy, and a full rebuild takes about 2 minutes.

---

## 0. Headline numbers

| | value |
|---|---|
| Completed contracts in the corpus (ContractPerformingNotice after de-duplication) | **26,612** |
| …of which water/sewage is the main scope (our "core wod-kan works") | **11,254** (42%); 11,184 executed |
| …"wod-kan only as a component", e.g. a road with a storm sewer | 6,046 (23%) |
| …not wod-kan (gyms, schools, roads that only list a wod-kan CPV) | 8,943 (34%) |
| Total value of core wod-kan contracts (rows that pass quality checks) | **20.7 bn PLN gross**; paid 21.2 bn |
| Paid above contract value (sum of overruns) / net of underruns | **582 mln PLN** / 482 mln PLN (+2.3%) |
| Finished later than the original deadline (field 5.3 = Nie) | **30.3%** (all works: 32%) |
| Delay when late: median / P90 | **58 days / 188 days** |
| At least 1 contract change (5.4.1 > 0) | **41.4%** (all works: 48%) |
| Paid more than contract value (> +0.5%) | **21.5%**; cost deviation P90 = **+6.9%**, median 0% |
| Late share by value: < 0.5 mln → > 10 mln PLN | **19% → 52%** (changes 25% → 70%) |
| Design-and-build vs build-only | late 47% vs 28%; the gap holds in every value bucket (+5 to +23 pp) |
| Tenders for wod-kan works that were cancelled, 2022 → 2026 | 33% → 14%; "price above budget" (art. 255 pkt 3) 20% → 7% |
| Unit cost, sanitary sewer: median contract value per km (2021 → 2022) | 0.72 → 1.02 mln PLN/km (+41%) |

Full procedure chains (contract → result → performance notice) exist for **19,353 procedures**. For
86% of procedures that have a performance notice, the contract notice is in the corpus too, and for 91.5%
the result notice is. `tenderId` (OCID) is **never missing** (0 of 113,278).

---

## 1. Pipeline and files

| script | what it does | output |
|---|---|---|
| `bzp_parse.py` | **reusable library**: htmlBody → ordered field entries, typed normalisers, one extractor per notice type | – |
| `01_field_inventory.py` | field catalogue per type and year | `out/field_catalogue.csv`, `out/sections_free_text.csv`, `out/notices_by_type_year.csv` |
| `02_build_tables.py` | one streaming pass (10 processes, about 35 s) → normalised tables | `data/{notice_index,perf,perf_changes,changes,results,contract_notices}.csv.gz` |
| `03_chaining.py` | tenderId chains, reference resolution | `out/chain_*.csv/json`, `out/perf_ref_resolution.csv` |
| `wodkan_classify.py` | **reusable**: relevance filter, subsector, scope kind, work type, design-and-build, each with a "why" | – |
| `04_reference_stats.py` | one row per contract plus quality flags; distributions | `data/contracts_reference.csv.gz`, `out/ref_stats_*.csv`, `out/quality_flags.csv`, `out/min_n_bootstrap.csv`, `out/censoring_by_year.csv` |
| `change_keywords.py` | **reusable**: keyword pre-classifier for change reasons (R01–R15 + N-*) | – |
| `05_changes.py` | legal bases, value %, extensions, keyword frequencies, the stratified sample | `out/change_*.csv`, `data/change_reasons_sample.csv` |
| `gold_labels.py`, `06_gold_eval.py` | 150 hand labels, category frequencies, keyword vs gold | `data/gold_change_reasons.csv`, `out/gold_category_freq.csv`, `out/keyword_vs_gold.csv` |
| `07_wow_features.py`, `08_causes_by_year.py` | unit costs, competition, radar, backtest, pitch numbers | `out/wow_*.csv`, `data/radar_open_contracts.csv.gz`, `data/unit_cost_contracts.csv.gz` |

Run the scripts in order: `python3 -I 01_…`, `python3 -I 02_…`, then
`uv run --with pandas --with numpy python -I 03_… 04_… 05_… 06_… 07_… 08_…`.
`data/` is about 82 MB, can be regenerated, and is not covered by `.gitignore`. Consider adding it there.

---

## 2. Field parser and field catalogue

### 2.1 How the HTML is built

* All 113,278 notices use **one template version** (`<!-- Version 1.0.0 -->`) from 2021 to 2026.
* A field is an `<h3>` whose text starts with a numeric code: `4.4.)`, `1.3)`, `7.3.1)` or `4.2.` (four
  spellings, all handled). The value is either an inline `<span class="normal">` or the text after the
  `</h3>` (`<p>` blocks, plain text, `<div>`) up to the next `<h2>`/`<h3>`. Lists such as additional CPV codes
  come as one `<p>` per item.
* Some `<h3>` headers have no code and mark **context**:
  * `Część N` marks a lot (contract and result notices).
  * `Umowa dla części nr N` marks the lot a contract belongs to (performance and change notices).
  * `Kryterium N` marks an award criterion. `Wykonawca`, `Zamawiający` and `Podmiot` mark repeated parties.
* In result notices, sections V–VIII repeat **per lot** with the lot in the `<h2>` title:
  `SEKCJA V ZAKOŃCZENIE POSTĘPOWANIA (dla części 2)`. The parser takes the lot from there.
* Free-text sections without codes come as an `<h2>` followed by a `<div>`:
  * CP/AU "SEKCJA VI INFORMACJE DODATKOWE" (12.7% / 14.2% of notices)
  * TR "SEKCJA IX INFORMACJE DODATKOWE" (6.9%)
  * CN "SEKCJA IX – POZOSTAŁE INFORMACJE" (46%)

  These sections often explain what a value field means, e.g. "Uwagi do pkt 4.2: do 30 dni roboczych od
  daty protokolarnego przekazania terenu". Keep them.
* **Codes repeat.** The change block 5.4.2–5.4.8 repeats once per change in performance notices, and
  lots and criteria repeat their codes. The parser therefore returns an **ordered list** of
  `Entry(code, label, value, part, section, criterion)`. It also offers `first(code, part=)`, `all(code)`,
  `as_dict()` (first occurrence) and `groups(start_code)` to split repeated blocks.
* **Codes are not stable across notice types.** Contract value is `4.4` in CP/AU and `8.2` in TR. Planned
  duration is `4.2` in CP/AU, `8.3` in TR and `4.2.10` in CN. The extractors map codes to semantic names.

### 2.2 Normalisers (`bzp_parse.py`)

| function | input → output |
|---|---|
| `money()` | `"1 234 567,89 PLN"`, `"129513,18"`, `"129513.18 PLN"`, `"1.234.567,89 zł"`, NBSP → `(Decimal, currency)` |
| `duration()` | `"4 miesiące"`, `"330 dni"`, `"6 tygodni"`, `"2 lata"`, `"1,5 miesiąca"` → kind `days`. `"do 2023-05-30"` → kind `until`. `"Od 2021-02-09 do 2021-07-30"` → kind `range`. `planned_end(contract_date)` adds **calendar months** for month/year units. |
| `yes_no()` | Tak/Nie → bool; "nie dotyczy" → None |
| `iso_date()` | ISO dates and `dd.mm.yyyy` |
| `notice_no()` | `"2021/BZP 00005925/01"` → `{bzp:"2021/BZP 00005925", version:"01"}`. Also handles TED `2022/S 123-456789` and `456789-2024`. |
| `legal_basis_455()` | `"art. 455 ust. 1 pkt 4 ustawy"` → `["455.1.4"]` (several bases possible) |
| `nip()`, `regon()`, `cpv_codes()` | identifiers |
| `extension_days()` | best-effort extension parsed from free text ("przedłużenie terminu o 60 dni") |

All 26,842 performance-notice durations parse: 74.3% are "N miesięcy/dni", 23.4% "do DATE" and
2.3% "Od…do…".

### 2.3 Key fields per notice type, with fill rate

Every code with its label variants and fill rate per year is in `out/field_catalogue.csv` (380 rows).
"%" is the share of notices of that type where the field appears.

**ContractPerformingNotice (CP, 26,842)**, the main source for the reference class:

| code | label | % | notes |
|---|---|---|---|
| 2.1 / 2.2 / 2.3 / 2.4 | tenderId / numer / wersja / data | 100 | |
| 3.1 | Charakter zamówienia | 100 | "klasyczne < progi UE" etc. |
| 3.2 / 3.2.1 | poprzedzone ogłoszeniem / numer ogłoszenia (BZP or TED) | 100 / 96.7 | the link to the CN |
| 3.3 / 3.4 | współfinansowanie UE / nazwa projektu | 100 / 15.2 | |
| 3.5, 3.7, 3.8, 3.9, 3.10 | tryb, nazwa, krótki opis, CPV główny, CPV dodatkowe | 100, 100, 99.4, 99.4, 89.7 | |
| 4.1 | Data zawarcia umowy | 100 | |
| 4.2 | Okres realizacji zamówienia | 100 | the planned duration |
| 4.3.1 / 4.3.2 | wykonawca / NIP | 100 / 99.0 | 4.3.1.1 lists consortium members (6.8%) |
| 4.4 | Wartość umowy | 100 | gross PLN; **in about 10% it is not the award value** (see §5.1) |
| 4.5 | Numer ogłoszenia o wyniku (BZP or TED) | 100 | the link to the TR; **label text changed in May 2024**, code unchanged |
| 5.1 | Czy umowa została wykonana | 100 | Nie = 0.85% |
| 5.2 | Termin wykonania umowy | 97.1 | the actual completion date |
| 5.3 | Czy wykonano w pierwotnie określonym terminie | 99.8 | the declared on-time flag |
| 5.4.1 | Liczba zmian | 100 | 0 in 52.5% |
| 5.4.2–5.4.8 | per change: numer, podstawa prawna, przyczyny, opis, wartość, waluta, wzrost ceny | 47.5 (5.4.6 value 35.9) | 26,267 change blocks; block count always equals 5.4.1 |
| 5.5 | Łączna wartość wypłaconego wynagrodzenia | 100 | |
| 5.6 | Czy wykonana należycie | 100 | Nie = 1.8% |
| 5.7 | kontrolowane wymagania (art. 95) | 100 | |

**AgreementUpdateNotice (AU, 5,079):**

| code | label | % |
|---|---|---|
| 2.1 / 2.2 | dotyczy zmiany (Umowy) / tenderId | 100 |
| 3.1 / 3.1.1 | poprzedzone ogłoszeniem / numer | 100 / 97.7 |
| 3.2 / 3.3 | UE / projekt | 100 / 16.8 |
| 4.1, 4.2, 4.4, 4.5 | data umowy, okres realizacji, wartość umowy, nr ogłoszenia o wyniku | 100 |
| 4.3.2 | NIP wykonawcy | 94.7 (**40% in 2021**, 100% from 2024) |
| 5.1 | Data zmiany | 100 |
| 5.2 | Podstawa prawna zmiany | 100 (only 455.1.3 and 455.1.4, as the law requires) |
| 5.3 | Przyczyny dokonania zmian (free text) | 100 |
| 5.4 | Krótki opis zmiany (free text) | 100 |
| 5.5.1 / 5.5.2 | Wartość zmiany / waluta | 74.3 |
| 5.5.3 | Wzrost ceny | 100 |
| 5.6 / 5.7 | wcześniejsze zmiany / nr wcześniejszego ogłoszenia o zmianie | 100 / 28.7 |

**TenderResultNotice (TR, 40,453 notices → 49,895 lot rows):**

| code | label | % |
|---|---|---|
| 2.4 | tenderId | 100 |
| 2.11 / 2.12 | UE / projekt | 100 / 15.2 |
| 2.13 / 2.14 | poprzedzone ogłoszeniem / numer CN | 100 / 95.7 |
| 3.1 / 3.1.1 / 3.1.2 | tryb / uzasadnienie trybu / identyfikator wcześniejszego postępowania | 100 / 4.0 / 1.0 |
| 4.2 | części jako odrębne postępowania | 99.96 |
| 4.3 / 4.3.1 / 4.5.5 | wartość zamówienia (net estimate) / dla postępowania / wartość części | 44.4 / 8.8 / 11.8 |
| 4.5.1, 4.5.3, 4.5.4 | opis, CPV główny, CPV dodatkowe (per lot) | 100, 100, 91.9 |
| 5.1 | zawarcie umowy albo unieważnienie | 99.9 |
| 5.2 / 5.2.1 | podstawa / przyczyna unieważnienia | 25.1 |
| 6.1, 6.1.3, 6.1.6 | liczba ofert, od MŚP, odrzuconych | 90.3, 89.3, 87.8 |
| 6.2 / 6.3 / 6.4 | cena najniższa / najwyższa / wybranej oferty | 86.5 / 86.0 / 76.2 |
| 7.2, 7.3.1, 7.3.2, 7.4 | wielkość wykonawcy, nazwa, NIP, podwykonawcy | 66.8, 76.6, 76.5, 67.1 |
| 8.1 / 8.2 / 8.3 | data umowy / wartość umowy / okres realizacji | 76.6 (each awarded lot) |

**ContractNotice (CN, 40,904 → 50,029 lot rows):**

| code | label | % |
|---|---|---|
| 2.3, 2.4, 2.5 | nazwa, tenderId, numer | 100 |
| 2.14 / 2.15 | UE / projekt | 100 / 15.5 |
| 2.16 | tryb | 100 |
| 4.1.4 | części jako odrębne postępowania | 100 |
| 4.1.5 | wartość zamówienia | **9.8** |
| 4.1.8 / 4.1.9 | oferty częściowe / liczba części | 100 / 11.7 |
| 4.2.2, 4.2.6, 4.2.7 | opis, CPV (per lot) | 100 |
| 4.2.8 / 4.2.9 | opcje | 100 / 1.4 |
| **4.2.10** | okres realizacji (per lot) | 100 |
| 4.3.x | kryteria ("Kryterium N" blocks) | 100 |
| 6.4 / 6.5 | wadium / ZNWU | 100 |
| 7.1 / 7.2 | zaliczki | 100 / 6.8 |
| **7.3 / 7.4** | przewiduje zmiany umowy / rodzaj i zakres zmian | 100 / 98.5; this is the planned change-clause text (art. 455 ust. 1 pkt 1), useful for "which clauses limited problems" |
| 8.1 / 8.4 | termin składania ofert / związania ofertą | 100 |

None of the four types contains "kwota przeznaczona na sfinansowanie" (the budget the buyer intends to
spend). The only budget proxy is the **net estimate** (TR 4.3 / 4.3.1 / 4.5.5, CN 4.1.5).

### 2.4 Does the layout change between 2021 and 2026?

Effectively no. The codes, sections and template are the same in every year. The small differences:

* The 4.5 label in CP changed in **May 2024**. Before: "Numer ogłoszenia o wyniku postępowania w BZP lub
  Dz. Urz. UE". After: "…zamieszczonego w BZP lub numer ogłoszenia o udzieleniu zamówienia opublikowanego w
  Dzienniku Urzędowym Unii Europejskiej". **Parse by code, not by label.**
* Referenced notice numbers sometimes come **without the version suffix** ("2025/BZP 00394693"). The
  normaliser handles this.
* Fill-rate drift: phone/fax filled 77% in 2021 and 47% in 2026. AU contractor NIP 40% in 2021 and 100% from
  2024. CP change blocks (5.4.2+) 30% in 2021 and 54% in 2026, because more contracts have changes and the
  field is filled more often. EU-project name 10% in 2021 and 22% in 2026.

---

## 3. Procedure chains (tenderId / OCID)

* `tenderId` is filled in **100%** of notices (0 missing) and always has the form `ocds-148610-…`.
* **Versions:** the corpus contains several versions of the same notice. 772 rows share
  (type, bzpNumber), mostly CN versions /02 to /15 (2,666 CN rows have version > 01, against 31 CP and
  106 TR). **Keep the highest version** per (type, bzpNumber), which leaves 112,886 notices.
* **Re-published performance notices:** the same contract (tenderId + contractor NIP + value + lot)
  is sometimes published again under a **new** notice number, often with a different completion
  date. There are 213 such extra rows, about 0.8%. Keep the latest publication.
* **One tenderId reused for unrelated procedures** happens occasionally, e.g. a road project and a design
  service sharing one OCID. When chaining, always check the title and buyer too.

**Chain coverage** (45,069 procedures after de-duplication; `out/chain_patterns.csv`):

| pattern | procedures | % |
|---|---|---|
| CN+TR (awarded or cancelled, no performance notice yet) | 17,124 | 38.0 |
| **CN+TR+CP** | 16,985 | 37.7 |
| CN only (ongoing or no result yet) | 2,972 | 6.6 |
| **CN+TR+AU+CP** (full chain with changes) | 2,368 | 5.3 |
| TR+CP (CN missing: free-hand procedure, TED or pre-2021) | 1,697 | 3.8 |
| CP only | 1,257 | 2.8 |
| other | 2,666 | 5.9 |

* Full chain CN→TR→CP: **19,353 procedures**. With at least one AU: 2,368.
* Of procedures that have a CP: the CN is present in **86.2%**, the TR in **91.5%**, both in 83.5%.
* Of procedures that have an AU: 82.7% also have a CP. AU 4.5 resolves to a TR in the corpus in 94%.
* Of procedures that have a CN: 91% have a TR and 49% a CP. A CP is reported for 50–60% of CNs from
  2021–2025 and **14% of CNs from 2026** (the contracts are not finished yet).

**How CP notices reference other notices** (`out/perf_ref_resolution.csv`):

| field | BZP number | TED number | missing | other text | resolves in corpus (BZP) | same tenderId |
|---|---|---|---|---|---|---|
| 3.2.1 → CN | 93.0% | 3.5% | 3.3% (no prior notice, e.g. free-hand award; 3.2 = Nie in 905 rows) | 0.2% | 22,611 / 24,950 (90.6%) | 99.9% of resolved |
| 4.5 → TR | 96.2% | 3.7% | 0 | 0.2% | 24,416 / 25,791 (94.7%) | 99.99% of resolved |

* The 2,339 unresolved 3.2.1 BZP references fall mostly in 2021 (973). They are CNs published before the
  corpus starts or under CPVs outside the selection. 196 point to another notice type, and 153 of those
  point to the **TR** instead of the CN (a user error).
* Above-EU contracts: 1,039 CPs (3.9%) have `isTenderAmountBelowEU = false`. Their CN/TR are on **TED**
  and are not in this copy, so a TED connector is needed to close those chains.

**Lots and multiple contracts:**

* **Every CP notice describes exactly one contract.** 4.1 appears exactly once in every notice.
* 23% of CPs carry an `Umowa dla części nr N` marker. 5,339 have one lot and 846 have 2 to 8 lots, i.e. one
  contract covering several lots.
* 2,077 procedures have more than one CP (5,711 notices), up to 10+ for multi-lot procedures.
* CN: 11.7% are divided into lots (4.1.9). TR: 11.8% have `Część N`, which gives 49,895 lot rows from 40,453
  notices.
* 261 procedures have 2 or more TR notices (239 have exactly 2; lots settled at different times). 1,058
  procedures have 2–11 AU notices.
* **Matching CP → TR lot:** use (TR number from 4.5, contractor NIP). This matches 10,284 of 11,237 core
  wod-kan CPs with a TR reference. Then try (TR number, value within ±1%), which matches 96 more. A
  single-lot TR is the last fallback.
* **Planned values in CP vs TR** (23,957 matched pairs):
  * Contract date identical in 98.3%.
  * Planned end identical in 94.7%. The CP's 4.2 is **later by more than 7 days in 3.4%**; those
    contracts were probably extended by annex and the new deadline was typed in.
  * Contract value within 0.5% in **90.4%**.

---

## 4. Relevance filter and subsector classification (`wodkan_classify.py`)

Because the copy is selected by CPV, 35,674 notices have the generic main CPV 45000000 and about 20k are
road works. CPV alone cannot decide relevance; the **title** has to.

**Rule: the first object named in the title is the main scope.** Polish titles put the main object first:
"Przebudowa drogi … wraz z kanalizacją deszczową" is a road.

1. Find all wod-kan object keywords (per subsector, below) and all "other main object" keywords (droga,
   ulica, budynek, szkoła, sala gimnastyczna, boisko, termomodernizacja, sieć ciepłownicza, gazociąg,
   melioracja, rzeka, wewnętrzna instalacja wod-kan, …) with their positions.
2. The first hit decides:
   * a wod-kan keyword first → `core`
   * another object first, but a wod-kan keyword present → `component`
   * no wod-kan keyword in the title: repeat steps 1–2 on the first 600 characters of the short description
   * still nothing: a strong wod-kan main CPV (45231300, 452324xx, 4525212x, 45262220, …) → `cpv_only`;
     otherwise `none`.
3. The main subsector is the subsector of the first wod-kan keyword. Every matched subsector is stored as an
   additional subsector, as the expert classification asks.
   * "sieć wodno-kanalizacyjna" → WOD main + SAN additional.
   * SAN keywords followed within 30 characters by "deszcz/burz/opadow" → DESZ.
4. Tags: `scope_kind` (`works`, `design_only`, `supervision`, `maintenance` (awarie, konserwacja,
   czyszczenie, umowy ramowe), `delivery`); `work_type` (`build` / `renovation` / `mixed`); `design_build`
   ("zaprojektuj i wybuduj", "zaprojektowanie i wykonanie", "wraz z opracowaniem dokumentacji", …, in the
   title or the description).

| subsector | keyword stems (beginning of a word, case-insensitive) | CPV fallback |
|---|---|---|
| OCZ Oczyszczalnia ścieków | (pod)oczyszczal*, przydomow* oczyszcz*, osad* ściekow*, stacj* zlewn*, POŚ | 45252100/127, 45232420/421/422, 4525212x |
| SUW Uzdatnianie i zaopatrzenie | uzdatnia*, SUW, stacj* wodociągow*, ujęci*, studni* głębinow*, hydrofor*, zbiornik* wody pitnej/wyrównawcz*, wież* ciśnień, stacja podnoszenia ciśnienia, wody pitnej | 45252126, 45232430, 45252120, 45262220, 45255110, 4523215x |
| DESZ Kanalizacja deszczowa i retencja | kanalizac* deszczow*/burzow*, deszczow*, wód opadowych, retencj*, odwodnieni*, drenaż*, wpust* uliczn*, separator* | 45232130, 45232454 |
| SAN Kanalizacja sanitarna | kanalizac* (not "teletechn*"), rekanalizac*, kanał sanitarny, kolektor* (not "słoneczny"), przepompowni* ścieków, tłoczn*, ściek*, wodno-ściekow* | 45232410/400/440/411/423/424 |
| WOD Sieć wodociągowa | wodociąg*, sieci wodnej, magistral* wod*, przyłącz* wod*, wodno-kanaliz*, wod-kan, hydrant* | 45232150, 45232100 |
| INNE | core wod-kan with no subsector keyword (in practice 4 contracts; mixed "gospodarka wodno-ściekowa" goes to SAN) | |

Results on the 26,612 completed contracts:
* relevance: core 11,607, component 6,046, cpv_only 16, none 8,943
* scope: works 25,417, maintenance 774, services 250, delivery 132, design-only 38
* **Core wod-kan works: 11,254.** By subsector: SAN 4,298, WOD 4,038, DESZ 1,088, SUW 994, OCZ 832.

Spot checks of 30 random titles per class, read by hand: core about 29/30 correct; component (almost all
roads with drainage or storm sewers) and none (roads, buildings, schools, heat networks) 30/30 plausible.
The known false positives were fixed: "kolektor kanalizacji deszczowej", "kolektory słoneczne",
"kanalizacja teletechniczna", "urządzeń", "jazdy".

---

## 5. Reference-class statistics (ContractPerformingNotice)

### 5.1 Definitions: computing planned vs actual robustly

* **Planned end** comes from the duration field, at award if possible:
  * "do DATE" → DATE; "Od A do B" → B
  * "N miesięcy / lat" → contract date + N **calendar** months
  * "N dni / tygodni" → contract date + N days
  * Prefer **TR 8.3** at award; fall back to CP 4.2. CP 4.2 sometimes holds the annexed deadline (3.4% of
    matched pairs).
* **Actual end** = CP 5.2. **Actual duration** = 5.2 − 4.1.
* **Late** = the declared flag 5.3 = "Nie", i.e. the original deadline was missed. This is the primary,
  authoritative measure.
* **Delay (reconciled)**:
  * 5.3 = Tak → 0. Computed positive values here are mostly start-date conventions, e.g. "od przekazania
    placu budowy", which the form does not capture.
  * 5.3 = Nie and computed > 0 → the computed value.
  * 5.3 = Nie and computed ≤ 0 → unknown (2.4% of rows).

  How well the declared flag and the computed delay agree (`q_*` flags):

  | duration type | declared on time → computed ≤ 0 | declared late → computed > 7 d |
  |---|---|---|
  | "do DATE" | 85% | 82% |
  | months / days | 68.5% (12.8% fall within 1–7 days: month rounding) | 92% |

  3.7% of rows are on time but computed > 30 days late. 2.4% are late but computed ≤ 0.
* **Cost deviation** = (5.5 paid − contract value) / contract value.
  * Baseline: prefer **TR 8.2** (value at award) when matched. CP 4.4 differs from it in 9.6% of matched
    pairs and sometimes already contains the annexed value.
  * With TR 8.2 as the baseline, the overrun share rises from 20.7% to 23.5% and P90 from 6.5% to 9.2%. The
    tables below use CP 4.4, so they are a **lower bound**.
  * The form says nothing about net vs gross; both values are gross by practice.
* **Usable rows:** time stats use 96% of core rows (`time_ok`), cost stats 98.4% (`cost_ok`). See §6.

### 5.2 Distributions, core wod-kan works (n = 11,184 executed)

All tables: `out/ref_stats_by_group.csv`. Delay columns use the reconciled delay; the "if late" columns
cover only contracts declared late.

| group | n | late % | ≥1 change % | planned days P50 | delay if late P50 / P90 (days) | delay % of planned P75 / P90 | cost dev P75 / P90 (%) | paid > value % | paid < value % |
|---|---|---|---|---|---|---|---|---|---|
| **all core wod-kan** | 11,184 | **30.3** | **41.4** | 152 | **58 / 188** | 9.2 / 44.6 | 0.0 / **6.9** | **21.5** | 6.4 |
| wod-kan only as a component | 6,002 | 33.2 | 53.2 | 180 | 50 / 181 | 12.5 / 50.7 | 3.3 / 10.7 | 36.1 | 9.5 |
| not wod-kan | 9,200 | 33.5 | 51.8 | 183 | 59 / 203 | 12.3 / 49.3 | 2.8 / 10.8 | 34.4 | 10.9 |

**By subsector:**

| subsector | n | late % | change % | planned P50 | delay if late P50 / P90 | delay % P90 | cost P90 % | paid > value % |
|---|---|---|---|---|---|---|---|---|
| Sieć wodociągowa | 4,019 | 24.0 | 33.0 | 122 | 45 / 164 | 38.3 | 5.3 | 16.6 |
| Kanalizacja sanitarna | 4,268 | 32.0 | 44.7 | 180 | 60 / 185 | 44.6 | 7.4 | 23.4 |
| Kanalizacja deszczowa i retencja | 1,078 | 30.9 | 46.0 | 120 | 62 / 193 | 63.3 | **11.5** | **29.0** |
| Oczyszczalnia ścieków | 827 | **39.4** | 49.1 | 274 | **80 / 253** | 50.4 | 5.1 | 23.0 |
| Uzdatnianie i zaopatrzenie w wodę | 988 | **40.3** | 50.2 | 251 | 60 / 200 | 47.0 | 6.4 | 24.0 |

**By contract value** (gross PLN). This is the strongest single factor:

| value | n | late % | change % | planned P50 | delay if late P50 / P90 | cost P90 % | paid > value % |
|---|---|---|---|---|---|---|---|
| < 0.5 mln | 4,921 | 19.0 | 24.6 | 91 | 39 / 128 | 2.8 | 12.3 |
| 0.5–1 mln | 1,740 | 30.3 | 42.1 | 152 | 44 / 157 | 6.6 | 20.3 |
| 1–2.5 mln | 1,975 | 38.1 | 52.4 | 213 | 61 / 190 | 8.3 | 25.8 |
| 2.5–5 mln | 1,408 | 44.3 | 60.4 | 335 | 63 / 206 | 9.9 | 33.2 |
| 5–10 mln | 830 | 46.5 | 70.7 | 457 | 92 / 238 | 9.8 | 39.9 |
| > 10 mln | 310 | **51.6** | 70.3 | 560 | **114 / 344** | 10.3 | **46.7** |

**By year the contract was signed.** Later years are right-censored; read the caveat below.

| year | n | late % | change % | delay if late P50 | delay % P75 | cost P90 % | paid > value % |
|---|---|---|---|---|---|---|---|
| 2021 | 1,477 | **35.0** | 42.4 | 61 | **19.3** | **8.3** | 21.9 |
| 2022 | 2,435 | 30.3 | 41.7 | 68.5 | 7.9 | 5.7 | 21.8 |
| 2023 | 2,315 | 30.8 | 43.2 | 75 | 10.0 | 7.2 | 22.8 |
| 2024 | 2,123 | 27.6 | 41.9 | 59 | 2.9 | 7.3 | 23.2 |
| 2025* | 2,152 | 30.3 | 39.2 | 42 | 10.2 | 6.1 | 19.4 |
| 2026* | 681 | 26.3 | 38.2 | 24 | 0 | 5.3 | 17.0 |
| cohort 2021–22 | 3,913 | 32.1 | 42.0 | 64 | 11.9 | 6.8 | 21.9 |
| cohort 2023+ | 7,271 | 29.3 | 41.2 | 52 | 7.8 | 6.9 | 21.3 |

\* **Right-censoring.** A contract appears here only once it is finished and reported, which is required
within 30 days of performance. Recent cohorts therefore contain mostly short, on-time contracts:

* Only 153 of 2,152 contracts signed in 2025 had a planned end before 2025-06-30.
* Median planned duration is 183 days for the 2022–2024 cohorts, 120 days for 2025 and 90 days for 2026.

Compare cohorts only on contracts with comparable follow-up (`out/censoring_by_year.csv`). The inflation
shock is weak in completed contracts. 2021 contracts are the worst: 35% late, P75 of delay 19%, cost P90
8.3%. The shock shows strongly in **cancelled tenders** (§10.2) and in **unit costs** (§10.1). For long
projects the 2021–22 cohort is worse:

| subsector | late %, 2021–22 cohort | late %, 2023+ cohort |
|---|---|---|
| OCZ | 47 | 35 |
| SUW | 47 | 37 |
| DESZ | 36 | 28 |

Part of that gap is censoring (`out/ref_stats_subsector_x_cohort.csv`).

**By other dimensions:**

| dimension | group | n | late % | change % | delay if late P50 | cost P90 % | paid > value % |
|---|---|---|---|---|---|---|---|
| EU co-financing (3.3) | yes | 2,573 | 37.6 | 47.8 | 55 | 5.7 | 20.6 |
| | no | 8,611 | 28.1 | 39.6 | 59 | 7.1 | 21.8 |
| design-and-build | yes | 1,390 | **47.2** | 56.0 | 80 | 6.1 | 19.9 |
| | no | 9,794 | 27.9 | 39.4 | 54 | 6.9 | 21.8 |
| work type | build | 7,236 | 29.0 | 40.1 | 58 | 6.4 | 20.5 |
| | renovation | 1,631 | 32.3 | 43.7 | 53 | 9.3 | 25.1 |
| | mixed | 1,372 | 36.6 | 49.1 | 62 | 7.0 | 26.3 |
| region (late %, lowest → highest) | | | kujawsko-pomorskie 23.1, podkarpackie 24.1, lubelskie 24.8, …, łódzkie 35.8, dolnośląskie 40.2, lubuskie 43.1 | | | | |

Controlling for size (`design_build` and `euFunded` within value buckets):

* **Design-and-build** contracts are late more often in every bucket, by +5 to +23 pp; the largest gap is
  in < 0.5 mln, 41% vs 18%. Their **cost overrun share is lower** (8–36% vs 13–47%), which is consistent with
  lump-sum design-build moving cost risk to the contractor.
* **EU-funded** contracts are late more often in every bucket, by +2 to +13 pp.

Region table for a map: `out/wow_pitch_by_province.csv` (all 16 provinces, n from 225 to 1,698).

### 5.3 Reference-class sizes

Core wod-kan executed contracts, subsector × value bucket (`out/ref_class_sizes.csv`; with work type:
`ref_class_sizes_detail.csv`):

| | <0.5 | 0.5–1 | 1–2.5 | 2.5–5 | 5–10 | >10 mln |
|---|---|---|---|---|---|---|
| SAN | 1,565 | 705 | 861 | 656 | 371 | 110 |
| WOD | 2,349 | 595 | 563 | 321 | 153 | **38** |
| DESZ | 620 | 198 | 156 | **47** | **34** | **23** |
| SUW | 218 | 137 | 214 | 265 | 136 | **18** |
| OCZ | 167 | 105 | 180 | 118 | 136 | 121 |

---

## 6. Data-quality issues (quantified)

From `out/quality_flags.csv`: 26,612 CPs after de-duplication; core wod-kan in brackets.

| issue | n (% of all) | core wod-kan % | handling |
|---|---|---|---|
| notice versions (/02, /03) of the same CP | 17 rows (CN: 2,666) | | keep the latest version |
| contract re-published under a new number | 213 | | keep the latest publication |
| not executed (5.1 = Nie) | 226 (0.85%) | 0.62 | exclude from completed stats; a termination signal of its own |
| completion date 5.2 missing | 780 (2.9%) | 2.8 | time stats NA |
| **completion date after the notice publication date** (impossible) | 210 (0.8%) | 0.75 | exclude from time stats (probably the planned date typed in) |
| completion before contract date | 35 (0.13%) | | exclude |
| planned duration ≤ 0 or > 5 years | 25 | | exclude |
| early by more than 1 year / late by more than 2 years | 68 / 14 | | keep, flag |
| **paid = 0** | 130 (0.5%) | 0.4 | exclude from cost stats |
| **decimal or scale errors** (paid/value ≈ 10, 100, 1000 or their inverses, e.g. value 365,927,500 vs paid 3,818,314) | 75 (0.3%) | 0.3 | exclude, or fix by ×10ⁿ |
| paid < 50% of value (not a scale error) | 178 (0.7%) | 0.5 | exclude from cost stats (partial or terminated) |
| paid > 200% of value | 46 (0.17%) | 0.18 | exclude |
| paid/value exactly 1.23 or 1/1.23 (net/gross mix-up) and 1.08 or 1/1.08 | 201 (0.76%) | 0.71 | 1.23: 53 vs about 15 expected by chance. **Net/gross confusion is real but rare (about 0.2–0.3%)**: flag, don't fix. CP vs TR values with ratio 1.23: 38 of 23,957 pairs. |
| on-time declared but computed delay > 30 days | 984 (3.7%) | 3.4 | use the declared flag; delay = 0 |
| late declared but computed delay ≤ 0 | 638 (2.4%) | 2.5 | magnitude unknown |
| 0 changes declared but paid ≠ value (±0.5%) | 1,947 (7.3%) | 5.7 | remeasurement contracts, penalties: real, not an error |
| on-time flag missing | 47 | | |
| currency not PLN | 3 | | |
| CP 4.4 differs from TR 8.2 value (> 0.5%) | 9.6% of matched | | baseline = TR 8.2 |
| CP 4.2 planned end later than TR 8.3 | 3.4% of matched | | baseline = TR 8.3 |
| very large outliers that are plausible typos (e.g. 72 mln PLN for one street's storm sewer) | a few | | robust statistics (medians and quantiles), never plain sums without a filter |
| 4.5 or 3.2.1 pointing at the wrong notice type | 153 | | resolve by tenderId |

After these filters, **96% (time) and 98% (cost)** of core contracts can be used.

---

## 7. Contract changes

### 7.1 Legal bases

* **AgreementUpdateNotice** contains only art. 455 ust. 1 pkt 3 and pkt 4. That is correct: only those
  changes require a separate notice.
* The **full picture** comes from the change blocks inside performance notices (`out/change_bases.csv`).

| basis | meaning | AU, core wod-kan (n = 1,705) | changes inside CP, core wod-kan (n = 8,586) | CP, all |
|---|---|---|---|---|
| 455.1.1 | foreseen in the procurement documents (change clause) | – | **60.0%** | 56.9% |
| 455.2 | de minimis (< EU threshold and < 15% for works) | – | **19.0%** | 22.2% |
| 455.1.4 | unforeseeable circumstances | **62.8%** | 12.9% | 11.5% |
| 455.1.3 | additional works by the same contractor | 37.2% | 7.3% | 8.8% |
| 455.1.2 | change of contractor (lit. a/b/c) | – | 0.7% | 0.7% |

So **only about 20% of changes ever get a separate AU notice**. The other 80% are visible only in the
performance notice. A model trained only on AU notices would miss most changes.

### 7.2 Price increase and size of the change

From `out/change_value_stats.csv`, core wod-kan. Value % = change value / contract value, for changes that
report a value.

| source / basis | n | "wzrost ceny" = Tak | value given | value % if increase: P25 / P50 / P75 / P90 |
|---|---|---|---|---|
| AU 455.1.3 | 635 | **77%** | 86% | 2.1 / **6.0** / 15.0 / 31.2 |
| AU 455.1.4 | 1,070 | 33% | 56% | 2.6 / **6.9** / 17.9 / 50.0 |
| AU all | 1,705 | 49% | 67% | 2.3 / 6.4 / 15.7 / 36.4 |
| CP 455.1.1 | 5,154 | 16% | 51% | 1.3 / 3.7 / 10.8 / 46.0 |
| CP 455.2 | 1,630 | 70% | 88% | 1.4 / 3.4 / 8.6 / 14.6 (the 15% cap is visible) |
| CP 455.1.3 | 630 | 80% | 87% | 1.9 / 5.4 / 13.8 / 25.1 |
| CP 455.1.4 | 1,110 | 29% | 58% | 2.3 / 6.3 / 15.7 / 34.8 |
| CP all | 8,586 | **33%** | 62% | 1.5 / **4.1** / 10.6 / 22.6 |

**What was changed** (keyword detection in reason + description; `out/change_what.csv`):

| source | deadline | price | scope |
|---|---|---|---|
| AU 455.1.4 | **71%** | 34% | 27% |
| AU 455.1.3 | 49% | 45% | 47% |
| CP all | 62% | 28% | 30% |

Most "unforeseeable circumstances" changes are **deadline extensions**.

### 7.3 Deadline extension parsed from descriptions

Core wod-kan AU, `out/change_extension_stats.csv`:

* An extension in days could be extracted for only about **20%** of AU notices: 87 from "o N dni/miesięcy"
  and 263 from a new deadline date minus the planned end, out of about 60–70% that change the deadline at all.
* Where parsed: extension **P50 = 79 days**, P25 = 32, P75 = 170, P90 = 358 (455.1.4: P50 = 84; 455.1.3: P50 = 71).
* The more reliable delay measure stays CP 5.2 − planned end. Use the AU text to explain the delay, not to
  measure it.

### 7.4 Inflation, war and COVID signals in change reasons

Shares of change reasons that match the keyword patterns (`out/wow_change_causes_by_year.csv`,
`out/change_price_reasons_by_year.csv`):

| contract year | COVID (CP changes) | price, war, indexation (CP) | price, war, indexation (AU) |
|---|---|---|---|
| 2021 | 10.8% | 5.8% | 11.7% |
| 2022 | 2.1% | 6.2% | 10.3% |
| 2023 | 0.7% | 2.6% | 4.7% |
| 2024 | 0.4% | 0.9% | 2.1% |
| 2025 | 0.4% | 1.0% | 3.0% |

The 2021–22 shock is clearly visible in the **reasons** for changes.

---

## 8. Change-cause taxonomy (hand-labelled gold sample)

**Sample:** 150 "Przyczyny" texts from core wod-kan contracts, stratified by source and basis:

* AU 455.1.4: 45, AU 455.1.3: 30
* CP 455.1.1: 30, CP 455.2: 20, CP 455.1.4: 15, CP 455.1.3: 10

Texts shorter than 25 characters were excluded (2.9% of AU and 4.6% of CP reasons are that short).
Seed 20261121. I read every text together with its "opis zmiany" and assigned a **primary** and an optional
**secondary** category. Files: `data/gold_change_reasons.csv` (texts, labels and notice numbers, usable as
few-shot examples) and `out/gold_category_freq.csv`.

New categories proposed in addition to R01–R15:

* **N-WEATHER**: weather
* **N-PRICE**: war in Ukraine, inflation, material prices, indexation, price renegotiation
* **N-COVID**: COVID-19
* **N-CLIENT**: scope extended or changed at the buyer's request
* **N-SCOPE-RED**: scope reduced, works abandoned
* **N-LAW**: change in the law
* **N-FORMAL**: formal or personnel change with no risk content
* **N-UNSPEC**: no actual cause given, only the statutory formula or the effect restated. This is not a risk
  category, but it matters as a **data-quality category for the expert panel**.

Groundwater and archaeological finds are kept under R02, utility collisions and land access under R03, and
design errors under R01 (gaps or inconsistencies in the documentation) or R09 (change of technical solution).

| category | primary n (%) | any n (%) | example quotes (verbatim fragments, notice number) |
|---|---|---|---|
| **R07** additional or substitute works, no root cause stated | **33 (22.0)** | 41 (27.3) | "Wykonanie robót dodatkowych, które są konieczne do prawidłowego wykonania przedmiotu umowy" (2021/BZP 00338399/01), "Pismo wykonawcy, protokół konieczności w związku z potrzebą wykonania robót dodatkowych/zamiennych." (2022/BZP 00098044/01) |
| **R02** existing conditions not investigated: ground, **groundwater**, condition of existing assets, archaeology | **19 (12.7)** | 25 (16.7) | "wystąpiły inne warunki gruntowo-wodne, niż wcześniej zakładane, wyższy poziom wód gruntowych - co spowodowało opóźnienia w wykonywaniu wykopów" (2023/BZP 00410290/01), "stwierdzono występowanie odmiennych warunków gruntowych niż przewidywała dokumentacja projektowa. Konieczność mechanicznego odspojenia skał" (2023/BZP 00396960/01) |
| **N-UNSPEC** no actual cause given | **16 (10.7)** | 18 (12.0) | "Zmiana umowy spowodowana jest okolicznościami, których zamawiający, działając z należytą starannością, nie mógł przewidzieć w momencie udzielenia zamówienia." (2024/BZP 00505219/01), "Wystąpienie okoliczności opisanych w piśmie Wykonawcy" (2026/BZP 00136753/01) |
| **R03** collisions, land access, property rights | 11 (7.3) | 18 (12.0) | "rzeczywista lokalizacja uzbrojenia podziemnego tj. sieci gazowej gD100 i sieci wodociągowej wD100 jest inna niż ta zaznaczona na mapie" (2021/BZP 00311955/01), "Rezygnacja z realizacji budowy kanalizacji sanitarnej w ul. Grottgera … w związku z brakiem zgody mieszkańców" (2024/BZP 00530518/01) |
| **R01** incomplete or inconsistent scope, documentation errors | 11 (7.3) | 14 (9.3) | "W zakresie PFU przyjęto wymianę instalacji i urządzeń nie planując wymiany sieci zewnętrznych pomiędzy SUW a zbiornikiem wody." (2025/BZP 00289058/01), "dodatkowe zbrojenie ścian i stropu zbiornika żelbetowego (zastosowanie większej ilości stali niż wynikająca z dokumentacji projektowej)" (2025/BZP 00459828/01) |
| **R04** decisions, permits, utility operators | 9 (6.0) | 15 (10.0) | "Przedłużająca się procedura administracyjna dot. wydania pozwolenia wodnoprawnego i w związku z tym wydania pozwolenia na budowę" (2025/BZP 00293936/01), "Brak odbioru wykonanego przyłącza energetycznego przez zarządcę sieci energetycznej." (2024/BZP 00481289/01) |
| **N-WEATHER** weather | 9 (6.0) | 11 (7.3) | "Wystąpiły kilkustopniowe mrozy, które nie pozwoliły na prowadzenie robót ziemnych i montażowych." (2024/BZP 00094668/01), "Brak możliwości wykonania robót odtworzeniowych nawierzchni bitumicznej w okresie zimowym z uwagi na panujące niskie temperatury" (2022/BZP 00174105/01) |
| **N-CLIENT** extension at the buyer's request | 6 (4.0) | 13 (8.7) | "postanowiono rozbudować instalację alarmową o monitoring dozorowy z wykorzystaniem kamer" (2025/BZP 00027416/01), "zaistniała potrzeba wykonania sieci światłowodowej (światłowodowy ring komunikacyjny) na terenie oczyszczalni ścieków" (2024/BZP 00255399/01) |
| **R12** contractor capacity, supply chain | 6 (4.0) | 9 (6.0) | "Udokumentowany brak dostaw materiałów niezbędnych do realizacji zamówienia z przyczyn niezależnych od wykonawcy" (2025/BZP 00627700/01), "złoże podlegające wymianie w ramach inwestycji, jest na rynku niedostępne" (2025/BZP 00450688/01) |
| **N-COVID** | 5 (3.3) | 6 (4.0) | "opóźnieniami w dostawie spowodowanymi COVID. Swój wniosek podparł pismami od dwóch dostawców." (2022/BZP 00481914/01), "Wzrost kosztu związanego z wykonaniem odtworzenia nawierzchni asfaltowej spowodowany wystąpieniem okoliczności związanych z obecnością COVID-19" (2022/BZP 00525506/01) |
| **R09** change of technical solution | 5 (3.3) | 8 (5.3) | "Konieczność zrealizowania projektu przy zastosowaniu innych rozwiązań technicznych/technologicznych niż wskazane w dokumentacji." (2022/BZP 00303247/01), "zmiana technologii wykonania przepompowni ścieków P2 tj podniesienie zbiornika ze względu na możliwość jego zalania wodą opadową" (2025/BZP 00419158/01) |
| **R08** payment model, remeasurement | 5 (3.3) | 8 (5.3) | "Rozliczenie końcowe budowy na podstawie obmiaru powykonawczego robót." (2023/BZP 00321355/01), "rozliczenia dokonanego zgodnie z obmiarem wykonanych robót i kosztorysem powykonawczym zatwierdzonym przez Zamawiającego" (2024/BZP 00611024/01) |
| **N-FORMAL** | 5 (3.3) | 5 (3.3) | "zmiana projektanta branża elektryczna" (2025/BZP 00602127/01), "Zmiana numerów działek, na których ma zostać wykonana inwestycja." (2025/BZP 00615912/01) |
| **R13** funding, budget | 4 (2.7) | 4 (2.7) | "Konieczność przesunięcia części środków finansowych na zadanie na kolejny rok" (2026/BZP 00292900/01), "w zależności od otrzymywanych środków z funduszy zewnętrznych lub innych wytycznych wynikających z zawartych umów o dofinansowanie" (2025/BZP 00419347/01) |
| **N-PRICE** war, inflation, prices | 2 (1.3) | 5 (3.3) | "trudność w zakupie przez Wykonawcę materiałów budowlanych (m.in. stal, nagrzewnice, komponenty do produkcji PP, PCV)" (2023/BZP 00255987/01), "Wykonawca wniósł wniosek o renegocjację wartości umowy" (2023/BZP 00105389/01) |
| **R10** testing, start-up, acceptance | 2 (1.3) | 5 (3.3) | "W trakcie prac rozruchowych oczyszczalni pojawiła się konieczność wykonania następujących robót" (2025/BZP 00158444/01), "Problem z uzyskaniem pozwoleń na użytkowanie" (2021/BZP 00250092/01) |
| **N-SCOPE-RED** | 2 (1.3) | 3 (2.0) | "Gmina Bałtów zmniejsza zakres robót do wykonania o odtworzenia nawierzchni asfaltowych" (2023/BZP 00008737/01), "zmniejszenia zakresu prac … w przypadku wystąpienia robót tzw. zaniechanych" (2024/BZP 00296600/01) |
| **R06** schedule and dependencies | 0 | 1 | "należało opróżnić reaktor ze ścieków a dopływające ścieki do oczyszczalni Użytkownik musi taborem asenizacyjnym wywozić na inną oczyszczalnię" (2024/BZP 00306175/01; works on an operating plant) |
| **N-LAW** | 0 | 1 | "Zmiana przepisów regulujących kwestie dotyczące zapisów umów dofinansowanych w ramach Rządowego Funduszu Polski Ład" (2022/BZP 00478248/01) |
| R11 procedure | 0 in sample | | found in the corpus: "Zawarcie umowy z Wykonawcą po upływie pierwotnego terminu związania ofertą"; "Odwołanie do KIO" |
| R15 effect not achieved | 0 in sample | | 7 matches in the corpus, e.g. "osiągnięciu niewystarczającego wskaźnika wybudowanych przyłączy sieci kanalizacji sanitarnej, które pozwoliłyby na osiągnięcie rezultatu efektu ekologicznego" |
| R05, R14 | 0 | | essentially absent from change notices; they belong in a document (SWZ/PFU/PPU) analysis instead |

**Readings:**

1. The most common physical root causes are **ground, groundwater and the condition of existing assets
   (R02)**, **utility collisions and land access (R03)**, **permits and utility operators, above all power
   connections and Wody Polskie water-law permits (R04)**, and **gaps in the documentation or PFU (R01)**.
   Together they are the primary cause in 33% of changes and appear, as primary or secondary label, in 39%.
2. A third of the reasons carry **no root cause** (R07 generic plus N-UNSPEC, 33%). The cause is then often
   in the "opis zmiany" field or in SEKCJA VI, so the LLM must read reason + description + VI together.
3. Weather is a common cause of deadline-only changes, especially under 455.1.1 and 455.1.4.

### 8.1 Cheap keyword pre-classifier

`change_keywords.py` is multi-label, scores reason + description, and was checked against the gold sample
(`out/keyword_vs_gold.csv`):

| category | precision | recall | use |
|---|---|---|---|
| N-COVID | 1.00 | 1.00 | reliable |
| N-WEATHER | 0.85 | 1.00 | reliable |
| R03 collisions and land | 0.87 | 0.72 | reliable |
| R02 ground and existing state | 0.82 | 0.56 | good precision |
| R12 supply | 1.00 | 0.44 | good precision |
| R13 funding | 0.75 | 0.75 | |
| R09 | 0.67 | 0.50 | |
| R04 permits | 0.50 | 0.80 | over-fires; needs an LLM |
| R07 additional works | 0.55 | 0.66 | |
| R08, N-SCOPE-RED, R06, R11 | ≤ 0.25 | | boilerplate words ("rozliczenie", "zaniechane", "harmonogram", "odwołanie") |
| R01, N-CLIENT | | 0.14, 0.15 | phrasing too varied; an LLM is needed |

Patterns that work, as word stems:

* groundwater and ground: `wod* gruntow*`, `igłofiltr*`, `warunk* gruntow*`, `kurzawk*`, `skał*`, `natrafion*`, `niezinwentaryzowan*`, `okazał* się`
* collisions and land: `kolizj*`, `właściciel*`, `brak* zgody`, `wejści* w teren`, `służebnoś*`, `PKP`
* permits and operators: `pozwoleni* wodnoprawn*`, `Wody Polskie`, `zgłoszeni* wodnoprawn*`, `przyłącz* energet*`, `PGE/Tauron/Enea/Energa`, `zarządc* drogi`
* weather: `atmosferyczn*`, `mroz*`, `niskich temperatur`, `opad* deszczu`
* COVID: `covid`, `art. 15r`
* supply: `dostaw* materiał*`, `niedostępn*`, `producent*`

**Suggested flow:**

1. Keywords for COVID, WEATHER, R03, R02 and R12: accept, show to the expert pre-labelled.
2. LLM for the rest, the about 24% with no keyword hit, and every R07/N-UNSPEC case. Pass reason +
   description + SEKCJA VI.
3. Use the 150 gold texts as few-shot examples and as a regression test.

Corpus-wide keyword frequencies by source and basis: `out/change_keyword_freq.csv`. These are rough, use the
precision column above.

---

## 9. Recommendations

### 9.1 Normalised schema to store

Store every row with **source notice number + field code + objectId + publication date**, so each value
traces to its source. For example: `contract.value_award ← TR 2024/BZP 00472360/01 §8.2`.

* **notice** (all types): objectId, noticeType, noticeNumber, bzpNumber, version, tenderId,
  publicationDate, buyer (name, NIP from the record, REGON from 1.3/1.4, province, city), orderType, cpv_main,
  cpv_additional[], isBelowEU, title, short_description, raw_fields (JSON of code → value with lot),
  section_texts, url (`https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/<objectId>`),
  `fetched_at`.
* **procedure** (tenderId): first CN, procedure mode (tryb), EU flag + project name, lots count, estimated
  value net (CN 4.1.5 / TR 4.3), planned duration per lot (CN 4.2.10), change clauses text (CN 7.4),
  cancellations (TR 5.1 / 5.2 / 5.2.1 per lot) with the art. 255 point.
* **lot / award** (TR row): part, outcome, n_offers, n_SME, n_rejected, min / max / winning offer, contractor
  (name, NIP, size), contract_date, value_award (8.2), duration_award (8.3) → planned_end_award,
  subcontracting.
* **contract** (CP, one per notice): link to lot (TR number + NIP), contract_date, planned duration (CP 4.2
  raw + parsed), value_cp (4.4), executed (5.1), exec_date (5.2), on_time_declared (5.3), n_changes (5.4.1),
  paid (5.5), properly_performed (5.6), section VI text. **Derived:** planned_end = TR 8.3 else CP 4.2; delay
  (raw and reconciled); cost_dev vs TR 8.2 else CP 4.4; the quality flags from §6.
* **contract_change**: one row per AU notice **and** per CP 5.4.x block (dedupe where an AU and a CP block
  describe the same change), with date (AU 5.1), basis (455.x.y), reason text, description text, value,
  price_increase, extension_days (parsed), what_changed {time, price, scope}, keyword categories, and later
  LLM category + expert decision.
* **classification**: relevance, subsector main + additional, scope_kind, work_type, design_build, each
  with `why` (the keyword that matched), so the expert can override it.

### 9.2 Which statistics can be shown to a jury

Solid:

* The **share late** (declared 5.3), the **share with at least 1 change** (5.4.1) and the **share paid
  above value**. These are declared directly in the form and almost complete (≥ 99.8%).
* **Delay magnitude for late contracts** (median and P90 days), computed from 5.2 − planned end and
  reconciled with 5.3. Show it as a range, not a point.
* **Cost deviation quantiles** (P75, P90). The median is 0% because of lump-sum contracts. Present it as "x%
  of contracts went over; among those the typical overrun is y%", not as a mean.
* The **size gradient** (value bucket) and the **subsector differences**. They are large, monotonic and
  stable under bootstrap.

Show with caveats:

* Year comparisons (censoring).
* EU and design-and-build effects (confounded; show them within a size bucket).
* Regions (n = 225–1,698; differences of about 10 pp are within 2–3 SE of each other at n of about 300).
* Unit costs (length parsing).

Do not show:

* Means of cost deviation without trimming.
* Plain sums of contract value without the scale-error filter.
* AU-only change statistics presented as "all changes".

### 9.3 Minimum n per reference class

From a bootstrap on the core set (`out/min_n_bootstrap.csv`; 90% interval of the estimate):

| n | share late (true 30%) | P90 of delay % (true 45%) | P90 of cost dev % (true 6.9%) |
|---|---|---|---|
| 10 | 10–50% | 0.7–115 | 0–16 |
| 20 | 15–45% | 7–91 | 0.1–15.7 |
| 30 | 17–43% | 12–83 | 0.3–14.5 |
| 50 | 20–42% | 20–77 | 1.3–12.9 |
| 100 | width about 20 pp | width 41 | width 8 |

**Recommendation:**

* **n ≥ 30** to show a class share (late, changes) and the median, with a bootstrap 90% interval.
* **n ≥ 50** (better ≥ 100) before showing P80/P90 bands.
* Below that, **back off hierarchically**: subsector × value bucket (× work type or design-and-build) →
  subsector × value → subsector → all wod-kan. Say which level was used and show n. Subsector × value buckets
  meet n ≥ 30 everywhere except WOD > 10 mln (38, OK), DESZ 2.5–5 / 5–10 / > 10 mln (47 / 34 / 23) and SUW
  > 10 mln (18). Merge the top buckets for DESZ and SUW.

---

## 10. Wow-feature feasibility

### 10.1 Unit-cost benchmark (PLN per km)

* **Method** (`07_wow_features.lengths()`):
  * regex `(\d+(?:[ ,.]\d+)?)\s*(km|mb|m.b.|m)` on title + short description (CP 3.8)
  * ignores mm, m², m³ and "m n.p.m.", plus depth, width and diameter contexts (głębokość, szerokość, średnica …)
  * a mention is a connection length (przyłącze, podłączenie, przykanalik, sięgacz) if that word occurs in
    the 60 characters before it
  * network length = an explicit total ("łączna długość") if present, otherwise the sum of segments
* **Coverage** (some length found / a network length found), core wod-kan contracts:

  | subsector | some length | network length |
  |---|---|---|
  | WOD | 54% | 53% |
  | SAN | 48% | 47% |
  | DESZ | 31% | 31% |
  | SUW | 12% | |
  | OCZ | 9% | |
  | all core | 42% | 42% |
* **PLN per km** = contract value (gross) / network length. Kept: 0.1–100 km and 50k–20 mln PLN/km.
  Medians by contract year:

  | contract year | SAN P50 (mln PLN/km) | WOD P50 (mln PLN/km) |
  |---|---|---|
  | 2021 | 0.72 | 0.37 |
  | 2022 | **1.02** | 0.41 |
  | 2023 | 0.96 | 0.42 |
  | 2024 | 0.89 | 0.45 |
  | 2025 | 0.90 | 0.35 |
  | 2026 | 0.70 | 0.36 |
  | all years | 0.89 (P25–P75 0.54–1.48; n = 1,734) | 0.39 (0.25–0.75; n = 1,881) |

  The inflation shock shows: **+41% for sanitary sewer from 2021 to 2022.**
* **Pitfalls:**
  * The value covers connections, pumping stations and road restoration, so this is cost per km of
    "project", not of pipe.
  * Segment lists are sometimes double counted ("w tym…").
  * Connection-only contracts ("108 podłączeń o łącznej długości 2064 mb") must be excluded or tagged.
  * Gravity vs pressure sewer and diameter are not separated.
  * The description field in CP is cut off in some notices.
* **Use it** as an "orders of magnitude" check with P25–P75, not as a cost estimate.
* Data: `data/unit_cost_contracts.csv.gz`, `out/wow_unit_cost_pln_per_km.csv`.

### 10.2 Competition signal

Fields available in the TR:

| field | filled |
|---|---|
| number of offers (6.1) | 91% |
| lowest / highest price (6.2 / 6.3) | 87% |
| winning price (6.4) | 78% |
| contract value (8.2) | 78% |
| **net estimate (4.3 / 4.3.1 / 4.5.5)** | **64%** |

The amount the buyer intended to spend is **not** in the BZP forms; it is on the buying platform. Proxy:
estimate × 1.23.

Linked CP ↔ TR for 10,381 of 11,237 core contracts (`out/wow_competition_vs_outcomes.csv`). Restricted to
1–5 mln to control for size:

| offers | n | late % | ≥1 change % | paid > value % | cost P90 % |
|---|---|---|---|---|---|
| 1 | 481 | **43.8** | 54.1 | 22.2 | 5.2 |
| 2 | 490 | 41.0 | 52.7 | 26.7 | 9.2 |
| 3–4 | 879 | 40.6 | 57.0 | 29.4 | 8.9 |
| 5–7 | 776 | 40.5 | 55.9 | 28.7 | 9.8 |
| 8+ | 421 | **34.9** | 55.8 | **34.7** | **12.1** |

| award vs estimate (single-lot) | n | late % | paid > value % | cost P90 % |
|---|---|---|---|---|
| < 60% | 131 | 32.1 | 27.5 | 10.2 |
| 60–80% | 279 | 40.9 | 31.5 | 13.1 |
| 80–95% | 281 | 45.2 | 31.3 | 9.2 |
| 95–105% | 257 | 42.7 | 26.8 | 7.0 |
| > 105% | 220 | 45.9 | 26.8 | 6.5 |

**Reading:** the effects are weak.

* **More bidders**: fewer late contracts (−9 pp) but **more and larger cost overruns** (+12 pp share, P90
  5% → 12%). This fits the pattern "aggressive price, then recovery through changes".
* **Single bidder**: the most delays, but the fewest overruns.
* A **deep discount** below 80% of the estimate goes with the highest cost P90 (13%).
* Present this as a risk flag ("8+ bidders and award < 80% of the estimate → cost overrun risk above
  average"), not as a strong predictor.

**Market-cooling signal** (core wod-kan tender lots, `out/wow_cancellations_by_year.csv`):

| year | cancelled | cancelled, price above budget (art. 255 pkt 3) | single offer | median offers |
|---|---|---|---|---|
| 2021 | 27% | 15% | 24% | 2 |
| 2022 | **33%** | **20%** | 25% | 2 |
| 2023 | 27% | 18% | 18% | 3 |
| 2024 | 20% | 12% | 13% | 4 |
| 2025 | 15% | 8% | 12% | 4 |
| 2026 | 14% | 7% | **8.5%** | **6** |

### 10.3 Ongoing contracts and an early-warning radar

From `out/wow_ongoing_radar.csv` and `data/radar_open_contracts.csv.gz`, core wod-kan awarded lots (TR
rows with a contract date):

| | count |
|---|---|
| Awarded | 15,812 |
| With a matched performance notice | 10,939 (69%) |
| **Without one** | **4,873** (4,574 with no CP at all in the whole procedure) |
| …planned end still in the future | 1,138 (genuinely ongoing) |
| …planned end passed by 0–90 days | 414 (expected: the notice is due within 30 days) |
| …planned end passed by 91–365 days | **627** (likely delayed) |
| …planned end passed by more than 365 days | **2,694** (very late, terminated, or never reported) |
| …with at least one AU change notice | 253; 234 of them are past their planned end |

The reporting rate is stable at 70–77% for contracts signed 2021–2025. About 25% of contracts never get a
CP notice, so do not treat a missing CP as evidence of delay.

**Radar logic:**

* *amber*: past planned end, no CP, no AU
* *red*: past planned end and has an AU 455.1.4 or 455.1.3
* *new event*: any AU or CP notice published for a tenderId on the watch-list

A live-API check by tenderId is cheap, about 1 call per watched procedure. The 234 "past end + change
notice" contracts are a ready demo list.

### 10.4 Backtest of the reference-class bands

`out/wow_backtest*.csv`. Train on core contracts completed before 2024-01-01 (n of about 4,500); test on
those completed 2024 to 2026-11 (n of about 6,100–6,300). Predict P10–P90 per subsector × value bucket,
falling back to the subsector-wide or global band when n < 30.

| metric | outcomes inside P10–P90 (target 80%) | above P90 (target 10%) | at or below P80 (target 80%) | pinball loss P90 vs global |
|---|---|---|---|---|
| delay days (reconciled) | 85% | 15% | 76% | **−7.6%** (16.9 vs 18.3) |
| delay % of planned | 88% | 12% | 77% | ≈ global |
| cost deviation % | 80% | 13% | 80% | −3.4% |

Share late as a probability:

* Brier score 0.217 by subsector × value, against 0.228 for the global rate.
* Calibration is monotonic but low by about 5 pp: predicted 17 / 26 / 35 / 44% against observed 20 / 36 /
  40 / 47%. The mean is predicted at 27%, observed at 33%.

The cause is that the training set (finished before 2024) under-represents long, delayed contracts. **Fix:**

* Build classes from planned-end cohorts with enough follow-up, or use survival or Kaplan–Meier estimation
  for "time to completion".
* Report "≥ x% late (lower bound, censored)".

Even so, the bands are roughly calibrated and conditioning on subsector × value beats a single global band
on the tails. This makes a good honest slide: "we checked our forecasts on 6,000 contracts finished later".

### 10.5 Pitch numbers

Core wod-kan, executed. Full tables in `out/wow_pitch_*.csv`.

* **11,184 completed contracts** worth **20.7 bn PLN** (rows passing quality checks); **21.2 bn PLN paid**.
* **+582 mln PLN** paid above contract values (sum of overruns; net of underruns: +482 mln PLN, +2.3%).
  Across all completed works in the copy: +2.7 bn PLN on 68 bn PLN.
* **30%** finished late. In total **261,000 days of delay** (about 716 years). Median delay when late is
  **58 days**, P90 188 days.
* **41%** had at least 1 contract change. **Top causes** (gold sample, primary label):
  1. existing conditions (ground, groundwater, condition of existing assets), 13%
  2. collisions and land access, 7%
  3. permits and utility operators, 6%

  Weather is also 6%; generic "additional works" with no cause given is 22%.
* By year signed:

  | year signed | late % | ≥1 change % | paid > value % |
  |---|---|---|---|
  | 2021 | 35 | 42 | 22 |
  | 2022 | 30 | 42 | 21 |
  | 2023 | 31 | 43 | 23 |
  | 2024 | 28 | 42 | 23 |

  The 2022 shock is clearest in **33% cancelled tenders (20% because the price was above budget)** and in
  **+41% sewer cost per km**, not in completed contracts.
* By completion year, the late share rises from 20% (2021) to 32% (2025) and 42% (2026 so far), because
  delayed 2021–23 contracts are finishing now.
* By province (late %): lowest kujawsko-pomorskie 23% and podkarpackie 24%; highest lubuskie 43% and
  dolnośląskie 40%. See `out/wow_pitch_by_province.csv` (TERYT codes PL02…PL32) for a choropleth.
