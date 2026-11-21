"""Pipeline step `extract_document` on one AsyncSession (S0's document_process), rolled back; fake LLM."""
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from riskminer.config import settings
from riskminer.llm.tasks.document_facts import extract_document

pytestmark = pytest.mark.fulldb
FIX = Path(__file__).parents[1] / "fixtures" / "llm" / "docs"


@pytest.fixture
async def db():
    engine = create_async_engine(settings().database_url)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        yield s
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _insert(db, key: str, sensitivity: str) -> int:
    d = json.loads((FIX / f"{key}.json").read_text(encoding="utf-8"))
    did = (await db.execute(text("INSERT INTO document (filename, sensitivity, origin, review_status, data) "
                                 "VALUES (:f, :s, 'SOURCE', 'auto', '{}'::jsonb) RETURNING id"),
                            {"f": d["filename"], "s": sensitivity})).scalar_one()
    for i, t in enumerate(d["pages"], 1):
        await db.execute(text("INSERT INTO document_page (document_id, page_no, text) VALUES (:d, :p, :t)"),
                         {"d": did, "p": i, "t": t})
    return did


@pytest.mark.parametrize("sens", ["public", "confidential"])
async def test_zlawies_step(db, sens):
    did = await _insert(db, "zlawies", sens)
    out = await extract_document(db, did, actor="test")
    assert out["status"] == "done" and out["doc_kind"] == "protokol_koniecznosci"
    assert out["change"]["delta_days"] == 36 and out["change"]["value"]["amount"] == "151481.54"
    facts = (await db.execute(text("SELECT data->'facts' FROM document WHERE id = :i"), {"i": did})).scalar_one()
    assert facts["change"]["legal_basis"] == ["455.1.3"] and facts["identifiers"]["contractor"].startswith("WIMAX")
    assert {c["risk_code"] for c in facts["causes"]} >= {"R02", "R07"}
    assert all(c["page_no"] and c["verification"] in ("exact", "fuzzy") for c in facts["causes"])
    if sens == "confidential":
        assert facts["processing"][-1].get("skipped") == "sovereign_unavailable"


async def test_scan_without_text_waits_for_ocr(db):
    did = (await db.execute(text("INSERT INTO document (filename, sensitivity, origin, review_status, data) "
                                 "VALUES ('scan.pdf', 'public', 'SOURCE', 'auto', '{}'::jsonb) RETURNING id"))).scalar_one()
    assert (await extract_document(db, did, actor="test"))["status"] == "waiting_ocr"
