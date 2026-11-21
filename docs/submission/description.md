# ex ante: Risk Miner dla inwestycji publicznych

**Wiedza ex post, decyzje ex ante.** Cyfrowa pamięć instytucjonalna inwestycji wodno-kanalizacyjnych: automatycznie zasilana baza zrealizowanych umów ze źródłami, zdarzeniami ryzyka i dowodami, oraz analiza nowej inwestycji na tle tego, jak naprawdę kończyły się podobne.

HackNation 2026, zadanie MFiPR „Risk Miner”. Dokumenty towarzyszące: [dokumentacja techniczna](technical.md), [raport z testu](test_report.md), [scenariusz filmu](video_script.md), [prezentacja](deck/), przykładowe eksporty w `exports/sample/`.

---

## 1. Problem

Od 2021 r. w Polsce wykonano 11 222 umowy na roboty wodno-kanalizacyjne, o których BZP ma ogłoszenie o wykonaniu umowy. **30,3% z nich skończyło się po terminie**, łącznie ok. **265 tys. dni opóźnień**, a ponad wartość umów zapłacono **586 mln zł**. 41,6% umów miało co najmniej jedną zmianę. Mediana opóźnienia, gdy już do niego doszło, to 58 dni, a co dziesiąta spóźniona umowa przekroczyła termin o 190 dni lub więcej.

Ta wiedza istnieje, ale jest rozproszona: ogłoszenia o zamówieniu, wyniku, zmianie i wykonaniu umowy w BZP, ogłoszenia TED, orzeczenia KIO, kontrole NIK, rejestry umów, BIP-y gmin i załączniki do SWZ. Zamawiający przygotowujący nową inwestycję nie ma jak zapytać: „jak kończyły się projekty podobne do mojego, dlaczego, i co wpisać do umowy, żeby to się nie powtórzyło?”. Każda instytucja uczy się na własnych błędach, osobno.

## 2. Przyjęty zakres

- **Sektor pilotażowy:** gospodarka wodno-ściekowa (sieci wodociągowe, kanalizacja sanitarna i deszczowa, oczyszczalnie, stacje uzdatniania), **cała Polska**, ogłoszenia z lat 2021–2026.
- **Projekty pilotażowe organizatora:** 22 projekty z pliku MFiPR, wszystkie powiązane z postępowaniami w BZP (22 z 22).
- **Baza krajowa:** 248 642 ogłoszenia BZP (kopia organizatora i bieżące API), 101 016 postępowań, 128 051 umów, 60 293 zmiany umów, 68 755 ogłoszeń o wykonaniu umowy, 354 796 rekordów z innych źródeł (TED, KIO, NIK, Centralny Rejestr Umów, Mapa Dotacji, KPOŚK, GUS, TERYT i inne; razem 23 źródła).
- **Drugi sektor jako dowód skalowalności:** drogi lokalne i regionalne (30 335 wykonanych umów drogowych). Sektor jest opisany wyłącznie danymi w pakiecie `catalogue/drogi/` (podsektory, kody CPV, ryzyka, słownik), bez zmian w kodzie silnika. Wszystkie wpisy pakietu czekają na zatwierdzenie eksperta.
- **Poza zakresem:** podpisane umowy i protokoły odbioru, których nie ma w źródłach publicznych (system przyjmuje je jako wgrywane dokumenty), ocena jakości technicznej rozwiązań projektowych.

## 3. Użytkownicy

Osoby przygotowujące i oceniające inwestycje w administracji rządowej i samorządowej: kierownik projektu w gminie lub spółce wodociągowej przed ogłoszeniem przetargu, ekspert instytucji finansującej, audytor. Interfejs jest po polsku, odpowiedzi mają formę pytania i odpowiedzi („Czy zdążysz w 14 miesięcy? Raczej nie”), a każda liczba ma liczebność próby i odnośnik do źródła. Nie trzeba znać SQL ani statystyki.

Role w aplikacji: **gość** (analiza nowej inwestycji, monitoring, przeglądanie bazy, pytania do pamięci), **ekspert** (kolejka przeglądu, katalog wiedzy, import), **administrator** (ustawienia modeli). Do pokazu jest konto „jurora” tylko do odczytu.

## 4. Główny scenariusz użytkownika

### Ścieżka A: import i automatyczne wzbogacenie projektu

