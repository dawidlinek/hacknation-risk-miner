# Analytics engine: implementation plan

Written 2026-11-21 19:25 for the analytics session (workstream **A** in `docs/flow1_build_plan.md`).
Every number marked **live** was queried from `riskminer-db` tonight; every query is in this file so it can
be re-run. Code, comments and this doc are in English; every user-facing sentence (templates, labels, flags)
is Polish (CLAUDE.md invariant 6).

Contents: §0 summary; §1 shared conventions; §2 module layout; §3 computations 1–11; §4 new catalogue
files; §5 endpoints; §6 golden tests; §7 work plan; §8 blockers and decisions.

---

## 0. Summary

### 0.1 Demo reference class: live vs design

Class: kanalizacja sanitarna (SAN), 5–10 mln zł gross, zaprojektuj i wybuduj (design-build).

| metric | design (`design/README.md` §10, research CSV on the offline copy) | **live DB now** | UI should show |
|---|---|---|---|
| funnel | 11 184 → 4 268 → 371 → **84** | 11 222 → 4 287 → 373 → **82** | live |
| late (5.3 = Nie) | 64% | **63.4%** (52 of 82; Wilson 90%: 54–72%) | live |
| ≥1 change | 77% | **76.8%** | live |
| delay P50/P80/P90, all contracts, on-time = 0 | +69 / +148 / +184 d (n = 79) | **+66 / +144 / +177 d** (n = 77, `time_ok`) | live, with `time_ok` |
| cost deviation P80/P90 | +4.1 / +11.8% (n = 83) | **+4.1 / +10.7%** (n = 81, `cost_ok`) | live |
| paid above value | 31% | **30.9%** | live |
| planned duration median | 548 d | **546.5 d = 18.0 mies.** (P25 452.5 d) | live |
| P(on time) for a 14-month plan | 36% | **36.4%** (ratio model, unweighted; 34.4% with the plan-length kernel) | live |
| 14-month plan, actual months P10/P50/P80/P90 | 12.9 / 16.3 / not shown / 20 | **13.5 / 15.7 / 18.3 / 20.7** (SQL; numpy 18.4 / 20.9) | live |
| unit cost SAN, mln zł/km P25/P50/P75 | 0.54 / 0.89 / 1.48, n = 1 734 | **0.51 / 0.86 / 1.44, n = 1 844** | live |
| 7 mln zł / 6 km = 1.17 mln zł/km | 64th percentile | **65th percentile** | live |
| P(≥2 offers), SAN 5–10 mln, tenders 2025+ | 90% (demo curve) | **95.7%** (n = 162), median 6 offers | live |

**Why they differ (reconciled contract by contract):**

1. **Classifier input.** `procedure` is classified from the CN title and CN short description (CP description as
   fallback); the research CSV classified each CP from the CP title and CP section 3.8. Four contracts that the
   research tagged design-build carry the phrase only in the CP description (2024/BZP 00301631,
   2025/BZP 00273146, 2026/BZP 00323791, 2026/BZP 00413362); one contract is design-build only in the DB
   (2024/BZP 00614498).
2. **Live delta.** One contract was published after the copy cut-off of 2026-11-12 (2026/BZP 00552421). Nationally
   70 core contracts come from the live API.
3. **Definitions agree.** For the 80 contracts in both sets the late flag and the delay in days are identical.
   The delay P50 gap (66 vs 69) is membership only; without the `time_ok` filter the DB gives 59, so the engine
   **must** apply `time_ok` (§1.1).
4. **The "~11.8k core"** count is a different filter: `relevance = 'core'` over every scope (maintenance, delivery,
   design-only, services) and both channels, including the roads demo slice (`sector = 'drogi'`, CPV 45233*, kept
   for W9). The reference base is `sector = 'wod-kan' AND relevance IN ('core','cpv_only') AND scope_kind = 'works'`
   = **11 222** (= 11 184 + 70 live − 32 classifier differences).

**Recommendation:** every screen renders engine output with its `n`; nothing is copied from the mockups. The
pitch deck freezes numbers from `GET /api/analytics/headline` at 07:00 and says "stan na 22.11.2026". The
national story is unchanged: 30.3% late, 41.6% with changes, median delay when late 58 d (P90 190), cost P90
+6.9%, 21.6% paid above value, 586 mln zł overpaid, 265 tys. dni of delay. One mockup case is wrong: Janów
(RM-2026-015) is shown as +150 d, but the source declares it **on time** (computed +28 d, a start-date
convention); show 0 d with a discrepancy note.

### 0.2 Solid vs risky

| solid (reproduced live tonight, golden ranges below) | risky |
|---|---|
| base population and quality flags; national headline (§3.10) | Monte Carlo **mitigation effects**: with keyword cause codes, R02 appears in 5 of 77 class contracts, so toggles move P80 by 0–10 days, far less than the mockup's demo values (§3.5.8) |
| reference class + funnel + widening (§3.1) | per-risk expected cost for 1.5: 0.1–0.7% of value per risk from data, versus 1–4% in the mockup (§3.7); multipliers and premiums are expert assumptions |
| time forecast (ratio model), shares with Wilson, bootstrap CIs (§3.2) | similarity text part without embeddings (BM25 on stems only, weight 0.13) (§3.4) |
| unit cost and percentile (§3.3), coverage 44% | buyer → gmina mapping by name (97% of buyers resolve, precision checked on 22 pilots only) (§3.9) |
| tender outcomes by year (§3.6), competition curve | funding deadlines: KPO date is sourced; FEnIKS end date must be confirmed per call (§4.2) |
| backtest W3 reproduced: 85.0 / 87.7 / 79.5% inside P10–P90 (§3.8) | NL→SQL guard is new code; must be tested before the demo (§3.10) |
| radar counts and woj aggregates match the mockup (§3.9) | hurdle model (03 §4) is optional tonight (§3.2.5) |

### 0.3 Blockers

1. **numpy is not a dependency** (`backend/pyproject.toml`). Add `numpy>=2.1` (BSD-3, permissive). Nothing else
   is needed: no pandas, no scipy, no scikit-learn in the API process.
2. `rc_contract` (materialized view owned by `ingest/derive.py`) has no quality flags, title, length, offers or
   TERYT. The analytics session adds its own MV `an_contract` on top (§1.1) plus two small tables; `derive.py`
   only needs one extra line (refresh `an_contract` after `rc_contract`), or the analytics CLI refreshes it.
3. LLM cause codes (`cause_codes_ai`) do not exist yet; 76.6% of core change rows have keyword codes, with weak
   precision for R04/R08/R06/R11 (§3.5.7). Simulation and allocation read whichever exists.
4. Three new catalogue files hold **expert assumptions** (`mitigations.yaml`, `funding_programmes.yaml`,
   `allocation.yaml`, §4). Someone has to own their values and the "założenie eksperta" label.

---

## 1. Shared conventions

### 1.1 Base population `an_contract` (materialized view, analytics migration)

One row per completed core water/sewage works contract with outcome fields, quality flags and everything the
engine needs, so the API can hold the whole case base in memory (11 222 rows, about 3 MB as numpy arrays).

```sql
CREATE TABLE contract_metric (              -- CALC facts derived from notice text (lengths), one per performance
  performance_id bigint PRIMARY KEY REFERENCES contract_performance(id) ON DELETE CASCADE,
  length_km double precision, conn_km double precision, used_total boolean, n_mentions int,
  method varchar(20) NOT NULL DEFAULT 'regex_v1', origin varchar(8) NOT NULL DEFAULT 'CALC',
  review_status varchar(10) NOT NULL DEFAULT 'auto', source_id bigint REFERENCES source(id),
  created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE an_buyer_teryt (               -- §3.9; CALC, ambiguous rows -> review_item
  buyer_nip varchar(10) PRIMARY KEY, terc7 varchar(7), woj varchar(2), pow varchar(4),
  method varchar(10) NOT NULL, confidence double precision NOT NULL,
  origin varchar(8) NOT NULL DEFAULT 'CALC', review_status varchar(10) NOT NULL DEFAULT 'auto');

CREATE MATERIALIZED VIEW an_contract AS
SELECT r.performance_id, r.contract_id, r.procedure_id, r.ocid,
       r.subsector_main, r.subsectors, r.work_type, r.design_build, r.eu_funded,
       r.province, substr(r.province, 3, 2) AS woj,
       p.title, p.buyer_nip, p.buyer_name, p.city AS buyer_city, p.first_published_on,
       left(n.extracted->'data'->>'description', 1500) AS cp_description,
       n.bzp_number AS cp_bzp_number, n.url AS cp_url, n.source_id AS cp_source_id,
       n.published_at::date AS cp_published_on,
       r.signed_on, r.contract_year, r.completed_on, r.completion_year,
       r.value_gross, r.value_bucket, r.paid_gross, r.planned_days, r.actual_days,
       r.late, r.delay_days, r.cost_dev_pct, r.changes_count, r.legal_bases, r.cause_codes,
       r.properly_performed,
       q.time_ok, q.cost_ok,
       CASE WHEN q.time_ok AND r.on_time_declared THEN least(r.actual_days / r.planned_days, 1.0)
            WHEN q.time_ok AND r.late AND r.delay_days > 0 THEN 1.0 + r.delay_days / r.planned_days
       END AS ratio_rec,                        -- reconciled actual/planned (§3.2)
       cm.length_km, cm.conn_km,
       l.n_offers, l.estimated_value_amount AS lot_estimate_net,
       bt.terc7, bt.pow, bt.method AS terc_method
FROM rc_contract r
JOIN contract_performance pf ON pf.id = r.performance_id
JOIN notice n ON n.id = pf.notice_id
JOIN procedure p ON p.id = r.procedure_id
LEFT JOIN contract c ON c.id = r.contract_id
LEFT JOIN lot l ON l.id = c.lot_id
LEFT JOIN contract_metric cm ON cm.performance_id = r.performance_id
LEFT JOIN an_buyer_teryt bt ON bt.buyer_nip = p.buyer_nip
CROSS JOIN LATERAL (SELECT
    (r.completed_on IS NOT NULL AND r.completed_on <= n.published_at::date AND r.actual_days >= 0
     AND r.planned_days > 0 AND r.planned_days <= 1826 AND r.actual_days <= 1826) AS time_ok,
    (r.paid_gross > 0 AND r.value_gross > 0
     AND r.paid_gross / r.value_gross BETWEEN 0.5 AND 2.0) AS cost_ok) q
WHERE r.sector = 'wod-kan' AND r.relevance IN ('core','cpv_only') AND r.scope_kind = 'works';
CREATE UNIQUE INDEX ix_an_contract_perf ON an_contract (performance_id);
```

* `time_ok` / `cost_ok` port `research/bzp_corpus/04_reference_stats.py` (completion after publication, negative
  or > 5 y durations; paid 0, ratio outside 0.5–2, which also removes the ×10ⁿ scale errors). Live: 10 836 of
  11 222 rows are `time_ok` (96.6%), 11 112 are `cost_ok` (99.0%). Without `time_ok` the class contains rows
  completed in 2027.
