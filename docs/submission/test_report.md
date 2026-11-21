# Raport z testu: ex ante (Risk Miner)

HackNation 2026, wyzwanie MFiPR „Risk Miner”. Stan bazy i aplikacji na 21.11.2026 (wieczór). Wszystkie liczby poniżej odczytano z działającej bazy (zapytania tylko do odczytu), z punktów API albo z uruchomionych testów; przy każdej sekcji podajemy źródło. Brief (§6) prosi o „zestawienie poprawnych, niepewnych i błędnych połączeń między bazami oraz wyniki analizy nowego projektu”; układ raportu idzie za testami jury: integracji, łączenia, kompletności przypadku, nowej inwestycji, źródłowym, pracy eksperta i założeń.

## Podsumowanie

- **22 z 22 projektów pilotażowych** powiązanych z postępowaniem BZP: 14 po numerze ogłoszenia (exact_id), 7 dopasowaniem rozmytym po NIP, tytule, CPV i dacie (fuzzy), 1 przez ogłoszenia powołujące brakujący numer (cross_reference, Wolin). Względem zbioru wzorcowego: **22 poprawne, 0 błędnych, 0 niesprawdzonych**.
- **Powiązania krajowe między bazami: 3 589 kandydatów**, każdy z cechami i uzasadnieniem: 1 324 zaakceptowane automatycznie (wynik ≥ 0,90), 1 234 do przeglądu eksperta (0,60–0,90), 1 031 odrzucone (< 0,60). Na parach referencyjnych Mapa Dotacji ↔ BZP: precyzja@1 **10/10**.
- **10 rozbieżności w danych** wykrytych automatycznie (w tym 8 w zestawie organizatora: odchylenie wartości, niezgodność części, brak ogłoszenia o zamówieniu, różna liczba zmian) czeka w kolejce eksperta; nic nie jest poprawiane po cichu.
- **23 źródła** pobrane i przeładowywalne jednym poleceniem; w bazie 248 642 ogłoszenia BZP, 101 016 postępowań, 128 051 umów, 68 755 ogłoszeń o wykonaniu, 60 293 zmiany umów, 860 286 wierszy dowodów, 47 250 zarejestrowanych pobrań (`source`) z sumą SHA-256.
- **Test źródłowy:** 81 z 81 wniosków z próby (seed 2026) potwierdzonych cytatem lub polem źródła (78 dokładnie, 3 w przybliżeniu). Cytaty przy klasyfikacji przyczyn zmian AI na całej bazie: **96,4%** potwierdzonych (20 694 unikalne teksty przyczyn). Trafność kodów przyczyn na próbie wzorcowej 150: **80,0%** (przedział 73,3–86,0%) wobec 37,3% dla reguł słownikowych.
- **Sprawdzian wsteczny prognoz:** w przedziale P10–P90 mieści się 85,0% opóźnień w dniach, 87,7% opóźnień w % planu i 79,5% odchyleń kosztu; Brier 0,217 wobec 0,227 dla prognozy globalnej; odsetek opóźnionych zaniżony o ok. 6 pp.
- **Trzy dokumenty organizatora** (Zagrodno, Zławieś, Grodzisko ze skanem do OCR) przechodzą cały potok i spełniają wszystkie wartości wzorcowe: test G6 3/3.
- **Testy automatyczne:** backend 276 zaliczonych, 3 pominięte celowo (testy zapisujące do bazy); frontend 157 z 157 w 23 plikach.

Źródło: sekcje poniżej.

## Połączenia między bazami: poprawne, niepewne i błędne

### Projekty pilotażowe (22) a postępowania BZP

Metoda (`backend/riskminer/ingest/linking.py`, PLAN §6.1–6.3): najpierw identyfikator. Gdy zestaw podaje numer BZP, szukamy ogłoszenia o tym numerze (exact_id, pewność 1,0); gdy numeru nie ma w źródle, szukamy ogłoszeń tego samego zamawiającego, które go powołują (cross_reference, 0,95). Gdy jest tylko numer KPO, oceniamy postępowania zamawiającego o zgodnym NIP: podobieństwo słów tytułu i opisu, CPV wod-kan, data od 2024 r. (era KPO B3.1.1); wynik znormalizowany do 0..1. Każdy kandydat trafia do `link_candidate` z cechami i opisem, wybrany do `project_procedure`. Wynik porównujemy ze zbiorem wzorcowym `research/bzp_linking/chains.json` (22 łańcuchy sprawdzone ręcznie); werdykt zapisuje się w kolumnie `link_candidate.reference_verdict`.

| Metoda | Liczba | Status | Wzorzec: poprawne | błędne |
|---|---:|---|---:|---:|
| exact_id | 14 | auto | 14 | 0 |
| fuzzy | 7 | auto | 7 | 0 |
| cross_reference | 1 | auto | 1 | 0 |
| **Razem** | **22** | | **22** | **0** |

Kandydaci alternatywni: dla 7 projektów powiązanych rozmycie pozostali kandydaci z rankingu (wynik od 0,21) trafiają do kolejki eksperta jako niepewni: **36 otwartych pozycji** `review_item` rodzaju `link`. Najlepszy kandydat w każdym z tych 7 projektów ma wynik 1,00, a drugi najwyżej 0,722 (Grodzisko Dolne), więc wybór nie jest niejednoznaczny w sensie progu `ambiguous_link` (różnica ≤ 0,05). Jeden kandydat odrzucony (poniżej progu).

