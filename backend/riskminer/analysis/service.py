"""Analysis records: create / patch features / run / get / list / versions (api_contract §3.3).

Writes only through the request session (tests roll back): `analysis`, `analysis_item`, `analysis_version`,
`audit_log`. Codes come from `rm_next_code('AN')` (gapless, rolls back with the transaction).
AI rows are never updated here; owner edits create new `edited` feature items for the new version.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analysis import features as FE
from riskminer.analysis import report as R
from riskminer.analytics import catalogue
from riskminer.analytics.base import get_casebase
from riskminer.analytics.forecast import seed_of


async def _casebase_for(s: AsyncSession, ft):
    """Case base of the analysis's sector (unknown sector pack → wod-kan, the pilot sector)."""
    from riskminer.analytics.base import sector_pack
    sector = getattr(ft, "sector", None) or "wod-kan"
    try:
        sector_pack(sector)
    except KeyError:
        sector = "wod-kan"
        ft.sector = sector
    cb = await get_casebase(s, sector=sector)
    # the BM25 index of a new case base takes seconds to build: do it in a thread, not on the event loop
    import asyncio

    from riskminer.analytics import similarity as SIM
    if SIM._INDEXES.get(cb.data_version) is None:
        await asyncio.to_thread(SIM._prep, cb, False)
    return cb


SOVEREIGN_NOTE = ("Model suwerenny niedostępny: dokument poufny przetworzono tylko regułami, bez AI. "
                  "Jeśli dokument jest publiczny (np. pobrany z BZP), oznacz go jako publiczny, a AI przetworzy go "
                  "ponownie.")


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


async def audit(s: AsyncSession, actor: str, action: str, table: str, row_id: int | None, before: Any = None,
                after: Any = None, request_id: str | None = None, note: str | None = None) -> None:
    await s.execute(text("INSERT INTO audit_log (actor, action, table_name, row_id, before, after, request_id, note) "
                         "VALUES (:a, :ac, :t, :r, CAST(:b AS jsonb), CAST(:af AS jsonb), :rq, :n)"),
                    {"a": actor[:80], "ac": action[:40], "t": table, "r": row_id,
                     "b": None if before is None else _j(before), "af": None if after is None else _j(after),
                     "rq": (request_id or None) and request_id[:64], "n": note})


async def _load(s: AsyncSession, code: str) -> dict[str, Any]:
    r = (await s.execute(text("SELECT * FROM analysis WHERE code = :c"), {"c": code})).mappings().first()
    if r is None:
        raise NotFound(code)
    return dict(r)


async def enqueue(s: AsyncSession, kind: str, payload: dict, actor: str, priority: int = 50) -> int:
    """Job row in the request transaction (visible to the worker after commit; rolls back in tests)."""
    return (await s.execute(text("INSERT INTO job (kind, payload, priority, created_by) VALUES (:k, CAST(:p AS jsonb), "
                                 ":pr, :by) RETURNING id"),
                            {"k": kind, "p": _j(payload), "pr": priority, "by": actor[:80]})).scalar_one()


async def job_state(s: AsyncSession, job_id: int | None) -> dict | None:
    if not job_id:
        return None
    r = (await s.execute(text("SELECT id, status, result, error, created_at, started_at, finished_at, "
                              "extract(epoch FROM now() - created_at) AS age FROM job WHERE id = :i"),
                         {"i": job_id})).mappings().first()
    if r is None:
        return None
    st = r["status"]
    stale = st == "queued" and (r["age"] or 0) > 600          # no worker picked it up within 10 min
    return {"job_id": r["id"], "status": "stale" if stale else st, "result": r["result"], "error": r["error"]}


def can_read(a: dict, actor: str, is_user: bool, is_admin: bool) -> bool:
    if is_admin or a.get("owner") == actor:
        return True
    return is_user and a.get("sensitivity") != "confidential"


def can_write(a: dict, actor: str, is_admin: bool) -> bool:
    return is_admin or a.get("owner") == actor