* Baselines stay as in the research tables: planned end from CP 4.2, cost against CP 4.4, so cost deviation is a
  **lower bound** (05 §5.1). Say so in the limitations list.
* `cause_codes` today = keyword codes; when the LLM session adds `contract_change.cause_codes_ai`, change the
  `cc` CTE in `rc_contract` (or add a column here) to `coalesce(nullif(ai approved/proposed, '{}'), kw)`.
* Value buckets are the DB's: `<0.5m, 0.5-1m, 1-2m, 2-5m, 5-10m, >10m` (research used 1–2.5 / 2.5–5; only the
  backtest is affected, marginally).
* Refresh order: `rc_contract` → `contract_metric` fill → `an_buyer_teryt` fill → `an_contract` → monitoring MVs.
  Store `an_meta(refreshed_at, n_rows, notices_max_published_at)`; the API reloads its in-memory copy when
  `refreshed_at` changes (checked at most once per minute).

### 1.2 The number envelope (origin, n, source)

Every number the API returns is a `Stat`; every analysis output row is an `analysis_item` whose `body` holds
`Stat`s. Pydantic model in `riskminer/analytics/base.py`:

```json
{
  "value": 0.364, "unit": "share|days|months|pct|pln|pln_per_km|count",
  "ci90": [0.27, 0.46],
  "origin": "CALC",                      // SOURCE | CALC | AI (invariant 1)
  "review_status": "auto",               // AI items start "proposed"
  "n": 77, "n_eff": 77.0, "n_unknown": 2,
  "tier": "high",                        // high | medium | low | insufficient (§1.3)
  "level": "subsector+value+formula",    // which funnel level fed it (§3.1)
  "method": "empirical_ratio|wilson|bootstrap|hurdle_shrinkage|monte_carlo|bm25",
  "definition_pl": "opóźnienie = data wykonania (5.2) − planowany koniec (4.2); w terminie = 0",
  "period": ["2021-01-13", "2026-11-21"],
  "assumptions": [{"code": "M-GEO", "catalogue": "mitigations", "version": 1, "status": "proposed"}],
  "source": {"kind": "bzp_notices", "notice_types": ["ContractPerformingNotice"],
             "field_codes": ["4.2", "5.2", "5.3"], "case_ids": [123, 456],
             "data_version": "an_contract@2026-11-21T19:00:00Z/11222"}
}
```

Rules:
* `origin = CALC` for everything computed from the case base; `SOURCE` for a single case's own fields (shown with
  its BZP number and field code); `AI` only for LLM output (flags from PFU/PPU), always `proposed` until reviewed.
* `case_ids` are `performance_id`s. The evidence path is `contract_performance.notice_id → notice.url /
  source_id → source (url, retrieved_at, sha256)`, plus the existing `evidence` rows (`structured_field`).
  For lists over 200 cases store the ids in `analysis.reference_class` and reference them by key.
* Expert assumptions (mitigation multipliers, premiums, funding dates) are never `SOURCE`. They travel in
  `assumptions` with their catalogue status and are labelled "założenie eksperta" in the UI.
* Templates use frequencies: "w 52 z 82 podobnych umów (63%; przedział 90%: 54–72%)" (03 §4.4). At most two
  significant digits on forecasts.

### 1.3 Tiers by sample size (config `analytics:`)

```yaml
analytics:
  min_n_share: 30        # shares and medians with CI
  min_n_tail: 50         # P80/P90 bands
  insufficient_n: 10     # below: no class percentiles
  bootstrap_b: 1000
  mc_draws: 20000
  kernel_sigma_ln: 0.5   # plan-length kernel (§3.2)
  prior_m: 10            # pseudo-cases for shrinkage (§3.2.5)
  as_of: null            # fixed "today" for radar/headline on demo day, e.g. 2026-11-22
```

| n_eff | tier | shows | label (PL) |
|---|---|---|---|
| ≥ 50 | high | shares, P10/P50/P80/P90, bootstrap whiskers | „Pewność: wysoka (n = …)” |
| 30–49 | medium | shares, P50, P80 with whiskers; P90 hidden (or from the hurdle model) | „Pewność: średnia (n = …)” |
| 10–29 | low | shares with Wilson interval, P50 only; widen first (§3.1) | „Pewność: niska – mała grupa porównawcza” |
| < 10 | insufficient | each case as a row; parent class as „tło sektorowe” | „Za mało danych (n = …)” |

The design rule "n < 10 → 'za mało danych' instead of a range" (`design/README.md` §6.2) is the last row.

---

## 2. Module layout

```
backend/riskminer/parsing/lengths.py        # port of 07_wow_features.lengths(); pure, no DB
backend/riskminer/analytics/
  __init__.py
  base.py           # Stat envelope, tiers, config access, data_version, CaseBase (in-memory numpy copy of an_contract)
  stats.py          # weighted quantiles, Kish n_eff, Wilson, bootstrap, Beta/Normal shrinkage
  refclass.py       # funnel + progressive widening                                  (§3.1)
  forecast.py       # time ratio model, cost, shares, programme deadline              (§3.2)
  unit_cost.py      # PLN/km, percentile, GUS indexation                             (§3.3)
  price_index.py    # loader for data/ref/price_index_construction.csv
  text_index.py     # in-memory BM25 over folded stems, built at startup             (§3.4)
  similarity.py     # features, s_i, contributions, explanation templates           (§3.4)
  simulate.py       # Monte Carlo, mitigations, what-ifs, tornado                  (§3.5)
  competition.py    # tender outcomes, competition curve                           (§3.6)
  allocation.py     # expected cost per risk, balance                              (§3.7)
  backtest.py       # W3                                                           (§3.8)
  teryt.py          # buyer -> gmina mapping (fills an_buyer_teryt)                (§3.9)
  monitoring.py     # area aggregates (reads MVs), radar                          (§3.9)
  headline.py       # Pulpit numbers                                               (§3.10)
  flags.py          # red-flag predicates                                          (§3.11)
  templates_pl.py   # every Polish sentence (summary, why, limits, flags)
  catalogue.py      # reads mitigations/funding/allocation/similarity/red_flags from catalogue_entry, YAML fallback
  sql/              # an_contract.sql, mv_monitor_area.sql, mv_radar.sql, ask_views.sql (used by the migration)
backend/riskminer/api/routers/analyses.py   # POST/GET /analyses, /simulate, /allocation (writes analysis + analysis_item + audit_log)
backend/riskminer/api/routers/analytics.py  # headline, tenders, unit-cost, backtest, monitoring, radar
backend/riskminer/api/routers/ask.py        # Zapytaj pamięć executor (read-only role)
backend/alembic/versions/xxxx_analytics.py  # tables + MVs + ask views + role
cli: riskminer analytics refresh | backtest | teryt
```

Boundaries (invariant 8): analytics reads the DB and returns objects; only `api/routers/analyses.py` writes
(`analysis`, `analysis_item`, `audit_log`, `review_item` for proposed AI flags). The catalogue loader
(`ingest/catalogue.py`) gets three more entries in its generic `(fname, table)` loop for the new YAML files.

Performance pattern: `CaseBase` loads `an_contract` once (about 1 s) into numpy arrays keyed by column; all
filters are boolean masks. Every computation in §3.1–3.5 then runs in 1–50 ms. Only the text index and the case
base are process-level caches; everything else is per request.

---

## 3. Computations

### 3.1 Reference class, progressive widening and the funnel

**Contract**

```
in:  Features {subsector_main: SAN|WOD|DESZ|OCZ|SUW, value_gross: Money (gross; net × 1.23 with vat_basis note),
               design_build: bool|null, work_type: build|renovation|mixed|null, plan_days, budget, ...}
out: ReferenceClass {levels: [{key, label_pl, n}], chosen: {shares: level, tails: level},
                     n, n_time, n_cost, widened: bool, widen_note_pl, case_ids, data_version}
```

**Algorithm**

1. Ordered filters: `all` → `+ subsector_main` → `+ value_bucket` → `+ design_build` (only if the user gave the
   formula) → `+ work_type` (only if given and n stays ≥ `min_n_tail`). Counts in one pass:

```sql
SELECT count(*)                                                              AS n_all,
       count(*) FILTER (WHERE subsector_main = $1)                           AS n_sub,
       count(*) FILTER (WHERE subsector_main = $1 AND value_bucket = $2)     AS n_sub_val,
       count(*) FILTER (WHERE subsector_main = $1 AND value_bucket = $2
                          AND design_build = $3)                             AS n_sub_val_db
FROM an_contract;
```
   (In the API the same is a mask over `CaseBase`.)
2. Choose the deepest level with `n_time ≥ min_n_tail` for bands and the deepest with `n ≥ min_n_share` for shares.
3. **Widening** when the deepest level is too small, in this order, stopping at the first level that passes:
   (a) drop `work_type`; (b) drop `design_build` and add it back as a **reweighting** note ("ZiW: +x pp w tej
   grupie wartości") from the parent; (c) merge the value bucket with its nearer neighbour on the log scale
   (5–10 → 2–5 ∪ 5–10 if the value is below 7.07 mln, else 5–10 ∪ >10); (d) drop value; (e) subsector family
   (networks SAN/WOD/DESZ, plants OCZ/SUW); (f) all. Known thin cells (05 §9.3): DESZ above 2 mln, SUW above
   10 mln.
4. Funnel labels (PL): „wszystkie wykonane umowy wod-kan, 2021–2026”, „kanalizacja sanitarna”,
   „wartość 5–10 mln zł”, „zaprojektuj i wybuduj”. Bar width as in the mockup: `max(6, sqrt(n/n_all)×100)%`.

**Provenance:** each level is a `Stat` (unit `count`, origin CALC, `definition_pl` lists the filters,
`source.notice_types = [ContractPerformingNotice]`). `analysis.reference_class` stores filters, levels, the
chosen level, `case_ids` and `data_version`.

**Golden (live):** funnel 11 222 → 4 287 → 373 → 82. Test ranges: 11 150–11 450; 4 250–4 420; 360–395;
78–92. Widening: with `design_build = true, subsector = DESZ, value 5–10m` the engine must widen (DESZ × 5–10m is
about 34 contracts; ZiW narrows it further).

### 3.2 Forecast: time, cost, shares

#### 3.2.1 Contract

```
in:  ReferenceClass rows, plan_days D (months × 30.4375), budget (gross), programme_deadline?, announce_date?
out: TimeForecast {p_on_time: Stat, q_days {p10,p50,p80,p90}: Stat, q_months, ci90 for p50/p80,
                   cdf: [(month, share)], rel_plan, flag_short_plan}
     CostForecast {p_no_overrun, p_within_10pct, q_pct {p50,p80,p90}, q_amount}
     Shares {late, changes, paid_above}: Stat with Wilson ci90
     DeadlineForecast {p_before_deadline, months_available, note_pl} (Q3)
```

#### 3.2.2 Time: reconciled ratio model

Durations are not comparable across plans, ratios are. For each class contract with `time_ok`:

* declared on time → `r = min(actual/planned, 1)`;
* declared late and computed delay > 0 → `r = 1 + delay/planned`;
* declared late and computed ≤ 0 (2.4% of rows) → excluded, counted in `n_unknown`.

This makes `P(r ≤ 1)` equal the declared on-time share, so the curve, the KPI and the late share never contradict
each other. The forecast for the user's plan is `T = D × r`.

**Plan-length kernel.** A plan shorter than the class's typical plan has a fatter tail (live, all core works:
plans below 0.6 × median: late 34%, ratio P90 2.08; plans above 1.6 × median: late 25%, ratio P90 1.27). Weight
each case by `w_j = exp(−(ln(rel_j / rel_u))² / (2σ²))`, `rel = planned / median(planned in class)`, σ = 0.5.
If Kish `n_eff = (Σw)² / Σw²` falls below `min_n_tail`, take the parent level with the same kernel.

