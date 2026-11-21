"""analysis records: gapless record codes (AN-2026-0001), analysis versions (immutable), analysis_item extensions

Branch `analysis` (session A, docs/impl/api_contract.md §6). Raw SQL, no autogenerate.

Revision ID: 0007_analysis
Revises: 0006
"""
from alembic import op

revision = "0007_analysis"
down_revision = "0006"
branch_labels = ("analysis",)
depends_on = None


def upgrade() -> None:
    # --- gapless record codes: a row per (prefix, year); UPDATE ... RETURNING rolls back with the transaction ---------
    op.execute("""
    CREATE TABLE IF NOT EXISTS record_counter (
        prefix varchar(8) NOT NULL,
        year   int        NOT NULL,
        n      int        NOT NULL DEFAULT 0,
        PRIMARY KEY (prefix, year)
    )""")
    op.execute("""
    CREATE OR REPLACE FUNCTION rm_next_code(p_prefix text, p_year int DEFAULT NULL) RETURNS text
    LANGUAGE plpgsql AS $$
    DECLARE
        y int := coalesce(p_year, extract(year FROM now())::int);
        k int;
    BEGIN
        INSERT INTO record_counter (prefix, year, n) VALUES (p_prefix, y, 1)
        ON CONFLICT (prefix, year) DO UPDATE SET n = record_counter.n + 1
        RETURNING n INTO k;
        RETURN p_prefix || '-' || y || '-' || lpad(k::text, 4, '0');
    END $$""")

    # --- analysis: code, version, owner, visibility ------------------------------------------------------------------
    op.execute("ALTER TABLE analysis ADD COLUMN IF NOT EXISTS code varchar(20)")
    op.execute("ALTER TABLE analysis ADD COLUMN IF NOT EXISTS version int NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE analysis ADD COLUMN IF NOT EXISTS owner text")
    op.execute("ALTER TABLE analysis ADD COLUMN IF NOT EXISTS visibility varchar(20) NOT NULL DEFAULT 'owner'")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_code ON analysis (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_owner ON analysis (owner, updated_at DESC)")

    # --- analysis_version: immutable snapshots ----------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS analysis_version (
        id                bigserial PRIMARY KEY,
        analysis_id       bigint NOT NULL REFERENCES analysis(id) ON DELETE CASCADE,
        version           int    NOT NULL,
        features          jsonb  NOT NULL DEFAULT '{}'::jsonb,
        reference_class   jsonb  NOT NULL DEFAULT '{}'::jsonb,
        results           jsonb  NOT NULL DEFAULT '{}'::jsonb,
        catalogue_version text,
        data_as_of        timestamptz,
        seed              bigint,
        reason            text,
        created_by        text,
        created_at        timestamptz NOT NULL DEFAULT now(),
        UNIQUE (analysis_id, version)
    )""")
    op.execute("""
    CREATE OR REPLACE FUNCTION rm_analysis_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'analysis_version is immutable (% rejected)', TG_OP;
    END $$""")
    op.execute("DROP TRIGGER IF EXISTS analysis_version_immutable ON analysis_version")
    op.execute("""
    CREATE TRIGGER analysis_version_immutable BEFORE UPDATE ON analysis_version
    FOR EACH ROW EXECUTE FUNCTION rm_analysis_version_immutable()""")
    # DELETE of a single version is rejected; whole-analysis cascade is allowed only via pg_trigger_depth() > 0
    op.execute("""
    CREATE OR REPLACE FUNCTION rm_analysis_version_nodelete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'analysis_version is immutable (DELETE rejected)';
    END $$""")
    op.execute("DROP TRIGGER IF EXISTS analysis_version_nodelete ON analysis_version")
    op.execute("""
    CREATE TRIGGER analysis_version_nodelete BEFORE DELETE ON analysis_version
    FOR EACH ROW EXECUTE FUNCTION rm_analysis_version_nodelete()""")

    # --- analysis_item: version, key, document anchors -------------------------------------------------------------
    for col, typ in [("version", "int NOT NULL DEFAULT 1"), ("key", "varchar(80)"), ("document_id", "bigint"),
                     ("page_no", "int"), ("char_start", "int"), ("char_end", "int"), ("quote", "text"),
                     ("verification", "varchar(20)")]:
        op.execute(f"ALTER TABLE analysis_item ADD COLUMN IF NOT EXISTS {col} {typ}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_item_avs ON analysis_item (analysis_id, version, section)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_analysis_item_avs")
    for col in ("verification", "quote", "char_end", "char_start", "page_no", "document_id", "key", "version"):
        op.execute(f"ALTER TABLE analysis_item DROP COLUMN IF EXISTS {col}")
    op.execute("DROP TABLE IF EXISTS analysis_version")
    op.execute("DROP FUNCTION IF EXISTS rm_analysis_version_immutable()")
    op.execute("DROP FUNCTION IF EXISTS rm_analysis_version_nodelete()")
    op.execute("DROP INDEX IF EXISTS ix_analysis_owner")
    op.execute("DROP INDEX IF EXISTS ux_analysis_code")
    for col in ("visibility", "owner", "version", "code"):
        op.execute(f"ALTER TABLE analysis DROP COLUMN IF EXISTS {col}")
    op.execute("DROP FUNCTION IF EXISTS rm_next_code(text, int)")
    op.execute("DROP TABLE IF EXISTS record_counter")
