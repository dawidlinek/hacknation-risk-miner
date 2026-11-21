"""ask views: whitelisted read-only views for NL->SQL (/api/ask) + role riskminer_ro

Revision ID: 0011_ask_views
Revises: 0010_data_geo
Branch: data

The /api/ask path (session L) runs generated SQL as: BEGIN READ ONLY; SET LOCAL ROLE riskminer_ro;
SET LOCAL statement_timeout = '3s'; ... LIMIT 1000. riskminer_ro can read only the v_ask_* views (views run with
the owner's rights on their tables; monitor_signals is SECURITY DEFINER for the same reason), nothing else.
Column names are English snake_case, labels for people are the *_name columns (Polish).

Scope is baked in: contract, change and procedure views hold core water/sewage rows only (sector 'wod-kan',
relevance 'core'), because generated SQL tends to forget that filter and rc_contract also holds roads and
non-core rows. `scope_kind` stays a column (works, maintenance, delivery...): `is_works` marks construction works,
the population the statistics and monitoring use. AI change causes come from session L's views
(v_change_cause_ai, v_contract_cause_ai in 0008_question): proposed until an expert approves them.
"""
from alembic import op

revision = "0011_ask_views"
down_revision = "0010_data_geo"
branch_labels = None
depends_on = "0008_question"          # v_change_cause_ai / v_contract_cause_ai (session L)

WOJ = "(SELECT terc, name FROM ref_teryt WHERE level = 'woj')"
SUB = "(SELECT code, name FROM catalogue_subsector WHERE sector = 'wod-kan' AND status = 'approved')"