```python
def time_forecast(r, planned, D, sigma=0.5):
    med = np.median(planned); rel_u = D / med
    w = np.exp(-np.log((planned / med) / rel_u) ** 2 / (2 * sigma ** 2))
    q = wquantile(r, w, [.1, .5, .8, .9]) * D                    # weighted empirical quantiles
    p_on = (w * (r <= 1)).sum() / w.sum()
    return p_on, q, kish(w)

def wquantile(x, w, qs):                                         # midpoint interpolation (03 §4.3)
    o = np.argsort(x); x, w = x[o], w[o]; cw = (np.cumsum(w) - w / 2) / w.sum()
    return np.interp(qs, cw, x)
```

**Bootstrap CI.** B = 1000 resamples of the class rows with probabilities `w/Σw`; recompute `p_on`, P50, P80;
`ci90` = 5th and 95th percentiles. Measured: 3–5 ms for n = 77.

**Shares.** Late, ≥1 change and paid above value (> +0.5%) as `k of n` with the Wilson 90% interval (never Wald):
`centre = (p + z²/2n)/(1 + z²/n)`, `half = z * sqrt(p(1−p)/n + z²/4n²)/(1 + z²/n)`, z = 1.645.

**Q1 card ("Czy zdążysz w 14 miesięcy?").** Verbal answer from `p_on`: < 0.25 „Nie”, 0.25–0.5 „Raczej nie”,
0.5–0.75 „Raczej tak”, ≥ 0.75 „Tak” (the mockup's four steps). Band = P10–P90 months, tick = P50, marker = D.

#### 3.2.3 Cost

`cost_dev_pct` with `cost_ok`; `p_no_overrun = share ≤ +0.5%`; quantiles P50/P80/P90; amounts =
`budget × (1 + q)`. Always say "x% umów zapłaciło ponad wartość; wśród nich typowo +y%" (05 §9.2), never a
mean. Show the lower-bound note (CP 4.4 baseline).

#### 3.2.4 Programme deadline (Q3)

`p_before_deadline = P(sign_date + T ≤ deadline)`. `sign_date = announce_date + tender_days`, with
`tender_days` resampled from the subsector's CN → signing distribution (live SAN: P10/P50/P80/P90 =
34/47/64/77 days, n = 3 736; query below). Without an announce date use the analysis date. The deadline comes
from `funding_programmes.yaml` (§4.2) or a chip the user edits. Computed in the same Monte Carlo as §3.5 so the
two screens agree.

```sql
SELECT p.subsector_main, percentile_cont(array[.1,.5,.8,.9]) WITHIN GROUP
       (ORDER BY r.signed_on - n.published_at::date) AS days_cn_to_sign
FROM an_contract r JOIN procedure p ON p.id = r.procedure_id
JOIN notice n ON n.procedure_id = p.id AND n.notice_type = 'ContractNotice' AND n.is_latest
WHERE r.signed_on >= n.published_at::date AND r.signed_on - n.published_at::date < 730
GROUP BY ROLLUP (1);
```

#### 3.2.5 Hurdle model (03 §4.3), optional tonight

Only for tier medium/low or as a cross-check. Occurrence: `p_late ~ Beta(m*p0 + k, m*(1−p0) + n − k)`, p0 =
parent late share, m = `prior_m`. Size: `z = ln(delay | late)`, Normal-Normal shrinkage to the parent mean with
m0 = 10, pooled σ; predictive draws, 20 000, cap 1 500 d. 60 lines, about 1 h with tests. Prototype on the demo
class: p_late 0.61, delay P50/P80/P90 = 48/146/225 d (empirical 66/144/177). **Fallback if not built:** widen
(§3.1) and show the parent's empirical quantiles labelled „tło sektorowe”.

#### 3.2.6 Provenance

`origin CALC`, `method empirical_ratio` (+ `bootstrap` for ci90, `wilson` for shares), `n` = rows with known
ratio, `n_eff`, `n_unknown`, `source.field_codes = ["4.1","4.2","5.2","5.3"]` (time) and `["4.4","5.5"]` (cost),
`case_ids`. The "W skrócie" sentence is a template over these numbers (never LLM):

> „Podobne inwestycje ({n} umów: {klasa}) w {late}% kończyły się po terminie. Przy planie {D} mies. szansa na
> termin to ok. {p_on}%, a 8 na 10 umów skończyłoby się w {t80} mies. Koszt kilometra ({ppk} mln zł) jest wyższy
> niż w {pct}% umów.”

#### 3.2.7 Golden (live, demo class, D = 426 d = 14 mies.)

| output | prototype | test range |
|---|---|---|
| p_on_time (unweighted / kernel) | 0.364 / 0.344 | 0.30–0.42 |
| months P10 / P50 / P80 / P90 | 13.5 / 15.7 / 18.4 / 20.9 | 12.5–14.5 / 15.0–16.5 / 17.5–19.5 / 19.5–22.5 |
| ci90 of p_on_time | 0.27–0.46 | width 0.12–0.24 |
| P(T ≤ 18 mies.) | 0.78 | 0.70–0.85 |
| late share Wilson 90% | 0.54–0.72 | centre 0.60–0.67 |
| cost P80 / P90 | 4.1 / 10.7% | 3.5–4.8 / 9.5–12.5 |
| flag "termin krótszy niż typowy" | 426 < P25 452.5 | fires |

### 3.3 Unit cost (PLN per km)

**Contract**

```
in:  subsector_main, budget (gross), length_km (chip), optional contract_year, index_to (e.g. 2026)
out: UnitCost {user_ppk, p25, p50, p75, p90, user_percentile, n, coverage, nominal|indexed, curve by year}
```

**Lengths.** Port `research/bzp_corpus/07_wow_features.lengths()` verbatim into `riskminer/parsing/lengths.py`
(regex `_LEN_RX`, `_CONN_RX`, `_SKIP_RX`, `_TOTAL_RX`; values < 5 m or > 200 km dropped; "przyłącz…" within 60
characters before → connection length; an explicit "łączna długość" total wins over the sum). Text = procedure
title + CP description (section 3.8). Fill `contract_metric` for all `an_contract` rows with
`riskminer analytics refresh` (about 1 s), `source_id` = the CP notice's source.

**Migration note.** `rc_contract` is a materialized view built by `derive.py`; do not add a column there. Use the
`contract_metric` table (§1.1) joined into `an_contract`. If the data session prefers a column on
`contract_performance`, the view join changes, nothing else.

**Coverage (live, net length found):** SAN 49.8%, WOD 54.8%, DESZ 33.0%, SUW 16.5%, OCZ 12.2%, all 44.3%.
Unit cost is offered only for SAN, WOD, DESZ (networks); plants get "brak miary długości" and a pointer to
RLM / m³/d (not built tonight).

**Unit cost.** Keep rows with `length_km ∈ [0.1, 100]`, `value_gross > 50 000`, `ppk = value_gross / length_km
∈ [50 000, 20 000 000]`. Class = **subsector only** (optionally by length band), **not by value bucket**: the
metric has value in the numerator, so conditioning on value biases it (inside SAN 5–10 mln the P50 jumps to
1.24 mln zł/km, n = 184). User percentile = share of class `ppk ≤ user_ppk` („tańsze niż X% umów” in plain
language mode).

**Indexation (optional toggle „w cenach 2026”).** `data/ref/price_index_construction.csv` (GUS, construction and
assembly production prices): annual `Y/I4` (2015 = 100: 2021 113.9, 2022 128.4, 2023 141.5, 2024 150.0,
2025 154.8); for 2026 chain the monthly `M/A` (same month previous year = 100) onto 2025. `ppk_idx = ppk ×
I(target)/I(contract_year)`. The design's limitation line „Koszt kilometra w cenach nominalnych (bez indeksacji
GUS)” disappears when the toggle is on; the GUS file row is the `source_id`.

**Provenance:** `CALC`, method `regex_v1 + quantiles`, `n`, `coverage` (rows with length / class rows),
`source.field_codes = ["3.7","3.8","4.4"]`, sample of case ids with their parsed length for the expert to check.

**Golden (live):** SAN n = 1 844 (range 1 750–1 950), P25/P50/P75 = 0.514/0.862/1.444 mln zł/km (ranges
0.48–0.55 / 0.82–0.90 / 1.38–1.50); WOD n = 1 938, 0.242/0.386/0.727; DESZ n = 281, 0.934/1.655/2.911;
demo 7 mln / 6 km → percentile 65.4 (62–68). SAN P50 by year 2021 0.72 → 2022 0.99 (+37%; research +41%). Regex unit
tests: „ok. 6 km” → 6.0; „1 234,5 mb” → 1.2345; „przyłącza o długości 250 m” → conn; „na głębokości 3 m” →
skipped; „o łącznej długości 2 064 mb” → total; „450 m n.p.m.” → skipped; „DN 160 mm” → skipped.

### 3.4 Similarity

**Contract**

```
in:  Features of the new investment, pool = pilots (22) ∪ national (an_contract), top_k
out: [SimilarCase {case_ref (RM-… or BZP no.), is_pilot, score S, coverage, contributions [{feature, s_i, w'_i, c_i}],
                   gaps [{feature, g_i}], why_pl, diff_pl, outcome {delay_days, cost_pct, late, changes}: Stat(SOURCE),
                   matched_terms, risk_overlap}]
```

**Features and s_i** (weights from `catalogue/wod-kan/similarity.yaml`, read through `catalogue_entry` so the
expert can edit them):

