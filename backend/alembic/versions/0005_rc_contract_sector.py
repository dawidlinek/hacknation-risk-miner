"""rc_contract: add procedure.sector (roads slice for the W9 sector-pack demo lives in the same tables)

Revision ID: 0005
Revises: 0004
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _rc_sql() -> str:
    spec = importlib.util.spec_from_file_location("m0003", Path(__file__).with_name("0003_rc_contract.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.RC.replace("p.subsector_main, p.subsectors, p.relevance,", "p.sector, p.subsector_main, p.subsectors, p.relevance,")


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS rc_contract")
    op.execute(_rc_sql())
    op.execute("CREATE UNIQUE INDEX ix_rc_contract_perf ON rc_contract (performance_id)")
    op.execute("CREATE INDEX ix_rc_contract_class ON rc_contract (sector, subsector_main, value_bucket, design_build)")


def downgrade() -> None:
    pass