VIEWS = {
    "v_ask_contract": f"""
CREATE OR REPLACE VIEW v_ask_contract AS
SELECT r.contract_id, r.ocid, p.title, coalesce(o.name, p.buyer_name) AS buyer_name, r.buyer_nip,
       r.buyer_woj AS woj, w.name AS woj_name, CASE WHEN length(r.buyer_terc) >= 4 THEN left(r.buyer_terc, 4) END AS powiat_terc,
       CASE WHEN length(r.buyer_terc) = 7 THEN r.buyer_terc END AS gmina_terc, g.name AS gmina_name,
       r.sector, r.subsector_main AS subsector, s.name AS subsector_name, r.relevance, r.scope_kind,
       r.work_type, r.design_build, r.eu_funded, r.below_eu, r.cpv_main,
       r.value_gross, r.paid_gross, r.value_bucket, r.signed_on, r.completed_on, r.contract_year, r.completion_year,
       r.planned_days, r.actual_days, r.late, r.delay_days, r.cost_dev_pct, r.changes_count, r.legal_bases, r.cause_codes,
       r.properly_performed, r.length_km, r.unit_cost_pln_per_km, r.dq_ok, (r.scope_kind = 'works') AS is_works,
       ca.cause_codes_ai, ca.any_approved AS cause_codes_ai_approved,
       (SELECT n.url FROM contract_performance pf JOIN notice n ON n.id = pf.notice_id
         WHERE pf.id = r.performance_id) AS performance_notice_url
FROM rc_contract r
JOIN procedure p ON p.id = r.procedure_id
LEFT JOIN organization o ON o.id = p.buyer_org_id
LEFT JOIN {WOJ} w ON w.terc = r.buyer_woj
LEFT JOIN ref_teryt g ON g.terc = r.buyer_terc AND g.level = 'gmi'
LEFT JOIN {SUB} s ON s.code = r.subsector_main
LEFT JOIN v_contract_cause_ai ca ON ca.contract_id = r.contract_id
WHERE r.sector = 'wod-kan' AND r.relevance = 'core'""",
    "v_ask_change": f"""
CREATE OR REPLACE VIEW v_ask_change AS
SELECT ch.id AS change_id, p.ocid, ch.contract_id, ch.kind, ch.changed_on, extract(year FROM ch.changed_on)::int AS change_year,
       ch.legal_basis, ch.change_types, ch.delta_days, ch.delta_value_amount, ch.delta_value_pct, ch.price_increase,
       ch.cause_text, ch.description_text, ch.cause_codes_kw AS cause_codes,
       p.title, coalesce(o.name, p.buyer_name) AS buyer_name, coalesce(left(o.teryt, 2), substr(p.province, 3, 2)) AS woj,
       w.name AS woj_name, p.sector, p.subsector_main AS subsector, s.name AS subsector_name, p.relevance, p.scope_kind,
       p.design_build, (p.scope_kind = 'works') AS is_works, n.notice_number, n.url AS notice_url,
       ai.primary_code AS cause_ai, ai.secondary_code AS cause_ai_secondary, ai.confidence AS cause_ai_confidence,
       ai.verification AS cause_ai_verification, ai.review_status AS cause_ai_review_status
FROM contract_change ch
JOIN procedure p ON p.id = ch.procedure_id
LEFT JOIN organization o ON o.id = p.buyer_org_id
LEFT JOIN notice n ON n.id = ch.notice_id
LEFT JOIN {WOJ} w ON w.terc = coalesce(left(o.teryt, 2), substr(p.province, 3, 2))
LEFT JOIN {SUB} s ON s.code = p.subsector_main
LEFT JOIN v_change_cause_ai ai ON ai.change_id = ch.id
WHERE NOT ch.is_duplicate AND ch.kind IN ('change_notice', 'performance_block') AND p.sector = 'wod-kan' AND p.relevance = 'core'""",
    "v_ask_signal": f"""
CREATE OR REPLACE VIEW v_ask_signal AS
SELECT s.contract_id, s.ocid, s.bzp_number, s.result_notice_url, s.lot_no, s.n_parts, s.buyer_nip, s.buyer_name, s.title,
       s.subsector_main AS subsector, sub.name AS subsector_name, s.value_amount, s.contractor_name, s.signed_on,
       s.planned_end_on, s.days_overdue, s.n_change_notices, s.last_change_on, s.woj, w.name AS woj_name,
       s.pow AS powiat_terc, s.gmi AS gmina_terc, s.lon, s.lat
FROM v_monitor_signal s
LEFT JOIN {WOJ} w ON w.terc = s.woj
LEFT JOIN {SUB} sub ON sub.code = s.subsector_main""",
    "v_ask_procedure": f"""
CREATE OR REPLACE VIEW v_ask_procedure AS
SELECT p.ocid, p.contract_notice_no, p.title, coalesce(o.name, p.buyer_name) AS buyer_name, p.buyer_nip,
       coalesce(left(o.teryt, 2), substr(p.province, 3, 2)) AS woj, w.name AS woj_name,
       p.sector, p.subsector_main AS subsector, s.name AS subsector_name, p.relevance, p.scope_kind, p.work_type,
       p.design_build, p.eu_funded, p.below_eu, p.estimated_value_amount AS estimated_value_net, p.n_lots,
       p.first_published_on, extract(year FROM p.first_published_on)::int AS year, p.cancelled, p.notice_types,
       p.length_km, (p.scope_kind = 'works') AS is_works, lt.n_offers_avg, lt.single_offer_lots, lt.cancelled_lots, lt.winning_offer_sum,
       (SELECT count(*) FROM contract c WHERE c.procedure_id = p.id) AS n_contracts,
       'https://ezamowienia.gov.pl/mo-client-board/bzp/list?searchNumber=' || replace(p.contract_notice_no, ' ', '%20') AS notice_search_url
FROM procedure p
LEFT JOIN organization o ON o.id = p.buyer_org_id
LEFT JOIN {WOJ} w ON w.terc = coalesce(left(o.teryt, 2), substr(p.province, 3, 2))
LEFT JOIN {SUB} s ON s.code = p.subsector_main
LEFT JOIN LATERAL (
  SELECT avg(l.n_offers) AS n_offers_avg, count(*) FILTER (WHERE l.n_offers = 1) AS single_offer_lots,
         count(*) FILTER (WHERE l.cancelled) AS cancelled_lots, sum(l.winning_offer_amount) AS winning_offer_sum
  FROM lot l WHERE l.procedure_id = p.id) lt ON true
WHERE p.sector = 'wod-kan' AND p.relevance = 'core'""",
}


def upgrade() -> None:
    op.execute("ALTER FUNCTION monitor_signals(date) SECURITY DEFINER SET search_path = public")
    for name in VIEWS:                       # DROP first: columns changed since the first version of this revision
        op.execute(f"DROP VIEW IF EXISTS {name}")
    for sql in VIEWS.values():
        op.execute(sql)
    op.execute("""DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'riskminer_ro') THEN
                      CREATE ROLE riskminer_ro NOLOGIN;
                    END IF;
                  END $$""")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM riskminer_ro")
    op.execute("GRANT USAGE ON SCHEMA public TO riskminer_ro")
    for name in VIEWS:
        op.execute(f"GRANT SELECT ON {name} TO riskminer_ro")
    op.execute("GRANT EXECUTE ON FUNCTION monitor_signals(date) TO riskminer_ro")
    op.execute("GRANT riskminer_ro TO CURRENT_USER")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
