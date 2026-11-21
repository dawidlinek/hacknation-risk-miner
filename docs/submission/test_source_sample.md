# Test źródłowy: własna próba wniosków

Przygotowane 21.11.2026 przez zespół ex ante (sesja LLM). Sprawdzamy to, co sprawdzi jury: czy wskazany fragment lub pole naprawdę potwierdza wniosek. Sprawdzenie jest mechaniczne, bez wywoływania modeli.

## Wynik w skrócie

- Wnioski AI: **61 z 61** potwierdzone cytatem na wskazanej stronie lub w tekście pozycji (58 dokładnie, 3 w przybliżeniu), a każda liczba z wniosku występuje w cytacie.
- Fakty źródłowe z BZP: **20 z 20** potwierdzone w ogłoszeniu (wartości: 10 z 10 w polu wskazanym przez dowód; cytaty: 5 z 10 w polu wskazanym przez dowód, pozostałe w innym polu tego samego ogłoszenia).
- Znaleźliśmy jeden błąd systematyczny po stronie danych (nie modelu): przy części zdarzeń wyliczonych z ogłoszeń o unieważnieniu i o zmianie dowód wskazuje sąsiednie pole (np. podstawę prawną zamiast uzasadnienia). Cytat jest w tym samym ogłoszeniu. Zgłoszone zespołowi danych.

## Metoda

1. Losowanie z ustalonym ziarnem (seed 2026) z każdego rodzaju wniosku, w kolejności `md5(id || seed)` w bazie albo `random.Random(2026)` dla nagranych przebiegów.
2. Dla każdego wniosku bierzemy cytat zapisany przy wniosku i tekst, na który wniosek się powołuje: stronę dokumentu (`document_page.text`), opis użytkownika, tekst przyczyny i opisu zmiany z ogłoszenia albo pole ogłoszenia BZP: wskazane wystąpienie pola w treści ogłoszenia (zakres znaków zapisany przy dowodzie), a gdy dowód go nie ma, `notice.parsed_fields`. Jeśli cytatu nie ma we wskazanym polu, szukamy go w całej treści ogłoszenia i oznaczamy wynik jako "w innym polu ogłoszenia".
3. Weryfikator cytatów (`backend/riskminer/llm/verify.py`, ten sam, którego używa aplikacja): normalizacja (miękkie łączniki, przeniesienia wyrazów, cudzysłowy, myślniki, białe znaki), potem kolejno: dokładne dopasowanie na wskazanej stronie, na innej stronie, dopasowanie przybliżone (rapidfuzz, próg 90), cytat przechodzący przez granicę stron, komórki tabeli czytane w innej kolejności. Wynik: dokładny, przybliżony albo niepotwierdzony.
4. Sprawdzenie liczb: każda liczba z wniosku (kwota, długość, liczba sztuk, termin, data) musi występować w cytacie (polskie formaty liczb, mln i tys., km i m).
5. Wnioski czerwonego długopisu i fakty z trzech dokumentów organizatora pochodzą z nagranych odpowiedzi modelu (te same, które aplikacja odtwarza, gdy model jest niedostępny). Pozostałe wnioski AI są wierszami bazy.

Odtworzenie: `cd backend && RISKMINER_LLM_FAKE=1 uv run python -m riskminer.llm.eval.source_test --seed 2026`. Pełna próba z cytatami: `exports/source_test_sample_seed2026.csv`.

## Wynik według rodzaju wniosku

| Rodzaj wniosku | Próba | Dokładny | Przybliżony | Niepotwierdzony | Potwierdzone |
|---|---|---|---|---|---|
| Klasyfikacja przyczyny zmiany (AI) | 18 | 18 | 0 | 0 | 18 z 18 |
| Propozycja zdarzenia ryzyka (AI) | 8 | 7 | 1 | 0 | 8 z 8 |
| Cecha inwestycji (AI) | 10 | 10 | 0 | 0 | 10 z 10 |
| Uwaga czerwonego długopisu (AI) | 15 | 13 | 2 | 0 | 15 z 15 |
| Fakt z nowego dokumentu (reguły i AI) | 10 | 10 | 0 | 0 | 10 z 10 |
| Cytat z pola ogłoszenia BZP (źródło) | 10 | 10 | 0 | 0 | 10 z 10 |
| Wartość z pola ogłoszenia BZP (źródło) | 10 | 10 | 0 | 0 | 10 z 10 |
| **Razem** | 81 | 78 | 3 | 0 | 81 z 81 |

