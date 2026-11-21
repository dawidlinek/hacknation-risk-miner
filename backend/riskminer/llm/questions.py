"""Question records (api_contract §3.4): every /ask and chat answer is a draft `question` row; saving assigns Q-YYYY-NNNN.
Writes use the caller's AsyncSession so API tests roll back."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


async def store(db: AsyncSession, *, kind: str, question: str, answer: dict, owner: str, scope: dict | None = None,
                sql: str | None = None, rows: list[dict] | None = None, llm_call_id: int | None = None,
                parent_id: int | None = None, title: str | None = None) -> int:
    qid = (await db.execute(text(
        "INSERT INTO question (kind, title, question_text, scope, answer, sql, rows, role, n, llm_call_id, owner, "
        "data_as_of, parent_id) VALUES (:k, :t, :q, CAST(:s AS jsonb), CAST(:a AS jsonb), :sql, CAST(:r AS jsonb), :role, "
        ":n, :lc, :o, now(), :p) RETURNING id"),
        {"k": kind, "t": title, "q": question[:4000], "s": _j(scope or {}), "a": _j(answer), "sql": sql,
         "r": _j((rows or [])[:200]) if rows is not None else None, "role": answer.get("role"), "n": answer.get("n"),
         "lc": llm_call_id, "o": owner, "p": parent_id})).scalar_one()
    return int(qid)


async def get(db: AsyncSession, *, qid: int | None = None, code: str | None = None) -> dict | None:
    if qid is not None:
        r = (await db.execute(text("SELECT * FROM question WHERE id = :i"), {"i": qid})).mappings().first()
    else:
        r = (await db.execute(text("SELECT * FROM question WHERE code = :c ORDER BY id DESC LIMIT 1"), {"c": code})).mappings().first()
    return dict(r) if r else None


async def save(db: AsyncSession, qid: int, title: str | None, actor: str, request_id: str | None) -> dict:
    q = await get(db, qid=qid)
    if q is None:
        raise KeyError(qid)
    if q["code"]:
        return {"code": q["code"], "title": q["title"], "saved_at": q["saved_at"]}
    code = (await db.execute(text("SELECT rm_next_code('Q')"))).scalar_one()
    t = (title or q["title"] or (q["answer"] or {}).get("title") or q["question_text"])[:200]
    now = datetime.now(UTC)
    ans = dict(q["answer"] or {})
    ans["code"] = code
    await db.execute(text("UPDATE question SET code = :c, status = 'saved', title = :t, saved_at = :n, "
                          "answer = CAST(:a AS jsonb) WHERE id = :i"), {"c": code, "t": t, "n": now, "a": _j(ans), "i": qid})
    await db.execute(text("INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id) "
                          "VALUES (:a, 'question.save', 'question', :i, CAST(:x AS jsonb), :r)"),
                     {"a": actor[:80], "i": qid, "x": _j({"code": code, "title": t}), "r": request_id})
    return {"code": code, "title": t, "saved_at": now}


def answer_of(q: dict) -> dict:
    a = dict(q["answer"] or {})
    a["id"] = f"q{q['id']}"
    a["code"] = q["code"]
    a.pop("fact_ids", None)
    a.pop("title", None)
    return a


async def listing(db: AsyncSession, owner: str, mine: bool, limit: int, offset: int) -> dict:
    where = "status = 'saved' AND " + ("owner = :o" if mine else "(owner = :o OR owner LIKE 'user:%')")
    total = (await db.execute(text(f"SELECT count(*) FROM question WHERE {where}"), {"o": owner})).scalar_one()
    rows = (await db.execute(text(f"SELECT code, title, saved_at, role, n FROM question WHERE {where} "
                                  "ORDER BY saved_at DESC LIMIT :l OFFSET :f"), {"o": owner, "l": limit, "f": offset})).mappings().all()
    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}