| Projekt | Metoda (pewność), numer BZP | Łańcuch: ogł./umowy/wyk./zmiany | Wzorzec | Alternatywy w kolejce | Rozbieżności wykryte |
|---|---|---|---|---:|---|
| RM-2026-001 Gmina Oława | exact_id (1,00) `2022/BZP 00058537` | 3/1/1/6 | poprawne | 0 | brak |
| RM-2026-002 Gmina Zagrodno | fuzzy (1,00) `2026/BZP 00089794` | 5/1/2/2 | poprawne | 5 | change_count_mismatch |
| RM-2026-003 Gmina Czernikowo (Steklin) | exact_id (1,00) `2024/BZP 00349631` | 5/1/1/5 | poprawne | 0 | brak |
| RM-2026-004 Gmina Czernikowo | exact_id (1,00) `2025/BZP 00569258` | 4/1/1/4 | poprawne | 0 | brak |
| RM-2026-005 Gmina Zławieś Wielka | fuzzy (1,00) `2025/BZP 00245492` | 9/1/1/1 | poprawne | 4 | brak |
| RM-2026-006 Gmina Gościeradów | exact_id (1,00) `2024/BZP 00067908` | 5/1/1/4 | poprawne | 0 | change_count_mismatch |
| RM-2026-007 Gmina Kamionka | fuzzy (1,00) `2026/BZP 00139226` | 5/1/1/0 | poprawne | 7 | value_deviation |
| RM-2026-008 Gmina Biecz | exact_id (1,00) `2026/BZP 00084760` | 7/4/4/2 | poprawne | 0 | part_scope_wider, value_deviation |
| RM-2026-009 Gmina Zakrzew | exact_id (1,00) `2025/BZP 00307948` | 6/2/2/2 | poprawne | 0 | part_mismatch |
| RM-2026-010 Gmina Grodzisko Dolne | fuzzy (1,00) `2025/BZP 00211437` | 3/1/1/1 | poprawne | 6 | brak |
| RM-2026-011 Gmina Sanok | exact_id (1,00) `2023/BZP 00271948` | 4/1/1/1 | poprawne | 0 | brak |
| RM-2026-012 Gmina Kartuzy, Urząd Miejski w Kartuzach | exact_id (1,00) `2025/BZP 00119683` | 3/1/1/2 | poprawne | 0 | brak |
| RM-2026-013 Gmina Bestwina | exact_id (1,00) `2023/BZP 00206497` | 5/1/1/2 | poprawne | 0 | brak |
| RM-2026-014 Gmina Bobrowniki | exact_id (1,00) `2026/BZP 00130634` | 3/1/1/2 | poprawne | 0 | value_deviation |
| RM-2026-015 Gmina Elbląg | exact_id (1,00) `2023/BZP 00135041` | 6/1/1/4 | poprawne | 0 | brak |
| RM-2026-016 Gmina Miłakowo | exact_id (1,00) `2022/BZP 00308854` | 3/1/1/2 | poprawne | 0 | brak |
| RM-2026-017 Gmina Kleszczewo | fuzzy (1,00) `2025/BZP 00358528` | 9/1/1/1 | poprawne | 4 | brak |
| RM-2026-018 Gmina Zduny | fuzzy (1,00) `2025/BZP 00620692` | 3/1/1/1 | poprawne | 4 | brak |
| RM-2026-019 Wielkopolski Zarząd Dróg Wojewódzkich w Poznaniu | exact_id (1,00) `2024/BZP 00354928` | 3/1/1/6 | poprawne | 0 | brak |
| RM-2026-020 Gmina Nowogard | fuzzy (1,00) `2025/BZP 00113651` | 9/1/1/4 | poprawne | 6 | brak |
| RM-2026-021 Gmina Nowogard | exact_id (1,00) `2025/BZP 00364116` | 6/1/1/2 | poprawne | 0 | brak |
| RM-2026-022 Gmina Wolin | cross_reference (0,95) `2023/BZP 00110672` | 5/2/2/5 | poprawne | 0 | contract_notice_missing |

Łańcuch liczy ogłoszenia, umowy, ogłoszenia o wykonaniu i zmiany umów (zmiany z ogłoszeń o zmianie i z listy zmian w ogłoszeniu o wykonaniu; duplikaty oznaczone `is_duplicate` nie wchodzą do statystyk).

### Powiązania krajowe między bazami

Etap `link_national` (`backend/riskminer/ingest/link_national.py`) łączy rejestry, które nie mają wspólnego identyfikatora. Progi te same co dla pilotów: akceptacja automatyczna od 0,90 (nadal widoczna i do zmiany przez eksperta), przegląd 0,60–0,90, odrzucenie poniżej 0,60. Gdy dwóch kandydatów ma podobny wynik albo jedna umowa BZP pasuje do kilku umów CRU, wynik lepszego jest obniżany do 0,89, czyli decyzja przechodzi do eksperta.

| Połączenie (metoda) | Akceptacja auto | Do przeglądu | Odrzucone | Cechy |
|---|---:|---:|---:|---|
| Pilot → postępowanie BZP (exact_id / fuzzy / cross_reference) | 22 | 36 | 1 | numer BZP, NIP, słowa tytułu, CPV, data |
| Pilot → projekt Mapy Dotacji (exact_value+beneficiary) | 10 | 0 | 0 | kwota co do grosza, beneficjent |
| Projekt KPO B3.1.1 (Mapa Dotacji) → postępowanie BZP (beneficiary+value+text) | 307 | 358 | 982 | gmina i jej rodzaj z TERYT, województwo, kwota, tekst (TF-IDF), części |
| Umowa CRU → umowa BZP (buyer_id+contractor+value+date) | 462 | 119 | 20 | NIP/REGON zamawiającego, wykonawca, wartość (netto/brutto), data ±45 dni |
| Zamawiający → ogłoszenie TED (exact_id / buyer_name+city) | 523 | 655 | 0 | numer krajowy, nazwa, miejscowość |
| Zamawiający → orzeczenie KIO (buyer_name+details / text_mention) | 0 | 66 | 28 | nazwa zamawiającego, wzmianka w tekście |
| **Razem** | **1 324** | **1 234** | **1 031** | |

Najważniejsze wyniki:

- **Mapa Dotacji (KPO B3.1.1):** 630 projektów (pominięty 1 wpis zbiorczy). Beneficjent rozpoznany dla 590, nierozpoznany dla 40 (głównie spółki, które nie ogłaszają w BZP). Dla najlepszego kandydata: akceptacja 296, przegląd 179, odrzucenie 103; kwota KPO równa kwocie z BZP co do grosza w 82 przypadkach. Kontrola na 10 parach referencyjnych (piloty z numerem KPO; pary nie są cechą wejściową): beneficjent poprawny 10/10, właściwe postępowanie na 1. miejscu 10/10, w pierwszej trójce 10/10; 7 akceptacji automatycznych, wszystkie poprawne, 3 właściwe postępowania w kolejce eksperta. Kandydaci z miejsc 2–3 dla tych par mają werdykt „niepewne” (20).
- **Centralny Rejestr Umów:** 16 982 umowy; zamawiający rozpoznany po NIP 4 771, po REGON z BZP 7 832, nierozpoznany 4 379. Najlepszy kandydat: akceptacja 462, przegląd 52, odrzucenie 7. W 85,9% zaakceptowanych par wartość CRU zgadza się z brutto BZP po doliczeniu 23% VAT, czyli CRU podaje zwykle netto (porównujemy tylko podobne z podobnym). Umów CRU z aneksami: 1 351; tylko 4 z zaakceptowanych mają ogłoszenie o zmianie w BZP, więc CRU uzupełnia monitoring o zmiany niewidoczne w BZP.
- **Niepewne trafiają do eksperta:** zadanie `review_sync` (`backend/riskminer/review/queue_sync.py`) tworzy pozycję kolejki dla każdego kandydata projektu o decyzji „review” (36 otwartych). Kandydaci krajowi o decyzji „review” (1 198) są dostępni w `GET /api/link-candidates` z filtrem decyzji i w eksporcie `link_candidates`, ale nie są jeszcze wpychani do kolejki Przeglądu (patrz ograniczenia).

