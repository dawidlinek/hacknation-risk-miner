# 03: Domain knowledge & analytical methodology (Risk Miner, wod-kan pilot)

> Scope: procurement-law mechanics that produce observable risk signals, a wod-kan risk taxonomy extending the expert catalogue R01–R15, quantitative evidence, small-sample forecasting, similarity scoring, evidence states and confidence, and subsector classification.
> Out of scope (covered elsewhere): data-source APIs (`01_bzp_api.md`) and the tech stack (`04_tech_stack.md`).
> Snapshot date: **2026-11-21**. Legal text checked against the consolidated Pzp **Dz.U. 2026 poz. 793** (state as of 25.05.2026).
> Language convention: narrative in English. Polish is kept for legal terms, notice field labels, catalogue values and contract-clause wording, since those go straight into the Polish UI and YAML.

---

## 0. TL;DR: decisions to implement

1. **The richest structured risk signal is the BZP "Ogłoszenie o wykonaniu umowy"** (form: annex 7 to the BZP notices regulation). It carries the original contract value (gross), the actual completion date, a self-declared "performed on the original deadline?" flag, every contract change with its **legal basis** (art. 455) and free-text **reason**, the total amount paid, and a "performed properly?" flag. It does **not** carry contractual penalties (kary umowne) or the reasons for a delay. Parse it first.
2. **Own baseline (sector prior):** n = 7,105 wod-kan contract-completion notices from 2022–2026 (BZP mirror, §3.1):
   - 31% are self-declared late; 47% finished after the planned date by the dates themselves.
   - 43% had at least one change; 24% paid more than the contract value.
   - Cost growth (paid vs contract): P50 0%, P80 +1.6%, P90 +7.4%. Delay: P80 46 days, P90 107 days.
   - Design-build ("zaprojektuj i wybuduj") is 50% late vs 29% for build-only.
   - Contracts of 5–20 M zł: 47% late, 71% changed.
   Use these numbers as the **shrinkage prior** (§4) and the **"tło sektorowe"** whenever the reference class is small.
3. **The distributions are zero-inflated.** About 76% of contracts end at exactly the contract price, because lump-sum (ryczałt) contracts dominate. Forecast with a **hurdle model**: P(overrun > 0) × conditional size. Do not quote a mean alone.
4. **Most of the cost risk sits before the contract is signed.**
   - In 2022, 31% of wod-kan tender parts were cancelled; 61% of all cancellations cite art. 255 pkt 3 (best price above the budget).
   - The award-to-estimate ratio fell from 0.92 (2022) to 0.71 (2026).
   - So the forecast must separate (a) the estimate→award error from (b) the award→final growth.
5. **Use a two-level risk taxonomy.** Keep the expert's R01–R15 as level 1 and add sector sub-risks (`R02.1 grunt/woda gruntowa`, `R03.1 kolizje`, `R03.2 grunty/służebność`, `R04.2 pozwolenie wodnoprawne`, `R06.1 presja terminu KPO`, `R08.1 waloryzacja`, `R12.1 upadłość wykonawcy`, `R15.1 niski stopień przyłączeń` …). Mark three new level-1 candidates (R16–R18) as `status: proposed`, waiting for expert approval. The full YAML seed is in §2.5.
6. **Similarity** is a weighted sum of per-feature similarities, with weights renormalised over the features that are present. The structured part weighs 0.87 and the text embedding 0.13.
   - The UI shows each feature's contribution `w_i×s_i` ("co przesądziło").
   - It also shows the largest `w_i×(1−s_i)` gaps ("kluczowe różnice").
   - It shows a **coverage** score.
7. **Tiered forecast by effective sample size n_eff:**
   - n_eff ≥ 20: empirical quantiles plus bootstrap confidence intervals.
   - n_eff 8–19: shrinkage to the sector prior (Beta-binomial for probabilities, log-normal for the size of overruns and delays).
   - n_eff 5–7: P50/P80 only, labelled "niska pewność".
   - n_eff < 5: **no percentiles.** Show the cases individually plus the labelled sector prior.
8. **Evidence states:** use 8 states, not 4 (§6). The brief's four are `BRAK_W_PACZCE`, `DOKUMENT_NIE_WSPOMINA`, `BRAK_POTWIERDZENIA` and `POTWIERDZONO_NIE_WYKONANO`. We add `NIECZYTELNY`, `JESZCZE_NIEWYMAGALNY`, `POTWIERDZONO` and `SPRZECZNOŚĆ`. Confidence is shown as **three separate bars** (data quality Q, completeness C, signal→event strength S) plus the product.
9. **Subsector classification:** CPV alone is insufficient. 45231300-8 is shared by water and sewer pipelines. Classify by components detected in the title, description and CPV, then pick the main component by estimated value share. When the top two are within 15 pp, mark them **"równorzędne"** and send to the expert. §7.4 has a worked table for all 22 dataset projects.

---

## 0.1 How the facts in this document were verified

| Item | How verified |
|---|---|
| Pzp art. 28, 30, 34, 222, 224, 255, 264, 433, 436, 439, 447, 448, 452–456, 465, 544 | Read in the consolidated text Dz.U. 2026 poz. 793 (api.sejm.gov.pl ELI PDF) |
| BZP notice forms and fields | Regulation Dz.U. 2020 poz. 2439 (annex list), plus **field labels parsed from real notices** in the BZP mirror `bzp.cytr.us` (224 + 7,144 completion notices, 1,163 change notices, about 12.4k result notices) |
| Gross vs net of "4.4 Wartość umowy" | Empirical check: 6,559 completion notices linked to their result notices. In 97.1% of cases the value equals the awarded **gross** offer price (6.4); only 0.2% equal price/1.23 |
| EIA thresholds | Regulation Dz.U. 2019 poz. 1839, §3 ust. 1 pkt 71, 73, 74, 79, 81 (original text; check the consolidated version before citing in production) |
| Prawo budowlane art. 29 | Consolidated text Dz.U. 2024 poz. 725 |
| Prawo wodne art. 389, 394 | Consolidated text Dz.U. 2024 poz. 1087 |
| KPO deadlines | MFiPR answer of 15.05.2026 to Sejm interpellation 16654 |
| Statistics | Sources listed with URLs in §3. Numbers marked *own analysis* were computed by us from the BZP mirror on 2026-11-21 |

---

## 1. Procurement-law mechanics that produce observable risk signals

### 1.1 Where in the life-cycle the signals are born

| Phase | Public artefact | Observable signal (machine-detectable) | Typical risk codes |
|---|---|---|---|
| Planowanie | WPF (uchwała), budget resolutions, funding agreement (KPO/FEnIKS/PROW/RPO) | WPF item amended: higher "łączne nakłady" or longer "okres realizacji"; funding agreement annex | R13, R06 |
| Przygotowanie | PFU/OPZ, projekt, STWiORB, przedmiar, decyzje | Missing geotechnical survey; "wartości orientacyjne"; private land on the route; no environmental decision (DŚU) / water-law permit | R01, R02, R03, R04 |
| Postępowanie | Ogłoszenie o zamówieniu; SWZ; Q&A; SWZ modifications; **kwota na sfinansowanie** (art. 222 ust. 4); otwarcie ofert; **ogłoszenie o wyniku** | Many questions and modifications; offer deadline extended; 1 offer; price > budget; price < 70% of estimate (art. 224 ust. 2); KIO appeal; cancellation (art. 255 pkt) | R01, R09, R11, R12, R13 |
| Umowa | PPU/SWU (signed contract rarely public) | No or weak waloryzacja (art. 439); penalty cap; term defined as a date not a duration; ryczałt with an uncertain scope | R05, R06, R08 |
| Realizacja | **Ogłoszenie o zmianie umowy** (only art. 455 ust. 1 pkt 3/4), aneksy (BIP), WPF changes, local news | Term extensions; additional works; unforeseen circumstances; contractor replacement | R02, R03, R04, R07, R12 |
| Odbiór/zamknięcie | **Ogłoszenie o wykonaniu umowy** (within 30 days, art. 448) | Late completion; paid > contract; "nienależycie"; "nie wykonano"; number and basis of changes | all (outcome) |
| Ex post | NIK, RIO, KIO, IOI controls; follow-up tenders "dokończenie…" | Findings; a **completion tender** after termination (strong R12 event) | R12, R13, R15 |

### 1.2 Contract changes: art. 454 and art. 455 Pzp (current text)

- **Art. 454**, a *substantial change* (istotna zmiana) needs a new procedure. A change is substantial if, among other things, it would have attracted other bidders, shifts the economic balance in the contractor's favour, significantly extends or reduces the scope, or replaces the contractor outside art. 455 ust. 1 pkt 2.

| Basis | Content (paraphrase of the statute) | Limit | Separate change notice? | eForms BT-200 code (TED) | Risk interpretation for Risk Miner |
|---|---|---|---|---|---|
| **art. 455 ust. 1 pkt 1** | Change foreseen in the notice or contract documents as clear, precise, unambiguous clauses. They define the type and scope of changes and the conditions, and do not alter the general nature. May include price-change rules (waloryzacja). | none ("niezależnie od wartości") | **No.** Visible only in the completion notice or in aneksy | `mod-rev` | Planned flexibility. The **reason text** decides the risk code: termin → R06/R07/R04; waloryzacja → R08; roboty zamienne → R01/R09 |
| **art. 455 ust. 1 pkt 2 lit. a/b/c** | New contractor replaces the old: (a) per review clause; (b) succession (przejęcie, połączenie, podział, przekształcenie, **upadłość, restrukturyzacja**, dziedziczenie, nabycie); (c) zamawiający takes over obligations to subcontractors (art. 465 ust. 1) | - | No (completion notice) | `mod-repl` | **R12 event**: contractor capacity or insolvency. lit. b with "upadłość/restrukturyzacja" means R12.1 is confirmed |
| **art. 455 ust. 1 pkt 3** | Additional works, supplies or services by the same contractor, not included in the base contract, which became necessary. Change of contractor impossible for economic/technical reasons and would cause significant inconvenience or cost | each change ≤ **50%** of the original value | **Yes** (BZP, or TED for EU-level) | `add-wss` | **R01** (incomplete scope) / **R07** (additional works). With "gestor/warunki techniczne" → **R03.1/R04.4** |
| **art. 455 ust. 1 pkt 4** | Necessity caused by circumstances that a diligent zamawiający could not foresee (also price changes); does not modify the general nature | each change ≤ **50%** | **Yes** | `mod-cir` | **R02/R03/R04/R07**; in 2022–23 also inflation-driven waloryzacja of old contracts (**R08.1**) |
| **art. 455 ust. 2** | De minimis: total value < EU threshold **and** < 15% (works) or < 10% (supplies/services) of the original value; no change of general nature | 15% for works | No (completion notice) | `mod-minv` | Small roboty dodatkowe/zamienne; R01/R07 weak |
| **art. 455 ust. 4** | If the contract contains price-change (waloryzacja) clauses, the 50% and 15% limits are computed on the **changed** price | - | - | - | Do not flag a change as "over the limit" without first applying the waloryzacja |

- **Art. 455 ust. 3**, for pkt 3 and 4 the zamawiający (1) may not split changes to evade the Act, and (2) must publish an **ogłoszenie o zmianie umowy** in BZP or send it to the EU Publications Office.
- Consequence: **for EU-level procedures, pkt 3/4 change notices are in TED (eForms "Contract modification notice", BT-200 reason code, BT-201 reason description, BT-202 modification description), while the completion notice still goes to BZP.**
- eForms codes were checked against the TED `modification-justification` codelist. There is also `mod-nons` (non-substantial changes).

**Observed distribution of change bases in wod-kan** (*own analysis*):
- Source: 5,839 change entries in 7,105 completion notices, 2022–2026.
- pkt 1: 59%; ust. 2: 19%; pkt 4: 13%; pkt 3: 8%; pkt 2 (contractor replacement): 0.6%.
- Implication: **about 79% of changes never get their own change notice.** The completion notice is the main source.

**Change notices** (*own analysis*, n = 1,163 wod-kan "ogłoszenia o zmianie umowy", 2022–2026):
- pkt 4: 61%; pkt 3: 39%.
- 52% raise the price.
- Price increase relative to the original contract, for price-raising changes (n = 578): P25 2.2%, **P50 5.5%**, P75 12.7%, **P90 22.9%**.
  - pkt 3: median 5.3%, P90 23.2%.
  - pkt 4: median 5.9%, P90 22.4%.

### 1.3 Price indexation (waloryzacja): art. 436 pkt 4 lit. b, art. 439, art. 440

- **art. 439 ust. 1** (current), a contract for works, supplies or services **concluded for more than 6 months** *must* contain rules for changing the remuneration when material prices or costs change. This version was introduced by the amendment Dz.U. 2022 poz. 2185, in force since **10.11.2022** (per secondary sources). Before that the rule covered only works and services, and only above **12 months**. The current wording was verified in Dz.U. 2026 poz. 793.
- **art. 439 ust. 2**, the contract must specify:
  1. the price/cost change level that entitles a party to request a change, and the initial date for measuring it;
  2. the method: by reference to an index (in particular a GUS index) or to a list of materials/costs;
  3. how the impact on the cost of performance is determined, and the periods in which the change may occur;
  4. the **maximum value of the change** the zamawiający allows.
- **ust. 3**, if the contract is signed more than 180 days after the offer deadline, indexation starts from the offer-opening date.
- **ust. 4**, indexation is symmetrical: prices can go up **and down**.
- **ust. 5**, the contractor must pass the change on to subcontractors when the contract lasts more than 6 months.
- **art. 440**, voluntary indexation in shorter contracts follows ust. 2–4.
- **art. 436 pkt 4 lit. b**, for contracts over **12 months**: mandatory rules for changing the price when VAT/excise, the minimum wage, ZUS/health contributions or PPK change ("ustawowa waloryzacja").
- **Practice and history:**
  - In 2022 prices rose very fast. GUS reports civil-engineering construction prices **+14.8% y/y in Nov 2022**, **+13.2% y/y in Jan 2023**, **+8.8% y/y in Dec 2023**.
  - Many pre-2022 contracts had no or capped indexation. They were changed under **art. 455 ust. 1 pkt 4**. BZP change notices literally say "drastyczny wzrost cen i inflacji…", e.g. an increase of 497,570.75 zł on a 4.07 M zł contract (12%).
- **Signals for R08.1:**
  - (i) PPU of a contract longer than 6 months *without* a waloryzacja clause. This is a legal defect, so it is a red flag.
  - (ii) The trigger threshold is high (≥ 10%), or the cap is low (≤ 5%), or the index is inappropriate (CPI instead of the construction-price index).
  - (iii) The contract duration is set at ≤ 6 months for a scope that is evidently longer. Avoiding the indexation obligation creates schedule pressure (R06).
  - (iv) The contract is signed more than 180 days after the offer deadline.

### 1.4 Other statutory contract content relevant to risk

| Provision | Rule | Why it matters / signal |
|---|---|---|
| **art. 433** (prohibited clauses) | PPU may not provide for: (1) liability for *opóźnienie* unless justified (only *zwłoka*, i.e. culpable delay); (2) penalties for conduct unrelated to the subject matter; (3) liability for circumstances that are solely the zamawiający's; (4) reduction of scope without a minimum value | PPU text violating art. 433 → KIO appeal risk (R11) and disputes (R05) |
| **art. 436** | Contract must state: (1) planned completion **in days/weeks/months/years** (a calendar date only if objectively justified); (2) payment terms; (3) **total maximum contractual penalties**; (4) for > 12 months, penalties for not paying subcontractors and the statutory indexation | A fixed date tied to a funding deadline instead of a duration is an R06.1 signal. A high penalty cap such as ≥ 30% raises the risk premium in prices and the dispute risk |
| **art. 437** | Works contracts: subcontracting procedure, penalties | - |
| **art. 447** | Works contracts > 12 months: payment in parts conditional on proof of paying subcontractors; if paid at the end only, **advances are mandatory** | Single end-payment for a long contract means contractor liquidity risk (R12/R13) |
| **art. 452–453** | Performance bond ≤ **5%** of price (≤ 10% if justified by risk); up to **30%** retained for warranty | A bond above 5% signals the zamawiający's risk perception (R12) |
| **art. 465** | Direct payment to subcontractors; **ust. 7**: repeated direct payments, or direct payments totalling more than **5% of the contract value**, may be grounds for odstąpienie | "bezpośrednia zapłata podwykonawcy" in BIP or uchwały is a **strong R12.1 signal** |
| **art. 456** | Zamawiający may withdraw (odstąpić): (1) within 30 days on a material change of circumstances (public interest); (2) if a change breached art. 454–455, etc. | Termination events |
| **Kodeks cywilny** | art. 483–484 (kara umowna; **§2 miarkowanie**); 471/476 (non-performance, *zwłoka*); 491–492 (withdrawal for zwłoka); 635 with 656 (withdrawal when the contractor is so late that completion on time is unlikely); 636 (wykonanie zastępcze); 632 §2 (court change of a ryczałt); 357¹ (rebus sic stantibus); 647¹ (subcontractor solidarity); 649¹–649⁵ (payment guarantee) | Classify disputes and terminations; "wykonanie zastępcze/zastępcze" in later tenders is a confirmed R12 event |

**Kary umowne are not observable in BZP.** Proxy sources:
- (a) completion notice **5.6 = "Nie"** (self-declared improper performance; only 0.7% of wod-kan contracts);
- (b) the gmina's budget reports: revenue **§0950 "Wpływy z tytułu kar i odszkodowań wynikających z umów"** in the year of completion, in the wod-kan chapters (dział 010 rural water/sanitation infrastructure, dział 900 rozdz. 90001). Check the current budget-classification regulation for exact chapter codes;
- (c) uchwały/WPF and local news ("naliczono kary", "odstąpiono od umowy");
- (d) NIK/RIO findings;
- (e) court rulings (portal orzeczeń sądów powszechnych).

### 1.5 The official BZP notice forms and their exact fields

Regulation of the Minister of Development, Labour and Technology of 23.12.2020 on notices published in BZP (**Dz.U. 2020 poz. 2439**):
- annex 1: ogłoszenie o zamówieniu;
- annex 3: ogłoszenie o wyniku postępowania;
- annex 6: **ogłoszenie o zmianie umowy**;
- annex 7: **ogłoszenie o wykonaniu umowy**;
- annex 9: ogłoszenie o zmianie ogłoszenia.

The field lists below are taken from **real notices** (labels as rendered by e-Zamówienia, 2026). The API names in parentheses are the BZP API `NoticeType` values.

#### 1.5.1 Ogłoszenie o wykonaniu umowy (`ContractPerformingNotice`): annex 7

| Section | Field (label) | Use in Risk Miner |
|---|---|---|
| I | 1.1 Nazwa zamawiającego; 1.3 Krajowy Numer Identyfikacyjny (NIP/REGON); 1.4.x adres, NUTS3; 1.5 Rodzaj zamawiającego | linking, beneficiary type |
| II | 2.1 **Identyfikator postępowania** (OCID `ocds-148610-…`); 2.2 Numer ogłoszenia; 2.3 Wersja; 2.4 Data ogłoszenia | linking; publication lag |
| III | 3.1 Charakter zamówienia (below / above EU thresholds, sectoral); 3.2 Poprzedzone ogłoszeniem? + 3.2.1 numer ogłoszenia o zamówieniu; 3.3 **Współfinansowane z UE?**; 3.4 **Nazwa projektu lub programu**; 3.5 Tryb + podstawa prawna; 3.6 Rodzaj zamówienia; 3.7 Nazwa zamówienia (+ "Umowa dla części nr X"); 3.8 Krótki opis przedmiotu; 3.9 Główny CPV; 3.10 Dodatkowe CPV | subsector, formula, funding, quantities from 3.8 |
| IV | 4.1 **Data zawarcia umowy**; 4.2 **Okres realizacji zamówienia** (date "do RRRR-MM-DD" or duration); 4.3.x **Wykonawca** (name, NIP/REGON, address); 4.4 **Wartość umowy** (empirically **gross**, original); 4.5 Numer ogłoszenia o wyniku (BZP) / o udzieleniu (Dz.Urz. UE) | baseline cost and time; contractor identity |
| V | 5.1 **Czy umowa została wykonana** (Tak/Nie); 5.2 **Termin wykonania umowy** (actual date); 5.3 **Czy umowę wykonano w pierwotnie określonym terminie** (Tak/Nie); 5.4 Informacje o zmianach: 5.4.1 **Liczba zmian**; per change: 5.4.2 Numer zmiany, 5.4.3 **Podstawa prawna zmiany**, 5.4.4 **Przyczyny dokonania zmian** (free text), 5.4.5 Krótki opis zamówienia po zmianie, 5.4.6 **Wartość zmiany**, 5.4.7 Kod waluty, 5.4.8 **Wzrost ceny w związku ze zmianą** (Tak/Nie); 5.5 **Łączna wartość wynagrodzenia wypłacona** (gross); 5.6 **Czy umowa została wykonana należycie** (Tak/Nie); 5.7 requirements checked during performance (e.g. employment under art. 95) | outcome variables; events; causes |

Pitfalls observed in real data:
- **5.3 is self-declared and often inconsistent.** In 10.9% of notices the zamawiający says "Tak" (on time) although 5.2 is more than 7 days after the end date in 4.2. Some treat an aneks-extended date as "pierwotny". Compute both and flag `SPRZECZNOŚĆ`.
- **4.2 may already contain the amended end date.** Prefer the end date from the result notice, SWZ or PPU when available.
- **5.4.6 "Wartość zmiany"** is sometimes the *delta* and sometimes the *new total*. In 3,706 wod-kan change entries with a value, 5.0% fell between 0.8× and 1.6× the contract value, so they almost certainly report the new total. Another 34% are 0, typically term-only changes. The same happens in the change notices' field 5.5.1 (4 of 69 sampled). Rule:
  - if `0.8 < wartość_zmiany / wartość_umowy < 1.6`, treat it as the new total (delta = value − contract);
  - otherwise treat it as the delta;
  - set `parse_confidence = 0.7` for this field.
- **5.5 < 4.4** (6.4% are more than 1% below) means unused scope (zaniechane roboty), deducted penalties, or obmiar/kosztorys settlement. Not automatically "good".
- **No field for penalties, delay reasons or waloryzacja amount.** Reasons appear only inside 5.4.4 when a change was made.
- **Deadline:** within 30 days of performance (art. 448). The UZP commentary dates "wykonanie" from the final acceptance protocol. A missing notice more than 60 days after the planned end is a status signal (`JESZCZE_NIEWYMAGALNY` → `BRAK_W_ŹRÓDLE`), **not** evidence of non-performance.

