# Raport z testu źródeł: Risk Miner

_Wygenerowano automatycznie: 2026-11-21 17:31 UTC (`uv run riskminer report`). Dane: manifesty `data/raw/*/manifest.jsonl` i baza (tabele `source`, `ingestion_run`, `source_check`, `link_candidate`, `review_item`)._

## 1. Podsumowanie per źródło

| Źródło | Zapytania | Pobrane OK | Puste | Zablokowane | Błędy | Rekordy w bazie | Sprawdzenia | Ostatni przebieg | Licencja | Lokalizacja |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| Zestaw organizatora (XLSX, 22 projekty) (`xlsx`) | 1 | 1 | 0 | 0 | 0 | 22 | - | 2026-11-21 11:58 UTC | organizer dataset (HackNation 2026, MFiPR) | `materials/starter/Risk_Miner_dane_projekty.xlsx` |
| BZP: kopia krajowa organizatora (`bzp_copy`) | 1 | 1 | 0 | 0 | 0 | 113278 | - | 2026-11-12 11:55 UTC | public information (organizer copy of the BZP API, records unchanged) | `materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl` |
| BZP: API e-Zamówienia (delta na żywo) (`bzp_api`) | 443 | 384 | 57 | 0 | 2 | 1077 | found=22 | 2026-11-21 13:26:10 UTC | public information | `data/raw/bzp_api/` |
| Biała lista VAT (`vat_whitelist`) | 9 | 9 | 0 | 0 | 0 | 234 | found=234;not_found=2 | 2026-11-21 13:01:54 UTC | public register | `data/raw/vat_whitelist/` |
| TERYT (TERC) (`teryt`) | 399 | 399 | 0 | 0 | 0 | 4360 | - | 2026-11-21 12:02:25 UTC | public (GUS TERYT) | `data/raw/teryt/` |
| Granice administracyjne (GeoJSON) (`geo`) | 35 | 35 | 0 | 0 | 0 | 2875 | - | 2026-11-21 12:00:26 UTC | public (PRG GUGiK); see note for mirror licence | `data/raw/geo/` |
| Mapa Dotacji: KPO B3.1.1 (`mapa_dotacji`) | 695 | 695 | 0 | 0 | 0 | 631 | found=24;not_found=6 | 2026-11-21 12:35:38 UTC | public; attribution (mapadotacji.gov.pl) | `data/raw/mapa_dotacji/` |
| TED (UE) (`ted`) | 7380 | 7380 | 0 | 0 | 0 | 18325 | found=2;not_found=40 | 2026-11-21 14:00:39 UTC | EU reuse (Decision 2011/833/EU) | `data/raw/ted/` |
| Orzeczenia KIO (`kio`) | 6608 | 6608 | 0 | 0 | 0 | 2084 | found=17;not_found=25 | 2026-11-21 13:17:02 UTC | public; natural persons pseudonymised by KIO | `data/raw/kio/` |
| Wyniki kontroli NIK (`nik`) | 1067 | 1062 | 0 | 0 | 5 | 522 | found=1;not_found=21 | 2026-11-21 12:39:12 UTC | public information | `data/raw/nik/` |
| Centralny Rejestr Umów (`cru`) | 3095 | 3093 | 0 | 2 | 0 | 16982 | found=25;not_found=9;partial=8 | 2026-11-21 17:31:42 UTC | public (art. 34a u.f.p.) | `data/raw/cru/` |
| Dokumenty postępowań (22) (`docs_22`) | 2687 | 2259 | 0 | 417 | 11 | 1138 | found=6;partial=16 | 2026-11-21 17:05:41 UTC | public information | `data/raw/docs_22/` |
| Dokumenty: próba krajowa (`docs_sample`) | 19819 | 19761 | 14 | 37 | 7 | 9403 | found=31;not_found=1;partial=173 | 2026-11-21 13:17:39 UTC | public information | `data/raw/docs_sample/` |
| KPOŚK (`kposk`) | 6 | 6 | 0 | 0 | 0 | 15950 | - | 2026-11-21 12:38:54 UTC | CC BY 4.0 | `data/raw/kposk/` |
| GUS BDL (`gus_bdl`) | 455 | 449 | 0 | 0 | 6 | 289873 | - | 2026-11-21 14:42:11 UTC | GUS open data, attribution | `data/raw/gus_bdl/` |
| GUS: wskaźnik cen (`gus_price_index`) | 4 | 4 | 0 | 0 | 0 | 671 | - | 2026-11-21 12:47:54 UTC | GUS open data, attribution | `data/raw/gus_price_index/` |
| Lista projektów FE (`fe_projects`) | 2 | 2 | 0 | 0 | 0 | 2350 | found=12;not_found=8 | 2026-11-21 12:43:30 UTC | public | `data/raw/fe_projects/` |
| NFOŚiGW (`nfosigw`) | 8 | 8 | 0 | 0 | 0 | 126 | - | 2026-11-21 12:49:03 UTC | CC0 | `data/raw/nfosigw/` |
| BIP (22 gminy) (`bip_22`) | 1912 | 1799 | 2 | 0 | 111 | 78 | blocked=3;found=9;not_found=9;partial=1 | 2026-11-21 13:23:40 UTC | public information | `data/raw/bip_22/` |
| GUS BIR (REGON) (`gus_bir`) | 81 | 81 | 0 | 0 | 0 | 38 | found=37;not_found=3 | 2026-11-21 12:53:27 UTC | public register | `data/raw/gus_bir/` |
| KRS (`krs`) | 215 | 108 | 0 | 107 | 0 | 107 | found=107 | 2026-11-21 14:11:07 UTC | public register | `data/raw/krs/` |
| Baza Konkurencyjności (`bk2021`) | 130 | 130 | 0 | 0 | 0 | 110 | found=16;not_found=4 | 2026-11-21 13:05:37 UTC | public; contact persons dropped | `data/raw/bk2021/` |
| BZP: drogi (pakiet W9) (`bzp_roads`) | 418 | 418 | 0 | 0 | 0 | 134287 | found=20 | 2026-11-21 15:20:43 UTC | public information | `data/raw/bzp_roads/` |

