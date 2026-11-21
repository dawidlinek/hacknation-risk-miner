"""indexes on evidence.chunk_id / document_id (FK ON DELETE SET NULL scanned 860k rows per chunk delete)

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_chunk_id ON evidence (chunk_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_document_id ON evidence (document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_chunk_id")
    op.execute("DROP INDEX IF EXISTS ix_evidence_document_id")
