"""notice.source_locator -> text (live API pages are cited by raw file path)

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE notice ALTER COLUMN source_locator TYPE text")


def downgrade() -> None:
    pass
