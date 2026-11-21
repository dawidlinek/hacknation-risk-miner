"""data/geo: network lengths, buyer TERYT centroids, rc_contract with location + data-quality flags, monitoring signals

Revision ID: 0010_data_geo
Revises: 0006
Branch: data (parallel build; the lead merges heads at freeze)

- procedure/lot: length_km, conn_km, length_method (filled by ingest/lengths.py, `riskminer derive-lengths`)
- contract_change: is_duplicate, duplicate_of_id (a change notice that repeats a change listed in the performance
  notice; filled by ingest/quality.py)
- ref_geo_centroid(terc, level, lon, lat) (filled by ingest/geo.py from data/ref/geo/*.geojson)
- organization.teryt is filled by ingest/geo.py (`riskminer geo-buyers`), method in organization.data->>'teryt_method'
- rc_contract recreated: + length_km, unit_cost_pln_per_km, buyer_terc, buyer_woj, dq_flags, dq_ok; rows with
  impossible dates keep their facts but get late/delay NULL so they drop out of statistics (flagged, not fixed)
- monitor_signals(as_of date): ongoing core water/sewage contracts past their planned end without a performance
  notice as of a date (replay); v_monitor_signal = monitor_signals(current_date)
"""
from alembic import op

revision = "0010_data_geo"
down_revision = "0006"
branch_labels = ("data",)
depends_on = None

RC = """
CREATE MATERIALIZED VIEW rc_contract AS
WITH ch AS (
  SELECT contract_id,
         array_agg(DISTINCT b) FILTER (WHERE b IS NOT NULL) AS legal_bases,
         count(*) AS change_rows
  FROM contract_change LEFT JOIN LATERAL unnest(legal_basis) b ON true
  WHERE contract_id IS NOT NULL AND NOT is_duplicate AND kind IN ('change_notice', 'performance_block')
  GROUP BY contract_id),
cc AS (
  SELECT contract_id, array_agg(DISTINCT k) AS cause_codes
  FROM contract_change, unnest(cause_codes_kw) k WHERE contract_id IS NOT NULL AND NOT is_duplicate
    AND kind IN ('change_notice', 'performance_block') GROUP BY contract_id),
base AS (
  SELECT pf.id AS performance_id, c.id AS contract_id, p.id AS procedure_id, p.ocid,
         p.sector, p.subsector_main, p.subsectors, p.relevance, p.scope_kind, p.work_type, p.design_build,
         p.province, p.buyer_nip, p.eu_funded, p.below_eu, p.cpv_main,
         coalesce(pf.signed_on, c.signed_on) AS signed_on,
         pf.completed_on,
         coalesce(pf.contract_value_amount, c.value_amount) AS value_gross,
         pf.total_paid_amount AS paid_gross,
         coalesce(pf.planned_days, c.planned_duration_days) AS planned_days,
         coalesce(pf.planned_end_on, c.planned_end_on) AS planned_end_on,
         pf.actual_days, pf.on_time_declared, pf.delay_days AS delay_days_computed, pf.cost_dev_pct,
         pf.changes_count, pf.properly_performed, pf.executed,
         CASE WHEN coalesce(c.lot_no, 0) > 0 AND l.length_km IS NOT NULL THEN l.length_km
              WHEN coalesce(p.n_lots, 1) <= 1 THEN p.length_km END AS length_km,
         o.teryt AS buyer_terc,
         coalesce(left(o.teryt, 2), substr(p.province, 3, 2)) AS buyer_woj,
         array_remove(ARRAY[
           CASE WHEN coalesce(pf.planned_end_on, c.planned_end_on) < coalesce(pf.signed_on, c.signed_on)
                THEN 'planned_end_before_signed' END,
           CASE WHEN coalesce(pf.planned_days, c.planned_duration_days) <= 0 THEN 'planned_days_nonpositive' END,
           CASE WHEN pf.actual_days < 0 THEN 'actual_days_negative' END], NULL) AS dq_flags
  FROM contract_performance pf
  JOIN procedure p ON p.id = pf.procedure_id
  LEFT JOIN contract c ON c.id = pf.contract_id
  LEFT JOIN lot l ON l.id = c.lot_id
  LEFT JOIN organization o ON o.id = p.buyer_org_id
  WHERE NOT pf.is_duplicate AND pf.executed IS NOT FALSE)
SELECT b.performance_id, b.contract_id, b.procedure_id, b.ocid,
       b.sector, b.subsector_main, b.subsectors, b.relevance, b.scope_kind, b.work_type, b.design_build,
       b.province, b.buyer_nip, b.eu_funded, b.below_eu, b.cpv_main,
       b.signed_on, extract(year FROM b.signed_on)::int AS contract_year,
       b.completed_on, extract(year FROM b.completed_on)::int AS completion_year,
       b.value_gross,
       CASE WHEN b.value_gross < 500000 THEN '<0.5m'
            WHEN b.value_gross < 1000000 THEN '0.5-1m'
            WHEN b.value_gross < 2000000 THEN '1-2m'
            WHEN b.value_gross < 5000000 THEN '2-5m'
            WHEN b.value_gross < 10000000 THEN '5-10m'
            WHEN b.value_gross IS NOT NULL THEN '>10m' END AS value_bucket,
       b.paid_gross,
       CASE WHEN cardinality(b.dq_flags) = 0 THEN b.planned_days END AS planned_days,
       b.planned_end_on,
       CASE WHEN cardinality(b.dq_flags) = 0 THEN b.actual_days END AS actual_days,
       b.on_time_declared,
       CASE WHEN cardinality(b.dq_flags) = 0 THEN (b.on_time_declared IS FALSE) END AS late,
       CASE WHEN cardinality(b.dq_flags) > 0 THEN NULL
            WHEN b.on_time_declared IS TRUE THEN 0
            WHEN b.on_time_declared IS FALSE AND b.delay_days_computed > 0 THEN b.delay_days_computed END AS delay_days,
       b.delay_days_computed,
       b.cost_dev_pct,
       b.changes_count,
       coalesce(ch.legal_bases, '{}') AS legal_bases,
       coalesce(cc.cause_codes, '{}') AS cause_codes,
       b.properly_performed, b.executed,
       b.length_km,
       CASE WHEN b.length_km >= 0.1 AND b.value_gross > 0 THEN round(b.value_gross / b.length_km, 2) END AS unit_cost_pln_per_km,
       b.buyer_terc, b.buyer_woj,
       b.dq_flags, cardinality(b.dq_flags) = 0 AS dq_ok
FROM base b
LEFT JOIN ch ON ch.contract_id = b.contract_id
LEFT JOIN cc ON cc.contract_id = b.contract_id
"""