| feature | w | candidate value | s_i |
|---|---|---|---|
| subsector_main | 0.20 | `subsector_main` | 1 same; 0.6 if one's main is in the other's `subsectors`; 0.3 same family (SAN/WOD/DESZ, OCZ/SUW); 0 |
| subsectors_all | 0.05 | `subsectors` | Jaccard |
| works_type | 0.07 | `work_type` | 1 same; 0.5 mixed vs pure; 0 build vs renovation |
| formula | 0.08 | `design_build` | 1 same; 0 different |
| value | 0.12 | `value_gross` (pilots: contract value from rc, never the KPO project value, 03 §4.2.4) | `exp(−ln(v1/v2)² / (2 × 0.693²))` |
| physical_size | 0.10 | `length_km` | same kernel |
| tech_tags | 0.07 | matched `lexicon.yaml → components` patterns in title + description | Jaccard |
| period | 0.06 | year of `signed_on` (new: planned year) | `exp(−|Δy|/3)`, × 0.7 across regimes ≤2021 / 2022–23 / ≥2024 |
| funding | 0.04 | pilots: `project.funding_programme`; national: `eu_funded` → family EU or own | 1 same; 0.5 same family; 0 |
| beneficiary_type | 0.03 | from buyer name: gmina wiejska / miejsko-wiejska / miejska (TERYT `rodz` via §3.9) / spółka / związek / inne | 1; 0.6 gmina vs gmina; 0.2 |
| region | 0.05 | `woj` | 1 same; 0.5 neighbour (adjacency list below); 0.2 |
| text | 0.13 | title + CP description | BM25 normalised (below); dense part off until embeddings exist |

`S = Σ_{i∈A} w_i s_i / Σ_{i∈A} w_i`, A = features present in both; `coverage = Σ_{i∈A} w_i`; contribution
`c_i = w_i s_i / Σ_A w` (they sum to S exactly); gap `g_i = w_i (1 − s_i) / Σ_A w`. Inclusion for the forecast
pool: `S ≥ 0.55` and `coverage ≥ 0.5`; list shows top_k = 30 with at most 2 per buyer in the top 10 (badge
"ten sam zamawiający").

**Text part tonight (no embeddings).** In-memory BM25 (k1 = 1.2, b = 0.75) over folded 6-character stems of title
+ first 600 characters of the CP description, stop-words removed (place and admin words: gmina, miejscowość,
budowa, etap, część…). Build at startup: 0.9 s for 11 222 documents, 14.7k terms; query 50 ms in pure Python
(vectorise posting lists if needed). Normalise per query: `s_text = clip((score − c0)/(c1 − c0), 0, 1)` with c0 =
median and c1 = P99 of the scores over the pool. Return the 2–3 matched stems as `matched_terms`. Postgres
fallback: `procedure.title` has a trigram index, but a full `similarity()` scan took 1.7 s, so do not use it in the
request path. When `chunk.embedding` arrives: `s_text = 0.7 × cos + 0.3 × bm25_norm` (the yaml already says so).

**Region adjacency** (TERYT woj codes; add to `similarity.yaml → features.region.neighbours`; a test verifies it
once against shared borders in `data/ref/geo/woj.geojson`):

```yaml
neighbours: {"02": ["08","16","30"], "04": ["10","14","22","28","30"], "06": ["14","18","20","26"],
  "08": ["02","30","32"], "10": ["04","14","16","24","26","30"], "12": ["18","24","26"],
  "14": ["04","06","10","20","26","28"], "16": ["02","10","24","30"], "18": ["06","12","26"],
  "20": ["06","14","28"], "22": ["04","28","30","32"], "24": ["10","12","16","26"],
  "26": ["06","10","12","14","18","24"], "28": ["04","14","20","22"], "30": ["02","04","08","10","16","22","32"],
  "32": ["08","22","30"]}
```

**Pools.** (a) The 22 pilot projects: features from `project` (subsector, works_type, delivery_model, funding) and
the linked `an_contract` rows (value, length, dates, outcome); multi-lot projects (Biecz, Zakrzew, Wolin) use the
largest lot for value and the union for outcome. (b) National: all `an_contract` rows. One ranked list over the
union, pilots tagged „przypadek zweryfikowany”. Scoring the whole pool is vectorised numpy: under 100 ms with
BM25.

**"Why" templates** (`templates_pl.py`; top 3 contributions, then top 2 gaps):

| feature | „dlaczego” | „różnica” |
|---|---|---|
| subsector_main | „ten sam podsektor” / „podsektor z tej samej grupy” | „inny podsektor: {x}” |
| formula | „też „zaprojektuj i wybuduj”” / „też samo wykonanie” | „formuła: {a} wobec {b}” |
| value | „podobna wartość ({a} wobec {b} mln zł)” | „wartość {a} wobec {b} mln zł” |
| physical_size | „podobna długość sieci ({a} wobec {b} km)” | |
| tech_tags | „wspólne elementy: {tags}” (e.g. „przepompownie, rurociąg tłoczny”) | |
| period | „ten sam okres cen” | „inny okres cenowy: {y1} wobec {y2}” |
| region | „to samo województwo” | |
| text | „podobny opis: {terms}” | |

Sentence: join the top three with „, ” (mockup: „ten sam podsektor, przepompownie, podobna wartość”). Coverage
line: „porównanie oparto na {k} z 12 cech (pokrycie {coverage})”. The stacked bar uses `c_i` grouped into the five
mockup colours (podsektor = subsector_main + subsectors_all; formuła; zakres i ilości = works_type + physical_size +
tech_tags; wartość = value + period; opis = text; the rest grey). The risk overlap badge („sygnał: … → w tym
przypadku: …”) is computed separately from the case's change codes and is **not** part of S.

**Provenance:** S and c_i are `CALC` (method `weighted_similarity_v1`, weights version from the catalogue); the
case outcome numbers are `SOURCE` with the case's BZP numbers and field codes; store
`similarity_explanations` rows in `analysis_item(section='similar', body={case, s_i, w'_i, c_i, text_pl})`.

**Golden:** property tests (identical feature vector → S = 1.0; contributions sum to S within 1e-9; dropping a
feature lowers coverage, not S; S decreases monotonically with the value ratio). Demo input (SAN, ZiW, 7 mln,
6 km, 2027): Bestwina RM-2026-013 (SAN, ZiW, 5.99 mln) ranks in the top 3 pilots with S ≥ 0.65 (hand-computed
about 0.75–0.8, not yet run); Steklin RM-2026-003 (OCZ, ZiW, 2.13 mln) scores lower than Bestwina.

### 3.5 Monte Carlo for 1.4 Symulacja

#### 3.5.1 Contract

```
POST /analyses/{id}/simulate
in:  {metric: time|cost|comp, toggles: ["M-GEO","M-K07",...], whatif: {tender_delay_months?, one_offer?, price_shock_pct?},
      seed?}
out: {series: [{label_pl, toggles, points: [[x, y]]}],   // "Teraz", one per toggle affecting the metric, "Razem" if ≥2
      kpis: [{label_pl, value: Stat, delta_pp}], tornado: [{risk, label_pl, delta, n_r}],
      per_risk: [{risk, p_r: Stat, impact_days {p50,p80}, impact_cost_pct {p50,p80}, n_r, kw_quality_note}],
      markers: [{x, label_pl}], summary_pl, assumptions: [...]}
```

#### 3.5.2 Engine: case resampling with risk attribution

Resampling whole cases keeps the correlation between delay, cost and causes (the mockup's limitation
„Ryzyka liczone niezależnie” then no longer applies to the base curves).

1. Draw N = 20 000 case indices `j` from the class with the §3.2 kernel weights (same seed per
   `analysis_id + params hash`, so the screen is stable).
2. Time: `T = D × min(r_j, 1) + E_t,j × (1 − removed_t,j)`, `E_t,j = max(r_j − 1, 0) × D` (excess days).
3. Cost: `C = budget × (1 + min(c_j, 0) + E_c,j × (1 − removed_c,j))`, `E_c,j = max(c_j, 0)`.
4. **Attribution:** `K_j` = the case's cause codes (all its changes; N-FORMAL and N-UNSPEC ignored). Each code
   gets the equal share `1/|K_j|` of the excess. Cases with excess and no code feed the row „bez rozpoznanej
   przyczyny” (live: 10.4% of the demo class are late without a coded cause).
5. **Mitigations:** for each toggled mitigation and each of its effects `{risk k, p_keep, time_cut, cost_cut}`,
   on draws with `k ∈ K_j`: with probability `1 − p_keep` the event is prevented (its whole share removed);
   otherwise `time_cut` (resp. `cost_cut`) of its share is removed. `removed` is the sum of removed shares,
   capped at 1.
   Catalogue sub-risk codes (R02.1) map to the data's top-level code by prefix.
6. **Plan override** (M-PLAN18): set `D` to the class median plan and recompute the kernel weights; the
   programme marker stays at its calendar date, so P(after programme end) rises, as the mockup warns.
7. Curves: time = empirical CDF of T in months on the 12–24 axis (or P5–P99 of T); cost = CDF of C in mln zł;
   competition = §3.6 curve with the toggles' `offers_shift`: `P'(≥N) = 1 − (1 − P(≥N)) × decay^{Σ shift}`,
   `decay = 0.85` (mockup formula, catalogue parameter); cancellation base = the class's lot cancellation share in
   the last 24 months, plus `Σ cancel_pp`, floored at 4%.
8. KPIs (deltas in pp against „Teraz”): time: P(T ≤ D), T50, T80, P(after programme end); cost:
   P(C ≤ 1.1 budget), P(C ≤ budget), C80, C90; competition: P(≥2), median offers, P(exactly 1), cancellation.
9. **Tornado:** for each code with `n_r ≥ 3` in the class: `Δ = T80(base) − T80(code fully removed)` in days
   (cost: C90 in pp of budget). Sorted; the unattributed row always shown.

```python
def run(j, r, c, share, D, budget, effects, rng):          # share: n_cases × n_codes (equal split)
    ex_t = np.maximum(r[j] - 1, 0) * D; ex_c = np.maximum(c[j], 0)
    red_t = np.zeros(len(j)); red_c = np.zeros(len(j)); sh = share[j]
    for k, p_keep, time_cut, cost_cut in effects:
        s = sh[:, k]; prevented = rng.random(len(j)) > p_keep
        red_t += s * np.where(prevented, 1.0, time_cut); red_c += s * np.where(prevented, 1.0, cost_cut)
    T = D * np.minimum(r[j], 1) + ex_t * (1 - np.minimum(red_t, 1))
    C = budget * (1 + np.minimum(c[j], 0) + ex_c * (1 - np.minimum(red_c, 1)))
    return T, C