1. **Import (2.1 Import i źródła).** Ekspert wgrywa plik organizatora (XLSX) albo dowolny arkusz lub paczkę dokumentów. Agent importu sprawdza nagłówki, proponuje mapowanie kolumn na pola modelu, waliduje NIP i REGON (sumy kontrolne), numery BZP i KPO, pyta o podstawę VAT kwot, uruchamia próbny import na 50 wierszach i dopiero po zatwierdzeniu importuje całość. Błędy danych (np. wartość przedsięwzięcia niezgodna z kwotami z BZP, brakujące ogłoszenie, niezgodna część zamówienia) trafiają do kolejki przeglądu jako rozbieżności; nic nie jest poprawiane po cichu.
2. **Wzbogacenie.** System sam odnajduje łańcuch: projekt → postępowania → ogłoszenia (o zamówieniu, wyniku, zmianie, wykonaniu) → umowy → zmiany → wykonanie, oraz rekordy z TED, KIO, NIK, CRU i Mapy Dotacji. Połączenia mają metodę (identyfikator, dopasowanie rozmyte, odsyłacz), wynik i wyjaśnienie cech; niepewne czekają na eksperta.
3. **Karta projektu (2.3) i graf powiązań (2.4).** Plan i wykonanie (termin, koszt), przebieg w czasie, zmiany umowy z podstawą prawną (art. 455 Pzp) i przyczyną przypisaną do katalogu ryzyk R01–R18, każdy fakt z numerem ogłoszenia i kodem pola albo stroną dokumentu i cytatem. Graf pokazuje, z którego źródła pochodzi każdy fakt.
4. **Nowe dokumenty projektu (2.5).** Wgrany protokół konieczności lub pismo (PDF z tekstem, DOCX albo skan, który przechodzi OCR) zamienia się w propozycje faktów: zmiana terminu, wartości, przyczyna z kodem ryzyka, z cytatem. System pokazuje „Co się zmieniło” w projekcie i podnosi alert w monitoringu; analizy, które używały tego projektu jako podobnego przypadku, dostają znacznik „nowe dane w przypadku podobnym, uruchom ponownie”.
5. **Przegląd eksperta (3.1).** Kolejka: zdarzenia zaproponowane przez AI, niepewne połączenia, rozbieżności, propozycje do katalogu. Ekspert zatwierdza, poprawia lub odrzuca (z powodem), może cofnąć decyzję i oznaczyć przykład jako wzorcowy; system przelicza podobne propozycje z nowym przykładem. Każda decyzja jest w historii zmian.

### Ścieżka B: analiza nowej inwestycji (kryterium 3)

1. **1.1 Nowa analiza.** Użytkownik opisuje inwestycję („Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS”) i może dołączyć PFU, projekt umowy lub SWZ. System odczytuje cechy jako edytowalne „chipy” (podsektor, formuła, długość, przepompownie, budżet brutto, termin, finansowanie), oznacza niepewne i zadaje pytania uzupełniające („Ile będzie przyłączy?”).
2. **1.2 Raport.** Lejek grupy porównawczej (11 222 → kanalizacja sanitarna 4 287 → 5–10 mln zł 373 → zaprojektuj i wybuduj 82), trzy pytania z odpowiedzią i przedziałem:
   - *Czy zdążysz w 14 miesięcy?* Raczej nie: 34% szans, 8 na 10 podobnych umów trwało 13,6–20,2 mies. (n = 77);
   - *Czy 7 mln zł wystarczy?* 1,17 mln zł za kilometr, więcej niż 68% umów (n = 1 962);
   - *Czy zdążysz przed końcem programu?* 98% szans (termin programu jako założenie eksperta).
   Do tego czerwone flagi z reguł („Termin krótszy niż typowy”), podobne przypadki z wyjaśnieniem i rozbiciem cech, zapisy do umowy z katalogu, ograniczenia analizy oraz wynik sprawdzianu wstecznego prognoz.
3. **1.3 Czerwony długopis.** Tekst PFU i projektu umowy z zaznaczonymi fragmentami: grunty prywatne na trasie, ryzyko gruntu przeniesione na wykonawcę, przekroczenia dróg i kolei; braki, np. „Brak klauzuli waloryzacyjnej (art. 439 Pzp)”, oraz proponowany zapis do wklejenia.
4. **1.4 Symulacja.** Krzywe „kiedy skończysz”, „ile zapłacisz” i „ile przyjdzie ofert” z 20 000 losowań całych umów; przełączniki zmian przed przetargiem (badania gruntu, dłuższy termin, waloryzacja, cena za metr) i pytania „co jeśli”.
5. **1.5 Podział ryzyk i pakiet.** Macierz: kto ponosi które ryzyko (zamawiający, wspólnie, wykonawca), oczekiwany koszt ryzyk z danych, ile wykonawcy doliczą w ofertach; pakiet do akt jako DOCX, PDF, CSV lub JSON z aneksem źródeł.
6. **1.6 Zapytaj pamięć.** Pytania w języku naturalnym („Zaprojektuj i wybuduj a samo wykonanie?”) zamieniane na zapytanie do bazy; odpowiedź ma rolę (obliczenie, wniosek AI, brak danych), pokazuje SQL („Jak to policzyłem”) i można ją zapisać jako rekord.