#### 1.5.2 Ogłoszenie o zmianie umowy (`AgreementUpdateNotice`): annex 6

- **Sections I–IV**, same as above: zamawiający; basic info; procedure (3.1 preceded by a notice + number; 3.2 EU funds; 3.4 tryb; 3.5 rodzaj; 3.6 nazwa; 3.7 opis); contract (4.1 date; 4.2 period; 4.3 contractor; **4.4 value**; 4.5 result-notice number).
- **Section V:**
  - 5.1 **Data zmiany umowy**
  - 5.2 **Podstawa prawna zmiany**, in practice only pkt 3 or pkt 4
  - 5.3 **Przyczyny dokonania zmian**
  - 5.4 **Krótki opis zmiany**
  - 5.5.1 **Wartość zmiany**, 5.5.2 waluta
  - 5.5.3 **Wzrost ceny w związku ze zmianą** (Tak/Nie)
  - 5.6 Wcześniejsze zmiany obligujące do zamieszczenia ogłoszenia
  - 5.7 Numer wcześniejszego ogłoszenia o zmianie
- **Value:** the reason and description texts are the best source of **causes**. Examples seen:
  - "W związku z uzyskaniem warunków technicznych od gestorów sieci TAURON oraz Orange wystąpiła konieczność wykonania robót dodatkowych … nie były przewidziane w PFU" → R03.1 + R01, under design-build.
  - "zmiana lokalizacji studni ze względu na brak jej wykonania w pierwotnej lokalizacji" → R02.1.

#### 1.5.3 Ogłoszenie o wyniku postępowania (`TenderResultNotice`): annex 3 (fields used)

| Field | Use |
|---|---|
| 4.2 części / 4.5.5 Wartość części | parts → separate contracts |
| **4.3 / 4.3.1 Wartość zamówienia (bez VAT)** | **net** estimate (art. 28/34), to compare with the gross price × 1/(1+VAT) |
| 5.1 zakończone umową / unieważnieniem; **5.2 Podstawa prawna unieważnienia**; **5.2.1 Przyczyna** | cancellation events |
| **6.1 Liczba ofert**; 6.1.3 od MŚP; 6.1.6 odrzucone; **6.1.7 z rażąco niską ceną** | competition (R11), low-price risk (R12) |
| **6.2 / 6.3 cena najniższa / najwyższa; 6.4 cena wybranej oferty** (gross) | estimate accuracy; price dispersion |
| 7.1 konsorcjum; 7.2 wielkość przedsiębiorstwa; 7.3.x wykonawca; 7.4 podwykonawcy | contractor-capacity features |

Cancellation bases (art. 255):
- pkt 1, no offers;
- pkt 2, all rejected;
- **pkt 3, the best price exceeds the budget the zamawiający intends to allocate, unless it can increase it;**
- pkt 5, material change of circumstances / public interest;
- pkt 6, an irremediable defect;
- pkt 7, the contractor did not sign or did not provide the bond;
- art. 256, cancellation before the offer deadline;
- art. 257, public funds not granted, if foreseen in the notice.

#### 1.5.4 Other procurement facts used as signals

- **Informacja o kwocie** (art. 222 ust. 4), the gross budget, published on the procurement platform before opening (not in BZP).
- **Informacja z otwarcia ofert** (art. 222 ust. 5).
- **Rażąco niska cena (art. 224 ust. 2)**, the zamawiający *must* request explanations when the total price is **at least 30% below** (a) the estimate + VAT, or (b) the mean of all non-rejected offers.
- **Standstill (art. 264)**, 10 days (electronic) above EU thresholds.
- **KIO** must hear an appeal within **15 days** of receipt (art. 544 ust. 1). An appeal typically adds about 3–6 weeks to award. Also check the KIO ruling for the *subject* of the dispute (OPZ, conditions, RNC).
- **Thresholds:**
  - national (Pzp applies): **170,000 zł net** for proceedings started from 1.01.2026 (Dz.U. 2025 poz. 1173); 130,000 zł before;
  - EU threshold for works 2026–2027: **5,404,000 EUR = 23,291,240 zł** (rate 4.31; UZP notice of 8.12.2025);
  - 2024–2025: 5,538,000 EUR = 25,680,260 zł.

### 1.6 Net vs gross: normalisation rules

| Amount | Where | VAT? | Notes |
|---|---|---|---|
| **Wartość zamówienia** (szacunkowa) | plan, ogłoszenie o wyniku 4.3 | **net** (art. 28: "bez podatku od towarów i usług") | For works based on the kosztorys inwestorski or, for design-build, on the planned costs in the PFU (art. 34); includes options (art. 31 ust. 2); parts are summed (art. 30) |
| **Kwota na sfinansowanie** | platform, before opening (art. 222 ust. 4) | **gross** | Compare with offer prices; basis for art. 255 pkt 3 |
| **Cena oferty** (6.2–6.4) | otwarcie ofert, ogłoszenie o wyniku | **gross** | VAT for wod-kan works is normally 23% |
| **Wartość umowy** (completion/change notice 4.4) | BZP | **gross** (97.1% equal the gross offer price) | Original value, before changes |
| **Łączna wypłata** (5.5) | completion notice | gross | Final paid |
| **Wartość zmiany** (5.4.6 / 5.5.1) | BZP | gross (same basis as 4.4) | delta or new total, see the rule in §1.5.1 |
| **Wartość przedsięwzięcia / projektu** (KPO, CST2021) | funding lists | usually **gross total project cost** incl. design, supervision, promotion; eligible cost may exclude recoverable VAT | **Not** equal to the contract value; the dataset says so explicitly |
| **Dofinansowanie** | funding lists | - | E.g. KPO B3.1.1 grants of about 76–81% of project value in the dataset |

Rules for the analytics module:
- (1) Always store `amount`, `currency`, `vat_basis ∈ {net, gross, unknown}`, `price_date`, `source_field`.
- (2) Compare only like with like. Convert net → gross with the VAT rate from the document; default 23%, flagged `assumed_vat`.
- (3) Express ratios as gross/gross.
- (4) Deflate to a base date with the GUS construction-price index for "obiekty inżynierii lądowej i wodnej" before comparing across years.

### 1.7 Sector-specific administrative law (what to look for)

- **Prawo budowlane:**
  - art. 29 ust. 1 pkt 2 lit. b–c, building **water and sewer networks needs only a zgłoszenie**, not a pozwolenie na budowę;
  - art. 29 ust. 6, a **pozwolenie na budowę is required** when the project requires an EIA (ocena oddziaływania na środowisko) or a Natura 2000 assessment;
  - house connections (przyłącza) are in art. 29 ust. 1 pkt 23 together with art. 29a (plan sytuacyjny);
  - treatment plants (oczyszczalnie) and SUW buildings normally need a pozwolenie na budowę.
- **Decyzja o środowiskowych uwarunkowaniach (DŚU)**, regulation Dz.U. 2019 poz. 1839, §3 ust. 1, "potentially significant" projects:
  - pkt 71, **magistralne** water mains and mains from the SUW to the distribution network (excluding trenchless reconstruction). This is the magistral/distribution distinction from the expert guide (04 §6.3);
  - pkt 73–74, groundwater intakes ≥ 10 m³/h, or ≥ 1 m³/h with another intake within 500 m;
  - pkt 79, treatment plants ≥ **400 RLM**; §2 ust. 1 pkt 40, > 150,000 RLM always significant;
  - pkt 81, **sewer networks ≥ 1 km** total length (excluding trenchless rebuilds, stormwater networks in road or railway land, and house connections).
  - *Consequence:* almost every sewer-network project ≥ 1 km needs at least a screening DŚU. Missing a DŚU in the documents of such a project is an R04.1 signal.
- **Prawo wodne:**
  - **pozwolenie wodnoprawne** is required for, among others: water services and the discharge of treated sewage (szczególne korzystanie z wód); **long-term lowering of the groundwater table** (art. 389 pkt 3); construction of water devices (pkt 6); **pipelines crossing flowing surface waters or flood embankments** (pkt 9);
  - **zgłoszenie wodnoprawne** covers, among others: **permanent dewatering of excavations** (art. 394 ust. 1 pkt 5); works that may change groundwater (pkt 6); **discharge of water from excavations** (pkt 8).
  - Signals: river or stream crossings, "igłofiltry", "odwodnienie wykopów", high groundwater in the geotechnical opinion → R02.1 and R04.2.
- **Land:**
  - the investor's right to use land for construction (oświadczenie, Prawo budowlane);
  - voluntary easements or **służebność przesyłu** (KC art. 305¹–305⁴);
  - otherwise an **administrative restriction by the starosta under art. 124 ugn** (networks are public purposes);
  - road-lane occupation permit and location consent from the road authority (ustawa o drogach publicznych art. 39–40);
  - coordination of utility routes at the starosta's **narada koordynacyjna (ZUD)** (Prawo geodezyjne i kartograficzne).
  - Dataset example RM-2026-014: "przebiega w terenach zielonych stanowiących własność prywatną", a direct R03.2 signal.
- **Obligation to connect:**
  - a property owner must connect to an existing sewer network (ustawa o utrzymaniu czystości i porządku w gminach art. 5 ust. 1 pkt 2);
  - the gmina enforces it by decision (art. 5 ust. 7).
  - NIK found weak enforcement, see §3.2. This drives **R15.1 (low connection rate)**.
- **KPO B3.1.1** ("Inwestycje w zrównoważoną gospodarkę wodno-ściekową na terenach wiejskich"):
  - IOI = MRiRW; voivodeship marshal offices (urzędy marszałkowskie) verify and settle projects;
  - project numbers look like `KPOD.03.15-IW.NN-XXXX/YY`. *Inferred from the dataset, not from official documentation:* `IW.(12+i)` = the i-th voivodeship in alphabetical order (13 = dolnośląskie, 14 = kujawsko-pomorskie, 15 = lubelskie, 21 = podkarpackie, 27 = wielkopolskie, 28 = zachodniopomorskie). This is useful as a cross-check of the beneficiary's TERYT;
  - **deadline:** project completion originally **15.05.2026**, extended to **15.06.2026** for indicator B41aG (if the gmina reported a delay and amended its agreement);
  - KPO indicators must be achieved and documented by **31.08.2026** (RRF Regulation 2021/241); the last Polish payment request goes to the EC on 30.09.2026;
  - causes of delay reported by gminy (interpellation 16654): long procurement, **difficult geological and hydrological conditions**, limited contractor availability, slow administrative procedures.
  - Every KPO-funded contract signed in 2025–2026 therefore carries **R06.1 (deadline compression) and R13.1 (loss of funding)** by construction.

---

## 2. Risk-event taxonomy for wod-kan (extends R01–R15)

### 2.1 Design principles

- **Two levels.**
  - Level 1 = the expert catalogue R01–R15, unchanged. Codes are stable, `status: approved_by_organizer`.
  - Level 2 = sector sub-risks `Rxx.y`, `status: proposed` until an expert approves them.
  - New level-1 candidates **R16–R18** are `status: proposed`. The brief requires an open catalogue where the system proposes categories and an expert approves them.
- **Every record follows the expert grammar:** *warunek/sygnał w dokumentach → możliwe zdarzenie → możliwy wpływ → środki zaradcze*.
- **Risk ≠ event.**
  - A *risk signal* is a fragment of a planning or tender document (SWZ/PFU/PPU/Q&A), with strength S.
  - An *event* is something that happened, evidenced by a notice, an aneks, a protokół, NIK, etc. Events use a closed vocabulary `EV_*` (§2.2) and are linked to risk codes through the `cause` attribution.
- **Effects are measured in the catalogue's units:**
  - `delay_days` = actual − planned end;
  - `delay_rel` = delay / planned duration;
  - `cost_pct` = paid / contract − 1, gross/gross;
  - `budget_pct` = award / (estimate × (1+VAT)) − 1.
  - Each effect carries `n`, `source` and `period`.

### 2.2 Event vocabulary and detection rules (from structured sources)

| Code | Event (PL label) | Detection rule | Source field(s) |
|---|---|---|---|
| `EV_LATE_COMPLETION` | Wykonanie po pierwotnym terminie | `5.3 == "Nie"` OR `(5.2 − planned_end) > 7 d` | completion notice 4.2, 5.2, 5.3; PPU/SWZ term |
| `EV_TERM_EXTENSION` | Zmiana terminu | change with reason/description matching `termin\|przedłuż\|wydłuż` | 5.4.4/5.4.5; change notice 5.3/5.4; aneks |
| `EV_PRICE_INCREASE` | Wzrost wynagrodzenia | `5.4.8 == "Tak"` OR change notice `5.5.3 == "Tak"` OR `5.5 > 4.4 × 1.001` | completion/change notice |
| `EV_PAID_BELOW_CONTRACT` | Wypłata niższa niż wartość umowy | `5.5 < 4.4 × 0.99` | completion notice |
| `EV_ADDITIONAL_WORKS` | Roboty dodatkowe | basis `455 ust.1 pkt 3` OR reason `dodatkow` | change/completion notice |
| `EV_UNFORESEEN_CHANGE` | Zmiana z okoliczności nieprzewidywalnych | basis `455 ust.1 pkt 4` | change/completion notice |
| `EV_DEMINIMIS_CHANGE` | Zmiana de minimis | basis `455 ust.2` | completion notice |
| `EV_SCOPE_REDUCTION` | Ograniczenie/zaniechanie zakresu | reason `zaniecha\|ograniczeni\|rezygnac` OR paid < contract | completion notice |
| `EV_CONTRACTOR_REPLACED` | Zmiana wykonawcy | basis `455 ust.1 pkt 2 lit. a/b/c` | completion notice |
| `EV_NOT_PERFORMED` | Umowa niewykonana / rozwiązana / odstąpienie | `5.1 == "Nie"` | completion notice; BIP |
| `EV_IMPROPER_PERFORMANCE` | Nienależyte wykonanie | `5.6 == "Nie"` | completion notice |
| `EV_COMPLETION_TENDER` | Postępowanie na dokończenie robót | same zamawiający, title `dokończeni\|pozostał\w* zakres\|wykonanie zastępcze`, within 24 months of `EV_NOT_PERFORMED` or of the original contract | BZP ogłoszenie o zamówieniu |
| `EV_TENDER_CANCELLED_BUDGET` | Unieważnienie: cena > kwota | `5.2 ~ art. 255 pkt 3` | result notice |
| `EV_TENDER_NO_OFFERS` | Unieważnienie: brak ofert | `art. 255 pkt 1` | result notice |
| `EV_TENDER_ALL_REJECTED` | Unieważnienie: oferty odrzucone | `art. 255 pkt 2` | result notice |
| `EV_TENDER_DEFECT` | Unieważnienie: wada postępowania | `art. 255 pkt 6` | result notice |
| `EV_REPEAT_TENDER` | Powtórzone postępowanie | same NIP + title similarity > 0.8 + CPV overlap after any cancellation | BZP |
| `EV_SINGLE_OFFER` | Jedna oferta | `6.1 == 1` | result notice |
| `EV_LOW_PRICE_FLAG` | Cena ≥ 30% poniżej szacunku+VAT | `6.4 < 0.7 × 4.3 × 1.23` OR `6.1.7 > 0` | result notice |
| `EV_PRICE_OVER_BUDGET_AWARDED` | Udzielono mimo ceny > kwoty | `6.4 > kwota (222 ust.4)` and contract signed | platform + result notice |
| `EV_KIO_APPEAL` | Odwołanie do KIO (wynik) | KIO ruling linked by zamawiający + subject + date | KIO portal |
| `EV_NIK_FINDING` | Nieprawidłowość w kontroli | NIK/RIO document mentioning the project | NIK/RIO |
| `EV_FUNDING_CHANGE` | Zmiana finansowania / WPF | WPF item: Δ nakłady or Δ okres; aneks to funding agreement | BIP uchwały |
| `EV_LATE_NOTICE` | Opóźniona publikacja ogłoszenia o wykonaniu | `pub_date − 5.2 > 30 d` | completion notice (compliance signal) |
| `EV_LOW_CONNECTION` | Niski stopień przyłączeń / nieosiągnięty wskaźnik | indicator achieved < target; NIK finding | funding reports, NIK, BIP |

### 2.3 Measured effects by cause (sector prior for the catalogue)

*Own analysis*, BZP completion notices 2022–2026, wod-kan, n = 7,105.
- **Method:** a contract is assigned to a cause category when any of its change reasons (5.4.4) matches the category's stems. Categories can overlap.
- **Caveat:** this is an *association*, not causation. Contracts with changes are larger and longer than average.
- **Baseline:** contracts with no change (n = 4,029) have delay P50 −1 d, P75 +1 d, cost P90 0.0%.

| Cause category (keyword stems in 5.4.4) | → risk | n | P(5.3 = late) | delay P50 / P75 (days) | cost growth P50 / P75 / P90 |
|---|---|---|---|---|---|
| projekt/dokumentacja (`projekt\|dokumentac\|błęd\|przedmiar\|PFU`) | R01, R09, R05.1 | 642 | 67% | 46 / 128 | +0.5% / +5.7% / +13.4% |
| roboty dodatkowe/zamienne | R01, R07 | 1,087 | 57% | 23 / 81 | +3.4% / +10.1% / +17.0% |
| grunt / woda gruntowa / geologia | R02.1 | 185 | - | 58 / 127 | 0.0% / +6.5% / +19.7% |
| archeologia / niewybuchy / zanieczyszczenia | R02.3 | 19 (small) | 79% | 116 / 195 | 0.0% / +4.5% / +13.3% |
| kolizje / uzbrojenie / gestorzy | R03.1 | 166 | - | 46 / 124 | +0.6% / +6.2% / +16.1% |
| nieruchomości / właściciele / służebność | R03.2 | 127 | - | 46 / 146 | 0.0% / +3.1% / +7.1% |
| decyzje / pozwolenia / uzgodnienia | R04 | 327 | - | 78 / 184 | 0.0% / +2.4% / +10.0% |
| waloryzacja / wzrost cen | R08.1 | 86 | - | 27 / 126 | +6.5% / +11.2% / +17.0% |
| dostawy / materiały / urządzenia | R12.2 | 241 | - | 46 / 120 | 0.0% / +5.0% / +14.7% |
| wykonawca / podwykonawca / upadłość (noisy) | R12.1 | 99 | 55% | 24 / 111 | 0.0% / +5.6% / +14.4% |
| finansowanie / dofinansowanie | R13 | 132 | 61% | 24 / 93 | 0.0% / +4.0% / +14.8% |
| mieszkańcy / przyłącza | R01.4, R15.1 | 249 | 63% | 46 / 113 | +1.6% / +6.6% / +16.4% |
| warunki atmosferyczne | R16 | 345 | - | 64 / 131 | 0.0% / +2.7% / +11.0% |
| drogi / nawierzchnie / koordynacja | R17 | 204 | 66% | 62 / 134 | +2.1% / +8.5% / +19.5% |
| obmiar / kosztorys powykonawczy | R08.2 | 167 | 38% | 8 / 50 | +2.4% / +8.6% / +19.0% |

**Frequency** of cause categories among the 3,084 contracts that had any change:

| Category | Share |
|---|---|
| termin | 37% |
| roboty dodatkowe/zamienne/zaniechane | 37% |
| projekt/dokumentacja | 21% |
| decyzje/uzgodnienia | 12% |
| pogoda | 12% |
| dostawy | 8% |
| koordynacja/drogi | 8% |
| kolizje | 7% |
| grunt/woda | 6% |
| obmiar | 5% |
| nieruchomości | 5% |
| finansowanie | 4% |
| waloryzacja | 3% |

In the separately published change notices (pkt 3/4 only), the shares are:

| Category | Share |
|---|---|
| roboty dodatkowe | 46% |
| termin | 43% |
| projekt/dokumentacja | 24% |
| drogi/nawierzchnie | 11% |
| grunt/woda | 10% |
| decyzje | 9% |
| kolizje | 7% |
| pogoda | 7% |
| dostawy | 7% |
| nieruchomości | 6% |
| waloryzacja | 3% |

### 2.4 Catalogue index

