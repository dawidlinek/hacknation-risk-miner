"""Zapytaj pamięć, saved questions, docked chats (api_contract §2.2, §2.3 1.6, §3.4). Owner: L (LLM).

/ask: curated intents run fixed SQL without the LLM; anything else goes NL→SQL (sqlguard, read-only, core wod-kan).
Chats answer from a fact sheet built by code (analysis report, project card); code labels the answer role."""
from __future__ import annotations

import csv
import io
import re
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api.prov import Answer
from riskminer.db.session import get_session
from riskminer.llm import questions as Q
from riskminer.llm.errors import LLMError

router = APIRouter(prefix="/api", tags=["ask"])
DB = Depends(get_session)
SESSION = Depends(A.session)


class AskScope(BaseModel):
    rm_id: str | None = None
    analysis_code: str | None = None
    terc: str | None = None


class AskIn(BaseModel):
    question: str
    scope: AskScope | None = None


class QuestionSaveIn(BaseModel):
    question_id: str
    title: str | None = None


class ChatIn(BaseModel):
    message: str
    context: Literal["report", "simulation", "redpen"] | None = None


SUGGESTIONS = {
    "zw": ("Zaprojektuj i wybuduj a samo wykonanie",
           "SELECT CASE WHEN design_build THEN 'zaprojektuj i wybuduj' ELSE 'samo wykonanie' END AS formula, "
           "round(100.0 * avg(late::int), 1) AS pct, count(*) AS n FROM v_ask_contract WHERE is_works AND late IS NOT NULL "
           "AND design_build IS NOT NULL GROUP BY 1 ORDER BY 1",
           "Po terminie kończy się {pct}% umów w formule {formula} (z {n} umów).", ("formula", "pct")),
    "woj_late": ("Które województwa najczęściej kończą po terminie?",
                 "SELECT woj_name, round(100.0 * avg(late::int), 1) AS pct, count(*) AS n FROM v_ask_contract "
                 "WHERE is_works AND late IS NOT NULL AND woj_name IS NOT NULL GROUP BY 1 HAVING count(*) >= 30 ORDER BY 2 DESC",
                 "Najczęściej po terminie kończy województwo {woj_name}: {pct}% z {n} umów.", ("woj_name", "pct")),
    "pfu_changes": ("Jak często PFU kończy się dopłatą?",
                    "SELECT round(100.0 * avg((cost_dev_pct > 0)::int), 1) AS pct, count(*) AS n FROM v_ask_contract "
                    "WHERE is_works AND design_build AND cost_dev_pct IS NOT NULL",
                    "Dopłatą kończy się {pct}% umów zaprojektuj i wybuduj (z {n} umów z danymi o wypłacie).", None),
    "single_offer": ("Ile przetargów miało jedną ofertę?",
                     "SELECT round(100.0 * sum(single_offer_lots) / nullif(sum(n_lots), 0), 1) AS pct, "
                     "sum(single_offer_lots) AS single, sum(n_lots) AS n FROM v_ask_procedure WHERE is_works AND n_lots > 0",
                     "Jedną ofertę miało {pct}% części zamówień ({single} z {n}).", None),
}
CONTEXT_SUGGESTIONS = {
    "analysis": ["Dlaczego termin jest ryzykowny?", "Co najbardziej podnosi koszt?", "Których danych brakuje?"],
    "project": ["Dlaczego ten projekt się opóźnił?", "Ile dopłacono i z jakiego powodu?", "Skąd pochodzą te dane?"],
}


def _err(e: LLMError) -> JSONResponse:
    return JSONResponse({"detail": e.detail, "code": e.code}, status_code=e.status)


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", (s or "").lower()).strip()


@router.get("/ask/suggestions", summary="Podpowiedzi pytań")
async def suggestions(context: Literal["pulpit", "zapytaj", "analysis", "project"] = "zapytaj"):
    if context in CONTEXT_SUGGESTIONS:
        return [{"key": f"{context}_{i}", "label": t} for i, t in enumerate(CONTEXT_SUGGESTIONS[context], 1)]
    return [{"key": k, "label": v[0]} for k, v in SUGGESTIONS.items()]


async def _curated(key: str) -> tuple[dict, str, list[dict]] | None:
    from riskminer.llm import sqlguard
    from riskminer.llm.schemas import BarSpec, SqlPlan
    from riskminer.llm.tasks import nl2sql as N

    title, sql, tmpl, bars = SUGGESTIONS[key]
    checked = sqlguard.check(sql, N.VIEWS)
    final = N.enforce_core(checked.sql)
    cols, rows = await sqlguard.execute(final)
    plan = SqlPlan(sql=sql, answer_template=tmpl, title=title, bars=BarSpec(label_col=bars[0], value_col=bars[1]) if bars else None)

    class _R:  # minimal stand-in for LLMResult.processing in a curated (no-LLM) answer
        processing = None
    ans = N._answer(plan, final, cols, rows, _R())  # type: ignore[arg-type]
    if key in ("zw", "woj_late") and len(rows) > 1 and ans["bars"]:
        top = max(ans["bars"], key=lambda b: b["value"] if b["value"] is not None else float("-inf"))
        for b in ans["bars"]:
            b["highlight"] = b is top
        if key == "zw" and len(rows) == 2:
            a, b = sorted(rows, key=lambda r: -float(r["pct"] or 0))
            ans["text"] = (f"Po terminie kończy się {N.fmt_pl(a['pct'])}% umów: {a['formula']} wobec "
                           f"{N.fmt_pl(b['pct'])}% przy formule {b['formula']} (razem {N.fmt_pl(a['n'] + b['n'])} umów).")
    ans["method"] = {"kind": "template", "sql": final, "template": f"ask:{key}"}
    return ans, final, rows