```

The tornado reuses `run` with one effect `(k, 0.0, 1.0, 1.0)` per code (risk fully removed).

#### 3.5.3 Per-risk P(r) and impact distributions

From the same arrays: `P(r)` = weighted share of class cases with r; impact | r = distribution of the attributed
days and cost share among those cases (P50, P80); `n_r`. Because class-level `n_r` is 2–27, compute per-risk
statistics at the **parent level `subsector + value ≥ 2 mln`** (SAN: n = 1 294) and scale impacts to the user's
plan and budget (impacts are stored as % of plan and % of value). Show each with its tier by `n_r`.

Keyword quality note (from `research/bzp_corpus/out/keyword_vs_gold.csv`, 150 gold causes): precision/recall
R02 0.82/0.56, R03 0.87/0.72, R04 0.50/0.80, R07 0.55/0.66, R08 0.23/0.62, R06 0.0, R11 0.0. Show P(r) as
measured, with the note „reguły słownikowe: ok. {precision×100}% trafień” for R04/R08; hide R06 and R11 rows
until LLM codes exist. When `cause_codes_ai` lands, no engine change is needed.

#### 3.5.4 What-ifs (mockup chat chips)

| what-if | computation | answer template (PL) |
|---|---|---|
| przetarg +2 mies. | `announce_date += 61 d`; deadline fixed; same draws | „Do końca programu zostanie ok. {m} mies. od podpisania umowy zamiast {m0}. Ryzyko odbioru po terminie programu rośnie z {a}% do {b}%.” |
| tylko jedna oferta | P(1 offer) from §3.6 for the class; late share by offer count at national level (live: 1 offer 31.8%, 8+ 23.6%, n = 10 070; within 1–5 mln: 42.3% vs 35.1%); optional MC restricted to parent cases with `n_offers = 1` | „Umowy z jedną ofertą kończyły się po terminie w {x}% przypadków, przy 8 i więcej ofertach w {y}%. Szansa na jedną ofertę w Twoim przetargu to ok. {p}%.” |
| ceny +10% | cost shift `budget × materials_share × 0.10` with `materials_share` from `mitigations.yaml defaults` (0.5, assumption); with M-K07 the buyer pays it during works up to the clause cap; without, text only | „Z klauzulą K-07 część wzrostu zapłacisz w trakcie budowy, ok. {x} mln zł…” |

Each what-if answer is `CALC` for the numbers and labelled „wniosek AI do sprawdzenia” only if an LLM phrases it;
the default is the template (no LLM).

#### 3.5.5 Funding-deadline probability

Same draws as §3.2.4: `P(sign + T > deadline)`; F5 (§3.11) fires when `deadline − (sign_P50 + D) < 60 d`.
The A2 Q3 card and the A4 "Po terminie programu" KPI read the same number.

#### 3.5.6 Performance

Prototype on the demo class: one run with 20 000 draws and four toggles = **3 ms**; ten runs = 16 ms. A full
response (base, ≤4 single toggles, „Razem”, tornado of ~12 codes, three metrics) is about 25 runs ≈ 80 ms plus
serialisation. Target < 500 ms holds with a wide margin; keep `mc_draws` configurable.

#### 3.5.7 Golden (live, demo class, D = 14 mies., budget 7 mln zł)

* Base: P(T ≤ 14 mies.) 0.30–0.42 and within ±0.03 of §3.2's p_on_time (same weights); T80 17.5–19.5 mies.;
  P(T ≤ 18 mies.) 0.70–0.85; cost C90 9–12.5% over budget; P(C ≤ 1.1 budget) 0.85–0.92.
* Tornado: R04 and R07 in the top 3 (prototype: R04 −20 d, R07 −20 d at T80).
* Monotonicity: no toggle worsens T80, C90 or P(≥2 offers).
* Determinism: same request twice → identical arrays.
* Per-risk at parent SAN ≥ 2 mln (n = 1 294): P(R04) 0.14–0.19, P(R07) 0.20–0.26, P(R02) 0.07–0.12.

#### 3.5.8 Honesty note for the demo

With data-driven attribution the four toggles move the time KPI by 0–4 pp and T80 by up to about 10 days
(prototype: all four together 18.3 → 17.9 mies.; cost P90 10.7 → 10.0%). The mockup's effects (−0.9 month for
soil surveys etc.) were demo values. Show the honest result with the line „Efekt liczony tylko z umów, w których
rozpoznano przyczynę zmiany ({k} z {n}); wielkości wpływu to założenia eksperta z Katalogu”. M-PLAN18 still moves
the curve visibly because it changes the plan itself.

### 3.6 Tender outcomes from `lot`

```sql
SELECT extract(year FROM n.published_at)::int AS yr, count(*) AS lots,
       round(avg(l.cancelled::int) * 100, 1)                                          AS cancelled_pct,
       round(avg(coalesce(l.cancel_basis LIKE 'art. 255 pkt 3%', false)::int) * 100, 1) AS cancelled_price_pct,
       round(avg(coalesce(l.n_offers = 1, false)::int) * 100, 1)                       AS single_offer_pct,
       round(avg((l.n_offers >= 2)::int) FILTER (WHERE l.n_offers > 0) * 100, 1)        AS ge2_pct,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY l.n_offers)                          AS median_offers
FROM lot l JOIN procedure p ON p.id = l.procedure_id JOIN notice n ON n.id = l.result_notice_id
WHERE p.sector = 'wod-kan' AND p.relevance IN ('core','cpv_only') AND p.scope_kind = 'works'
  AND l.cancelled IS NOT NULL
GROUP BY ROLLUP (1) ORDER BY 1;
```

Denominators match the research: cancelled, price-above-budget and single-offer shares over **all** result lots;
P(≥2) over lots with at least one offer; median over lots with a count.

**Competition curve for a class:** lots with the same subsector, gross size `coalesce(estimate_net × 1.23,
winning_offer)` within the value bucket, result published in the last 24 months; `P(≥N) = share(n_offers ≥ N)`,
N = 1…10. Fallbacks: < 50 lots → drop size; < 50 → all subsectors.

**Provenance:** `CALC`, `source.notice_types = [TenderResultNotice]`, field codes 5.1, 5.2, 6.1, n per year.

**Golden (live):**

| year | lots | cancelled | art. 255 pkt 3 | single offer | median offers |
|---|---|---|---|---|---|
| 2021 | 2 031 | 26.9 | 14.8 | 24.0 | 2 |
| 2022 | 4 452 | 32.7 | 20.3 | 24.6 | 2 |
| 2023 | 3 734 | 26.2 | 17.3 | 18.1 | 3 |
| 2024 | 3 702 | 19.1 | 12.3 | 12.4 | 4 |
| 2025 | 3 309 | 14.3 | 7.8 | 11.5 | 4 |
| 2026 | 2 543 | 14.2 | 7.2 | 8.6 | 5 |

Tolerance ±1.5 pp (live delta still arriving). The research says median 6 for 2026; live is 5. Demo class curve
(SAN, 5–10 mln, 2025+, n = 162): P(≥2) 95.7%, P(≥3) 86.4%, P(≥6) 54.3%, P(≥7) 45.7% → median 6; cancelled
10.1% build-only (n = 138), 0 of 30 design-build.

### 3.7 Risk allocation for 1.5

**Contract**

```
GET  /analyses/{id}/allocation → {risks: [{code, label_pl, expected_cost: Stat(pln), impact_text_pl, controllability,
                                          recommended, positions: [{who, how_pl}], chosen, warn_pl, case_refs}],
                                  balance: {buyer, contractor, premium}: Stat(pln), off_count, note_pl, pack_items}
PUT  /analyses/{id}/allocation   {choices: {R02: "buyer", ...}} → same, stored as analysis_item(section='allocation')
```

**Which risks:** the risks flagged for this analysis (calculated flags + AI flags from PFU/PPU, including
proposed ones) ∪ the top 3 of the tornado; at most 8 rows.

**Expected cost per risk** (parent-level statistics, §3.5.3):

`e_r = budget × E[attributed cost share_r] + budget × delay_cost_rate_per_month × E[attributed days_r] / 30.4375`

`delay_cost_rate_per_month` (default 0.5% of contract value per month: supervision, financing, own staff) is an
expert assumption in `allocation.yaml`. Impact line „jeśli się zdarzy: P80 +{d} dni” / „koszt P80 +{x}%” comes
from impact | r. Data-driven `e_r` is small (0.1–0.7% of value per risk; 7 mln zł → 7–50 tys. zł), so the balance
bar is honest but less dramatic than the mockup (which used 90–250 tys. zł per risk).

**Balance (exactly the mockup's math, `A5-Podzial.dc.html`):**

```python
def balance(risks, choice):                        # choice[code] in {"buyer","shared","contractor"}
    buyer = contr = prem = 0.0
    for r in risks:
        e, w, ctl, p = r.e, choice[r.code], r.controllability, r.premium   # p from allocation.yaml (defaults below)
        if w == "buyer":
            buyer += e
        elif w == "shared":
            buyer += e / 2; contr += e / 2
            prem += 0 if ctl == "contractor" else e * p["shared"]                         # 0.10
        else:
            contr += e
            prem += e * (p["contractor_controlled"] if ctl == "contractor" else p["contractor_uncontrolled"])  # 0.10 / 0.60
    off = sum(choice[r.code] != r.recommended for r in risks)
    return buyer, contr, prem, off