Wszystkie wyniki są rekordami (analizy `AN-2026-NNNN` z wersjami, pytania `Q-2026-NNNN`), które można filtrować, aktualizować i eksportować.

## 5. Co działa, a co jest zaprojektowane

Stan na 21.11.2026, zgodny z flagami w `config/config.example.yaml`. „Działa” oznacza: ekran korzysta z prawdziwego API na pełnej bazie, przeszedł test automatyczny i sprawdzenie w przeglądarce.

### Działa

| obszar | funkcja |
|---|---|
| Pozyskiwanie danych | 23 źródła z poleceniem ponownego uruchomienia (`riskminer scrape <źródło>`, `riskminer load-all`), surowe pliki z manifestem (URL, data pobrania, sha256), bieżące API BZP |
| Łączenie | 22 z 22 projektów pilotażowych z BZP; krajowe kandydaty połączeń z decyzją: przyjęte, do przeglądu, odrzucone; walidacja NIP/REGON/KPO |
| Import | agent importu z mapowaniem kolumn, regułami, próbą na 50 wierszach i zatwierdzeniem; plik organizatora |
| Dokumenty | PDF z tekstem, DOCX, skany przez OCR; strony i fragmenty do wyszukiwania pełnotekstowego |
| Nowe dokumenty projektu | OCR, fakty z cytatem, łączenie, alert, „Co się zmieniło” (trzy pliki organizatora przechodzą test) |
| Zdarzenia ryzyka | zdarzenia z pól BZP (opóźnienie, dopłata, zmiana, jedna oferta, unieważnienie i inne) oraz przyczyny zmian sklasyfikowane przez AI z cytatem, jako propozycje do przeglądu |
| Karta, graf, dokumenty i historia projektu | 2.3, 2.4, 2.5, 2.6 |
| Przegląd eksperta | kolejka, decyzje z cofnięciem, przykłady wzorcowe i przeliczenie propozycji |
| Katalog wiedzy | edycja ryzyk, zapisów, wag podobieństwa i założeń eksperta z wersjonowaniem, bez programisty |
| Analiza nowej inwestycji | 1.1–1.6 w całości, w tym symulacja, podział ryzyk i pakiet do akt |
| Monitoring | mapa Polski (województwa, powiaty, gminy), sygnały umów po terminie bez ogłoszenia o wykonaniu, obserwowanie, zgłoszenie przypadku, wehikuł czasu odtwarzający ogłoszenia z wybranego dnia |
| Pulpit i ustawienia | liczby krajowe, zadania eksperta, podgląd modeli i miejsc przetwarzania danych (tylko odczyt) |
| Drugi sektor | analiza inwestycji drogowej z pakietu `catalogue/drogi/` |
| Eksport | zbiory danych JSON i CSV (w tym separator średnik dla Excela), pakiet analizy |

### Zaprojektowane lub wyłączone

| funkcja | stan |
|---|---|
| Przełącznik trybu suwerennego w ustawieniach (`sovereign_switch`) | trasowanie dokumentów poufnych do modeli w Polsce jest w kodzie; przełącznik w interfejsie jest ukryty, dopóki model Bielik nie jest stale udostępniony na WCSS |
| Kreator nowego pakietu sektorowego (`sector_pack_wizard`) | zaprojektowany; dziś nowy sektor dodaje się plikami YAML (tak powstał sektor drogi) |
| Animowane postacie na ekranie 1.1 (`jelly`) | gotowe, czeka na włączenie po kontroli dostępności |
| Widok oryginału PDF w Czerwonym długopisie | tylko widok tekstowy stron z zaznaczeniami |
| Wektorowe wyszukiwanie semantyczne | kolumna `chunk.embedding` przygotowana; podobieństwo opisów liczone dziś przez BM25 |
| Założenia eksperta dla dróg | sektor drogi korzysta z założeń wod-kan (zmiany przed przetargiem, podział ryzyk, programy); raport to mówi |

