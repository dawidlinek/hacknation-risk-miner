"""`rescore_gold`: learning loop after an expert marks a decision as gold (api_contract §3, docs/impl/llm.md §2.9).

Re-classifies up to 20 similar AI proposals (still `proposed`; trigram similarity of the cause text, same model pick
as the gold item had or the expert's code) with the expert's examples in the prompt, updates only rows still
`proposed` (change_cause_ai, AI risk_event, the open review_item's model pick) and reports
{rescored, unchanged, changed, requeued_item_ids} for the toast "Model przeliczył N podobnych propozycji"."""
from __future__ import annotations

from riskminer.llm.tasks.classify_causes import classify_items, item_text

SIMILAR_SQL = """
SELECT a.id AS cause_ai_id, a.norm_md5, a.primary_code, cc.id AS change_id, cc.cause_text, cc.description_text,
       similarity(coalesce(cc.cause_text, '') || ' ' || left(coalesce(cc.description_text, ''), 300), $1) AS sim
FROM change_cause_ai a JOIN contract_change cc ON cc.id = a.sample_change_id
WHERE a.review_status = 'proposed' AND a.norm_md5 <> $2 AND a.primary_code = ANY($3::text[])
ORDER BY sim DESC LIMIT $4"""


async def examples(conn, limit: int = 8) -> list[dict]:
    """Expert-approved examples (gold_example from risk_event decisions), newest first."""
    rows = await conn.fetch(
        "SELECT g.catalogue_code AS code, coalesce(cc.cause_text || ' | ' || left(coalesce(cc.description_text, ''), 300), "
        "g.input_text) AS text FROM gold_example g LEFT JOIN risk_event e ON g.target_table = 'risk_event' AND e.id = g.target_id "
        "LEFT JOIN contract_change cc ON cc.id = e.change_id WHERE g.catalogue_code IS NOT NULL "
        "AND NOT coalesce((g.output->>'retracted')::boolean, false) ORDER BY g.id DESC LIMIT $1", limit)
    return [dict(r) for r in rows if r["text"]]


async def rescore(*, risk_event_id: int, code: str | None = None, limit: int = 20, dry_run: bool = False) -> dict:
    from riskminer.db.session import raw_conn
    from riskminer.llm import labels

    async with raw_conn() as conn:
        ev = await conn.fetchrow(
            "SELECT e.id, e.catalogue_code, e.change_id, cc.cause_text, cc.description_text, "
            "md5(rm_cause_norm(cc.cause_text, cc.description_text)) AS norm_md5, "
            "(SELECT primary_code FROM change_cause_ai a WHERE a.norm_md5 = md5(rm_cause_norm(cc.cause_text, cc.description_text)) "
            " ORDER BY created_at LIMIT 1) AS model_pick "
            "FROM risk_event e JOIN contract_change cc ON cc.id = e.change_id WHERE e.id = $1", risk_event_id)
        if ev is None:
            return {"rescored": 0, "unchanged": 0, "changed": 0, "requeued_item_ids": [], "note": "zdarzenie bez zmiany umowy"}
        gold_code = labels.normalise_code(code or ev["catalogue_code"]) or (code or ev["catalogue_code"])
        # the decision on the gold item itself is mirrored into change_cause_ai by B's review service
        probe = (ev["cause_text"] or "") + " " + (ev["description_text"] or "")[:300]
        picks = sorted({c for c in (ev["model_pick"], gold_code) if c})
        cands = [dict(r) for r in await conn.fetch(SIMILAR_SQL, probe, ev["norm_md5"], picks, limit)]
        exs = await examples(conn)
    if not cands:
        return {"rescored": 0, "unchanged": 0, "changed": 0, "requeued_item_ids": []}
    if not any(e["code"] == gold_code for e in exs):
        exs.insert(0, {"code": gold_code, "text": probe})
    items = [{"id": c["norm_md5"], "text": item_text(c["cause_text"], c["description_text"])} for c in cands]
    done, failed = await classify_items(items, subject=f"rescore:risk_event:{risk_event_id}", examples=exs, pack=25,
                                        run_budget=False)
    by = {c["norm_md5"]: c for c in cands}
    changed, unchanged, requeued = 0, 0, []
    if dry_run:
        diffs = [{"change_id": by[d.id]["change_id"], "before": by[d.id]["primary_code"], "after": d.primary,
                  "confidence": d.confidence} for d in done]
        return {"rescored": len(done), "unchanged": sum(x["before"] == x["after"] for x in diffs),
                "changed": sum(x["before"] != x["after"] for x in diffs), "failed": len(failed), "requeued_item_ids": [],
                "gold_code": gold_code, "dry_run": True, "diffs": diffs}
    async with raw_conn() as conn:
        async with conn.transaction():
            for d in done:
                c = by[d.id]
                if d.primary == c["primary_code"]:
                    unchanged += 1
                    continue
                changed += 1
                await conn.execute(
                    "UPDATE change_cause_ai SET primary_code = $1, secondary_code = $2, quote = $3, verification = $4, "
                    "confidence = $5, llm_call_id = $6, method = 'llm', updated_at = now() "
                    "WHERE id = $7 AND review_status = 'proposed'",
                    d.primary, d.secondary, d.quote, d.verification, d.confidence, d.llm_call_id, c["cause_ai_id"])
                eids = [r["id"] for r in await conn.fetch(
                    "UPDATE risk_event SET catalogue_code = $1, conf_data_quality = $2, llm_call_id = $3, updated_at = now() "
                    "WHERE key = 'ai:cause:' || $4::text AND origin = 'AI' AND review_status = 'proposed' RETURNING id",
                    d.primary[:12], d.confidence, d.llm_call_id, str(c["change_id"]))]
                if eids:
                    requeued += [r["id"] for r in await conn.fetch(
                        "UPDATE review_item SET model_pick = $1, confidence = $2, updated_at = now() "
                        "WHERE target_table = 'risk_event' AND target_id = ANY($3::bigint[]) AND status = 'open' RETURNING id",
                        d.primary, d.confidence, eids)]
    return {"rescored": len(done), "unchanged": unchanged, "changed": changed, "failed": len(failed),
            "requeued_item_ids": requeued, "gold_code": gold_code}