```

Display: round to 10 tys. zł; premium in orange when above 120 tys. zł (mockup rule, make it 1.7% of budget);
note „Podział zgodny z zaleceniami…” or „{off} ryzyka podzielone inaczej niż zalecamy…” (Polish plural rules
as in the mockup).

**Case-based warning per risk:** the most similar case (§3.4) whose changes carry the code, with its attributed
days or amount: „W {miejscowość} {opis}; {+d dni | +x zł}” (`SOURCE` numbers, BZP numbers linked).

**Provenance:** `e_r`, balance: `CALC` with `assumptions` = premium factors, delay cost rate, controllability,
recommended position (all `allocation.yaml`, status `proposed` until approved). How-texts are catalogue copy.

**Golden:** mockup default state (R02 buyer, R03 buyer, R04 shared, R06 shared, R08 contractor, R13 shared;
e = 210, 90, 120, 160, 250, 230 tys. zł; controllability buyer/buyer/shared/shared/buyer/shared) → buyer 555,
contractor 505, premium 201 (displayed 560 / 510 / +200 tys. zł), off = 1 (R08). Live demo `e_r` at budget
7 mln: each 5–60 tys. zł.

### 3.8 Backtest W3

Train on `an_contract` rows completed before 2024-01-01 (n = 4 569), test on those completed 2024-01-01 or later
(n = 6 378). For each test row predict P10/P80/P90 from its train class `subsector × value_bucket`, falling back to
the global band when the class has n < 30 (05 §10.4). Metrics: share inside P10–P90, share ≤ P80, share above P90,
pinball loss at P90 vs the global band; late as probability: Brier score vs the global rate, calibration in bins
of predicted p. Runs in numpy in < 1 s; store results in `analysis_item`-like JSON under
`GET /api/analytics/backtest` (cache per `data_version`).

**Golden (live, reproduced tonight):**

| metric | inside P10–P90 | above P90 | ≤ P80 | pinball P90 class / global |
|---|---|---|---|---|
| delay days | **85.0%** | 15.0% | 76.1% | 17.2 / 18.7 |
| delay % of plan | **87.7%** | 12.3% | 77.1% | 10.5 / 10.3 |
| cost deviation % | **79.5%** | 12.9% | 79.6% | 1.57 / 1.62 |
| late (prob.) | Brier **0.217** class vs 0.227 global | predicted 27.5% vs observed 33.4% | | |

Test ranges: 0.83–0.87, 0.86–0.90, 0.77–0.82; Brier class < global. One line in 1.2 (design suggestion):
„Sprawdziliśmy prognozy na 6 378 umowach zakończonych później: 85% opóźnień mieściło się w przedziale 8 na 10.”
State the known bias: late probability runs low by about 6 pp (right-censoring of the training set).

### 3.9 Monitoring

#### 3.9.1 Buyer → gmina / powiat (TERYT)

`ref_teryt` holds woj (16), pow (380), gmi (2 479, `rodz` 1 urban, 2 rural, 3 urban-rural) and parts (4/5).
`procedure` has `buyer_name`, `city`, `province` (PLxx). Algorithm (`teryt.py`, fills `an_buyer_teryt`):

1. Normalise the buyer name: strip „Urząd”, „Gmina Miejska”, „Gmina Miasto”, „Miasto i Gmina”, „Gmina i Miasto”,
   „Gmina Wiejska”, „Gmina”, „Miasto”, „Urząd Miejski w”, „Urząd Gminy”; cut at „,”, „(”, „ - ”, „–”; lower-case.
2. Type preference from the prefix: urban words → rodz 1, 3; „wiejska” → 2; „Miasto i Gmina” → 3; plain
   „Gmina X” → 2, 3, 1 (so „Gmina Elbląg” is the rural gmina, not the city); companies and others → 1, 3, 2.
3. Candidates: `ref_teryt` gmi rows in the same woj whose name equals the normalised name (method `name`,
   confidence 0.9), else equals `buyer_city` (method `city`, confidence 0.6: the seat, e.g. a regional road
   authority maps to Poznań). Take the best `rodz` rank; a tie → confidence 0.4, `review_status = 'proposed'` and a
   `review_item` („Do której gminy należy zamawiający {name}?”, invariant 10).
4. `pow = terc7[:4]`, `woj = terc7[:2]`.

Live: 3 252 of 3 354 core buyers resolve uniquely (97%), covering 98% of core contracts; 17 ties; the rest have
no match (associations, utilities outside their gmina). All 22 pilot buyers map correctly, including the traps in
02 §TERYT: Gmina Elbląg → 2804012 (rural), Gmina Sanok → 1817052 (rural), Kamionka → 0608053 (lubelskie),
Nowogard → 3204043, Bobrowniki → 2401042 (śląskie, as in the source).

#### 3.9.2 Area aggregates (materialized view `mv_monitor_area`)

```sql
CREATE MATERIALIZED VIEW mv_monitor_area AS
SELECT woj, pow, terc7, subsector_main, completion_year,
       GROUPING(woj, pow, terc7, subsector_main, completion_year)                AS gset,   -- which grouping set
       count(*)                                                                  AS n,
       count(*) FILTER (WHERE late)                                              AS n_late,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY delay_days) FILTER (WHERE late AND time_ok) AS delay_med_if_late,
       sum(greatest(paid_gross - value_gross, 0)) FILTER (WHERE cost_ok)        AS overpaid_sum,
       sum(value_gross) FILTER (WHERE cost_ok)                                   AS value_sum,
       count(*) FILTER (WHERE changes_count > 0)                                 AS n_changed,
       count(*) FILTER (WHERE properly_performed IS FALSE)                       AS n_improper
FROM an_contract
GROUP BY GROUPING SETS ((), (woj), (woj, pow), (woj, pow, terc7),
                        (subsector_main), (woj, subsector_main), (completion_year), (woj, completion_year));
```

Metrics (D2 switch): Po terminie = n_late/n; Opóźnienie = delay_med_if_late; Dopłaty = overpaid_sum/value_sum;
Zmiany umów = n_changed/n; Nienależyte wykonanie = n_improper/n; Sygnały = radar count (§3.9.3). Areas with
n < 30 show counts, not shares („za mało danych”), which applies to most gminas. Filters the mockup offers
(podsektor, lata) map to the grouping sets; "wartość" filter is computed on the fly from `an_contract` in memory.

**Golden (live, woj; matches the D2 `ST` array):** PL02 n 600, late 40.2%, delay median 63 d, overpaid 40.7 mln of
1 038.6 mln, changes 53.8%; PL04 23.4% / 55 d; PL08 43.4% / 62 d; PL14 n 1 707. Tolerance ±1.5 pp, ±5 d.

#### 3.9.3 Early-warning radar (`mv_radar`)

```sql
CREATE MATERIALIZED VIEW mv_radar AS
SELECT c.id AS contract_id, p.ocid, p.title, p.buyer_name, p.buyer_nip, bt.terc7, substr(p.province,3,2) AS woj,
       p.subsector_main, c.signed_on, c.planned_end_on, c.value_amount AS value_gross, c.result_notice_no,
       (SELECT count(*) FROM contract_change ch WHERE ch.contract_id = c.id AND ch.kind = 'change_notice') AS n_change_notices,
       (SELECT array_agg(DISTINCT b) FROM contract_change ch, unnest(ch.legal_basis) b
         WHERE ch.contract_id = c.id AND ch.kind = 'change_notice') AS change_bases,
       EXISTS (SELECT 1 FROM contract_performance pf WHERE pf.procedure_id = c.procedure_id) AS cp_in_procedure
FROM contract c JOIN procedure p ON p.id = c.procedure_id
LEFT JOIN an_buyer_teryt bt ON bt.buyer_nip = p.buyer_nip
WHERE p.sector = 'wod-kan' AND p.relevance IN ('core','cpv_only') AND p.scope_kind = 'works'
  AND c.terms_source = 'result_notice' AND c.signed_on IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM contract_performance pf WHERE pf.contract_id = c.id);
```

`days_past_end = as_of − planned_end_on` is computed at query time (`as_of` from config, default today), so
the view never goes stale between refreshes. Status: **czerwony** = days_past_end > 0 and a change notice with basis 455.1.3 or 455.1.4; **pomarańczowy** =
days_past_end > 90, no change notice; **szary** = 0–90 days (the notice is due within 30 days); future = „w toku”.
UI copy: „sygnał, nie dowód” (about 25% of contracts never get a performance notice). Refresh with the nightly
`analytics refresh` and after each live BZP pull; `as_of` fixes "today" for the demo.

**Golden (live, as of 2026-11-21):** awarded 15 362; without a performance notice 4 956 (research 4 873); past
end > 90 days 3 420 (research 3 321); past end with a change notice 202 (research 234). Ranges: 4 800–5 150;
3 250–3 600; 180–240. The five mockup alerts (Jeżów Sudecki, Potworów, Lędziny, Kąty Wrocławskie, Mogilno) should
appear in the red list unless a performance notice arrived since; the test asserts at least 3 of 5.

### 3.10 Pulpit numbers and "Zapytaj pamięć" safe views

#### 3.10.1 Headline (`GET /api/analytics/headline`)

```sql
SELECT count(*) AS n, avg(late::int) AS late_share, avg((changes_count > 0)::int) AS change_share,
       sum(delay_days) FILTER (WHERE time_ok) AS delay_days_sum,
       percentile_cont(array[.5,.9]) WITHIN GROUP (ORDER BY delay_days) FILTER (WHERE late AND time_ok) AS delay_if_late,
       percentile_cont(.9) WITHIN GROUP (ORDER BY cost_dev_pct) FILTER (WHERE cost_ok) AS cost_p90,
       avg((cost_dev_pct > 0.5)::int) FILTER (WHERE cost_ok) AS paid_above_share,
       sum(value_gross) FILTER (WHERE cost_ok) AS value_sum, sum(paid_gross) FILTER (WHERE cost_ok) AS paid_sum,
       sum(greatest(paid_gross - value_gross, 0)) FILTER (WHERE cost_ok) AS overpaid_sum