Przy n = 81 wynik nie jest dowodem doskonałości. To próba kontrolna, którą można powtórzyć z innym ziarnem.

## Próba

Linki prowadzą do API (`/api/...`), z którego czyta interfejs. Cytaty skrócone do ok. 110 znaków; pełne w CSV.

| Nr | Rodzaj | Wniosek | Cytat | Wskazane źródło | Wynik | Liczby | Link |
|---|---|---|---|---|---|---|---|
| 1 | Klasyfikacja przyczyny zmiany | R12 | problemach podwykonawców w dostępie do materiałów budowlanych i urządzeń spowodowanych globalnymi (…) | zmiana umowy 37710 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dab5ec-49a1-5449-22d9-370011098bbe` |
| 2 | Klasyfikacja przyczyny zmiany | R04 | przedłużająca się procedurą administracyjną związaną z uzyskaniem pozwolenia wodno-prawnego | zmiana umowy 55875 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08de3330-321a-9d33-0560-490001ff8831` |
| 3 | Klasyfikacja przyczyny zmiany | R17 | Konieczność uwzględnienia innych przedsięwzięć i działań powiązanych z przedmiotem Umowy | zmiana umowy 395661 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dc378c-4044-61d7-64c5-3a0001d3c0a2` |
| 4 | Klasyfikacja przyczyny zmiany | R13 | Konieczność dostosowania płatności częściowych do wymogów otrzymanej promesy inwestycyjnej | zmiana umowy 47492 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dcbdbe-68df-7b4f-82a9-430001452fdd` |
| 5 | Klasyfikacja przyczyny zmiany | R07 | wskazane w kosztorysie dodatkowe roboty budowlane niezbędne do wykonania zamówienia | zmiana umowy 40267 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08db6cd1-c57f-06f5-d0a9-9e0012b90a1c` |
| 6 | Klasyfikacja przyczyny zmiany | N-FORMAL | wniosek Wykonawcy o zmianę osoby na stanowisku kierownika budowy | zmiana umowy 51570 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dd66c8-45e6-a18b-8f1b-b600017d78e4` |
| 7 | Klasyfikacja przyczyny zmiany | R04 | przekroczenia określonych przez prawo terminów wydania wymaganych opinii i uzgodnień przez właściwe organy (…) | zmiana umowy 32374 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08db55f3-870c-56f6-537f-dc00110f7d7f` |
| 8 | Klasyfikacja przyczyny zmiany | R07 | Z uwagi na konieczność wykonania robót dodatkowych - demontaż i ponowny montaż płyt Yumbo | zmiana umowy 50723 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dd36f0-b6de-6666-8f1b-b600017b0566` |
| 9 | Klasyfikacja przyczyny zmiany | R09 | Konieczność poprawy jakości lub innych parametrów charakterystycznych dla danego elementu robót budowlanych (…) | zmiana umowy 41807 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dbd49a-10da-25ff-5986-1d001265c952` |
| 10 | Klasyfikacja przyczyny zmiany | R07 | Protokół konieczności nr 1-roboty dodatkowe i zamienne | zmiana umowy 410531 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dd5a22-44f3-e466-8f1b-b600017cd8b5` |
| 11 | Klasyfikacja przyczyny zmiany | R07 | Wykonanie robót dodatkowych i zamiennych. | zmiana umowy 50064 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dd28b6-45bd-2383-aa0d-d80001d390d1` |
| 12 | Klasyfikacja przyczyny zmiany | N-UNSPEC | 1. zmiana terminu zakończenia robót | zmiana umowy 392927 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dc16a2-5c72-41d3-6929-350011fa2808` |
| 13 | Klasyfikacja przyczyny zmiany | R03 | Wykonawca zwrócił się z wnioskiem na roboty dodatkowe w zakresie przestawienia słupa oświetleniowego wraz z (…) | zmiana umowy 56156 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08de397a-a9b7-59f9-d6d3-f50001cea5d8` |
| 14 | Klasyfikacja przyczyny zmiany | R04 | opóźnieniem w wykonaniu przez Gazownię Jasło przyłącza do sieci gazowej | zmiana umowy 39835 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08db4182-cd2d-02e6-ad68-5a00103b51b8` |
| 15 | Klasyfikacja przyczyny zmiany | R01 | Zmiana umowy wynika z konieczności wykonania robót dodatkowych, nieujętych w dokumentacji projektowej | zmiana umowy 412101 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dd8d39-d533-ec63-eaaa-350001a40689` |
| 16 | Klasyfikacja przyczyny zmiany | R13 | Gmina uzyskała dotację z Programu Rozwoju Obszarów Wiejskich (PROW), z której środki muszą zostać w pełni (…) | zmiana umowy 34284 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dcfd74-f744-7b75-985c-bb00013454c2` |
| 17 | Klasyfikacja przyczyny zmiany | R12 | W związku z powierzeniem przedmiotu zamówienia Podwykonawcy | zmiana umowy 429721 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dedc25-b86b-fbbb-2028-230001aefe5d` |
| 18 | Klasyfikacja przyczyny zmiany | R02 | Wysoki poziom wód gruntowych utrudniający prowadzenie robót ziemnych. | zmiana umowy 48619 (przyczyna i opis z ogłoszenia) | dokładny | nie dotyczy | `/api/notices/08dcf3fa-05e4-a46f-985c-bb000133eb2c` |
| 19 | Propozycja zdarzenia ryzyka | R14 | wykonania kanalizacji teletechnicznej , które jest konieczne dla utrzymania prawidłowego stanu technicznego (…) | przyczyna i opis zmiany w ogłoszeniu BZP | przybliżony | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743208` |
| 20 | Propozycja zdarzenia ryzyka | R03 | zmiana terminu ze względu na kolizję na budowie | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743137` |
| 21 | Propozycja zdarzenia ryzyka | N-UNSPEC | protokół | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743128` |
| 22 | Propozycja zdarzenia ryzyka | R07 | roboty uzupełniające - zmiany o niskiej wartości, na podstawie protokołu - konieczność wykonania robót (…) | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743127` |
| 23 | Propozycja zdarzenia ryzyka | N-CLIENT | Zlecenie dodatkowych (nie planowanych) robót stało się konieczne dla prawidłowego wykonania podstawowego (…) | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743106` |
| 24 | Propozycja zdarzenia ryzyka | R03 | Ponadto wstrzymano roboty w powodu braku ustalenia granic. | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743123` |
| 25 | Propozycja zdarzenia ryzyka | R15 | Z powodu problemów z wydajnością przepompowywania ścieków | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743203` |
| 26 | Propozycja zdarzenia ryzyka | N-COVID | inwazji zbrojnej Federacji Rosyjskiej na Ukrainę skutkujące odpływem znacznej ilości pracowników | przyczyna i opis zmiany w ogłoszeniu BZP | dokładny | nie dotyczy | `/api/evidence?claim_table=risk_event&claim_id=743207` |
| 27 | Cecha inwestycji | rodzaj_robot = budowa | Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj i wybuduj, budżet 7 mln zł brutto, termin 14 (…) | opis użytkownika w analizie AN-2026-0001 | dokładny | nie dotyczy | `/api/analyses/AN-2026-0001` |
| 28 | Cecha inwestycji | dlugosc_km = ok. 6 km? | Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 (…) | opis użytkownika w analizie AN-2026-0004 | dokładny | ok | `/api/analyses/AN-2026-0004` |
| 29 | Cecha inwestycji | formula = zaprojektuj i wybuduj | Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 (…) | opis użytkownika w analizie AN-2026-0004 | dokładny | nie dotyczy | `/api/analyses/AN-2026-0004` |
| 30 | Cecha inwestycji | dlugosc_km = ok. 6 km? | Budowa kanalizacji sanitarnej ok. 6 km, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS | opis użytkownika w analizie AN-2026-0005 | dokładny | ok | `/api/analyses/AN-2026-0005` |
| 31 | Cecha inwestycji | finansowanie = FEnIKS 2021–2027 | Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj i wybuduj, budżet 7 mln zł brutto, termin 14 (…) | opis użytkownika w analizie AN-2026-0003 | dokładny | nie dotyczy | `/api/analyses/AN-2026-0003` |
| 32 | Cecha inwestycji | przepompownie = 3 szt. | Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 (…) | opis użytkownika w analizie AN-2026-0004 | dokładny | ok | `/api/analyses/AN-2026-0004` |
| 33 | Cecha inwestycji | termin_mies = 14 mies. | Budowa kanalizacji sanitarnej ok. 6 km, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS | opis użytkownika w analizie AN-2026-0005 | dokładny | ok | `/api/analyses/AN-2026-0005` |
| 34 | Cecha inwestycji | dlugosc_km = ok. 6 km? | Siec o dlugosci ok. 6 km, ostateczna dlugosc wynikac bedzie z dokumentacji projektowej. | dokument 33366, s. 2 | dokładny | ok | `/api/analyses/AN-2026-0003` |
| 35 | Cecha inwestycji | budzet = 7 mln zł brutto | Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj i wybuduj, budżet 7 mln zł brutto, termin 14 (…) | opis użytkownika w analizie AN-2026-0002 | dokładny | ok | `/api/analyses/AN-2026-0002` |
| 36 | Cecha inwestycji | podsektor = kanalizacja sanitarna | Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj i wybuduj, budżet 7 mln zł brutto, termin 14 (…) | opis użytkownika w analizie AN-2026-0002 | dokładny | nie dotyczy | `/api/analyses/AN-2026-0002` |
| 37 | Uwaga czerwonego długopisu | R01.2 | Siec o dlugosci ok. 6 km, ostateczna dlugosc wynikac bedzie z dokumentacji projektowej. | dokument 33366, s. 2 | dokładny | nie dotyczy | `/api/analyses/AN-2026-0003/redpen/33366` |
| 38 | Uwaga czerwonego długopisu | R05.2: Ciągłość dostaw wody w trakcie robót | zapewnienie ciągłości dostaw wody pitnej do sieci wodociągowej w trakcie prowadzonych robót. | dokument 20119 (pfu), s. 6 | dokładny | nie dotyczy | `/api/documents/20119/file#page=6` |
| 39 | Uwaga czerwonego długopisu | R10.1: Odbiór uzależniony od rozruchu i parametrów | Podstawą do odbioru końcowego będzie protokół z dokonanego rozruchu wszystkich instalacji potwierdzającego (…) | dokument 20119 (pfu), s. 26 | dokładny | nie dotyczy | `/api/documents/20119/file#page=26` |
| 40 | Uwaga czerwonego długopisu | R05.2: Konieczność uzgodnień ze Spółdzielnią Mieszkaniową | Przewody projektować w oparciu o określony w PFU zakres, warunki techniczne do projektowania i budowy wydane (…) | dokument 30011 (pfu), s. 5 | przybliżony | nie dotyczy | `/api/documents/30011/file#page=5` |
| 41 | Uwaga czerwonego długopisu | R05.1: Uzupełnianie braków dokumentacji na koszt wykonawcy | Jeżeli w trakcie wykonywania robót okaże się koniecznym uzupełnienie dokumentów, Wykonawca sporządzi (…) | dokument 30011 (pfu), s. 20 | dokładny | nie dotyczy | `/api/documents/30011/file#page=20` |
| 42 | Uwaga czerwonego długopisu | R08.2: Przeniesienie ryzyka nieprzewidzianych okoliczności (…) | Zaoferowana cena jest ceną ryczałtową i musi zawierać wszelkie koszty wykonawcy związane z prawidłową i (…) | dokument 14531 (swz), s. 22 | dokładny | nie dotyczy | `/api/documents/14531/file#page=22` |
| 43 | Uwaga czerwonego długopisu | R09.1: Błędna minimalna grubość rdzenia dachu | pokrycie dachu – płyta warstwowa z rdzeniem grubości minimum 0 mm | dokument 20119 (pfu), s. 14 | dokładny | nie dotyczy | `/api/documents/20119/file#page=14` |
| 44 | Uwaga czerwonego długopisu | R02.3: Obszar wpisany do rejestru zabytków i brak MPZP | Wymagane jest uzyskanie Decyzji o ustaleniu lokalizacji inwestycji celu publicznego (teren inwestycji nie (…) | dokument 30011 (pfu), s. 10 | przybliżony | nie dotyczy | `/api/documents/30011/file#page=10` |
| 45 | Uwaga czerwonego długopisu | R08.2: Całkowite ryzyko niedoszacowania po stronie wykonawcy | Niedoszacowanie, pominięcie oraz brak rozpoznania zakresu przedmiotu umowy nie może być podstawą do żądania (…) | dokument 22095 (ppu), s. 6 | dokładny | nie dotyczy | `/api/documents/22095/file#page=6` |
| 46 | Uwaga czerwonego długopisu | R02.3: Wymóg uzgodnienia z konserwatorem zabytków | Projekt budowlany musi być wykonany na aktualnej mapie do celów projektowych, uzyskać uzgodnienie z narady (…) | dokument 30011 (pfu), s. 5 | dokładny | nie dotyczy | `/api/documents/30011/file#page=5` |
| 47 | Uwaga czerwonego długopisu | R12.1: Płatność wyłącznie jedną fakturą końcową | Rozliczenie wynagrodzenia za wykonanie przedmiotu umowy nastąpi na podstawie faktury końcowej wystawionej (…) | dokument 22095 (ppu), s. 6 | dokładny | nie dotyczy | `/api/documents/22095/file#page=6` |
| 48 | Uwaga czerwonego długopisu | R09.1: Niemierzalne wymaganie powierzchni budynku SUW | minimalna powierzchnia – intencją jest zachowanie przestrzeni do eksploatacji i konserwacji urządzeń SUW – (…) | dokument 20119 (pfu), s. 14 | dokładny | nie dotyczy | `/api/documents/20119/file#page=14` |
| 49 | Uwaga czerwonego długopisu | R18: Realizacja sieci w podziale na etapy | Rozbudowa sieci kanalizacyjnej na działce nr ewid. 358 na dł. od skrzyżowania z drogą - działka nr ewid. (…) | dokument 14531 (swz), s. 1 | dokładny | nie dotyczy | `/api/documents/14531/file#page=1` |
| 50 | Uwaga czerwonego długopisu | R01.3: Odtworzenie drogi dojazdowej i dróg publicznych | Wykonawca, na własny koszt, wykona odtworzenie drogi dojazdowej, a w przypadku zniszczeń dróg publicznych (…) | dokument 20119 (pfu), s. 23 | dokładny | nie dotyczy | `/api/documents/20119/file#page=23` |
| 51 | Uwaga czerwonego długopisu | R01.1: Rozbieżności między projektem a przedmiarem | W przypadku wystąpienia rozbieżności co do jakości wykonywanych robót i użytych materiałów między (…) | dokument 14531 (swz), s. 8 | dokładny | nie dotyczy | `/api/documents/14531/file#page=8` |
| 52 | Fakt z nowego dokumentu | doc_date = 05.05.2026 | KPOD.03.15-IW.13-0004/25 PROTOKÓŁ KONIECZNOŚCI ANEKSOWANIA UMOWY sporządzony dnia 05.05.2026 w Zagrodnie (…) | Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf, s. 1 | dokładny | ok | `POST /api/documents/upload (dokument organizatora)` |
| 53 | Fakt z nowego dokumentu | R07 (rule) | Opis okoliczności faktycznych 1) W trakcie realizacji zadania stwierdzono konieczność wykonania dodatkowych (…) | Risk_Miner_protokol_koniecznosci_zlawies.docx, s. 1 | dokładny | nie dotyczy | `POST /api/documents/upload (dokument organizatora)` |
| 54 | Fakt z nowego dokumentu | requested_end = 31.12.2025 | W związku z powyższym Gmina Grodzisko Dolne zwraca się z prośbą o wydłużenie terminu do 31.12.2025r. | Risk_Miner_pismo_termin_grodzisko.pdf, s. 1 | dokładny | ok | `POST /api/documents/upload (dokument organizatora)` |
| 55 | Fakt z nowego dokumentu | new_end = 05.12.2025 | Proponowany nowy termin zakończenia realizacji zadania: 05.12.2025 r. | Risk_Miner_protokol_koniecznosci_zlawies.docx, s. 2 | dokładny | ok | `POST /api/documents/upload (dokument organizatora)` |
| 56 | Fakt z nowego dokumentu | R03 (rule) | Wystąpienie kolizji z siecią wodociągową uniemożliwiające posadowienie pompowni numer PM2 | Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf, s. 1 | dokładny | nie dotyczy | `POST /api/documents/upload (dokument organizatora)` |
| 57 | Fakt z nowego dokumentu | delta_value = 151 481,54 zł brutto | Koszt robót dodatkowych ustala się na kwotę: 151 481,54 zł brutto 4. | Risk_Miner_protokol_koniecznosci_zlawies.docx, s. 2 | dokładny | ok | `POST /api/documents/upload (dokument organizatora)` |
| 58 | Fakt z nowego dokumentu | R05 (rule) | które pierwotnie miały pozostać w eksploatacji na podstawie deklaracji przedstawionej przez Inwestora | Risk_Miner_protokol_koniecznosci_zlawies.docx, s. 1 | dokładny | nie dotyczy | `POST /api/documents/upload (dokument organizatora)` |
| 59 | Fakt z nowego dokumentu | delta_months = +1 mies. | 05.03.2026 W związku z koniecznością przedłużenia terminu realizacji przedmiotu umowy o okres 1 miesiąca, (…) | Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf, s. 1 | dokładny | ok | `POST /api/documents/upload (dokument organizatora)` |
| 60 | Fakt z nowego dokumentu | contract_ref = umowa nr 272.4.27.1.0.2025 z dnia 14.02.2025 | Umowa nr 272.4.27.1.0.2025 z dnia 14.02.2025 r. | Risk_Miner_protokol_koniecznosci_zlawies.docx, s. 1 | dokładny | nie dotyczy | `POST /api/documents/upload (dokument organizatora)` |
| 61 | Fakt z nowego dokumentu | kpo_number = KPOD.03.15-IW.13-0004/25 | KPOD.03.15-IW.13-0004/25 PROTOKÓŁ KONIECZNOŚCI ANEKSOWANIA UMOWY sporządzony dnia 05. | Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf, s. 1 | dokładny | nie dotyczy | `POST /api/documents/upload (dokument organizatora)` |
| 62 | Cytat z pola ogłoszenia BZP | contract_change.cause_text | Konieczność zmiany umowy wynika z okoliczności zewnętrznych i o charakterze nadzwyczajnym, których (…) | ogłoszenie 08dedb54-bf14-c8fe-2028-230001aeed66, pole 5.3 | dokładny | nie dotyczy | `/api/notices/08dedb54-bf14-c8fe-2028-230001aeed66` |
| 63 | Cytat z pola ogłoszenia BZP | risk_event.event | Cena jedynej oferty złożonej w postępowaniu przekracza kwotę jaką Zamawiający zamierza przeznaczyć na (…) | ogłoszenie 08db5785-d079-1b8d-bbf2-560011d4a4cc, pole 5.2 | dokładny (w innym polu ogłoszenia) | nie dotyczy | `/api/notices/08db5785-d079-1b8d-bbf2-560011d4a4cc` |
| 64 | Cytat z pola ogłoszenia BZP | contract.value | 69031,89 PLN | ogłoszenie 08dc1117-9b2e-cd97-185f-a900116cc14f, pole 8.2, część 4 (…) | dokładny | nie dotyczy | `/api/notices/08dc1117-9b2e-cd97-185f-a900116cc14f` |
| 65 | Cytat z pola ogłoszenia BZP | risk_event.event | Termin wykonania zamówienia do dnia 31.10.2023 r. | ogłoszenie 08dc263c-9a1b-5b29-476d-c90011cd17aa, pole 5.4.2, zmiana 1 (…) | dokładny (w innym polu ogłoszenia) | nie dotyczy | `/api/notices/08dc263c-9a1b-5b29-476d-c90011cd17aa` |
| 66 | Cytat z pola ogłoszenia BZP | risk_event.event | roboty dodatkowe | ogłoszenie 08dc53af-baaf-bb64-d117-7300015ab082, pole 5.4.2 | dokładny (w innym polu ogłoszenia) | nie dotyczy | `/api/notices/08dc53af-baaf-bb64-d117-7300015ab082` |
| 67 | Cytat z pola ogłoszenia BZP | contract_change.cause_text | Zważywszy, że zgodnie z technologią masy asfaltowej brak jest możliwości natychmiastowego wykonania (…) | ogłoszenie 08dcd954-0d78-b6c6-49f1-3500018c45c3, pole 5.4.4 | dokładny | nie dotyczy | `/api/notices/08dcd954-0d78-b6c6-49f1-3500018c45c3` |
| 68 | Cytat z pola ogłoszenia BZP | risk_event.event | Wydłużenie terminu realizacji umowy w związku z brakiem zatwierdzonego projektu organizacji ruchu przez (…) | ogłoszenie 08dce215-dcae-a7ff-b670-080001888d8e, pole 5.1 | dokładny (w innym polu ogłoszenia) | nie dotyczy | `/api/notices/08dce215-dcae-a7ff-b670-080001888d8e` |
| 69 | Cytat z pola ogłoszenia BZP | risk_event.event | Postępowanie zostało unieważnione, ponieważ oferta z najniższą ceną (2 248 507,13 zł brutto) przewyższa (…) | ogłoszenie 08dc8b8e-edb1-c1d5-1a46-300001aba338, pole 5.2, część 1 (…) | dokładny (w innym polu ogłoszenia) | nie dotyczy | `/api/notices/08dc8b8e-edb1-c1d5-1a46-300001aba338` |
| 70 | Cytat z pola ogłoszenia BZP | contract_change.cause_text | Ze względu na niekorzystne warunki atmosferyczne w szczególności intensywne opady śniegu w połączeniu z (…) | ogłoszenie 08de3e1f-4f2e-8236-d6d3-f50001e7909a, pole 5.4.4, zmiana 2 (…) | dokładny | nie dotyczy | `/api/notices/08de3e1f-4f2e-8236-d6d3-f50001e7909a` |
| 71 | Cytat z pola ogłoszenia BZP | contract_change.cause_text | 1. istniejąca infrastruktura techniczna podziemna zlokalizowana została w ówczesnej skarpie i ułożona została (…) | ogłoszenie 08dd4467-391c-226c-8f1b-b600017bddba, pole 5.4.4, zmiana 2 (…) | dokładny | nie dotyczy | `/api/notices/08dd4467-391c-226c-8f1b-b600017bddba` |
| 72 | Wartość z pola ogłoszenia BZP | contract.value = 16500.00 | 16500 PLN | ogłoszenie 08dc4368-3ee6-ba20-5566-8b00013bf127, pole 8.2 | dokładny | ok | `/api/notices/08dc4368-3ee6-ba20-5566-8b00013bf127` |
| 73 | Wartość z pola ogłoszenia BZP | contract.signed_on = 2022-07-11 | 8.1.) Data zawarcia umowy: 2022-07-11 | ogłoszenie 08db0420-d425-64ca-50bb-3d0011fc1936, pole 8.1, część 9 (…) | dokładny | ok | `/api/notices/08db0420-d425-64ca-50bb-3d0011fc1936` |
| 74 | Wartość z pola ogłoszenia BZP | contract.signed_on = 2025-04-03 | 2025-04-03 | ogłoszenie 08dd728e-0c73-9523-8f1b-b600017e046f, pole 8.1 | dokładny | ok | `/api/notices/08dd728e-0c73-9523-8f1b-b600017e046f` |
| 75 | Wartość z pola ogłoszenia BZP | contract.value = 806061.07 | 806061,07 PLN | ogłoszenie 08df4488-43ae-3945-c1c5-d50001943c94, pole 8.2 | dokładny | ok | `/api/notices/08df4488-43ae-3945-c1c5-d50001943c94` |
| 76 | Wartość z pola ogłoszenia BZP | contract.value = 452411.97 | 452411,97 PLN | ogłoszenie 08dd200a-5d61-5147-a8d2-3c0001c53f3c, pole 8.2 | dokładny | ok | `/api/notices/08dd200a-5d61-5147-a8d2-3c0001c53f3c` |
| 77 | Wartość z pola ogłoszenia BZP | contract.signed_on = 2026-11-09 | 2026-11-09 | ogłoszenie 08df3f0c-b59c-619c-c1c5-d5000193f89d, pole 8.1 | dokładny | ok | `/api/notices/08df3f0c-b59c-619c-c1c5-d5000193f89d` |
| 78 | Wartość z pola ogłoszenia BZP | contract.value = 233564.70 | 8.2.) Wartość umowy/umowy ramowej: 233564,70 PLN | ogłoszenie 08dcc682-7ea7-06e2-82a9-430001458033, pole 8.2, część 1 (…) | dokładny | ok | `/api/notices/08dcc682-7ea7-06e2-82a9-430001458033` |
| 79 | Wartość z pola ogłoszenia BZP | contract.signed_on = 2025-09-02 | 2025-09-02 | ogłoszenie 08ddea29-d0de-a452-ac53-c40001fae814, pole 8.1 | dokładny | ok | `/api/notices/08ddea29-d0de-a452-ac53-c40001fae814` |
| 80 | Wartość z pola ogłoszenia BZP | contract.value = 920602.99 | 920602,99 PLN | ogłoszenie 08ddfb5e-7495-ec4f-d903-3900014f30a6, pole 8.2 | dokładny | ok | `/api/notices/08ddfb5e-7495-ec4f-d903-3900014f30a6` |
| 81 | Wartość z pola ogłoszenia BZP | contract.signed_on = 2025-05-29 | 8.1.) Data zawarcia umowy: 2025-05-29 | ogłoszenie 08dda33e-c145-1caa-eaaa-350001a51080, pole 8.1, część 5 (…) | dokładny | ok | `/api/notices/08dda33e-c145-1caa-eaaa-350001a51080` |

