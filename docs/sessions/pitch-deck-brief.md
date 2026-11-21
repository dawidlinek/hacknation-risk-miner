# Session brief: pitch deck versions in Claude canvas (`pitch-deck`)

Start a fresh session in `/home/dawid-home-pc/Desktop/hacknation-risk-miner` (shared checkout, no worktree), Opus, effort high.

## Task

Build the **pitch deck** for "ex ante" as Claude canvas artifacts, in **several versions** the user can choose from.

- Use the Artifact tool: first call `action: "quickstart"` with `intent: "slides"` and follow it. The Slides type exports PDF/PPTX.
- The HackTribe submission needs a **PDF of at most 10 slides**.
- Finalists also pitch live, with about 2 minutes of demo, on Sun 15:15.

## 1. Style references

Find the user's earlier decks named **"Rogatka"**, **"Prawo dla Ciebie"** and **"Jak doczłapię"**. Names are approximate and diacritics may vary. Look in three places:

1. Their artifacts: Artifact `action: "list"` with `scope: "all"`, then `action: "read"` on each match.
2. Their Google Drive: load `mcp__google-personal__search_drive_files` via ToolSearch and search by name. "Prawo dla Ciebie" exists there as a Google Doc.
3. Claude canvas design types.

From each deck you find, extract the visual language: layout, type, colour, rhythm, and how numbers are shown. If a deck can't be found, say so and use your own proposals instead.

## 2. Versions (3–4)

- One version in the style of each reference you found.
- **One in the product's own design system**:
  - monochrome, zgrai.pl-like
  - black summary cards
  - a single orange accent meaning "needs attention"
  - Geist fonts
  - the `ex [ante]` wordmark, with "ante" in a black box

  Sources: `design/README.md` §1–§2 and §5, `design/tokens.json`, and the screens canvas at https://claude.ai/artifact/Uw6gRiCAmtK7DHyrg6tKX7.
- Optionally, one bold proposal of your own.

All versions share the same storyline and the same real numbers. Only the design differs.

## 3. Storyline (≤10 slides)

Write in Polish, short sentences, answer first, and show `n` with every number.

1. **Hook.** National numbers: since 2021, 11 222 completed water/sewage contracts; 30% finished late; about 261 000 days of delay in total; 586 mln zł paid above contract values. Verify them against `curl http://127.0.0.1:8000/api/analytics/headline`.
2. **Problem.** Knowledge is scattered across BZP, TED, BIP, KIO, NIK and contract annexes. Institutional memory is missing.
3. **Solution.** ex ante: "Wiedza ex post, decyzje ex ante". A source-backed case base, expert approval of every AI conclusion, and analysis of new investments.
4. **Demo flow (jury path b).** Describe the investment or upload the PFU → report (similar cases, chances, budget per km) → Czerwony długopis → symulacja → podział ryzyk + pakiet DOCX/PDF.
5. **Data and linking (jury path a).**
   - 23 public sources and 250k notices
   - 22/22 pilot projects linked
   - an automatic card for every national contract
   - new documents produce "Co się zmieniło"
6. **Trust.**
   - Quotes verified on the page: 98.8% on PDFs, 43/43 on the test documents.
   - Every AI conclusion approved by an expert, with an audit trail.
   - Backtest: 80–88% of later outcomes fell inside our P10–P90 band.
   - AI cause classification: 80% vs 37% for keyword rules, on 150 gold cases.
7. **Expert control and learning.**
   - review queue
   - catalogue editable without code
   - approved decisions become examples for the model
   - new risk categories proposed (R18)
8. **Sovereignty and architecture.**
   - Confidential documents go only to Polish models (Bielik, PLLuM) on WCSS.
   - Public data goes to Gemini, with an EU-provider fallback (Mistral).
   - The model is swapped in config, so there is no lock-in.
   - Permissive licences only.
9. **Scale.**
   - A new sector is data, not code; roads data is already loaded.
   - Monitoring of ongoing contracts: 3 321 are more than 90 days past their deadline.
10. **Ask, next steps, team.** Use a placeholder for team names; the user fills it in.

Cross-check every figure with `docs/PLAN.md` (§0, §1, §3a, §9), `docs/research/05_bzp_corpus_stats.md`, `docs/submission/overnight_log.md` and the live API. Mark anything you can't verify as `[do sprawdzenia]`; never invent a number.

## 4. Repo outputs

Write only under `docs/submission/deck/`:

- `deck_notes.md`: speaker notes for a 2-minute live pitch, and how they map to the slides.
- `versions.md`: one link per version, plus your recommendation and why.

## Rules

- Never wait for the user, and never use a tool that needs their approval.
- Produce all versions, then pick a recommended one, polish it and export it to PDF, so a final version is ready by morning. The user can still switch.
- No em dashes (U+2014) and no middle dots (U+00B7) anywhere.
- Never mention Claude, Anthropic or any AI assistant on the slides. No emoji.
- Commit nothing. The lead session `local_82c8f33d-4c6d-4615-a1aa-86c2488b1828` commits.
- When done, send the lead a short status with the links.
