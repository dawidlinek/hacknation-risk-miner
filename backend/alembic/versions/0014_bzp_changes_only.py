"""statistics and ask views count BZP changes only (not document proposals)

Revision ID: 0014_bzp_changes_only
Revises: 0013_alerts
Branch: data

Session B now writes proposed contract_change rows with kind 'document_change' from uploaded documents (protocols,
letters). National statistics (rc_contract) and the NL->SQL change view must count only the published BZP changes
(kind change_notice | performance_block), so proposals never leak into the reference class. 0010 and 0011 carry the
filter for fresh databases; this revision rebuilds rc_contract (and v_ask_contract, which depends on it) and replaces
v_ask_change on databases that already ran them.
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "0014_bzp_changes_only"
down_revision = "0013_alerts"
branch_labels = None
depends_on = None


def _sibling(name: str):
    spec = importlib.util.spec_from_file_location(f"_rm_{name}", Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def upgrade() -> None:
    m10, m11 = _sibling("0010_data_geo"), _sibling("0011_ask_views")
    op.execute("DROP VIEW IF EXISTS v_ask_contract")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS rc_contract")
    op.execute(m10.RC)
    op.execute("CREATE UNIQUE INDEX ix_rc_contract_perf ON rc_contract (performance_id)")
    op.execute("CREATE INDEX ix_rc_contract_class ON rc_contract (sector, subsector_main, value_bucket, design_build)")
    op.execute("CREATE INDEX ix_rc_contract_geo ON rc_contract (buyer_terc)")
    op.execute("CREATE INDEX ix_rc_contract_woj ON rc_contract (buyer_woj)")
    for name, sql in m11.VIEWS.items():
        if name in ("v_ask_contract", "v_ask_change"):
            op.execute(f"DROP VIEW IF EXISTS {name}")
        op.execute(sql)
        op.execute(f"GRANT SELECT ON {name} TO riskminer_ro")


def downgrade() -> None:
    pass        # the filter is harmless to keep; earlier definitions are not restored