@router.post("/ask", response_model=Answer, summary="Zapytaj pamięć (obliczenie, wniosek AI albo brak danych)",
             dependencies=[Depends(A.rate_limit("ask", 10))])
async def ask(body: AskIn, request: Request, db: AsyncSession = DB, sess: A.Session = SESSION):
    from riskminer.llm.tasks import nl2sql as N

    qn = _norm(body.question)
    key = next((k for k, v in SUGGESTIONS.items() if qn in (k, _norm(v[0]))), None)
    sql, rows, llm_call_id = None, [], None
    try:
        if key:
            ans, sql, rows = await _curated(key)
        else:
            out = await N.ask(body.question, subject=f"ask:{sess.actor}")
            ans, sql, rows = out.answer, out.sql, out.rows
            llm_call_id = out.llm.llm_call_id if out.llm else None
    except LLMError as e:
        return _err(e)
    qid = await Q.store(db, kind="ask", question=body.question, answer=ans, owner=sess.actor,
                        scope=body.scope.model_dump() if body.scope else {}, sql=sql, rows=rows, llm_call_id=llm_call_id,
                        title=ans.get("title"))
    await db.commit()
    ans = {**ans, "id": f"q{qid}"}
    ans.pop("title", None)
    return ans


class AgentIn(BaseModel):
    question: str
    route: str | None = None
    scope: AskScope | None = None


@router.post("/ask/agent", summary="Zapytaj jako asystent: kroki, narzędzia i odpowiedź",
             dependencies=[Depends(A.rate_limit("ask", 10))])
async def ask_agent(body: AgentIn, request: Request, db: AsyncSession = DB, sess: A.Session = SESSION):
    """Agent loop (riskminer/llm/agent.py): the model plans, calls read-only tools (app guide, data, documents,
    project, monitoring) in several steps and answers; the visible steps come back with the answer."""
    from riskminer.llm import agent as AG

    try:
        out = await AG.run(body.question, body.route, actor=sess.actor, db=db)
    except LLMError as e:
        return _err(e)
    ans = out["answer"]
    qid = await Q.store(db, kind="ask", question=body.question, answer=ans, owner=sess.actor,
                        scope=body.scope.model_dump() if body.scope else {}, llm_call_id=out["llm_call_id"],
                        title=body.question[:120])
    await db.commit()
    return {"answer": {**ans, "id": f"q{qid}"}, "steps": out["steps"]}


def _qid(s: str) -> int:
    s = s.removeprefix("qd_").removeprefix("q")
    if not s.isdigit():
        raise A.ApiError(404, "Nie znaleziono pytania.", "not_found")
    return int(s)


@router.post("/questions", status_code=201, summary="Zapisz odpowiedź jako rekord Q-…")
async def save_question(body: QuestionSaveIn, request: Request, db: AsyncSession = DB, sess: A.Session = SESSION):
    q = await Q.get(db, qid=_qid(body.question_id))
    if q is None or (q["owner"] != sess.actor and sess.user is None):
        raise A.ApiError(404, "Nie znaleziono pytania.", "not_found")
    out = await Q.save(db, q["id"], body.title, sess.actor, A.request_id(request))
    await db.commit()
    return out


@router.get("/questions", summary="Zapisane pytania")
async def list_questions(mine: bool = True, limit: int = Query(50, le=500), offset: int = 0, db: AsyncSession = DB,
                         sess: A.Session = SESSION):
    return await Q.listing(db, sess.actor, mine, limit, offset)


async def _saved(db: AsyncSession, code: str) -> dict:
    q = await Q.get(db, code=code)
    if q is None:
        raise A.ApiError(404, f"Nie znaleziono pytania {code}.", "not_found")
    return q


@router.get("/questions/{code}", response_model=Answer, summary="Zapisane pytanie")
async def get_question(code: str, db: AsyncSession = DB):
    return Q.answer_of(await _saved(db, code))


