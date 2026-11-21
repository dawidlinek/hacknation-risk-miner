"""Review queue sync (job `review_sync`, idempotent by review_item.key). Fills the queue from proposals:
risk_event AI proposed -> event; project link_candidate decision 'review' -> link; AI-read facts -> fact;
AI catalogue proposals -> catalogue. Items whose target was decided elsewhere are dismissed."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FACT_TABLES = ("contract_performance", "contract_change", "contract", "lot")


async def sync(db: AsyncSession) -> dict:
    out: dict[str, int] = {}

    async def run(name: str, sql: str) -> None:
        out[name] = (await db.execute(text(sql))).rowcount or 0

    await run("event", """
        INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, model_pick, confidence, severity, key, created_by, detail)
        SELECT 'event', 'ai_event', 'risk_event', e.id, e.project_id, left(e.summary, 300),
               'Które ryzyko opisuje to zdarzenie? ' || left(e.summary, 200), e.catalogue_code,
               coalesce(e.conf_data_quality, e.conf_completeness), 'medium', 'evt:' || e.id, 'system:review_sync',
               jsonb_build_object('cause', e.cause)
        FROM risk_event e WHERE e.origin = 'AI' AND e.review_status = 'proposed'
        ON CONFLICT (key) DO NOTHING""")
    await run("link", """
        INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, model_pick, confidence, severity, key, created_by, detail)
        SELECT 'link', 'link_candidate', 'link_candidate', lc.id, lc.left_id,
               'Powiązanie projektu z postępowaniem ' || coalesce(lc.right_ref, '?') || ' (' || lc.method || ')',
               'Czy to postępowanie dotyczy tego projektu?', lc.right_ref, lc.score, 'medium', 'link:' || lc.id, 'system:review_sync',
               jsonb_build_object('method', lc.method, 'explanation', lc.explanation)
        FROM link_candidate lc WHERE lc.left_table = 'project' AND lc.right_table = 'procedure'
          AND lc.decision = 'review' AND lc.review_status = 'proposed'
        ON CONFLICT (key) DO NOTHING""")
    for t in FACT_TABLES:
        await run(f"fact:{t}", f"""
            INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, target_field, severity, key, created_by, detail)
            SELECT 'fact', 'ai_fact', '{t}', f.id, NULL,
                   'Odczyt modelu do sprawdzenia: ' || coalesce(ev.claim_field, '{t}'),
                   'Czy odczyt modelu jest poprawny?', ev.claim_field, 'medium', 'fact:{t}:' || f.id, 'system:review_sync', '{{}}'::jsonb
            FROM {t} f LEFT JOIN LATERAL (SELECT claim_field FROM evidence e WHERE e.claim_table = '{t}' AND e.claim_id = f.id
                                           AND e.verification <> 'exact' ORDER BY e.id LIMIT 1) ev ON true
            WHERE f.origin = 'AI' AND f.review_status = 'proposed'
            ON CONFLICT (key) DO NOTHING""")
    await run("catalogue", """
        INSERT INTO review_item (kind, code, target_table, target_id, title, question, severity, key, created_by, detail)
        SELECT 'catalogue', 'catalogue_proposal', 'catalogue_risk', c.id,
               'Propozycja ryzyka' || CASE WHEN c.sector <> 'wod-kan' THEN ' (sektor ' || c.sector || ')' ELSE '' END || ': ' || c.name,
               'Czy dodać to ryzyko do katalogu?', 'low', 'cat:risk:' || c.id, 'system:review_sync',
               jsonb_build_object('merge_suggestion', c.data->>'merge_suggestion', 'sector', c.sector)
        FROM catalogue_risk c WHERE c.origin = 'AI' AND c.status = 'proposed'
        ON CONFLICT (key) DO NOTHING""")
    # dismiss open items whose target is no longer awaiting review (decided outside the queue)
    await run("dismissed", """
        UPDATE review_item r SET status = 'dismissed', resolved_by = 'system:review_sync', resolved_at = now(), updated_at = now()
        WHERE r.status = 'open' AND (
          (r.kind = 'event' AND r.target_table = 'risk_event' AND NOT EXISTS (SELECT 1 FROM risk_event e WHERE e.id = r.target_id AND e.review_status = 'proposed'))
          OR (r.kind = 'link' AND NOT EXISTS (SELECT 1 FROM link_candidate l WHERE l.id = r.target_id AND l.review_status = 'proposed'))
          OR (r.kind = 'catalogue' AND NOT EXISTS (SELECT 1 FROM catalogue_risk c WHERE c.id = r.target_id AND c.status = 'proposed')))""")
    await db.execute(text("""INSERT INTO audit_log (actor, action, table_name, after, note) VALUES ('system:review_sync', 'review.sync', 'review_item', CAST(:a AS jsonb), 'synchronizacja kolejki')"""),
                     {"a": __import__("json").dumps(out)})
    return out
