# Morning brief, Sun 22.11 (ex ante)

**Live:** https://exante.linek.dev, one-click "Zaloguj się" (Ekspert demo). Code is final on `main`: 27 commits since the start of the night, latest `2a56774`. The site runs `51d2c33`; later commits are docs only.

## Works end to end
- **Jury path (b), new investment:**
  - "Wypełnij przykładem" (fills the text and attaches the example PFU) or your own PDF/DOCX/TXT
  - report (similar cases with n, chances, budget per km), Czerwony długopis, Symulacja, Podział
  - PDF/DOCX pack in the new layout
- **Jury path (a), case base:**
  - Projekty: 22 pilots plus the national tab with 18 689 procedures
  - project card: chat, Podobne przypadki, "Eksportuj rekord" as PDF/DOCX/MD/JSON
  - graph, Dokumenty with "Co się zmieniło"
  - Monitoring map, drill-down to the contract, coloured
  - Przegląd, Katalog, Zapytaj (agent with visible steps)
- **The organizers' 3 documents:** drop them on Źródła. They link to RM-2026-002/005/010 with their changes and causes, and the planted NIP error is flagged. Re-uploading a file reuses the existing one.
- **The 11:00 test:** rehearsed in about 7 s for the record and about 1 min for the analysis. Runbook: `docs/submission/test_1100_runbook.md`.
- **Flags:** 28 of 32 on.
  - **Off and hidden:** `sovereign_switch`, `sector_pack_wizard`, `docs_sample`, `monitoring_replay` (Wehikuł czasu; you asked to hide it).
- **Tests:** backend 365 passed, frontend 193 passed, build OK.

## Decisions taken overnight
- Login is one user type. Black became blue #3056F5, and "wymaga uwagi" is yellow.
- Uploads are always public; you dropped the checkbox. The Polish models stay off on the live site, but they were verified on WCSS: confidential routing 9 of 9, gold-150 Bielik 58.7% vs Gemini 80.0%.
- The AI scan of tender documents: 1 363 proposals with verified quotes, $7 spent. Two new sectors were added: budynki and ciepło.
- Tonight's test records were deleted from the local DB with your OK. The live DB is still the older rehearsal copy until the final restore.

## Known issues
- **Final DB is live** (restored 08:09 UTC, baseline recorded): 1 460 AI risk events, the national tab with 18 689 procedures, 1 517 items in Przegląd.
- There is no "Nowe ryzyko" button: no API exists for it.
- On 1440 px screens the map filter row wraps.
- The Grodzisko scan also gets a REGON checksum item (690581210). It is either an OCR misread or a second planted error.

## Your to-do, in order
1. Done: the final database is restored, the baseline is recorded and the live check passes.
2. **Pick the video:** A (recommended, 1:56), B, C or D, in `docs/submission/video/`. Upload it with an open link.
3. **Review the deck and description:** the deck is `docs/submission/deck/ex-ante-pitch.pdf` (deck D) and the description is `docs/submission/description.md`. Optionally decide whether unapproved AI notes go into an appendix of the analysis PDF.
4. **Decide the licence** (`morning_decisions.md`), then make the repo public around 10:15.
5. **Submit in HackTribe by 10:45:** deck PDF, description, video link, repo link, https://exante.linek.dev.
6. **The live test at 11:00:** follow the runbook. Don't push between 11:00 and 11:45.
7. **Discord:** check every team member has it.
8. **After the event:** rotate the Gemini and OpenRouter keys, and cancel the WCSS job (`ssh wcss scancel 6385732`; it ends 17:15 anyway).