## Niepotwierdzone i uwagi

**1. Data zawarcia umowy (wyjaśnione).** W pierwszym przebiegu data umowy 126312 (11.07.2022) różniła się od pola 8.1
wskazanego ogłoszenia (20.07.2022). Przyczyna: ogłoszenie o wyniku obejmuje kilka części, a pole 8.1 powtarza się dla
każdej części; nasza kopia pól pokazywała pierwsze wystąpienie. Zespół danych dodał do dowodów zakres znaków konkretnego
wystąpienia pola (np. "8.1, część 9 (wystąpienie 3 z 5)") dla 145 799 dowodów w 21 436 ogłoszeniach. Teraz data jest
w zakresie wskazanego wystąpienia dla wszystkich 3 669 takich umów. Dane były poprawne, niejednoznaczne było tylko wskazanie.

**2. Zdarzenia z ogłoszeń o unieważnieniu i o zmianie: dowód wskazuje sąsiednie pole** (5 z 10 cytatów BZP w próbie;
wszystkie cytaty są w treści tego samego ogłoszenia). Przykład: dowód `evidence:4169437` wskazuje pole 5.2 (podstawa
prawna unieważnienia, "art. 255 pkt 3 ustawy"), a cytowane uzasadnienie jest w kolejnym polu. Wniosek jest poprawny, ale
wskazane pole nie pokazuje cytatu. Zgłoszone zespołowi danych: poprawić mapowanie kodów pól przy wyliczaniu zdarzeń.

**3. Wyniki przybliżone** (3, wszystkie AI): różnice tylko w białych znakach, przeniesieniach i znakach tabel; treść
cytatu zgadza się z tekstem strony (wynik dopasowania co najmniej 90 na 100).

## Ograniczenia

- Sprawdzamy, czy cytat i liczby są w źródle. Czy cytat trafnie uzasadnia kod ryzyka, ocenia ekspert w Przeglądzie; trafność kodów mierzymy osobno na 150 opisanych przyczynach (flash-lite 80,0%, przedział 73 do 86%; reguły słownikowe 37,3%).
- Wnioski AI z dokumentów poufnych nie wchodzą do próby: przy wyłączonym modelu w Polsce poufne dokumenty dostają tylko fakty z reguł.