SIGNALS = """
CREATE OR REPLACE FUNCTION monitor_signals(as_of date)
RETURNS TABLE (
  contract_id bigint, procedure_id bigint, ocid text, bzp_number text, result_notice_url text, lot_no int, n_parts int,
  buyer_org_id bigint, buyer_nip text, buyer_name text, title text, subsector_main text,
  value_amount numeric, value_currency text, value_vat text, contractor_name text,
  signed_on date, planned_end_on date, planned_end_computed boolean, days_overdue int, n_change_notices int,
  last_change_on date, has_performance boolean,
  woj text, pow text, gmi text, buyer_terc text, lon double precision, lat double precision, location_method text,
  watched boolean
) LANGUAGE sql STABLE AS $$
  SELECT c.id, p.id, p.ocid::text, c.result_notice_no::text, rn.url, coalesce(c.lot_no, 0), coalesce(p.n_lots, 1),
         p.buyer_org_id, p.buyer_nip::text, coalesce(o.name, p.buyer_name), p.title, p.subsector_main::text,
         c.value_amount, c.value_currency::text, c.value_vat::text, c.contractor_name,
         c.signed_on, c.planned_end_on, c.planned_end_computed, (as_of - c.planned_end_on)::int,
         coalesce(chg.n, 0)::int, chg.last_on, false,
         coalesce(left(o.teryt, 2), substr(p.province, 3, 2)),
         CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END,
         CASE WHEN length(o.teryt) = 7 THEN o.teryt END,
         o.teryt::text,
         coalesce(gc.lon, pc.lon), coalesce(gc.lat, pc.lat),
         CASE WHEN gc.lon IS NOT NULL THEN coalesce(o.data->>'teryt_method', 'teryt') || '|gmina'
              WHEN pc.lon IS NOT NULL THEN coalesce(o.data->>'teryt_method', 'teryt') || '|powiat' END,
         EXISTS (SELECT 1 FROM monitor_watch w WHERE w.contract_id = c.id AND w.active)
  FROM contract c
  JOIN procedure p ON p.id = c.procedure_id
  LEFT JOIN lot l ON l.id = c.lot_id
  LEFT JOIN notice rn ON rn.id = c.result_notice_id
  LEFT JOIN organization o ON o.id = p.buyer_org_id
  LEFT JOIN ref_geo_centroid gc ON gc.terc = CASE WHEN length(o.teryt) = 7 THEN o.teryt END
  LEFT JOIN ref_geo_centroid pc ON pc.terc = CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END
  LEFT JOIN LATERAL (
    SELECT count(*) AS n, max(ch.changed_on) AS last_on
    FROM contract_change ch JOIN notice n ON n.id = ch.notice_id
    WHERE ch.contract_id = c.id AND ch.kind = 'change_notice' AND n.published_at::date <= as_of) chg ON true
  WHERE p.sector = 'wod-kan' AND p.relevance = 'core' AND p.scope_kind = 'works'
    AND c.terms_source = 'result_notice'
    AND c.planned_end_on IS NOT NULL AND c.planned_end_on < as_of
    AND c.signed_on IS NOT NULL AND c.signed_on <= as_of AND c.planned_end_on >= c.signed_on
    AND (rn.published_at IS NULL OR rn.published_at::date <= as_of)
    AND NOT coalesce(l.cancelled, false)
    AND NOT EXISTS (
      SELECT 1 FROM contract_performance pf
      JOIN notice pn ON pn.id = pf.notice_id
      LEFT JOIN contract c2 ON c2.id = pf.contract_id
      WHERE pf.procedure_id = c.procedure_id AND NOT pf.is_duplicate AND pn.published_at::date <= as_of
        AND (pf.contract_id = c.id
             OR (c2.terms_source <> 'result_notice'
                 AND (c2.contractor_nip = c.contractor_nip OR coalesce(c2.lot_no, 0) = coalesce(c.lot_no, 0)))))
$$
"""
SIGNALS_VIEW = "CREATE OR REPLACE VIEW v_monitor_signal AS SELECT * FROM monitor_signals(current_date)"