@router.post("/questions/{code}/rerun", summary="Policz ponownie (stara i nowa wersja)")
async def rerun_question(code: str, db: AsyncSession = DB, sess: A.Session = SESSION):
    from riskminer.llm import sqlguard
    from riskminer.llm.schemas import SqlPlan
    from riskminer.llm.tasks import nl2sql as N

    q = await _saved(db, code)
    before = Q.answer_of(q)
    if not q["sql"]:
        return {"before": before, "after": before, "changed": False}
    checked = sqlguard.check(q["sql"], N.VIEWS)
    cols, rows = await sqlguard.execute(checked.sql)
    m = re.search(r"ask:(\w+)", str((q["answer"] or {}).get("method", {}).get("template") or ""))
    if m and m.group(1) in SUGGESTIONS:
        after, _, rows = await _curated(m.group(1))
    else:
        tmpl = (q["answer"] or {}).get("answer_template")
        plan = SqlPlan(sql=q["sql"], answer_template=tmpl or "", title=q["title"] or "")

        class _R:
            processing = (q["answer"] or {}).get("processing")
        after = N._answer(plan, checked.sql, cols, rows, _R())  # type: ignore[arg-type]
        if not tmpl:
            after["text"] = before["text"] if rows == (q["rows"] or []) else "Wynik po ponownym przeliczeniu w tabeli poniżej."
    nid = await Q.store(db, kind=q["kind"], question=q["question_text"], answer=after, owner=sess.actor, scope=q["scope"],
                        sql=checked.sql, rows=rows, parent_id=q["id"], title=q["title"])
    await db.commit()
    after = {**after, "id": f"q{nid}", "code": None}
    after.pop("title", None)
    import json as _json
    same = _json.loads(Q._j(q["rows"] or [])) == _json.loads(Q._j(rows))
    return {"before": before, "after": after, "changed": not same}


@router.get("/questions/{code}/rows.{fmt}", summary="Wiersze wyniku: CSV lub JSON")
async def question_rows(code: str, fmt: Literal["csv", "json"], db: AsyncSession = DB):
    q = await _saved(db, code)
    rows = q["rows"] or []
    if fmt == "json":
        return {"code": code, "sql": q["sql"], "rows": rows, "n": q["n"]}
    buf = io.StringIO()
    buf.write("﻿")
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{code}.csv"'})


async def _history(db: AsyncSession, kind: str, scope_key: str, scope_val: str, owner: str) -> list[dict]:
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT question_text, answer->>'text' AS answer FROM question WHERE kind = :k AND scope->>:sk = :sv AND owner = :o "
        "ORDER BY id DESC LIMIT 3"), {"k": kind, "sk": scope_key, "sv": scope_val, "o": owner})).mappings().all()
    hist = []
    for r in reversed(rows):
        hist += [{"role": "user", "text": r["question_text"]}, {"role": "assistant", "text": r["answer"]}]
    return hist


@router.post("/analyses/{code}/chat", response_model=Answer, summary="Rozmowa o raporcie, symulacji lub dokumencie",
             dependencies=[Depends(A.rate_limit("chat", 20))])
async def analysis_chat(code: str, body: ChatIn, db: AsyncSession = DB, sess: A.Session = SESSION):
    from riskminer.analysis import service as SV
    from riskminer.llm.tasks.chat import chat, facts_from

    try:
        a = await SV._load(db, code)
    except SV.NotFound:
        raise A.ApiError(404, f"Nie znaleziono analizy {code}.", "not_found") from None
    is_user = sess.user is not None
    if not SV.can_read(a, sess.actor, is_user, is_user and sess.user.role == "admin"):
        raise A.ApiError(403, "To nie jest Twoja analiza.", "forbidden")
    report = await SV.get_report(db, code)
    if isinstance(report, tuple):
        report = report[-1]
    facts = facts_from(report)
    try:
        res = await chat(body.message, facts, subject_label=f"analizę {code}", sensitivity=a.get("sensitivity") or "public",
                         history=await _history(db, "analysis_chat", "analysis_code", code, sess.actor),
                         subject=f"analysis:{code}", input_refs=[f"analysis:{code}"])
    except LLMError as e:
        return _err(e)
    ans = res.answer
    qid = await Q.store(db, kind="analysis_chat", question=body.message, answer=ans, owner=sess.actor,
                        scope={"analysis_code": code, "context": body.context},
                        llm_call_id=res.llm.llm_call_id if res.llm else None)
    await db.commit()
    return {**ans, "id": f"q{qid}"}


@router.post("/projects/{rm_id}/chat", response_model=Answer, summary="Rozmowa o projekcie (tylko zatwierdzone fakty publicznie)",
             dependencies=[Depends(A.rate_limit("chat", 20))])
async def project_chat(rm_id: str, body: ChatIn, db: AsyncSession = DB, sess: A.Session = SESSION):
    from riskminer.api import project_views as PV
    from riskminer.llm.tasks.chat import chat, facts_from

    card = await PV.card(db, rm_id, sess.user)
    if card is None:
        raise A.ApiError(404, "Nie znaleziono projektu.", "not_found")
    facts = facts_from(card, public=sess.user is None)
    try:
        res = await chat(body.message, facts, subject_label=f"projekt {rm_id}", sensitivity="public",
                         history=await _history(db, "project_chat", "rm_id", rm_id, sess.actor), subject=f"project:{rm_id}")
    except LLMError as e:
        return _err(e)
    ans = res.answer
    qid = await Q.store(db, kind="project_chat", question=body.message, answer=ans, owner=sess.actor,
                        scope={"rm_id": rm_id, "context": body.context}, llm_call_id=res.llm.llm_call_id if res.llm else None)
    await db.commit()
    return {**ans, "id": f"q{qid}"}
