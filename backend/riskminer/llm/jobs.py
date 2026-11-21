"""Job kinds of the LLM layer (registered with riskminer.jobs.worker).

- analysis_redpen      {analysis_code, document_ids?}  Red Pen scan → analysis_item(section 'redpen_note', AI, proposed)
- analysis_features_ai {analysis_code, document_ids?}  AI chips → analysis_item(section 'feature', AI, proposed)
- llm_classify_causes  {limit?, buckets?, model_alias?, run_id?}  national change-cause classification
- llm_rescore_gold     {review_item_id | change_cause_ai_id}
- llm_eval             {aliases?, variant?}
"""
from __future__ import annotations

import json
from typing import Any

from riskminer.db.session import raw_conn
from riskminer.jobs.worker import register
from riskminer.llm.docs import load_documents


async def _analysis(conn, code: str) -> dict:
    r = await conn.fetchrow("SELECT id, code, version, sensitivity, input_text, input_documents FROM analysis WHERE code = $1", code)
    if r is None:
        raise ValueError(f"analysis {code} not found")
    return dict(r)


async def _insert_items(conn, analysis_id: int, version: int, items: list[dict]) -> list[int]:
    ids = []
    for it in items:
        ids.append(await conn.fetchval(
            "INSERT INTO analysis_item (analysis_id, version, section, key, rank, title, body, catalogue_code, origin, "
            "review_status, document_id, page_no, quote, verification, llm_call_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) RETURNING id",
            analysis_id, version, it["section"], (it.get("key") or "")[:80], it.get("rank"), it.get("title"),
            it.get("body") or {}, it.get("catalogue_code"), it.get("origin", "AI"), it.get("review_status", "proposed"),
            it.get("document_id"), it.get("page_no"), it.get("quote"), it.get("verification"), it.get("llm_call_id")))
    return ids


@register("analysis_redpen")
async def analysis_redpen(payload: dict, job_id: int) -> dict:
    from riskminer.llm.tasks.redpen_scan import note_items, redpen_scan

    async with raw_conn() as conn:
        a = await _analysis(conn, payload["analysis_code"])
    doc_ids = [int(d) for d in (payload.get("document_ids") or a["input_documents"] or [])]
    docs = await load_documents(doc_ids)
    out: dict[str, Any] = {"analysis_code": a["code"], "documents": {}}
    for did, doc in docs.items():
        res = await redpen_scan(doc, sensitivity=a["sensitivity"], subject=f"analysis:{a['code']}")
        items = note_items(res, doc)
        async with raw_conn() as conn, conn.transaction():
            # replace this layer's previous proposals for the document; approved/edited/rejected rows stay
            await conn.execute("DELETE FROM analysis_item WHERE analysis_id = $1 AND section = 'redpen_note' "
                               "AND origin = 'AI' AND review_status = 'proposed' AND document_id = $2", a["id"], did)
            ids = await _insert_items(conn, a["id"], a["version"], items)
        status = "sovereign_unavailable" if res.sovereign_unavailable and not res.notes else (
            "partial" if res.failed_pages else "done")
        out["documents"][str(did)] = {"status": status, "notes": len(ids), "item_ids": ids,
                                      "unverified": sum(1 for n in res.notes if n["verification"] == "unverified"),
                                      "failed_pages": res.failed_pages, "errors": res.errors,
                                      "processing": res.processing, "llm_call_ids": res.llm_call_ids}
    out["status"] = ("sovereign_unavailable" if out["documents"] and all(
        d["status"] == "sovereign_unavailable" for d in out["documents"].values()) else "done")
    return out


@register("analysis_features_ai")
async def analysis_features_ai(payload: dict, job_id: int) -> dict:
    from riskminer.llm.tasks.extract_features import extract_features, feature_items

    async with raw_conn() as conn:
        a = await _analysis(conn, payload["analysis_code"])
    doc_ids = [int(d) for d in (payload.get("document_ids") or a["input_documents"] or [])]
    res = await extract_features(a["input_text"], doc_ids, sensitivity=a["sensitivity"], subject=f"analysis:{a['code']}")
    items = feature_items(res)
    async with raw_conn() as conn, conn.transaction():
        await conn.execute("DELETE FROM analysis_item WHERE analysis_id = $1 AND version = $2 AND section = 'feature' "
                           "AND origin IN ('AI') AND review_status = 'proposed'", a["id"], a["version"])
        ids = await _insert_items(conn, a["id"], a["version"], items)
    return {"analysis_code": a["code"], "chips": len(ids), "item_ids": ids, "missing": res.missing,
            "errors": res.errors, "processing": res.processing, "rows": len(res.rows)}


