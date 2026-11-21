"""Demo reset (DEMO ONLY): record a baseline, later revert every review decision made after it by appending compensating
`review` rows (never deleting; audit_log stays append-only). Covers: review decisions (events, links, discrepancies, facts,
catalogue proposals, link corrections, audit restores), skipped queue items and catalogue versions created after the baseline.
Not covered: analyses and questions (owned by anonymous visitors), monitoring watches, uploads.

CLI: `uv run python -m riskminer.review.demo baseline|reset|status`."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.auth import ApiError
from riskminer.review import catalogue as K
from riskminer.review import service as SV
from riskminer.review.common import audit, expert_writes, jdump

KEY = "demo_baseline"
SKIP_OPTIONS = ("undo", "demo_reset")


async def _scalar(db: AsyncSession, sql: str, **p) -> Any:
    return (await db.execute(text(sql), p)).scalar()


async def get_baseline(db: AsyncSession) -> dict | None:
    return await _scalar(db, "SELECT value FROM app_setting WHERE key = :k", k=KEY)


async def set_baseline(db: AsyncSession, actor: str, request_id: str | None = None) -> dict:
    b = {"at": datetime.now(timezone.utc).isoformat(), "review_id": await _scalar(db, "SELECT coalesce(max(id), 0) FROM review"),
         "audit_id": await _scalar(db, "SELECT coalesce(max(id), 0) FROM audit_log"),
         "catalogue_label": await K.current_label(db)}
    await db.execute(text("""INSERT INTO app_setting (key, value, updated_by) VALUES (:k, CAST(:v AS jsonb), :a)
                             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()"""),
                     {"k": KEY, "v": jdump(b), "a": actor})
    await audit(db, actor, "demo.baseline", "app_setting", None, None, b, request_id, "zapisano stan wyjściowy dema")
    return b


async def pending(db: AsyncSession, b: dict) -> list[dict]:
    """Decisions after the baseline that have not been compensated yet, newest first."""
    rs = (await db.execute(text("""
        SELECT r.* FROM review r
        WHERE r.id > :rid AND r.action IN ('approve','edit','reject') AND r.undo_of IS NULL
          AND coalesce(r.option_key, '') NOT IN ('undo', 'demo_reset')
          AND NOT EXISTS (SELECT 1 FROM review c WHERE c.undo_of = r.id)
        ORDER BY r.id DESC"""), {"rid": b["review_id"]})).mappings().all()
    return [dict(r) for r in rs]


async def reset(db: AsyncSession, actor: str, *, dry_run: bool = False, request_id: str | None = None) -> dict:
    b = await get_baseline(db)
    if not b:
        raise ApiError(409, "Nie zapisano stanu wyjściowego dema. Najpierw wywołaj demo-baseline.", "no_baseline")
    todo = await pending(db, b)
    skipped_items = [r[0] for r in (await db.execute(text("""
        SELECT DISTINCT row_id FROM audit_log WHERE id > :a AND action = 'review.skip' AND table_name = 'review_item'"""), {"a": b["audit_id"]})).all()]
    cur_label = await K.current_label(db)
    out = {"baseline": b, "decisions_to_revert": len(todo), "skipped_to_clear": len(skipped_items),
           "catalogue_restore": cur_label != b["catalogue_label"], "dry_run": dry_run}
    if dry_run:
        return out
    reverted, failed = [], []
    for rv in todo:
        try:
            async with db.begin_nested():  # one stale row must not block the rest of the reset
                res = await SV.revert(db, rv, actor=actor, request_id=request_id, option_key="demo_reset",
                                      comment=f"reset dema: cofnięcie decyzji #{rv['id']}", audit_action="demo.reset")
            reverted.append(res["undone_review_id"])
        except ApiError as e:
            failed.append({"review_id": rv["id"], "code": e.code, "detail": e.detail})
    if skipped_items:
        await db.execute(text("""UPDATE review_item SET detail = detail - 'skipped_at' - 'skipped_by', updated_at = now()
                                 WHERE id = ANY(:ids) AND status = 'open'"""), {"ids": skipped_items})
    restored_to = None
    if cur_label != b["catalogue_label"]:
        r = await K.restore(db, b["catalogue_label"], "reset dema", actor, request_id)
        restored_to = r["catalogue_version"]
    await audit(db, actor, "demo.reset", "app_setting", None, None, {"reverted": len(reverted), "skipped_cleared": len(skipped_items),
                                                                   "catalogue_version": restored_to}, request_id, "reset dema zakończony")
    out.update({"reverted": reverted, "failed": failed, "catalogue_version": restored_to or cur_label})
    return out


async def status(db: AsyncSession) -> dict:
    b = await get_baseline(db)
    if not b:
        return {"baseline": None}
    return {"baseline": b, "decisions_since": len(await pending(db, b)), "catalogue_version": await K.current_label(db)}


async def _main(cmd: str) -> None:
    from riskminer.db.session import sessionmaker
    async with sessionmaker()() as db:
        if cmd == "baseline":
            print(await set_baseline(db, "system:demo"))
        elif cmd == "reset":
            print(await reset(db, "system:demo"))
        else:
            print(await status(db))
        await db.commit()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else "status"))