async def _documents(s: AsyncSession, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    rows = (await s.execute(text(
        "SELECT d.id, d.filename, d.doc_type, d.sensitivity, d.data, "
        "(SELECT count(*) FROM document_page p WHERE p.document_id = d.id) AS pages "
        "FROM document d WHERE d.id = ANY(:ids)"), {"ids": ids})).mappings().all()
    out = []
    for r in rows:
        from riskminer.analysis.redpen import doc_type_ui
        dt = doc_type_ui(r["doc_type"])
        out.append({"document_id": r["id"], "id": r["id"], "filename": r["filename"],
                    "doc_type": dt, "pages": int(r["pages"] or 0),
                    "label": f"{dt}, {int(r['pages'] or 0)} s.", "sensitivity": r["sensitivity"] or "confidential"})
    return out


async def _feature_items(s: AsyncSession, analysis_id: int, version: int) -> list[dict]:
    rows = (await s.execute(text(
        "SELECT id, key, body, origin, review_status, version, document_id, page_no, quote, verification, llm_call_id "
        "FROM analysis_item WHERE analysis_id = :a AND section = 'feature' AND version <= :v ORDER BY version, id"),
        {"a": analysis_id, "v": version})).mappings().all()
    out = []
    for r in rows:
        b = dict(r["body"] or {})
        b.update({"key": r["key"], "item_id": r["id"], "origin": r["origin"], "review_status": r["review_status"],
                  "version": r["version"]})
        if r["document_id"] and not b.get("source"):
            b["source"] = {"document_id": r["document_id"], "page": r["page_no"]}
        if r["quote"] and not b.get("quote"):
            b["quote"] = r["quote"]
        if r["llm_call_id"]:
            b["llm_call_id"] = r["llm_call_id"]
        out.append(b)
    return out


async def _insert_item(s: AsyncSession, analysis_id: int, version: int, it: dict) -> int:
    body = it.get("body", {})
    q = text("INSERT INTO analysis_item (analysis_id, version, section, key, rank, title, body, catalogue_code, origin, "
             "review_status, document_id, page_no, quote, verification, llm_call_id) VALUES (:a, :v, :sec, :k, :rk, :t, "
             "CAST(:b AS jsonb), :cc, :o, :rs, :d, :p, :q, :vf, :lc) RETURNING id")
    return (await s.execute(q, {"a": analysis_id, "v": version, "sec": it["section"], "k": (it.get("key") or "")[:80],
                                "rk": it.get("rank"), "t": it.get("title"), "b": _j(body),
                                "cc": (it.get("catalogue_code") or None), "o": it.get("origin", "CALC"),
                                "rs": it.get("review_status", "auto"), "d": it.get("document_id"),
                                "p": it.get("page_no"), "q": it.get("quote"),
                                "vf": it.get("verification"), "lc": it.get("llm_call_id")})).scalar_one()


def _draft(a: dict, chips: dict[str, dict], docs: list[dict], skipped: list[str]) -> dict:
    ordered = [chips[k] for k in FE.CHIP_ORDER if k in chips] + [v for k, v in chips.items() if k not in FE.CHIP_ORDER]
    return {"id": a["code"], "code": a["code"], "version": a["version"],
            "status": a["status"] if a["status"] in ("draft", "running", "ready", "error") else "draft",
            "text": a.get("input_text") or "", "title": a.get("title"), "sensitivity": a.get("sensitivity"),
            "documents": docs, "features": [_chip_out(c) for c in ordered],
            "follow_ups": FE.follow_ups(chips, skipped),
            "questions": [{"key": f["key"], "text": f["title"], "why": f["why"], "input": f["input"]}
                          for f in FE.follow_ups(chips, skipped)]}


def _chip_out(c: dict) -> dict:
    origin = c.get("origin", "CALC")
    role = {"CALC": "calc", "AI": "ai", "SOURCE": "source"}.get(origin, "calc")
    if c.get("review_status") == "edited":
        role = "source"
    refs = [{"kind": "input_text", "id": "opis", "label": c.get("source_label") or "opis"}]
    if c.get("source"):
        refs = [{"kind": "document", "id": str(c["source"].get("document_id")), "label": c.get("source_label") or "dokument",
                 "page_no": c["source"].get("page"), "quote": c.get("quote"),
                 "verification": c.get("verification") or ("exact" if c.get("quote") else None)}]
    prov = {"role": role, "review_status": c.get("review_status", "auto"), "method": c.get("method") or "regex",
            "refs": refs}
    if role == "calc":
        prov["n"] = 1          # one input text parsed
    if c.get("llm"):
        prov["llm"] = c["llm"]
    out = {k: c.get(k) for k in ("key", "label", "value", "display", "source_label", "source", "unsure", "editor",
                                 "options", "unit", "item_id")}
    out["origin"] = origin
    out["review_status"] = c.get("review_status", "auto")
    out["prov"] = prov
    return out


# --- create / patch ---------------------------------------------------------------------------------------------------

async def check_docs(s: AsyncSession, ids: list[int], doc_ok) -> None:
    """Every attached document must exist and be readable by the caller (confidential uploads: uploader only)."""
    if not ids:
        return
    rows = (await s.execute(text("SELECT id, sensitivity, data FROM document WHERE id = ANY(:ids)"),
                            {"ids": list(ids)})).mappings().all()
    found = {r["id"]: dict(r) for r in rows}
    for i in ids:
        if i not in found or (doc_ok is not None and not doc_ok(found[i])):
            raise Forbidden(f"document {i}")


async def create(s: AsyncSession, *, text_in: str, document_ids: list[int], title: str | None, sensitivity: str,
                 owner: str, actor: str, request_id: str | None = None, doc_ok=None, ai: bool = True) -> dict:
    await check_docs(s, document_ids, doc_ok)
    docs = await _documents(s, document_ids)
    if any(d["sensitivity"] == "confidential" for d in docs):
        sensitivity = "confidential"
    code = (await s.execute(text("SELECT rm_next_code('AN')"))).scalar_one()
    chips = FE.extract(text_in)
    for k, c in (await _doc_regex_chips(s, document_ids)).items():
        chips.setdefault(k, c)          # the description wins; the documents fill what it does not say
    feats = {k: v["value"] for k, v in chips.items()}
    row = (await s.execute(text(
        "INSERT INTO analysis (code, title, input_text, input_documents, features, sensitivity, status, created_by, "
        "owner, version, visibility) VALUES (:c, :t, :x, CAST(:d AS jsonb), CAST(:f AS jsonb), :s, 'draft', :cb, :o, 1, "
        "'owner') RETURNING *"),
        {"c": code, "t": title or _title_from(chips, text_in), "x": text_in, "d": _j(document_ids), "f": _j(feats),
         "s": sensitivity, "cb": actor[:80], "o": owner})).mappings().one()
    a = dict(row)
    for k, c in chips.items():
        await _insert_item(s, a["id"], 1, {"section": "feature", "key": k, "title": c["label"], "origin": "CALC",
                                           "review_status": "auto", "body": c, "quote": c.get("quote")})
    jobs = {}
    if ai and ((text_in or "").strip() or document_ids):
        jobs["features"] = await enqueue(s, "analysis_features_ai", {"analysis_code": code}, actor, priority=20)
        await s.execute(text("UPDATE analysis SET results = CAST(:r AS jsonb) WHERE id = :id"),
                        {"r": _j({"jobs": jobs}), "id": a["id"]})
        a["results"] = {"jobs": jobs}
    await audit(s, actor, "analysis.create", "analysis", a["id"], None, {"code": code, "features": feats,
                                                                        "jobs": jobs}, request_id)
    d = _draft(a, chips, docs, [])
    d["ai_features"] = {"job_id": jobs.get("features"), "status": "queued" if jobs else "off"}
    return d


async def _doc_regex_chips(s: AsyncSession, document_ids: list[int] | None) -> dict[str, dict]:
    """Regex chips (CALC, local rules, so allowed for confidential documents) read from the attached documents' text.
    Without them a confidential upload with an empty description had no features while the sovereign model was down."""
    if not document_ids:
        return {}
    parts = []
    for did in document_ids:
        parts += [p["text"] or "" for p in await _pages(s, did)]
    out = FE.extract("\n".join(parts)[:200_000])
    for c in out.values():
        c["source_label"] = "dokument"
    return out


def _title_from(chips: dict, txt: str) -> str:
    sub = (chips.get("podsektor") or {}).get("display")
    if sub:
        L = chips.get("dlugosc_km")
        return sub.capitalize() + (f", {L['display'].replace('?', '')}" if L else "")
    return (txt or "Nowa analiza").strip()[:80] or "Nowa analiza"


async def get_draft(s: AsyncSession, code: str) -> tuple[dict, dict]:
    a = await _load(s, code)
    items = await _feature_items(s, a["id"], a["version"])
    chips = FE.pick(items)
    docs = await _documents(s, list(a.get("input_documents") or []))
    skipped = list((a.get("results") or {}).get("skipped") or [])
    d = _draft(a, chips, docs, skipped)
    js = await job_state(s, ((a.get("results") or {}).get("jobs") or {}).get("features"))
    d["ai_features"] = {"job_id": js["job_id"], "status": js["status"],
                        "errors": (js.get("result") or {}).get("errors")} if js else {"job_id": None, "status": "off"}
    errs = d["ai_features"].get("errors") or []
    if errs or (js and js["status"] in ("failed", "stale")):
        detail = next((e.get("detail") for e in errs if isinstance(e, dict) and e.get("detail")), None)
        sovereign = any(isinstance(e, dict) and (e.get("sovereign_unavailable") or e.get("code") ==
                                                 "sovereign_unavailable") for e in errs)
        if sovereign:
            d["ai_features"]["sovereign_unavailable"] = True
            d["ai_features"]["note"] = SOVEREIGN_NOTE
        else:
            d["ai_features"]["note"] = ("Odczyt AI niedostępny" + (f": {detail}" if detail else ".")
                                        + " Pokazujemy cechy odczytane regułami z opisu.")
    d["confidential_documents"] = [x["document_id"] for x in docs if x["sensitivity"] == "confidential"]
    d["ai_pending"] = bool(js and js["status"] in ("queued", "running"))
    return a, d


async def patch_features(s: AsyncSession, code: str, values: dict[str, Any], skipped: list[str], actor: str,
                         request_id: str | None = None, text_in: str | None = None,
                         document_ids: list[int] | None = None, doc_ok=None, ai: bool = True) -> dict:
    a = await _load(s, code)
    if document_ids is not None:
        await check_docs(s, document_ids, doc_ok)
    items = await _feature_items(s, a["id"], a["version"])
    before = FE.pick(items)
    new_v = a["version"] + 1
    changed = {}
    for k, v in (values or {}).items():
        if k not in FE.FEATURE_DEFS:
            continue
        val = FE.coerce(k, v)
        c = FE.chip(k, val, source_label="Ty", method="owner_edit", origin="SOURCE", review_status="edited")
        changed[k] = val
        await _insert_item(s, a["id"], new_v, {"section": "feature", "key": k, "title": c["label"], "origin": "SOURCE",
                                               "review_status": "edited", "body": c})
    if "sektor" in changed and "podsektor" not in changed:
        # a new sector has its own subsectors: re-read the subsector from the description for that sector
        from riskminer.analytics.base import classify_subsector, sector_pack
        sec = changed["sektor"] or "wod-kan"
        txt = (text_in if text_in is not None else a.get("input_text")) or ""
        if sec == "wod-kan":
            hit = FE.wodkan_subsector(txt.lower())
            sub_chip = FE.chip("podsektor", hit[0], method="regex:subsector") if hit else None
        else:
            try:
                code_ = classify_subsector(sector_pack(sec), txt.lower())
            except KeyError:
                code_ = None
            sub_chip = FE.chip("podsektor", code_, method="regex:subsector", unsure=True,
                               options=FE.subsector_options(sec)) if code_ else None
        if not sub_chip:      # nothing recognisable for the new sector: an empty, unsure chip for the owner to pick
            sub_chip = FE.chip("podsektor", None, method="regex:subsector", unsure=True,
                               options=FE.subsector_options(sec))
        await _insert_item(s, a["id"], new_v, {"section": "feature", "key": "podsektor", "title": "podsektor",
                                               "origin": "CALC", "review_status": "auto", "body": sub_chip})
    if text_in is not None and text_in != a.get("input_text"):
        # new description: re-extract regex chips for keys the owner has not edited
        for k, c in FE.extract(text_in).items():
            if (before.get(k) or {}).get("review_status") in ("edited", "approved") or k in changed:
                continue
            await _insert_item(s, a["id"], new_v, {"section": "feature", "key": k, "title": c["label"],
                                                   "origin": "CALC", "review_status": "auto", "body": c})
    results = dict(a.get("results") or {})
    results["skipped"] = sorted(set(results.get("skipped") or []) | set(skipped or []))
    results["stale"] = ["report"]
    new_text = text_in is not None and text_in != a.get("input_text")
    new_docs = document_ids is not None and sorted(document_ids) != sorted(a.get("input_documents") or [])
    if new_docs:
        # documents attached later: their regex chips fill only features nobody has given yet (text, AI, owner)
        have = set(before) | set(changed) | (set(FE.extract(text_in)) if new_text else set())
        for k, c in (await _doc_regex_chips(s, document_ids)).items():
            if k in have:
                continue
            await _insert_item(s, a["id"], new_v, {"section": "feature", "key": k, "title": c["label"], "origin": "CALC",
                                                   "review_status": "auto", "body": c, "quote": c.get("quote")})
    if ai and (new_text or new_docs):
        jobs = dict(results.get("jobs") or {})
        jobs["features"] = await enqueue(s, "analysis_features_ai", {"analysis_code": code}, actor, priority=20)
        results["jobs"] = jobs
    after_items = await _feature_items(s, a["id"], new_v)
    feats = {k: v.get("value") for k, v in FE.pick(after_items).items()}
    docs_ids = document_ids if document_ids is not None else list(a.get("input_documents") or [])
    row = (await s.execute(text(
        "UPDATE analysis SET version = :v, features = CAST(:f AS jsonb), results = CAST(:r AS jsonb), "
        "input_text = coalesce(:x, input_text), input_documents = CAST(:d AS jsonb), status = 'draft', "
        "updated_at = now() WHERE id = :id RETURNING *"),
        {"v": new_v, "f": _j(feats), "r": _j(results), "x": text_in, "d": _j(docs_ids), "id": a["id"]})).mappings().one()
    await audit(s, actor, "analysis.features", "analysis", a["id"],
                {k: (before.get(k) or {}).get("value") for k in changed}, {"changed": changed, "skipped": skipped,
                                                                           "version": new_v}, request_id)
    a = dict(row)
    docs = await _documents(s, docs_ids)
    d = _draft(a, FE.pick(after_items), docs, results["skipped"])
    d["stale_sections"] = ["report"]
    return d


# --- run / get ----------------------------------------------------------------------------------------------------------

async def _ai_flags(s: AsyncSession, analysis_id: int) -> list[dict]:
    """AI flags written by the LLM session (section 'flag', origin AI) for this analysis, any version."""
    rows = (await s.execute(text(
        "SELECT id, key, title, body, review_status, document_id, page_no, quote, verification, llm_call_id "
        "FROM analysis_item WHERE analysis_id = :a AND origin = 'AI' AND section IN ('flag', 'redpen_note') "
        "AND review_status <> 'rejected' ORDER BY id"), {"a": analysis_id})).mappings().all()
    out = []
    for r in rows:
        b = dict(r["body"] or {})
        codes = b.get("risk_codes") or ([b["risk_code"]] if b.get("risk_code") else [])
        page = r["page_no"] or b.get("page_no") or b.get("page")
        meta = ", ".join([*codes, "AI"] + ([f"{b.get('doc_type', 'dokument')} s. {page}"] if page else []))
        out.append({"id": f"ai-{r['id']}", "item_id": r["id"], "origin": "AI", "review_status": r["review_status"],
                    "title": r["title"] or b.get("title") or "Sygnał z dokumentu", "text": b.get("text") or b.get("why") or "",
                    "meta": meta, "risk_codes": codes,
                    "doc": {"document_id": r["document_id"], "page": page, "note_no": b.get("n") or b.get("no")}
                    if r["document_id"] else None,
                    "review_item_id": b.get("review_item_id"), "kind": "ai",
                    "quote": r["quote"], "verification": r["verification"],
                    "prov": {"role": "ai", "review_status": r["review_status"],
                             "refs": [{"kind": "document", "id": str(r["document_id"]), "label": f"s. {page}",
                                       "page_no": page, "quote": r["quote"], "verification": r["verification"]}]
                             if r["document_id"] else [],
                             "llm": b.get("llm") or {"provider": "?", "model": "?", "data_location": "?",
                                                     "llm_call_id": r["llm_call_id"]}}})
    return out


async def _in_pack(s: AsyncSession, analysis_id: int) -> set[str]:
    rows = (await s.execute(text("SELECT key FROM analysis_item WHERE analysis_id = :a AND section = 'pack_clause' "
                                 "AND review_status <> 'rejected'"), {"a": analysis_id})).scalars().all()
    return set(rows)


async def run(s: AsyncSession, code: str, actor: str, request_id: str | None = None, reason: str = "run",
              ai: bool = True) -> dict:
    """Compute every section for the current features and store an immutable `analysis_version` snapshot.
    Re-running an already snapshotted version creates the next version (snapshots never change)."""
    a = await _load(s, code)
    version = a["version"]
    snap = (await s.execute(text("SELECT id FROM analysis_version WHERE analysis_id = :a AND version = :v"),
                            {"a": a["id"], "v": version})).scalar()
    if snap is not None:
        version += 1
    items = await _feature_items(s, a["id"], version)
    chips = FE.pick(items)
    ft = FE.to_features(chips, a.get("input_text") or "")
    cb = await _casebase_for(s, ft)
    cat = await catalogue.load(s)
    seed = seed_of(code, version)
    docs = await _documents(s, list(a.get("input_documents") or []))
    report, out_items = R.compose(cb, cat, ft, code=code, version=version, seed=seed, documents=docs, chips=chips,
                                  ai_flags=await _ai_flags(s, a["id"]), in_pack=await _in_pack(s, a["id"]))
    # risk register for the pack: the allocation with the owner's saved choices (recommended positions by default)
    try:
        from riskminer.analysis import allocation as AL
        from riskminer.analysis import simulation as SM
        sim = SM.build(cb, cat, ft, code, version)
        if not sim.get("insufficient"):
            al = AL.build(report, sim, cat, await _choices(s, a["id"]), ft.value_gross, ft.plan_days)
            report["allocation"] = {k: al[k] for k in ("risks", "balance", "premium")}
    except Exception:  # noqa: BLE001 - the report must not fail because of the optional register
        report.pop("allocation", None)
    if docs:
        found, miss = await _doc_notes(s, a, report, docs)
        k = 0
        for did, ns in found["notes"].items():
            for n in ns:
                if n.get("origin") == "AI":
                    continue
                k += 1
                d = next((x for x in docs if x["document_id"] == did), {})
                fl = {"id": f"doc-{did}-{n['rule']}", "origin": "CALC", "review_status": "auto", "title": n["title"],
                      "text": n["why"], "meta": f"{', '.join(n['risk_codes'])}, reguła, {d.get('doc_type', 'dokument')} "
                                               f"s. {n['page']}", "risk_codes": n["risk_codes"],
                      "doc": {"document_id": did, "page": n["page"], "note_no": None}, "review_item_id": None,
                      "kind": "calc", "rule": n["rule"], "quote": n["quote"], "verification": "exact",
                      "prov": {"role": "calc", "review_status": "auto", "n": 1, "method": f"rule:{n['rule']}+regex",
                               "refs": [{"kind": "document", "id": str(did), "label": f"{d.get('doc_type')} s. {n['page']}",
                                         "page_no": n["page"], "quote": n["quote"], "verification": "exact"}]}}
                report["flags"].append(fl)
                out_items.append({"section": "flag", "key": fl["id"], "title": fl["title"], "origin": "CALC",
                                  "body": fl, "catalogue_code": n["rule"], "document_id": did, "page_no": n["page"],
                                  "quote": n["quote"][:2000], "verification": "exact", "rank": 100 + k})
        report["missing"] = miss["missing"]
        for m in miss["missing"]:
            out_items.append({"section": "missing", "key": m["rule"], "title": m["title"], "origin": "CALC", "body": m})
    await s.execute(text("DELETE FROM analysis_item WHERE analysis_id = :a AND version = :v AND origin = 'CALC' "
                         "AND review_status = 'auto' AND section NOT IN ('feature', 'pack_clause', 'allocation', "
                         "'simulation')"), {"a": a["id"], "v": version})
    for it in out_items:
        await _insert_item(s, a["id"], version, it)
    results = dict(a.get("results") or {})
    results.pop("stale", None)
    results.pop("stale_cases", None)
    results["report"] = report
    results["computed_at"] = datetime.now(UTC).isoformat()
    feats_json = {k: v.get("value") for k, v in chips.items()}
    await s.execute(text(
        "UPDATE analysis SET status = 'ready', version = :v, results = CAST(:r AS jsonb), "
        "reference_class = CAST(:rc AS jsonb), features = CAST(:f AS jsonb), updated_at = now() WHERE id = :id"),
        {"v": version, "r": _j(results), "rc": _j(report["reference_class"]), "f": _j(feats_json), "id": a["id"]})
    await s.execute(text(
        "INSERT INTO analysis_version (analysis_id, version, features, reference_class, results, catalogue_version, "
        "data_as_of, seed, reason, created_by) VALUES (:a, :v, CAST(:f AS jsonb), CAST(:rc AS jsonb), "
        "CAST(:r AS jsonb), :cv, :da, :sd, :rs, :cb)"),
        {"a": a["id"], "v": version, "f": _j(feats_json), "rc": _j(report["reference_class"]), "r": _j(report),
         "cv": cat.get("version"), "da": datetime.combine(cb.data_as_of, datetime.min.time(), UTC)
         if cb.data_as_of else None, "sd": seed, "rs": reason, "cb": actor[:80]})
    redpen_job = None
    if docs and ai:
        redpen_job = await enqueue(s, "analysis_redpen", {"analysis_code": code}, actor, priority=30)
        results.setdefault("jobs", {})["redpen"] = redpen_job
        await s.execute(text("UPDATE analysis SET results = CAST(:r AS jsonb) WHERE id = :id"),
                        {"r": _j(results), "id": a["id"]})
    await audit(s, actor, "analysis.run", "analysis", a["id"], None,
                {"code": code, "version": version, "n": report["reference_class"]["n"],
                 "data_version": report["data_version"], "redpen_job_id": redpen_job}, request_id)
    return {"id": code, "code": code, "version": version, "status": "ready",
            "sections": {"report": "done", "redpen": "queued" if redpen_job else "skipped"},
            "redpen_job_id": redpen_job}


async def get_report(s: AsyncSession, code: str, version: int | None = None) -> dict:
    a = await _load(s, code)
    if version is not None and version != a["version"]:
        snap = (await s.execute(text("SELECT results FROM analysis_version WHERE analysis_id = :a AND version = :v"),
                                {"a": a["id"], "v": version})).scalar()
        if not snap:
            raise NotFound(f"{code} v{version}")
        rep = dict(snap)
    else:
        rep = (a.get("results") or {}).get("report")
        if not rep:
            _, d = await get_draft(s, code)
            return {**d, "status": "draft", "summary": None, "questions": [], "flags": [], "similar_cases": [],
                    "clauses": [], "reference_class": None, "limitations": [], "pending_review": 0, "subtitle": code,
                    "chat": {"suggestions": []}}
        rep = dict(rep)
        rep["flags"] = [f for f in rep.get("flags", []) if f.get("origin") != "AI"] + await _ai_flags(s, a["id"])
        pack = await _in_pack(s, a["id"])
        for c in rep.get("clauses", []):
            c["in_pack"] = c["code"] in pack
        if (a.get("results") or {}).get("stale"):
            rep["stale_sections"] = ["report"]
            rep["features_version"] = a["version"]
        if (a.get("results") or {}).get("stale_cases"):
            rep["stale_cases"] = a["results"]["stale_cases"]
    rep["sensitivity"] = a.get("sensitivity")
    _, d = await get_draft(s, code)
    rep["features"] = d["features"]
    rep["text"] = a.get("input_text") or ""
    rep["pending_review"] = sum(1 for f in rep.get("flags", []) if f.get("origin") == "AI"
                                and f.get("review_status") == "proposed")
    return rep


async def list_analyses(s: AsyncSession, owner: str | None, status: str | None, limit: int, offset: int) -> dict:
    where, p = ["code IS NOT NULL"], {"l": limit, "o": offset}
    if owner is not None:
        where.append("owner = :ow")
        p["ow"] = owner
    if status:
        where.append("status = :st")
        p["st"] = status
    w = " AND ".join(where)
    total = (await s.execute(text(f"SELECT count(*) FROM analysis WHERE {w}"), p)).scalar()
    rows = (await s.execute(text(f"SELECT code, title, version, status, sensitivity, updated_at, created_at FROM analysis "
                                 f"WHERE {w} ORDER BY updated_at DESC LIMIT :l OFFSET :o"), p)).mappings().all()
    return {"total": total, "limit": limit, "offset": offset,
            "items": [{**dict(r), "id": r["code"]} for r in rows]}


async def versions(s: AsyncSession, code: str) -> list[dict]:
    a = await _load(s, code)
    rows = (await s.execute(text(
        "SELECT version, created_at, created_by, reason, catalogue_version, data_as_of, seed, "
        "(results ? 'summary') AS has_report FROM analysis_version WHERE analysis_id = :a ORDER BY version"),
        {"a": a["id"]})).mappings().all()
    return [dict(r) for r in rows]


async def reference_class_contracts(s: AsyncSession, code: str, limit: int, offset: int) -> dict:
    a = await _load(s, code)
    rep = (a.get("results") or {}).get("report")
    if not rep:
        raise NotFound(code)
    from riskminer.analytics import refclass as RCm
    ft = RCm.Features(**{k: v for k, v in (rep.get("features_used") or {}).items()
                         if k in RCm.Features.__dataclass_fields__})
    cb = await _casebase_for(s, ft)
    rc = RCm.build(cb, ft)
    import numpy as np
    idx = np.flatnonzero(rc.mask)
    idx = idx[np.argsort(-cb["value_gross"][idx])]
    page = idx[offset: offset + limit]
    items = []
    for i in page:
        dd = R._outcome(cb, int(i))
        items.append({
            "performance_id": int(cb["performance_id"][i]), "ocid": cb["ocid"][i], "title": cb["title"][i],
            "buyer_name": cb["buyer_name"][i], "province": cb["province"][i],
            "value_gross": {"amount": f"{cb['value_gross'][i]:.2f}", "currency": "PLN", "vat_basis": "gross"},
            "paid_gross": {"amount": f"{cb['paid_gross'][i]:.2f}" if np.isfinite(cb["paid_gross"][i]) else None,
                           "currency": "PLN", "vat_basis": "gross"},
            "planned_days": None if not np.isfinite(cb["planned_days"][i]) else float(cb["planned_days"][i]),
            "actual_days": None if not np.isfinite(cb["actual_days"][i]) else float(cb["actual_days"][i]),
            "late": bool(cb["late"][i] == 1), "delay_days": dd[0], "cost_dev_pct": dd[1],
            "changes_count": None if not np.isfinite(cb["changes_count"][i]) else int(cb["changes_count"][i]),
            "cause_codes": list(cb["cause_codes"][i]), "time_ok": bool(cb["time_ok"][i]),
            "cost_ok": bool(cb["cost_ok"][i]), "notice_number": cb["cp_bzp_number"][i], "url": cb["cp_url"][i],
            "signed_on": None if np.isnat(cb["signed_on"][i]) else str(cb["signed_on"][i]),
            "completed_on": None if np.isnat(cb["completed_on"][i]) else str(cb["completed_on"][i]),
            "origin": "SOURCE", "review_status": "auto"})
    return {"total": int(idx.size), "limit": limit, "offset": offset, "items": items,
            "filter": rc.chosen.filters, "label": rc.label()}


async def add_pack_clause(s: AsyncSession, code: str, clause_code: str, text_override: str | None, actor: str,
                          request_id: str | None = None) -> dict:
    a = await _load(s, code)
    exists = (await s.execute(text("SELECT id FROM analysis_item WHERE analysis_id = :a AND section = 'pack_clause' "
                                   "AND key = :k"), {"a": a["id"], "k": clause_code})).scalar()
    if exists is None:
        iid = await _insert_item(s, a["id"], a["version"], {
            "section": "pack_clause", "key": clause_code, "title": clause_code, "origin": "SOURCE",
            "review_status": "approved" if not text_override else "edited",
            "body": {"code": clause_code, "text": text_override, "added_by": actor}})
        await audit(s, actor, "analysis.pack_clause", "analysis_item", iid, None, {"code": clause_code}, request_id)
    return {"code": clause_code, "in_pack": True}


def today() -> date:
    return date.today()


# --- 1.4 simulation / 1.5 allocation ------------------------------------------------------------------------------------

async def _ready(s: AsyncSession, code: str) -> tuple[dict, dict]:
    a = await _load(s, code)
    rep = (a.get("results") or {}).get("report")
    if not rep:
        raise NotReady(code)
    return a, rep


class NotReady(Exception):
    pass


def _features_from(rep: dict):
    from riskminer.analytics.refclass import Features
    fu = rep.get("features_used") or {}
    return Features(**{k: v for k, v in fu.items() if k in Features.__dataclass_fields__})


async def simulation(s: AsyncSession, code: str) -> dict:
    from riskminer.analysis import simulation as SM
    a, rep = await _ready(s, code)
    ft = _features_from(rep)
    ft.text = a.get("input_text") or ""
    cb = await _casebase_for(s, ft)
    cat = await catalogue.load(s)
    return SM.build(cb, cat, ft, code, rep["version"])


async def _choices(s: AsyncSession, analysis_id: int) -> dict:
    row = (await s.execute(text("SELECT body FROM analysis_item WHERE analysis_id = :a AND section = 'allocation' "
                                "AND key = 'choices' ORDER BY id DESC LIMIT 1"), {"a": analysis_id})).scalar()
    return dict((row or {}).get("choices") or {})


async def allocation(s: AsyncSession, code: str) -> dict:
    from riskminer.analysis import allocation as AL
    a, rep = await _ready(s, code)
    sim = await simulation(s, code)
    cat = await catalogue.load(s)
    ft = _features_from(rep)
    rep_live = await get_report(s, code)
    out = AL.build(rep_live, sim, cat, await _choices(s, a["id"]), ft.value_gross, ft.plan_days)
    out["version"] = rep["version"]
    return out


async def put_allocation(s: AsyncSession, code: str, choices: dict, actor: str, request_id: str | None = None) -> dict:
    from riskminer.analysis import allocation as AL
    a, rep = await _ready(s, code)
    before = await _choices(s, a["id"])
    norm = {k: AL._pos(v) for k, v in choices.items()}
    merged = {**before, **norm}
    iid = await _insert_item(s, a["id"], a["version"], {
        "section": "allocation", "key": "choices", "title": "Podział ryzyk", "origin": "SOURCE",
        "review_status": "edited", "body": {"choices": merged, "by": actor}})
    out = await allocation(s, code)
    results = dict(a.get("results") or {})
    results["allocation"] = {k: out[k] for k in ("risks", "balance", "premium")}
    results["report"] = {**results.get("report", {}), "allocation": results["allocation"]}
    await s.execute(text("UPDATE analysis SET results = CAST(:r AS jsonb), updated_at = now() WHERE id = :id"),
                    {"r": _j(results), "id": a["id"]})
    await audit(s, actor, "analysis.allocation", "analysis_item", iid, before, merged, request_id)
    return out


# --- 1.3 Red Pen -------------------------------------------------------------------------------------------------------

async def _pages(s: AsyncSession, document_id: int) -> list[dict]:
    rows = (await s.execute(text("SELECT page_no, text FROM document_page WHERE document_id = :d ORDER BY page_no"),
                            {"d": document_id})).mappings().all()
    return [dict(r) for r in rows]


async def _doc_notes(s: AsyncSession, a: dict, rep: dict | None, docs: list[dict]) -> tuple[dict, dict]:
    """Regex notes + AI notes per document, and missing items for the whole package."""
    from riskminer.analysis import redpen as RP
    texts, pages_by = {}, {}
    for d in docs:
        pg = await _pages(s, d["document_id"])
        pages_by[d["document_id"]] = pg
        texts[d["document_id"]] = "\n".join(p["text"] or "" for p in pg)
    package = " ".join(texts.values())
    notes: dict[int, list[dict]] = {}
    for d in docs:
        found = RP.regex_notes(pages_by[d["document_id"]], package)
        for n in found:
            n["document_id"] = d["document_id"]
            n["doc_type"] = d["doc_type"]
        notes[d["document_id"]] = found
    ai = (await s.execute(text(
        "SELECT id, document_id, page_no, char_start, char_end, quote, verification, review_status, body, llm_call_id "
        "FROM analysis_item WHERE analysis_id = :a AND section = 'redpen_note' AND origin = 'AI' "
        "AND review_status <> 'rejected' ORDER BY page_no NULLS LAST, id"), {"a": a["id"]})).mappings().all()
    for r in ai:
        b = dict(r["body"] or {})
        notes.setdefault(r["document_id"], []).append({
            "kind": "found", "origin": "AI", "item_id": r["id"], "document_id": r["document_id"], "page": r["page_no"],
            "char_start": r["char_start"], "char_end": r["char_end"], "quote": r["quote"],
            "verification": r["verification"], "review_status": r["review_status"],
            "title": b.get("title"), "why": b.get("why") or b.get("text"), "risk_codes": b.get("risk_codes") or [],
            "locator": b.get("locator") or b.get("clause_ref"), "suggested_clause": b.get("suggested_clause"),
            "llm": b.get("llm"), "method": "llm:redpen_scan"})
    feats = (rep or {}).get("features_used") or {}
    missing = RP.missing_items(docs, texts, feats.get("plan_days"), feats.get("length_km"), feats.get("subsector_main"))
    return {"notes": notes, "pages": pages_by}, {"missing": missing}


async def redpen(s: AsyncSession, code: str, document_id: int, only_noted: bool) -> dict:
    from riskminer.analysis import redpen as RP
    a = await _load(s, code)
    rep = (a.get("results") or {}).get("report")
    docs = await _documents(s, list(a.get("input_documents") or []))
    doc = next((d for d in docs if d["document_id"] == document_id), None)
    if doc is None:
        raise NotFound(f"{code}/{document_id}")
    found, miss = await _doc_notes(s, a, rep, docs)
    notes = sorted(found["notes"].get(document_id, []), key=lambda n: (n.get("page") or 0, n.get("char_start") or 0))
    for i, n in enumerate(notes, 1):
        n["no"] = str(i)
    cat = await catalogue.load(s)
    pack = await _in_pack(s, a["id"])
    sims = (rep or {}).get("similar_cases") or []

    pool = (rep or {}).get("similar_code_counts") or {}

    def cases_for(n: dict) -> list[dict]:
        codes = {c.split(".")[0] for c in n.get("risk_codes") or []}
        out = [{"label": (c.get("buyer_name") or c["title"])[:50], "href": c["href"]} for c in sims
               if codes & {x.split(".")[0] for x in c.get("cause_codes") or []}][:2]
        for code in codes:
            for c in (pool.get(code) or {}).get("cases", []):
                if len(out) < 3 and c["href"] not in {o["href"] for o in out}:
                    out.append({"label": c["label"], "href": c["href"]})
        return out

    case_hints = []
    for code in sorted({c.split(".")[0] for n in notes + miss["missing"] for c in n.get("risk_codes") or []}):
        e = pool.get(code)
        if e and e["k"]:
            case_hints.append({"risk_code": code, "text": f"W {e['k']} z {e['n']} najbardziej podobnych umów zmiany "
                                                         f"miały przyczynę {code}.",
                               "cases": e["cases"],
                               "number": {"value": e["k"], "display": f"{e['k']} z {e['n']}", "unit": "count",
                                          "prov": {"role": "calc", "review_status": "auto", "n": e["n"],
                                                   "method": "similar_top30_cause_share",
                                                   "refs": [{"kind": "query", "id": "similar:top30",
                                                             "label": "najbardziej podobne umowy"}]}}})

    out_notes = [RP.note_out(n, cat["clauses"], pack, cases_for(n)) for n in notes]
    out_missing = [RP.note_out(m, cat["clauses"], pack, cases_for(m)) for m in miss["missing"]]
    pages = RP.build_pages(found["pages"][document_id], notes, only_noted)
    ai_pending = any(n.get("origin") == "AI" for n in notes)
    js = await job_state(s, ((a.get("results") or {}).get("jobs") or {}).get("redpen"))
    status, limits = "done", []
    if js:
        if js["status"] in ("queued", "running"):
            status = js["status"]
        elif js["status"] == "stale":
            limits.append("Skan dokumentu modelem AI nie ruszył; pokazujemy tylko reguły i braki.")
        elif js["status"] == "done":
            dres = ((js.get("result") or {}).get("documents") or {}).get(str(document_id)) or {}
            if dres.get("status") == "sovereign_unavailable" or (js.get("result") or {}).get("status") == \
                    "sovereign_unavailable" and not dres:
                # the page text and the rule notes need no model: show them, say why the AI part is missing
                status = "sovereign_unavailable"
                limits.append(SOVEREIGN_NOTE)
            pnote = (dres.get("processing") or {}).get("note") if isinstance(dres.get("processing"), dict) else None
            if pnote:
                limits.append(f"Uwagi AI: {pnote}.")
            for fr, to in dres.get("failed_pages") or []:
                limits.append(f"Strony {fr} do {to} nieprzeczytane przez model AI." if fr != to
                              else f"Strona {fr} nieprzeczytana przez model AI.")
        elif js["status"] == "failed":
            limits.append("Skan dokumentu modelem AI nie powiódł się; pokazujemy tylko reguły i braki.")
    return {"status": status, "job": js and {"job_id": js["job_id"], "status": js["status"]}, "limitations": limits, "document": {"id": document_id, "filename": doc["filename"], "pages": doc["pages"],
                                           "doc_type": doc["doc_type"], "demo": doc["sensitivity"] == "public",
                                           "sensitivity": doc["sensitivity"],
                                           "file_url": f"/api/documents/{document_id}/file"},
            "pages": pages, "notes": out_notes + out_missing,
            "counts": {"found": len(out_notes), "missing": len(out_missing)}, "case_hints": case_hints,
            "ai_notes": ai_pending}


async def item_decision(s: AsyncSession, code: str, item_id: int, action: str, value: Any, reason: str | None,
                        add_clause: str | None, actor: str, request_id: str | None = None) -> dict:
    """Owner decision on an AI item of their own analysis (not expert review): proposed -> approved/edited/rejected."""
    a = await _load(s, code)
    it = (await s.execute(text("SELECT id, review_status, body, origin FROM analysis_item WHERE id = :i AND "
                               "analysis_id = :a"), {"i": item_id, "a": a["id"]})).mappings().first()
    if it is None:
        raise NotFound(str(item_id))
    new = {"approve": "approved", "edit": "edited", "reject": "rejected"}[action]
    body = dict(it["body"] or {})
    if action == "edit" and value is not None:
        body["owner_value"] = value
    if reason:
        body["owner_reason"] = reason
    row = (await s.execute(text("UPDATE analysis_item SET review_status = :rs, body = CAST(:b AS jsonb), "
                                "updated_at = now() WHERE id = :i RETURNING review_status"),
                           {"rs": new, "b": _j(body), "i": item_id})).scalar()
    if row != new:
        raise Protected(str(item_id))
    await s.execute(text("INSERT INTO review (target_table, target_id, action, before, after, reviewer, comment, "
                         "request_id) VALUES ('analysis_item', :i, :ac, CAST(:b AS jsonb), CAST(:af AS jsonb), :rv, :c, "
                         ":rq)"), {"i": item_id, "ac": action, "b": _j({"review_status": it["review_status"]}),
                                   "af": _j({"review_status": new, "value": value}), "rv": actor[:80],
                                   "c": reason, "rq": request_id})
    await audit(s, actor, f"analysis.item_{action}", "analysis_item", item_id, {"review_status": it["review_status"]},
                {"review_status": new}, request_id)
    if add_clause:
        await add_pack_clause(s, code, add_clause, None, actor, request_id)
    return {"item_id": item_id, "review_status": new, "in_pack": new in ("approved", "edited")}


class Protected(Exception):
    pass


class SovereignUnavailable(Exception):
    pass


# --- affected analyses (docs/impl/new_documents.md §2 step 8) -----------------------------------------------------------

async def affected(s: AsyncSession, rm_id: str | None = None, ocid: str | None = None) -> list[dict]:
    """Analyses whose current version shows this project (rm_id) or procedure (ocid) among its similar cases."""
    if not rm_id and not ocid:
        return []
    rows = (await s.execute(text(
        "SELECT DISTINCT a.id, a.code, a.title, a.owner, a.version, i.title AS case_title, i.key "
        "FROM analysis a JOIN analysis_item i ON i.analysis_id = a.id AND i.section = 'similar' AND i.version = a.version "
        "WHERE (CAST(:rm AS text) IS NOT NULL AND (i.key = CAST(:rm AS text) OR i.body->>'rm_id' = CAST(:rm AS text))) "
        "   OR (CAST(:oc AS text) IS NOT NULL AND (i.key = CAST(:oc AS text) OR i.body->>'ocid' = CAST(:oc AS text))) "
        "ORDER BY a.code"),
        {"rm": rm_id, "oc": ocid})).mappings().all()
    return [dict(r) for r in rows]


async def mark_affected(s: AsyncSession, *, rm_id: str | None = None, ocid: str | None = None, reason: str,
                        actor: str, document_id: int | None = None, request_id: str | None = None) -> list[str]:
    """Flag every analysis citing the case: results.stale_cases += {case, reason, document_id, at}. The report shows
    „Nowe dane w przypadku podobnym…, uruchom ponownie”; the next run clears it. Never touches approved items."""
    marked = []
    for r in await affected(s, rm_id, ocid):
        a = await _load(s, r["code"])
        results = dict(a.get("results") or {})
        cases = [c for c in (results.get("stale_cases") or []) if c.get("case") != (rm_id or ocid)]
        entry = {"case": rm_id or ocid, "label": r["case_title"], "reason": reason, "document_id": document_id,
                 "at": datetime.now(UTC).isoformat()}
        cases.append(entry)
        results["stale_cases"] = cases
        await s.execute(text("UPDATE analysis SET results = CAST(:r AS jsonb), updated_at = now() WHERE id = :id"),
                        {"r": _j(results), "id": a["id"]})
        await audit(s, actor, "analysis.case_updated", "analysis", a["id"], None, entry, request_id)
        marked.append(r["code"])
    return marked


async def make_document_public(s: AsyncSession, code: str, document_id: int, actor: str, doc_ok=None,
                               request_id: str | None = None) -> dict:
    """Owner's explicit choice: a document of this analysis is public after all (e.g. downloaded from BZP). Only then
    may the AI pass use cloud models; the jobs are queued again. Confidential data never leaves PL without this."""
    a = await _load(s, code)
    if document_id not in [int(x) for x in (a.get("input_documents") or [])]:
        raise NotFound(f"{code}/{document_id}")
    await check_docs(s, [document_id], doc_ok)
    before = (await s.execute(text("SELECT sensitivity FROM document WHERE id = :d"), {"d": document_id})).scalar()
    await s.execute(text("UPDATE document SET sensitivity = 'public', updated_at = now() WHERE id = :d"),
                    {"d": document_id})
    docs = await _documents(s, list(a.get("input_documents") or []))
    if all(x["sensitivity"] == "public" for x in docs):
        await s.execute(text("UPDATE analysis SET sensitivity = 'public' WHERE id = :id"), {"id": a["id"]})
    results = dict(a.get("results") or {})
    jobs = dict(results.get("jobs") or {})
    jobs["features"] = await enqueue(s, "analysis_features_ai", {"analysis_code": code}, actor, priority=20)
    if results.get("report"):
        jobs["redpen"] = await enqueue(s, "analysis_redpen", {"analysis_code": code}, actor, priority=30)
    results["jobs"] = jobs
    await s.execute(text("UPDATE analysis SET results = CAST(:r AS jsonb), updated_at = now() WHERE id = :id"),
                    {"r": _j(results), "id": a["id"]})
    await audit(s, actor, "document.make_public", "document", document_id, {"sensitivity": before},
                {"sensitivity": "public", "analysis": code}, request_id)
    return {"document_id": document_id, "sensitivity": "public", "jobs": jobs}