_ = json


@register("llm_classify_causes")
async def llm_classify_causes(payload: dict, job_id: int) -> dict:
    """payload: {limit?, buckets?: [1..4], alias?, run_id?, relevance?: [...], propose?: true, sample?: 40}"""
    from riskminer.llm.tasks.classify_causes import national_run, propose_events

    async def progress(st: dict) -> None:
        async with raw_conn() as conn:
            await conn.execute("UPDATE job SET result = $1 WHERE id = $2", {"progress": st}, job_id)

    st = await national_run(limit=payload.get("limit"), buckets=tuple(payload.get("buckets") or (1, 2, 3, 4)),
                            alias=payload.get("alias"), run_id=payload.get("run_id") or f"job{job_id}",
                            relevance=tuple(payload.get("relevance") or ("core", "component")), progress=progress)
    if payload.get("propose", True):
        st["events"] = await propose_events(st["run_id"], sample=int(payload.get("sample", 40)))
    return st


@register("llm_rescore_gold")
async def llm_rescore_gold(payload: dict, job_id: int) -> dict:
    """payload from B's review service: {risk_event_id, code, gold_example_id}"""
    from riskminer.llm.tasks.rescore_gold import rescore

    return await rescore(risk_event_id=int(payload["risk_event_id"]), code=payload.get("code"),
                         limit=int(payload.get("limit", 20)))


@register("llm_eval")
async def llm_eval(payload: dict, job_id: int) -> dict:
    """payload: {aliases?: [...], variant?: 'packed25'|'single'}"""
    from riskminer.llm.eval.gold import run_eval

    return await run_eval(aliases=payload.get("aliases"), variant=payload.get("variant", "packed25"))


@register("llm_catalogue_proposals")
async def llm_catalogue_proposals(payload: dict, job_id: int) -> dict:
    """payload: {sample?: 200, insert?: true}"""
    from riskminer.llm.tasks.catalogue_proposals import propose

    return await propose(int(payload.get("sample", 200)), insert=bool(payload.get("insert", True)))


@register("rescore_gold")
async def rescore_gold_job(payload: dict, job_id: int) -> dict:
    """B's generic gold job {gold_example_id, kind, limit}. Change-cause events are re-scored by the classifier; other
    kinds (link, fact, discrepancy, catalogue) have no model proposals to re-score yet: zeros with a note."""
    from riskminer.llm.tasks.rescore_gold import rescore

    gid = payload.get("gold_example_id")
    g = None
    if gid is not None:
        async with raw_conn() as conn:
            g = await conn.fetchrow("SELECT target_table, target_id, catalogue_code FROM gold_example WHERE id = $1", int(gid))
    if g and g["target_table"] == "risk_event" and g["target_id"]:
        return await rescore(risk_event_id=int(g["target_id"]), code=g["catalogue_code"], limit=int(payload.get("limit", 20)))
    return {"rescored": 0, "unchanged": 0, "changed": 0, "requeued_item_ids": [],
            "note": f"brak propozycji modelu do przeliczenia dla rodzaju {payload.get('kind') or '?'}"}


async def _document_extract(payload: dict, job_id: int) -> dict:
    """{document_id}: rules + LLM facts for a new project document → document.data.facts (proposals for B's linking).
    A scan without text waits for OCR (D's document_ocr job should enqueue document_extract again when done)."""
    from riskminer.jobs.worker import enqueue, known_kind
    from riskminer.llm.tasks.document_facts import document_facts

    did = int(payload["document_id"])
    docs = await load_documents([did])
    if did not in docs:
        return {"status": "not_found", "document_id": did}
    doc = docs[did]
    if not any((t or "").strip() for t in doc["pages"].values()):
        return {"status": "waiting_ocr", "document_id": did}
    facts = await document_facts(doc, sensitivity=doc.get("sensitivity") or "confidential", subject=f"document:{did}")
    async with raw_conn() as conn:
        await conn.execute("UPDATE document SET data = coalesce(data, '{}'::jsonb) || jsonb_build_object('facts', $1::jsonb) "
                           "WHERE id = $2", facts, did)
    link_job = None
    if known_kind("document_link"):
        link_job = (await enqueue("document_link", {"document_id": did}, created_by="llm:document_extract"))["id"]
    return {"status": "done", "document_id": did, "doc_kind": facts["doc_kind"], "level": facts["level"],
            "causes": [c["code"] for c in facts["causes"]], "flags": [f["code"] for f in facts["flags"]],
            "processing": facts["processing"], "document_link_job": link_job, "facts": facts}


register("document_extract")(_document_extract)
register("extract_events")(_document_extract)
