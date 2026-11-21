"""few_shot reads B's document gold examples (rolled back)."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from riskminer.config import settings
from riskminer.llm.learning import few_shot, rates

pytestmark = pytest.mark.fulldb


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


async def test_gold_examples_feed_few_shot(db):
    did = (await db.execute(text("INSERT INTO document (filename, sensitivity, origin, review_status, data) VALUES "
                                 "('p.pdf', 'public', 'SOURCE', 'auto', CAST(:d AS jsonb)) RETURNING id"),
                            {"d": '{"facts": {"doc_kind": "protokol_koniecznosci"}}'})).scalar_one()
    for code, quote, retracted in (("R02", "wysoki poziom wód gruntowych przy wykopie", False),
                                   ("R03", "kolizja z siecią gazową", True)):
        out = {"document_id": did, "item_code": "document_cause", "action": "approve"}
        if retracted:
            out["retracted"] = True
        await db.execute(text("INSERT INTO gold_example (task, catalogue_code, input_text, output, created_by) VALUES "
                              "('document_facts', :c, :q, CAST(:o AS jsonb), 'user:test')"),
                         {"c": code, "q": quote, "o": __import__("json").dumps(out)})
    fs = await few_shot(db, "protokol_koniecznosci")
    assert fs["n_examples"] >= 1 and "wysoki poziom wód gruntowych" in fs["examples"] and "R02" in fs["examples"]
    assert "kolizja z siecią gazową" not in fs["examples"]           # undone decision is not a model input
    r = await rates(db)
    assert r["gold_examples_documents"] >= 1