### Praca eksperta nad powiązaniami

W Przeglądzie (3.1) ekspert zatwierdza, poprawia albo odrzuca kandydata (`backend/riskminer/review/service.py`): zatwierdzenie tworzy lub nadpisuje powiązanie z `method = expert`, `review_status = approved`; poprawka to wskazanie innego numeru BZP (powiązanie zastąpione, kandydat odrzucony); odpowiedź „żadne” odrzuca wszystkich otwartych kandydatów projektu. Każda decyzja to wiersz `review` z treścią przed i po, a cofnięcie (`POST /api/reviews/{id}/undo`) to nowy wiersz z `undo_of`. Wiersze zatwierdzone i poprawione chroni wyzwalacz `rm_protect_approved` (także na `link_candidate`), więc ponowne przeładowanie danych ani model ich nie nadpisze. `audit_log` ma wyzwalacz `audit_log_append_only` (odrzuca UPDATE i DELETE). Stan na żywej bazie: 2 decyzje (1 zatwierdzenie, 1 poprawka), 97 wierszy audytu; kolejka: 36 powiązań, 97 zdarzeń AI, 10 rozbieżności, 4 propozycje katalogu. Decyzję i cofnięcie w przeglądarce sprawdziła sesja integracyjna (flaga `review_queue`), testy `tests/api/test_review.py` w zestawie automatycznym.

### Rozbieżności w danych wykryte automatycznie

| Projekt | Kod | Waga | Opis (tytuł pozycji w kolejce) |
|---|---|---|---|
| RM-2026-002 | change_count_mismatch | niska | w ogłoszeniach są 2 zmiany, w ogłoszeniu o wykonaniu zadeklarowano 1 |
| RM-2026-006 | change_count_mismatch | niska | w ogłoszeniach są 3 zmiany, w ogłoszeniu o wykonaniu zadeklarowano 2 |
| RM-2026-007 | value_deviation | wysoka | wartość przedsięwzięcia 3 096 863,90 zł, najbliższa kwota z BZP (suma umów) 1 478 460,00 zł, -52,3% |
| RM-2026-008 | part_scope_wider | wysoka | zestaw wskazuje część 1, opis obejmuje części 1, 2, 3, 4 |
| RM-2026-008 | value_deviation | wysoka | 6 188 345,13 zł wobec sumy wypłat 4 955 056,04 zł, -19,9% |
| RM-2026-009 | part_mismatch | wysoka | zestaw wskazuje część 2, opis odpowiada części 1 |
| RM-2026-014 | value_deviation | wysoka | 1 714 989,00 zł wobec sumy wypłat 1 294 007,90 zł, -24,5% |
| RM-2026-022 | contract_notice_missing | wysoka | ogłoszenie 2023/BZP 00110672 nie występuje w BZP; powołują je 3 późniejsze ogłoszenia zamawiającego |
| (krajowo) | dates_inconsistent | niska | 71 umów z planowanym końcem przed podpisaniem: wyłączone ze statystyk i sygnałów |
| (krajowo) | dates_inconsistent | niska | 116 umów klasy referencyjnej z niemożliwymi datami: opóźnienie i czas trwania nie są liczone |

### Inne źródła: „szukano, znaleziono” i „szukano, nie znaleziono”

Każde wyszukiwanie dla projektu lub zamawiającego zapisuje wynik w `source_check`, także pusty; brak wyniku nie oznacza braku zdarzenia.

| Źródło | Projekty (22): znaleziono / częściowo / brak | Zamawiający: znaleziono / częściowo / brak |
|---|---|---|
| Mapa Dotacji | 10 / 0 / 0 (piloty z numerem KPO) | 14 / 0 / 6 |
| TED | 0 / 0 / 22 | 2 / 0 / 18 |
| KIO | 0 / 0 / 22 | 17 / 0 / 3 |
| NIK | 1 / 0 / 21 | nie dotyczy |
| CRU | 13 / 4 / 5 | 12 / 4 / 4 |
| BIP (22 gminy) | 9 / 1 / 9, zablokowane 3 | nie dotyczy |
| Lista projektów FE | nie dotyczy | 12 / 0 / 8 |
| Baza Konkurencyjności | nie dotyczy | 16 / 0 / 4 |
| Biała lista VAT | nie dotyczy | 234 / 0 / 2 |
| GUS BIR (REGON) | nie dotyczy | 37 / 0 / 3 |
| KRS | nie dotyczy | 107 / 0 / 0 |
| Dokumenty postępowań (22) | 6 / 16 / 0 | nie dotyczy |
| BZP API na żywo | 22 / 0 / 0 | nie dotyczy |

KPOŚK (15 950 rekordów: 7 694 aglomeracje, 8 256 oczyszczalni), GUS BDL, wskaźnik cen GUS i NFOŚiGW służą jako dane kontekstowe i nie mają miary dopasowania do projektów [do sprawdzenia: brak zapisanej miary trafności łączenia KPOŚK z projektami].

Źródło: `select method, review_status, count(*) from project_procedure group by 1,2`; `link_candidate` (decision, review_status, method, reference_verdict, rank, z `external_record.source_kind`); `review_item` (kind, status, code, title); `review` (action); `audit_log`; `source_check` (source_kind, subject_type, result); `docs/test_report_sources.md` §3–4a (`uv run riskminer report`, 21.11.2026 19:27 UTC); `research/bzp_linking/chains.json`.

## Test integracji

Każde źródło ma konektor, który tylko pobiera i zapisuje surowe bajty bez zmian w `data/raw/<źródło>/` z jedną linią `manifest.jsonl` na pobranie (URL, czas, SHA-256, licencja). Normalizacja do bazy jest osobnym, odtwarzalnym krokiem. Reguły pobierania: ≤ 1 zapytanie/s na serwis (BZP ≤ 25/min), backoff, robots.txt, stały User-Agent bez danych osobowych, bez obchodzenia CAPTCHA i WAF (zapis `blocked`).

