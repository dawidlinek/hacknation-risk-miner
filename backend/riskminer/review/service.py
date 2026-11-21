"""Review decisions (approve / edit / reject / mark_gold), undo, skip and link correction.

Rules (docs/impl/api_contract.md §3): one transaction on the request session; every write inserts `review` + `audit_log`;
`riskminer.expert_write` is set only here (common.expert_writes); after each UPDATE the result is re-read and a trigger that
kept OLD becomes a 409 `protected_row`, never a fake "saved"."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.auth import ApiError
from riskminer.review import cards
from riskminer.review.common import (audit, expert_writes, fetch_row, insert_row, jclean, jdump, update_fields)

UNDO_MINUTES = 15
CODE_RE = re.compile(r"^\s*(R\d{1,2}(?:\.\d+)?)\b\s*(.*)$", re.S)


async def _rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def _scalar(db: AsyncSession, sql: str, **p) -> Any:
    return (await db.execute(text(sql), p)).scalar()


@dataclass
class Result:
    changes: list[dict] = field(default_factory=list)   # [{table, id, before: {..}|None (row created), after: {..}}]
    resolution: dict = field(default_factory=dict)
    target_table: str | None = None
    target_id: int | None = None
    undoable: bool = True


@dataclass
class Ctx:
    db: AsyncSession
    item: dict
    target: dict | None
    option: dict
    action: str
    value: Any
    reason: str | None
    actor: str
    request_id: str | None


def _applied(changes: list[dict]) -> list[dict]:
    out = []
    for c in changes:
        for f, after in (c.get("after") or {}).items():
            before = (c.get("before") or {}).get(f)
            out.append({"table": c["table"], "id": c["id"], "field": f, "before": before, "after": after})
    return out


def _change(table: str, row_id: int, before: dict | None, after: dict) -> dict:
    return {"table": table, "id": row_id, "before": jclean(before), "after": jclean(after)}


async def _set(db: AsyncSession, table: str, row_id: int, fields: dict) -> dict:
    """Update fields on a row and return the change record (before snapshot taken here)."""
    cur = await fetch_row(db, table, row_id, list(fields))
    if cur is None:
        raise ApiError(404, "Nie znaleziono rekordu.", "not_found")
    await update_fields(db, table, row_id, fields)
    return _change(table, row_id, cur, fields)


# ------------------------------------------------------------------------------------------------------------ helpers

def _text_value(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("value") or v.get("text") or "")
    return "" if v is None else str(v)


async def _approved_risk(db: AsyncSession, code: str) -> dict:
    rs = await _rows(db, "SELECT code, name FROM catalogue_risk WHERE sector='wod-kan' AND code=:c AND status='approved' "
                         "ORDER BY version DESC LIMIT 1", c=code)
    if not rs:
        raise ApiError(422, f"Ryzyko {code} nie istnieje w zatwierdzonym katalogu.", "bad_code")
    return rs[0]


async def resolve_bzp(db: AsyncSession, bzp: str) -> dict:
    """BZP number (with or without the /01 version suffix) -> {ocid, procedure_id}."""
    n = bzp.strip()
    base = re.sub(r"/\d+$", "", n)
    rs = await _rows(db, """SELECT pr.id AS procedure_id, pr.ocid FROM procedure pr
                            WHERE pr.contract_notice_no = :b OR pr.ocid IN (SELECT ocid FROM notice WHERE bzp_number = :b AND ocid IS NOT NULL)
                            ORDER BY pr.id LIMIT 1""", b=base)
    if not rs:
        raise ApiError(404, f"Nie znaleziono postępowania dla numeru {n}.", "bzp_not_found")
    return rs[0]


# ------------------------------------------------------------------------------------------------------ link correction

async def link_correct(db: AsyncSession, *, rm_id: str, action: str, bzp_number: str | None, lots: list[int] | None,
                       reason: str | None, actor: str, request_id: str | None, review_item_id: int | None = None,
                       write_records: bool = True) -> dict:
    """Expert link correction: replace | add | remove a project -> procedure link. Writes review + audit."""
    if action not in ("replace", "add", "remove"):
        raise ApiError(422, "Nieznana czynność.", "bad_action")
    proj = await _rows(db, "SELECT id, rm_id FROM project WHERE rm_id = :r", r=rm_id)
    if not proj:
        raise ApiError(404, "Nie ma takiego projektu.", "not_found")
    pid = proj[0]["id"]
    if not bzp_number:
        raise ApiError(422, "Podaj numer ogłoszenia BZP.", "bzp_required")
    target = await resolve_bzp(db, bzp_number)
    changes: list[dict] = []
    async with expert_writes(db):
        existing = await _rows(db, "SELECT * FROM project_procedure WHERE project_id=:p", p=pid)
        mine = next((e for e in existing if e["procedure_id"] == target["procedure_id"]), None)
        if action == "remove":
            if not mine:
                raise ApiError(404, "Ten projekt nie jest powiązany z tym postępowaniem.", "not_found")
            changes.append(await _set(db, "project_procedure", mine["id"], {"review_status": "rejected"}))
            pp_id = mine["id"]
        else:
            if action == "replace":
                for e in existing:
                    if e["procedure_id"] != target["procedure_id"] and e["review_status"] != "rejected":
                        changes.append(await _set(db, "project_procedure", e["id"], {"review_status": "rejected"}))
            cand_id = await _scalar(db, """
                INSERT INTO link_candidate (left_table, left_id, right_table, right_id, right_ref, method, score, rank, explanation, decision, review_status)
                VALUES ('project', :p, 'procedure', :prid, :ocid, 'expert', 1.0, 0, :expl, 'accept', 'approved')
                ON CONFLICT (left_table, left_id, right_table, right_ref, method) DO UPDATE SET review_status = 'approved'
                RETURNING id""", p=pid, prid=target["procedure_id"], ocid=target["ocid"], expl=reason or "powiązanie wskazane przez eksperta")
            fields = {"method": "expert", "score": 1.0, "review_status": "approved", "origin": "SOURCE", "link_candidate_id": cand_id,
                      "explanation": {"by": actor, "reason": reason}}
            if lots is not None:
                fields["lots"] = lots
            if mine:
                changes.append(await _set(db, "project_procedure", mine["id"], fields))
                pp_id = mine["id"]
            else:
                pp_id = await insert_row(db, "project_procedure", {"project_id": pid, "procedure_id": target["procedure_id"], **fields})
                changes.append(_change("project_procedure", pp_id, None, fields))
        closed = [r["id"] for r in await _rows(db, """
            UPDATE review_item SET status='resolved', resolved_by=:a, resolved_at=now(), updated_at=now(),
                   detail = detail || CAST(:res AS jsonb)
            WHERE project_id=:p AND status='open' AND kind='discrepancy' AND code IN ('part_mismatch','contract_notice_missing','part_scope_wider')
              AND (CAST(:own AS bigint) IS NULL OR id <> :own)
            RETURNING id""", a=actor, p=pid, res=jdump({"resolution": {"option": "link_corrected", "by": actor, "bzp_number": bzp_number}}),
                                          own=review_item_id)]
    review_id = None
    if write_records:  # callers inside decide() write their own review + audit rows
      review_id = await _scalar(db, """INSERT INTO review (target_table, target_id, review_item_id, action, option_key, before, after, reviewer, comment, request_id)
        VALUES ('project_procedure', :t, :ri, 'edit', :opt, CAST(:b AS jsonb), CAST(:a AS jsonb), :rev, :c, :req) RETURNING id""",
                              t=pp_id, ri=review_item_id, opt=f"link_{action}", b=jdump({"changes": [{"table": c["table"], "id": c["id"], "fields": c["before"]} for c in changes]}),
                              a=jdump({"changes": [{"table": c["table"], "id": c["id"], "fields": c["after"]} for c in changes]}),
                              rev=actor, c=reason, req=request_id)
      await audit(db, actor, "link.correct", "project_procedure", pp_id, {"changes": [c["before"] for c in changes]},
                  {"action": action, "bzp_number": bzp_number, "ocid": target["ocid"], "lots": lots}, request_id, reason)
    link = (await _rows(db, "SELECT pp.*, pr.ocid FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id WHERE pp.id=:i", i=pp_id))[0]
    return {"project_procedure": {"procedure_id": link["procedure_id"], "ocid": link["ocid"], "method": link["method"], "score": link["score"],
                                  "explanation": link["explanation"] or {}, "lots": link["lots"] or [], "review_status": link["review_status"]},
            "review_id": review_id, "closed_review_items": closed, "_changes": changes}


# ------------------------------------------------------------------------------------------------------ per-kind apply

async def _apply_event(c: Ctx) -> Result:
    t = c.target
    if t is None:
        raise ApiError(404, "Nie znaleziono zdarzenia.", "not_found")
    r = Result(target_table="risk_event", target_id=t["id"])
    if c.action == "approve":
        code = c.option["key"] if CODE_RE.match(c.option["key"]) else t.get("catalogue_code")
        if code:
            await _approved_risk(c.db, code)
        fields = {"review_status": "approved", **({"catalogue_code": code} if code else {})}
        r.resolution = {"option": c.option["key"], "catalogue_code": code}
    elif c.action == "edit":
        m = CODE_RE.match(_text_value(c.value))
        if not m:
            raise ApiError(422, "Podaj kod ryzyka z katalogu, np. R04.", "bad_code")
        await _approved_risk(c.db, m.group(1))
        fields = {"review_status": "edited", "catalogue_code": m.group(1)}
        r.resolution = {"option": "other", "catalogue_code": m.group(1), "note": m.group(2).strip() or None}
    else:
        fields = {"review_status": "rejected"}
        r.resolution = {"option": c.option["key"], "reason": c.reason}
    r.changes.append(await _set(c.db, "risk_event", t["id"], fields))
    await _mirror_cause_ai(c.db, t, fields, r)
    return r


async def _mirror_cause_ai(db: AsyncSession, ev: dict, fields: dict, r: Result) -> None:
    """Keep L's national cause table in step: the expert's decision on a risk_event is mirrored into change_cause_ai
    (review_status, and primary_code when the code changed) for the row behind this change (view v_change_cause_ai)."""
    if not ev.get("change_id") or not await _scalar(db, "SELECT to_regclass('change_cause_ai') IS NOT NULL AND to_regclass('v_change_cause_ai') IS NOT NULL"):
        return
    row = await _rows(db, "SELECT cause_ai_id FROM v_change_cause_ai WHERE change_id = :c LIMIT 1", c=ev["change_id"])
    if not row or row[0]["cause_ai_id"] is None:
        return
    upd = {"review_status": fields["review_status"]}
    if fields.get("catalogue_code"):
        upd["primary_code"] = fields["catalogue_code"]
    r.changes.append(await _set(db, "change_cause_ai", row[0]["cause_ai_id"], upd))


async def _apply_link(c: Ctx) -> Result:
    t = c.target
    if t is None:
        raise ApiError(404, "Nie znaleziono kandydata powiązania.", "not_found")
    r = Result(target_table="link_candidate", target_id=t["id"])
    proj_id = t["left_id"] if t["left_table"] == "project" else c.item.get("project_id")
    if t["left_table"] == "document":  # document -> contract proposal (doclink): accept keeps the change on that contract, reject detaches it
        if c.action == "edit":
            raise ApiError(422, "Inną umowę wskaż w Przeglądzie jako odrzucenie i dopisz uwagę.", "unsupported")
        new_status = "approved" if c.action == "approve" else "rejected"
        r.changes.append(await _set(c.db, "link_candidate", t["id"], {"review_status": new_status}))
        if c.action == "reject":
            for ch in await _rows(c.db, "SELECT id FROM contract_change WHERE document_id = :d AND kind = 'document_change' AND contract_id = :c",
                                  d=t["left_id"], c=t.get("right_id")):
                r.changes.append(await _set(c.db, "contract_change", ch["id"], {"contract_id": None}))
        r.resolution = {"option": c.option["key"], "reason": c.reason, "document_id": t["left_id"], "contract_id": t.get("right_id")}
        return r
    if c.action == "approve":
        r.changes.append(await _set(c.db, "link_candidate", t["id"], {"review_status": "approved"}))
        if t["left_table"] == "project" and t["right_table"] == "procedure" and t.get("right_id"):
            ex = await _rows(c.db, "SELECT id FROM project_procedure WHERE project_id=:p AND procedure_id=:q", p=proj_id, q=t["right_id"])
            f = {"method": "expert", "score": t.get("score"), "review_status": "approved", "origin": "SOURCE", "link_candidate_id": t["id"]}
            if ex:
                r.changes.append(await _set(c.db, "project_procedure", ex[0]["id"], f))
            else:
                new_id = await insert_row(c.db, "project_procedure", {"project_id": proj_id, "procedure_id": t["right_id"], **f})
                r.changes.append(_change("project_procedure", new_id, None, f))
        r.resolution = {"option": "accept", "ocid": t.get("right_ref")}
    elif c.action == "edit":
        rm = c.item.get("rm_id")
        res = await link_correct(c.db, rm_id=rm, action="replace", bzp_number=_text_value(c.value), lots=None, reason=c.reason,
                                 actor=c.actor, request_id=c.request_id, review_item_id=c.item["id"], write_records=False)
        r.changes = res.pop("_changes")
        r.changes.append(await _set(c.db, "link_candidate", t["id"], {"review_status": "rejected"}))
        r.resolution = {"option": "other", "bzp_number": _text_value(c.value)}
    else:
        rows = await _rows(c.db, "SELECT id FROM link_candidate WHERE left_table='project' AND left_id=:p AND right_table='procedure' "
                                 "AND review_status='proposed'", p=proj_id)
        for rr in rows:
            r.changes.append(await _set(c.db, "link_candidate", rr["id"], {"review_status": "rejected"}))
        if not any(x["id"] == t["id"] for x in r.changes):
            r.changes.append(await _set(c.db, "link_candidate", t["id"], {"review_status": "rejected"}))
        r.resolution = {"option": "none", "reason": c.reason}
    return r


async def _apply_discrepancy(c: Ctx) -> Result:
    r = Result(target_table=c.item.get("target_table") or "review_item", target_id=c.item.get("target_id") or c.item["id"])
    key, det = c.option["key"], c.item.get("detail") or {}
    r.resolution = {"option": key, "reason": c.reason}
    if key == "use_matched":
        parts = [int(x) for x in (det.get("matched_parts") or [])]
        links = await _rows(c.db, "SELECT id FROM project_procedure WHERE project_id=:p AND review_status <> 'rejected'", p=c.item.get("project_id"))
        if not links:
            raise ApiError(409, "Projekt nie ma powiązanego postępowania, części nie ma do czego przypisać.", "no_link")
        for l in links[:1]:
            r.changes.append(await _set(c.db, "project_procedure", l["id"], {"lots": parts}))
        r.resolution["lots"] = parts
    elif key == "link_other":
        res = await link_correct(c.db, rm_id=c.item["rm_id"], action="replace", bzp_number=_text_value(c.value), lots=None, reason=c.reason,
                                 actor=c.actor, request_id=c.request_id, review_item_id=c.item["id"], write_records=False)
        r.changes = res.pop("_changes")
        r.resolution["bzp_number"] = _text_value(c.value)
    return r


async def _apply_fact(c: Ctx) -> Result:
    t, item = c.target, c.item
    if t is None or not item.get("target_table"):
        raise ApiError(404, "Nie znaleziono faktu.", "not_found")
    table, fld = item["target_table"], item.get("target_field")
    r = Result(target_table=table, target_id=t["id"])
    if c.action == "approve":
        fields = {"review_status": "approved"}
    elif c.action == "edit":
        if not fld:
            raise ApiError(422, "Ten fakt nie ma pola do poprawienia.", "bad_field")
        fields = {fld: _text_value(c.value), "review_status": "edited"}
    else:
        fields = {"review_status": "rejected"}
    r.changes.append(await _set(c.db, table, t["id"], fields))
    if c.action == "edit":
        await c.db.execute(text("""INSERT INTO evidence (claim_table, claim_id, claim_field, verification, note)
                                   VALUES (:t, :i, :f, 'structured_field', :n)"""),
                           {"t": table, "i": t["id"], "f": fld, "n": f"ekspert: {c.reason or _text_value(c.value)}"[:500]})
    r.resolution = {"option": c.option["key"], "reason": c.reason, "value": _text_value(c.value) if c.action == "edit" else None}
    return r


async def _apply_catalogue(c: Ctx) -> Result:
    from riskminer.review import catalogue as K
    t = c.target
    if t is None:
        raise ApiError(404, "Nie znaleziono propozycji.", "not_found")
    r = Result(target_table="catalogue_risk", target_id=t["id"], undoable=False)
    key = c.option["key"]
    if key.startswith("merge:") or c.action == "edit":
        into = key.split(":", 1)[1] if key.startswith("merge:") else _text_value(c.value).strip()
        r.changes = await K.merge_proposal(c.db, t, into, c.actor, c.request_id)
        r.resolution = {"option": "merge", "merged_into": into}
    elif c.action == "approve":
        r.changes = await K.approve_proposal(c.db, t, c.actor, c.request_id)
        r.resolution = {"option": "add"}
    else:
        r.changes = await K.reject_proposal(c.db, t, c.reason, c.actor, c.request_id)
        r.resolution = {"option": "reject", "reason": c.reason}
    return r


async def _apply_generic(c: Ctx) -> Result:
    r = Result(target_table=c.item.get("target_table") or "review_item", target_id=c.item.get("target_id") or c.item["id"])
    r.resolution = {"option": c.option["key"], "reason": c.reason}
    return r


APPLY = {"event": _apply_event, "link": _apply_link, "discrepancy": _apply_discrepancy, "fact": _apply_fact,
         "catalogue": _apply_catalogue}


# ------------------------------------------------------------------------------------------------------------- decide

async def _next_item(db: AsyncSession, current: dict) -> int | None:
    return await _scalar(db, """SELECT id FROM review_item WHERE status='open' AND id <> :id
                                ORDER BY (detail ? 'skipped_at'), (kind <> :k), id LIMIT 1""", id=current["id"], k=current["kind"])


async def decide(db: AsyncSession, item_id: int, *, actor: str, option: str | None, action: str | None, value: Any = None,
                 reason: str | None = None, gold: bool = False, request_id: str | None = None) -> dict:
    item = await cards.load_item(db, item_id, lock=True)
    if item is None:
        raise ApiError(404, "Nie ma takiej sprawy.", "not_found")
    if item["status"] != "open":
        raise ApiError(409, "Ta sprawa została już rozstrzygnięta.", "already_resolved")
    card = await cards.build_card(db, item)
    opts = {o["key"]: o for o in card["options"]}
    opt = opts.get(option or "")
    if opt is None:
        if action in ("edit", "reject", "approve") and option:
            opt = {"key": option, "action": action, "needs_input": None if option.startswith("merge:") else ("value" if action == "edit" else ("reason" if action == "reject" else None)),
                   "effects": []}
        else:
            raise ApiError(422, "Wybierz jedną z opcji.", "bad_option")
    action = action or opt["action"]
    if action != opt["action"]:
        raise ApiError(422, "Czynność nie pasuje do wybranej opcji.", "bad_action")
    if action == "reject" and not (reason or "").strip():
        raise ApiError(422, "Podaj powód odrzucenia.", "reason_required")
    if opt.get("needs_input") == "value" and not _text_value(value).strip():
        raise ApiError(422, "Podaj wartość.", "value_required")
    if opt.get("needs_input") == "reason" and not (reason or "").strip() and action != "reject":
        raise ApiError(422, "Podaj uzasadnienie.", "reason_required")
    if gold and action == "reject":
        gold = False

    target = None
    if item.get("target_table") and item.get("target_id"):
        try:
            target = await fetch_row(db, item["target_table"], item["target_id"])
        except ApiError:
            target = None
    ctx = Ctx(db, item, target, opt, action, value, reason, actor, request_id)
    item_before = {"status": item["status"], "resolved_by": item.get("resolved_by"), "resolution": (item.get("detail") or {}).get("resolution")}
    async with expert_writes(db):
        res = await APPLY.get(item["kind"], _apply_generic)(ctx)

    before = {"changes": [{"table": c["table"], "id": c["id"], "fields": c["before"]} for c in res.changes], "item": item_before}
    after = {"changes": [{"table": c["table"], "id": c["id"], "fields": c["after"]} for c in res.changes], "resolution": res.resolution}
    review_id = await _scalar(db, """INSERT INTO review (target_table, target_id, review_item_id, action, option_key, before, after, reviewer, comment, request_id)
        VALUES (:tt, :ti, :ri, :act, :opt, CAST(:b AS jsonb), CAST(:a AS jsonb), :rev, :c, :req) RETURNING id""",
                              tt=res.target_table or "review_item", ti=res.target_id or item_id, ri=item_id, act=action, opt=opt["key"],
                              b=jdump(before), a=jdump(after), rev=actor, c=reason or (_text_value(value) if action == "edit" else None), req=request_id)
    await db.execute(text("""UPDATE review_item SET status='resolved', resolved_by=:a, resolved_at=now(), updated_at=now(),
                             detail = detail || CAST(:res AS jsonb) WHERE id=:i"""),
                     {"a": actor, "i": item_id, "res": jdump({"resolution": {**res.resolution, "review_id": review_id, "by": actor}})})
    await audit(db, actor, f"review.{action}", res.target_table, res.target_id, before, after, request_id, f"sprawa #{item_id}: {item['title'][:120]}")

    gold_out = None
    if gold:
        gold_out = await _mark_gold(db, item, card, opt, action, value, res, review_id, actor, request_id)
    marked: list[str] = []
    if (item.get("key") or "").startswith("doc:") and action in ("approve", "edit"):
        if not gold and item["kind"] in ("event", "fact"):
            await _document_gold(db, item, card, action, value, res, review_id, actor, request_id)
        if item["kind"] in ("event", "fact") and item.get("rm_id"):  # approved new facts of a project: analyses that cite it as a similar case are stale
            from riskminer.analysis import service as ASV
            det = item.get("detail") or {}
            try:
                marked = await ASV.mark_affected(db, rm_id=item["rm_id"], reason=item["title"][:160], actor=actor, document_id=det.get("document_id"), request_id=request_id)
            except Exception:  # analysis tables are optional for the review path
                marked = []
    return {"item_id": item_id, "review_id": review_id,
            "review_status": {"approve": "approved", "edit": "edited", "reject": "rejected"}[action] if res.target_table != "review_item" else None,
            "applied": _applied(res.changes), "effects": opt.get("effects") or [], "gold": gold_out, "analyses_marked": marked,
            "undo_until": (datetime.now(timezone.utc) + timedelta(minutes=UNDO_MINUTES)).isoformat() if res.undoable else None,
            "next_item_id": await _next_item(db, item)}


async def _document_gold(db, item, card, action, value, res: Result, review_id, actor, request_id) -> None:
    """Learning loop: an approved or edited document-derived proposal is a gold example for the LLM session's `document_facts` task
    (task 'document_facts', input = the verified quote, output = the decided value). No rescore job: the extractor reads these as few-shot."""
    ev = card.get("evidence") or {}
    quote = " ".join(x for x in (ev.get("pre"), ev.get("hit"), ev.get("post")) if x).strip() or item["title"]
    det = item.get("detail") or {}
    out = {"document_id": det.get("document_id"), "item_code": item.get("code"), "action": action, "value": jclean(value),
           "resolution": res.resolution, "source": "document", "page": (ev.get("ref") or {}).get("page_no"), "verification": ev.get("verification")}
    gid = await _scalar(db, """INSERT INTO gold_example (task, catalogue_code, input_text, output, target_table, target_id, review_id, created_by)
                               VALUES ('document_facts', :code, :inp, CAST(:out AS jsonb), :tt, :ti, :rv, :by) RETURNING id""",
                        code=(lambda c: c if c and CODE_RE.match(c) else None)(res.resolution.get("catalogue_code") or item.get("model_pick")), inp=quote[:4000], out=jdump(out), tt=res.target_table,
                        ti=res.target_id, rv=review_id, by=actor)
    await db.execute(text("""INSERT INTO review (target_table, target_id, review_item_id, action, option_key, after, reviewer, comment, request_id)
                             VALUES (:tt, :ti, :ri, 'mark_gold', 'document_facts', CAST(:a AS jsonb), :rev, 'wzorzec z dokumentu', :req)"""),
                     {"tt": res.target_table or "review_item", "ti": res.target_id or item["id"], "ri": item["id"], "a": jdump({"gold_example_id": gid}),
                      "rev": actor, "req": request_id})
    await audit(db, actor, "review.mark_gold", "gold_example", gid, None, {"task": "document_facts", "review_id": review_id}, request_id)


async def _mark_gold(db, item, card, opt, action, value, res: Result, review_id, actor, request_id) -> dict:
    ev = card.get("evidence") or {}
    quote = " ".join(x for x in (ev.get("pre"), ev.get("hit"), ev.get("post")) if x).strip() or item["title"]
    out = {"option": opt["key"], "action": action, "value": jclean(value), "resolution": res.resolution}
    code = res.resolution.get("catalogue_code")
    gid = await _scalar(db, """INSERT INTO gold_example (task, catalogue_code, input_text, output, target_table, target_id, review_id, created_by)
                               VALUES (:task, :code, :inp, CAST(:out AS jsonb), :tt, :ti, :rv, :by) RETURNING id""",
                        task=f"review:{item['kind']}", code=code, inp=quote[:4000], out=jdump(out), tt=res.target_table, ti=res.target_id,
                        rv=review_id, by=actor)
    gold_review = await _scalar(db, """INSERT INTO review (target_table, target_id, review_item_id, action, option_key, before, after, reviewer, comment, request_id)
        VALUES (:tt, :ti, :ri, 'mark_gold', :opt, NULL, CAST(:a AS jsonb), :rev, 'wzorcowy przykład', :req) RETURNING id""",
                               tt=res.target_table or "review_item", ti=res.target_id or item["id"], ri=item["id"], opt=opt["key"],
                               a=jdump({"gold_example_id": gid}), rev=actor, req=request_id)
    pending = await _scalar(db, "SELECT count(*) FROM review_item WHERE kind=:k AND status='open' AND id <> :i", k=item["kind"], i=item["id"]) or 0
    if item["kind"] == "event" and res.target_table == "risk_event":  # L's handler: llm_rescore_gold {risk_event_id, code}
        jkind, payload = "llm_rescore_gold", {"risk_event_id": res.target_id, "code": code, "gold_example_id": gid}
    else:
        jkind, payload = "rescore_gold", {"gold_example_id": gid, "kind": item["kind"], "limit": 20}
    job_id = await _scalar(db, "INSERT INTO job (kind, payload, priority, created_by) VALUES (:k, CAST(:p AS jsonb), 50, :by) RETURNING id",
                           k=jkind, p=jdump(payload), by=actor)
    await audit(db, actor, "review.mark_gold", "gold_example", gid, None, {"review_id": gold_review, "job_id": job_id}, request_id)
    return {"gold_example_id": gid, "job_id": job_id, "similar_pending": pending}


# --------------------------------------------------------------------------------------------------------- skip / undo

async def skip(db: AsyncSession, item_id: int, *, actor: str, request_id: str | None = None) -> dict:
    item = await cards.load_item(db, item_id, lock=True)
    if item is None:
        raise ApiError(404, "Nie ma takiej sprawy.", "not_found")
    if item["status"] != "open":
        raise ApiError(409, "Ta sprawa została już rozstrzygnięta.", "already_resolved")
    await db.execute(text("UPDATE review_item SET detail = detail || CAST(:d AS jsonb), updated_at=now() WHERE id=:i"),
                     {"i": item_id, "d": jdump({"skipped_at": datetime.now(timezone.utc).isoformat(), "skipped_by": actor})})
    await audit(db, actor, "review.skip", "review_item", item_id, None, {"skipped": True}, request_id)
    return {"next_item_id": await _next_item(db, item)}


async def undo(db: AsyncSession, review_id: int, *, actor: str, request_id: str | None = None) -> dict:
    rv = await _rows(db, "SELECT * FROM review WHERE id = :i FOR UPDATE", i=review_id)
    if not rv:
        raise ApiError(404, "Nie ma takiej decyzji.", "not_found")
    rv = rv[0]
    if rv["action"] not in ("approve", "edit", "reject") or rv.get("undo_of"):
        raise ApiError(409, "Tej decyzji nie można cofnąć.", "not_undoable")
    if rv["reviewer"] != actor:
        raise ApiError(403, "Możesz cofnąć tylko własną decyzję.", "not_owner")
    if rv["created_at"] < datetime.now(timezone.utc) - timedelta(minutes=UNDO_MINUTES):
        raise ApiError(409, f"Minęło {UNDO_MINUTES} minut, decyzji nie można już cofnąć.", "undo_expired")
    if await _scalar(db, "SELECT count(*) FROM review WHERE undo_of = :i", i=review_id):
        raise ApiError(409, "Ta decyzja została już cofnięta.", "already_undone")
    if (rv.get("option_key") or "").startswith("catalogue"):
        raise ApiError(409, "Zmian w katalogu nie cofa się tutaj, przywróć wersję katalogu.", "not_undoable")
    return await revert(db, rv, actor=actor, request_id=request_id, option_key="undo", comment=f"cofnięcie decyzji #{review_id}", audit_action="review.undo")


async def revert(db: AsyncSession, rv: dict, *, actor: str, request_id: str | None, option_key: str, comment: str, audit_action: str) -> dict:
    """Restore everything a decision changed (review.before) and reopen its queue item, by appending a compensating review row.
    Shared by undo (15 min, same reviewer) and the admin demo reset (no window). Nothing is deleted except rows the decision itself created."""
    review_id = rv["id"]
    before = rv["before"] or {}
    restored = []
    async with expert_writes(db):
        for ch in reversed(before.get("changes") or []):
            if ch["fields"] is None:
                if ch["table"] in ("project_procedure", "link_candidate"):  # rows created by the decision
                    await db.execute(text(f"DELETE FROM {ch['table']} WHERE id = :i"), {"i": ch["id"]})
                restored.append({"table": ch["table"], "id": ch["id"], "deleted": True})
            else:
                await update_fields(db, ch["table"], ch["id"], ch["fields"])
                restored.append({"table": ch["table"], "id": ch["id"], "fields": ch["fields"]})
    new_id = await _scalar(db, """INSERT INTO review (target_table, target_id, review_item_id, action, option_key, before, after, reviewer, comment, undo_of, request_id)
        VALUES (:tt, :ti, :ri, 'edit', :opt, CAST(:b AS jsonb), CAST(:a AS jsonb), :rev, :c, :u, :req) RETURNING id""",
                           tt=rv["target_table"], ti=rv["target_id"], ri=rv["review_item_id"], b=jdump(rv["after"]), a=jdump(rv["before"]),
                           rev=actor, c=comment, u=review_id, req=request_id, opt=option_key)
    if rv["review_item_id"]:
        prior = (before.get("item") or {}).get("resolution")
        await db.execute(text("""UPDATE review_item SET status='open', resolved_by=NULL, resolved_at=NULL, updated_at=now(),
                                 detail = CASE WHEN CAST(:p AS jsonb) IS NULL THEN detail - 'resolution'
                                               ELSE jsonb_set(detail, '{resolution}', CAST(:p AS jsonb)) END WHERE id=:i"""),
                         {"i": rv["review_item_id"], "p": jdump(prior) if prior else None})
    await db.execute(text("""UPDATE gold_example SET output = output || '{"retracted": true}'::jsonb WHERE review_id = :r"""), {"r": review_id})
    await audit(db, actor, audit_action, rv["target_table"], rv["target_id"], rv["after"], rv["before"], request_id, comment)
    return {"review_id": new_id, "undone_review_id": review_id, "restored": restored}


# ------------------------------------------------------------------------------------------------- restore from audit

async def restore_from_audit(db: AsyncSession, audit_id: int, *, reason: str, actor: str, request_id: str | None = None) -> dict:
    """Re-apply the values an expert decision overwrote (audit row `before`). A new edit: the review and audit rows are appended,
    nothing is deleted. 409 when the row changed after that decision."""
    from riskminer.api import audit_read as AR
    rows = await _rows(db, "SELECT * FROM audit_log WHERE id = :i", i=audit_id)
    if not rows:
        raise ApiError(404, "Nie ma takiego wpisu w dzienniku.", "not_found")
    row = rows[0]
    if not AR.restorable(row):
        raise ApiError(409, "Tego wpisu nie można przywrócić.", "not_restorable")
    if await _scalar(db, "SELECT count(*) FROM audit_log WHERE action = 'audit.restore' AND (after->>'restored_audit_id')::bigint = :i", i=audit_id):
        raise ApiError(409, "Ten wpis został już przywrócony.", "already_restored")
    befores = row["before"]["changes"]
    afters = {(c["table"], c["id"]): c.get("fields") or {} for c in (row["after"] or {}).get("changes") or []}
    restored, before_now = [], []
    async with expert_writes(db):
        for ch in befores:
            if not ch.get("fields"):
                continue  # created rows are not removed by a restore
            cur = await fetch_row(db, ch["table"], ch["id"], list(ch["fields"]))
            if cur is None:
                raise ApiError(404, "Rekord już nie istnieje.", "not_found")
            expect = afters.get((ch["table"], ch["id"]), {})
            from riskminer.review.common import _norm
            if any(_norm(cur.get(k)) != _norm(v) for k, v in expect.items()):
                raise ApiError(409, "Rekord zmienił się po tej decyzji, przywrócenie nadpisałoby nowszą zmianę.", "stale")
            await update_fields(db, ch["table"], ch["id"], ch["fields"])
            before_now.append({"table": ch["table"], "id": ch["id"], "fields": jclean(cur)})
            restored.append({"table": ch["table"], "row_id": ch["id"], "fields": ch["fields"]})
    if not restored:
        raise ApiError(409, "Tego wpisu nie można przywrócić.", "not_restorable")
    first = restored[0]
    review_id = await _scalar(db, """INSERT INTO review (target_table, target_id, action, option_key, before, after, reviewer, comment, request_id)
        VALUES (:tt, :ti, 'edit', 'restore', CAST(:b AS jsonb), CAST(:a AS jsonb), :rev, :c, :req) RETURNING id""",
                              tt=first["table"], ti=first["row_id"], b=jdump({"changes": before_now}),
                              a=jdump({"changes": [{"table": r["table"], "id": r["row_id"], "fields": r["fields"]} for r in restored]}),
                              rev=actor, c=reason, req=request_id)
    new_audit = await audit(db, actor, "audit.restore", first["table"], first["row_id"], {"changes": before_now},
                            {"restored_audit_id": audit_id, "changes": [{"table": r["table"], "id": r["row_id"], "fields": r["fields"]} for r in restored]},
                            request_id, reason)
    return {"review_id": review_id, "audit_id": new_audit, "restored": restored[0] if len(restored) == 1 else restored}
