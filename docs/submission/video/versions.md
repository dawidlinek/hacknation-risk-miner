# ex ante: demo video, four versions

All versions: 1920x1080, 60 fps, H.264, no audio, Polish on-screen captions (each works muted).
Screens are real captures of https://exante.linek.dev, logged in as "Ekspert (demo)", recorded on 22.11.2026.
Numbers on title cards come from `GET /api/analytics/headline` (data as of 20.11.2026, n on every card);
numbers in captions are read off the screen they sit on (analysis AN-2026-0023, project RM-2026-003 Steklin).

| Version | File | Length | Angle |
|---|---|---|---|
| **A** | `ex-ante-demo-A.mp4` | 1:56 | Problem first: four live numbers, "ta wiedza już istnieje", logo, then path (b) in five steps and path (a): projects, card, graph, documents, monitoring, review, ask. |
| **B** | `ex-ante-demo-B.mp4` | 1:58 | Pure walkthrough, full-screen app: path (b) end to end with more reading time, then path (a) quickly, including the project chat, record export and the catalogue. |
| **C** | `ex-ante-demo-C.mp4` | 1:04 | Teaser: all four numbers on one card, logo, the strongest screen of each step, URL. |
| **D** | `ex-ante-demo-D.mp4` | 1:36 | Question-led (own idea): the questions a municipality asks before a tender ("Czy zdążymy w terminie?", "Co w PFU jest ryzykowne?", "Skąd to wiadomo?"), each answered by a screen. |

Sizes: A 48 MB, B 34 MB (re-encoded at CRF 24 to stay under 50 MB), C 27 MB, D 38 MB. 720p previews (5 to 10 MB) are in
`preview/`. QA contact sheets are in `qa/`. The Remotion sources are in `remotion/` (see its README).

## Recommendation

**A for the submission.** It gives the jury the problem in 12 seconds with sourced numbers, then shows both
required paths in the order of the challenge, and every step is labelled ("Ścieżka b, krok 2 z 5"). Use **C** where a
short clip helps (social post, the opening of the live pitch). **D** is the most memorable story but shows less of
path (a); **B** is the best "how does it work" reference for a juror who wants to see every screen.

## What the captures show, and what to know

- The app is recorded in virtual time (exactly 60 fps). Waiting for the AI to read the PFU, for the analysis to
  compute and for the agent to answer is cut out, so the app looks faster than in real use. No number or label was
  edited.
- Path (b) is one real run: "Wypełnij przykładem" (example description + the public Kaniów PFU), then "Uruchom
  analizę" created **AN-2026-0023**. Report: 82 similar contracts, plan 22 months, about 36% chance on time, 1,81 mln zł
  per km (more expensive than 83% of contracts).
- Dokumenty shows the organizer protokół (Zagrodno) uploaded as a copy with one appended byte, already processed:
  facts with verified quotes and "Co się zmieniło" (planned end 05.05.2026 → 05.06.2026).
- Przegląd shows one real approval (R02 on an RM-2026-020 contract change). Every record created on live is listed in
  `created_records.md`.
- Noticed in the app while filming: on Symulacja of AN-2026-0023 (plan 22 months) the option reads "Termin 18 miesięcy
  zamiast 14" (fixed template text). The captions do not quote it.

## Narration scripts (Polish, for an optional voiceover)

Timings are scene starts in the rendered file; about 2,3 words per second fits.

### A (1:56)

| Start | Screen | Lektor |
|---|---|---|
| 0:00 | 11 222 umów | Od 2021 roku w Polsce wykonano 11 222 umowy wodno-kanalizacyjne. |
| 0:03 | 30% | Prawie co trzecia skończyła się po terminie. |
| 0:06 | 586 mln zł | Ponad wartość umów zapłacono 586 milionów złotych. |
| 0:08 | Źródła | Ta wiedza istnieje: w BZP, TED, KIO, NIK i w aneksach. Ale każda gmina uczy się sama. |
| 0:12 | Logo | Dlatego zbudowaliśmy ex ante. Wiedza ex post, decyzje ex ante. |
| 0:15 | Ścieżka b | Ścieżka pierwsza: nowa inwestycja. |
| 0:17 | Nowa inwestycja | Wklejam opis i PFU. System sam odczytuje cechy: kanalizacja, 4 kilometry, 22 miesiące, i pyta o to, czego brakuje. Uruchamiam analizę. |
| 0:29 | Raport | Grupa porównawcza to 82 podobne umowy z BZP. Szansa na termin około 36 procent, a kilometr droższy niż w 83 procentach umów. Każda liczba ma liczebność próby, a podobne przypadki pokazują, które cechy zdecydowały. |
| 0:41 | Czerwony długopis | Czerwony długopis wskazuje ryzykowne zapisy w PFU, ze stroną, cytatem i propozycją zapisu do umowy. |
| 0:46 | Symulacja | Symulacja pokazuje, jak zmiana przed przetargiem przesuwa krzywą ukończenia. |
| 0:54 | Pakiet | Podział ryzyk liczy, ile wykonawcy doliczą w ofertach, a wszystko trafia do pakietu do akt. |
| 1:01 | Ścieżka a | Ścieżka druga: projekt z pamięci. |
| 1:03 | Projekty, karta | Projekty organizatora są powiązane z BZP. Steklin: 277 dni po terminie i 40 procent ponad umowę, a przebieg z ogłoszeń pokazuje dlaczego. |
| 1:14 | Graf | Graf prowadzi od źródła przez fakt do wniosku. |
| 1:21 | Dokumenty | Nowy dokument z budowy agent czyta etapami i pokazuje, co się zmieniło: termin przesunięty o miesiąc. |
| 1:30 | Monitoring | Monitoring pokazuje cały kraj, a w drążeniu umowy w toku, które już są po terminie. |
| 1:40 | Przegląd | AI tylko proponuje. Ekspert zatwierdza, a historia zapisuje każdą decyzję. |
| 1:46 | Zapytaj | A pamięć można po prostu zapytać. |
| 1:52 | Koniec | ex ante. exante.linek.dev. |