| Źródło | Zapytania | OK | Puste | Zablokowane | Błędy | Rekordy w bazie |
|---|---:|---:|---:|---:|---:|---:|
| Zestaw organizatora (XLSX, 22 projekty) | 1 | 1 | 0 | 0 | 0 | 22 |
| BZP: kopia krajowa organizatora | 1 | 1 | 0 | 0 | 0 | 113 278 |
| BZP: API e-Zamówienia (delta na żywo) | 443 | 384 | 57 | 0 | 2 | 1 077 |
| BZP: drogi (pakiet drugiego sektora) | 418 | 418 | 0 | 0 | 0 | 134 287 |
| Biała lista VAT | 9 | 9 | 0 | 0 | 0 | 234 |
| TERYT (TERC) | 399 | 399 | 0 | 0 | 0 | 4 360 |
| Granice administracyjne (GeoJSON) | 35 | 35 | 0 | 0 | 0 | 2 875 |
| Mapa Dotacji: KPO B3.1.1 | 695 | 695 | 0 | 0 | 0 | 631 |
| TED (UE) | 7 380 | 7 380 | 0 | 0 | 0 | 18 325 |
| Orzeczenia KIO | 6 608 | 6 608 | 0 | 0 | 0 | 2 084 |
| Wyniki kontroli NIK | 1 140 | 1 135 | 0 | 0 | 5 | 522 |
| Centralny Rejestr Umów | 4 884 | 4 880 | 0 | 4 | 0 | 16 982 |
| Dokumenty postępowań (22) | 3 077 | 2 649 | 0 | 417 | 11 | 1 138 |
| Dokumenty: próba krajowa | 22 288 | 22 230 | 14 | 37 | 7 | 9 403 |
| KPOŚK | 6 | 6 | 0 | 0 | 0 | 15 950 |
| GUS BDL | 455 | 449 | 0 | 0 | 6 | 289 873 |
| GUS: wskaźnik cen | 4 | 4 | 0 | 0 | 0 | 671 |
| Lista projektów FE | 2 | 2 | 0 | 0 | 0 | 2 350 |
| NFOŚiGW | 8 | 8 | 0 | 0 | 0 | 126 |
| BIP (22 gminy) | 1 912 | 1 799 | 2 | 0 | 111 | 78 |
| GUS BIR (REGON) | 81 | 81 | 0 | 0 | 0 | 38 |
| KRS | 215 | 108 | 0 | 107 | 0 | 107 |
| Baza Konkurencyjności | 130 | 130 | 0 | 0 | 0 | 110 |

Baza przypadków z BZP po normalizacji: 248 642 ogłoszenia (najnowsze wersje 248 250), 101 016 postępowań, 112 733 części, 128 051 umów, 68 755 ogłoszeń o wykonaniu, 60 293 zmiany umów, 18 641 organizacji, 860 286 wierszy dowodów (pole formularza ogłoszenia z cytatem). Wod-kan: 45 347 postępowań; klasa referencyjna wykonanych umów na roboty (bez duplikatów) n = 11 210, po terminie 30,2%. Tekst dokumentów: 9 911 dokumentów, 66 043 strony, 214 449 fragmentów w indeksie; OCR (Tesseract, model pol) dla 3 188 dokumentów.

Przebiegi: 208 wierszy `ingestion_run` dla 35 konektorów i etapów, 199 zakończonych `ok`, 9 `error`. Błędy dotyczą wczesnych przebiegów (np. typ jsonb, znak `\u0000`, za krótkie pole, przerwanie sesji) i każdy z tych etapów ma później udany przebieg. Zarejestrowane pobrania: 47 250 wierszy `source`, 46 615 z sumą SHA-256 [do sprawdzenia: 635 wierszy `source` bez sha256, nie ustaliliśmy, czy to rekordy pochodne bez własnych bajtów].

Odtworzenie:

```bash
docker compose -f infra/docker-compose.yml up -d db
cd backend && uv sync && uv run alembic upgrade head
uv run riskminer load-all                 # katalog → XLSX → kopia BZP → wyprowadzenie → łączenie 22/22 → źródła → raport
uv run riskminer sources                  # lista 21 konektorów
uv run riskminer scrape <źródło> [--since D --limit N --only a,b]
uv run riskminer report                   # docs/test_report_sources.md + exports/sources_summary.csv
```

Źródło: `docs/test_report_sources.md` §1–2, 4b; `exports/sources_summary.csv`; `select status, count(*), count(distinct connector) from ingestion_run group by 1`; `select count(*), count(sha256) from source`; `select count(*) from evidence`.

## Test kompletności przypadku

Dwa projekty z pełnym łańcuchem: projekt → postępowanie → ogłoszenia (o zamówieniu, o wyniku, o zmianie umowy, o wykonaniu) → umowa → zmiany → wykonanie → zdarzenia ryzyka. Każde zdarzenie wyliczone (CALC) ma wiersz dowodu z kodem pola ogłoszenia.

### RM-2026-003: oczyszczalnia ścieków w Steklinie (Gmina Czernikowo), zaprojektuj i wybuduj

- **Powiązanie:** exact_id (1,00), postępowanie `ocds-148610-6b092479-223f-11ef-87ba-8eb060fd7bb8`, wartość szacunkowa 2 602 091,26 zł **netto**, 1 część.
- **Ogłoszenia:** o zamówieniu `2024/BZP 00349631/01` (04.06.2024), o wyniku `2024/BZP 00418711/01` (18.07.2024), o zmianie umowy `2024/BZP 00554831/01` (21.10.2024) i `2024/BZP 00618384/01` (27.11.2024), o wykonaniu `2026/BZP 00276065/01` (03.06.2026).
- **Umowa:** Zakład Usług Melioracyjnych i Geodezyjnych Piotr Rojek, podpisana 18.07.2024, 2 131 590,00 zł **brutto**, 396 dni, planowany koniec 18.08.2025.
- **Zmiany:** dwie zmiany zakresu i wynagrodzenia na podstawie art. 455 ust. 1 pkt 3 (+758 084,56 zł, czyli +35,6%, oraz +100 325,44 zł, czyli +4,7%); trzecia zmiana z listy w ogłoszeniu o wykonaniu na podstawie art. 455 ust. 1 pkt 1 (przedłużające się postępowanie administracyjne Wód Polskich).
- **Wykonanie:** zakończone 22.05.2026, w terminie: nie, 3 zmiany, wypłacono 2 990 000,00 zł brutto. Czas faktyczny 673 dni wobec 396: **+277 dni**; koszt **+40,3%** (wypłata wobec wartości umowy). Wartości zgodne ze wzorcem (Steklin: +277 dni, +40,3%).
- **Zdarzenia ryzyka (12, każde z dowodem):** roboty dodatkowe R07 (CALC), zmiana terminu R06 (CALC), wykonanie po terminie +277 dni (CALC), wypłata wyższa od wartości umowy +858 410,00 zł, 40,3% (CALC); przyczyny według modelu AI: R01 „niepełny lub niespójny zakres” i R04 „decyzje, pozwolenia, uzgodnienia” (AI, `proposed`, w kolejce eksperta).

### RM-2026-020: kanalizacja sanitarna z oczyszczalnią ścieków (Gmina Nowogard)

