"""widen contract_change array element types

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("legal_basis", "change_types", "cause_codes_kw"):
        op.execute(f"ALTER TABLE contract_change ALTER COLUMN {col} TYPE varchar(40)[]")


def downgrade() -> None:
    pass