| Code | Name (PL) | Parent | Status |
|---|---|---|---|
| R01 | Niepełny lub niespójny zakres | - | approved_by_organizer |
| R01.1 | Rozbieżności projekt/przedmiar/STWiORB/PFU | R01 | proposed |
| R01.2 | Zakres orientacyjny w PFU (formuła ZiW) | R01 | proposed |
| R01.3 | Roboty towarzyszące poza zakresem (odtworzenia, zjazdy, przebudowy) | R01 | proposed |
| R01.4 | Niejasna granica zakresu sieć/przyłącza/sięgacze | R01 | proposed |
| R02 | Niedostateczne rozpoznanie stanu istniejącego | - | approved_by_organizer |
| R02.1 | Warunki gruntowo-wodne (woda gruntowa, kurzawka, grunty słabe, skała) | R02 | proposed |
| R02.2 | Nieznany stan istniejącej infrastruktury (przebudowa/modernizacja) | R02 | proposed |
| R02.3 | Archeologia, niewybuchy, zanieczyszczenia gruntu | R02 | proposed |
| R03 | Kolizje, dostęp do terenu i prawa do nieruchomości | - | approved_by_organizer |
| R03.1 | Kolizje z uzbrojeniem (w tym niezinwentaryzowanym) | R03 | proposed |
| R03.2 | Brak prawa do dysponowania gruntem / służebności | R03 | proposed |
| R03.3 | Przekroczenia przeszkód (cieki, drogi wyższej kategorii, kolej) | R03 | proposed |
| R04 | Decyzje, pozwolenia, uzgodnienia podmiotów trzecich | - | approved_by_organizer |
| R04.1 | Decyzja środowiskowa / ocena Natura 2000 | R04 | proposed |
| R04.2 | Pozwolenie / zgłoszenie wodnoprawne | R04 | proposed |
| R04.3 | Pozwolenie na budowę / zgłoszenie / ZUD / konserwator | R04 | proposed |
| R04.4 | Warunki techniczne operatora i gestorów, przepustowość odbiornika | R04 | proposed |
| R05 | Niejasny podział odpowiedzialności | - | approved_by_organizer |
| R05.1 | Ryzyko projektowe i hierarchia dokumentów (ZiW vs buduj) | R05 | proposed |
| R05.2 | Interfejs z operatorem / innym właścicielem sieci | R05 | proposed |
| R06 | Nierealistyczny harmonogram | - | approved_by_organizer |
| R06.1 | Presja terminu dofinansowania (KPO, koniec perspektywy) | R06 | proposed |
| R06.2 | Niedoszacowany czas projektowania i decyzji w ZiW | R06 | proposed |
| R07 | Nieprzewidziane zmiany i roboty dodatkowe (kategoria zdarzeniowa) | - | approved_by_organizer |
| R08 | Model wynagrodzenia niedopasowany do niepewności | - | approved_by_organizer |
| R08.1 | Brak/niewystarczająca waloryzacja (inflacja) | R08 | proposed |
| R08.2 | Ryczałt przy niepewnych ilościach / kosztorys bez limitu | R08 | proposed |
| R09 | Niejednoznaczne lub niemierzalne wymagania techniczne | - | approved_by_organizer |
| R09.1 | Brak mierzalnych parametrów technologicznych (OŚ, SUW) | R09 | proposed |
| R09.2 | Wskazanie marek / niejasna równoważność | R09 | proposed |
| R10 | Niedookreślone próby, rozruch i odbiór | - | approved_by_organizer |
| R10.1 | Rozruch technologiczny OŚ/SUW | R10 | proposed |
| R10.2 | Odbiory sieci: inspekcja TV, szczelność, inwentaryzacja | R10 | proposed |
| R11 | Postępowanie podatne na odwołanie / ograniczenie konkurencji | - | approved_by_organizer |
| R11.1 | Unieważnienie: cena > budżet, powtórzone postępowanie | R11 | proposed |
| R11.2 | Brak ofert / jedna oferta / nadmierne warunki | R11 | proposed |
| R11.3 | Odwołanie do KIO | R11 | proposed |
| R12 | Niewystarczająca zdolność wykonawcy / łańcucha dostaw | - | approved_by_organizer |
| R12.1 | Niewypłacalność / upadłość wykonawcy, odstąpienie | R12 | proposed |
| R12.2 | Długie terminy dostaw urządzeń i materiałów | R12 | proposed |
| R12.3 | Rażąco niska cena / agresywna oferta | R12 | proposed |
| R13 | Finansowanie, budżet, płatności | - | approved_by_organizer |
| R13.1 | Utrata lub obniżenie dofinansowania | R13 | proposed |
| R13.2 | Luka budżetowa / zmiany WPF | R13 | proposed |
| R14 | Nadmierne koszty eksploatacji | - | approved_by_organizer |
| R14.1 | Mały przepływ / długie tłoczne / energochłonność | R14 | proposed |
| R15 | Nieosiągnięcie efektu | - | approved_by_organizer |
| R15.1 | Niski stopień przyłączeń (RLM, liczba osób) | R15 | proposed |
| R15.2 | Nieosiągnięte parametry oczyszczania / jakości wody | R15 | proposed |
| **R16** | **Warunki atmosferyczne i sezonowość** | - | **proposed (new L1)** |
| **R17** | **Koordynacja z infrastrukturą i inwestycjami innych podmiotów (drogi, kolej, inne sieci, odtworzenia)** | - | **proposed (new L1)** |
| **R18** | **Zależność efektu od zadań powiązanych (sieć ↔ oczyszczalnia/SUW/kolektor innego podmiotu)** | - | **proposed (new L1)** |

How the new L1 candidates were chosen:
- **R16**, weather is the #2 cause of stoppages in site observation (Rybka et al. 2016: 25% of stoppages). It is cited in 12% of changed wod-kan contracts (BZP). R01–R15 have no exogenous-event category.
- **R17**, roads, surfaces and coordination appear in 11% of change notices and carry the largest cost tail (P90 +19.5%).
- **R18**, the expert guide (04 §3.3, §4.3, §6.1, §7.5) repeatedly stresses dependence on other tasks and entities. The dataset has concrete cases:
  - RM-2026-002, network "zostanie wpięta do realizowanej obecnie oczyszczalni";
  - a BZP change notice, "podłączenie … do sieci kanalizacyjnej w gminie Wolsztyn".

### 2.5 YAML seed (`risk_catalogue.wodkan.yaml`)

Conventions:
- `patterns` are case-insensitive Python regexes over normalised text (lower-case, Polish diacritics kept). Apply them to the document types listed in `doc_types`.
- `strength` is the expert-prior probability that the signal is followed by the event in a comparable project. It is updated with approved cases (§6.3).
- `effects.empirical` refers to §2.3.
- `checklist_refs` point to the expert guide `04_poradnik` items.

