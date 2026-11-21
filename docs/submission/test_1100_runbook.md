# Test na żywo, niedziela 22.11.2026, 11:00 do 11:45: runbook

Organizatorzy dają dwa pliki: **rekord jednego dodatkowego projektu** (jak 22 wiersze z `Risk_Miner_dane_projekty.xlsx`)
i **opis nowej inwestycji** (kilka stron tekstu). Przetwarzamy je bez zmian w kodzie i do **11:45** oddajemy dwa pliki:

1. **eksport rekordu projektu**, plik `SolvroDawid_1_eksport_rekordu_<ID>.pdf`,
2. **analizę nowej inwestycji**, plik `SolvroDawid_2_analiza_nowej_inwestycji_<AN-kod>.pdf`.

Format dowolny, byle z tekstem: wysyłamy PDF z warstwą tekstu (zapas: DOCX, Markdown, JSON z tych samych ekranów).
Próba generalna przeszła 21.11 wieczorem na lokalnej kopii (czasy w punkcie 6, pliki w `docs/submission/dryrun_outputs/`).

---

## 0. Przed 10:45: przygotowanie

1. **Wdrożyć zmiany z nocy na https://exante.linek.dev.** Są tylko lokalnie (bez commita). Bez nich na produkcji
   nie ma przycisku „Eksportuj rekord”, importowany rekord nie łączy się z BZP i nie da się wgrać opisu w TXT.
   Commit, push na `main`, Coolify zbuduje obraz. Zasada „bez zmian w kodzie” obowiązuje od 11:00, więc wdrożenie
   musi się skończyć przed 11:00. Sprawdzenie (dziś zwraca 404, po wdrożeniu ma być 200):

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://exante.linek.dev/api/projects/RM-2026-001/export.json
   curl -s https://exante.linek.dev/api/health
   ```

2. **Sprawdzić produkcję tylko odczytem** (nic nie zapisuje): otwórz https://exante.linek.dev/projekty/RM-2026-001,
   kliknij „Eksportuj rekord”, potem PDF. Ma się pobrać `rekord_RM-2026-001.pdf` z tekstem. Sprawdź też worker
   (bez niego import nie zakończy się, a czerwony długopis nie dostanie uwag AI): w Coolify kontener `worker` ma
   stan Running, a po zalogowaniu https://exante.linek.dev/api/jobs?status=queued zwraca `"total":0` albo małą liczbę.
3. **Zalogować się wcześniej:** https://exante.linek.dev/zaloguj, przycisk „Zaloguj się” (jedno kliknięcie, konto
   „Ekspert (demo)”, pełne uprawnienia). W prawym górnym rogu widać inicjały ED.
4. **Foldery robocze:**

   ```bash
   mkdir -p ~/Desktop/test_1100/wejscie ~/Desktop/test_1100/wynik
   ```

   Przeglądarka zapisuje pobrane pliki w `~/Downloads`.
5. **Zapas lokalny gotowy** (punkt 5.1): baza, API :8000, web :5173 i worker działają na tym komputerze.
6. Przed finalnym zrzutem bazy usuń dane próby (lista i SQL: `docs/submission/dryrun_ids.md`). Produkcja ich nie ma.

## 1. 11:00: odbiór plików (2 min)

1. Zapisz oba pliki do `~/Desktop/test_1100/wejscie/`.
2. Rozpoznaj, który jest który: **rekord** ma kolumny jak zestaw organizatora (Identyfikator rekordu, NIP, Nazwa
   przedsięwzięcia, Identyfikator publiczny...), **opis** to kilka stron zwykłego tekstu.
3. Zanotuj z rekordu: **Identyfikator rekordu** (np. `RM-2026-023`) i **Identyfikator publiczny** (numer KPO albo BZP).
4. Jeśli któryś przyszedł jako tekst w wiadomości, a nie plik: wklej go do pliku `.txt` (rekord jako wiersze
   „Kolumna: wartość” albo wiersz z kolumnami rozdzielonymi `|`, opis jako zwykły tekst) i dalej postępuj jak z plikiem.

## 2. Zadanie A: rekord projektu (cel: 10 min, start ok. 11:02)

1. Otwórz https://exante.linek.dev/zrodla (menu „Więcej”, potem „Import i źródła”).
2. „Wybierz pliki” albo przeciągnij plik rekordu na pole. Działają: **XLSX, CSV, TXT, MD, JSON, DOCX, PDF z tekstem**
   (wiersz z nagłówkami albo tabela/wiersze „Kolumna: wartość”).
3. Agent sam przegląda plik i proponuje mapowanie (kilka sekund). Sprawdź:
   - wywołanie `match_schema` pokazuje „zestaw organizatora”, 23 z 23 (przy innym układzie mniej, to w porządku);
   - w tabeli mapowania kolumny Identyfikator rekordu, Identyfikator odbiorcy, Nazwa przedsięwzięcia, Identyfikator
     publiczny, Adnotacja instytucji są „zgodne”;
   - „Lp.” jako „propozycja” jest normalne (nie wchodzi do bazy).
4. **Pytanie „Kwoty w pliku: netto czy brutto?”** pojawia się tylko, gdy plik ma osobną kolumnę z kwotą. Wybierz to,
   co mówi nagłówek lub opis kolumny. Jeśli plik nie mówi: „Brutto, z VAT.” i zapisz to w wiadomości do organizatorów.
   (Kwoty z „Adnotacji instytucji” wchodzą z podstawą VAT „nieznana”, bez pytania.)
5. „Wykonaj próbny import (50 wierszy)”. Oczekiwane: „1 z 1 wierszy bez błędów”. Jeśli plik zawiera cały zestaw
   (22 stare wiersze + nowy), import doda tylko nowy, a 22 rekordy pilotażowe pominie jako chronione: to poprawne.
   Jeśli nowy rekord ma identyfikator istniejącego pilota (RM-2026-001 do 022), import go nie nadpisze (chroniony);
   wtedy eksportuj kartę tego identyfikatora i opisz różnice w wiadomości. Jeśli wiersz jest odrzucony (np.
   NIP z błędną sumą kontrolną): to zamierzony błąd w danych. Nie poprawiaj pliku. Błędna wartość nie wejdzie do
   bazy, sprawa trafi do Przeglądu, a system i tak znajdzie zamawiającego (po nazwie albo z ogłoszenia BZP).
6. „Zatwierdź i importuj”. Po 5 do 10 s: „Import zakończony” i wiersz
   „Otwórz kartę projektu <ID>, powiązano z BZP: <metoda>, wynik 0,97”. Metody:
   numer ogłoszenia BZP (1,00), numer KPO w ogłoszeniach zamawiającego (0,97), NIP, nazwa, CPV i data (wynik
   dopasowania). Jeśli widzisz „nie znaleziono postępowania w BZP”: idź dalej (punkt 5.3), eksport to opisze.
7. Kliknij „Otwórz kartę projektu”. Sprawdź w minutę: tytuł, NIP, zdanie „Co się stało” (np. „Skończono 13 dni po
   terminie i zapłacono o 11,2% więcej niż w umowie.”), kafle Termin i Koszt, Przebieg (ogłoszenie, umowa, zmiany,
   wykonanie), zdarzenia ryzyka, podobne przypadki. **Nie klikaj „Wzbogać ponownie”** (przeładowuje wszystkie dane, trwa długo).
8. Rozbieżności nowego rekordu (NIP, numer KPO a województwo, TERYT a nazwa województwa, wartość a kwoty z BZP,
   część a podział na części) są w „Przegląd” i w eksporcie (sekcja 8). **Zostaw je otwarte** (nie zatwierdzaj
   ani nie odrzucaj w pośpiechu): eksport pokazuje je jako sprawy do decyzji eksperta, i o to chodzi.
9. Na karcie, prawy górny róg: **„Eksportuj rekord”**, potem **PDF** (zapas: DOCX, Markdown, JSON).
   Plik: `~/Downloads/rekord_<ID>.pdf`. Nie myl z przyciskiem „Eksportuj” obok (to jeden wiersz tabeli projektów).
10. Kopia do wyników:

    ```bash
    cp ~/Downloads/rekord_<ID>.pdf ~/Desktop/test_1100/wynik/SolvroDawid_1_eksport_rekordu_<ID>.pdf
    ```

Co jest w eksporcie rekordu: identyfikacja i finansowanie, powiązane postępowanie BZP z metodą, wynikiem i cechami
dopasowania, umowy, plan i wykonanie (terminy i kwoty z podstawą VAT), zmiany umowy, zdarzenia ryzyka z kodami R
i dowodami (ogłoszenie, pole, cytat), propozycje AI oznaczone jako propozycje, sprawy do przeglądu, dokumenty
i „Co się zmieniło”, lista źródeł (adres, data pobrania, sha256).

## 3. Zadanie B: analiza nowej inwestycji (cel: 20 min, start ok. 11:12)

1. Otwórz https://exante.linek.dev/analizy/nowa (menu „Nowa inwestycja”).
2. **Poufność:** od 21.11 wieczorem ekran nie ma już pola „Dokument jest publiczny”: pliki wgrane tutaj są
   przetwarzane jako publiczne, czyli model AI w chmurze czyta dokument (cechy i uwagi czerwonego długopisu, w próbie 6 do 10
   uwag z cytatami). To właściwe dla dokumentu testowego organizatorów. Jeśli na produkcji pole jednak jest (starsza wersja),
   zaznacz je przed wgraniem pliku: dokument poufny przechodzi tylko przez reguły (model krajowy jest wyłączony, w próbie
   4 sygnały, bez uwag AI). Plik wgrany wcześniej jako poufny wgraj jeszcze raz jako publiczny: system zdejmie poufność.
3. **Wgraj plik opisu** (przeciągnij na pole opisu albo wybierz): PDF, DOCX, DOC, ODT, RTF, TXT. **Nie wklejaj
   tekstu zamiast pliku**: z wklejonego tekstu powstaje raport bez czerwonego długopisu, czyli bez sygnałów z cytatami
   i numerami stron. Opis z wiadomości zapisz do `opis.txt` i wgraj.
4. **Poczekaj, aż zniknie „Czytamy opis i dokumenty…”** (ok. 20 s). Dopiero wtedy sprawdź chipy „Rozumiemy to tak”
   i popraw kliknięciem to, co się nie zgadza z dokumentem (decyzje ręczne):
   - **podsektor**: przedmiot z tytułu (kanalizacja sanitarna, wodociąg, oczyszczalnia, SUW, deszczówka);
   - **długość**: cała sieć (grawitacyjna + tłoczna), bez przyłączy;
   - **budżet**: kwota brutto, którą zamawiający ma na zadanie. Gdy dokument podaje i szacunek, i kwotę zabezpieczoną,
     model raz bierze szacunek brutto, raz kwotę zabezpieczoną (w próbie 11,62 albo 10,8 mln zł). Wybierz kwotę zabezpieczoną,
     bo o nią pyta analiza („czy wystarczy?”); szacunek i tak opisze sygnał AI „Budżet niższy od szacunku”;
   - **termin**: termin realizacji umowy w miesiącach (nie gwarancja, nie sam etap projektowania);
   - formuła, finansowanie, województwo, przepompownie, przyłącza: zwykle dobrze.
5. **„Uruchom analizę”**. Raport jest po kilku sekundach.
6. Raport: zdanie podsumowania, karty pytań (szansa na termin, koszt kilometra, termin programu) z liczbą umów n,
   lejek klasy porównawczej, podobne przypadki.
7. **„Czerwony długopis”**: poczekaj, aż zniknie „Model AI czyta dokument…” (15 do 30 s). Przejdź przez uwagi oznaczone „AI”:
   kliknij, przeczytaj cytat i stronę, trafne **„Zatwierdź”**, błędne **„Odrzuć”** z powodem (min. 3 znaki).
   **Do pakietu wchodzą tylko zatwierdzone uwagi AI** (zasada produktu: AI to propozycja, decyduje ekspert). Pakiet z
   niezatwierdzonymi pokaże tylko „Pominięto N wniosków AI”. Ok. 10 uwag to 2 do 4 min.
8. **„Symulacja”**: obejrzyj, nic nie trzeba ustawiać.
9. **„Podział ryzyk i pakiet”**: zostaw pozycje zalecane, chyba że opis jednoznacznie mówi inaczej. Opcjonalnie dodaj
   do pakietu proponowane zapisy umowne (z Czerwonego długopisu przy uwadze, „Dodaj do PPU”).
10. W polu eksportu: **„PDF”** i **„Pobierz DOCX”**. Pliki: `~/Downloads/AN-2026-XXXX-v1.pdf` i `.docx`.
11. Kopia do wyników:

    ```bash
    cp ~/Downloads/AN-2026-XXXX-v1.pdf ~/Desktop/test_1100/wynik/SolvroDawid_2_analiza_nowej_inwestycji_AN-2026-XXXX.pdf
    ```

Co jest w pakiecie: cechy inwestycji, podsumowanie, klasa odniesienia z n, pytania (szansa na termin, koszt kilometra z n,
termin programu), sygnały ryzyka z cytatem i stroną, rejestr ryzyk, podział ryzyk, podobne przypadki, luki w dokumentach,
proponowane zapisy, ograniczenia, metoda i załącznik ze źródłami i cytatami (z sha256).

## 4. 11:35: sprawdzenie i wysyłka

Eksport rekordu (`SolvroDawid_1_...pdf`):
- [ ] otwiera się i tekst da się zaznaczyć (nie obraz);
- [ ] sekcja 1: identyfikator, NIP, numer KPO/BZP, wartość i dofinansowanie z podstawą VAT;
- [ ] sekcja 2: postępowanie BZP z metodą i wynikiem (albo „Nie znaleziono postępowania w BZP”, wtedy dopisz to w wiadomości);
- [ ] sekcje 4 do 6: plan i wykonanie (brutto), zmiany umowy, zdarzenia z kodami R i cytatami z pól ogłoszeń;
- [ ] sekcja 7: propozycje AI opisane jako propozycje; sekcja 10: źródła z sha256.

Analiza (`SolvroDawid_2_...pdf`):
- [ ] tekst da się zaznaczyć; jest „Sygnały ryzyka” z kolumną „Cytat (strona)”;
- [ ] są n przy liczbach (klasa końcowa, szansa na termin, koszt kilometra), „Podobne przypadki”, „Rejestr ryzyk”, „Podział ryzyk”;
- [ ] nie ma „Pominięto N wniosków AI” (albo odrzuciłeś je świadomie);
- [ ] cechy w „Opis inwestycji” zgadzają się z dokumentem (budżet, termin, długość).

Wyślij oba pliki tam, gdzie organizatorzy wskazali („tutaj”, kanał testu), **przed 11:45**. W wiadomości: identyfikator
rekordu, kod analizy, jedno zdanie o decyzjach ręcznych (np. budżet przyjęty jako kwota zabezpieczona, zatwierdzone
uwagi AI: N z M, rozbieżności rekordu zostawione do przeglądu).

## 5. Gdy coś nie działa

### 5.1 Produkcja nie działa: lokalnie

```bash
docker compose -f ~/Desktop/hacknation-risk-miner/infra/docker-compose.yml up -d db
cd ~/Desktop/hacknation-risk-miner/backend && uv run uvicorn riskminer.api.main:app --port 8000   # terminal 1
cd ~/Desktop/hacknation-risk-miner && scripts/run_worker.sh                                      # terminal 2
cd ~/Desktop/hacknation-risk-miner/frontend && npm run dev                                       # terminal 3
```

Te same kroki na http://127.0.0.1:5173 (logowanie: http://127.0.0.1:5173/zaloguj). Dane lokalne są tą samą bazą co produkcja
(plus rekord próby `RM-DRY-2026-023`, jeśli nie został usunięty; nie koliduje z nowym identyfikatorem).

### 5.2 Ekran importu zawodzi: linia poleceń (lokalna baza)

```bash
cd ~/Desktop/hacknation-risk-miner/backend
uv run riskminer import-record ~/Desktop/test_1100/wejscie/<plik_rekordu> [--vat gross]   # import + powiązanie z BZP, ok. 4 s
uv run riskminer export-project <ID> --fmt pdf --out ~/Desktop/test_1100/wynik/SolvroDawid_1_eksport_rekordu_<ID>.pdf
uv run riskminer export-project <ID> --fmt md  --out ~/Desktop/test_1100/wynik/SolvroDawid_1_eksport_rekordu_<ID>.md
```

`--dry-run` zatrzymuje się po próbnym imporcie. Na produkcji to samo przez API (curl):

```bash
B=https://exante.linek.dev; J=/tmp/rm.cj; H='X-Requested-With: ex-ante'
curl -s -c $J -b $J -X POST -H "$H" $B/api/auth/demo-login >/dev/null
C=$(curl -s -b $J -X POST -H "$H" -F "files=@$HOME/Desktop/test_1100/wejscie/<plik_rekordu>" $B/api/imports | jq -r .code)
curl -s -b $J -X POST -H "$H" $B/api/imports/$C/inspect | jq '.tool_calls[].out'
curl -s -b $J -X POST -H "$H" $B/api/imports/$C/propose-mapping | jq '.status, .questions'
# tylko gdy jest pytanie o netto/brutto:
# curl -s -b $J -X POST -H "$H" -H 'Content-Type: application/json' -d '{"value_vat_basis":"gross"}' $B/api/imports/$C/answers
curl -s -b $J -X POST -H "$H" -H 'Content-Type: application/json' -d '{"rows":50}' $B/api/imports/$C/test-run | jq '.ok, .failed, .failures'
curl -s -b $J -X POST -H "$H" -H 'Content-Type: application/json' -d '{"importer_name":"zestaw organizatora"}' $B/api/imports/$C/approve
JOB=$(curl -s -b $J -X POST -H "$H" $B/api/imports/$C/run | jq -r .job_id)
curl -s -b $J $B/api/jobs/$JOB | jq '.status, .result.projects, .result.link.link.per_project, .error'   # powtarzaj do "done"
curl -s -b $J -o ~/Desktop/test_1100/wynik/SolvroDawid_1_eksport_rekordu_<ID>.pdf $B/api/projects/<ID>/export.pdf
```

### 5.3 Rekord nie powiązał się z BZP

- Ponów samo powiązanie (lokalnie): `uv run riskminer link-imported --rm-ids <ID>`.
- Jeśli postępowania nie ma w naszej bazie (ogłoszenia nowsze niż dane z 21.11): eksport i tak powstanie, sekcja 2 powie
  „Nie znaleziono postępowania w BZP”, a Przegląd ma sprawę „no_procedure_found” albo „bzp_not_found”. Napisz to w
  wiadomości. Nie dociągaj danych z API BZP w trakcie testu (limit 25 zapytań na minutę, długie przeliczenia).

### 5.4 Ekran analizy zawodzi: API (curl)

```bash
D=$(curl -s -b $J -X POST -H "$H" -F "file=@$HOME/Desktop/test_1100/wejscie/<plik_opisu>" -F "sensitivity=public" $B/api/documents/upload | jq -r .document_id)
A=$(curl -s -b $J -X POST -H "$H" -H 'Content-Type: application/json' -d "{\"text\":\"\",\"document_ids\":[$D],\"sensitivity\":\"public\"}" $B/api/analyses | jq -r .code)
sleep 25; curl -s -b $J $B/api/analyses/$A/draft | jq '.features[] | [.key, .display]'      # sprawdź cechy
# poprawka cechy, np. budżet: curl -s -b $J -X PATCH -H "$H" -H 'Content-Type: application/json' -d '{"values":{"budzet":10800000}}' $B/api/analyses/$A/features
curl -s -b $J -X POST -H "$H" $B/api/analyses/$A/run | jq .
sleep 30; curl -s -b $J $B/api/analyses/$A | jq -r '.flags[] | [.origin, .item_id, .title, .quote] | @tsv'
# zatwierdź trafne uwagi AI (po jednej):
# curl -s -b $J -X POST -H "$H" -H 'Content-Type: application/json' -d '{"action":"approve"}' $B/api/analyses/$A/items/<item_id>/decision
curl -s -b $J -o ~/Desktop/test_1100/wynik/SolvroDawid_2_analiza_nowej_inwestycji_$A.pdf $B/api/analyses/$A/pack.pdf
curl -s -b $J -o ~/Desktop/test_1100/wynik/SolvroDawid_2_analiza_nowej_inwestycji_$A.docx $B/api/analyses/$A/pack.docx
```

### 5.5 Inne awarie

- **PDF się nie generuje** (konwerter LibreOffice): pobierz DOCX albo Markdown. Organizatorzy przyjmują Word i Markdown.
- **Model AI w chmurze nie odpowiada**: analiza i tak powstaje z reguł (cechy z dokumentu, 4 sygnały z cytatami w próbie).
  Popraw chipy ręcznie, uruchom, wyślij; napisz w wiadomości, że uwagi AI były niedostępne.
- **Zadania wiszą w kolejce** (import „w toku” ponad minutę, brak uwag AI): worker nie działa. Lokalnie
  `scripts/run_worker.sh`; na produkcji kontener `worker` w Coolify (restart).

## 6. Czasy z próby (21.11, lokalnie, ta sama baza co produkcja)

| Krok | Czas |
|---|---|
| A, przez ekran (automat): wgranie, mapowanie, próba, import z powiązaniem, karta, eksport PDF i Markdown | 6,6 do 9,1 s (XLSX 8,1; CSV 6,6; TXT 9,1; TXT „Kolumna: wartość” 9,1) |
| A, w tym powiązanie z BZP i zdarzenia ryzyka | 0,2 s |
| A, eksport rekordu: JSON / Markdown / DOCX / PDF | poniżej 0,1 s / 0,1 s / 0,1 s / ok. 1 s |
| A, linia poleceń `import-record` (JSON) | 3,7 s |
| B, odczyt cech przez AI po wgraniu | 18 do 21 s |
| B, „Uruchom analizę” | poniżej 1 s (pierwsze uruchomienie po restarcie API ok. 9 s) |
| B, uwagi AI w Czerwonym długopisie | 12 do 17 s po uruchomieniu |
| B, pakiet PDF / DOCX | ok. 1 s / 0,3 s |
| B, cała ścieżka przez ekran (automat, z zatwierdzeniem wszystkich uwag AI) | DOCX 43 do 53 s, PDF 58 s, TXT 40 s, tekst wklejony 20 s |
| B, domyślnie poufny PDF (tylko reguły) | 71 s |
| **Człowiek, z czytaniem i decyzjami (szacunek)** | **A 5 do 8 min, B 12 do 18 min, sprawdzenie i wysyłka 5 min: razem ok. 30 min z 45** |

## 7. Decyzje ręczne w skrócie

| Gdzie | Decyzja | Zalecenie |
|---|---|---|
| Import, pytanie o kwoty | netto czy brutto | jak w nagłówku pliku; bez informacji: brutto i wzmianka w wiadomości |
| Import, odrzucony wiersz lub wartość | poprawiać czy nie | nie poprawiać; to rozbieżność dla eksperta, eksport ją pokaże |
| Przegląd, rozbieżności nowego rekordu | zatwierdzić / odrzucić | zostawić otwarte |
| Nowa inwestycja, poufność | publiczny czy poufny | publiczny (ekran robi to sam; w API `sensitivity=public`) |
| Nowa inwestycja, chipy | budżet, termin, długość, podsektor | sprawdzić z dokumentem; budżet = kwota zabezpieczona brutto |
| Czerwony długopis, uwagi AI | zatwierdzić / odrzucić | zatwierdzić trafne (z poprawnym cytatem), odrzucić z powodem błędne |
| Podział ryzyk | pozycje | zostawić zalecane |

## 8. Co zmieniono 21.11 w nocy (musi być wdrożone przed 11:00)

- Import rekordu: po imporcie rekord przechodzi te same kontrole co rekordy organizatora (NIP, numer KPO a województwo,
  TERYT a nazwa województwa, rodzaj identyfikatora, dofinansowanie większe niż wartość), łączy się z BZP (numer BZP,
  numer KPO powołany w ogłoszeniach zamawiającego, albo NIP, nazwa, CPV i data) i dostaje zdarzenia ryzyka; ekran importu
  pokazuje link do karty. Wcześniej importowany rekord zostawał bez powiązania.
- Import czyta też TXT, MD, JSON, DOCX i PDF z tekstem (wiersz z nagłówkami albo „Kolumna: wartość”), CSV z jednym
  wierszem i dowolnym separatorem, XLSX z arkuszem danych o innej nazwie niż „Projekty”.
- Nowe: `GET /api/projects/{id}/export.{json|md|docx|pdf}` i przycisk „Eksportuj rekord” na karcie projektu;
  linia poleceń `riskminer import-record`, `riskminer link-imported`, `riskminer export-project`.
- Nowa inwestycja: wgranie TXT, MD i RTF; cechy z reguł czytane także z wgranego dokumentu (wcześniej tylko z wklejonego
  tekstu, więc dokument poufny bez modelu dawał pustą analizę); poprawione reguły (termin nie bierze „mieszkańców”,
  podsektor z tytułu, kwota zabezpieczona przed szacunkiem); ponowne wgranie tego samego pliku jako publiczny zdejmuje poufność.
- Pakiet analizy: w tabeli sygnałów kolumna „Cytat (strona)”, uwagi AI oznaczone „[AI, zatwierdzone]”, kwoty w rejestrze
  ryzyk po polsku z podstawą VAT.