FROM an_contract;
```

Template (Main): „Od 2021 r. {late}% z {n} wykonanych umów wodno-kanalizacyjnych skończyło się po terminie,
łącznie {delay_k} tys. dni opóźnień. Ponad wartość umów zapłacono {overpaid} mln zł.”

**Golden (live):** n 11 222; late 30.3%; changes 41.6%; delay sum 264 971 d (→ „265 tys.”); delay if late P50/P90
58/190 d; cost P90 +6.9%; paid above 21.6%; value 20.88 bn; paid 21.37 bn; overpaid 586 mln zł. Ranges: late
29.5–31.0; changes 40.5–42.5; delay sum 255–275 k; P50 55–61; P90 180–196; cost P90 6.5–7.3; overpaid 560–610 mln.

Chip answers (Main, A6), same engine: design-build late **45.2%** (n = 1 446) vs build-only **28.1%** (n = 9 776),
the gap holds in every value bucket (+4 to +19 pp) (mockup: 47% vs 28%, n 1 390 / 9 794); unit cost SAN 0.86,
WOD 0.39 mln zł/km (§3.3); late by woj: lubuskie 43.4, dolnośląskie 40.2, kujawsko-pomorskie 23.4.

#### 3.10.2 Tiles

„Czeka na Twoją decyzję” = open `review_item` count by kind; „Nowe sygnały w monitoringu” = red radar rows whose
latest notice was published in the last 7 days; „Twoje analizy” = `analysis` count by status. All read-only.

#### 3.10.3 Zapytaj pamięć: views a NL→SQL model may see

The model sees only these views (schema + column comments in Polish, used as the prompt). All live in schema
`ask`, owned by the migration; a role `riskminer_ask` has `USAGE` on `ask` and `SELECT` on its views only.

| view | columns | excluded on purpose |
|---|---|---|
| `ask.contracts` (from `an_contract` + `ref_teryt` names) | performance_id, ocid, cp_bzp_number, url, title, buyer_name, buyer_nip, woj_name, powiat_name, gmina_name, terc7, subsector, design_build, work_type, eu_funded, contract_year, completion_year, value_gross, value_bucket, paid_gross, planned_days, actual_days, late, delay_days, cost_dev_pct, changes_count, cause_codes, properly_performed, time_ok, cost_ok, length_km, n_offers | contractor name and NIP (sole traders are natural persons, invariant 9), raw JSON, HTML |
| `ask.changes` (from `contract_change`) | change_id, performance_id, ocid, kind, changed_on, legal_basis, change_types, delta_days, delta_value_amount, price_increase, cause_text (first 500 chars), cause_codes | description beyond 500 chars |
| `ask.tenders` (from `lot` + `procedure`) | ocid, lot_no, year, subsector, estimate_net, n_offers, cancelled, cancel_basis, min/max/winning offer | cancel_reason free text |
| `ask.areas` (`mv_monitor_area` with names) | level, terc, name, n, late_share, delay_med_if_late, overpaid_pct, change_share, improper_share | |
| `ask.radar` (`mv_radar` with names) | ocid, title, buyer_name, woj_name, gmina_name, planned_end_on, days_past_end, status, n_change_notices | |
| `ask.projects` (22 pilots, approved/edited facts only) | rm_id, title, beneficiary_name, subsector, value, delay_days, cost_pct, status | AI facts still `proposed` |

Execution guard (`api/routers/ask.py`):
1. Accept exactly one statement starting with `SELECT` or `WITH`; reject `;` inside, comments, and any of
   `INSERT|UPDATE|DELETE|COPY|CALL|DO|SET|pg_|lo_|dblink`.
2. `EXPLAIN (FORMAT JSON)` it under the `riskminer_ask` role; walk the plan and require every `Relation Name` to
   be in the `ask` schema whitelist (this also catches functions that touch other tables).
3. Execute as `SET LOCAL ROLE riskminer_ask; SET LOCAL statement_timeout = '3s';
   SET LOCAL default_transaction_read_only = on;` wrapped as `SELECT * FROM (<sql>) q LIMIT 1000`.
4. Return rows + the SQL + `n`; the answer sentence is a template filled from the result where possible; when the
   LLM writes the sentence it is labelled „wniosek AI”. Save as `analysis(kind='question')` → `Q-2026-NNNN`.

Golden: as `riskminer_ask`, `SELECT 1 FROM notice` fails; `SELECT contractor_name FROM ask.contracts` fails;
`EXPLAIN` guard rejects `SELECT * FROM ask.contracts, pg_catalog.pg_user`; „Ile umów w wielkopolskim skończyło się
po terminie?” → 35.3% of 998 (mockup: 35% of 995).

### 3.11 Red flags that can be code predicates

Inputs: F = analysis features (chips), RC = reference class stats, DOC = uploaded document pages with
`doc_type` and evidence states (`evidence_states.yaml`), CAT = catalogue patterns (`risks.yaml → signals`).

| flag | predicate | inputs | kind |
|---|---|---|---|
| **F6** czas krótszy niż u 75% podobnych | `F.plan_days < RC.planned_p25` (demo: 426 < 452.5 → fires); the A2 text uses the median („14 mies. wobec mediany 18 mies.”), so show both numbers | F, RC | **code** |
| **F5** termin a dofinansowanie | `deadline − (expected_sign + plan_days) < 60 d`; probabilistic version = §3.5.5 | F, funding_programmes.yaml | **code** |
| **F12** ZiW + decyzje + termin < 12 mies. | `F.design_build AND F.plan_months < 12 AND (subsector ∈ {SAN, OCZ, SUW, DESZ} OR R04 pattern in DOC)` | F, DOC | **code** (+ regex) |
| **F14** zimowe roboty ziemne bez rezerwy | planned works window covers Dec–Feb AND `plan_days < RC.planned_p50` | F (dates), RC | **code** |
| **F9** kosztorys nieaktualny | `estimate_date < analysis_date − 6 mies.` AND GUS index change since then > 5% | F, price index | **code** (needs estimate date chip) |
| **F3** sieć ≥ 1 km bez decyzji środowiskowej | `F.length_km ≥ 1` AND state(DŚU) ∈ {BRAK_W_PACZCE, DOKUMENT_NIE_WSPOMINA} | F, DOC states | **code** (+ doc state) |
| **F7** > 6 mies. bez waloryzacji | `plan_days > 182` AND PPU present AND no match of `waloryzac|art\.?\s*439|zmian\w* wynagrodzenia[^.]{0,80}cen` (state DOKUMENT_NIE_WSPOMINA); if PPU missing → BRAK_W_PACZCE | F, DOC | **code + regex** |
| **F8** ryczałt przy ilościach orientacyjnych | `ryczałt\w*` in PPU/SWZ AND R01.2 patterns (`ok\.\s?\d`, `około \d+ ?(m|mb|km)`, `wartości (są )?orientacyjne`) in PFU | DOC, CAT | **code + regex** |
| **F1** brak badań geotechnicznych | state(GEOTECH) ∈ {BRAK_W_PACZCE, DOKUMENT_NIE_WSPOMINA} AND R02.1 patterns in PFU (`wod\w* gruntow`, `badani\w* (podłoża|geotechn)` absent, `po stronie wykonawcy`) | DOC, CAT | **code + regex** |
| **F2** grunty prywatne bez prawa do dysponowania | R03.2 patterns (`działk\w* prywatn`, `służebnoś`, `właściciel`) AND state(zgody) ≠ POTWIERDZONO | DOC, CAT | **code + regex** |
| **F4** przekroczenia cieków, dróg, kolei | R03.3 patterns (`przekrocz\w* (rzek|ciek|rów)`, `drog\w* (krajow|wojewódzk)`, `DK ?\d`, `PKP|kolej`, `przewiert`) | DOC, CAT | **regex** |
| **F10** bez przyłączy i programu przyłączeń | scope has no `przyłącz|sięgacz|przykanalik` AND no `program\w* przyłącz` | F, DOC | **regex** |
| **F11** efekt zależny od innego zadania | R18 patterns (`oczyszczal\w* .* (innego|odrębn)`, `kolektor\w* (innego|gminy)`) | DOC | **regex** (weak) |
| **F13** brak mierzalnych parametrów (OŚ/SUW) | subsector ∈ {OCZ, SUW} AND no `RLM|m3/d|m³/d|BZT5|ChZT|azot|fosfor|żelaz|mangan` with a number | F, DOC | regex weak; **LLM** preferred |
| **F15** klauzule ryzykowne (art. 433) | needs reading of PPU clauses | DOC | **LLM only** |

Code flags are `CALC` (`origin CALC`, inputs listed, rule id and version, `review_status auto`); regex flags are
`CALC` with the matched quote and page as evidence (page text verified by construction); LLM flags are `AI`,
`proposed`, with a verified quote. Tonight: F6, F5, F12, F14 (no documents needed) and F7/F8 once page text of the
demo PFU/PPU is in `document_page`.

---

## 4. New catalogue files (sector pack, expert assumptions)

All three are loaded by `ingest/catalogue.py` into `catalogue_entry` (`table_name` = file stem, one entry per
code) so the Katalog screen can edit them; analytics reads the DB copy, falling back to YAML. Every value is
`status: proposed` until an expert approves it, and every number derived from them carries the label „założenie
eksperta”.

### 4.1 `catalogue/wod-kan/mitigations.yaml`

```yaml
schema_version: 1
sector: wod-kan
defaults:
  offers_decay: 0.85            # P'(>=N) = 1 - (1 - P(>=N)) * decay^shift
  cancel_floor_pct: 4
  materials_share: 0.5          # what-if "ceny +10%"
mitigations:
- code: M-GEO
  short: Badania gruntu
  label: Badania gruntu przed przetargiem
  description: Dokumentacja geotechniczna jako załącznik do SWZ.
  metrics: [time, cost, comp]
  effects:                      # p_keep: probability the event still happens; time_cut/cost_cut: share of its impact removed if it does
  - {risk: R02, p_keep: 0.5, time_cut: 0.4, cost_cut: 0.4}
  competition: {offers_shift: 0.3, cancel_pp: -1}
  clause_refs: [R02.1-K1]
  rationale: Wykonawca nie wycenia ryzyka gruntu w ciemno; mniej robót dodatkowych z powodu warunków gruntowo-wodnych.
  status: proposed
- code: M-PLAN18
  short: Plan 18 mies.
  label: Termin 18 miesięcy zamiast 14
  description: Tyle wynosi mediana planowanych terminów w tej grupie.
  metrics: [time, cost, comp]
  plan: {set: class_median}     # overrides D; programme deadline stays fixed
  effects:
  - {risk: R06, p_keep: 0.5, time_cut: 0.0, cost_cut: 0.0}
  competition: {offers_shift: 0.6, cancel_pp: -1}
  status: proposed
- code: M-K07
  short: Waloryzacja
  label: Klauzula waloryzacyjna K-07
  description: Art. 439 Pzp, próg 5%, limit 10%.
  metrics: [cost, comp]
  effects:
  - {risk: N-PRICE, p_keep: 1.0, time_cut: 0.0, cost_cut: 0.5}
  - {risk: R13, p_keep: 1.0, time_cut: 0.0, cost_cut: 0.5}
  price_pass_through: {threshold_pct: 5, cap_pct: 10}
  competition: {offers_shift: 1.0, cancel_pp: -2}
  clause_refs: [R08.1-K1]
  status: proposed
- code: M-R08
  short: Cena za metr
  label: Cena za metr sieci ponad 6 km
  description: Ryczałt do 6,0 km, dalej cena jednostkowa z oferty.
  metrics: [cost, comp]
  effects:
  - {risk: R08, p_keep: 1.0, time_cut: 0.0, cost_cut: 0.6}
  - {risk: R01, p_keep: 1.0, time_cut: 0.0, cost_cut: 0.3}
  competition: {offers_shift: 0.4, cancel_pp: -1}
  clause_refs: [R01.2-K1]
  status: proposed
```

### 4.2 `catalogue/wod-kan/funding_programmes.yaml`

```yaml
schema_version: 1
programmes:
- code: KPO_B311
  name: KPO, inwestycja B3.1.1 (infrastruktura wodno-kanalizacyjna)
  family: EU
  deadlines:
  - kind: indicators_achieved
    date: 2026-08-31
    source: "Rozporządzenie (UE) 2021/241; MFiPR, odpowiedź na interpelację 16654 (15.05.2026), 03 §1.7"
  buffer_days: 60               # F5 threshold
  status: approved
- code: FENIKS
  name: FEnIKS 2021–2027
  family: EU
  deadlines:
  - kind: eligibility_end
    date: 2029-12-31
    source: "Rozporządzenie (UE) 2021/1060, art. 63 ust. 2; termin z umowy o dofinansowanie ma pierwszeństwo"
  buffer_days: 60
  status: proposed              # confirm against the call / funding agreement
- code: FEP_RPO
  name: Fundusze Europejskie dla województwa (2021–2027)
  family: EU
  deadlines: [{kind: eligibility_end, date: 2029-12-31, source: "jw."}]
  status: proposed
- code: PROW
  name: PROW 2014–2020
  family: EU
  deadlines: []                 # closed; keep for similarity family only
  status: proposed
- code: RFIL_PIS
  name: Rządowe programy (RFIL, Polski Ład / PIS)
  family: national
  deadlines: []
  status: proposed
- code: OWN
  name: Środki własne
  family: own
  deadlines: []
  status: approved