```yaml
schema_version: 1
sector: wod-kan
effect_units: {delay_days: "dni (rzeczywisty − planowany koniec)", cost_pct: "wypłata/umowa − 1 (brutto/brutto)", budget_pct: "cena wybrana/(wartość zamówienia × (1+VAT)) − 1"}
default_sources:
  BZP_2022_2026: "Analiza własna: ogłoszenia o wykonaniu umowy BZP 2022–2026, wod-kan, n=7105 (kopia bzp.cytr.us, 2026-11-21)"
  BZP_CHG_2022_2026: "Analiza własna: ogłoszenia o zmianie umowy BZP 2022–2026, wod-kan, n=1163"
  BZP_RES_2022_2026: "Analiza własna: ogłoszenia o wyniku BZP 2022–2026, wod-kan, n=9414 części"

risks:
- id: R01
  name: Niepełny lub niespójny zakres
  status: approved_by_organizer
  effects_text: Błędna wycena, pominięcie lub dublowanie robót, zmiana zakresu, roboty dodatkowe, roszczenie albo spór o wynagrodzenie.
  children: [R01.1, R01.2, R01.3, R01.4]

- id: R01.1
  parent: R01
  name: Rozbieżności między projektem, przedmiarem, STWiORB i PFU
  status: proposed
  phases: [przygotowanie, postepowanie, realizacja]
  formula: [buduj, zaprojektuj_i_wybuduj]
  signals:
    - {doc_types: [QA], patterns: ['przedmiar\w* nie (zawiera|uwzględnia|obejmuje)', 'brak (pozycji|w przedmiarze)', 'rozbieżnoś\w* (między|pomiędzy)', 'niezgodnoś\w* (projektu|przedmiaru|dokumentacji)'], strength: 0.45}
    - {doc_types: [SWZ_MOD], patterns: ['zmian\w* (przedmiaru|dokumentacji projektowej|STWiORB)', 'zamieszcza zmieniony przedmiar'], strength: 0.40}
    - {doc_types: [meta], rule: "liczba pytań w Q&A / wartość zamówienia [mln zł] > P75 grupy referencyjnej", strength: 0.30}
    - {doc_types: [meta], rule: "termin składania ofert przesunięty ≥ 2 razy (ogłoszenia o zmianie ogłoszenia)", strength: 0.30}
  events: [EV_ADDITIONAL_WORKS, EV_PRICE_INCREASE, EV_TERM_EXTENSION]
  notice_evidence: {legal_basis: ['455 ust. 1 pkt 3', '455 ust. 2', '455 ust. 1 pkt 1'], reason_patterns: ['nieujęt\w* w (przedmiarze|dokumentacji)', 'błęd\w* (projekt|w dokumentacji)', 'roboty (dodatkowe|zamienne)']}
  effects:
    empirical: {category: projekt/dokumentacja, n: 642, p_late: 0.67, delay_days: {p50: 46, p75: 128}, cost_pct: {p50: 0.005, p75: 0.057, p90: 0.134}, source: BZP_2022_2026}
    literature: "Rybka & Bondar-Nowakowska 2013: projekt zamawiającego (Red Book) – 92 zmiany dokumentacji, koszt 14,42% kwoty kontraktu; ZiW (Yellow Book) – 1 zmiana, 7,01%."
  causes: [pośpiech w przygotowaniu dokumentacji, nieaktualne mapy do celów projektowych, długi czas między projektem a przetargiem, brak weryfikacji przedmiaru]
  mitigations: [niezależna weryfikacja dokumentacji i przedmiaru przed ogłoszeniem, aktualizacja projektu starszego niż 2 lata, hierarchia dokumentów w umowie, ceny jednostkowe do rozliczania robót dodatkowych]
  clauses:
    - "W przypadku rozbieżności pomiędzy dokumentami obowiązuje następująca kolejność ważności: 1) umowa, 2) SWZ wraz z wyjaśnieniami i zmianami, 3) dokumentacja projektowa, 4) STWiORB, 5) przedmiar robót (charakter pomocniczy)."
    - "Roboty nieujęte w dokumentacji, niezbędne do prawidłowego wykonania przedmiotu umowy, wykonawca wykona po sporządzeniu protokołu konieczności; ich wartość ustala się według cen jednostkowych z kosztorysu ofertowego, a w razie ich braku – według średnich stawek i cen SEKOCENBUD z kwartału poprzedzającego wykonanie robót (R, S, Kp, Z)."
  checklist_refs: ['04:3.5.1']

- id: R01.2
  parent: R01
  name: Zakres orientacyjny w PFU (formuła zaprojektuj i wybuduj)
  status: proposed
  formula: [zaprojektuj_i_wybuduj]
  signals:
    - {doc_types: [PFU, OPZ, NOTICE_DESC], patterns: ['wartości (są )?orientacyjne', 'nie mogą zostać zagwarantowane', 'ok\.\s?\d', 'około \d+ ?(m|mb|km|szt)', 'brak (analizy terenu|badań gruntu)'], strength: 0.55}
    - {doc_types: [PPU], patterns: ['wynagrodzenie ryczałtowe'], combine_with: 'wartości orientacyjne', strength: 0.60, note: "ryczałt + ilości orientacyjne = przeniesienie niepoliczalnego ryzyka na wykonawcę → premia w cenie lub spór"}
  events: [EV_ADDITIONAL_WORKS, EV_PRICE_INCREASE, EV_TERM_EXTENSION, EV_SCOPE_REDUCTION]
  effects:
    empirical: {note: "ZiW vs buduj (BZP_2022_2026): P(5.3=Nie) 50% vs 29%; opóźnienie P80 129 vs 39 dni; P(≥1 zmiana) 62% vs 41%; koszt P90 +7,5% vs +7,3%"}
  causes: [PFU przygotowany bez wizji terenu i badań, zakres liczony z mapy]
  mitigations: [koncepcja i badania geotechniczne przed PFU, ilości graniczne (min–max) z ceną jednostkową za nadwyżkę, etapowanie z punktem decyzyjnym po koncepcji]
  clauses:
    - "Wynagrodzenie ryczałtowe obejmuje wykonanie sieci o łącznej długości do [L_max] m; za długość przekraczającą [L_max] wynagrodzenie ustala się jako iloczyn nadwyżki i ceny jednostkowej za 1 m określonej w formularzu ofertowym. W przypadku długości mniejszej niż [L_min] wynagrodzenie ulega obniżeniu według tej samej ceny jednostkowej."
    - "Po zatwierdzeniu koncepcji przez zamawiającego strony w terminie 14 dni potwierdzają zakres rzeczowy; zmiana zakresu wynikająca z koncepcji stanowi zmianę przewidzianą w art. 455 ust. 1 pkt 1 Pzp."

- id: R01.3
  parent: R01
  name: Roboty towarzyszące poza zakresem (odtworzenie nawierzchni, zjazdy, przebudowy kolizji)
  status: proposed
  signals:
    - {doc_types: [QA], patterns: ['kto (ponosi|pokrywa) koszt\w* odtworzeni', 'odtworzeni\w* nawierzchni (na całej szerokości|w pełnej)', 'zakres odtworzenia'], strength: 0.45}
    - {doc_types: [PFU, OPZ], patterns: ['odtworzeni\w* nawierzchni zgodnie z (warunkami|decyzją) zarządcy'], strength: 0.30}
  events: [EV_ADDITIONAL_WORKS, EV_PRICE_INCREASE]
  effects: {empirical: {category: drogi/nawierzchnie/koordynacja, n: 204, delay_days: {p50: 62, p75: 134}, cost_pct: {p50: 0.021, p75: 0.085, p90: 0.195}, source: BZP_2022_2026}}
  mitigations: [uzyskać warunki zarządcy drogi przed przetargiem, wycenić odtworzenie jako odrębną pozycję obmiarową]
  clauses:
    - "Odtworzenie nawierzchni rozlicza się obmiarowo według ceny jednostkowej za 1 m² dla każdego typu nawierzchni; jeżeli zarządca drogi określi zakres odtworzenia większy niż przyjęty w dokumentacji, wynagrodzenie ulega zmianie według tych cen jednostkowych."

- id: R01.4
  parent: R01
  name: Niejasna granica zakresu sieć / przyłącza / sięgacze
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ, SWZ, QA], patterns: ['przyłącz\w* (do|w granicach) (budynk|nieruchomoś)', 'sięgacz\w*', 'do granicy (działki|nieruchomości)', 'studni\w* przyłączeniow', 'czy (zamawiający|zakres) obejmuje przyłącz'], strength: 0.35}
  events: [EV_ADDITIONAL_WORKS, EV_SCOPE_REDUCTION]
  effects: {empirical: {category: mieszkańcy/przyłącza, n: 249, p_late: 0.63, delay_days: {p50: 46, p75: 113}, cost_pct: {p50: 0.016, p75: 0.066, p90: 0.164}, source: BZP_2022_2026}}
  mitigations: [jednoznaczna definicja punktu granicznego w PFU/OPZ, wykaz działek z przyłączami i zgodami właścicieli]
  clauses:
    - "Zakres obejmuje wykonanie [N] odgałęzień (sięgaczy) zakończonych studnią przyłączeniową [korkiem] w odległości do 1 m od granicy nieruchomości; liczba odgałęzień może ulec zmianie o ±[X]% bez zmiany ceny jednostkowej za odgałęzienie."
  checklist_refs: ['04:3.3', '04:2.4.1']

- id: R02
  name: Niedostateczne rozpoznanie stanu istniejącego
  status: approved_by_organizer
  effects_text: Przeprojektowanie, nieprzewidziane roboty, przestoje, wzrost kosztu albo wydłużenie terminu.
  children: [R02.1, R02.2, R02.3]

- id: R02.1
  parent: R02
  name: Warunki gruntowo-wodne (woda gruntowa, grunty słabe, kurzawka, skała)
  status: proposed
  signals:
    - {doc_types: [SWZ, PFU, OPZ, QA], patterns: ['brak (badań|dokumentacji) (geotechn|geolog|gruntow)', 'czy zamawiający posiada (badania|opinię) geotechn', 'opini\w* geotechniczn\w* (wykona|leży po stronie) wykonaw'], strength: 0.50}
    - {doc_types: [GEOTECH, PROJECT, STWIORB], patterns: ['zwierciadł\w* wody (gruntowej )?(na głębokości|ustabilizowan)\D{0,20}(0,\d|1,\d)', 'kurzawk', 'grunt\w* (nienośn|organiczn|torf)', 'namuł', 'igłofiltr', 'odwodnieni\w* wykop'], strength: 0.45}
    - {doc_types: [meta], rule: "trasa w dolinie cieku / teren podmokły (z opisu lub mapy)", strength: 0.30}
  events: [EV_ADDITIONAL_WORKS, EV_UNFORESEEN_CHANGE, EV_TERM_EXTENSION]
  notice_evidence: {legal_basis: ['455 ust. 1 pkt 4', '455 ust. 1 pkt 3'], reason_patterns: ['warunk\w* grunt', 'wod\w* gruntow', 'odwodni', 'geotechn', 'kurzawk', 'skał']}
  effects:
    empirical: {category: grunt/woda, n: 185, delay_days: {p50: 58, p75: 127}, cost_pct: {p50: 0.0, p75: 0.065, p90: 0.197}, source: BZP_2022_2026}
    literature: "Interpelacja 16654 (2026): gminy wskazują trudne warunki geologiczne i hydrologiczne jako przyczynę opóźnień KPO B3.1.1."
  causes: [brak badań lub badania punktowe co >500 m, sezonowe wahania zwierciadła wody, mokry sezon realizacji]
  mitigations: [badania podłoża w rozstawie dostosowanym do trasy, pozycja rezerwowa na odwodnienie rozliczana obmiarowo, uzgodnienie wodnoprawne odwodnienia przed startem]
  clauses:
    - "Zamawiający przekazuje dokumentację badań podłoża gruntowego (załącznik nr [X]). W przypadku stwierdzenia warunków gruntowo-wodnych istotnie odmiennych od opisanych w tej dokumentacji wykonawca niezwłocznie, nie później niż w terminie 3 dni roboczych, zawiadamia inspektora nadzoru; strony sporządzają protokół konieczności, a roboty dodatkowe (odwodnienie, wymiana gruntu, umocnienia) rozlicza się według cen jednostkowych z kosztorysu ofertowego. Termin wykonania ulega przedłużeniu o czas niezbędny do ich wykonania, potwierdzony przez inspektora nadzoru."
    - "Odwodnienie wykopów rozlicza się obmiarowo według ceny jednostkowej za dobę pracy zestawu odwadniającego na 1 m wykopu, do kwoty rezerwy [Y] zł."
  checklist_refs: ['04:5.4', '04:6.6.1']

- id: R02.2
  parent: R02
  name: Nieznany stan istniejącej infrastruktury (przebudowa, modernizacja OŚ/SUW, renowacja kanałów)
  status: proposed
  works_type: [przebudowa]
  signals:
    - {doc_types: [PFU, OPZ, QA], patterns: ['brak (inwentaryzacji|dokumentacji powykonawczej)', 'stan techniczny (nieznany|do ustalenia)', 'inspekcj\w* (TV|CCTV|kamerą) (wykona|po stronie) wykonaw', 'czy zamawiający posiada (inwentaryzację|ekspertyzę)'], strength: 0.45}
  events: [EV_ADDITIONAL_WORKS, EV_UNFORESEEN_CHANGE]
  mitigations: [inwentaryzacja i ekspertyza przed przetargiem, inspekcja CCTV kanałów do renowacji, ruch obiektu w trakcie modernizacji – plan tymczasowy]
  clauses:
    - "Wykonawca w terminie [14] dni od przekazania terenu budowy wykona inwentaryzację stanu istniejącego obiektów objętych przebudową; ujawnione w jej wyniku konieczne roboty nieprzewidziane w dokumentacji rozlicza się na zasadach określonych w § [X] (protokół konieczności, ceny jednostkowe)."
    - "Zamawiający zapewnia ciągłość pracy oczyszczalni/stacji w okresie robót; wykonawca przedstawi plan przełączeń i pracy tymczasowej do akceptacji operatora."

- id: R02.3
  parent: R02
  name: Archeologia, niewybuchy, zanieczyszczenia gruntu
  status: proposed
  signals:
    - {doc_types: [DECISION, PFU, OPZ], patterns: ['stanowisk\w* archeolog', 'nadzór archeolog', 'strefa ochrony konserwatorskiej', 'niewybuch', 'saper', 'zanieczyszcz\w* (grunt|ziemi)'], strength: 0.35}
  effects: {empirical: {category: archeologia/niewybuchy/zanieczyszczenia, n: 19, p_late: 0.79, delay_days: {p50: 116, p75: 195}, cost_pct: {p75: 0.045, p90: 0.133}, source: BZP_2022_2026, note: "mała próba"}}
  mitigations: [uzgodnienie z WUOZ przed przetargiem, nadzór archeologiczny jako odrębna pozycja, rozpoznanie historyczne terenu]
  clauses:
    - "Wstrzymanie robót na polecenie organu ochrony zabytków lub w związku z odkryciem przedmiotu, który posiada cechy zabytku, albo niewybuchu, stanowi okoliczność uzasadniającą przedłużenie terminu o czas wstrzymania robót."

- id: R03
  name: Kolizje, dostęp do terenu i prawa do nieruchomości
  status: approved_by_organizer
  effects_text: Brak możliwości rozpoczęcia części robót, zmiana trasy lub technologii, wstrzymanie prac albo roszczenia.
  children: [R03.1, R03.2, R03.3]

- id: R03.1
  parent: R03
  name: Kolizje z uzbrojeniem terenu (w tym niezinwentaryzowanym)
  status: proposed
  signals:
    - {doc_types: [QA], patterns: ['koliz\w*', 'niezinwentaryzowan', 'sieci? (gazow|teletechn|energetyczn)\w* (koliduj|w kolizji)'], strength: 0.45}
    - {doc_types: [PFU, OPZ], patterns: ['warunki (techniczne )?(gestor|właściciel\w* sieci) (uzyska|leży po stronie) wykonaw', 'przebudow\w* kolizji'], strength: 0.40}
    - {doc_types: [meta], rule: "wąskie ulice zabudowy zwartej; trasa w pasie drogi z istniejącym uzbrojeniem (opis)", strength: 0.30}
  events: [EV_ADDITIONAL_WORKS, EV_UNFORESEEN_CHANGE, EV_TERM_EXTENSION]
  notice_evidence: {legal_basis: ['455 ust. 1 pkt 3', '455 ust. 1 pkt 4'], reason_patterns: ['koliz', 'niezinwentaryz', 'gestor', 'tauron|enea|energa|pge|orange|psg|polska spółka gazownictwa']}
  effects:
    empirical: {category: kolizje/gestorzy, n: 166, delay_days: {p50: 46, p75: 124}, cost_pct: {p50: 0.006, p75: 0.062, p90: 0.161}, source: BZP_2022_2026}
    literature: "KE SWD(2020)43: projekt kanalizacji w Sochaczewie – napotkane ok. 50-letnie, niezarejestrowane uzbrojenie wymagało robót dodatkowych i zmian projektu; opóźnienie > 1 rok (łącznie z wolnym przetargiem)."
  mitigations: [aktualna mapa do celów projektowych, warunki gestorów przed przetargiem, przekopy kontrolne w miejscach krytycznych, pozycja rezerwowa]
  clauses:
    - "Kolizje z uzbrojeniem terenu nieujawnionym na mapie do celów projektowych stanowią okoliczność, za którą wykonawca nie ponosi odpowiedzialności. Wykonawca niezwłocznie zawiadamia inspektora nadzoru i gestora sieci; termin wykonania ulega przedłużeniu o czas uzgodnień z gestorem, nie dłuższy niż [30] dni dla każdej kolizji, a koszt przebudowy rozlicza się według cen jednostkowych."
  checklist_refs: ['04:5.4']

- id: R03.2
  parent: R03
  name: Brak prawa do dysponowania gruntem / służebności na trasie
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ, PROJECT_DESC, FUNDING_DESC], patterns: ['własnoś\w* prywatn', 'teren\w* prywatn', 'przez (działk|nieruchomoś)\w* prywatn', 'zgod\w* właściciel', 'służebnoś', 'nieuregulowan\w* stan\w* prawn'], strength: 0.45}
    - {doc_types: [QA], patterns: ['czy zamawiający posiada (prawo do dysponowania|zgody właścicieli)', 'brak zgody (właściciel|na wejście)'], strength: 0.55}
    - {doc_types: [PFU], patterns: ['uzyskanie zgód właścicieli (leży po stronie|należy do) wykonawc'], strength: 0.55, note: "ZiW przenosi ryzyko na wykonawcę, ale skutek terminowy zostaje u zamawiającego"}
  events: [EV_TERM_EXTENSION, EV_SCOPE_REDUCTION, EV_UNFORESEEN_CHANGE]
  notice_evidence: {reason_patterns: ['właściciel', 'brak zgody', 'służebn', 'dysponowani', 'zmian\w* trasy']}
  effects: {empirical: {category: nieruchomości, n: 127, delay_days: {p50: 46, p75: 146}, cost_pct: {p75: 0.031, p90: 0.071}, source: BZP_2022_2026}, literature: "KE SWD(2020)43: wodociąg Sofia – wywłaszczenia → 3 lata opóźnienia i +32% kosztu."}
  causes: [trasa poza pasem drogowym, brak wcześniejszych rozmów z właścicielami, rozdrobnione działki]
  mitigations: [zgody przed przetargiem (formuła buduj), decyzja z art. 124 ugn jako ścieżka awaryjna, trasa w pasie drogowym, wykaz działek z dysponowaniem jako załącznik]
  clauses:
    - "Zamawiający oświadcza, że posiada prawo do dysponowania nieruchomościami na cele budowlane w zakresie działek wymienionych w załączniku nr [X]. Brak prawa do dysponowania nieruchomością ujawniony po zawarciu umowy uprawnia strony do zmiany trasy sieci lub ograniczenia zakresu robót, nie więcej niż o [10]% wynagrodzenia, z obniżeniem wynagrodzenia według cen jednostkowych z kosztorysu ofertowego, oraz do przedłużenia terminu o czas niezbędny do uzyskania decyzji, o której mowa w art. 124 ustawy o gospodarce nieruchomościami."
  checklist_refs: ['04:5.2', '04:5.3', '04:5.5.1']

- id: R03.3
  parent: R03
  name: Przekroczenia przeszkód (cieki, wały, drogi krajowe/wojewódzkie, kolej)
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ, PROJECT], patterns: ['przekroczeni\w* (cieku|rzeki|rowu|drogi|torów|linii kolejowej)', 'przewiert\w*', 'przecisk', 'HDD', 'przejści\w* pod (dnem|drogą|torami)', 'drog\w* (krajow|wojewódzk)', 'PKP|PLK'], strength: 0.40}
  events: [EV_TERM_EXTENSION, EV_ADDITIONAL_WORKS]
  mitigations: [uzgodnienia z zarządcą (GDDKiA/ZDW/PKP PLK/Wody Polskie) przed przetargiem, technologia bezwykopowa wyceniona osobno, pozwolenie wodnoprawne art. 389 pkt 9 PW]
  clauses:
    - "Termin wykonania przekroczenia [cieku/drogi/linii kolejowej] liczy się od dnia doręczenia wykonawcy ostatecznej decyzji/uzgodnienia zarządcy; opóźnienie zarządcy ponad ustawowy termin załatwienia sprawy przedłuża termin wykonania o czas tego opóźnienia, pod warunkiem złożenia przez wykonawcę kompletnego wniosku w terminie wynikającym z harmonogramu."

- id: R04
  name: Decyzje, pozwolenia i uzgodnienia zależne od podmiotów trzecich
  status: approved_by_organizer
  effects_text: Opóźnienie rozpoczęcia lub kontynuacji prac, zmiana warunków realizacji albo brak możliwości użytkowania obiektu.
  children: [R04.1, R04.2, R04.3, R04.4]
  effects: {empirical: {category: decyzje/pozwolenia/uzgodnienia, n: 327, delay_days: {p50: 78, p75: 184}, cost_pct: {p75: 0.024, p90: 0.10}, source: BZP_2022_2026}}

- id: R04.1
  parent: R04
  name: Decyzja o środowiskowych uwarunkowaniach / ocena Natura 2000
  status: proposed
  applicability_rules:
    - "sieć kanalizacyjna ≥ 1 km (rozp. RM 2019 poz. 1839 §3 ust.1 pkt 81; wyjątki: przebudowa bezwykopowa, deszczówka w pasie drogowym, przyłącza)"
    - "oczyszczalnia ≥ 400 RLM (pkt 79)"
    - "rurociąg wodociągowy magistralny / od SUW do sieci rozdzielczej (pkt 71)"
    - "ujęcie wód podziemnych ≥ 10 m³/h (pkt 73) lub ≥ 1 m³/h przy innym ujęciu < 500 m (pkt 74)"
    - "obszar Natura 2000 / formy ochrony przyrody na trasie"
  signals:
    - {doc_types: [SWZ, PFU, OPZ], patterns: ['decyzj\w* o środowiskowych uwarunkowaniach (zostanie|należy|uzyska)', 'brak decyzji środowiskowej', 'raport (oddziaływania|OOŚ)', 'Natura 2000', 'RDOŚ'], strength: 0.45}
    - {doc_types: [meta], rule: "applicability_rules == true AND w pakiecie brak DŚU lub wzmianki o niej → stan DOKUMENT_NIE_WSPOMINA/BRAK_W_PACZCE", strength: 0.35}
  events: [EV_TERM_EXTENSION]
  mitigations: [DŚU przed ogłoszeniem przetargu (buduj), w ZiW – bufor ≥ 3–6 mies. na DŚU i warunki z niej wynikające]
  clauses:
    - "Okres od złożenia kompletnego wniosku o wydanie decyzji do dnia jej ostateczności, w części przekraczającej [60] dni, nie wlicza się do terminu wykonania etapu projektowego, o ile opóźnienie nie wynika z przyczyn leżących po stronie wykonawcy."
  checklist_refs: ['04:6.3', '04:6.4', '04:6.6.2']

- id: R04.2
  parent: R04
  name: Pozwolenie / zgłoszenie wodnoprawne
  status: proposed
  applicability_rules:
    - "zrzut ścieków oczyszczonych (OŚ) – pozwolenie wodnoprawne (usługi wodne / szczególne korzystanie z wód)"
    - "rurociąg pod/nad wodami płynącymi lub przez wał – art. 389 pkt 9 PW (pozwolenie)"
    - "długotrwałe obniżenie zwierciadła wód podziemnych – art. 389 pkt 3 (pozwolenie)"
    - "trwałe odwadnianie wykopów, odprowadzanie wód z wykopów – art. 394 ust.1 pkt 5, 8 (zgłoszenie)"
  signals:
    - {doc_types: [SWZ, PFU, OPZ, QA], patterns: ['pozwoleni\w* wodnoprawn', 'zgłoszeni\w* wodnoprawn', 'operat wodnoprawn', 'Wody Polskie', 'wylot\w* (do|ścieków)', 'odbiornik\w* ścieków'], strength: 0.35}
  events: [EV_TERM_EXTENSION, EV_UNFORESEEN_CHANGE]
  notice_evidence: {reason_patterns: ['wodnoprawn', 'Wody Polskie', 'PGW']}
  mitigations: ["operat wodnoprawny w zakresie wykonawcy ZiW z buforem czasowym", "wczesna konsultacja z PGW Wody Polskie"]
  clauses:
    - "Wykonawca uzyska w imieniu zamawiającego pozwolenia i zgłoszenia wodnoprawne niezbędne do wykonania robót, w tym na odwodnienie wykopów i przekroczenia cieków; termin uzyskania przez organ, przekraczający termin ustawowy, przedłuża termin wykonania o czas opóźnienia organu."

- id: R04.3
  parent: R04
  name: Pozwolenie na budowę / zgłoszenie, ZUD, uzgodnienia konserwatorskie (ZiW)
  status: proposed
  formula: [zaprojektuj_i_wybuduj]
  signals:
    - {doc_types: [PFU, OPZ], patterns: ['uzyskanie (pozwolenia na budowę|zgłoszenia|decyzji)\w* (leży po stronie|należy do|po stronie) wykonawc', 'narad\w* koordynacyjn', 'ZUD', 'konserwator'], strength: 0.35}
  events: [EV_TERM_EXTENSION]
  note: "sieci wodociągowe i kanalizacyjne – zgłoszenie (PB art. 29 ust.1 pkt 2 lit. b–c); pozwolenie wymagane, gdy przedsięwzięcie wymaga OOŚ/oceny Natura 2000 (art. 29 ust. 6)"
  mitigations: ["kamień milowy 'projekt + decyzje' z terminem i rezerwą", "dopuszczenie etapowania robót wg uzyskanych decyzji"]

- id: R04.4
  parent: R04
  name: Warunki techniczne operatora i gestorów, przepustowość odbiornika (OŚ/SUW/kolektor)
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ, PROJECT_DESC, FUNDING_DESC], patterns: ['warunk\w* techniczn\w* (przyłączenia|podłączenia) (zostaną|należy) uzyska', 'przepustowoś\w* (oczyszczalni|stacji)', 'wpięt\w* do (realizowanej|budowanej|projektowanej)', 'podłączeni\w* do sieci (gminy|w gminie)'], strength: 0.40}
  events: [EV_ADDITIONAL_WORKS, EV_TERM_EXTENSION]
  notice_evidence: {reason_patterns: ['warunk\w* techniczn', 'operator', 'przedsiębiorstw\w* wodociąg']}
  mitigations: [pisemne stanowisko operatora o możliwości dostawy/odbioru (wg 04:4.2) przed przetargiem, aktualność ≤ 12 mies.]
  checklist_refs: ['04:4.1', '04:4.2', '04:4.5.1']

- id: R05
  name: Niejasny lub nieadekwatny podział odpowiedzialności
  status: approved_by_organizer
  effects_text: Luka odpowiedzialności, dublowanie prac, odmowa wykonania, roszczenie i spór o koszt lub termin.
  children: [R05.1, R05.2]

- id: R05.1
  parent: R05
  name: Ryzyko projektowe i hierarchia dokumentów (ZiW vs dokumentacja zamawiającego)
  status: proposed
  signals:
    - {doc_types: [PPU, SWU], rule: "brak klauzuli kolejności ważności dokumentów", strength: 0.30}
    - {doc_types: [PPU], patterns: ['wykonawca (ponosi|przejmuje) (pełną )?odpowiedzialnoś\w* za (błędy|kompletność) dokumentacji (projektowej )?(zamawiającego|przekazanej)'], strength: 0.50, note: "potencjalnie sprzeczne z art. 433 pkt 3 Pzp → R11.3"}
  events: [EV_ADDITIONAL_WORKS, EV_KIO_APPEAL]
  mitigations: ["jasny podział: kto odpowiada za dane wejściowe (mapy, badania, warunki), a kto za rozwiązania", "klauzula hierarchii dokumentów"]
  checklist_refs: ['04:7.2', '04:7.6.1']

- id: R05.2
  parent: R05
  name: Interfejs z operatorem / właścicielem innej sieci, przyszła eksploatacja
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ, FUNDING_DESC], patterns: ['eksploatator', 'przedsiębiorstw\w* wodociągow\w*', 'przekazani\w* (do eksploatacji|w administrowanie)', 'sieć (gminy|należąca do)'], strength: 0.25}
  mitigations: ["porozumienie z operatorem przed realizacją (odbiory, standardy materiałów)", "udział operatora w odbiorach"]
  checklist_refs: ['04:7.4']

- id: R06
  name: Nierealistyczny harmonogram i nieuwzględnione zależności
  status: approved_by_organizer
  effects_text: Opóźnienie, kary, kumulacja prac, presja na skrócenie prób i badań albo pogorszenie jakości.
  children: [R06.1, R06.2]

- id: R06.1
  parent: R06
  name: Presja terminu dofinansowania (KPO 15.06/31.08.2026, koniec perspektywy)
  status: proposed
  signals:
    - {doc_types: [meta], rule: "źródło finansowania = KPO AND planowany koniec umowy > (termin IOI − 60 dni)", strength: 0.55}
    - {doc_types: [meta], rule: "planowany czas realizacji < P25 grupy referencyjnej przy porównywalnym zakresie (km, RLM)", strength: 0.45}
    - {doc_types: [PPU, SWZ], patterns: ['termin wykonania[^.]{0,40}do dnia \d', 'nieprzekraczaln\w* termin'], strength: 0.30}
  events: [EV_LATE_COMPLETION, EV_TERM_EXTENSION, EV_FUNDING_CHANGE]
  effects: {literature: "MFiPR 15.05.2026 (odp. na interpelację 16654): termin B3.1.1 przesunięty z 15.05 na 15.06.2026 na liczne wnioski gmin; wskaźniki KPO do 31.08.2026.", empirical: {note: "pole 3.3 = UE: P(5.3=Nie) 37% vs 30% bez UE (BZP_2022_2026); rok publikacji 2026: 39% spóźnionych vs 27% w 2022"}}
  mitigations: [ogłoszenie przetargu z dokumentacją gotową, bufor ≥ 15% czasu, etapy i odbiory częściowe zsynchronizowane z wnioskami o płatność, plan B – zakres podstawowy wymagany do wskaźnika vs zakres opcjonalny]
  clauses:
    - "Termin wykonania: [X] miesięcy od dnia zawarcia umowy, nie później niż do [data]; wskazanie daty jest uzasadnione terminem kwalifikowalności wydatków wynikającym z umowy o dofinansowanie (obiektywna przyczyna w rozumieniu art. 436 pkt 1 Pzp)."
    - "Wykonawca przedstawi harmonogram rzeczowo-finansowy z wyodrębnionymi kamieniami milowymi; w przypadku opóźnienia przekraczającego [14] dni względem harmonogramu wykonawca w terminie 7 dni przedstawi plan naprawczy (zwiększenie zasobów, praca zmianowa) bez dodatkowego wynagrodzenia."
    - "Zamawiający przewiduje prawo opcji / możliwość ograniczenia zakresu o nie więcej niż [15]% wynagrodzenia (zakres opcjonalny wskazany w załączniku), jeżeli jego wykonanie w terminie zagrażałoby kwalifikowalności wydatków."

- id: R06.2
  parent: R06
  name: Niedoszacowany czas projektowania i uzyskiwania decyzji w formule ZiW
  status: proposed
  formula: [zaprojektuj_i_wybuduj]
  signals:
    - {doc_types: [meta], rule: "ZiW AND łączny termin < 12 mies. AND wymagana DŚU/pozwolenie wodnoprawne", strength: 0.55}
  effects: {empirical: {note: "ZiW (BZP_2022_2026, n=676): P(późno) 50%, opóźnienie P50 19 d, P80 129 d, P90 180 d; mediana planowanego czasu 426 d"}}
  mitigations: [osobny termin na etap projektowy z mechanizmem przesunięcia przy opóźnieniu organów, wcześniejsza DŚU przez zamawiającego]

- id: R07
  name: Nieprzewidziane zmiany i roboty dodatkowe
  status: approved_by_organizer
  kind: event_category
  note: "Kategoria zdarzeniowa – przy zatwierdzaniu przypisz przyczynę źródłową (R01–R04, R16–R18). Pole 'przyczyna nieustalona' dozwolone z obniżoną pewnością."
  events: [EV_ADDITIONAL_WORKS, EV_UNFORESEEN_CHANGE, EV_DEMINIMIS_CHANGE]
  effects: {empirical: {note: "ogłoszenia o zmianie (pkt 3/4) podnoszące cenę: wzrost względem wartości pierwotnej P50 5,5%, P75 12,7%, P90 22,9% (n=578, BZP_CHG_2022_2026)"}}

- id: R08
  name: Model wynagrodzenia niedopasowany do niepewności zakresu
  status: approved_by_organizer
  children: [R08.1, R08.2]

- id: R08.1
  parent: R08
  name: Brak lub niewystarczająca waloryzacja (inflacja, wzrost cen materiałów)
  status: proposed
  signals:
    - {doc_types: [PPU], rule: "czas trwania umowy > 6 mies. AND brak postanowień o waloryzacji (art. 439) → naruszenie ustawy", strength: 0.70}
    - {doc_types: [PPU], patterns: ['maksymaln\w* (łączn\w* )?wartoś\w* zmiany wynagrodzenia[^.]{0,60}\b([1-4](,\d)?|5)\s?%', 'poziom\w* zmiany[^.]{0,60}\b(1\d|[2-9]\d)\s?%', 'wskaźnik\w* cen towarów i usług konsumpcyjnych'], strength: 0.40, note: "niski limit (≤5%), wysoki próg (≥10%) lub indeks CPI zamiast cen produkcji budowlano-montażowej"}
    - {doc_types: [meta], rule: "umowa zawarta > 180 dni po terminie składania ofert", strength: 0.35}
    - {doc_types: [meta], rule: "okres realizacji ustalony na ≤ 6 mies. przy zakresie typowo dłuższym (ucieczka od art. 439)", strength: 0.35}
  events: [EV_PRICE_INCREASE, EV_UNFORESEEN_CHANGE, EV_NOT_PERFORMED]
  notice_evidence: {legal_basis: ['455 ust. 1 pkt 1', '455 ust. 1 pkt 4'], reason_patterns: ['waloryz', 'wzrost\w* cen', 'inflac']}
  effects:
    empirical: {category: waloryzacja/ceny, n: 86, delay_days: {p50: 27, p75: 126}, cost_pct: {p50: 0.065, p75: 0.112, p90: 0.17}, source: BZP_2022_2026}
    macro: "GUS: ceny budowy obiektów inżynierii lądowej i wodnej r/r: XI 2022 +14,8%, I 2023 +13,2%, XII 2023 +8,8%."
  mitigations: ["klauzula art. 439 oparta o wskaźnik GUS dla inżynierii lądowej i wodnej, symetryczna, z realnym limitem", "rezerwa budżetowa na waloryzację"]
  clauses:
    - "1. Strony przewidują zmianę wysokości wynagrodzenia w przypadku zmiany ceny materiałów lub kosztów związanych z realizacją zamówienia (art. 439 Pzp). 2. Miarą zmiany jest wskaźnik cen produkcji budowlano-montażowej – budowa obiektów inżynierii lądowej i wodnej – ogłaszany w komunikacie Prezesa GUS, liczony narastająco od miesiąca, w którym upłynął termin składania ofert (a gdy umowę zawarto po upływie 180 dni od tego terminu – od dnia otwarcia ofert). 3. Strona może żądać zmiany wynagrodzenia, jeżeli wskaźnik zmieni się o więcej niż 5% (próg); zmiana obejmuje część wynagrodzenia za roboty pozostałe do wykonania, o wartość zmiany wskaźnika ponad próg, nie częściej niż raz na kwartał. 4. Zmiana obejmuje zarówno wzrost, jak i obniżenie cen. 5. Maksymalna łączna wartość zmiany wynagrodzenia wynosi [10–15]% wynagrodzenia pierwotnego. 6. Wykonawca zmienia wynagrodzenie podwykonawców zgodnie z art. 439 ust. 5 Pzp."

- id: R08.2
  parent: R08
  name: Ryczałt przy niepewnych ilościach / kosztorys bez limitu
  status: proposed
  signals:
    - {doc_types: [PPU], patterns: ['wynagrodzenie ryczałtow'], combine_with: ['R01.2', 'R02.1', 'R03.1'], strength: 0.40}
    - {doc_types: [PPU], patterns: ['wynagrodzenie kosztorysow', 'kosztorys powykonawcz', 'obmiar'], rule: "brak limitu wartości", strength: 0.30}
  events: [EV_PRICE_INCREASE, EV_PAID_BELOW_CONTRACT]
  effects: {empirical: {category: obmiar/kosztorys, n: 167, delay_days: {p50: 8, p75: 50}, cost_pct: {p50: 0.024, p75: 0.086, p90: 0.19}, source: BZP_2022_2026}}
  mitigations: ["model mieszany – ryczałt za elementy przewidywalne, obmiar dla odwodnień, wymian gruntu i odtworzeń", "limit wartości robót obmiarowych"]

- id: R09
  name: Niejednoznaczne lub niemierzalne wymagania techniczne
  status: approved_by_organizer
  children: [R09.1, R09.2]

- id: R09.1
  parent: R09
  name: Brak mierzalnych parametrów technologicznych (oczyszczalnia, SUW)
  status: proposed
  subsectors: [oczyszczalnia, uzdatnianie]
  signals:
    - {doc_types: [PFU, OPZ], rule: "brak liczbowych parametrów: Qśr/Qmax [m³/d], RLM, ładunki BZT5/ChZT/zawiesina/N/P na dopływie, wymagania na odpływie; dla SUW: Fe, Mn, NH4, mętność, wydajność [m³/h]", strength: 0.45}
    - {doc_types: [PFU], patterns: ['technologi\w* (do|według) uznania wykonawcy', 'parametry zostaną (ustalone|określone)'], strength: 0.40}
  events: [EV_UNFORESEEN_CHANGE, EV_IMPROPER_PERFORMANCE]
  mitigations: [pomiary ilości i jakości ścieków/wody surowej przed PFU, parametry gwarantowane w umowie]

- id: R09.2
  parent: R09
  name: Wskazanie marek / niejasna równoważność materiałów i urządzeń
  status: proposed
  signals:
    - {doc_types: [OPZ, STWIORB, PROJECT], patterns: ['lub równoważn', 'typu [A-Z][a-z]+', 'np\. firmy'], rule: "wskazanie producenta bez kryteriów równoważności", strength: 0.30}
  events: [EV_KIO_APPEAL, EV_TERM_EXTENSION]
  clauses:
    - "Ilekroć w dokumentacji wskazano znak towarowy lub producenta, dopuszcza się rozwiązania równoważne o parametrach nie gorszych niż: [wykaz parametrów]; wykonawca wykazuje równoważność przed wbudowaniem, a zamawiający rozpatruje wniosek w terminie 7 dni."

- id: R10
  name: Niedookreślone próby, rozruch i odbiór
  status: approved_by_organizer
  children: [R10.1, R10.2]

- id: R10.1
  parent: R10
  name: Rozruch technologiczny oczyszczalni / SUW
  status: proposed
  subsectors: [oczyszczalnia, uzdatnianie]
  signals:
    - {doc_types: [PPU, PFU], rule: "brak określenia: czasu rozruchu, liczby prób, laboratorium, kryteriów odbioru, postępowania przy niedostatecznym dopływie", strength: 0.45}
  events: [EV_LATE_COMPLETION, EV_IMPROPER_PERFORMANCE]
  effects: {empirical: {note: "OŚ (BZP_2022_2026, n=783): P(późno) 40%, opóźnienie P80 84 d, P90 158 d; SUW/ujęcia (n=375): 38%, P80 79 d"}}
  clauses:
    - "Rozruch technologiczny trwa nie krócej niż [3] miesiące. Odbiór końcowy następuje po potwierdzeniu parametrów ścieków oczyszczonych wymaganych pozwoleniem wodnoprawnym w co najmniej [4] próbach średniodobowych pobranych i zbadanych przez laboratorium akredytowane. W przypadku dopływu ścieków niższego niż [X]% przepływu projektowego strony sporządzają protokół odbioru warunkowego, a próby powtarza się w terminie [6] miesięcy w ramach rękojmi."

- id: R10.2
  parent: R10
  name: Odbiory sieci – inspekcja TV, próby szczelności, inwentaryzacja geodezyjna
  status: proposed
  signals:
    - {doc_types: [STWIORB, PPU], rule: "brak wymogu inspekcji TV kanałów grawitacyjnych przed odbiorem / brak kryteriów spadków i deformacji", strength: 0.30}
  events: [EV_LATE_COMPLETION]
  clauses:
    - "Warunkiem odbioru końcowego jest przedłożenie: protokołów prób szczelności, raportu z inspekcji TV kanałów grawitacyjnych wraz z nagraniem, inwentaryzacji geodezyjnej powykonawczej przyjętej do PZGiK."

- id: R11
  name: Postępowanie podatne na odwołanie lub ograniczenie konkurencji
  status: approved_by_organizer
  children: [R11.1, R11.2, R11.3]

- id: R11.1
  parent: R11
  name: Unieważnienie z powodu ceny > budżet, powtórzone postępowanie
  status: proposed
  signals:
    - {doc_types: [meta], rule: "kosztorys inwestorski starszy niż 6 mies. przy wysokiej dynamice cen (indeks GUS r/r > 5%)", strength: 0.40}
    - {doc_types: [meta], rule: "kwota na sfinansowanie (art. 222 ust.4) < wartość zamówienia × 1,23", strength: 0.50}
  events: [EV_TENDER_CANCELLED_BUDGET, EV_REPEAT_TENDER]
  effects: {empirical: {note: "BZP_RES_2022_2026: udział unieważnionych części: 2022 31%, 2023 24%, 2024 16%, 2025 11%, 2026 12%; 61% unieważnień – art. 255 pkt 3. Relacja cena wybrana/(wartość×1,23): mediana 0,92 (2022) → 0,71 (2026)."}}
  mitigations: [aktualizacja kosztorysu wskaźnikiem GUS przed ogłoszeniem, rezerwa budżetowa, art. 257 Pzp w ogłoszeniu gdy finansowanie niepewne, podział na części]

- id: R11.2
  parent: R11
  name: Brak ofert / jedna oferta / nadmierne warunki udziału
  status: proposed
  signals:
    - {doc_types: [SWZ], rule: "warunek doświadczenia > 100% wartości zamówienia lub wymóg kilku robót o wysokiej wartości", strength: 0.35}
    - {doc_types: [meta], rule: "termin składania ofert < 21 dni dla robót > 5 mln zł; ogłoszenie w okresie wysokiego obłożenia rynku", strength: 0.30}
  events: [EV_TENDER_NO_OFFERS, EV_SINGLE_OFFER]
  effects: {empirical: {note: "BZP_RES_2022_2026: odsetek postępowań z 1 ofertą 25% (2022) → 6% (2026); mediana liczby ofert 3 → 6"}}

- id: R11.3
  parent: R11
  name: Odwołanie do KIO
  status: proposed
  signals:
    - {doc_types: [PPU], rule: "postanowienia sprzeczne z art. 433 Pzp (kary za opóźnienie zamiast zwłoki, odpowiedzialność za okoliczności zamawiającego, ograniczenie zakresu bez minimum)", strength: 0.40}
    - {doc_types: [QA], patterns: ['wnosimy o (zmianę|wykreślenie)', 'narusza (art\.|zasad)', 'nieproporcjonaln'], strength: 0.25}
  events: [EV_KIO_APPEAL]
  effects: {literature: "KIO rozpoznaje odwołanie w terminie 15 dni od doręczenia (art. 544 ust.1 Pzp); typowo +3–6 tyg. do zawarcia umowy."}

- id: R12
  name: Niewystarczająca zdolność wykonawcy lub łańcucha dostaw
  status: approved_by_organizer
  children: [R12.1, R12.2, R12.3]

- id: R12.1
  parent: R12
  name: Niewypłacalność / upadłość wykonawcy, odstąpienie od umowy
  status: proposed
  signals:
    - {doc_types: [meta], rule: "wartość umowy > 3× największej wcześniejszej umowy wykonawcy w BZP", strength: 0.35}
    - {doc_types: [meta], rule: "wykonawca ma w BZP wcześniejsze ogłoszenie o wykonaniu z 5.1=Nie lub 5.6=Nie", strength: 0.50}
    - {doc_types: [BIP, NEWS], patterns: ['bezpośredni\w* zapłat\w* podwykonawc', 'zszedł z budowy', 'odstąpi\w* od umowy', 'upadłoś', 'restrukturyzac'], strength: 0.70}
  events: [EV_NOT_PERFORMED, EV_CONTRACTOR_REPLACED, EV_COMPLETION_TENDER]
  notice_evidence: {legal_basis: ['455 ust. 1 pkt 2'], fields: {'5.1': 'Nie'}}
  effects:
    empirical: {note: "BZP_2022_2026: umowy niewykonane 0,5%, nienależycie 0,7% – rzadkie, ale z największym skutkiem (nowy przetarg na dokończenie)."}
    literature: "KE SWD(2020)43: Craiova – wymiana wykonawcy przez nowy przetarg; Słowenia – dwóch kolejnych wykonawców upadło. Coface: budownictwo ~17–18% niewypłacalności firm w PL w 2025."
  mitigations: [zabezpieczenie do 10% przy uzasadnionym ryzyku (art. 452 ust.3), płatności częściowe miesięczne, monitoring bezpośrednich zapłat (art. 465 ust.7), cesja umów podwykonawczych]
  clauses:
    - "Wykonawca niezwłocznie, nie później niż w terminie 3 dni, informuje zamawiającego o złożeniu wniosku o ogłoszenie upadłości lub otwarcie postępowania restrukturyzacyjnego. Zamawiający może odstąpić od umowy w terminie 30 dni od powzięcia wiadomości o przerwaniu robót przez wykonawcę na okres dłuższy niż 21 dni lub o konieczności dokonania bezpośrednich zapłat podwykonawcom na sumę większą niż 5% wartości umowy (art. 465 ust. 7 Pzp)."
    - "W razie odstąpienia strony w terminie 7 dni sporządzają protokół inwentaryzacji robót; wykonawca przekazuje dokumentację budowy, karty gwarancyjne i prawa z umów z dostawcami urządzeń."

- id: R12.2
  parent: R12
  name: Długie terminy dostaw urządzeń i materiałów (pompy, technologia OŚ/SUW, automatyka, rury)
  status: proposed
  signals:
    - {doc_types: [PFU, OPZ], patterns: ['dmuchaw', 'reaktor\w* SBR', 'pomp\w* zatapialn', 'automatyk', 'SCADA', 'telemetri', 'filtr\w* (ciśnieniow|odżelaziaj)'], strength: 0.25}
  events: [EV_TERM_EXTENSION]
  effects: {empirical: {category: dostawy, n: 241, delay_days: {p50: 46, p75: 120}, cost_pct: {p75: 0.05, p90: 0.147}, source: BZP_2022_2026}}
  clauses:
    - "Wykonawca w terminie 30 dni od zawarcia umowy przedstawi potwierdzenie złożenia zamówień na urządzenia o czasie dostawy dłuższym niż 8 tygodni. Dopuszcza się zastosowanie urządzeń równoważnych o parametrach nie gorszych niż wymagane, bez zmiany wynagrodzenia, po akceptacji zamawiającego i operatora."

- id: R12.3
  parent: R12
  name: Rażąco niska cena / agresywna oferta
  status: proposed
  signals:
    - {doc_types: [meta], rule: "cena wybranej oferty < 0,7 × (wartość zamówienia × 1,23) lub < 0,7 × średnia ofert (art. 224 ust. 2)", strength: 0.40}
    - {doc_types: [RESULT], rule: "6.1.7 liczba ofert z RNC > 0", strength: 0.30}
  events: [EV_PRICE_INCREASE, EV_NOT_PERFORMED, EV_TERM_EXTENSION]
  effects: {empirical: {note: "BZP_RES_2022_2026: cena wybrana/(wartość×1,23) P10 0,44, P25 0,64 – niski stosunek częsty od 2024 (mediana 0,71 w 2026); wymaga analizy łącznie z jakością kosztorysu inwestorskiego."}}
  mitigations: [rzetelne wyjaśnienia RNC z kalkulacją, zabezpieczenie podwyższone, ścisły monitoring harmonogramu]

- id: R13
  name: Ryzyko finansowania, budżetu i płatności
  status: approved_by_organizer
  children: [R13.1, R13.2]

- id: R13.1
  parent: R13
  name: Utrata lub obniżenie dofinansowania (terminy, wskaźniki, kwalifikowalność)
  status: proposed
  signals:
    - {doc_types: [meta], rule: "R06.1 aktywne AND brak zakresu opcjonalnego", strength: 0.45}
    - {doc_types: [FUNDING], patterns: ['wskaźnik\w* (rezultatu|produktu)[^.]{0,80}(osób|RLM|przyłącz)', 'zwrot dofinansowania'], strength: 0.25}
  events: [EV_FUNDING_CHANGE]
  effects: {literature: "NIK P/20/046: opóźnienia AKPOŚK wynikały głównie z braku środków własnych i niepozyskania dofinansowania; w 40 aglomeracjach wydatkowano 30,2% planowanych nakładów (do IX 2020)."}
  clauses:
    - "Odbiory częściowe i płatności następują zgodnie z harmonogramem rzeczowo-finansowym skorelowanym z wnioskami o płatność; wykonawca przekazuje dokumenty rozliczeniowe w terminie 7 dni od odbioru. Zmiana umowy o dofinansowanie w zakresie terminów lub zakresu stanowi podstawę zmiany umowy przewidzianą w art. 455 ust. 1 pkt 1 Pzp."

- id: R13.2
  parent: R13
  name: Luka budżetowa (cena > kwota, brak środków na roboty dodatkowe, zmiany WPF)
  status: proposed
  signals:
    - {doc_types: [meta], rule: "cena wybranej oferty > kwota na sfinansowanie (zwiększenie kwoty)", strength: 0.40}
    - {doc_types: [WPF], rule: "zwiększenie 'łącznych nakładów' przedsięwzięcia w WPF ≥ 10% lub przesunięcie 'okresu realizacji'", strength: 0.60}
  events: [EV_FUNDING_CHANGE, EV_SCOPE_REDUCTION]

- id: R14
  name: Nadmierne koszty eksploatacji i utrzymania
  status: approved_by_organizer
  children: [R14.1]

- id: R14.1
  parent: R14
  name: Mały przepływ, długie przewody tłoczne, energochłonność przepompowni
  status: proposed
  signals:
    - {doc_types: [PFU, PROJECT_DESC, FUNDING_DESC], rule: "długość sieci / liczba przyłączy > P75 grupy (m na przyłącze) lub zabudowa rozproszona/sezonowa", strength: 0.35}
    - {doc_types: [PFU], patterns: ['kanalizacj\w* (ciśnieniow|podciśnieniow)', 'przepompowni\w* przydomow', 'tłoczni\w* przydomow', 'rurociąg\w* tłoczn\w* o długości'], strength: 0.30}
  effects: {literature: "Poradnik 04 §2.3: długi przewód przy małym poborze – wydłużony czas przebywania wody; ścieki w długich tłocznych – zagniwanie (H₂S), korozja."}
  mitigations: ["wymagania eksploatacyjne w PFU (energia, czas zatrzymania, płukanie, telemetria)", "kryterium kosztu cyklu życia", "konsultacja z operatorem"]
  checklist_refs: ['04:2.3']

- id: R15
  name: Nieosiągnięcie efektu technologicznego, użytkowego lub środowiskowego
  status: approved_by_organizer
  children: [R15.1, R15.2]

- id: R15.1
  parent: R15
  name: Niski stopień przyłączeń nieruchomości (RLM, liczba osób)
  status: proposed
  signals:
    - {doc_types: [FUNDING_DESC, PFU], rule: "zakres = sieć z sięgaczami do granicy działki, bez przyłączy na terenie nieruchomości i bez programu dofinansowania przyłączy", strength: 0.45}
    - {doc_types: [meta], rule: "brak w pakiecie deklaracji mieszkańców / analizy odbiorców (Poradnik 04 §2.1)", strength: 0.35}
  events: [EV_LOW_CONNECTION, EV_FUNDING_CHANGE]
  effects: {literature: "NIK P/20/046: w 26 gminach 5 088–6 360 nieruchomości niepodłączonych do sieci zbudowanych do 2017 r. i 866–1 152 do sieci zbudowanych później; 20 z 44 gmin nie miało danych o nieruchomościach do podłączenia; tylko 6 gmin systematycznie egzekwowało obowiązek; postępowania objęły 7% niepodłączonych."}
  mitigations: [deklaracje przyłączeniowe przed decyzją o zakresie, przyłącza w zakresie inwestycji lub dotacja gminna, egzekucja art. 5 ust. 7 ucpg, harmonogram przyłączeń w umowie o dofinansowanie]
  checklist_refs: ['04:2.1', '04:2.2', '04:2.4.1', '04:1.5.2']

- id: R15.2
  parent: R15
  name: Nieosiągnięte parametry oczyszczania / jakości wody
  status: proposed
  subsectors: [oczyszczalnia, uzdatnianie]
  signals:
    - {doc_types: [PFU, PPU], rule: "brak gwarantowanych parametrów odpływu/wody uzdatnionej i sankcji", strength: 0.40}
  events: [EV_IMPROPER_PERFORMANCE, EV_NIK_FINDING]
  clauses:
    - "Wykonawca gwarantuje osiągnięcie parametrów ścieków oczyszczonych określonych w pozwoleniu wodnoprawnym i załączniku nr [X] przez okres [24] miesięcy od odbioru; w razie ich nieosiągnięcia wykonawca na własny koszt wykona niezbędne zmiany technologiczne w terminie [60] dni."

- id: R16
  name: Warunki atmosferyczne i sezonowość robót
  status: proposed
  level: 1
  rationale: "Brak w R01–R15 kategorii zdarzeń egzogenicznych; pogoda – 25% przestojów w obserwacji budów wod-kan (Rybka i in. 2016), 12% zmienionych umów (BZP)."
  signals:
    - {doc_types: [meta], rule: "planowany okres robót ziemnych obejmuje XII–II AND brak rezerwy czasowej", strength: 0.35}
  events: [EV_TERM_EXTENSION, EV_LATE_COMPLETION]
  effects: {empirical: {category: warunki atmosferyczne, n: 345, delay_days: {p50: 64, p75: 131}, cost_pct: {p75: 0.027, p90: 0.11}, source: BZP_2022_2026}}
  clauses:
    - "Okolicznością uzasadniającą zmianę terminu są warunki atmosferyczne uniemożliwiające prowadzenie robót zgodnie z technologią (np. temperatura powietrza poniżej [−5] °C lub opad powyżej [10] mm/dobę według najbliższej stacji IMGW), trwające łącznie dłużej niż [średnia wieloletnia dla danego miesiąca + 5] dni, potwierdzone wpisem do dziennika budowy i zaakceptowane przez inspektora nadzoru; termin przedłuża się o liczbę dni ponad ten próg."

- id: R17
  name: Koordynacja z infrastrukturą i inwestycjami innych podmiotów (drogi, kolej, inne sieci, odtworzenia)
  status: proposed
  level: 1
  rationale: "11% ogłoszeń o zmianie dotyczy dróg/nawierzchni; najdłuższy ogon kosztowy (P90 +19,5%)."
  signals:
    - {doc_types: [PFU, OPZ, QA, FUNDING_DESC], patterns: ['w (ciągu|pasie) drogi (wojewódzkiej|krajowej|powiatowej)', 'przebudow\w* drogi', 'równocześnie z', 'zarządc\w* drogi', 'koordynac'], strength: 0.35}
  events: [EV_TERM_EXTENSION, EV_ADDITIONAL_WORKS]
  effects: {empirical: {category: drogi/nawierzchnie/koordynacja, n: 204, p_late: 0.66, delay_days: {p50: 62, p75: 134}, cost_pct: {p50: 0.021, p75: 0.085, p90: 0.195}, source: BZP_2022_2026}}
  mitigations: [porozumienie z zarządcą drogi o harmonogramie i zakresie odtworzeń, wspólny harmonogram z inwestycją drogową]

- id: R18
  name: Zależność efektu od zadań powiązanych (sieć ↔ oczyszczalnia/SUW/kolektor innego podmiotu)
  status: proposed
  level: 1
  rationale: "Poradnik 04 §3.3, §4.3, §7.5; przykłady: RM-2026-002 (wpięcie do oczyszczalni w budowie), zmiana umowy Uście (podłączenie do sieci gminy Wolsztyn)."
  signals:
    - {doc_types: [FUNDING_DESC, PFU, OPZ, NOTICE_DESC], patterns: ['(realizowan|budowan|projektowan)\w* obecnie (oczyszczalni|sieci|stacji)', 'etap (I|II|III|1|2|3)\b', 'w ramach odrębnego zadania', 'podłączeni\w* do (sieci|kolektora) (gminy|miasta)'], strength: 0.40}
  events: [EV_LOW_CONNECTION, EV_TERM_EXTENSION]
  mitigations: [harmonogram zadań powiązanych w jednym planie, warunek gotowości odbiornika przed odbiorem sieci, porozumienie międzygminne]
  checklist_refs: ['04:3.3', '04:4.3', '04:6.6.1', '04:7.5']
```

