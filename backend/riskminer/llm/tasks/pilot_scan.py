"""Batch Red Pen over the 22 pilot projects' own tender documents (SWZ, PPU, PFU, modifications, Q&A, contracts,
annexes) → AI `risk_event` proposals with evidence (document, page, verified quote). Documents are public (published
tender documents); `fast` alias (flash-lite). Only notes whose quote verifies on the page are kept. Idempotent per
(document, page, code, quote) through risk_event.key; approved rows are never touched (insert-only, ON CONFLICT DO NOTHING).
Stops at the spend cap and reports how far it got.

    uv run python -m riskminer.llm.tasks.pilot_scan --cap 5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time

from riskminer.db.session import raw_conn
from riskminer.llm.docs import load_documents
from riskminer.llm.tasks.redpen_scan import redpen_scan

TYPE_ORDER = ["swz", "ppu", "pfu", "umowa", "aneks", "modyfikacja", "opz", "qa"]
STRENGTH = {"silny": 0.8, "średni": 0.6, "słaby": 0.4}


LATER_ORDER = ["stwiorb", "wpf", "kosztorys", "decyzja_srodowiskowa", "zarzadzenie", "ogloszenie", "uniewaznienie", "inne",
               "wybor", "otwarcie", "kwota", "przedmiar", "projekt"]
TEXT_PAGES = "(SELECT count(*) FROM document_page x WHERE x.document_id = d.id AND length(coalesce(x.text, '')) > 200)"


def _rank(dt: str) -> int:
    order = TYPE_ORDER + LATER_ORDER
    return order.index(dt) if dt in order else len(order)


async def candidates(types: list[str] | None, mode: str = "pilot") -> list[dict]:
    """pilot: documents of the 22 pilot projects; monitor: documents we already hold for ongoing contracts flagged in
    Monitoring (v_monitor_signal), most overdue first. Documents already scanned (facts.kind tender_scan) are skipped."""
    async with raw_conn() as conn:
        if mode == "pilot":
            rows = await conn.fetch(f"""
                SELECT d.id, lower(coalesce(d.doc_type, 'inne')) AS dt, d.project_id, d.procedure_id, d.source_id, p.rm_id,
                       NULL::bigint AS contract_id, 0 AS days_overdue, {TEXT_PAGES} AS text_pages
                FROM document d JOIN project p ON p.id = d.project_id
                WHERE ($1::text[] IS NULL OR lower(coalesce(d.doc_type, 'inne')) = ANY($1::text[]))
                  AND NOT coalesce((d.data->'facts'->>'kind') = 'tender_scan', false)""", types)
        else:
            rows = await conn.fetch(f"""
                SELECT DISTINCT ON (d.id) d.id, lower(coalesce(d.doc_type, 'inne')) AS dt, NULL::bigint AS project_id,
                       d.procedure_id, d.source_id, coalesce(s.bzp_number, s.ocid) AS rm_id, s.contract_id, s.days_overdue,
                       {TEXT_PAGES} AS text_pages
                FROM v_monitor_signal s JOIN contract c ON c.id = s.contract_id JOIN document d ON d.procedure_id = c.procedure_id
                WHERE d.project_id IS NULL AND ($1::text[] IS NULL OR lower(coalesce(d.doc_type, 'inne')) = ANY($1::text[]))
                  AND NOT coalesce((d.data->'facts'->>'kind') = 'tender_scan', false)
                ORDER BY d.id, s.days_overdue DESC""", types)
    out = [dict(r) for r in rows if r["text_pages"] > 0]
    out.sort(key=lambda r: (-(r["days_overdue"] or 0), _rank(r["dt"]), -r["text_pages"]))
    return out


async def spent(run: str) -> float:
    """Spend of every pilotscan run whose id starts with `run` (so one cap can cover several runs, e.g. 'ext')."""
    async with raw_conn() as conn:
        return float(await conn.fetchval("SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE subject LIKE $1", f"pilotscan:{run}%") or 0)


async def store(doc_row: dict, doc: dict, res) -> dict:
    kept = [n for n in res.notes if n["verification"] in ("exact", "fuzzy")]
    ins = 0
    async with raw_conn() as conn:
        async with conn.transaction():
            for n in kept:
                h = hashlib.sha1(f"{doc_row['id']}|{n['page_no']}|{n['code']}|{n['quote']}".encode()).hexdigest()[:12]
                eid = await conn.fetchval("""
                    INSERT INTO risk_event (project_id, procedure_id, contract_id, event_type, catalogue_code, summary, cause,
                        phase, conf_data_quality, llm_call_id, key, source_id, origin, review_status)
                    VALUES ($1, $2, $10, 'EV_DOC_SIGNAL', $3, $4, $5, 'przygotowanie', $6, $7, $8, $9, 'AI', 'proposed')
                    ON CONFLICT (key) DO NOTHING RETURNING id""",
                    doc_row["project_id"], doc_row["procedure_id"], n["code"][:12], n["title"][:300], n["why"],
                    STRENGTH.get(n["strength"], 0.5), n["llm_call_id"], f"ai:doc:{doc_row['id']}:{n['page_no']}:{n['code']}:{h}",
                    doc_row["source_id"], doc_row.get("contract_id"))
                if eid:
                    ins += 1
                    await conn.execute("""
                        INSERT INTO evidence (claim_table, claim_id, claim_field, document_id, source_id, page_no, char_start,
                            char_end, quote, verification, note)
                        VALUES ('risk_event', $1, 'catalogue_code', $2, $3, $4, $5, $6, $7, $8, $9)""",
                        eid, doc_row["id"], doc_row["source_id"], n["page_no"], n["char_start"], n["char_end"], n["quote"],
                        n["verification"], f"{doc_row['dt'].upper()} s. {n['page_no']}" + (f", {n['pkt']}" if n.get("pkt") else ""))
            facts = {"version": 1, "kind": "tender_scan", "document_id": doc_row["id"], "doc_kind": doc_row["dt"],
                     "level": "tender", "signals": [{k: n.get(k) for k in ("code", "title", "why", "strength", "page_no", "pkt",
                                                                             "quote", "char_start", "char_end", "verification",
                                                                             "suggested_clause")} for n in kept],
                     "dropped_unverified": len(res.notes) - len(kept), "failed_pages": res.failed_pages,
                     "processing": [{"pass": "llm", **(res.processing or {})}], "llm_call_ids": res.llm_call_ids}
            await conn.execute("UPDATE document SET data = coalesce(data, '{}'::jsonb) || jsonb_build_object('facts', $1::jsonb) "
                               "WHERE id = $2", facts, doc_row["id"])
    return {"notes": len(res.notes), "kept": len(kept), "inserted": ins, "failed_pages": res.failed_pages}


async def run(cap_usd: float = 5.0, run_id: str | None = None, concurrency: int = 4, types: list[str] | None = None,
              limit: int | None = None, mode: str = "pilot", spent_prefix: str | None = None) -> dict:
    run_id = run_id or time.strftime("%H%M")
    cands = await candidates(types, mode)
    if limit:
        cands = cands[:limit]
    stats = {"run": run_id, "candidates": len(cands), "done": 0, "notes": 0, "kept": 0, "inserted": 0, "failed_docs": 0,
             "stopped": None}
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async def one(r: dict):
        async with sem:
            if stop.is_set():
                return
            if await spent(spent_prefix or run_id) >= cap_usd:
                stop.set()
                stats["stopped"] = f"cap ${cap_usd} reached"
                return
            docs = await load_documents([r["id"]])
            d = docs.get(r["id"])
            if not d:
                return
            if d.get("sensitivity") == "confidential":      # never send a confidential document to the cloud
                return
            d["sensitivity"] = "public"
            try:
                res = await redpen_scan(d, sensitivity="public", subject=f"pilotscan:{run_id}:{r['rm_id']}", alias="fast")
                o = await store(r, d, res)
            except Exception as e:  # noqa: BLE001
                stats["failed_docs"] += 1
                print("fail", r["id"], type(e).__name__, str(e)[:120], flush=True)
                return
            stats["done"] += 1
            for k in ("notes", "kept", "inserted"):
                stats[k] += o[k]
            if stats["done"] % 10 == 0:
                print("progress", json.dumps({**stats, "spent": round(await spent(spent_prefix or run_id), 3)}), flush=True)

    await asyncio.gather(*(one(r) for r in cands))
    stats["spent_usd"] = round(await spent(run_id), 3)
    stats["spent_cap_scope_usd"] = round(await spent(spent_prefix or run_id), 3)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=5.0)
    ap.add_argument("--run", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--types", default=None)
    ap.add_argument("--mode", default="pilot", choices=["pilot", "monitor"])
    ap.add_argument("--cap-scope", default=None, help="run-id prefix whose total spend the cap applies to")
    a = ap.parse_args()
    print("FINAL", json.dumps(asyncio.run(run(a.cap, a.run, types=a.types.split(",") if a.types else None, limit=a.limit,
                                              mode=a.mode, spent_prefix=a.cap_scope))), flush=True)


if __name__ == "__main__":
    main()
