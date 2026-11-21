"""Import agent 2.1 (api_contract §2.4 2.1, §3.5). Owner: D (data-db). Login required for every step; writes need a
writer (expert or admin): the read-only demo Juror gets 403 read_only.
Sandbox tools, rules and the deterministic importer live in `riskminer/imports/`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.db.session import get_session
from riskminer.imports import service as S

router = APIRouter(prefix="/api", tags=["imports"], dependencies=[Depends(A.require_login)])
DB = Depends(get_session)
CSRF = [Depends(A.csrf_guard)]


class TestRunIn(BaseModel):
    rows: int = 50


class ApproveIn(BaseModel):
    importer_name: str


def _check(res: Any, code: str):
    if res is None:
        raise A.ApiError(404, f"Nie ma importu {code}.", "import_not_found")
    if isinstance(res, dict) and res.get("error"):
        raise A.ApiError(409, res["error"], "import_step_order")
    return res


@router.post("/imports", status_code=201, summary="Wgraj pliki do importu", dependencies=CSRF)
async def create_import(request: Request, files: list[UploadFile] = File(...), user: A.User = Depends(A.require_writer),
                        db: AsyncSession = DB):
    if not files:
        raise A.ApiError(422, "Dodaj co najmniej jeden plik.", "no_files")
    res = await S.create(db, [(f.filename or "plik", f) for f in files], user.actor, A.request_id(request))
    await db.commit()
    return res


@router.get("/imports/{code}", summary="Stan importu")
async def get_import(code: str, db: AsyncSession = DB):
    return _check(await S.state(db, code), code)


@router.post("/imports/{code}/inspect", summary="Agent: przejrzyj pliki (zarejestrowane narzędzia)", dependencies=CSRF)
async def inspect(code: str, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    res = _check(await S.inspect(db, code, user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.post("/imports/{code}/propose-mapping", summary="Agent: zaproponuj mapowanie kolumn", dependencies=CSRF)
async def propose_mapping(code: str, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    res = _check(await S.propose_mapping(db, code, user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.post("/imports/{code}/answers", summary="Odpowiedz na pytania agenta", dependencies=CSRF)
async def answers(code: str, body: dict[str, Any], request: Request, user: A.User = Depends(A.require_writer),
                  db: AsyncSession = DB):
    res = _check(await S.answer(db, code, body, user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.post("/imports/{code}/test-run", summary="Próbny import (transakcja wycofana)", dependencies=CSRF)
async def test_run(code: str, body: TestRunIn, request: Request, user: A.User = Depends(A.require_writer),
                   db: AsyncSession = DB):
    res = _check(await S.test_run(db, code, body.rows, user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.post("/imports/{code}/approve", summary="Zatwierdź importer", dependencies=CSRF)
async def approve(code: str, body: ApproveIn, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    res = _check(await S.approve(db, code, body.importer_name.strip() or "importer", user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.post("/imports/{code}/run", summary="Uruchom pełny import (zadanie)", dependencies=CSRF)
async def run(code: str, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    res = _check(await S.start_run(db, code, user.actor, A.request_id(request)), code)
    await db.commit()
    return res


@router.get("/importers", summary="Zatwierdzone importery")
async def importers(db: AsyncSession = DB):
    return await S.importers(db)