### B (1:58)

| Start | Screen | Lektor |
|---|---|---|
| 0:00 | Logo | ex ante: ryzyka inwestycji wodno-kanalizacyjnych z pamięci tysięcy umów. |
| 0:02 | Ścieżka b | Najpierw nowa inwestycja, w pięciu krokach. |
| 0:04 | Nowa inwestycja | Krok pierwszy: opis i PFU. Jeden przycisk wypełnia przykład z gminy Bestwina. System odczytuje cechy i pyta o liczbę przyłączy. Uruchamiam analizę. |
| 0:16 | Raport | Krok drugi, raport. 82 podobne umowy, przy planie 22 miesięcy około 36 procent szans na termin. Kilometr kosztuje 1,81 miliona złotych, więcej niż w 83 procentach umów. Niżej sygnały z PFU i podobne przypadki z wyjaśnieniem. |
| 0:29 | Czerwony długopis | Krok trzeci, czerwony długopis: uwaga, strona, cytat i proponowany zapis. |
| 0:34 | Symulacja | Krok czwarty, symulacja. Zaznaczam dłuższy termin i badania gruntu, każda zmiana rysuje własną krzywą. |
| 0:43 | Pakiet | Krok piąty, podział ryzyk i pakiet do akt w DOCX albo PDF. |
| 0:50 | Ścieżka a | Teraz projekt, który już się wydarzył. |
| 0:52 | Projekty, karta | Lista projektów i karta Steklina: 277 dni opóźnienia, 40 procent dopłaty, przebieg z ogłoszeń BZP. |
| 1:03 | Czat, eksport | O projekt można zapytać, a rekord wyeksportować do PDF, DOCX, Markdown albo JSON. |
| 1:13 | Graf | Graf pokazuje drogę każdego wniosku do źródła. |
| 1:20 | Dokumenty | Dokument z budowy daje fakty z cytatami i zestawienie, co się zmieniło. |
| 1:29 | Monitoring | Monitoring: województwo, powiat, umowa po terminie. |
| 1:39 | Przegląd, katalog | Ekspert zatwierdza propozycje modelu. Katalog ryzyk ma wersje. |
| 1:48 | Zapytaj | Agent odpowiada z widocznymi krokami. |
| 1:54 | Koniec | ex ante, exante.linek.dev. |

### C (1:04)

| Start | Screen | Lektor |
|---|---|---|
| 0:00 | Liczby | 11 222 umowy, 30 procent po terminie, 265 tysięcy dni opóźnień, 586 milionów ponad wartość umów. |
| 0:04 | Logo | ex ante: wiedza ex post, decyzje ex ante. |
| 0:06 | Nowa inwestycja, raport | Opis i PFU wystarczą, żeby w kilka chwil zobaczyć szanse na termin i koszt kilometra na tle 82 podobnych umów. |
| 0:23 | Czerwony długopis, symulacja, pakiet | Ryzykowne zapisy z cytatem, symulacja zmian i pakiet do akt. |
| 0:38 | Dokumenty, monitoring | Nowe dokumenty i umowy w toku są pod obserwacją. |
| 0:51 | Graf, przegląd | Każdy wniosek ma źródło, a decyzję podejmuje ekspert. |
| 1:00 | Koniec | exante.linek.dev. |

### D (1:36)

| Start | Screen | Lektor |
|---|---|---|
| 0:00 | Pytanie | Gmina planuje kanalizację. Czy zdąży w terminie? |
| 0:02 | 30% | Od 2021 roku 30 procent takich umów skończyło się po terminie. |
| 0:05 | Logo | ex ante odpowiada z tysięcy wykonanych umów. |
| 0:07 | Pytanie 1 | Co wiemy z samego opisu i PFU? |
| 0:09 | Nowa inwestycja | System odczytuje cechy i pyta o brakujące. |
| 0:21 | Pytanie 2 | Zdążymy i starczy pieniędzy? |
| 0:23 | Raport | 82 podobne umowy: około 36 procent szans na termin, a kilometr droższy niż w 83 procentach umów. |
| 0:35 | Pytanie 3 | Co w PFU jest ryzykowne? |
| 0:36 | Czerwony długopis | Czerwony długopis wskazuje zapis, stronę i cytat. |
| 0:42 | Pytanie 4 | Co zmienić przed przetargiem? |
| 0:43 | Symulacja, pakiet | Symulacja pokazuje skutek zmian, a podział ryzyk trafia do pakietu. |
| 0:56 | Pytanie 5 | Skąd to wiadomo? |
| 0:58 | Karta, graf, dokumenty, przegląd | Z ogłoszeń BZP i dokumentów. Każdy fakt ma źródło, a wnioski AI zatwierdza ekspert. |
| 1:20 | Pytanie 6 | Co dzieje się teraz w regionie? |
| 1:22 | Monitoring | Monitoring pokazuje umowy w toku, które już są po terminie. |
| 1:32 | Koniec | ex ante. exante.linek.dev. |

## Licences

- **Remotion** (the video editor) is free for individuals and for companies of up to 3 people under the Remotion
  License; the team is one person, so no company licence is needed. If MFiPR (after the copyright transfer) or a
  larger team re-renders the videos, it needs a Remotion company licence. The rendered MP4 files themselves carry no
  Remotion licence obligation.
- Fonts: Geist and Geist Mono, SIL Open Font License 1.1 (same as the app).
- Capture tooling: Playwright (Apache-2.0). No music, no stock footage, no generated imagery.
