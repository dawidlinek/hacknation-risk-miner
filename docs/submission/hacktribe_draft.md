# HackTribe: draft for the 20:00 checkpoint

Paste into HackTribe (Partner Task: **Risk Miner, MFiPR**). Fields marked [ ] need the team's input.

- **Nazwa projektu:** ex ante
- **Nazwa zespołu:** [ ]
- **Repozytorium:** https://github.com/dawidlinek/hacknation-risk-miner (currently private: make it public, or give the jury access, before Sunday 11:00)
- **Numer stołu:** [ ]

## Wstępny opis (PL)

**ex ante: Risk Miner dla inwestycji publicznych.** Wiedza ex post, decyzje ex ante.

Od 2021 r. w Polsce wykonano 11 184 umowy wodno-kanalizacyjne. Co trzecia skończyła się po terminie: łącznie 261 tys. dni opóźnień i 582 mln zł wypłacone ponad wartość umów. Ta wiedza leży rozproszona w BZP, TED, BIP, orzeczeniach KIO i kontrolach NIK.

ex ante buduje z niej cyfrową pamięć instytucjonalną:

1. **Automatycznie zasilana baza przypadków.** Ponad 113 tys. ogłoszeń BZP (kopia krajowa i API na żywo) oraz TED, lista projektów KPO, KIO, NIK, Centralny Rejestr Umów i dokumenty postępowań. Wszystko jest łączone w łańcuchy projekt, postępowanie, ogłoszenia, umowa, zmiany, wykonanie. Pilotażowe 22 projekty są powiązane w 22 z 22 przypadków, a każdy rekord prowadzi do źródła.
2. **Zdarzenia ryzyka z dowodem.** Opóźnienia, dopłaty i zmiany umów (art. 455 Pzp) mają przyczyny przypisane do katalogu ryzyk R01 do R15. Każdy wniosek AI ma cytat ze strony dokumentu i czeka na zatwierdzenie przez eksperta.
3. **Analiza nowej inwestycji.** Opisz projekt albo wrzuć PFU, a dostaniesz:
   - podobne zakończone przypadki z wyjaśnieniem podobieństwa;
   - szanse na termin i budżet z krajowej grupy porównawczej (z liczebnością próby i niepewnością);
   - koszt za kilometr na tle kraju;
   - Czerwony długopis, czyli ryzykowne zapisy w PFU i PPU wraz z propozycjami klauzul;
   - symulację scenariuszy, podział ryzyk zamawiający / wykonawca;
   - pakiet DOCX do akt.
4. **Kontrola eksperta i monitoring.** Kolejka przeglądu, edytowalny katalog wiedzy bez programisty oraz radar trwających umów po terminie na mapie Polski.

Dokumenty poufne (projekty SWZ i PFU przed publikacją) przetwarzają wyłącznie polskie modele (Bielik, PLLuM) na infrastrukturze WCSS we Wrocławiu. Dane publiczne analizuje Gemini.

## Notes for the team (not for HackTribe)

- Numbers above are from `docs/research/05_bzp_corpus_stats.md`; re-check after the production pipeline recomputes them.
- The repo needs commits pushed before the jury looks at it. The data session is waiting for a yes to commit `backend/` and friends to a branch.
- Every team member needs a Discord account before the final submission.