```

The analysis chip „finansowanie” stores the code and an optional **agreement deadline** that overrides the
programme default (the mockup's 31.08.2028 was demo-only). With no deadline, Q3 shows „brak terminu programu”.

### 4.3 `catalogue/wod-kan/allocation.yaml`

```yaml
schema_version: 1
defaults:
  delay_cost_rate_per_month: 0.005        # share of contract value per month of delay
  premium: {shared: 0.10, contractor_uncontrolled: 0.60, contractor_controlled: 0.10}
risks:
- code: R02
  label: Nierozpoznany grunt
  controllability: buyer                  # buyer | shared | contractor
  recommended: buyer
  how:
    buyer: badania geotechniczne przed ogłoszeniem; reszta wg protokołu konieczności
    shared: badania przed ogłoszeniem, nadwyżka ponad raport dzielona po połowie
    contractor: wykonawca bada grunt po umowie, w ryczałcie
  clause_refs: [R02.1-K1]
  status: proposed
- code: R03   # Służebności na trasie: buyer / buyer
- code: R04   # Decyzje organów: shared / shared (K-12)
- code: R06   # Zbyt krótki termin: shared / shared
- code: R08   # Długość sieci „ok. 6 km”: buyer / shared
- code: R13   # Wzrost cen materiałów: shared / shared (K-07)
```

(The six demo risks take their how-texts verbatim from `A5-Podzial.dc.html`.)

---

## 5. Endpoints owned by analytics

Per `docs/flow1_build_plan.md` §2 (publish the response schemas first so the frontend can mock them):

| endpoint | returns | notes |
|---|---|---|
| `POST /api/analyses` | `AN-2026-NNNN`, features, reference class, report | runs §3.1–3.4 + code flags, writes `analysis` + `analysis_item` + `audit_log`; LLM chip extraction is the L session's |
| `PATCH /api/analyses/{id}/features` | re-run | new version in `analysis.results.versions[]` |
| `GET /api/analyses/{id}` | funnel, Q1–Q3, shares, flags, similar cases, clauses, limits, summary | |
| `POST /api/analyses/{id}/simulate` | §3.5 | stateless, cached by params hash |
| `GET|PUT /api/analyses/{id}/allocation` | §3.7 | |
| `GET /api/analytics/headline` | §3.10.1 | Pulpit + pitch numbers |
| `GET /api/analytics/tenders?subsector=&years=` | §3.6 | |
| `GET /api/analytics/unit-cost?subsector=&ppk=` | §3.3 | |
| `GET /api/analytics/backtest` | §3.8 | |
| `GET /api/monitoring/areas?level=&woj=&pow=&metric=` | §3.9.2 | |
| `GET /api/monitoring/radar?woj=&pow=&status=` (+ `.csv`) | §3.9.3 | |
| `POST /api/ask` | §3.10.3 | |

`analysis_item.section` values: `funnel`, `q_time`, `q_cost`, `q_deadline`, `shares`, `flag`, `similar`,
`clause`, `limit`, `summary`, `simulation`, `allocation`.

---

## 6. Golden tests (pytest)

`backend/tests/test_analytics_*.py`. Tests marked `@pytest.mark.db` need the live DB and skip otherwise; ranges
leave room for the live BZP delta.

| # | test | asserts |
|---|---|---|
| 1 | `test_base_population` | n 11 150–11 450; time_ok share 0.95–0.98; cost_ok 0.98–1.0; no `completed_on > cp_published_on` among time_ok |
| 2 | `test_headline` | §3.10.1 ranges |
| 3 | `test_funnel_demo` | 11 222 → 4 287 → 373 → 82 within §3.1 ranges; chosen level = formula level (n ≥ 50) |
| 4 | `test_demo_class_stats` | late 0.60–0.67; changes 0.73–0.80; delay P50 55–75, P80 135–155, P90 165–190; cost P80 3.5–4.8, P90 9.5–12.5; planned median 530–560 |
| 5 | `test_widening` | DESZ + ZiW + 5–10 mln widens; label says which filter was dropped |
| 6 | `test_tiers` (no DB) | n 8 → insufficient, 25 → low, 40 → medium, 80 → high; P90 hidden below 50 |
| 7 | `test_wilson_bootstrap` (no DB) | Wilson(3, 9) 90% ≈ 0.14–0.60 (03 §4.3); bootstrap reproducible with seed |
| 8 | `test_forecast_demo_14m` | §3.2.7 ranges |
| 9 | `test_lengths_regex` (no DB) | the seven cases in §3.3 |
| 10 | `test_length_coverage` | SAN 0.46–0.53, WOD 0.51–0.58, all 0.41–0.47 |
| 11 | `test_unit_cost_san` | §3.3 ranges; percentile of 1.1667 = 62–68 |
| 12 | `test_similarity_properties` (no DB) | identity = 1.0; Σc_i = S; coverage; monotone in value ratio |
| 13 | `test_similarity_demo` | Bestwina top 3 among pilots, S ≥ 0.65; Steklin < Bestwina |
| 14 | `test_mc_perf` | one run < 50 ms; full simulate < 500 ms |
| 15 | `test_mc_demo` | §3.5.7 |
| 16 | `test_mitigation_monotone` | every toggle and every pair: no worse T80, C90, P(≥2) |
| 17 | `test_tender_by_year` | §3.6 table ±1.5 pp |
| 18 | `test_competition_demo` | P(≥2) 0.93–0.98; median 5–7 |
| 19 | `test_allocation_mockup_math` (no DB) | 555 / 505 / 201, off = 1 |
| 20 | `test_backtest` | §3.8 ranges; Brier class < global |
| 21 | `test_monitoring_woj` | PL02 39.5–41.5% / 60–66 d; PL04 22.5–24.5%; PL08 42–45% |
| 22 | `test_radar_counts` | §3.9.3 ranges; ≥ 3 of the 5 mockup alerts are red |
| 23 | `test_teryt_pilots` | 22 pilot buyers → expected terc7; coverage ≥ 0.95 of core contracts |
| 24 | `test_ask_guard` | §3.10.3 rejections; read-only role |
| 25 | `test_flags_demo` | F6 fires for 14 mies.; F12 not; F5 fires with deadline < plan end + 60 d |
| 26 | `test_provenance_envelope` | every Stat in a report has origin, n, method, source.data_version; AI items are `proposed` |

---

## 7. Work plan (analytics session, start about 20:00)

Flow 1 first. Hours are for one session working in the order below.

| # | block | h | depends on |
|---|---|---|---|
| A0 | numpy dep; migration: `contract_metric`, `an_buyer_teryt` (empty), `an_contract`, `an_meta`; `CaseBase` loader; `Stat` envelope; config keys | 0.6 | – |
| A1 | `stats.py` (weighted quantiles, Kish, Wilson, bootstrap) + `refclass.py` funnel and widening + tests 3–7 | 0.8 | A0 |
| A2 | `forecast.py` time ratio model, cost, shares, Q3 with `funding_programmes.yaml` (KPO + FEnIKS), summary template + tests 4, 8 | 1.0 | A1 |
| A3 | `parsing/lengths.py` port, `contract_metric` fill (CLI), `unit_cost.py` + tests 9–11 | 0.7 | A0 |
| A4 | `POST/GET /analyses` minimal (features in JSON, no LLM), items for funnel/Q1/Q2/Q3/shares/summary/limits; `GET /analytics/headline`; flags F6, F5, F12, F14 | 0.9 | A2, A3 |
| **00:00 cut** | **1.1 → 1.2 on real numbers: funnel, Q1–Q3, shares, summary, limits, code flags, headline** | **4.0** | |
| A5 | similarity: structured features (0.6 h), BM25 text index (0.4 h), explanations, pilots pool + tests 12–13 | 1.2 | A0 |
| A6 | `simulate.py` + `mitigations.yaml` + what-ifs + tornado + per-risk + tests 14–16 | 2.0 | A2 |
| A7 | `competition.py` tender stats + curve + test 17–18 | 0.5 | A0 |
| A8 | `allocation.py` + `allocation.yaml` + GET/PUT + test 19 | 0.8 | A6 |
| A9 | `teryt.py` + `mv_monitor_area` + `mv_radar` + monitoring endpoints + tests 21–23 | 1.5 | A0 |
| A10 | ask views, role, guard, `POST /ask` executor (the L session writes NL→SQL) + test 24 | 1.0 | A9 |
| A11 | backtest endpoint + test 20 | 0.4 | A1 |
| A12 | hurdle model (optional) | 1.0 | A2 |
| | **total after the cut** | **8.4** (7.4 without A12) | |

Suggested clock: 20:00–00:00 A0–A4; 00:00–01:15 A5; 01:15–03:15 A6; 03:15–04:00 A7 + A11; 04:00–04:50 A8;
04:50–06:20 A9; 06:20–07:00 A10 (or hand A9/A10 to the data session if it is free after 00:00). Freeze 07:00.
If time runs short, cut in this order: A12, A10 (Zapytaj pamięć keeps canned answers from `headline`), A9 gmina
level (keep woj from `mv_monitor_area` and the radar list), A8 to the mockup's math over engine `e_r`.

**Minimum by 00:00:** A0–A4. The 1.2 report then shows real funnel, Q1 (P(on time), band, median, CI), Q2 (unit
cost and percentile), Q3 (programme deadline), shares with Wilson intervals, the summary sentence, limitations
and four code flags, all with origin/n/source. Similar cases and the clause list come right after (A5).

---

## 8. Decisions and blockers

1. **Add numpy** to `backend/pyproject.toml` (BSD-3). No pandas in the API.
2. **Use live numbers in the UI** (§0.1); the frontend's mock layer must be replaced endpoint by endpoint; do not
   hard-code 84 / 69 / 11.8% anywhere. Fix the Janów mockup value (declared on time).
3. **Base population filter** is fixed: `sector = 'wod-kan' AND relevance IN ('core','cpv_only') AND
   scope_kind = 'works'` (11 222). The roads slice stays out of every statistic.
4. **Who adds `length_km`**: the flow1 plan gives it to the data session; this plan puts it in `contract_metric`
   owned by analytics so neither `derive.py` nor `rc_contract` changes. Agree before 20:30 to avoid two migrations.
5. **One line in `derive.py`** (data session): `REFRESH MATERIALIZED VIEW an_contract` after `rc_contract`, or the
   analytics CLI does it in `load-all`'s report step.
6. **Expert assumptions**: someone signs off the 4 mitigations, 6 allocation rows and funding dates; until then
   they show „założenie eksperta, do zatwierdzenia”.
7. **Demo honesty**: mitigation and allocation numbers will be smaller than in the mockups (§3.5.8, §3.7). Say it
   on stage as a feature: „liczymy tylko to, co widać w danych”.
8. **LLM cause codes**: when the L session writes `cause_codes_ai`, extend the `rc_contract` `cc` CTE (or
   `an_contract`) to prefer them; per-risk P(r) and the tornado improve without engine changes.
