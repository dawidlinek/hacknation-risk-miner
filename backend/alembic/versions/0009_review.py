"""review queue columns, review.option_key/undo_of/request_id, catalogue_version, protect trigger on link_candidate

Own Alembic branch `review` off 0006 (session B). Raw SQL only, no autogenerate.

Revision ID: 0009_review
Revises: 0006
"""
from alembic import op

revision = "0009_review"
down_revision = "0006"
branch_labels = ("review",)
depends_on = None


def upgrade() -> None:
    # review queue: question text, option list and the model's pick shown on the card
    op.execute("""
        ALTER TABLE review_item
          ADD COLUMN IF NOT EXISTS question text,
          ADD COLUMN IF NOT EXISTS options jsonb,
          ADD COLUMN IF NOT EXISTS model_pick text,
          ADD COLUMN IF NOT EXISTS confidence double precision,
          ADD COLUMN IF NOT EXISTS target_field text
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_item_status_kind ON review_item (status, kind)")

    op.execute("""
        ALTER TABLE review
          ADD COLUMN IF NOT EXISTS option_key text,
          ADD COLUMN IF NOT EXISTS undo_of bigint REFERENCES review(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS request_id text
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_reviewer_created ON review (reviewer, created_at DESC)")

    # catalogue pack versions: one row per pack label (v1.1 -> v1.2 ...), changes = [{table, code, from_version, to_version, before, after}]
    op.execute("""
        CREATE TABLE IF NOT EXISTS catalogue_version (
          id bigserial PRIMARY KEY,
          sector text NOT NULL DEFAULT 'wod-kan',
          label text NOT NULL,
          summary text,
          changes jsonb NOT NULL DEFAULT '[]'::jsonb,
          actor text NOT NULL DEFAULT 'system:catalogue',
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_catalogue_version_label UNIQUE (sector, label)
        )
    """)
    op.execute("""
        INSERT INTO catalogue_version (sector, label, summary, actor)
        SELECT 'wod-kan', 'v1.1', 'Pakiet startowy z plików YAML', 'system:catalogue'
        WHERE NOT EXISTS (SELECT 1 FROM catalogue_version WHERE sector = 'wod-kan')
    """)

    # link_candidate carries review_status (approved by the expert): protect it like the fact tables
    op.execute("DROP TRIGGER IF EXISTS link_candidate_protect_approved ON link_candidate")
    op.execute("""
        CREATE TRIGGER link_candidate_protect_approved BEFORE UPDATE OR DELETE ON link_candidate
        FOR EACH ROW EXECUTE FUNCTION rm_protect_approved()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS link_candidate_protect_approved ON link_candidate")
    op.execute("DROP TABLE IF EXISTS catalogue_version")
    op.execute("DROP INDEX IF EXISTS ix_review_reviewer_created")
    op.execute("ALTER TABLE review DROP COLUMN IF EXISTS request_id, DROP COLUMN IF EXISTS undo_of, DROP COLUMN IF EXISTS option_key")
    op.execute("DROP INDEX IF EXISTS ix_review_item_status_kind")
    op.execute("ALTER TABLE review_item DROP COLUMN IF EXISTS target_field, DROP COLUMN IF EXISTS confidence, "
               "DROP COLUMN IF EXISTS model_pick, DROP COLUMN IF EXISTS options, DROP COLUMN IF EXISTS question")
