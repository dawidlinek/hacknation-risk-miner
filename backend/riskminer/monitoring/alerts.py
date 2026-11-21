"""Monitoring alerts raised by new documents (docs/impl/new_documents.md §2 step 8, G4). Owner: D (data-db).

Session B's "Co się zmieniło" diff calls `raise_for_document(...)` after a new document produced proposed changes for a
contract or a project. An alert is raised only when the target was ONGOING on the document's date: a contract signed on
or before that date with no performance notice completed before it (completion comes from the BZP performance notice);
a project when any of its contracts was ongoing then (or it has none and its status is not finished). The alert keeps
whether the contract is still open today, so the UI can say "dokument z 05.05.2026 dotyczył umowy w realizacji;
umowę zakończono 01.06.2026".

Provenance: origin CALC, source_id = the document's source, document_id kept; one alert per (document, kind, target)
via `key`, re-raising updates the text but never the expert's status. Alerts from confidential documents are hidden
from callers who cannot see that document (auth.public_doc_filter).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STATUSES = ("new", "seen", "closed")


def _d(x) -> date | None:
    if x is None or isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)[:10]).date()
    except ValueError:
        return None


def _pl(d: date | None) -> str | None:
    return d.strftime("%d.%m.%Y") if d else None


async def contract_state(db: AsyncSession, contract_id: int) -> dict | None:
    r = (await db.execute(text("""
        SELECT c.id, c.procedure_id, c.signed_on, c.planned_end_on, c.contractor_name, p.ocid,
               (SELECT max(pf.completed_on) FROM contract_performance pf WHERE pf.contract_id = c.id AND NOT pf.is_duplicate)
                 AS completed_on,
               (SELECT pp.project_id FROM project_procedure pp WHERE pp.procedure_id = c.procedure_id
                  AND pp.method <> 'cross_reference_related' ORDER BY pp.project_id LIMIT 1) AS project_id
        FROM contract c JOIN procedure p ON p.id = c.procedure_id WHERE c.id = :id"""), {"id": contract_id})).mappings().first()
    return dict(r) if r else None


def ongoing_on(st: dict, as_of: date) -> bool:
    signed, done = st.get("signed_on"), st.get("completed_on")
    return (signed is None or signed <= as_of) and (done is None or done >= as_of)


def _severity(changes: list[dict]) -> str:
    for c in changes:
        if (c.get("delta_days") or 0) >= 30 or (c.get("delta_value_amount") or 0) > 0:
            return "high"
    return "medium"


def _title(target: str, changes: list[dict], doc_date: date | None) -> str:
    what = "; ".join(str(c["summary"]) for c in changes if c.get("summary"))[:240]
    when = f" (dokument z {_pl(doc_date)})" if doc_date else ""
    return f"Nowy dokument zmienia {target} w realizacji{when}" + (f": {what}" if what else "")


async def raise_for_document(db: AsyncSession, *, document_id: int, contract_id: int | None = None,
                             project_id: int | None = None, doc_date: date | str | None = None,
                             changes: list[dict] | None = None, kind: str = "document_change", title: str | None = None,
                             severity: str | None = None, created_by: str = "system:diff") -> dict[str, Any]:
    """Raise (or refresh) the alert for one document and target. Caller commits.

    changes: the diff's change items, e.g. [{"summary": "termin +1 mies. (do 05.06.2026)", "kind": "termin",
    "delta_days": 31}, {"summary": "+151 481,54 zł brutto", "delta_value_amount": 151481.54}].
    Returns {"raised": bool, "alert_id"?, "reason"?, ...}."""
    changes = list(changes or [])
    doc = (await db.execute(text("SELECT id, source_id, title, project_id FROM document WHERE id = :id"),
                            {"id": document_id})).mappings().first()
    if doc is None:
        return {"raised": False, "reason": "no such document"}
    as_of = _d(doc_date) or date.today()
    states: list[dict] = []
    procedure_id = None
    if contract_id is not None:
        st = await contract_state(db, contract_id)
        if st is None:
            return {"raised": False, "reason": "no such contract"}
        states = [st]
        procedure_id = st["procedure_id"]
        project_id = project_id or st["project_id"]
    else:
        project_id = project_id or doc["project_id"]
        if project_id is None:
            return {"raised": False, "reason": "no contract or project to alert on"}
        ids = [r[0] for r in (await db.execute(text("""
            SELECT c.id FROM project_procedure pp JOIN contract c ON c.procedure_id = pp.procedure_id
            WHERE pp.project_id = :p AND pp.method <> 'cross_reference_related'"""), {"p": project_id})).all()]
        states = [s for s in [await contract_state(db, i) for i in ids] if s]
    if contract_id is None and not states:
        status = (await db.execute(text("SELECT status FROM project WHERE id = :p"), {"p": project_id})).scalar()
        ongoing = not str(status or "").lower().startswith("zakończ")
    else:
        ongoing = any(ongoing_on(s, as_of) for s in states)
    if not ongoing:
        return {"raised": False, "reason": f"target not ongoing on {as_of.isoformat()}",
                "contracts": [{"contract_id": s["id"], "completed_on": s["completed_on"]} for s in states]}

    target = "umowę" if contract_id is not None else "projekt"
    still_open = [s["id"] for s in states if s.get("completed_on") is None]
    detail = {"document_id": document_id, "document_title": doc["title"], "doc_date": as_of.isoformat(),
              "changes": changes, "rule": "target ongoing on the document date (signed <= date <= performance notice)",
              "contracts": [{"contract_id": s["id"], "ocid": s["ocid"], "signed_on": s["signed_on"],
                             "planned_end_on": s["planned_end_on"], "completed_on": s["completed_on"],
                             "still_open": s.get("completed_on") is None} for s in states],
              "still_open": bool(still_open)}
    watch_id = (await db.execute(text("""SELECT id FROM monitor_watch WHERE active AND
                                         (contract_id = CAST(:c AS bigint) OR project_id = CAST(:p AS bigint))
                                         ORDER BY id LIMIT 1"""), {"c": contract_id, "p": project_id})).scalar()
    key = f"doc:{document_id}:{kind}:" + (f"c{contract_id}" if contract_id is not None else f"p{project_id}")
    row = (await db.execute(text("""
        INSERT INTO alert (watch_id, kind, title, detail, source_id, status, occurred_at, contract_id, project_id,
                           procedure_id, document_id, severity, origin, key, created_by)
        VALUES (:w, :k, :t, CAST(:d AS jsonb), :sid, 'new', :occ, :c, :p, :proc, :doc, :sev, 'CALC', :key, :by)
        ON CONFLICT (key) DO UPDATE SET title = EXCLUDED.title, detail = EXCLUDED.detail, severity = EXCLUDED.severity,
            watch_id = coalesce(alert.watch_id, EXCLUDED.watch_id), updated_at = now()
        RETURNING id, (xmax = 0) AS inserted"""),
        {"w": watch_id, "k": kind, "t": title or _title(target, changes, _d(doc_date)),
         "d": json.dumps(detail, ensure_ascii=False, default=str), "sid": doc["source_id"], "occ": as_of, "c": contract_id,
         "p": project_id, "proc": procedure_id, "doc": document_id, "sev": severity or _severity(changes), "key": key,
         "by": created_by})).one()
    await db.execute(text("""INSERT INTO audit_log (actor, action, table_name, row_id, after)
                             VALUES (:a, 'monitoring.alert', 'alert', :id, CAST(:after AS jsonb))"""),
                     {"a": created_by, "id": row[0], "after": json.dumps({"key": key, "document_id": document_id,
                                                                          "contract_id": contract_id, "project_id": project_id,
                                                                          "inserted": row[1]}, ensure_ascii=False)})
    return {"raised": True, "alert_id": row[0], "inserted": row[1], "key": key, "still_open": bool(still_open)}


_LIST_SQL = """
SELECT a.id, a.kind, a.title, a.severity, a.status, a.occurred_at, a.created_at, a.updated_at, a.contract_id, a.project_id,
       a.procedure_id, coalesce(a.document_id, d.id) AS document_id, a.detail, a.origin, a.source_id, a.watch_id, pr.rm_id, p.ocid, d.title AS document_title