Rodzaje rekordów: `vat_whitelist`: vat_entity=234; `teryt`: teryt_unit=4360; `geo`: admin_boundary=2875; `mapa_dotacji`: kpo_project=631; `ted`: ted_notice=18325; `kio`: kio_ruling=2084; `nik`: nik_audit=80; `cru`: cru_agreement=16982; `kposk`: kposk_agglomeration=7694;kposk_wwtp=8256; `gus_bdl`: bdl_value=289873; `gus_price_index`: price_index=671; `fe_projects`: fe_project=2350; `nfosigw`: nfosigw_grant=126; `gus_bir`: bir_entity=38; `krs`: krs_entity=107; `bk2021`: bk_announcement=110

## 2. Baza przypadków z BZP (krajowo)

- Ogłoszenia: **248 642** (najnowsze wersje: 248 250; zastąpione wersje: 392)
- Postępowania (OCID): **101 016**; części: 112 733; umowy: 128 051; ogłoszenia o wykonaniu: 68 755 (w tym 694 ponownie opublikowanych dla tej samej umowy); zmiany umów: 60 293; organizacje: 18 641; dowody (pola formularzy): 860 189
- Sektory: `drogi`: 55 669 postępowań, 133 773 ogłoszeń; `wod-kan`: 45 347 postępowań, 114 477 ogłoszeń (pakiet `drogi` = wycinek BZP CPV 45233* 2024–2026 do demonstracji „nowy sektor w 60 s”; liczby poniżej dotyczą wod-kan)
- Trafność wod-kan (klasyfikator na poziomie postępowania): component: 9 945, core: 18 689, cpv_only: 42, none: 16 671
- Klasa referencyjna `rc_contract` (core, roboty, wykonane, bez duplikatów): n = **11 210**; po terminie (pole 5.3 = Nie): 3 397 (30.3%); wypłata > wartość umowy o >0,5%: 2 437

## 3. Projekty pilotażowe (22)