- **Powiązanie:** fuzzy (1,00) po NIP, słowach tytułu, CPV wod-kan i dacie; postępowanie `ocds-148610-740158c8-9281-4fe9-9f58-59edc56af25c`, wartość szacunkowa 2 207 285,70 zł netto. Zestaw organizatora podaje wartość 1 749 991,33 zł (podstawa VAT nieznana).
- **Ogłoszenia (9):** o zamówieniu `2025/BZP 00113651/01` (20.02.2025), 4 zmiany ogłoszenia (20.02–13.03.2025), o wyniku `2025/BZP 00206455/01` (25.04.2025), o zmianie umowy `2025/BZP 00558908/01` (27.11.2025) i `2026/BZP 00280220/01` (09.06.2026), o wykonaniu `2026/BZP 00291637/01` (16.06.2026).
- **Umowa:** konsorcjum „Starkan”, podpisana 24.04.2025, 1 969 611,30 zł brutto, 183 dni, planowany koniec 24.10.2025.
- **Zmiany:** dwie na podstawie art. 455 ust. 1 pkt 4: ustanowienie służebności przesyłu na działce 3/39 obręb Konarzewo oraz niekorzystne warunki gruntowe ujawnione przy pracach ziemnych.
- **Wykonanie:** zakończone 27.04.2026, w terminie: nie, 2 zmiany; 368 dni wobec 183: **+185 dni**; wypłacono 1 719 611,30 zł brutto, czyli **-12,7%** wobec wartości umowy.
- **Zdarzenia ryzyka (14):** okoliczności nieprzewidywalne R07 i zmiana terminu R06 (CALC), wykonanie po terminie +185 dni, wypłata niższa od wartości umowy -250 000,00 zł (CALC); przyczyny według modelu: R03 kolizje z uzbrojeniem i dostęp do terenu, R02 rozpoznanie stanu istniejącego (AI, `proposed`).

Zdarzenia z ogłoszeń o zmianie i z listy zmian w ogłoszeniu o wykonaniu występują w obu wersjach; zmiany powtórzone mają `is_duplicate = true` i nie są liczone podwójnie w statystykach. Pełne eksporty karty projektu: `exports/sample/RM-2026-003_projekt.{json,csv}`, `exports/sample/RM-2026-003_karta.json`.

Źródło: tabele `project`, `project_procedure`, `procedure`, `notice`, `contract`, `contract_change`, `contract_performance`, `risk_event`, `evidence` (zapytania tylko do odczytu, filtr po `rm_id`).

## Test źródłowy

Własna próba wniosków losowana ze stałym ziarnem (seed 2026), sprawdzana mechanicznie tym samym weryfikatorem cytatów, którego używa aplikacja (`backend/riskminer/llm/verify.py`: normalizacja, dopasowanie dokładne na wskazanej stronie, przybliżone rapidfuzz ≥ 90, cytat przez granicę stron, komórki tabel). Dodatkowo każda liczba z wniosku musi występować w cytacie.

| Rodzaj wniosku | Próba | Dokładny | Przybliżony | Niepotwierdzony |
|---|---:|---:|---:|---:|
| Klasyfikacja przyczyny zmiany (AI) | 18 | 18 | 0 | 0 |
| Propozycja zdarzenia ryzyka (AI) | 8 | 7 | 1 | 0 |
| Cecha inwestycji (AI) | 10 | 10 | 0 | 0 |
| Uwaga czerwonego długopisu (AI) | 15 | 13 | 2 | 0 |
| Fakt z nowego dokumentu (reguły i AI) | 10 | 10 | 0 | 0 |
| Cytat z pola ogłoszenia BZP (źródło) | 10 | 10 | 0 | 0 |
| Wartość z pola ogłoszenia BZP (źródło) | 10 | 10 | 0 | 0 |
| **Razem** | **81** | **78** | **3** | **0** |

Uwagi z próby: (1) data zawarcia umowy w ogłoszeniu wieloczęściowym wskazywała pierwsze wystąpienie pola 8.1; dowody dostały zakres znaków konkretnego wystąpienia (145 799 dowodów w 21 436 ogłoszeniach), teraz zgodne dla wszystkich 3 669 takich umów; (2) przy zdarzeniach z ogłoszeń o unieważnieniu i o zmianie dowód w 5 z 10 cytatów BZP wskazuje sąsiednie pole tego samego ogłoszenia (np. podstawę prawną zamiast uzasadnienia): wniosek poprawny, wskazanie do poprawy; (3) 3 wyniki przybliżone różnią się tylko białymi znakami i znakami tabel. Przy n = 81 to próba kontrolna, nie dowód doskonałości; powtarzalna z innym ziarnem: `cd backend && RISKMINER_LLM_FAKE=1 uv run python -m riskminer.llm.eval.source_test --seed 2026`, pełna próba w `exports/source_test_sample_seed2026.csv`.

**Cytaty przy klasyfikacji przyczyn zmian na całej bazie** (`change_cause_ai`): 20 694 unikalne teksty przyczyn (23 118 zmian umów). Cytat potwierdzony: dokładnie 19 422 (93,9%), w przybliżeniu 529 (2,6%), niepotwierdzony 743 (3,6%); razem **96,4%** potwierdzonych (96,5% ważone liczbą zmian). Niepotwierdzone nie są ukrywane: wniosek ma stan weryfikacji i trafia do eksperta jako propozycja.

**Trafność kodów przyczyn na próbie wzorcowej 150** (`model_eval`, zadanie `classify_causes`, wersja promptu `classify_causes@v1`, paczki po 25):

| Wariant | Model | Trafność (95% CI) | Kod główny lub drugi | κ | Cytaty potwierdzone | Koszt próby |
|---|---|---|---:|---:|---:|---:|
| fast (produkcja, masowo) | gemini-3.5-flash-lite | **80,0%** (73,3–86,0%) | 89,3% | 0,775 | 99,3% | 0,036 USD |
| strong | gemini-3.8-flash | 82,7% (76,0–88,7%) | 88,7% | 0,807 | 98,7% | 0,064 USD |
| emergency (zapas publiczny) | mistralai/mistral-medium-3-5 | 78,0% (70,7–84,0%) | 85,3% | 0,755 | 86,0% | 0,120 USD |
| reguły słownikowe (bez AI) | keyword rules | 37,3% (29,3–45,3%) | nie dotyczy | 0,329 | nie dotyczy | 0 |

Na bazie krajowej pracuje wariant fast: niemal ta sama trafność co strong przy około połowie kosztu i trzykrotnie krótszym czasie. Benchmark czerwonego długopisu i cech na 4 publicznych dokumentach (PFU, PPU, SWZ, 26–31 stron): 43 z 43 cytatów potwierdzonych na stronie (39 dokładnie, 4 w przybliżeniu), 16 z 16 cytatów cech.

