# Pitch notes: 2 minutes live (Sun 15:15)

Deck: version A, https://claude.ai/artifact/RUkSbfTocR6XFtK316WQYE (PDF: `ex-ante-pitch.pdf`).
Every slide also carries longer Polish speaker notes in the deck itself (presenter view).

The script below is about 270 words, which is about 2 minutes at a calm pace. It assumes the live demo runs
inside the 2 minutes on slide 4. If the demo cannot run, stay on slide 4 and say the same lines over it.

## Timing and mapping

| Time | Slide | What happens |
|---|---|---|
| 0:00 to 0:15 | 1 Hook | Numbers only. No product name yet. |
| 0:15 to 0:25 | 2 Problem | Six sources, no memory. |
| 0:25 to 0:35 | 3 Solution | One sentence and the tagline. |
| 0:35 to 1:15 | 4 Demo (path b) | Switch to the app: `/analizy/nowa` → report → Czerwony długopis → symulacja → pakiet. |
| 1:15 to 1:30 | 5 Data (path a) | Back to slides. Say the numbers, skip the chain. |
| 1:30 to 1:45 | 6 Trust | Two numbers: 80–88% and 80% vs 37%. |
| 1:45 to 1:55 | 7 + 8 | One line each: the expert decides, confidential stays in Poland. |
| 1:55 to 2:00 | 10 Ask | The ask and the tagline. Slide 9 is shown only if there is time or a question. |

## Script (Polish)

**[1]** Od 2021 roku w Polsce wykonano 11 222 umowy wodno-kanalizacyjne. Co trzecia skończyła się po terminie:
265 tysięcy dni opóźnień. Ponad wartość umów zapłacono 586 milionów złotych.

**[2]** Ta wiedza istnieje. Leży w BZP, TED, BIP, KIO, NIK i w aneksach. Ale każda gmina uczy się sama.

**[3]** Dlatego zbudowaliśmy ex ante. Wiedza ex post, decyzje ex ante.

**[4, demo]** Opisuję nową inwestycję: kanalizacja, sześć kilometrów, zaprojektuj i wybuduj. Po kilku sekundach
mam raport: podobne zakończone przypadki i dlaczego są podobne, szanse na termin, koszt za kilometr na tle kraju.
Czerwony długopis zaznacza ryzykowne zapisy w PFU i proponuje lepszą klauzulę. Symulacja pokazuje, co daje
na przykład badanie gruntu przed przetargiem. Na końcu podział ryzyk i pakiet do akt.

**[5]** Pod spodem: 23 publiczne źródła, prawie 250 tysięcy ogłoszeń, 22 z 22 projektów pilotażowych powiązanych,
a każda umowa w kraju ma swoją kartę. Nowy dokument, jak protokół od organizatorów, sam się wiąże i pokazuje,
co się zmieniło.

**[6]** Nie prosimy o zaufanie, mierzymy. Na 6 143 umowach, których model nie widział, 80 do 88 procent wyników
mieści się w naszym przedziale. AI trafia przyczynę zmian w 80 procentach, reguły w 37.

**[7, 8]** Każdy wniosek AI zatwierdza ekspert. Dokumenty poufne przetwarzają tylko polskie modele.

**[10]** Prosimy o pilotaż na prawdziwych naborach. ex ante: wiedza ex post, decyzje ex ante. Dziękujemy.

## Facts to have ready for questions

All numbers are on the slides with their `n`. Sources: `GET /api/analytics/headline` (data 20.11.2026),
`GET /api/analytics/backtest`, `GET /api/stats`, `GET /api/sources/summary`, `GET /api/monitoring/signals`,
`docs/impl/llm.md` §3, the be-llm gold-150 eval (`exports/eval/classify_causes_20261121_2027.json`),
`docs/submission/overnight_log.md`.

- Design-build vs build-only: late in 45,3% (n = 1 443) vs 28,1% (n = 9 755).
- Median delay when late 58 days, P90 190 days (n = 3 025).
- Backtest split: trained on contracts finished before 2024 (n = 4 422), tested on later ones
  (delay n = 6 143: 85% inside P10–P90; delay as % of plan 88%; cost n = 6 332: 80%).
- Gold-150 cause classification: flash-lite 80,0% [73,3; 86,0], stronger model 82,7%, EU fallback Mistral 78,0%,
  keyword rules 37,3%.
- Quotes: 85 of 86 verified on the stated page (8 runs on a PFU and a PPU); Red Pen 43 of 43 on 4 public documents;
  own source test 81 of 81 AI conclusions confirmed on the cited page.
- Monitoring: 3 397 ongoing contracts more than 90 days past the planned end (of 3 803 with a signal), computed
  against today's date, so the number moves daily. Say "about 3 400" if asked on Sunday.
- Sovereignty: confidential documents are routed only to Bielik and PLLuM on WCSS. If that model is unavailable,
  the document waits (the app shows an honest 503); it never falls back to a cloud model. Do not claim a live
  Bielik run unless the WCSS job is up on Sunday.
- Roads: 134 287 road notices loaded; the example road analysis uses a comparison group of n = 893
  (73% chance of finishing on time, 0,83 mln zł per km). These are one analysis, not national averages.

## Before Sunday 11:00

- Fill the team names on slide 10 (`[Imię Nazwisko]` placeholders).
- Replace `demo: [adres do sprawdzenia]` on slide 10 with the public URL once the deploy is live, or delete the line.
- Re-check `3 397` on slide 9 against `GET /api/monitoring/signals` on the morning of the submission.
- Export the final PDF from the deck (Share, Export, PDF) or use `ex-ante-pitch.pdf` in this folder.
