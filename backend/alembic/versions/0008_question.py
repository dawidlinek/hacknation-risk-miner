"""LLM layer: saved questions (Q-…), app settings (routing overrides), llm_call columns, AI change-cause codes, model eval

Revision ID: 0008_question
Revises: 0006
Branch: ask (session L, docs/impl/api_contract.md §6, docs/impl/llm.md §1.4, §2.3, §4). Raw SQL, no autogenerate.

- question: every /ask and chat answer (draft) and saved records Q-2026-NNNN (codes via rm_next_code from 0007)
- app_setting: key/value overrides set in Ustawienia (LLM routing)
- llm_call: prompt_version, tokens_cached, tokens_thought, attempt, fallback_from, batch_ref, subject, price_basis
- rm_cause_norm(cause, description): the one normalisation used to dedupe change causes (lowercase, whitespace
  collapsed, digits masked, description capped at 600 chars); IMMUTABLE so it can be indexed
- change_cause_ai: one AI classification per (norm_md5, model, prompt_version); origin AI, review_status proposed;
  protected by rm_protect_approved
- v_change_cause_ai: contract_change -> latest non-rejected AI code; v_contract_cause_ai: contract -> cause_codes_ai
  (confidence >= 0.6, quote verified) for Monte Carlo / analytics
- model_eval: gold-set benchmark results
"""
from alembic import op

