"""imports: import agent sessions and approved importers (api_contract §3.5)

Revision ID: 0012_imports
Revises: 0011_ask_views
Depends on: 0007_analysis (rm_next_code for IMP-2026-NNNN codes)

import_session: one upload + inspect + mapping + test run + approve + run cycle; files stay in data/imports/<code>/
  (outside data/raw) until the importer is approved and the full run copies them in with manifest lines.
importer: approved declarative specs (never generated code), versioned per name; reused when >= 80% of headers match.
"""
from alembic import op

revision = "0012_imports"
down_revision = "0011_ask_views"
branch_labels = None
depends_on = "0007_analysis"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS importer (
      id bigserial PRIMARY KEY,
      name text NOT NULL,
      version int NOT NULL DEFAULT 1,
      format text NOT NULL,
      spec jsonb NOT NULL,
      spec_sha256 varchar(64) NOT NULL,
      status varchar(12) NOT NULL DEFAULT 'approved' CHECK (status IN ('approved', 'retired')),
      uses int NOT NULL DEFAULT 0,
      created_by text,
      approved_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (name, version))""")
    op.execute("""
    CREATE TABLE IF NOT EXISTS import_session (
      id bigserial PRIMARY KEY,
      code text NOT NULL UNIQUE,
      status varchar(20) NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'inspected', 'awaiting_answer', 'mapped', 'tested', 'approved', 'running', 'done', 'failed')),
      files jsonb NOT NULL DEFAULT '[]',
      sandbox_path text,
      tool_calls jsonb NOT NULL DEFAULT '[]',
      mapping jsonb NOT NULL DEFAULT '[]',
      questions jsonb NOT NULL DEFAULT '[]',
      answers jsonb NOT NULL DEFAULT '{}',
      test_result jsonb,
      importer_id bigint REFERENCES importer(id) ON DELETE SET NULL,
      job_id bigint REFERENCES job(id) ON DELETE SET NULL,
      run_id uuid,
      created_by text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_import_session_status ON import_session (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_session")
    op.execute("DROP TABLE IF EXISTS importer")
