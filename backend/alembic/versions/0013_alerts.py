"""alerts from new documents: link alert rows to contract / project / procedure / document

Revision ID: 0013_alerts
Revises: 0012_imports
Branch: data

new_documents.md G4: when a newly uploaded document changes an ongoing contract or project, the "Co się zmieniło"
diff (session B) raises a Monitoring alert through riskminer/monitoring/alerts.py. The `alert` table from 0001 only
pointed at a watch or a notice; this adds the targets, the triggering document, severity, provenance (origin CALC,
source_id of the document) and an idempotency key (one alert per document, kind and target).
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_alerts"
down_revision = "0012_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert", sa.Column("contract_id", sa.BigInteger, sa.ForeignKey("contract.id", ondelete="SET NULL")))
    op.add_column("alert", sa.Column("project_id", sa.BigInteger, sa.ForeignKey("project.id", ondelete="SET NULL")))
    op.add_column("alert", sa.Column("procedure_id", sa.BigInteger, sa.ForeignKey("procedure.id", ondelete="SET NULL")))
    op.add_column("alert", sa.Column("document_id", sa.BigInteger, sa.ForeignKey("document.id", ondelete="SET NULL")))
    op.add_column("alert", sa.Column("severity", sa.String(10), nullable=False, server_default="medium"))
    op.add_column("alert", sa.Column("origin", sa.String(10), nullable=False, server_default="CALC"))
    op.add_column("alert", sa.Column("key", sa.String(200)))
    op.add_column("alert", sa.Column("created_by", sa.String(80)))
    op.create_unique_constraint("uq_alert_key", "alert", ["key"])
    op.create_index("ix_alert_contract_id", "alert", ["contract_id"])
    op.create_index("ix_alert_project_id", "alert", ["project_id"])
    op.create_index("ix_alert_document_id", "alert", ["document_id"])
    op.create_index("ix_alert_status", "alert", ["status"])


def downgrade() -> None:
    for ix in ("ix_alert_status", "ix_alert_document_id", "ix_alert_project_id", "ix_alert_contract_id"):
        op.drop_index(ix, table_name="alert")
    op.drop_constraint("uq_alert_key", "alert", type_="unique")
    for col in ("created_by", "key", "origin", "severity", "document_id", "procedure_id", "project_id", "contract_id"):
        op.drop_column("alert", col)