revision = "0008_question"
down_revision = "0006"
branch_labels = ("ask",)
depends_on = "0007_analysis"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS question (
        id            bigserial PRIMARY KEY,
        code          varchar(20) UNIQUE,
        status        varchar(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'saved')),
        parent_id     bigint REFERENCES question(id) ON DELETE SET NULL,
        kind          varchar(20) NOT NULL DEFAULT 'ask',           -- ask | analysis_chat | project_chat
        title         text,
        question_text text NOT NULL,
        scope         jsonb NOT NULL DEFAULT '{}'::jsonb,
        answer        jsonb NOT NULL DEFAULT '{}'::jsonb,
        sql           text,
        params        jsonb NOT NULL DEFAULT '{}'::jsonb,
        rows          jsonb,
        role          varchar(10),
        n             int,
        llm_call_id   bigint REFERENCES llm_call(id) ON DELETE SET NULL,
        owner         text,
        data_as_of    timestamptz,
        created_at    timestamptz NOT NULL DEFAULT now(),
        saved_at      timestamptz
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_question_owner ON question (owner, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_question_saved ON question (saved_at DESC) WHERE status = 'saved'")

    op.execute("""
    CREATE TABLE IF NOT EXISTS app_setting (
        key        varchar(80) PRIMARY KEY,
        value      jsonb NOT NULL,
        updated_by text,
        updated_at timestamptz NOT NULL DEFAULT now()
    )""")

    for col, typ in [("prompt_version", "varchar(80)"), ("tokens_cached", "int"), ("tokens_thought", "int"),
                     ("attempt", "smallint"), ("fallback_from", "varchar(60)"), ("batch_ref", "varchar(120)"),
                     ("subject", "varchar(120)"), ("price_basis", "varchar(10)")]:
        op.execute(f"ALTER TABLE llm_call ADD COLUMN IF NOT EXISTS {col} {typ}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_llm_call_created ON llm_call (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_llm_call_subject ON llm_call (subject)")

    op.execute(r"""
    CREATE OR REPLACE FUNCTION rm_cause_norm(cause text, descr text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
        SELECT regexp_replace(regexp_replace(lower(
                   coalesce(cause, '') || ' | ' || left(coalesce(descr, ''), 600)),
               '\s+', ' ', 'g'), '\d', '0', 'g')
    $$""")
    op.execute("""CREATE INDEX IF NOT EXISTS ix_contract_change_cause_norm
                  ON contract_change (md5(rm_cause_norm(cause_text, description_text)))
                  WHERE cause_text IS NOT NULL OR description_text IS NOT NULL""")

    op.execute("""
    CREATE TABLE IF NOT EXISTS change_cause_ai (
        id              bigserial PRIMARY KEY,
        norm_md5        varchar(32) NOT NULL,
        sample_change_id bigint REFERENCES contract_change(id) ON DELETE SET NULL,
        n_changes       int,
        primary_code    varchar(20) NOT NULL,
        secondary_code  varchar(20),
        quote           text,
        verification    varchar(20),
        confidence      real,
        kw_codes        varchar(40)[] NOT NULL DEFAULT '{}',
        agrees_kw       boolean,
        method          varchar(10) NOT NULL DEFAULT 'llm',          -- llm | rule
        provider        varchar(40),
        model           varchar(120),
        prompt_version  varchar(80),
        llm_call_id     bigint REFERENCES llm_call(id) ON DELETE SET NULL,
        run_id          varchar(60),
        origin          varchar(10) NOT NULL DEFAULT 'AI' CHECK (origin IN ('SOURCE', 'CALC', 'AI')),
        review_status   varchar(10) NOT NULL DEFAULT 'proposed'
                        CHECK (review_status IN ('auto', 'proposed', 'approved', 'edited', 'rejected')),
        created_at      timestamptz NOT NULL DEFAULT now(),
        updated_at      timestamptz NOT NULL DEFAULT now(),
        UNIQUE (norm_md5, model, prompt_version)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_change_cause_ai_norm ON change_cause_ai (norm_md5)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_change_cause_ai_code ON change_cause_ai (primary_code)")
    op.execute("DROP TRIGGER IF EXISTS change_cause_ai_protect_approved ON change_cause_ai")
    op.execute("""CREATE TRIGGER change_cause_ai_protect_approved BEFORE UPDATE OR DELETE ON change_cause_ai
                  FOR EACH ROW EXECUTE FUNCTION rm_protect_approved()""")

    op.execute("""
    CREATE OR REPLACE VIEW v_change_cause_ai AS
    SELECT cc.id AS change_id, cc.contract_id, cc.procedure_id, a.id AS cause_ai_id, a.primary_code, a.secondary_code,
           a.confidence, a.quote, a.verification, a.review_status, a.origin, a.model, a.prompt_version, a.llm_call_id
    FROM contract_change cc
    JOIN LATERAL (
        SELECT * FROM change_cause_ai a
        WHERE a.norm_md5 = md5(rm_cause_norm(cc.cause_text, cc.description_text)) AND a.review_status <> 'rejected'
        ORDER BY (a.review_status IN ('approved', 'edited')) DESC, a.created_at DESC
        LIMIT 1) a ON true
    WHERE cc.cause_text IS NOT NULL OR cc.description_text IS NOT NULL""")
    op.execute("""
    CREATE OR REPLACE VIEW v_contract_cause_ai AS
    WITH c AS (
        SELECT contract_id, primary_code AS code, review_status
        FROM v_change_cause_ai
        WHERE contract_id IS NOT NULL AND coalesce(confidence, 0) >= 0.6 AND verification IN ('exact', 'fuzzy')
        UNION ALL
        -- expert-approved AI causes from project documents (protokoły konieczności, aneksy) on a known contract
        SELECT contract_id, catalogue_code, review_status
        FROM risk_event
        WHERE origin = 'AI' AND review_status IN ('approved', 'edited') AND contract_id IS NOT NULL
          AND catalogue_code ~ '^(R[0-9]{2}|N-)' AND coalesce(event_type, '') <> 'EV_CHANGE_CAUSE_AI')
    SELECT contract_id,
           array_agg(DISTINCT split_part(code, '.', 1)::varchar(20) ORDER BY split_part(code, '.', 1)::varchar(20)) AS cause_codes_ai,
           bool_or(review_status IN ('approved', 'edited')) AS any_approved,
           count(*) AS n_changes
    FROM c GROUP BY contract_id""")

    op.execute("""
    CREATE TABLE IF NOT EXISTS model_eval (
        id             bigserial PRIMARY KEY,
        task           varchar(60) NOT NULL,
        gold_sha256    char(64),
        alias          varchar(40),
        provider       varchar(40),
        model          varchar(120),
        prompt_version varchar(80),
        variant        varchar(40),
        n              int,
        metrics        jsonb NOT NULL DEFAULT '{}'::jsonb,
        per_class      jsonb NOT NULL DEFAULT '{}'::jsonb,
        confusion      jsonb NOT NULL DEFAULT '{}'::jsonb,
        cost_usd       real,
        created_at     timestamptz NOT NULL DEFAULT now()
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_eval")
    op.execute("DROP VIEW IF EXISTS v_contract_cause_ai")
    op.execute("DROP VIEW IF EXISTS v_change_cause_ai")
    op.execute("DROP TABLE IF EXISTS change_cause_ai")
    op.execute("DROP INDEX IF EXISTS ix_contract_change_cause_norm")
    op.execute("DROP FUNCTION IF EXISTS rm_cause_norm(text, text)")
    op.execute("DROP INDEX IF EXISTS ix_llm_call_subject")
    op.execute("DROP INDEX IF EXISTS ix_llm_call_created")
    for col in ("price_basis", "subject", "batch_ref", "fallback_from", "attempt", "tokens_thought", "tokens_cached",
                "prompt_version"):
        op.execute(f"ALTER TABLE llm_call DROP COLUMN IF EXISTS {col}")
    op.execute("DROP TABLE IF EXISTS app_setting")
    op.execute("DROP TABLE IF EXISTS question")
