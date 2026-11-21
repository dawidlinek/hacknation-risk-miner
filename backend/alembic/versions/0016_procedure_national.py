"""Materialized view `procedure_national`: one row per wod-kan procedure (relevance core/component) with plan vs actual,
delay, value and changes, for the national list on Projekty (GET /api/projects/national). Derived and rebuildable;
refreshed with rc_contract by the derive stage. Read-only for the API.

Revision ID: 0016_procedure_national
Revises: 0015_freeze
"""
from alembic import op

revision = "0016_procedure_national"
down_revision = "0015_freeze"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE MATERIALIZED VIEW procedure_national AS
    WITH c AS (
      SELECT procedure_id, count(*) n_contracts, min(signed_on) signed_on, max(planned_end_on) planned_end_on,
             sum(value_amount) value_amount, min(value_currency) value_currency,
             CASE WHEN count(DISTINCT value_vat) = 1 THEN min(value_vat) ELSE 'unknown' END value_vat,
             (array_agg(result_notice_no ORDER BY id) FILTER (WHERE result_notice_no IS NOT NULL))[1] result_notice_no
      FROM contract GROUP BY procedure_id
    ), pf AS (
      SELECT DISTINCT ON (pf.contract_id) pf.procedure_id, pf.contract_id, pf.completed_on, pf.delay_days, pf.changes_count,
             pf.contract_value_amount, n.notice_number, n.url
      FROM contract_performance pf LEFT JOIN notice n ON n.id = pf.notice_id
      WHERE NOT pf.is_duplicate AND pf.contract_id IS NOT NULL ORDER BY pf.contract_id, pf.id DESC
    ), pa AS (
      SELECT procedure_id, count(*) n_perf, max(completed_on) completed_on, max(delay_days) delay_days, sum(changes_count) changes_perf,
             (array_agg(notice_number ORDER BY delay_days DESC NULLS LAST))[1] perf_notice_no,
             (array_agg(url ORDER BY delay_days DESC NULLS LAST))[1] perf_notice_url
      FROM pf GROUP BY procedure_id
    ), ch AS (
      SELECT procedure_id, count(*) n FROM contract_change WHERE kind = 'change_notice' GROUP BY procedure_id
    )
    SELECT p.id procedure_id, p.ocid, p.title, p.relevance, p.scope_kind, coalesce(o.name, p.buyer_name) buyer_name,
           coalesce(left(o.teryt, 2), substr(p.province, 3, 2)) woj,
           CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END pow, CASE WHEN length(o.teryt) = 7 THEN o.teryt END gmi,
           gc.name gmina, pc.name powiat,
           c.n_contracts, c.signed_on, c.planned_end_on, c.value_amount, c.value_currency, c.value_vat, c.result_notice_no,
           coalesce(pa.n_perf, 0) n_perf, pa.completed_on, pa.delay_days, pa.perf_notice_no, pa.perf_notice_url,
           coalesce(pa.changes_perf, ch.n, 0)::int AS changes,
           CASE WHEN pa.n_perf > 0 THEN 'completed' WHEN c.n_contracts > 0 THEN 'ongoing' ELSE 'none' END AS status,
           extract(year FROM coalesce(c.signed_on, p.first_published_on))::int AS year,
           lower(coalesce(p.title, '') || ' ' || coalesce(o.name, p.buyer_name, '') || ' ' || coalesce(gc.name, '')) search_text
    FROM procedure p
    LEFT JOIN c ON c.procedure_id = p.id
    LEFT JOIN pa ON pa.procedure_id = p.id
    LEFT JOIN ch ON ch.procedure_id = p.id
    LEFT JOIN organization o ON o.id = p.buyer_org_id
    LEFT JOIN ref_geo_centroid gc ON gc.terc = CASE WHEN length(o.teryt) = 7 THEN o.teryt END
    LEFT JOIN ref_geo_centroid pc ON pc.terc = CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END
    WHERE p.sector = 'wod-kan' AND p.relevance IN ('core', 'component')
    """)
    op.execute("CREATE UNIQUE INDEX ix_procedure_national_ocid ON procedure_national (ocid)")
    op.execute("CREATE INDEX ix_procedure_national_rel_woj ON procedure_national (relevance, woj)")
    op.execute("CREATE INDEX ix_procedure_national_search ON procedure_national USING gin (search_text gin_trgm_ops)")
    op.execute("GRANT SELECT ON procedure_national TO PUBLIC")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS procedure_national")