FROM alert a
LEFT JOIN document d ON d.id = coalesce(a.document_id, CASE WHEN a.detail->>'document_id' ~ '^[0-9]+$'
                                                       THEN (a.detail->>'document_id')::bigint END)
LEFT JOIN project pr ON pr.id = a.project_id
LEFT JOIN procedure p ON p.id = a.procedure_id
WHERE (d.id IS NULL OR {visible}) {extra}
"""


async def list_alerts(db: AsyncSession, visible_sql: str, *, status: str | None = None, contract_id: int | None = None,
                      project_id: int | None = None, rm_id: str | None = None, document_id: int | None = None,
                      limit: int = 50, offset: int = 0) -> dict:
    where, params = [], {"limit": limit, "offset": offset}
    for col, val in (("a.status", status), ("a.contract_id", contract_id), ("a.project_id", project_id),
                     ("a.document_id", document_id), ("pr.rm_id", rm_id)):
        if val is not None:
            k = col.split(".")[1]
            where.append(f"AND {col} = :{k}")
            params[k] = val
    sql = _LIST_SQL.format(visible=visible_sql, extra=" ".join(where))
    total = (await db.execute(text(f"SELECT count(*) FROM ({sql}) x"), params)).scalar()
    rows = (await db.execute(text(sql + " ORDER BY a.occurred_at DESC NULLS LAST, a.id DESC LIMIT :limit OFFSET :offset"),
                             params)).mappings().all()
    items = []
    for r in rows:
        it = dict(r)
        it["document"] = ({"id": r["document_id"], "title": r["document_title"], "href": f"/api/documents/{r['document_id']}"}
                          if r["document_id"] else None)
        it.pop("document_title", None)
        it["card_href"] = f"/projekty/{r['rm_id']}" if r["rm_id"] else None
        it["prov"] = {"origin": r["origin"], "source_id": r["source_id"], "method": "alert: new document vs contract state",
                      "refs": ([{"kind": "document", "id": str(r["document_id"]), "label": r["document_title"]}]
                               if r["document_id"] else [])}
        items.append(it)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def set_status(db: AsyncSession, alert_id: int, status: str, actor: str, request_id: str | None) -> dict | None:
    row = (await db.execute(text("UPDATE alert SET status = :s, updated_at = now() WHERE id = :id RETURNING id, status"),
                            {"s": status, "id": alert_id})).first()
    if not row:
        return None
    await db.execute(text("""INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id)
                             VALUES (:a, 'monitoring.alert_status', 'alert', :id, CAST(:after AS jsonb), :rid)"""),
                     {"a": actor, "id": alert_id, "after": json.dumps({"status": status}), "rid": request_id})
    return {"id": row[0], "status": row[1]}