def upgrade() -> None:
    op.execute("ALTER TABLE procedure ADD COLUMN IF NOT EXISTS length_km numeric(10,3), "
               "ADD COLUMN IF NOT EXISTS conn_km numeric(10,3), ADD COLUMN IF NOT EXISTS length_method text")
    op.execute("ALTER TABLE lot ADD COLUMN IF NOT EXISTS length_km numeric(10,3), ADD COLUMN IF NOT EXISTS conn_km numeric(10,3)")
    op.execute("ALTER TABLE contract_change ADD COLUMN IF NOT EXISTS is_duplicate boolean NOT NULL DEFAULT false, "
               "ADD COLUMN IF NOT EXISTS duplicate_of_id bigint REFERENCES contract_change(id) ON DELETE SET NULL")
    op.execute("""CREATE TABLE IF NOT EXISTS ref_geo_centroid (
                    terc varchar(7) PRIMARY KEY, level varchar(4) NOT NULL, name text,
                    lon double precision NOT NULL, lat double precision NOT NULL)""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_organization_teryt ON organization (teryt)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS rc_contract")
    op.execute(RC)
    op.execute("CREATE UNIQUE INDEX ix_rc_contract_perf ON rc_contract (performance_id)")
    op.execute("CREATE INDEX ix_rc_contract_class ON rc_contract (sector, subsector_main, value_bucket, design_build)")
    op.execute("CREATE INDEX ix_rc_contract_geo ON rc_contract (buyer_terc)")
    op.execute("CREATE INDEX ix_rc_contract_woj ON rc_contract (buyer_woj)")
    op.execute(SIGNALS)
    op.execute(SIGNALS_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_monitor_signal")
    op.execute("DROP FUNCTION IF EXISTS monitor_signals(date)")