| Projekt | Powiązanie BZP (metoda, pewność) | Łańcuch (ogł./umowy/wyk./zmiany) | Wzorzec | Mapa Dotacji | TED | KIO | CRU | Biała lista | API na żywo | Dokumenty | Rozbieżności |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RM-2026-001 Gmina Oława | exact_id (1.00) `2022/BZP 00058537` | 3/1/1/6 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/68) 2026-11-21 | szukano, brak (0/51) 2026-11-21 | znaleziono (33/391) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 77 pobr.; not_applicable: 1 | - |
| RM-2026-002 Gmina Zagrodno | fuzzy (1.00) `2026/BZP 00089794` | 5/1/2/2 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/23) 2026-11-21 | szukano, brak (0/4) 2026-11-21 | częściowo (3/0) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (5/5) 2026-11-21 | 15 pobr.; not_applicable: 1, not_in_package: 2 | - |
| RM-2026-003 Gmina Czernikowo | exact_id (1.00) `2024/BZP 00349631` | 5/1/1/5 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (0/29) 2026-11-21 | szukano, brak (0/2) 2026-11-21 | szukano, brak (0/42) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (5/5) 2026-11-21 | 35 pobr.; not_applicable: 2, not_in_package: 1 | - |
| RM-2026-004 Gmina Czernikowo | exact_id (1.00) `2025/BZP 00569258` | 4/1/1/4 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (0/29) 2026-11-21 | szukano, brak (0/2) 2026-11-21 | szukano, brak (0/42) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (4/4) 2026-11-21 | 53 pobr.; not_applicable: 1 | - |
| RM-2026-005 Gmina Zławieś Wielka | fuzzy (1.00) `2025/BZP 00245492` | 9/1/1/1 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/32) 2026-11-21 | szukano, brak (0/0) 2026-11-21 | znaleziono (3/125) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (9/9) 2026-11-21 | 38 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-006 Gmina Gościeradów | exact_id (1.00) `2024/BZP 00067908` | 5/1/1/4 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/17) 2026-11-21 | szukano, brak (0/1) 2026-11-21 | szukano, brak (0/1) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (5/5) 2026-11-21 | 56 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-007 Gmina Kamionka | fuzzy (1.00) `2026/BZP 00139226` | 5/1/1/0 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/38) 2026-11-21 | szukano, brak (0/24) 2026-11-21 | znaleziono (5/43) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 25 pobr.; not_applicable: 1, not_in_package: 2 | value_deviation |
| RM-2026-008 Gmina Biecz | exact_id (1.00) `2026/BZP 00084760` | 7/4/4/2 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/60) 2026-11-21 | szukano, brak (0/11) 2026-11-21 | częściowo (3/0) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (6/6) 2026-11-21 | 64 pobr.; not_applicable: 1, not_in_package: 1 | part_scope_wider; value_deviation |
| RM-2026-009 Gmina Zakrzew | exact_id (1.00) `2025/BZP 00307948` | 6/2/2/2 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/33) 2026-11-21 | szukano, brak (0/14) 2026-11-21 | znaleziono (2/121) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (4/4) 2026-11-21 | 66 pobr.; not_applicable: 1, not_in_package: 1 | part_mismatch |
| RM-2026-010 Gmina Grodzisko Dolne | fuzzy (1.00) `2025/BZP 00211437` | 3/1/1/1 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/27) 2026-11-21 | szukano, brak (0/8) 2026-11-21 | częściowo (5/0) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 40 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-011 Gmina Sanok | exact_id (1.00) `2023/BZP 00271948` | 4/1/1/1 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (0/50) 2026-11-21 | szukano, brak (0/36) 2026-11-21 | znaleziono (3/19) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (4/4) 2026-11-21 | 91 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-012 Gmina Kartuzy – Urząd Miejski w Kartuzach | exact_id (1.00) `2025/BZP 00119683` | 3/1/1/2 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (0/77) 2026-11-21 | szukano, brak (0/28) 2026-11-21 | znaleziono (7/266) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 22 pobr.; not_applicable: 1, not_in_package: 2 | - |
| RM-2026-013 Gmina Bestwina | exact_id (1.00) `2023/BZP 00206497` | 5/1/1/2 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (0/55) 2026-11-21 | szukano, brak (0/3) 2026-11-21 | znaleziono (4/56) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (5/5) 2026-11-21 | 30 pobr.; not_applicable: 2 | - |
| RM-2026-014 Gmina Bobrowniki | exact_id (1.00) `2026/BZP 00130634` | 3/1/1/2 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/13) 2026-11-21 | szukano, brak (0/16) 2026-11-21 | znaleziono (1/196) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 43 pobr.; not_applicable: 1 | value_deviation |
| RM-2026-015 Gmina Elbląg | exact_id (1.00) `2023/BZP 00135041` | 6/1/1/4 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/29) 2026-11-21 | szukano, brak (0/89) 2026-11-21 | znaleziono (8/183) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (6/6) 2026-11-21 | 25 pobr.; not_applicable: 3, not_in_package: 1 | - |
| RM-2026-016 Gmina Miłakowo | exact_id (1.00) `2022/BZP 00308854` | 3/1/1/2 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/15) 2026-11-21 | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/18) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 21 pobr.; not_applicable: 3 | - |
| RM-2026-017 Gmina Kleszczewo | fuzzy (1.00) `2025/BZP 00358528` | 9/1/1/1 | ✔ zgodne | znaleziono (1.00) | szukano, brak (22/126) 2026-11-21 | szukano, brak (0/7) 2026-11-21 | częściowo (4/0) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 37 pobr.; not_applicable: 1, not_in_package: 2 | - |
| RM-2026-018 Gmina Zduny | fuzzy (1.00) `2025/BZP 00620692` | 3/1/1/1 | ✔ zgodne | znaleziono (1.00) | szukano, brak (0/32) 2026-11-21 | szukano, brak (0/12) 2026-11-21 | szukano, brak (0/71) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 26 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-019 Wielkopolski Zarząd Dróg Wojewódzkich w Poznaniu | exact_id (1.00) `2024/BZP 00354928` | 3/1/1/6 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/367) 2026-11-21 | szukano, brak (0/119) 2026-11-21 | znaleziono (30/620) 2026-11-21 | szukano, brak (0/0) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 42 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-020 Gmina Nowogard | fuzzy (1.00) `2025/BZP 00113651` | 9/1/1/4 | ✔ zgodne | znaleziono (1.00) | szukano, brak (3/60) 2026-11-21 | szukano, brak (0/16) 2026-11-21 | znaleziono (7/127) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (9/9) 2026-11-21 | 83 pobr.; not_applicable: 1, not_in_package: 1 | - |
| RM-2026-021 Gmina Nowogard | exact_id (1.00) `2025/BZP 00364116` | 6/1/1/2 | ✔ zgodne | znaleziono (1/1) 2026-11-21 | szukano, brak (3/60) 2026-11-21 | szukano, brak (0/16) 2026-11-21 | znaleziono (7/127) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (4/4) 2026-11-21 | 172 pobr.; not_in_package: 1 | - |
| RM-2026-022 Gmina Wolin | cross_reference (0.95) `2023/BZP 00110672` | 5/2/2/5 | ✔ zgodne | szukano, brak (0/0) 2026-11-21 | szukano, brak (0/27) 2026-11-21 | szukano, brak (0/12) 2026-11-21 | znaleziono (1/168) 2026-11-21 | znaleziono (1/1) 2026-11-21 | znaleziono (3/3) 2026-11-21 | 108 pobr.; not_applicable: 1 | contract_notice_missing |