Źródło: `docs/submission/test_source_sample.md`; `select verification, count(*), sum(n_changes) from change_cause_ai group by 1`; `select * from model_eval` (wiersze 3–6); `exports/eval/classify_causes_20261121_2027.json`; notatki sesji LLM (benchmark czerwonego długopisu).

## Wyniki analizy nowej inwestycji

Dwa przypadki policzone na żywej bazie (stan na 21.11.2026). Każda liczba w aplikacji ma liczebność próby, metodę i odnośnik do źródła; poniżej skrót.

### Przypadek 1: kanalizacja sanitarna (wod-kan, sektor pilotażowy)

Opis wpisany w 1.1: „Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS”. Rekord pokazowy: **AN-2026-0004** (ścieżka przez interfejs). Ten sam opis z dołączonymi dwoma publicznymi dokumentami z BZP (PFU, 57 s., i projekt umowy, 28 s.) policzono jako **AN-2026-0009**; jego eksport jest w `exports/sample/` (pakiet DOCX, PDF, CSV, JSON, symulacja i lista 82 umów grupy porównawczej).

**Cechy rozpoznane z opisu** (reguły, bez AI): podsektor kanalizacja sanitarna, formuła zaprojektuj i wybuduj, długość ok. 6 km (oznaczona jako niepewna), 3 przepompownie, budżet 7 mln zł brutto, termin 14 mies., finansowanie FEnIKS. Pytanie uzupełniające: „Ile będzie przyłączy?”.

**Grupa porównawcza** (wykonane umowy z ogłoszeń o wykonaniu umowy w BZP):

| krok | n |
|---|---|
| wszystkie wykonane umowy wod-kan, 2021–2026 | 11 222 |
| kanalizacja sanitarna | 4 287 |
| wartość 5–10 mln zł | 373 |
| zaprojektuj i wybuduj | **82** |

**Odpowiedzi na trzy pytania:**

| pytanie | odpowiedź | liczby | n |
|---|---|---|---|
| Czy zdążysz w 14 miesięcy? | Raczej nie | 34% szans; 8 na 10 podobnych umów trwało 13,6–20,2 mies., mediana 15,9 mies. | 77 |
| Czy 7 mln zł wystarczy? | Raczej tak | 1,17 mln zł/km, wyżej niż w 68% umów; połowa umów 0,44–1,39 mln zł/km, mediana 0,80 | 1 962 |
| Czy zdążysz przed końcem programu? | Tak | 98% szans (koniec FEnIKS 31.12.2029, założenie eksperta) | 77 |

**Udziały w grupie** (przedział Wilsona 90% w aplikacji): po terminie 63% (52 z 82), co najmniej jedna zmiana umowy 77% (63 z 82), zapłacono ponad wartość 31% (25 z 81). Odchylenie kosztu: P80 +4,1%, P90 +10,7%.

**Zdanie „W skrócie”** (szablon, nie model językowy): „Podobne inwestycje (82 umowy: kanalizacja sanitarna, wartość 5–10 mln zł, zaprojektuj i wybuduj) w 63% kończyły się po terminie. Przy planie 14 mies. szansa na termin to ok. 34%, a 8 na 10 umów skończyłoby się w 18 mies. Koszt kilometra (1,17 mln zł) jest wyższy niż w 68% umów.”

**Flagi** (reguły z Katalogu): „Termin krótszy niż typowy” (14 mies. wobec mediany 17,8 mies.; krócej planowała tylko co czwarta umowa), „Zimowe roboty ziemne bez rezerwy”.

**Czerwony długopis (AN-2026-0009, reguły z cytatem sprawdzonym w tekście strony):** PFU s. 3 „trasa częściowo na działkach prywatnych” (R03.2), PFU s. 11 „Wykonawca powinien przewidzieć w Cenie Kontraktowej możliwość wystąpienia warunków gruntowo-wodnych odmiennych…” (R02.1), PFU s. 6 przekroczenia dróg i terenów kolejowych (R03.3); brak: klauzula waloryzacyjna w projekcie umowy (art. 439 Pzp, stan „dokument nie wspomina”, proponowany zapis R08.1-K1). Uwagi modelu AI dochodzą osobno jako propozycje do zatwierdzenia.

**Podobne przypadki** (ważone cechy strukturalne + BM25 na opisach, z rozbiciem wkładu cech):

| podobieństwo | przypadek | dlaczego | wynik |
|---|---|---|---|
| 0,91 | Leleszki, etap I (BZP) | ten sam podsektor, podobny opis, podobna wartość | w terminie, bez dopłat |
| 0,90 | Wola Łaskarzewska (BZP) | ten sam podsektor, podobna wartość, podobna długość sieci (7,8 km) | w terminie, bez dopłat |
| 0,88 | Koliszowy, gm. Ruda Maleniecka (BZP) | ten sam podsektor, podobny opis, podobna wartość | w terminie, bez dopłat |
| 0,84 | **Bestwina, RM-2026-013** (przypadek zweryfikowany) | ten sam podsektor, podobna wartość, podobny opis | +31 dni, +6,8% |

**Zapisy do umowy:** R06.1-K1 (harmonogram i kamienie milowe), R16-K1 (warunki atmosferyczne), R08.1-K1 (waloryzacja, art. 439; 31% podobnych umów rozliczono ponad wartość).

**Symulacja (1.4):** 20 000 losowań całych umów z grupy. Najwięcej dni do wyniku „8 na 10” dokładają: roboty dodatkowe R07 (+18 d), decyzje R04 (+9 d), dostawy R12 (+6 d). Zmiany przed przetargiem (badania gruntu, termin 18 mies., waloryzacja K-07, cena za metr) przesuwają krzywe niewiele, bo efekt liczony jest tylko z umów z rozpoznaną przyczyną (39 z 49 opóźnionych); aplikacja mówi to wprost.

**Podział ryzyk (1.5):** oczekiwany koszt ryzyk z danych 1–30 tys. zł na ryzyko (np. R08 długość sieci 30 tys. zł, R02 grunt 28 tys. zł); podział zalecany jest zgodny z Katalogiem. Pakiet do akt pobiera się jako DOCX, PDF, CSV i JSON.

**Wiarygodność prognoz (sprawdzian wsteczny):** na 6 143 umowach zakończonych od 2024 r. 85% opóźnień mieściło się w przedziale P10–P90 policzonym na danych sprzed 2024 r. (koszt 79,5%). Prognoza odsetka opóźnionych była zaniżona o ok. 6 pp; to ograniczenie jest pokazywane w raporcie.

**Ograniczenia pokazane w raporcie:** koszt liczony względem wartości z ogłoszenia o wykonaniu (dolna granica dopłat); przyczyny zmian z klasyfikacji AI do przeglądu (ok. 8 na 10 trafień na próbie wzorcowej); koszt kilometra nominalny, długość odczytana z opisu dla 54% umów; termin programu to założenie eksperta; bez dołączonego PFU/PPU sygnały z dokumentów nie są sprawdzone.

