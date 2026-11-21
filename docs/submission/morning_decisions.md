
## LICENCJA

Status: the repository has no LICENSE file; none was added. Choosing the licence is a decision for the team.

What the rules say (`materials/text/02_regulamin.txt`):
- §4 ust. 3: „Zwycięzcy są zobowiązani do zawarcia z Przyrzekającym umowy o przeniesienie autorskich praw majątkowych do utworów wytworzonych w ramach realizacji Zadania (dalej: „Umowa przeniesienia praw”).”
- §4 ust. 6 and 7 list the fields of exploitation (computer program under art. 74 ust. 4, other works under art. 50), including making available on a public website, modification, distribution and permitting third-party derivative works; ust. 7 lit. f covers source code.
- §3 ust. 6 and 10: the prize is paid within 14 days of signing the transfer agreement; if the winner does not sign within 7 days of receiving it, the right to the prize is lost.
- §4 ust. 2: „Uczestnicy zapewniają, że opracowane rozwiązanie jest wolne od wad prawnych oraz nie narusza praw osób trzecich.”
- The model Umowa przeniesienia praw (Załącznik nr 2) is not in `materials/text/`, so its exact terms are unchecked.

What the brief says (`materials/text/01_tresc_zadania.txt`, section 5): the team must supply information on where data is processed and the licence, a list of models, services, libraries and licences, and the repository or source package. It does not require a specific code licence.

Recommendation:
1. Add no open-source licence to the public repo yet. After a win, the economic rights pass to MFiPR, so a licence chosen now by the team may conflict with the transfer. Before the result, the default (all rights reserved) is the safe state.
2. Obtain and read Załącznik nr 2 (the model transfer agreement) now and check that every contributor can sign it (§4 ust. 8: all co-authors sign) and that no third-party code or data breaks §4 ust. 2.
3. If the team wants the repo public as evidence for the jury, state in the README that the code is submitted to the competition and that dependencies are permissive (done). After the transfer, MFiPR decides on the licence.
4. Dependencies are permissive (see `docs/submission/licenses_backend.md` and `licenses_frontend.md`), so they do not block the transfer; the organiser data and the sources with their own terms (see `docs/submission/technical.md` §3) remain third-party content.