### Rozbieżności wykryte w zestawie organizatora

- **RM-2026-007** (wiersz 7): Wartość przedsięwzięcia 3 096 863,90 zł odbiega od kwot z BZP (najbliższa: suma wartości umów 1 478 460,00 zł, -52,3%)
- **RM-2026-008** (wiersz 8): Zestaw wskazuje część 1, ale opis przedsięwzięcia obejmuje części [1, 2, 3, 4]
- **RM-2026-008** (wiersz 8): Wartość przedsięwzięcia 6 188 345,13 zł odbiega od kwot z BZP (najbliższa: suma wypłat 4 955 056,04 zł, -19,9%)
- **RM-2026-009** (wiersz 9): Zestaw wskazuje część 2, ale opis przedsięwzięcia odpowiada części [1] (wyróżniające słowa: [['100', '237', '435', '445']])
- **RM-2026-014** (wiersz 14): Wartość przedsięwzięcia 1 714 989,00 zł odbiega od kwot z BZP (najbliższa: suma wypłat 1 294 007,90 zł, -24,5%)
- **RM-2026-022** (wiersz 22): Ogłoszenie 2023/BZP 00110672 nie występuje w źródle (BZP); 3 późniejsze ogłoszenia zamawiającego powołują ten numer (postępowanie ocds-148610-f193152b-b443-11ed-9236-36fed59ea7dd)

## 4. Jakość powiązań

- Metody powiązania 22 projektów: exact_id: 14, cross_reference: 1, fuzzy: 7
- Względem zbioru wzorcowego (research/bzp_linking, 22/22 zweryfikowane ręcznie): poprawne **22**, błędne 0, niesprawdzone 0.
- Po przeglądzie eksperta: zatwierdzone 0, odrzucone 0 (kolumna `review_status` w `link_candidate`).
- Progi: automatyczna akceptacja ≥ 0,90; do przeglądu 0,60–0,90; odrzucenie < 0,60 (powiązania rozmyte pokazują cechy i wynik).

