"""Learning loop for document facts and cause codes (lead's direction 21.11 22:10; api_contract §3 gold decisions).

- `few_shot(db, doc_kind)`: expert-approved/edited extractions → few-shot examples for the next `document_facts` call
  (same document kind first), and rejections with a reason → a "typowe błędy" list in the prompt.
- `rates(db)`: accept / edit / reject counts per document kind and model, plus for national cause codes per model, for
  the learning view (`learning_loop` flag) and Ustawienia.
Everything reads the review trail (`review`, `gold_example`, `evidence`, `llm_call`); nothing here writes.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

DOC_EVENTS = """
SELECT e.id, e.catalogue_code, e.summary, e.review_status, e.llm_call_id, ev.quote,
       coalesce(d.data->'facts'->>'doc_kind', d.doc_type, 'inne') AS doc_kind, lc.model
FROM risk_event e
JOIN LATERAL (SELECT document_id, quote FROM evidence x WHERE x.claim_table = 'risk_event' AND x.claim_id = e.id
              AND x.document_id IS NOT NULL ORDER BY x.id LIMIT 1) ev ON true
JOIN document d ON d.id = ev.document_id
LEFT JOIN llm_call lc ON lc.id = e.llm_call_id
WHERE e.origin = 'AI'"""


async def few_shot(db, doc_kind: str | None, k_examples: int = 6, k_mistakes: int = 6) -> dict[str, Any]:
    try:
        # B writes one gold_example per approve/edit of a document-derived item (task 'document_facts'); undo → retracted
        ex = (await db.execute(text("""
            SELECT coalesce(d.data->'facts'->>'doc_kind', d.doc_type, 'inne') AS doc_kind, g.catalogue_code AS code,
                   g.input_text AS quote, g.output->>'item_code' AS item, g.output->>'action' AS action
            FROM gold_example g LEFT JOIN document d ON d.id = (g.output->>'document_id')::bigint
            WHERE g.task = 'document_facts' AND (g.output->>'retracted') IS NULL AND g.input_text IS NOT NULL
            ORDER BY (coalesce(d.data->'facts'->>'doc_kind', d.doc_type, 'inne') = :k) DESC, g.id DESC LIMIT :n"""),
            {"k": doc_kind or "", "n": k_examples})).mappings().all()
        mi = (await db.execute(text(f"""
            WITH de AS ({DOC_EVENTS})
            SELECT de.doc_kind, de.catalogue_code AS code, de.quote, r.comment
            FROM de JOIN review r ON r.target_table = 'risk_event' AND r.target_id = de.id AND r.action = 'reject'
            WHERE coalesce(r.comment, '') <> '' AND r.undo_of IS NULL
            ORDER BY (de.doc_kind = :k) DESC, r.id DESC LIMIT :n"""), {"k": doc_kind or "", "n": k_mistakes})).mappings().all()
    except Exception:  # noqa: BLE001  tables or columns missing in a fresh DB: no learning context
        return {"examples": "", "mistakes": "", "n_examples": 0, "n_mistakes": 0}
    examples = ""
    if ex:
        examples = "\nPrzykłady zatwierdzone przez eksperta (wzorce, nie kopiuj ich treści):\n" + "\n".join(
            f'- [{r["doc_kind"]}] {"poprawione przez eksperta: " if r.get("action") == "edit" else ""}kod {r["code"] or "-"}'
            f' ({r.get("item") or "przyczyna"}): "{(r["quote"] or "")[:200]}"' for r in ex)
    mistakes = ""
    if mi:
        mistakes = "\nTypowe błędy (ekspert odrzucił takie propozycje):\n" + "\n".join(
            f'- [{r["doc_kind"]}] kod {r["code"]} dla "{(r["quote"] or "")[:120]}": {r["comment"][:160]}' for r in mi)
    return {"examples": examples, "mistakes": mistakes, "n_examples": len(ex), "n_mistakes": len(mi)}


async def rates(db) -> dict[str, Any]:
    """Accept / edit / reject per document kind and model (document facts) and per model (national cause codes)."""
    out: dict[str, Any] = {"documents": [], "causes": []}
    try:
        out["documents"] = [dict(r) for r in (await db.execute(text(f"""
            WITH de AS ({DOC_EVENTS})
            SELECT doc_kind, coalesce(model, 'reguły') AS model, count(*) AS proposals,
                   count(*) FILTER (WHERE review_status = 'approved') AS approved,
                   count(*) FILTER (WHERE review_status = 'edited') AS edited,
                   count(*) FILTER (WHERE review_status = 'rejected') AS rejected,
                   count(*) FILTER (WHERE review_status = 'proposed') AS pending
            FROM de GROUP BY 1, 2 ORDER BY 1, 2"""))).mappings().all()]
        out["causes"] = [dict(r) for r in (await db.execute(text("""
            SELECT coalesce(model, '?') AS model, count(*) AS proposals,
                   count(*) FILTER (WHERE review_status = 'approved') AS approved,
                   count(*) FILTER (WHERE review_status = 'edited') AS edited,
                   count(*) FILTER (WHERE review_status = 'rejected') AS rejected,
                   count(*) FILTER (WHERE review_status = 'proposed') AS pending
            FROM change_cause_ai GROUP BY 1 ORDER BY 2 DESC"""))).mappings().all()]
        out["gold_examples"] = int((await db.execute(text(
            "SELECT count(*) FROM gold_example WHERE NOT coalesce((output->>'retracted')::boolean, false)"))).scalar() or 0)
        out["gold_examples_documents"] = int((await db.execute(text(
            "SELECT count(*) FROM gold_example WHERE task = 'document_facts' AND (output->>'retracted') IS NULL"))).scalar() or 0)
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
    for row in out["documents"] + out["causes"]:
        decided = (row["approved"] or 0) + (row["edited"] or 0) + (row["rejected"] or 0)
        row["decided"] = decided
        row["accept_rate"] = round((row["approved"] + row["edited"]) / decided, 3) if decided else None
        row["edit_rate"] = round(row["edited"] / decided, 3) if decided else None
    return out