### Przypadek 2: droga gminna (sektor drogi, rozszerzenie pilotażu)

Opis: „Przebudowa drogi gminnej 2,4 km z chodnikiem, 3,1 mln zł, 10 mies.”. Ten sam silnik, inny pakiet sektorowy (`catalogue/drogi/`, wszystkie wpisy w stanie „do zatwierdzenia”). System sam rozpoznał sektor i podsektor z opisu.

| krok | n |
|---|---|
| wszystkie wykonane umowy drogowe, 2021–2026 | 30 335 |
| droga gminna lub ulica | 15 007 |
| wartość 2–5 mln zł | 1 521 |
| przebudowa lub modernizacja | **893** |

Szansa na termin przy 10 mies.: ok. 73%; 8 na 10 umów w 7,2–13,2 mies.; po terminie 32,5% (290 z 892); zmiany umowy 55% (490 z 893); koszt kilometra drogi: mediana 0,83 mln zł/km (n = 5 743, długość odczytana dla 45% umów), 3,1 mln zł / 2,4 km = 1,29 mln zł/km, czyli 70. percentyl. Raport oznacza sektor jako rozszerzenie pilotażu i informuje, że założenia eksperta (zmiany przed przetargiem, podział ryzyk) przejęto z wod-kan.

**Pliki przykładowe w `exports/sample/`:** `AN-2026-0009_pakiet.docx`, `AN-2026-0009_pakiet.pdf`, `AN-2026-0009_pakiet.csv`, `AN-2026-0009_pakiet.json`, `AN-2026-0009_symulacja.json`, `AN-2026-0009_grupa_porownawcza.json`, `AN-2026-0009_grupa_porownawcza.csv`, `RM-2026-003_projekt.json`, `RM-2026-003_projekt.csv`, `RM-2026-003_karta.json`.

Źródło: `docs/submission/_section_new_investment.md` (sekcja przygotowana przez właściciela analityki, liczby sprawdzone na żywej bazie; wstawiona bez zmian); `exports/sample/`.

## Dokumenty organizatora: nowe dokumenty od wgrania do „Co się zmieniło”

Trzy pliki z `materials/organizer_cases/` przechodzą ten sam potok co każdy nowy dokument projektu (`backend/riskminer/documents/pipeline.py`): OCR, gdy brak warstwy tekstowej, → fakty (reguły, potem model z weryfikacją cytatów) → powiązanie z projektem i umową → ponowna analiza, alert w monitoringu i zestawienie „Co się zmieniło”. Oczekiwane wartości wzorcowe zapisano z góry w `docs/impl/new_documents.md` §1.

| Dokument | Projekt | Sprawdzone wartości wzorcowe | Wynik |
|---|---|---|---|
| `Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf` (1 s., warstwa tekstowa) | RM-2026-002, przez numer KPO `KPOD.03.15-IW.13-0004/25` | termin +1 mies., nowy planowany koniec 05.06.2026 (CALC), przyczyny R03 (kolizja z siecią wodociągową przy pompowni PM2) i R02 (wody gruntowe) z cytatami, propozycja R18 (zależność od powiązanej inwestycji, oczyszczalnia Modlikowice), alert dla trwającej umowy, niepusty diff | zaliczony |
| `Risk_Miner_protokol_koniecznosci_zlawies.docx` | RM-2026-005 | +151 481,54 zł **brutto**, termin 30.10.2025 → 05.12.2025 (+36 dni, CALC), podstawa art. 455 ust. 1 pkt 3, wykonawca WIMAX, przyczyna R02, niepusty diff | zaliczony |
| `Risk_Miner_pismo_termin_grodzisko.pdf` (skan bez tekstu) | RM-2026-010, przez numer KPO `KPOD.03.15-IW.21-0025/25` | OCR stron, wniosek o przedłużenie projektu KPO do 31.12.2025 zapisany jako zmiana terminu umowy o dofinansowanie, **nie** jako zmiana umowy wykonawczej, pozycja kolejki dla NIP 8161571014 z błędną sumą kontrolną (w rejestrze 8161570014; bez cichej poprawki), alert na poziomie projektu, niepusty diff | zaliczony |

Test: `backend/tests/api/test_new_documents.py` (G6, znacznik `fulldb`). Wgrywa pliki jako ekspert, uruchamia potok w transakcji wycofywanej na końcu, z modelem w trybie odtwarzania nagranych odpowiedzi, więc niczego nie zapisuje do bazy. Uruchomiony przy tym raporcie: **3 zaliczone** (5,1 s); wchodzi też w pełny zestaw backendu. Reguły same spełniają §1, więc dokumenty poufne (bez wysyłki do chmury) dają ten sam wynik. Dodatkowo próba źródłowa zawiera 10 faktów z tych trzech dokumentów, 10 z 10 potwierdzonych cytatem (sekcja „Test źródłowy”). Grodzisko ma też REGON 690581210 z błędną sumą kontrolną, oznaczony do przeglądu.

Źródło: `uv run pytest -q tests/api/test_new_documents.py -v` (3 passed); `docs/impl/new_documents.md` §1; notatki sesji integracyjnej (flaga `new_document_reanalysis` włączona po G6 3/3).

## Sprawdzian wsteczny prognoz

Uczymy na umowach wod-kan zakończonych przed 01.01.2024 r., sprawdzamy na zakończonych od 01.01.2024 r. (wersja danych `an_contract:wod-kan@2026-11-21T20:33:48Z/11222`).

| Wielkość | n uczące | n testowe | W przedziale P10–P90 | Powyżej P90 | ≤ P80 | Strata kwantylowa P90: klasa / globalnie |
|---|---:|---:|---:|---:|---:|---|
| Opóźnienie (dni) | 4 422 | 6 143 | **85,0%** | 15,0% | 76,1% | 17,23 / 18,65 |
| Opóźnienie (% planu) | 4 422 | 6 143 | **87,7%** | 12,3% | 77,1% | 10,46 / 10,34 |
| Odchylenie kosztu (%) | 4 510 | 6 332 | **79,5%** | 12,9% | 79,6% | 1,57 / 1,62 |

Prawdopodobieństwo opóźnienia (n = 6 367): Brier **0,217** dla klasy referencyjnej wobec 0,227 dla prognozy globalnej; prognozowany odsetek opóźnionych 27,5%, obserwowany 33,4%, czyli prognoza **zaniżona o ok. 6 pp** (5,9 pp). Klasa referencyjna poprawia prognozę dni i kosztu względem średniej krajowej, a dla opóźnienia w % planu jest na poziomie globalnej. Raport analizy pokazuje tę notę przy prognozie (flaga `backtest`).

