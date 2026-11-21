"""performance duplicates + rc_contract materialized view (reference class)

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

RC = """
CREATE MATERIALIZED VIEW rc_contract AS
WITH ch AS (
  SELECT contract_id,
         array_agg(DISTINCT b) FILTER (WHERE b IS NOT NULL) AS legal_bases,
         count(*) AS change_rows
  FROM contract_change LEFT JOIN LATERAL unnest(legal_basis) b ON true
  WHERE contract_id IS NOT NULL GROUP BY contract_id),
cc AS (
  SELECT contract_id, array_agg(DISTINCT k) AS cause_codes
  FROM contract_change, unnest(cause_codes_kw) k WHERE contract_id IS NOT NULL GROUP BY contract_id)
SELECT pf.id AS performance_id, c.id AS contract_id, p.id AS procedure_id, p.ocid,
       p.subsector_main, p.subsectors, p.relevance, p.scope_kind, p.work_type, p.design_build,
       p.province, p.buyer_nip, p.eu_funded, p.below_eu, p.cpv_main,
       coalesce(pf.signed_on, c.signed_on) AS signed_on,
       extract(year FROM coalesce(pf.signed_on, c.signed_on))::int AS contract_year,
       pf.completed_on, extract(year FROM pf.completed_on)::int AS completion_year,
       coalesce(pf.contract_value_amount, c.value_amount) AS value_gross,
       CASE WHEN coalesce(pf.contract_value_amount, c.value_amount) < 500000 THEN '<0.5m'
            WHEN coalesce(pf.contract_value_amount, c.value_amount) < 1000000 THEN '0.5-1m'
            WHEN coalesce(pf.contract_value_amount, c.value_amount) < 2000000 THEN '1-2m'
            WHEN coalesce(pf.contract_value_amount, c.value_amount) < 5000000 THEN '2-5m'
            WHEN coalesce(pf.contract_value_amount, c.value_amount) < 10000000 THEN '5-10m'
            WHEN coalesce(pf.contract_value_amount, c.value_amount) IS NOT NULL THEN '>10m' END AS value_bucket,
       pf.total_paid_amount AS paid_gross,
       coalesce(pf.planned_days, c.planned_duration_days) AS planned_days,
       pf.actual_days,
       pf.on_time_declared,
       (pf.on_time_declared IS FALSE) AS late,
       CASE WHEN pf.on_time_declared IS TRUE THEN 0
            WHEN pf.on_time_declared IS FALSE AND pf.delay_days > 0 THEN pf.delay_days END AS delay_days,
       pf.delay_days AS delay_days_computed,
       pf.cost_dev_pct,
       pf.changes_count,
       coalesce(ch.legal_bases, '{}') AS legal_bases,
       coalesce(cc.cause_codes, '{}') AS cause_codes,
       pf.properly_performed, pf.executed
FROM contract_performance pf
JOIN procedure p ON p.id = pf.procedure_id
LEFT JOIN contract c ON c.id = pf.contract_id
LEFT JOIN ch ON ch.contract_id = pf.contract_id
LEFT JOIN cc ON cc.contract_id = pf.contract_id
WHERE NOT pf.is_duplicate AND pf.executed IS NOT FALSE
"""


def upgrade() -> None:
    op.execute("ALTER TABLE contract_performance ADD COLUMN is_duplicate boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE contract_performance ADD COLUMN duplicate_of_id bigint REFERENCES contract_performance(id) ON DELETE SET NULL")
    op.execute(RC)
    op.execute("CREATE UNIQUE INDEX ix_rc_contract_perf ON rc_contract (performance_id)")
    op.execute("CREATE INDEX ix_rc_contract_class ON rc_contract (subsector_main, value_bucket, design_build)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS rc_contract")
    op.execute("ALTER TABLE contract_performance DROP COLUMN duplicate_of_id, DROP COLUMN is_duplicate")