### 2.6 Red flags for a *new* investment (rule → flag shown in the analysis screen)

| # | Flag (UI text, PL) | Trigger | Code |
|---|---|---|---|
| F1 | „Brak badań geotechnicznych przy trasie w terenie o wysokich wodach gruntowych” | state(GEOTECH) ∈ {BRAK_W_PACZCE, DOKUMENT_NIE_WSPOMINA} AND (valley/wetland OR R02.1 pattern) | R02.1 |
| F2 | „Trasa przez grunty prywatne bez potwierdzonego prawa do dysponowania” | R03.2 pattern AND state(zgody) ≠ POTWIERDZONO | R03.2 |
| F3 | „Sieć kanalizacyjna ≥ 1 km – brak informacji o decyzji środowiskowej” | length ≥ 1 km AND DŚU state ∈ {BRAK_W_PACZCE, DOKUMENT_NIE_WSPOMINA} | R04.1 |
| F4 | „Przekroczenie cieku/drogi wyższej kategorii/kolei – uzgodnienia nieznane” | R03.3 pattern | R03.3, R04.2 |
| F5 | „Termin wykonania koliduje z terminem dofinansowania (bufor < 2 mies.)” | funding deadline − planned end < 60 d | R06.1, R13.1 |
| F6 | „Czas realizacji krótszy niż u 75% podobnych inwestycji” | planned_duration < P25(reference class) adjusted for length | R06 |
| F7 | „Umowa > 6 mies. bez klauzuli waloryzacyjnej / limit ≤ 5%” | §1.3 rules | R08.1 |
| F8 | „Ryczałt przy ilościach orientacyjnych” | R01.2 + ryczałt | R08.2, R01.2 |
| F9 | „Kosztorys inwestorski nieaktualny” | estimate date older than 6 months AND GUS index change > 5% | R11.1 |
| F10 | „Zakres bez przyłączy i bez programu przyłączeń” | R15.1 rule | R15.1 |
| F11 | „Efekt zależny od innego zadania” | R18 patterns | R18 |
| F12 | „Formuła ZiW z wymaganymi decyzjami i terminem < 12 mies.” | R06.2 rule | R06.2 |
| F13 | „Brak mierzalnych parametrów technologicznych (OŚ/SUW)” | R09.1 rule | R09.1, R10.1 |
| F14 | „Zimowe roboty ziemne bez rezerwy” | R16 rule | R16 |
| F15 | „PPU z klauzulami ryzykownymi wg art. 433 Pzp” | R11.3 rule | R11.3, R05 |

---

## 3. Evidence: statistics on cost overruns and delays

### 3.1 Own analysis of BZP notices (the sector prior)

**Data.**
- Source: the BZP mirror `https://bzp.cytr.us` (same API as e-Zamówienia), queried 2026-11-21.
- Queries: `NoticeType ∈ {ContractPerformingNotice, AgreementUpdateNotice, TenderResultNotice}`, CPV filters {45231300-8, 45232400-6, 45252100-9, 45232410-9, 45232150-8, 45252127-4}, quarterly windows 2022Q1–2026Q4, `PageSize=500`.
- Records kept when the title matches wod-kan stems (`kanaliz|wodoci|oczyszczal|ściek|uzdatn|deszczow|przepomp|tłoczn|SUW|retencj`) and the main CPV starts with 45.
- **It is a large sample, not a census.** 12 of 120 completion-notice windows and 18 of 60 result-notice windows hit the 500 cap.
- Subsector: heuristic by the first matching title stem, in the order oczyszczalnia → uzdatnianie → deszczowa → kanalizacja → wodociąg.
- ZiW = `zaprojektuj|projektuj i buduj|zaprojektowanie i (wykonanie|budowa)` in the title or the start of the description.

**Measures.**
- `cost_pct` = 5.5 / 4.4 − 1, for performed contracts with 0.2 < ratio < 5.
- `delay_days` = 5.2 − planned end. The planned end is taken from 4.2: the date, or 4.1 + duration.
- `delay_rel` = delay_days / (planned end − 4.1), for planned durations > 14 days.

