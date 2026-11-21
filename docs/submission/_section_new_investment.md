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