Źródło: `curl -s localhost:8000/api/analytics/backtest` (metoda `backtest_w3`, tylko odczyt).

## Testy automatyczne

| Zestaw | Polecenie | Wynik | Czas |
|---|---|---|---|
| Backend (pytest) | `cd backend && uv run pytest -q` | **276 zaliczonych, 3 pominięte**, 0 błędów (279 zebranych) | 114 s |
| Frontend (vitest) | `cd frontend && npx vitest run` | **157 z 157 zaliczonych** w 23 plikach, 0 błędów | 5,9 s |

Pominięte celowo: 3 testy w `tests/test_link_national.py`, które zapisują do bazy („mutates the DB; set RISKMINER_TESTDB=1 on a test DB”); domyślna konfiguracja pomija testy `mutates`, `live` i `live_llm`, a testy na bazie krajowej (`fulldb`) działają w transakcjach wycofywanych. Zestaw backendu obejmuje m.in.: test kontraktu API (każda ścieżka z `/openapi.json`, bez duplikatów i przesłaniania), test braku atrap danych przy włączonych flagach, smoke każdego GET dla gościa i eksperta z utworzeniem i uruchomieniem analizy, test uprawnień zapisu (39 tras: juror tylko do odczytu dostaje 403, gość 401), smoke dla każdej włączonej flagi (test pilnujący nie pozwala włączyć flagi bez smoke), G6 dla dokumentów organizatora. W wyjściu vitest widać ostrzeżenia jsdom „Not implemented: Window's scrollTo()”: to ograniczenie środowiska testowego, nie błąd. Nie zaobserwowaliśmy błędów wcześniej istniejących w żadnym zestawie.

**Dostępność i przeglądarka (sesja integracyjna):**

- Przegląd axe (WCAG 2.1 A/AA) na 18 stronach, publicznych i eksperckich. Bez uwag: Nowa analiza, Raport, Pakiet, Projekty, karta projektu, Graf, Zapytaj, Pulpit, Przegląd, Katalog, Dokumenty, Historia (projekt i globalna), Źródła, Ustawienia. Poważne uwagi: Monitoring i Monitoring/12 (`scrollable-region-focusable` na listach wehikułu czasu) oraz Symulacja (`color-contrast`, tekst wyciszony z przezroczystością); uwagi w szkielecie (link logo, przycisk konta) poprawione. Obie uwagi poprawiono po przeglądzie: przewijana lista wehikułu czasu przyjmuje fokus klawiatury (`tabIndex=0`), a tekst „bez wpływu na …” w Symulacji ma kontrast co najmniej 4,5:1 (bez przezroczystości); ponowny przegląd zlecono zespołowi integracji.
- Przejścia przeglądarką bez interfejsu (Chromium headless): ścieżki publiczne (Monitoring, Projekty, karta RM-2026-003, Graf, Nowa analiza) i eksperckie (Pulpit, Przegląd, Katalog, Dokumenty) z 0 błędami API 4xx/5xx i 0 błędami JS; ścieżka jury przez interfejs: Nowa analiza → Uruchom analizę → raport AN-2026-0004 w ok. 7 s → Symulacja → Pakiet → pakiet PDF, 0 błędów API; wszystkie 4 formaty pakietu pobrane (PDF 143 KB); drugi sektor: opis drogi gminnej → AN-2026-0007 w 2,5 s z lejkiem 30 335 / 15 007 / 1 521 / 893.
- Flagi funkcji: włączone tylko ekrany podłączone do prawdziwego API i sprawdzone w przeglądarce oraz smoke; wyłączone i ukryte: `jelly` (animacja 3D ignoruje `prefers-reduced-motion`), `sovereign_switch` (model w Polsce jeszcze nie serwowany), `sector_pack_wizard` (niezbudowany).

Źródło: uruchomienia z 21.11.2026 (wyjście w notatkach roboczych); notatki sesji integracyjnej (`s0-flags.md`, `s0-api-contract.md`); `config/config.example.yaml` → `features:`.

## Znane ograniczenia i luki danych

- **Kolejka eksperta dla powiązań krajowych:** do Przeglądu trafiają tylko kandydaci projektów pilotażowych (36). 1 198 kandydatów krajowych o decyzji „review” (Mapa Dotacji 358, CRU 119, TED 655, KIO 66) jest dostępnych przez API i eksport, ale nie jako pozycje kolejki.
- **Dowód wskazuje sąsiednie pole** przy części zdarzeń z ogłoszeń o unieważnieniu i o zmianie (5 z 10 cytatów BZP w próbie); cytat jest w tym samym ogłoszeniu, mapowanie kodów pól do poprawy.
- **Dokumenty postępowań:** 417 pobrań zablokowanych przez zabezpieczenia platform (nie obchodzimy ich); 16 z 22 projektów ma dokumenty częściowe. 12 skanów czeka na OCR, 427 dokumentów ma niską pewność OCR (cytaty oznaczone jako nieczytelne).
- **CRU:** szczegóły (lista aneksów) pobrane dla 4 446 z 16 982 umów (serwis za WAF, pobieranie wstrzymywane przy stronie wyzwania); CRU działa od 01.07.2026 i podaje zwykle kwoty netto.
- **Koszt:** odchylenie liczone względem wartości z ogłoszenia o wykonaniu, więc to dolna granica dopłat; koszt kilometra nominalny, długość odczytana z opisu dla 54% umów wod-kan.
- **Przyczyny zmian:** klasyfikacja AI trafia w ok. 8 na 10 przypadków (próba 150); 3,6% tekstów przyczyn ma niepotwierdzony cytat. Wszystkie wnioski AI mają status `proposed` do decyzji eksperta.
- **Prognoza odsetka opóźnień** zaniżona o ok. 6 pp w sprawdzianie wstecznym; pokazywane przy prognozie.
- **Dane niespójne:** 71 umów z planowanym końcem przed podpisaniem i 116 umów klasy referencyjnej z niemożliwymi datami wyłączonych ze statystyk (dwie pozycje `dates_inconsistent`; zbiory mogą się pokrywać).
- **Model w Polsce (dane poufne):** zadanie na klastrze czeka w kolejce; bez niego poufne dokumenty dostają tylko fakty z reguł, nigdy nie trafiają do chmury.
- **Drugi sektor (drogi):** wpisy katalogu w stanie „do zatwierdzenia”, założenia eksperta przejęte z wod-kan.
- **Źródła kontekstowe** (KPOŚK, GUS BDL, NFOŚiGW) nie mają miary trafności łączenia z projektami.

Źródło: sekcje powyżej; `docs/test_report_sources.md` §4b i §5; `review_item` (kind discrepancy, code dates_inconsistent).