**Table A, sector prior by group (completion notices, contracts performed, 2022–2026)**

| Group | n | P(5.3 = late) | P(≥1 change) | P(paid > contract) | cost_pct P50 / P80 / P90 | delay_days P50 / P80 / P90 | delay_rel P50 / P80 / P90 |
|---|---|---|---|---|---|---|---|
| All wod-kan | 7,105 | 31% | 43% | 24% | 0.0% / +1.6% / +7.4% | 0 / 46 / 107 | 0% / +24% / +52% |
| Kanalizacja sanitarna | 3,809 | 31% | 44% | 25% | 0.0% / +1.9% / +7.9% | 0 / 46 / 106 | 0% / +24% / +50% |
| Sieć wodociągowa | 1,560 | 24% | 32% | 17% | 0.0% / 0.0% / +5.7% | 0 / 24 / 67 | 0% / +22% / +48% |
| Oczyszczalnia ścieków | 783 | 40% | 53% | 26% | 0.0% / +1.5% / +5.1% | 4 / 84 / 158 | +2% / +28% / +53% |
| Uzdatnianie / SUW / ujęcia | 375 | 38% | 50% | 26% | 0.0% / +1.6% / +6.5% | 1 / 79 / 152 | +1% / +28% / +58% |
| Kanalizacja deszczowa / retencja | 521 | 33% | 53% | 38% | 0.0% / +5.8% / +10.6% | 0 / 43 / 91 | 0% / +27% / +66% |
| Formuła zaprojektuj i wybuduj | 676 | **50%** | **62%** | 25% | 0.0% / +1.7% / +7.5% | 19 / **129** / 180 | +5% / +30% / +56% |
| Formuła „buduj” | 6,429 | 29% | 41% | 24% | 0.0% / +1.6% / +7.3% | 0 / 39 / 91 | 0% / +23% / +51% |
| Wartość umowy < 1 mln zł | 3,960 | 22% | 29% | 15% | 0.0% / 0.0% / +4.4% | 0 / 19 / 54 | 0% / +19% / +49% |
| 1–5 mln zł | 2,304 | 41% | 57% | 32% | 0.0% / +3.7% / +10.0% | 7 / 70 / 135 | +3% / +31% / +60% |
| 5–20 mln zł | 805 | 47% | 71% | 46% | 0.0% / +4.4% / +9.7% | 17 / 125 / 199 | +4% / +28% / +45% |
| ≥ 20 mln zł | 36 | 67% | 75% | 72% | +1.5% / +5.1% / +8.6% | 35 / 143 / 185 | +8% / +32% / +51% |
| Co-funded by EU (3.3 = Tak) | 1,613 | 37% | 48% | 22% | 0.0% / +1.0% / +6.1% | 2 / 52 / 107 | +1% / +28% / +55% |
| Published 2022 | 1,147 | 27% | 35% | 19% | 0.0% / 0.0% / +6.4% | 0 / 31 / 67 | 0% / +23% / +50% |
| Published 2023 | 1,323 | 26% | 38% | 23% | 0.0% / +1.4% / +6.1% | 0 / 32 / 79 | 0% / +16% / +44% |
| Published 2024 | 1,478 | 31% | 43% | 25% | 0.0% / +1.7% / +8.0% | 0 / 48 / 123 | 0% / +24% / +51% |
| Published 2025 | 1,737 | 32% | 47% | 27% | 0.0% / +2.3% / +7.4% | 0 / 55 / 122 | 0% / +23% / +43% |
| Published 2026 | 1,420 | **39%** | **51%** | 26% | 0.0% / +2.3% / +8.1% | 3 / 60 / 140 | +2% / +35% / +70% |

Threshold shares (all wod-kan).
- **Delay:** > 0 d 46.9%; > 7 d 38.9%; > 30 d 24.6%; > 90 d 11.7%; > 180 d 4.3%; > 365 d 1.0%.
- **Cost:** paid > contract by > 0.1% 24.3%; > 5% 12.9%; > 10% 7.6%; > 20% 2.6%; > 30% 1.1%. Paid < contract by > 1%: 6.4%; by > 10%: 2.0%.
- **Not performed** (5.1 = Nie): 0.5%. **Improper** (5.6 = Nie): 0.7%.
- **Contracts with a pkt 3/4 change** (n = 835): cost_pct P50 +2.1%, P75 +9.6%, P90 +20.9%.

**Table B, hurdle-model parameters** (use these directly as priors in §4)

| Group | p_pos = P(cost_pct > 0.1%) | positive cost_pct P25 / P50 / P75 / P90 | ln(cost_pct) of positives: μ / σ | P(delay > 0) | positive delay days P50 / P75 / P90 | ln(delay days) of positives: μ / σ | median planned duration (d) |
|---|---|---|---|---|---|---|---|
| All | 0.24 | 2.3% / 5.5% / 12.0% / 20.5% | −3.00 / 1.21 | 0.47 | 33 / 90 / 170 | 3.37 / 1.52 | 180 |
| Kanalizacja sanitarna | 0.25 | 2.3% / 5.6% / 12.8% / 22.5% | −2.97 / 1.23 | 0.48 | 32 / 90 / 164 | 3.35 / 1.51 | 183 |
| Sieć wodociągowa | 0.17 | 3.1% / 7.5% / 14.6% / 22.0% | −2.75 / 1.13 | 0.39 | 25 / 69 / 148 | 3.09 / 1.52 | 122 |
| Oczyszczalnia | 0.26 | 1.6% / 3.4% / 8.2% / 13.0% | −3.41 / 1.21 | 0.56 | 50 / 121 / 217 | 3.69 / 1.51 | 304 |
| Uzdatnianie | 0.26 | 1.8% / 4.6% / 10.3% / 15.4% | −3.21 / 1.17 | 0.52 | 52 / 123 / 259 | 3.76 / 1.50 | 274 |
| Deszczowa | 0.38 | 3.4% / 6.2% / 11.3% / 15.0% | −2.93 / 1.13 | 0.47 | 30 / 78 / 151 | 3.31 / 1.46 | 152 |
| Zaprojektuj i wybuduj | 0.25 | 2.2% / 5.5% / 12.1% / 17.5% | −3.03 / 1.25 | 0.63 | 67 / 152 / 230 | 3.93 / 1.45 | 426 |

Fit check for the log-normal size model.
- Cost: exp(μ) gives P50 5.0% vs empirical 5.5%. exp(μ + 1.28σ) gives P90 23.5% vs empirical 20.5%. So the model is slightly conservative in the tail.
- Delay: P50 29 d vs 33 d; P90 204 d vs 170 d.
- Prior-only hurdle simulation for kanalizacja 1–5 M zł (p_pos = 0.32): P80 +3.5% and P90 +9.4%, vs empirical +3.6% and +10.1%.

**Table C, pre-award (result notices, wod-kan tender parts)**

| Year | parts n | cancelled | of which art. 255 pkt 3 / pkt 1 / pkt 2 | median offers | single-offer share | award / (estimate × 1.23): P25 / median / P75 | max/min offer price (median) |
|---|---|---|---|---|---|---|---|
| 2022 | 2,045 | **31%** | 390 / 149 / 34 | 3 | 25% | 0.75 / 0.92 / 1.02 | 1.37 |
| 2023 | 2,110 | 24% | 317 / 83 / 23 | 3 | 16% | 0.72 / 0.86 / 1.00 | 1.46 |
| 2024 | 1,871 | 16% | 208 / 39 / 21 | 4 | 10% | 0.68 / 0.81 / 0.98 | 1.52 |
| 2025 | 1,884 | 11% | 111 / 17 / 12 | 5 | 9% | 0.55 / 0.74 / 0.94 | 1.66 |
| 2026 | 1,504 | 12% | 80 / 18 / 19 | 6 | 6% | 0.53 / 0.71 / 0.89 | 1.73 |

- **All years:** 19% of parts cancelled. Cancellation bases:

| Basis | Count | Share of cancellations |
|---|---|---|
| art. 255 pkt 3 (price above budget) | 1,106 | 61% |
| pkt 1 (no offers) | 306 | 17% |
| pkt 2 (all offers rejected) | 109 | 6% |
| pkt 6 (irremediable defect) | 98 | 5% |
| art. 310 | 67 | - |
| pkt 5 | 29 | - |
| art. 256 | 28 | - |
| pkt 7 | 25 | - |

- **Award / (estimate × 1.23)**, n = 2,073 single-part procedures with an estimate: P10 0.44, P25 0.64, median 0.81, P75 1.00, P90 1.12. In 20% of cases the award was above the gross estimate.
- **Reading:**
  - 2022 was a "budget shock" year: estimates lagged inflation, so cancellations were high and offers few.
  - From 2024 the market loosened: more offers and prices well below estimates.
  - Hence **"year/price regime" must be a similarity feature (§5)** and **R11.1/R12.3 signals are period-dependent.**

**Table D, change notices** (pkt 3/4, n = 1,163): see §1.2. Price-raising changes: P50 +5.5%, P90 +22.9% of the original value.

> Limitations of the BZP baseline:
> - It measures **contract** outcomes (award → final), not project outcomes (budget at decision → final).
> - It depends on the zamawiający's self-reporting (5.3/5.6 are self-declared; see the 10.9% inconsistency).
> - 4.2 may contain an amended end date. That biases delays downwards.
> - Lump-sum contracts mask cost growth inside the contract price.
> - It does not include unpublished notices (non-compliance with art. 448).

### 3.2 NIK: audit P/20/046 „Zbieranie i oczyszczanie ścieków komunalnych” (2022)

Report: nr ewid. 164/2021/P/20/046/KSI. PDF: <https://www.nik.gov.pl/plik/id,25776,vp,28549.pdf>. Press release: <https://www.nik.gov.pl/2022/04/zbieranie-i-oczyszczanie-sciekow-bez-nadzoru-grozba-dotkliwych-kar-finansowych-ze-strony-ue.html>
- **Spending vs plan.** In the 40 audited agglomerations, 1,366.9 M zł was spent on AKPOŚK 2017 tasks by 30.09.2020. That is **30.2% of planned outlays**: 34.0% for networks, 20.7% for treatment plants.
- **Delays.** Only **7 agglomerations** implemented without delays against the AKPOŚK 2017 deadlines. Delays came mainly from insufficient own funds and failure to obtain (enough) co-financing (p. 67) → R13.
- **Compliance.** Only **4 of 44 (9.1%)** agglomerations met all conditions of Directive 91/271/EEC (p. 60).
- **Connections.**
  - 20 gminy had no data on properties that should be connected.
  - In 26 gminy there were **5,088–6,360 unconnected properties** on networks built by end-2017, and **866–1,152** on networks built later.
  - Only **6 gminy systematically enforced** the obligation to connect.
  - 512 proceedings covered **7%** of unconnected properties; 311 decisions were issued; 90 were executed (pp. 114–120) → **R15.1**.
- **Connection requests.** 45,905 requests to connect were filed with operators; **77.5% approved**. Refusals cited, among other things, insufficient capacity → R04.4.
- **Non-sewered areas.** Only about **43%** of liquid waste from non-sewered areas was collected; 2/3 of gminy collected less than half.
- **EU penalty risk.** NIK warns of a possible EU penalty of nearly **6 bn EUR** for non-implementation of 91/271/EEC in 2016–2020.

### 3.3 European Commission: ex post evaluation of environment major projects 2000–2013

SWD(2020) 43 final, 21.2.2020: <https://ec.europa.eu/regional_policy/sources/evaluation/swd_ex_post_env_2000_2013_en.pdf>
- **Overall.** Of 10 case studies, **7 had time overruns and 3 had cost overruns.** "Budget planning proved to generally be accurate." Delays were primarily due to contractor underperformance, low capacity, slow procurement and unpredicted exogenous factors such as weather. Demand forecasting was the most problematic determinant of performance → R15.1.
- **Poland, Sochaczew sewage management.**
  - Delays of over a year due to slow procurement.
  - Builders met roughly **50-year-old underground infrastructure not in registers or maps**, requiring additional works and design changes → R03.1.
  - Cost **underrun of −51%** from crisis-era prices and competitive tendering; the project was split into smaller contracts.
- **Other cases.**
  - Bulgaria, Sofia water cycle: +3 years (expropriation) and **+32%** cost → R03.2.
  - Romania, Craiova: contractor underperformance, contractor replaced through a new tender → R12.1.
  - Slovenia: the first two contractors went **bankrupt**.

### 3.4 Reference-class base rates (Oxford Global Projects / Flyvbjerg)

Budzier, Flyvbjerg et al., *The Oxford Olympics Study 2024*, Table 5 (source: Oxford Projects Database Q2 2023; real terms, local currencies): <https://arxiv.org/abs/2406.01714>

| Project type | n | Mean cost overrun | On or below budget | Overrun > 50% |
|---|---|---|---|---|
| **Water** | 345 | **15%** | 40% | 11% |
| Pipeline | 412 | 14% | 45% | 6% |
| Road | 2,250 | 16% | 42% | 9% |
| Building | 310 | 52% | 29% | 25% |
| Dam | 334 | 71% | 26% | 35% |

- The baseline in this database is the budget at the **decision to build**. That is a wider window than our award→final measure, which explains why the means differ: 15% vs +1.6%.
- Method references: Flyvbjerg (2006), "From Nobel Prize to Project Management: Getting Risks Right", *Project Management Journal* 37(3); Flyvbjerg et al. (2002/2003) on transport.

### 3.5 HM Treasury Green Book: optimism bias uplifts (Mott MacDonald 2002)

<https://www.gov.uk/government/publications/green-book-supplementary-guidance-optimism-bias>
- Values below are verified from the guidance PDF table. The guidance tells appraisers to start from the upper bound and reduce it as contributory factors are mitigated.

| Project type | Works duration: upper / lower | Capital expenditure: upper / lower |
|---|---|---|
| Standard civil engineering | 20% / 1% | 44% / 3% |
| Non-standard civil engineering | 25% / 3% | 66% / 6% |

- "Standard civil engineering" includes "most new roads and some utility projects". Wod-kan networks are standard; WWTP modernisations and upgrades are non-standard.
- Use: as an *outer bound* sanity check for pre-decision budgets (project level).

### 3.6 Polish academic studies on wod-kan construction

| Study | Sample | Findings |
|---|---|---|
| Rybka, Bondar-Nowakowska, Połoński (2016), "Causes and effects of adverse events during water supply and sewerage construction", *Archives of Civil Engineering* 62(1). PDF via <https://czasopisma.pan.pl/Content/84083> | 12 sites, Lower Silesia/Opole, 2010–2014 | Time overrun 0–60% of contract time (one site not completed); cost overrun 0–6%. Stoppages: 6–75% of observations (mean 31%). Causes: worker discipline 34%, **weather 25%**, organisation 17%, financing assumptions 12%, design errors 6%, lack of investor supervision 5% |
| Rybka, Bondar-Nowakowska (2013), "Risk of alterations to project documentation on an example of environmental engineering construction", *Archives of Civil Engineering* LIX(4), DOI 10.2478/ace-2013-0027. <https://czasopisma.pan.pl/Content/83907> | 2 sewer contracts | Red Book (employer's design): **92 design alterations, +14.42%** of the accepted contract amount. Yellow Book (design-build): **1 alteration, +7.01%**. Expert survey: 96% confirm frequent design flaws; 71% say they raise costs |
| "Cost Risk in Water and Sewerage Systems Construction Projects" (ResearchGate 309271479; metadata not verified, 403) | - | Abstract snippet: time overruns 0–203%, cost overruns 0–25%; design problems the main cause |
| Skorupka (2015), "Identification of risk factors in water supply and sewage projects", *Logistics and Transport* 4/2015 | - | Risk-factor identification (qualitative). <https://yadda.icm.edu.pl/baztech/element/bwmeta1.element.baztech-3cc75346-c3a4-4fc1-8ed9-fd307795c84b> |

### 3.7 Macro and context numbers

- **GUS construction prices**, "budowa obiektów inżynierii lądowej i wodnej", y/y: **XI 2022 +14.8%**, **I 2023 +13.2%**, **XII 2023 +8.8%**.
  - GUS releases: <https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-produkcji-budowlano-montazowej-w-listopadzie-2022-roku,15,48.html>, <https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-produkcji-budowlano-montazowej-w-grudniu-2023-roku,15,61.html>
  - These are the deflators to use in §4.2 and the reference index for art. 439 clauses.
- **KPO B3.1.1 deadlines.** MFiPR answer of 15.05.2026 to interpellation 16654: <https://api.sejm.gov.pl/sejm/term10/interpellations/16654/body>. Details in §1.7.
- **Insolvency.** Construction was about 17–18% of company insolvencies in Poland in 2025 (H1 2025: 643 construction firms; Coface via press): <https://bank.pl/?p=524271>. Secondary source; verify before quoting in the product.
- **Not found:** no dedicated UZP statistical report analysing "ogłoszenia o wykonaniu umowy" (delay and change shares) was located. Our §3.1 analysis fills this gap and is itself a strong demo point: the system *produces* the sector statistic from public data.

---

## 4. Forecasting with small samples (reference class forecasting)

### 4.1 Target variables (three different horizons, never mixed)

| Variable | Definition | Data | Horizon |
|---|---|---|---|
| `budget_pct` | award_gross / (estimate_net × (1+VAT)) − 1, or award / kwota (art. 222 ust. 4) − 1 | result notice, platform | planning → award |
| `cost_pct` | paid_gross (5.5) / contract_gross (4.4) − 1 | completion notice | award → completion |
| `project_pct` | final project cost / project budget at funding decision − 1 | CST/KPO lists, WPF, NIK | decision → completion |
| `delay_days`, `delay_rel` | actual end − planned end; ÷ planned duration | completion notice (+ PPU/SWZ for the original term) | contract |
| `p_event[k]` | share of reference cases where event k (EV_*) occurred | events table | contract |

The forecast for a planned investment combines `budget_pct` (risk that the estimate is wrong) with `cost_pct` (execution growth): `final/estimate = (1+budget_pct)(1+cost_pct)`. Simulate both by Monte Carlo from their own reference classes.

### 4.2 Normalisation before comparing