### 4a. Powiązania krajowe (etap `link_national`)

**Projekty KPO B3.1.1 (Mapa Dotacji) a postępowania BZP.** Rekordów: 630 (pominięto 1 wpis zbiorczy programu). Mapa Dotacji nie podaje numeru KPO ani NIP, więc beneficjenta przypisujemy do zamawiającego z BZP po nazwie gminy, jej rodzaju z TERYT (miejska, wiejska, miejsko-wiejska) i województwie, a spółki komunalne po podobnej nazwie i siedzibie w powiecie. Beneficjent rozpoznany: 590, nierozpoznany: 40 (głównie spółki, które nie ogłaszają zamówień w BZP). Projekty z kandydatem: 578. Najlepszy kandydat: akceptacja automatyczna 296, do przeglądu 179, odrzucony 103; kwota KPO równa kwocie z BZP co do grosza: 82. Zapisano 1647 kandydatów (do 3 na projekt), każdy z cechami i uzasadnieniem.

**Kontrola na parach referencyjnych.** 10 projektów pilotażowych z numerem KPO ma znany rekord Mapy Dotacji i postępowanie BZP (etap `link_pilot`). Pary nie są cechą wejściową, służą wyłącznie do oceny. Beneficjent przypisany do właściwego NIP: 10/10. Właściwe postępowanie na 1. miejscu: 10/10 (precyzja@1 100,0%), w pierwszej trójce: 10/10 (czułość@3 100,0%). Akceptacje automatyczne dla tych projektów: 7, w tym poprawne 7 (precyzja 100,0%); właściwe postępowanie w kolejce do przeglądu eksperta: 3.

**Umowy z Centralnego Rejestru Umów (od 1.07.2026) a umowy z BZP.** Umów CRU: 16982. Zamawiający rozpoznany po NIP: 4347, po numerze REGON z ogłoszeń BZP: 8153, nierozpoznany: 4482. Dla 6446 umów CRU zamawiający ma w BZP umowę zawartą w oknie ±45 dni (większość pozostałych to umowy poniżej progu stosowania ustawy). Najlepszy kandydat: akceptacja automatyczna 462, do przeglądu 52, odrzucony 7. Wartość z CRU zgadza się z wartością brutto z BZP po doliczeniu 23% VAT w 85,9% zaakceptowanych par, czyli CRU podaje zwykle kwoty netto. Umowy CRU z aneksami lub innymi zmianami: 500, z czego powiązane z umową z BZP automatycznie 38 i do przeglądu 18 (aneksy TSU02: 225, powiązane automatycznie 9, do przeglądu 15). Spośród zaakceptowanych ogłoszenie o zmianie umowy w BZP ma tylko: 4, więc CRU uzupełnia moduł monitorowania o zmiany niewidoczne w BZP.

Progi: akceptacja automatyczna od 0,90 (nadal podlega przeglądowi eksperta), przegląd od 0,60 do 0,90, odrzucenie poniżej 0,60. Wiersze zatwierdzone, poprawione lub odrzucone przez eksperta nie są nadpisywane.

## 4b. Tekst dokumentów i wyszukiwanie

- Dokumenty z tekstem w indeksie pełnotekstowym: 6 732; strony: 49 308; fragmenty (chunk): 182 381. Wyszukiwanie: `GET /api/search`.
- OCR (Tesseract, model pol, WCSS): dokumenty po OCR 0; skany bez warstwy tekstowej czekające na OCR: 3 200.

## 5. Ograniczenia i stany dowodowe

- „Szukano, nie znaleziono” jest zapisywane jawnie (`source_check`): brak wyniku ≠ brak zdarzenia.
- Dokumenty niedostępne mają stan: `not_in_package`, `blocked` (zabezpieczenie platformy, którego nie obchodzimy), `link_dead`, `not_applicable`.
- Wyjątek od robots.txt: platformazakupowa.pl i logintrade.net blokują w robots.txt pobieranie załączników. Za zgodą operatorów tych platform (zgłoszoną przez zespół 21.11.2026) pobieramy publiczne linki do załączników co 5 s; każde takie pobranie ma w manifeście notatkę `robots.txt override`. Pozostałe serwisy: robots.txt i Crawl-delay respektowane.
- Dane osobowe kontaktowe nie są kopiowane do tabel znormalizowanych ani eksportów (RODO).