## 6. Wiarygodność i kontrola eksperta

- **Źródło każdej informacji.** Każdy rekord ma `source_id` (URL, data pobrania, sha256, ścieżka do niezmienionego pliku), pochodzenie (źródło, obliczenie, AI) i status przeglądu. Fakty mają dowód: kod pola ogłoszenia albo dokument, stronę i cytat.
- **AI proponuje, ekspert decyduje.** Wyniki AI zapisują się jako propozycje. Cytaty są sprawdzane w tekście strony, a liczby w cytatach. Zatwierdzonych danych AI nie nadpisze: pilnuje tego wyzwalacz w bazie, a dziennik operacji jest tylko do dopisywania.
- **Liczby z niepewnością.** Każda prognoza podaje liczebność próby, przedział (bootstrap, Wilson), poziom pewności i definicję; przy n < 10 zamiast przedziału jest „za mało danych”. Zdania podsumowań powstają z szablonów na liczbach z bazy, nie z modelu językowego.
- **Sprawdzian wsteczny.** Prognozy z danych sprzed 2024 r. sprawdzono na 6 143 umowach zakończonych później: 85% opóźnień zmieściło się w przedziale P10–P90.
- **Wiedza ekspercka bez programisty.** Katalog ryzyk, zapisów umownych, czerwonych flag, wag podobieństwa i założeń (np. skutki badań gruntu przed przetargiem) edytuje się w aplikacji, z wersjami i historią.

## 7. Gdzie przetwarzane są dane

- Aplikacja, baza i pliki: serwer zespołu.
- Dane publiczne: Google Gemini (region globalny), awaryjnie OpenRouter (modele Mistral) wyłącznie dla danych publicznych.
- Dokumenty poufne (np. projekty SWZ i PFU przed publikacją): wyłącznie modele w Polsce (Bielik, PLLuM) na infrastrukturze WCSS we Wrocławiu. Gdy taki model jest niedostępny, część AI jest wstrzymana, a reguły działają dalej; poufny dokument nie trafia do chmury.
- Zmiana modelu lub dostawcy to zmiana w `config/config.example.yaml`, bez zmian w kodzie. Szczegóły i licencje: [dokumentacja techniczna](technical.md).

## 8. Ograniczenia i luki danych

- **Koszt jest dolną granicą.** Odchylenie kosztu liczone jest względem wartości umowy z ogłoszenia o wykonaniu; wcześniejsze aneksy podnoszące wartość są już w tej bazie.
- **Około 25% umów nigdy nie dostaje ogłoszenia o wykonaniu.** Dlatego sygnały monitoringu to „sygnał, nie dowód”.
- **Przyczyny zmian** pochodzą z klasyfikacji AI (ok. 8 na 10 trafień na próbie wzorcowej 150 przyczyn) z regułami słownikowymi jako zapasem; są propozycjami do przeglądu. Wpływ zmian przed przetargiem w symulacji opiera się na umowach z rozpoznaną przyczyną i na założeniach eksperta, więc efekty są skromne i aplikacja to mówi.
- **Długość sieci lub drogi** odczytywana jest z opisów (dla ok. połowy umów); koszt kilometra jest w cenach nominalnych.
- **Dokumenty postępowań** są dostępne dla części projektów; część platform zakupowych blokuje pobieranie automatyczne (rejestrujemy to jako „zablokowane”, bez obchodzenia zabezpieczeń). Ok. 3 tys. skanów wymagało OCR.
- **Prognoza odsetka opóźnień jest zaniżona o ok. 6 pp.** Powodem są umowy w toku w danych uczących; raport pokazuje to ograniczenie.
- **Mapowanie zamawiającego na gminę** opiera się na nazwie i rejestrach; dla ok. 10% zamawiających (związki, spółki poza gminą) lokalizacja jest przybliżona.
- **Sektor drogi** to rozszerzenie pilotażu: jego katalog nie został jeszcze zatwierdzony przez eksperta.

## 9. Dalszy rozwój

Kolejne sektory jako pakiety danych (drogi gotowe do zatwierdzenia; następne: energetyka, budynki publiczne), wyszukiwanie semantyczne na osadzeniach tekstu, stałe udostępnienie Bielika na WCSS i włączenie trybu suwerennego, integracja z obiegiem dokumentów instytucji, cykliczne odświeżanie ze źródeł i alerty dla obserwowanych umów.