1. **Gross/net**, §1.6.
2. **Price level**, deflate all amounts to a base month with the GUS construction-price index for civil engineering: `amount_base = amount_t × I_base / I_t`. Use the month of the offer deadline for awards and the completion month for payments.
3. **Size**, compare unit values (zł per m of network by type, zł per RLM, zł per m³/d) only within the same subsector. Unit costs are heavy-tailed, so compare them on a log scale.
4. **Contract vs project**, never compare a contract value with a project value (the dataset's KPO "wartość przedsięwzięcia" includes non-construction costs).

### 4.3 Algorithm

```
INPUT: new investment x, case base D (completed contracts with outcomes), sector prior table P (Table A/B)
1. sim_j = similarity(x, d_j) for all j               # §5
2. R = top-k by sim with sim_j ≥ s_min                 # k ≤ 30, s_min = 0.55 (configurable)
3. weights w_j = sim_j^γ  (γ = 3)                      # emphasise the closest cases
   n_eff = (Σ w_j)² / Σ w_j²                           # Kish effective sample size
4. Hurdle decomposition per target variable y:
   a) occurrence: k_pos = Σ w_j×[y_j > 0] ; p̂ = k_pos/Σ w_j
   b) size: z_j = ln(y_j) for y_j > 0 (cost overrun as a fraction) or ln(delay_days) (time)
5. Shrinkage to the sector prior (group = subsector × formula, from Table B):
   occurrence: Beta(α0 = m×p0, β0 = m×(1−p0)), m = 10
       posterior p ~ Beta(α0 + k_pos×n_eff/Σw, β0 + (Σw−k_pos)×n_eff/Σw)
   size: Normal-Normal on z with prior mean μ0 and prior weight m0 = 10 pseudo-cases
       μ_post = (n_pos×z̄ + m0×μ0)/(n_pos + m0)
       σ = pooled σ (sector σ if n_pos < 10; else sample σ shrunk to sector σ)
       predictive z ~ N(μ_post, σ²(1 + 1/(n_pos + m0)))
6. Monte Carlo (≥ 20 000 draws): y = 0 with prob 1−p, else exp(z) (cost fraction or days); cap draws at a sanity limit (e.g. 150% / 1 500 d)
   → P50, P80, P90 and P(y > threshold) for thresholds {5%, 10%, 20%} / {30, 90, 180 d}
7. Uncertainty of the quantiles: weighted bootstrap of R (B = 2000), repeating steps 4–6
   → 90% interval for P50 and P80 (show as whiskers)
8. Tier the output by n_eff (§4.4). Attach: n, n_eff, list of case IDs, prior weight share = m/(m+n_eff)
```

Why these choices:
- **Hurdle model.** 76% of contracts have exactly zero cost growth. A single log-normal would be badly mis-specified, and a plain mean hides the 24% that do grow.
- **Log-normal size.** Positive overruns and delays span two orders of magnitude (0.1%–100%, 1–1 000 d). ln(y) is close to Normal. The fit check under Table B shows it reproduces the empirical quantiles, slightly conservatively in the tail.
- **m = 10 pseudo-observations.** With n_eff = 10 the prior and the cases weigh equally; with n_eff = 30 the prior weighs 25%. Expose `m` in the expert panel ("siła tła sektorowego") so it can be edited without code. The brief requires that.
- **Kish n_eff.** It prevents weighted samples dominated by 1–2 very similar cases from pretending to be large.
- **Weighted empirical quantiles** (when n_eff ≥ 20): sort y, accumulate normalised weights, interpolate at 0.5, 0.8 and 0.9 (Harrell–Davis is also fine). Do not use type-7 unweighted quantiles on weighted data.
- **Small-proportion intervals.** For "k of n" statements use the **Wilson** interval. For example, 3 of 9 gives a 90% interval of 14–60%; 4 of 6 gives 35–88%. Never use the Wald interval.

### 4.4 What to show depending on sample size

| n_eff | Show | Label (PL) |
|---|---|---|
| ≥ 20 | P50/P80/P90 from cases (prior weight ≤ 33%), bootstrap whiskers, P(threshold) | „Pewność: wysoka (n = …, n_eff = …)” |
| 8–19 | Shrunk P50/P80/P90 with whiskers; list of cases; prior share in % | „Pewność: średnia – wynik łączy {n} przypadków i tło sektorowe ({x}%)” |
| 5–7 | P50 and P80 only (no P90); cases listed individually; prior share explicit | „Pewność: niska – mała grupa porównawcza” |
| < 5 | **No case-based percentiles.** Show each case's actual outcome as a dot or row (value, cause, link). Show the sector prior distribution (Table A/B) **labelled "tło sektorowe BZP 2022–2026, n = …"**, and qualitative flags | „Za mało podobnych przypadków (n = {n}) do wyznaczenia przedziału. Poniżej: wyniki poszczególnych przypadków oraz rozkład dla całego podsektora.” |
| 0 | Sector prior only, plus the list of checks | „Brak podobnych zakończonych inwestycji w bazie” |

Communication rules:
1. Always print **n and n_eff**, the **period** covered and the **measure definition** (e.g. "wzrost = wypłata/wartość umowy brutto").
2. Use frequencies, not just percentages: „w 4 z 9 podobnych umów (44%; przedział 90%: 19–73%)”.
3. Separate **source data** (case values with links), **calculation** (quantiles and intervals) and **model inference** (shrinkage and similarity). The brief requires this visual separation.
4. Show asymmetry: „P80 = +6%” means „w 1 na 5 podobnych umów wzrost był większy niż 6%”.
5. Never show more than two significant digits on a forecast.
6. If the case base is dominated by one beneficiary or one year, say so: „5 z 8 przypadków to umowy z 2022 r. (szok cenowy)”.

### 4.5 Worked example

**Planned investment.** Kanalizacja sanitarna, about 3 M zł, formula "buduj", 2027.
- Sector group from Table A (kanalizacja, 1–5 M zł, build-only, n = 1,218):
  - P(late) 39%; P(≥1 change) 56%; P(paid > contract) 32%;
  - cost_pct P80 +3.6%, P90 +10.1%;
  - delay P50 5 d, P80 61 d, P90 124 d; delay_rel P80 +30%.
  - → Reserve guidance: about +4% (P80) or +10% (P90) on the contract value. The schedule buffer is about 30% of the planned duration at P80.

**Reference class of 8 cases** (n_eff = 6).
- 3 of the 8 had a cost increase: +5%, +15% and +25%, so z̄ = mean(ln y) = −2.09.
- Occurrence: prior p0 = 0.25 (Table B), m = 10 → posterior p ≈ 0.31.
- Size: μ0 = −2.97, σ = 1.23 (Table B, kanalizacja), m0 = 10 → μ_post = (3×(−2.09) + 10×(−2.97))/13 = −2.77, so the positive-part median is +6.3%.
- Monte Carlo of the combined distribution: **P50 = 0%, P80 ≈ +4%, P90 ≈ +11%, P(wzrost > 10%) ≈ 11%** → tier "niska pewność". Show P50/P80 and list the 8 cases.
- For comparison, a plain bootstrap of an n = 8 sample drawn from the BZP class (values −8.3%, 0, 0, 0, 0, 0, +5.6%, +6.7%) gives a 95% CI for P80 of [0%, +6.7%]. That is too narrow because the sample cannot show the tail. **This is exactly why shrinkage is needed for small n.**

**Delay probability** with 4 of 6 late: posterior mean (4 + 3.1)/(6 + 10) = 0.44, 90% credible interval ≈ 0.25–0.64. The raw Wilson interval is 0.35–0.88.

### 4.6 Validation

- **Leave-one-out on the case base.** Coverage of the P80 interval should be about 80%. Brier score for event probabilities. Calibration plot in 5 bins.
- **Backtest by time.** Train on contracts finished by year T, test on T+1. This shows the 2022 regime shift honestly.
- **Report in the "Raport z testu"** that the brief requires: coverage, Brier score, and how the result depends on `m` and `s_min`.

---

## 5. Similarity: structured features + text, with an explanation of what decided it

### 5.1 Features, similarity functions and default weights

S(x, d) = Σ w'_i, s_i(x, d), where w'_i = w_i / Σ_{i ∈ A} w_i and A is the set of features present in **both** records.
**Coverage** = Σ_{i ∈ A} w_i, reported to the user.

| # | Feature | Extraction | s_i (0–1) | w_i |
|---|---|---|---|---|
| 1 | `subsector_main` | §7 classifier | 1 same; 0.6 if one's main = other's secondary; 0.3 same family (networks: wodociąg/kanalizacja/deszczowa; plants: oczyszczalnia/uzdatnianie); 0 otherwise | **0.20** |
| 2 | `subsectors_all` | main ∪ secondary | Jaccard | 0.05 |
| 3 | `works_type` | §7.3 | 1 same; 0.5 mixed vs pure; 0 opposite | 0.07 |
| 4 | `formula` | ZiW vs buduj | 1 same; 0 different (ZiW doubles the late probability, Table A) | 0.08 |
| 5 | `value` | contract gross, deflated (§4.2); for a new project, the estimate × 1.23 | Gaussian kernel on log ratio: exp(−(ln(v₁/v₂))² / (2×ln(2)²)). Ratio 2 → 0.61, 3 → 0.37, 5 → 0.13 | **0.12** |
| 6 | `physical_size` | network km (by type); plants RLM or m³/d; SUW m³/h | same kernel, σ = ln 2 | **0.10** |
| 7 | `tech_tags` | regex tags: grawitacyjna, tłoczna, ciśnieniowa, podciśnieniowa, przepompownie, przyłącza, sięgacze, przewiert/HDD, przekroczenie cieku, pas DW/DK, teren prywatny, SBR, osad czynny, filtry/odżelazianie, studnia głębinowa, zbiornik, renowacja bezwykopowa, rozdział ogólnospławnej, retencja | Jaccard | 0.07 |
| 8 | `period` | year of offer deadline; price regime {≤2021, 2022–23, ≥2024} | exp(−\|Δyear\|/3), × 0.7 if regimes differ | 0.06 |
| 9 | `funding` | KPO, FEnIKS/POIiŚ, FEP/RPO, PROW, RFIL/PIS, NFOŚ/WFOŚ, own | 1 same; 0.5 same family (EU); 0 otherwise | 0.04 |
| 10 | `beneficiary_type` | gmina wiejska / miejsko-wiejska / miejska / spółka wod-kan / związek / inne (ZDW) | 1 same; 0.6 gmina–gmina; 0.2 otherwise | 0.03 |
| 11 | `region` | TERYT voivodeship (+ optional terrain class) | 1 same; 0.5 neighbouring; 0.2 otherwise | 0.05 |
| 12 | `text` | dense embedding of (title + 3.8 description + scope summary) plus BM25 on technical terms | s = clip((0.7×cos + 0.3×bm25_norm − c0)/(c1 − c0), 0, 1). c0 = median similarity of random pairs, c1 = P99 | **0.13** |

Sum of weights = 1.00. Structured part = 0.87; text = 0.13.
- Rationale: structured features drive the outcome distributions (Table A shows strong effects of subsector, formula and size).
- Text catches what the structure misses (e.g. "kanalizacja podciśnieniowa", "przewiert pod DK").
- The text weight is deliberately limited, because embeddings over-reward look-alike boilerplate (SWZ templates).

Inclusion rules:
- **Reference class for forecasts:** only cases with outcomes (completion notice or equivalent), S ≥ 0.55 and coverage ≥ 0.5.
- **"Lessons" list:** any case with events, ranked by S.
- **Diversity:** at most 2 cases per beneficiary in the top 10 (MMR, λ = 0.7). Mark the same beneficiary with a badge (institutional memory, e.g. Czernikowo ×2, Nowogard ×2 in the dataset).

### 5.2 Explanation ("co przesądziło o podobieństwie")

- contribution `c_i = w'_i, s_i`
- gap `g_i = w'_i, (1 − s_i)`

Show:
1. **Dlaczego podobne**, top 3 c_i, from templates:
   - „Ten sam podsektor główny: Kanalizacja sanitarna (+0,20)”
   - „Zbliżona wartość: 3,1 vs 2,7 mln zł brutto, ceny 2026 (+0,11)”
   - „Podobna długość sieci: 2,4 vs 3,0 km (+0,08)”
   - „Wspólne elementy: przepompownie, przyłącza do granicy działki (+0,05)”
2. **Kluczowe różnice**, top 2 g_i:
   - „Formuła: zaprojektuj i wybuduj vs buduj (−0,08)”
   - „Inny okres cenowy: 2022 vs 2026 (−0,03)”
3. **Dopasowanie tekstu**, 2–3 matched phrases or BM25 terms, with document locators.
4. **Pokrycie danych**, e.g. „porównanie oparto na 9 z 12 cech (pokrycie 0,78)”.
5. **Dopasowanie ryzyk**, a separate badge, *not* part of S: overlap between the new project's open risk signals and the case's realised events. Example: „sygnał: grunty prywatne → w tym przypadku: zmiana trasy, +46 dni”. Keeping it separate avoids circular reasoning.

Render the explanation as a stacked bar (contributions sum to S). Store `similarity_explanations` as records (case_id, feature, s_i, w'_i, c_i, text) so they can be exported to JSON/CSV and edited by the expert.

### 5.3 Learning from expert feedback

- Log every expert action on a suggested case: accept, reject, "bardziej/mniej podobne".
- After ≥ 30 labels, fit a non-negative logistic regression on the vector (s_1…s_12) → w_learned.
- Blend: `w = (1−λ)×w_default + λ×w_learned`, with λ = n_labels/(n_labels + 50).
- Keep weights in YAML so they can be edited in the panel without code:

```yaml
similarity:
  version: 1
  min_similarity: 0.55
  min_coverage: 0.5
  top_k: 30
  weight_gamma: 3          # forecast weights = sim^gamma
  max_per_beneficiary_top10: 2
  features:
    subsector_main:   {w: 0.20, family_bonus: 0.3, secondary_match: 0.6}
    subsectors_all:   {w: 0.05, fn: jaccard}
    works_type:       {w: 0.07, mixed: 0.5}
    formula:          {w: 0.08}
    value:            {w: 0.12, fn: log_gauss, sigma_ln: 0.693, deflator: GUS_ILW}
    physical_size:    {w: 0.10, fn: log_gauss, sigma_ln: 0.693}
    tech_tags:        {w: 0.07, fn: jaccard}
    period:           {w: 0.06, tau_years: 3, regime_penalty: 0.7, regimes: [[0,2021],[2022,2023],[2024,9999]]}
    funding:          {w: 0.04, family: {EU: [KPO, FENIKS, POIIS, FEP, RPO, PROW]}}
    beneficiary_type: {w: 0.03}
    region:           {w: 0.05, neighbour: 0.5, other: 0.2}
    text:             {w: 0.13, dense: 0.7, bm25: 0.3}
```

---

## 6. Evidence states and the confidence model

### 6.1 Evidence states for any "check item"

A check item is a question such as „czy uzyskano decyzję środowiskową?”, „czy były roboty dodatkowe?” or „czy umowę wykonano w terminie?”.

| State (enum) | PL label | Definition | Effect on risk | Effect on completeness C | Example | Suggested action text |
|---|---|---|---|---|---|---|
| `JESZCZE_NIEWYMAGALNY` | jeszcze niewymagalny | The document cannot exist yet (e.g. completion notice before planned end + 30 d) | none | excluded from C | contract runs until 2026-12 | - |
| `BRAK_W_PACZCE` | brak w paczce | No document of an expected type is in the package, and the automatic search found nothing. Reason code: `nie_szukano` / `szukano_nie_znaleziono` / `nie_publikowany_z_mocy_prawa` / `wymaga_wniosku_o_informację_publiczną` | **none** (unknown ≠ negative) | lowers C | no PFU attached | „Uzupełnij: PFU (rozdz. zakres, warunki gruntowe). Bez niego nie ocenimy R02.1, R01.2.” |
| `NIECZYTELNY` | dokument nieczytelny | Document present but unusable: no text layer, OCR confidence < 0.8, pages missing | none | lowers C (like missing) | scanned PPU without OCR | „Dokument wymaga OCR lub pełnej wersji (brak stron 7–12)” |
| `DOKUMENT_NIE_WSPOMINA` | dokument nie wspomina | Document of the right type present, fully parsed, and the topic is expected there (`expected_topics[doc_type]`), but there is no mention | weak signal; **strong if the topic is mandatory by law** (e.g. waloryzacja in a PPU > 6 months → R08.1 red flag) | C unchanged | SWZ silent on geotechnics | „SWZ i PFU nie zawierają informacji o badaniach podłoża” |
| `BRAK_POTWIERDZENIA` | brak potwierdzenia | A claim, intent or plan exists ("decyzja zostanie uzyskana", "zamawiający wystąpi", "planowane…"), or a signal suggests an event, but no document confirms the outcome | signal per catalogue strength | C unchanged | Q&A: "zamawiający jest w trakcie uzyskiwania zgód" | „Zweryfikuj: czy zgody właścicieli uzyskano? Brak dokumentu potwierdzającego” |
| `POTWIERDZONO` | potwierdzono | An authoritative source confirms the fact or event (structured notice field, aneks, decyzja, protokół, KIO/NIK) | event recorded (S = 1 for the occurrence) | raises C | 5.4.3 = pkt 4, reason "kolizja" | - |
| `POTWIERDZONO_NIE_WYKONANO` | potwierdzono, że nie wykonano / nie wystąpiło | An authoritative source explicitly states the negative (5.1 = Nie; 5.3 = Tak with consistent dates; protocol "nie wykonano"; NIK „nie wyegzekwowano”; "Liczba zmian: 0") | event recorded as a negative | raises C | "Liczba zmian: 0" → no formal changes reported | - |
| `SPRZECZNOŚĆ` | sprzeczność | Two sources disagree and it is not a legitimate later change (check chronology and versions first) | escalate to expert | - | 5.3 = Tak but 5.2 is 120 d after 4.2 | „Sprzeczność: deklaracja terminowości vs daty (120 dni). Rozstrzygnij.” |

Decision procedure (deterministic, testable):

```python
def evidence_state(check, project, package, search_log, today):
    exp = expected_docs(check, project.phase, project.formula, project.regime)  # §6.2
    if not exp.is_due(today):
        return "JESZCZE_NIEWYMAGALNY"
    pos = find_evidence(check, package, polarity=+1)   # each hit: doc_id, page, quote, authority
    neg = find_evidence(check, package, polarity=-1)
    pos_auth = [h for h in pos if h.authoritative]
    neg_auth = [h for h in neg if h.authoritative]
    if pos_auth and neg_auth and not later_version_supersedes(pos_auth, neg_auth):
        return "SPRZECZNOŚĆ"
    if neg_auth:
        return "POTWIERDZONO_NIE_WYKONANO"
    if pos_auth:
        return "POTWIERDZONO"
    if pos or neg:                                     # non-authoritative claim, plan, intent
        return "BRAK_POTWIERDZENIA"
    docs = [d for d in package if d.type in exp.types]
    if not docs:
        return ("BRAK_W_PACZCE", search_log.reason(exp.types))
    if all(d.unreadable for d in docs):
        return "NIECZYTELNY"
    return ("DOKUMENT_NIE_WSPOMINA", {"mandatory": exp.mandatory_topic(check)})
```

**Strength of negative evidence**, how much an *absence* tells us:

| Absence of… | Given… | Strength | Reason |
|---|---|---|---|
| any change in the completion notice ("Liczba zmian: 0") | notice published | 0.9 | statutory form; still self-reported |
| a pkt 3/4 change notice | completion notice lists pkt 3/4 changes | - | compliance flag (`EV_LATE_NOTICE`-type), not a negative |
| a pkt 3/4 change notice | contract running, no completion notice yet | 0.5 | publication is mandatory, but compliance < 100% |
| an aneks on BIP | - | 0.2 | no general obligation to publish aneksy |
| a completion notice | > 60 d after planned end | 0 for performance; 0.6 for "zamawiający nie dopełnił art. 448 or the contract is still running" | not evidence of non-performance |
| a decision (DŚU / water-law) in the tender package | build formula, length ≥ 1 km | 0.4 | often not attached even if it exists |

### 6.2 Expected-documents matrix (seed)

| Document | Expected when | Public by law | Where | Due |
|---|---|---|---|---|
| Ogłoszenie o zamówieniu | always (Pzp ≥ threshold) | yes | BZP / TED | at start |
| SWZ + PFU/OPZ, projekt, STWiORB, przedmiar, PPU | always (PFU if ZiW; projekt+przedmiar if buduj) | yes, during the procedure | purchasing platform | at start |
| Pytania i odpowiedzi, modyfikacje SWZ | if questions were asked | yes | platform | before opening |
| Informacja o kwocie (art. 222 ust. 4) | always | yes | platform | before opening |
| Informacja z otwarcia ofert | always | yes | platform | at opening |
| Ogłoszenie o wyniku | always | yes | BZP / TED | after award |
| Orzeczenie KIO | if appealed | yes | KIO portal | +15 d from appeal |
| Umowa (signed) | always exists | **rarely published** | BIP rejestr umów | - |
| Ogłoszenie o zmianie umowy | if change under pkt 3/4 | yes | BZP / TED | after change |
| Aneks | if any change | no general obligation | BIP, uchwały | - |
| **Ogłoszenie o wykonaniu umowy** | after performance | yes | BZP | **≤ 30 d after performance** |
| DŚU | §1.7 thresholds | announcements yes | BIP of the wójt/burmistrz, ekoportal | before PnB / zgłoszenie |
| Pozwolenie / zgłoszenie wodnoprawne | §1.7 cases | partially | PGW Wody Polskie | before works |
| Badania geotechniczne | buduj: as an attachment; ZiW: contractor's deliverable | as attachment | platform | at start |
| WPF / uchwały budżetowe | JST beneficiary | yes | BIP | yearly |
| Funding agreement / project list | co-funded | lists yes | CST2021, KPO lists, IOI | - |
| NIK / RIO findings | only if audited | yes | nik.gov.pl, RIO | - |

### 6.3 Confidence model: three separate components + product

The brief demands a separate assessment of data quality, completeness and signal→event strength. Show **three bars plus an overall band**.

**Q, data quality** = authority × extraction × linking.

| Source authority tier | Value |
|---|---|
| A: structured official notice (BZP/TED field), KIO/NIK document, signed contract or aneks | 0.95 |
| B: zamawiający procedure documents (SWZ/PFU/PPU/Q&A/protokół/uchwała/WPF) | 0.85 |
| C: official communiqué or news on BIP, IOI/operator lists | 0.70 |
| D: press, third-party aggregators | 0.50 |

| Extraction method | Factor |
|---|---|
| Structured field | 1.00 |
| Regex on structured HTML | 0.95 |
| LLM extraction with **verified verbatim quote + page** | 0.85 |
| LLM without a verified quote | 0.50 (cannot be approved as source) |
| OCR text | × OCR confidence |

| Record linking | Factor |
|---|---|
| Identifier match (BZP no. `\d{4}/BZP \d{8}(/\d{2})?`, OCID `ocds-148610-<uuid>`, TED `\d{1,6}-\d{4}`, KPO `KPOD\.\d{2}\.\d{2}-IW\.\d{2}-\d{4}/\d{2}`, NIP with checksum 6-5-7-2-3-4-5-6-7 mod 11) | 1.00 |
| Fuzzy match (name + zamawiający + CPV + value + dates) | match score 0.5–0.9 |
| Expert-confirmed link | 1.00 |

**C, completeness** = Σ_{doc ∈ expected(check), state ∈ {present, readable}} importance(doc) / Σ_{doc ∈ expected(check)} importance(doc).
Example importances:

| Check | Document importances |
|---|---|
| Cost outcome | wynik 0.25, wykonanie 0.50, zmiany/aneksy 0.25 |
| Delay outcome | PPU/SWZ term 0.30, wykonanie 0.50, zmiany 0.20 |
| R02.1 signal | PFU/OPZ 0.40, geotech 0.40, Q&A 0.20 |

**S, strength of the signal→event link:**
- For a *confirmed event* from a structured field, S = 1 for occurrence.
- For **cause attribution**, use the explicitness of the reason text: S = 0.8 if 5.4.4 names the cause explicitly ("kolizja z siecią gazową"); 0.5 if inferred from a generic text ("okoliczności niezależne od stron"); 0.3 if inferred only from co-occurrence.
- For a *risk signal* in planning documents, S = the catalogue `strength` (expert prior), updated with approved cases:
  - `S_post = (a + k) / (a + b + n)`, with `a = 10×strength`, `b = 10×(1 − strength)`;
  - k = approved cases where the signal was followed by the event; n = approved cases with the signal;
  - show it as „siła sygnału 0,45 (na podstawie 12 zatwierdzonych przypadków)”.
- **Several signals for the same risk:** noisy-OR, `P = 1 − Π_i (1 − Q_i×S_i)`. Show the strongest signal first.

**Overall** = Q × C × S → band: **wysoka** ≥ 0.60; **średnia** 0.30–0.60; **niska** < 0.30.
- Never hide the components: a high Q × S with a low C reads as „sygnał mocny, ale paczka niepełna – uzupełnij …”.
- Expert decisions: approval sets `expert_status = approved` and freezes the values. Rejection keeps the record with `rejected` (needed for learning S). Edits are versioned (who, when, before/after).

### 6.4 Re-analysis when a new document arrives

For each check item affected by the new document's type:
1. recompute the state;
2. log transitions such as `BRAK_W_PACZCE → POTWIERDZONO`, `BRAK_POTWIERDZENIA → POTWIERDZONO_NIE_WYKONANO`, `POTWIERDZONO → SPRZECZNOŚĆ`;
3. list the facts, contradictions and risks that were **confirmed, changed or closed**, as required by the expert material's "Aktualizacja analizy".

**Monitoring mode** for ongoing contracts. Alert on:
- a new change notice for the contract's OCID;
- WPF changes;
- planned end + 30 d passed without a completion notice;
- a "dokończenie" tender by the same zamawiający.

---

## 7. Subsector classification (6 subsectors, main/secondary, works type, formula)

### 7.1 Rules

1. **Detect components** (C ∈ {WOD, KAN, OCZ, UZD, DESZ, INNE}) with quantities from the title, description (3.8 / funding description), PFU/OPZ scope and CPV (§7.2–7.3). CPV is **supporting evidence only**: 45231300-8 is shared by water and sewer pipelines and is the most frequent code in both.
2. **Estimate each component's value share:**
   - (a) part values or kosztorys/zestawienie, if available;
   - else (b) quantities × unit-cost table. The table lives in YAML and is calibrated by regressing BZP contract values on quantities extracted from 3.8 descriptions (km by network type, pumping stations, connections, RLM, m³/d), using the same deflator;
   - else (c) a title-salience heuristic: the first-named object in the title gets +0.3; an object introduced by „wraz z / z / oraz” is a candidate secondary.
3. **Main subsector** = argmax share.
   - If the top-2 shares differ by < 15 pp → set `zakresy_rownorzedne = true` (the expert material allows equal scopes) and send to the expert queue.
4. **Secondary subsectors** = other components with share ≥ 10%, **or** any separately named object (oczyszczalnia, SUW, zbiornik), regardless of share.
5. **Works type** per component and for the main component (§7.3):
   - `budowa/rozbudowa` (new capacity or extension);
   - `przebudowa/renowacja` (modernisation, replacement, rehabilitation, separation of combined sewers);
   - `mieszany` if the main component has both.
6. **Formula:**
   - `zaprojektuj_i_wybuduj` if `zaprojektuj|zaprojektowanie i (wykonanie|wybudowanie|budow)|projektuj i buduj` is in the title or description, or a PFU is present, or CPV 71320000-7 / 71322000-1 co-occur with 45* in a works contract;
   - else `buduj` if a projekt/przedmiar/STWiORB is present;
   - else `nieustalona`.
7. **Classification confidence** = agreement of independent cues (title, description, CPV, quantities). Below 0.6 → expert queue.

### 7.2 CPV codes (names verified from BZP notices)

| CPV | Polish name (as in BZP) | Component signal |
|---|---|---|
| 45231300-8 | Roboty budowlane w zakresie budowy wodociągów i rurociągów do odprowadzania ścieków | WOD **or** KAN (ambiguous) |
| 45231100-6 | Ogólne roboty budowlane związane z budową rurociągów | WOD/KAN (weak) |
| 45231110-9 | Roboty budowlane w zakresie kładzenia rurociągów | WOD/KAN (weak) |
| 45232150-8 | Roboty w zakresie rurociągów do przesyłu wody | WOD |
| 45232100-3 | Roboty pomocnicze w zakresie wodociągów | WOD |
| 45232151-5 | Roboty budowlane w zakresie węzłów do przepompowywania wody | WOD/UZD |
| 45232153-9 | Roboty budowlane w zakresie wież wodnych | UZD |
| 45232154-6 | Roboty budowlane w zakresie wysoko umieszczonych zbiorników wody pitnej | UZD |
| 44162500-8 | Rurociągi wody pitnej (supply) | WOD |
| 45232400-6 | Roboty budowlane w zakresie kanałów ściekowych | KAN |
| 45232410-9 | Roboty w zakresie kanalizacji ściekowej | KAN |
| 45232411-6 | Roboty budowlane w zakresie rurociągów wody ściekowej | KAN |
| 45232440-8 | Roboty budowlane w zakresie budowy rurociągów do odprowadzania ścieków | KAN |
| 45232423-3 | Roboty budowlane w zakresie przepompowni ścieków | KAN |
| 45232424-0 | Roboty budowlane w zakresie wylotów kanałów ściekowych | KAN/OCZ |
| 45255600-5 | Roboty w zakresie kładzenia rur w kanalizacji | KAN |
| 45232420-2 | Roboty w zakresie ścieków | KAN/OCZ (ambiguous) |
| 45232460-4 | Roboty sanitarne | weak |
| 45232421-9 | Roboty w zakresie oczyszczania ścieków | OCZ |
| 45232422-6 | Roboty w zakresie uzdatniania osadów | OCZ |
| 45252100-9 | Roboty budowlane w zakresie zakładów oczyszczania ścieków | OCZ |
| 45252127-4 | Roboty budowlane w zakresie oczyszczalni ścieków | OCZ |
| 45252200-0 | Wyposażenie oczyszczalni ścieków | OCZ |
| 45252130-8 | Wyposażenie zakładów odprowadzania ścieków | OCZ |
| 45252140-1 | Roboty budowlane w zakresie zakładów odwadniania osadów | OCZ |
| 42996000-4 | Maszyny do uzdatniania ścieków (supply) | OCZ |
| 45232430-5 | Roboty w zakresie uzdatniania wody | UZD |
| 45232431-2 | Przepompownie wody odpadowej | KAN (despite the name) |
| 45252120-5 | Roboty budowlane w zakresie zakładów uzdatniania wody | UZD |
| 45252126-7 | Roboty budowlane w zakresie zakładów uzdatniania wody pitnej | UZD |
| 45252210-3 | Roboty budowlane w zakresie zakładów oczyszczania wody | UZD |
| 45262220-9 | Wiercenie studni wodnych | UZD |
| 45255110-3 | Roboty budowlane w zakresie studni | UZD (weak) |
| 42912300-5 | Maszyny i aparatura do filtrowania lub oczyszczania wody (supply) | UZD |
| 45232130-2 | Roboty budowlane w zakresie rurociągów do odprowadzania wody burzowej | DESZ |
| 45232450-1 | Roboty budowlane w zakresie budowy upustów | DESZ |
| 45232451-8 | Roboty odwadniające i nawierzchniowe | DESZ |
| 45232452-5 | Roboty odwadniające | DESZ (also used for roads, needs text) |
| 45232453-2 | Roboty budowlane w zakresie upustów | DESZ |
| 45232454-9 | Roboty budowlane w zakresie zbiorników wód deszczowych | DESZ |
| 45247270-3 | Budowa zbiorników | DESZ/UZD (ambiguous) |
| 45111240-2 | Roboty w zakresie odwadniania gruntu | **not a subsector**, construction dewatering; tag R02.1 |
| 45330000-9 / 45332000-3 / 45332300-6 | Roboty instalacyjne wodno-kanalizacyjne / wodne i kanalizacyjne / kanalizacyjne | building installations, weak; often in house connections |
| 71320000-7, 71322000-1, 71322200-3 | Usługi projektowania (inż. lądowa i wodna, rurociągi) | **formula ZiW** cue when paired with 45* |
| 71247000-1, 71248000-8, 71520000-9 | Nadzór nad robotami / projektem / budowlany | supervision contracts, exclude from the works reference class |
| 90481000-2, 65100000-4 | Eksploatacja oczyszczalni / usługi przesyłu wody | operation, exclude (not investment) |

### 7.3 Keyword lexicon (regex stems, case-insensitive, on title + description)

```yaml
components:
  WOD:  ['wodociąg', 'sie[ćc]i? wodociągow', 'magistral\w* wod', 'przyłącz\w* wodociągow', 'hydrant', 'rurociąg\w* (wody|wodociągow)']
  KAN:  ['kanalizac\w* sanitarn', 'sie[ćc]i? kanalizac', 'kanał\w* sanitarn', 'kolektor\w* sanitarn', 'tłoczn', 'rurociąg\w* tłoczn',
         'przepompowni\w* ścieków', 'pompowni\w* ścieków', 'przykanalik', 'sięgacz', 'kanalizac\w* (ciśnieniow|podciśnieniow|grawitacyjn)',
         'tranzyt\w* (przesyłow|kanaliz)']
  OCZ:  ['oczyszczalni\w* ścieków', 'oczyszczani\w* ścieków', '\bSBR\b', 'osad\w* czynn', 'reaktor\w* biologiczn', '\bRLM\b', 'osadnik', 'stacj\w* zlewn',
         'przydomow\w* oczyszczal']        # przydomowe: see open question Q1
  UZD:  ['stacj\w* uzdatniania', '\bSUW\b', 'ujęci\w* wody', 'studni\w* (głębinow|wierconej)', 'zbiornik\w* (wody czystej|retencyjn\w* wody pitnej)',
         'hydroforni', 'pompowni\w* wody', 'odżelazian', 'odmanganian', 'wież\w* ciśnień']
  DESZ: ['kanalizac\w* deszczow', 'wód opadowych', 'odwodnieni\w* (drogi|ulicy|terenu)', 'zbiornik\w* retencyjn', 'retencj', 'separator',
         'kolektor\w* deszczow', 'ogólnospławn', 'rozdział\w* kanalizacji', 'studni\w* chłonn']
  INNE: ['telemetri', 'SCADA', 'stacj\w* zlewn', 'punkt\w* zlewn']
works_type:
  budowa_rozbudowa:     ['\bbudow', 'rozbudow', 'wykonani\w* (sieci|kanalizacji|wodociągu)', 'dobudow', 'nowe?j? (sieci|odcink)']
  przebudowa_renowacja: ['przebudow', 'moderniz', 'remont', 'renowac', 'wymian', 'rekonstrukc', 'relining', 'bezwykopow\w* renowac',
                         'rozdział\w* kanalizacji', 'zwiększeni\w* (przepustowości|wydajności)']   # note: 'zwiększenie przepustowości' of a plant = rozbudowa if capacity grows
formula:
  zaprojektuj_i_wybuduj: ['zaprojektuj', 'projektuj i (wy)?buduj', 'zaprojektowani\w* i (wykonani|wybudowani|budow)', 'program\w* funkcjonalno']
quantities:
  length:      '(\d+(?:[.,]\d+)?)\s*(km|mb|m)\b(?!\s*[²³23])'
  diameter:    '\bDN\s?(\d{2,4})\b|\bø\s?(\d{2,4})'
  connections: '(\d+)\s*(?:szt\.?\s*)?(?:przyłącz|odgałęzie|sięgacz|przykanalik)'
  pumps:       '(\d+)\s*(?:szt\.?\s*)?(?:przepompowni|pompowni|tłoczni)'
  pe:          '(\d[\d\s]*)\s*RLM'
  flow_day:    '(\d[\d\s,.]*)\s*m3?\s*/\s*d(ob)?'
```

Notes:
- Prawo budowlane treats *rozbudowa* as a form of *budowa* (art. 3 pkt 6), distinct from *przebudowa* (art. 3 pkt 7a) and *remont* (art. 3 pkt 8). Our binary feature follows the brief: "budowa/rozbudowa" vs "przebudowa/renowacja".
- **Lengths:** sum lengths by component context. Use the sentence window: "sieci wodociągowej o długości 22,616 km" → WOD 22.616 km. Convert m/mb → km. Ignore lengths preceded by "w odległości".

### 7.4 Worked classification of the 22 dataset projects

(Main / secondary, works type, formula. ⚑ = equal-scope or ambiguous → expert queue.)

| ID | Title (short) | Main subsector | Secondary | Works type | Formula | Notes / signals |
|---|---|---|---|---|---|---|
| RM-2026-001 | Rurociąg tłoczny kan. san. Godzikowice–Jaczkowice | Kanalizacja sanitarna | - | budowa | ? | tłoczny → R14.1 tag |
| RM-2026-002 | Kanalizacja Modlikowice (2,38 km + pompownia) | Kanalizacja sanitarna | - | budowa | ? | **R18**: "wpięta do realizowanej obecnie oczyszczalni"; KPO → R06.1 |
| RM-2026-003 | Oczyszczalnia Steklin, ZiW | Oczyszczalnia ścieków | - | budowa | ZiW | ZiW → R06.2; R04.1 if ≥ 400 RLM |
| RM-2026-004 | Modernizacja SUW Czernikowo | Uzdatnianie i zaopatrzenie w wodę | - | przebudowa | ? | R02.2, R10.1 |
| RM-2026-005 | Kanalizacja Zławieś + modernizacja SUW Pędzewo | Kanalizacja sanitarna | Uzdatnianie | mieszany (KAN budowa; UZD przebudowa) | ? | ⚑ shares unknown; KPO |
| RM-2026-006 | Przebudowa (modernizacja) OŚ Gościeradów | Oczyszczalnia ścieków | - | przebudowa | ? | PROW; R02.2, R10.1 |
| RM-2026-007 | Rozbudowa sieci wodociągowej Kamionka | Sieć wodociągowa | - | budowa (rozbudowa) | ? | KPO |
| RM-2026-008 | Kanalizacja Biecz, cz. 1 (projekt 11,871 km) | Kanalizacja sanitarna | - | budowa | ? | record = part 1; KPO; BZP 2026 → strong R06.1 |
| RM-2026-009 | Sieć wodociągowa Zakrzew, cz. 2 | Sieć wodociągowa | - | budowa | ? | record = part 2; KPO |
| RM-2026-010 | Kanalizacja Zmysłówka, Grodzisko Dolne | Kanalizacja sanitarna | - | budowa | ? | KPO |
| RM-2026-011 | Sieć wodociągowa Czerteż, Zabłotce, Sanoczek | Sieć wodociągowa | - | budowa | ? | mountainous region (podkarpackie) |
| RM-2026-012 | Tranzyt przesyłowy kan. san. Smętowo Chm.–Kosy | Kanalizacja sanitarna | - | budowa | ? | transit; R18 (connection to existing system); R14.1 |
| RM-2026-013 | Kanalizacja Kaniów (Bestwina) | Kanalizacja sanitarna | - | budowa | ? | PROW |
| RM-2026-014 | Kanalizacja ul. Słoneczna, Siemoń | Kanalizacja sanitarna | - | budowa | ? | **R03.2**: "tereny zielone stanowiące własność prywatną"; DW 913 catchment → R03.3/R17; KPO |
| RM-2026-015 | Przebudowa wodociągu, kan. san. i deszczowej + przyłącza + modernizacja OŚ Janów, ZiW | ⚑ Kanalizacja sanitarna (provisional) | Sieć wodociągowa, Kanalizacja deszczowa, Oczyszczalnia | przebudowa | ZiW | ⚑ four components; needs cost split |
| RM-2026-016 | Wodociąg 22,616 km + kanalizacja 18,09 km, Miłakowo | ⚑ Kanalizacja sanitarna (by value) / Sieć wodociągowa (by length) | the other | budowa | ? | ⚑ length favours WOD, unit cost favours KAN → mark equal |
| RM-2026-017 | Kanalizacja + przyłącza + przepompownie Tanibórz | Kanalizacja sanitarna | - | budowa | ? | KPO; przyłącza in scope (good for R15.1) |
| RM-2026-018 | Kanalizacja Baszków – etap II | Kanalizacja sanitarna | - | budowa | ? | "etap II" → R18; KPO |
| RM-2026-019 | Kanalizacja deszczowa w ciągu DW 444, Sulmierzyce (WZDW) | Kanalizacja deszczowa i retencja | - | budowa | ? | road-authority beneficiary (type "inne"); R17 |
| RM-2026-020 | Kanalizacja + oczyszczalnia Konarzewo | ⚑ Oczyszczalnia ścieków (description lists OŚ first; 17 connections → short network) | Kanalizacja sanitarna | mieszany (OŚ przebudowa + budowa; KAN budowa) | ? | ⚑ title says kanalizacja first; KPO |
| RM-2026-021 | Rozdział kanalizacji ul. 700-lecia, Nowogard (odporność hydrologiczna) | ⚑ Kanalizacja deszczowa i retencja | Kanalizacja sanitarna | przebudowa | ? | ⚑ separating combined sewers, see Q2 |
| RM-2026-022 | Sieci wodociągowe i kanalizacja, Wolin | ⚑ (needs quantities) | - | budowa | ? | ⚑ |

Dataset observations useful for the demo:
- The sheet header says 23 rows but contains 22 projects.
- Two records are parts (RM-008 "część 1", RM-009 "część 2"). Each part has a separate contract (expert rule "postępowanie → części → umowy").
- 10 records are identified only by a KPO number, so they need fuzzy linking to BZP.
- Two beneficiaries appear twice: Czernikowo (003, 004) and Nowogard (020, 021).
- KPO "Wartość przedsięwzięcia" is a project value, not a contract value. Implied grants are about 76–81% of project value.

---

## 8. Limitations and questions for MFiPR mentors

- **Q1.** Przydomowe oczyszczalnie ścieków: "Oczyszczalnia ścieków" or "Inne obiekty wod-kan"? (Proposal: Oczyszczalnia + tag `indywidualne`.)
- **Q2.** Separation of combined sewers (rozdział kanalizacji ogólnospławnej): main subsector deszczowa or sanitarna? (Proposal: by the newly built pipe; if both, mark equal.)
- **Q3.** Is "dominujący zakres" meant by **value** (our proposal) or by **length**?
- **Q4.** Acceptance of the new level-1 candidates R16–R18, or keep them as R07 sub-codes.
- **Q5.** Treatment of VAT in KPO/CST project values: gross, or eligible net?
- **Data limitations:**
  - BZP self-declared flags (5.3/5.6);
  - 4.2 may hold amended dates;
  - kary umowne are invisible in BZP;
  - lump-sum contracts mask scope growth;
  - our BZP sample is capped per query window;
  - cause attribution from 5.4.4 is keyword-based (association, not causation).

---

## Appendix A. Sources

Legal:
- Pzp, consolidated text Dz.U. 2026 poz. 793: <https://api.sejm.gov.pl/eli/acts/DU/2026/793/text/T/D20260793L.pdf>
- Rozporządzenie MRPiT z 23.12.2020 w sprawie ogłoszeń zamieszczanych w BZP, Dz.U. 2020 poz. 2439: <https://api.sejm.gov.pl/eli/acts/DU/2020/2439/text.html>
- Amendment raising the national threshold to 170 000 zł (Dz.U. 2025 poz. 1173): <https://eli.gov.pl/eli/DU/2025/1173>; overview: <https://www.prawo.pl/biznes/pzp-170000-zl-prog-przetargi,535939.html>
- EU thresholds 2026–2027 (5 404 000 EUR = 23 291 240 zł): M.P. 2025 poz. 1288 <https://eli.gov.pl/eli/MP/2025/1288/ogl/pol/pdf>
- Rozporządzenie RM w sprawie przedsięwzięć mogących znacząco oddziaływać na środowisko, Dz.U. 2019 poz. 1839: <https://api.sejm.gov.pl/eli/acts/DU/2019/1839/text.html>
- Prawo budowlane, Dz.U. 2024 poz. 725: <https://api.sejm.gov.pl/eli/acts/DU/2024/725/text.html>
- Prawo wodne, Dz.U. 2024 poz. 1087: <https://api.sejm.gov.pl/eli/acts/DU/2024/1087/text.html>
- eForms `modification-justification` codelist: <https://docs.ted.europa.eu/eforms/1.12/reference/code-lists/modification-justification.html>
- Art. 448 Pzp (text): <https://prawnik.cc/laws/prawo-zamowien-publicznych/art-448-ogloszenie-zamawiajacego-o>; UZP Q&A on completion notices: <https://www.gov.pl/web/uzp/pytania-i-odpowiedzi-dotyczace-ogloszenia-o-wykonaniu-umowy>

KPO:
- Interpellation 16654 and the MFiPR answer (15.05.2026): <https://api.sejm.gov.pl/sejm/term10/interpellations/16654/body>, <https://api.sejm.gov.pl/sejm/term10/interpellations/attachment/ATTDU7JFM/i16654-o1.pdf>
- MRiRW extension to 15.06.2026: <https://wartowiedziec.pl/rozwoj-i-fundusze/80352-a-jednak-rzad-przedluza-rozliczenia-inwestycji-wod-kan-na-wsiach-w-ramach-kpo>

Statistics and studies:
- NIK P/20/046: <https://www.nik.gov.pl/plik/id,25776,vp,28549.pdf>
- EC SWD(2020) 43: <https://ec.europa.eu/regional_policy/sources/evaluation/swd_ex_post_env_2000_2013_en.pdf>
- Budzier, Flyvbjerg et al. 2024 (Table 5, Oxford Projects Database): <https://arxiv.org/abs/2406.01714>
- HM Treasury Green Book optimism bias: <https://www.gov.uk/government/publications/green-book-supplementary-guidance-optimism-bias>
- Rybka, Bondar-Nowakowska, Połoński 2016 (ACE 62/1): <https://czasopisma.pan.pl/Content/84083>
- Rybka, Bondar-Nowakowska 2013 (ACE LIX/4, DOI 10.2478/ace-2013-0027): <https://czasopisma.pan.pl/Content/83907>
- ResearchGate 309271479 (unverified metadata): <https://www.researchgate.net/publication/309271479_Cost_Risk_in_Water_and_Sewerage_Systems_Construction_Projects>
- GUS construction price indices: <https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-produkcji-budowlano-montazowej-w-listopadzie-2022-roku,15,48.html>, <https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-produkcji-budowlano-montazowej-w-grudniu-2023-roku,15,61.html>
- Coface insolvency (press): <https://bank.pl/?p=524271>

Data:
- BZP mirror (hackathon): <https://bzp.cytr.us>, `/mo-board/api/v1/notice?NoticeType=…&CpvCode=…&PublicationDateFrom=…&PublicationDateTo=…&PageSize=…`. `NoticeType` values used: `ContractPerformingNotice` (wykonanie umowy), `AgreementUpdateNotice` (zmiana umowy), `TenderResultNotice` (wynik). The `PageNumber` parameter appeared to be ignored, so we used date windows for paging.

## Appendix B. Reproducing §3.1 (sketch for the analytics module)

1. Pull `ContractPerformingNotice` by CPV × quarter. Split a window whenever it returns the cap.
2. Strip `htmlBody` to text. Field regexes (label-based, robust to whitespace):
   - `r'4\.4\.\) Wartość umowy[^:]*:\s*([\d ,.]+)'`
   - `r'5\.2\.\) Termin wykonania umowy:\s*(\d{4}-\d{2}-\d{2})'`
   - `r'5\.3\.\)[^:]*:\s*(Tak|Nie)'`
   - `r'5\.4\.1\.\) Liczba zmian:\s*(\d+)'`
   - per change `r'5\.4\.3\.\) Podstawa prawna zmiany:\s*\n?([^\n]+)'`, `r'5\.4\.4\.\) Przyczyny dokonania zmian:\s*\n?([^\n]+)'`
   - `r'5\.5\.\)[^:]*:\s*([\d ,.]+)'`
   - `r'5\.6\.\)[^:]*:\s*(Tak|Nie)'`
   - planned end from 4.2 (`do RRRR-MM-DD`, or `N dni/miesięcy` added to 4.1).
3. Numbers use a comma decimal separator. Strip spaces, then convert `,` → `.`.
4. Link to `TenderResultNotice` via 4.5 (`\d{4}/BZP \d+`) for the estimate (4.3, net), offers (6.1) and prices (6.2–6.4, gross).
5. Compute Tables A–D. Store the result as `sector_prior.wodkan.json` with fields (group, n, p_late, p_change, p_pos, mu, sigma, quantiles, period, source_query, computed_at), so the expert can see and override it.
