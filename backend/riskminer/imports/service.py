"""Import agent service (api_contract §2.4 2.1, §3.5). All request-path writes use the request session (rollback-able in
tests) and leave an audit_log row; the full run is a job (`import_mapped`, riskminer/imports/jobs.py)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import settings
from riskminer.imports import registry, rules, runner, sandbox

STATUS_PL = {"uploaded": "wgrane", "inspected": "przejrzane", "awaiting_answer": "czeka na odpowiedź", "mapped": "zmapowane",
             "tested": "próba wykonana", "approved": "importer zatwierdzony", "running": "import trwa", "done": "zakończony",
             "failed": "błąd"}


def imports_dir() -> Path:
    return Path(settings().data_dir) / "imports"


def _safe(name: str) -> str:
    base = Path(name or "plik").name
    return re.sub(r"[^\w.\-]+", "_", base)[:150] or "plik"


async def _audit(db: AsyncSession, actor: str, action: str, row_id: int | None, after: dict, request_id: str | None) -> None:
    await db.execute(text("INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id) "
                          "VALUES (:a, :ac, 'import_session', :r, CAST(:after AS jsonb), :rid)"),
                     {"a": actor, "ac": action, "r": row_id, "after": json.dumps(after, ensure_ascii=False, default=str),
                      "rid": request_id})


async def _load(db: AsyncSession, code: str) -> dict | None:
    r = (await db.execute(text("SELECT * FROM import_session WHERE code = :c"), {"c": code})).mappings().first()
    return dict(r) if r else None


async def _save(db: AsyncSession, code: str, **fields) -> None:
    sets = ", ".join(f"{k} = CAST(:{k} AS jsonb)" if k in ("files", "tool_calls", "mapping", "questions", "answers", "test_result")
                     else f"{k} = :{k}" for k in fields)
    params = {k: (json.dumps(v, ensure_ascii=False, default=str) if k in ("files", "tool_calls", "mapping", "questions", "answers",
                                                                           "test_result") else v) for k, v in fields.items()}
    params["code"] = code
    await db.execute(text(f"UPDATE import_session SET {sets}, updated_at = now() WHERE code = :code"), params)


def _public_calls(calls: list[dict]) -> list[dict]:
    return [{k: c.get(k) for k in ("call", "out", "ms", "llm")} for c in calls]


async def state(db: AsyncSession, code: str) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    importer = None
    if s["importer_id"]:
        i = (await db.execute(text("SELECT id, name, version, spec FROM importer WHERE id = :i"), {"i": s["importer_id"]})).mappings().first()
        if i:
            importer = {"id": i["id"], "name": i["name"], "version": f"v{i['version']}", "spec_preview": _preview(i["spec"])}
    if importer is None:
        draft = (s["answers"] or {}).get("_importer_draft")
        if draft:
            importer = draft
    return {"code": s["code"], "status": s["status"], "status_label": STATUS_PL.get(s["status"], s["status"]),
            "files": [{k: f.get(k) for k in ("name", "bytes", "sha256", "kind", "duplicate_of_source_id")} for f in s["files"]],
            "tool_calls": _public_calls(s["tool_calls"] or []), "mapping": s["mapping"] or [], "questions": s["questions"] or [],
            "rules": rules.RULES_PL, "importer": importer, "test_run": s["test_result"], "job_id": s["job_id"],
            "run_id": str(s["run_id"]) if s["run_id"] else None}


def _preview(spec: dict | None) -> dict:
    spec = spec or {}
    cols = {h: {"field": m.get("field"), "rule": m.get("rule")} for h, m in (spec.get("columns") or {}).items() if m.get("field")}
    return {"sheet": spec.get("sheet"), "columns": cols}


# ---- steps ------------------------------------------------------------------------------------------------------------

async def create(db: AsyncSession, uploads: list[tuple[str, Any]], actor: str, request_id: str | None) -> dict:
    code = (await db.execute(text("SELECT rm_next_code('IMP')"))).scalar()
    d = imports_dir() / code
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name, stream in uploads:
        fname = _safe(name)
        target = d / fname
        h = hashlib.sha256()
        size = 0
        with target.open("wb") as out:
            while True:
                chunk = await stream.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        sha = h.hexdigest()
        dup = (await db.execute(text("SELECT id FROM source WHERE sha256 = :s ORDER BY id LIMIT 1"), {"s": sha})).scalar()
        files.append({"name": fname, "bytes": size, "sha256": sha, "kind": sandbox.kind_of(fname), "duplicate_of_source_id": dup,
                      "path": str(target)})
    sid = (await db.execute(text("""INSERT INTO import_session (code, status, files, sandbox_path, created_by)
                                    VALUES (:c, 'uploaded', CAST(:f AS jsonb), :p, :by) RETURNING id"""),
                            {"c": code, "f": json.dumps(files), "p": str(d), "by": actor})).scalar()
    await _audit(db, actor, "import.upload", sid, {"code": code, "files": [{k: f[k] for k in ("name", "bytes", "sha256")} for f in files]},
                 request_id)
    return {"code": code, "status": "uploaded",
            "files": [{k: f[k] for k in ("name", "bytes", "sha256", "kind", "duplicate_of_source_id")} for f in files]}


async def _approved_importers(db: AsyncSession) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(
        "SELECT id, name, version, spec FROM importer WHERE status = 'approved' ORDER BY name, version DESC"))).mappings().all()]


def _call(name: str, fn, *args, llm: bool = False, **kw) -> dict:
    t0 = time.time()
    try:
        out, data = fn(*args, **kw)
    except Exception as e:  # noqa: BLE001 - a broken file is reported, not raised
        out, data = f"błąd: {type(e).__name__}", {"error": str(e)[:300]}
    return {"call": name, "out": out, "ms": int((time.time() - t0) * 1000), "llm": llm, "data": data}


async def inspect(db: AsyncSession, code: str, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    importers = await _approved_importers(db)
    calls = []
    for f in s["files"]:
        p = Path(f["path"])
        if f["kind"] == "zip":
            c = _call(f'list_archive("{f["name"]}")', sandbox.list_archive, p)
            calls.append(c)
            names = (c["data"] or {}).get("names") or []
            calls.append(_call(f"classify_docs(sample={min(len(names), sandbox.MAX_CLASSIFY)})", sandbox.classify_docs, names))
        elif f["kind"] in ("xlsx", "csv") or f["kind"] in sandbox.RECORD_KINDS:
            c = _call(f'sample_rows("{f["name"]}", n={sandbox.MAX_SAMPLE})', sandbox.sample_rows, p)
            c["file"] = f["name"]
            headers = (c["data"] or {}).get("headers") or []
            if f["kind"] in sandbox.RECORD_KINDS and sum(1 for h in headers if sandbox._known(h)) < 3:
                # a text document, not a record: classify it like any other document
                calls.append(_call(f'classify_docs("{f["name"]}")', sandbox.classify_docs, [f["name"]]))
                continue
            f["tabular"] = True
            calls.append(c)
            m = _call("match_schema(known_formats)", sandbox.match_schema, headers, importers)
            m["file"] = f["name"]
            calls.append(m)
        else:
            calls.append(_call(f'classify_docs("{f["name"]}")', sandbox.classify_docs, [f["name"]]))
    await _save(db, code, tool_calls=calls, files=s["files"], status="inspected")
    await _audit(db, actor, "import.inspect", s["id"], {"calls": [c["call"] for c in calls]}, request_id)
    return await state(db, code)


def _validity(sample: dict, header: str, rule: str | None, answers: dict) -> tuple[int, int]:
    hs = sample.get("headers") or []
    if header not in hs:
        return 0, 0
    i = hs.index(header)
    vals = [r[i] for r in sample.get("rows") or [] if i < len(r) and r[i] not in (None, "")]
    ok = sum(1 for v in vals if rules.check(rule, v, answers)[0])
    return ok, len(vals)


async def propose_mapping(db: AsyncSession, code: str, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    calls = s["tool_calls"] or []
    sample = next((c["data"] for c in calls if c["call"].startswith("sample_rows")), None)
    match = next((c["data"] for c in calls if c["call"].startswith("match_schema")), None) or {}
    if sample is None:
        return {"error": "Najpierw uruchom przegląd plików (inspect)."}
    answers = s["answers"] or {}
    importer_spec = None
    if match.get("importer_id") and (match.get("score") or 0) >= 0.8:
        importer_spec = (await db.execute(text("SELECT spec FROM importer WHERE id = :i"), {"i": match["importer_id"]})).scalar()
    mapping, used_llm = [], False
    for h in sample.get("all_headers") or []:
        if not h:
            continue
        if rules.is_pii_header(h):
            mapping.append({"column": h, "field": None, "rule": "personal_data", "status": "dropped"})
            continue
        f = ((importer_spec or {}).get("columns") or {}).get(h, {}).get("field") or registry.field_for(h)
        if not f:
            mapping.append({"column": h, "field": None, "rule": None, "status": "proposal"})
            continue
        label, rule = registry.TARGET_FIELDS[f]
        ok, total = _validity(sample, h, rule, answers)
        if rule == "money_requires_vat_basis" and answers.get("value_vat_basis") not in ("net", "gross"):
            status = "question"
        elif total and ok / total < 0.8:
            status = "check"
        else:
            status = "ok"
        mapping.append({"column": h, "field": f, "label": label, "rule": rule, "status": status, "valid": ok, "total": total})
    unknown = [m["column"] for m in mapping if m["status"] == "proposal"]
    if unknown:   # the LLM may suggest fields for unknown headers; suggestions stay proposals until validated
        try:
            from riskminer.llm.tasks import import_mapping  # session L
            sugg = await import_mapping.propose(headers=unknown, sample=sample, fields=list(registry.TARGET_FIELDS))
            used_llm = True
            for m in mapping:
                f = (sugg or {}).get(m["column"])
                if m["status"] == "proposal" and f in registry.TARGET_FIELDS:
                    m.update(field=f, label=registry.TARGET_FIELDS[f][0], rule=registry.TARGET_FIELDS[f][1], suggested_by="model")
        except Exception:  # noqa: BLE001 - no model available: unknown columns stay proposals, never imported
            used_llm = False
    questions = []
    if any(m["status"] == "question" for m in mapping):
        questions.append({"key": "value_vat_basis", "text": "Kwoty w pliku: netto czy brutto?",
                          "options": [{"value": "gross", "label": "Brutto, z VAT."}, {"value": "net", "label": "Netto, bez VAT."}]})
    calls = calls + [{"call": "propose_mapping(headers, sample<=20)", "ms": 0, "llm": used_llm,
                      "out": f"{sum(1 for m in mapping if m['field'])} z {len(mapping)} kolumn zmapowanych", "data": {}}]
    name = match.get("best") if (match.get("score") or 0) >= 0.5 else "nowy importer"
    draft = {"name": name, "version": f"v{(match.get('version') or 0) + 1}" if match.get("importer_id") else "v1",
             "spec_preview": _preview(_spec(sample, mapping, answers))}
    answers = {**answers, "_importer_draft": draft}
    await _save(db, code, mapping=mapping, questions=questions, tool_calls=calls, answers=answers,
                status="awaiting_answer" if questions else "mapped")
    await _audit(db, actor, "import.propose_mapping", s["id"],
                 {"mapped": sum(1 for m in mapping if m["field"]), "questions": [q["key"] for q in questions]}, request_id)
    return await state(db, code)


def _spec(sample: dict, mapping: list[dict], answers: dict) -> dict:
    return {"format": "xlsx" if sample.get("sheet") else "csv", "sheet": sample.get("sheet"), "headers": sample.get("all_headers"),
            "columns": {m["column"]: {"field": m["field"], "rule": m["rule"], "status": m["status"]} for m in mapping if m.get("field")},
            "answers": {k: v for k, v in answers.items() if not k.startswith("_")}}


async def answer(db: AsyncSession, code: str, body: dict, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    answers = {**(s["answers"] or {}), **{k: v for k, v in body.items() if not k.startswith("_")}}
    if answers.get("value_vat_basis") not in (None, "net", "gross"):
        return {"error": "Dozwolone odpowiedzi: net albo gross."}
    mapping = s["mapping"] or []
    for m in mapping:
        if m.get("status") == "question" and m.get("rule") == "money_requires_vat_basis" and answers.get("value_vat_basis"):
            m["status"] = "ok"
    questions = [q for q in (s["questions"] or []) if q["key"] not in answers]
    await _save(db, code, answers=answers, mapping=mapping, questions=questions,
                status="awaiting_answer" if questions else "mapped")
    await _audit(db, actor, "import.answer", s["id"], {k: v for k, v in body.items()}, request_id)
    return await state(db, code)


def _is_table(f: dict) -> bool:
    return f["kind"] in ("xlsx", "csv") or bool(f.get("tabular"))


def _first_table(s: dict) -> dict | None:
    return next((f for f in s["files"] if _is_table(f)), None)


async def test_run(db: AsyncSession, code: str, rows: int, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    if s["questions"]:
        return {"error": "Najpierw odpowiedz na pytania agenta."}
    f = _first_table(s)
    if not f:
        return {"error": "Brak pliku z tabelą (XLSX/CSV) do importu."}
    sample = next((c["data"] for c in s["tool_calls"] if c["call"].startswith("sample_rows")), {}) or {}
    spec = _spec(sample, s["mapping"] or [], s["answers"] or {})
    res = await runner.run(db, Path(f["path"]), spec, file_sha=f["sha256"], source_id=None, limit=max(1, min(rows, 500)),
                           dry_run=True)
    items = 0
    for fl in res.failures:
        await db.execute(text("""
            INSERT INTO review_item (key, kind, code, title, detail, severity, created_by)
            VALUES (:k, 'import', :rule, :t, CAST(:d AS jsonb), 'medium', :by)
            ON CONFLICT (key) DO UPDATE SET detail = EXCLUDED.detail, status = 'open', updated_at = now()"""),
            {"k": f"imp:{code}:row:{fl['row']}:{fl['column']}"[:200], "rule": fl["rule"][:60],
             "t": f"Import {code}: wiersz {fl['row']}, kolumna „{fl['column']}” nie przechodzi reguły {fl['rule']}",
             "d": json.dumps({**fl, "import_code": code}, ensure_ascii=False), "by": actor})
        items += 1
    result = {"ok": res.ok, "failed": res.failed, "failures": res.failures[:50], "would": res.would, "rows": res.rows,
              "review_items_created": items}
    await _save(db, code, test_result=result, status="tested")
    await _audit(db, actor, "import.test_run", s["id"], {k: result[k] for k in ("ok", "failed", "rows")}, request_id)
    return result


async def approve(db: AsyncSession, code: str, importer_name: str, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    if s["status"] not in ("tested", "approved"):
        return {"error": "Najpierw wykonaj próbny import."}
    sample = next((c["data"] for c in s["tool_calls"] if c["call"].startswith("sample_rows")), {}) or {}
    spec = _spec(sample, s["mapping"] or [], s["answers"] or {})
    sha = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    same = (await db.execute(text("SELECT id, version FROM importer WHERE name = :n AND spec_sha256 = :s"),
                             {"n": importer_name, "s": sha})).first()
    if same:
        iid, ver = same
    else:
        ver = ((await db.execute(text("SELECT max(version) FROM importer WHERE name = :n"), {"n": importer_name})).scalar() or 0) + 1
        fmt_label = f"{(spec.get('format') or '').upper()}, {len(spec.get('headers') or [])} kolumn"
        iid = (await db.execute(text("""INSERT INTO importer (name, version, format, spec, spec_sha256, created_by, approved_by)
                                        VALUES (:n, :v, :f, CAST(:s AS jsonb), :sha, :by, :by) RETURNING id"""),
                                {"n": importer_name, "v": ver, "f": fmt_label, "s": json.dumps(spec, ensure_ascii=False),
                                 "sha": sha, "by": actor})).scalar()
    await db.execute(text("""INSERT INTO review (target_table, target_id, action, after, reviewer, comment)
                             VALUES ('importer', :i, 'approve', CAST(:a AS jsonb), :by, :c)"""),
                     {"i": iid, "a": json.dumps({"name": importer_name, "version": ver, "spec_sha256": sha}), "by": actor,
                      "c": f"import {code}"})
    await _save(db, code, importer_id=iid, status="approved")
    await _audit(db, actor, "import.approve", s["id"], {"importer_id": iid, "name": importer_name, "version": ver}, request_id)
    return {"importer_id": iid, "version": f"v{ver}"}


async def start_run(db: AsyncSession, code: str, actor: str, request_id: str | None) -> dict | None:
    s = await _load(db, code)
    if not s:
        return None
    if not s["importer_id"]:
        return {"error": "Najpierw zatwierdź importer."}
    run_id = uuid.uuid4()
    job_id = (await db.execute(text("""INSERT INTO job (kind, payload, created_by) VALUES ('import_mapped', CAST(:p AS jsonb), :by)
                                       RETURNING id"""),
                               {"p": json.dumps({"import_code": code, "importer_id": s["importer_id"], "run_id": str(run_id)}),
                                "by": actor})).scalar()
    await _save(db, code, job_id=job_id, run_id=str(run_id), status="running")
    await _audit(db, actor, "import.run", s["id"], {"job_id": job_id, "run_id": str(run_id)}, request_id)
    return {"job_id": job_id, "run_id": str(run_id)}


async def importers(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("""SELECT DISTINCT ON (name) name, version, format, uses FROM importer
                                     WHERE status = 'approved' ORDER BY name, version DESC"""))).mappings().all()
    return [{"name": r["name"], "format_label": r["format"], "uses": r["uses"], "version": f"v{r['version']}"} for r in rows]


# ---- full run (job) -----------------------------------------------------------------------------------------------------

def raw_root() -> Path | None:
    """Root for RawStore (None = data/raw); tests point it at a temp dir."""
    return None


async def full_run(db: AsyncSession, code: str, run_id: str | None = None) -> dict:
    """Same code path as the test run with dry_run = False. Each file is copied into data/raw/imports/ with a manifest
    line and gets a `source` row; every imported row cites it."""
    from riskminer.connectors.base import RawStore, request_key, sha256_bytes
    s = await _load(db, code)
    if not s or not s["importer_id"]:
        raise ValueError(f"import {code}: no approved importer")
    spec = (await db.execute(text("SELECT spec FROM importer WHERE id = :i"), {"i": s["importer_id"]})).scalar()
    rid = uuid.UUID(run_id) if run_id else uuid.uuid4()
    await db.execute(text("""INSERT INTO ingestion_run (id, connector, stage, params, status) VALUES (:id, 'import', 'load',
                             CAST(:p AS jsonb), 'running') ON CONFLICT (id) DO UPDATE SET status = 'running'"""),
                     {"id": rid, "p": json.dumps({"import_code": code, "importer_id": s["importer_id"]})})
    store = RawStore("imports", root=raw_root())
    stats: dict[str, Any] = {"files": 0, "rows": 0, "ok": 0, "failed": 0, "inserted": 0, "updated": 0, "protected_skipped": 0,
                             "projects": []}
    for f in s["files"]:
        src = Path(f["path"])
        dest = store.path_for(f"{f['sha256'][:16]}_{f['name']}")
        if not dest.exists():
            shutil.copyfile(src, dest)
        content_sha = sha256_bytes(dest.read_bytes())
        now = datetime.now(UTC)
        store.append({"source": "imports", "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "method": "UPLOAD",
                      "url": f"upload:{code}/{f['name']}", "params": {}, "http_status": None, "content_type": None,
                      "bytes": f["bytes"], "sha256": content_sha, "path": store.rel(dest), "licence": "user-upload",
                      "run_id": str(rid), "status": "ok", "note": f"import {code}", "key": request_key("UPLOAD", f["name"], {"c": code})})
        sid = (await db.execute(text("SELECT id FROM source WHERE sha256 = :s AND kind = 'import' ORDER BY id LIMIT 1"),
                                {"s": content_sha})).scalar()
        if not sid:
            sid = (await db.execute(text("""INSERT INTO source (kind, url, method, retrieved_at, bytes, sha256, path, licence, status,
                                            note, run_id, manifest_key) VALUES ('import', :u, 'UPLOAD', now(), :b, :s, :p,
                                            'user-upload', 'ok', :n, :r, :k) RETURNING id"""),
                                    {"u": f"upload:{code}/{f['name']}", "b": f["bytes"], "s": content_sha, "p": store.rel(dest),
                                     "n": f"import {code}", "r": rid, "k": content_sha[:64]})).scalar()
        stats["files"] += 1
        if not _is_table(f):
            continue
        res = await runner.run(db, dest, spec, file_sha=content_sha, source_id=sid, dry_run=False)
        stats["rows"] += res.rows
        stats["ok"] += res.ok
        stats["failed"] += res.failed
        stats["inserted"] += res.would["insert"]["project"]
        stats["updated"] += res.would["update"]
        stats["protected_skipped"] += res.would["protected_skipped"]
        stats["projects"] += [k for k in res.written_keys if k not in stats["projects"]]
        for fl in res.failures:
            await db.execute(text("""INSERT INTO review_item (key, kind, code, title, detail, severity, created_by, source_id)
                VALUES (:k, 'import', :rule, :t, CAST(:d AS jsonb), 'medium', 'system:import', :sid)
                ON CONFLICT (key) DO UPDATE SET detail = EXCLUDED.detail, updated_at = now()"""),
                {"k": f"imp:{code}:row:{fl['row']}:{fl['column']}"[:200], "rule": fl["rule"][:60],
                 "t": f"Import {code}: wiersz {fl['row']}, kolumna „{fl['column']}” nie przechodzi reguły {fl['rule']}",
                 "d": json.dumps({**fl, "import_code": code}, ensure_ascii=False), "sid": sid})
    await db.execute(text("UPDATE importer SET uses = uses + 1 WHERE id = :i"), {"i": s["importer_id"]})
    await db.execute(text("UPDATE ingestion_run SET status = 'ok', finished_at = now(), stats = CAST(:s AS jsonb) WHERE id = :id"),
                     {"s": json.dumps(stats), "id": rid})
    await _save(db, code, status="done")
    await _audit(db, "system:import", "import.done", s["id"], stats, None)
    return {"import_code": code, "run_id": str(rid), **stats}
