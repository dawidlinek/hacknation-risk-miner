"""BZP notices -> `notice` rows. Shared by the offline copy loader (streamed, multi-process) and the
live API loader (data/raw/bzp_api pages). Records are kept exactly as the API returns them:
`raw_json` = record minus htmlBody, `html_body` = the official form, parsed per field code."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from riskminer.parsing import bzp_parse as bp
from riskminer.parsing.wodkan_classify import classify

log = logging.getLogger("riskminer.bzp")

NOTICE_URL = "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{}"
TYPE_ABBR = {"ContractNotice": "CN", "TenderResultNotice": "TR", "AgreementUpdateNotice": "AU",
             "ContractPerformingNotice": "CP", "NoticeUpdateNotice": "NU"}
_REF_RE = re.compile(r"(\d{4})\s*/\s*BZP\s*0*(\d{5,9})", re.I)
_URL_RE = re.compile(r"https?://[^\s<>\"']+")

NOTICE_COLS = (
    "object_id", "notice_type", "notice_number", "bzp_number", "version", "ocid", "published_at", "buyer_nip",
    "buyer_name", "buyer_city", "province", "order_object", "cpv_raw", "refs", "raw_json", "html_body",
    "parsed_fields", "extracted", "url", "source_locator", "channel", "source_id", "origin", "review_status",
)


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, ensure_ascii=False, default=str))


def notice_row(rec: dict, locator: str, channel: str, source_id: int | None) -> tuple:
    """One API/JSONL record -> tuple in NOTICE_COLS order (pure function; runs in worker processes)."""
    html = rec.get("htmlBody") or ""
    pn = bp.parse_html(html)
    ntype = rec.get("noticeType") or ""
    ex: Any
    try:
        fn = bp.EXTRACTORS.get(ntype)
        ex = fn(rec, pn) if fn else None
    except Exception as e:  # noqa: BLE001 - keep the notice, flag the parser failure
        ex = {"_parse_error": f"{type(e).__name__}: {e}"}
    extra: dict[str, Any] = {"parts": pn.parts(), "part_markers": pn.part_markers, "template": pn.template_version}
    if ntype == "ContractNotice":
        urls = []
        for code in ("3.1", "3.5"):
            for u in _URL_RE.findall(pn.first(code) or ""):
                u = u.rstrip(".,;)")
                if u not in urls:
                    urls.append(u)
        extra["platform_urls"] = urls
    # classification on the notice's own title/description (procedure-level choice happens in derive)
    first = ex[0] if isinstance(ex, list) and ex else ex if isinstance(ex, dict) else {}
    desc = (first or {}).get("shortDescription") or (first or {}).get("description") or ""
    tag = classify(rec.get("orderObject"), desc, (first or {}).get("cpvMain"), (first or {}).get("cpvAll"),
                   rec.get("orderType"))
    extra["class"] = {"relevance": tag.relevance, "primary": tag.primary, "subsectors": tag.subsectors,
                      "scope_kind": tag.scope_kind, "work_type": tag.work_type, "design_build": tag.design_build,
                      "why": tag.why}
    own = (rec.get("bzpNumber") or "").upper()
    refs = sorted({f"{m.group(1)}/BZP {int(m.group(2)):08d}" for m in _REF_RE.finditer(html)} - {own})
    raw = {k: v for k, v in rec.items() if k != "htmlBody"}
    nn = bp.notice_no(rec.get("noticeNumber"))
    ver = int(nn["version"]) if nn.get("version") else None
    pub = rec.get("publicationDate")
    try:
        pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
    except ValueError:
        pub_dt = None
    return (
        rec.get("objectId"), ntype, rec.get("noticeNumber") or "", rec.get("bzpNumber"), ver,
        rec.get("tenderId") or None, pub_dt, bp.nip(rec.get("organizationNationalId")) or rec.get("organizationNationalId"),
        rec.get("organizationName"), rec.get("organizationCity"), rec.get("organizationProvince"),
        rec.get("orderObject"), rec.get("cpvCode"), refs, raw, html, pn.as_dict(),
        _jsonable({"data": ex, **extra}), NOTICE_URL.format(rec.get("objectId")), locator, channel, source_id,
        "SOURCE", "auto",
    )


# ---- offline copy: split the 2.7 GB JSONL into byte ranges, one process per range --------------

def _ranges(path: Path, n: int) -> list[tuple[int, int]]:
    size = path.stat().st_size
    bounds = [0]
    with path.open("rb") as fh:
        for i in range(1, n):
            fh.seek(size * i // n)
            fh.readline()
            bounds.append(fh.tell())
    bounds.append(size)
    return [(bounds[i], bounds[i + 1]) for i in range(n) if bounds[i + 1] > bounds[i]]


def _line_offsets_start(path: Path, start: int) -> int:
    """Line number (1-based) of the line starting at byte `start` (counts newlines before it)."""
    if start == 0:
        return 1
    n = 0
    with path.open("rb") as fh:
        remaining = start
        while remaining > 0:
            chunk = fh.read(min(1 << 24, remaining))
            if not chunk:
                break
            n += chunk.count(b"\n")
            remaining -= len(chunk)
    return n + 1


def _worker(args: tuple[str, int, int, int | None, str, int, int | None]) -> dict:
    path, start, end, source_id, dsn, worker_no, limit = args
    return asyncio.run(_worker_async(Path(path), start, end, source_id, dsn, worker_no, limit))


async def _worker_async(path: Path, start: int, end: int, source_id: int | None, dsn: str, worker_no: int,
                        limit: int | None) -> dict:
    import asyncpg

    from riskminer.db.session import set_codecs

    conn = await asyncpg.connect(dsn)
    await set_codecs(conn)
    line_no = _line_offsets_start(path, start)
    batch: list[tuple] = []
    n = errors = 0
    with path.open("rb") as fh:
        fh.seek(start)
        while fh.tell() < end:
            raw = fh.readline()
            if not raw:
                break
            ln = line_no
            line_no += 1
            if not raw.strip():
                continue
            try:
                if b"\\u0000" in raw:       # Postgres text cannot hold NUL
                    raw = raw.replace(b"\\u0000", b"")
                rec = json.loads(raw)
                batch.append(notice_row(rec, f"line:{ln}", "bzp_copy", source_id))
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.warning("line %s: %s", ln, e)
            n += 1
            if len(batch) >= 1000:
                await conn.copy_records_to_table("notice_stage", records=batch, columns=list(NOTICE_COLS))
                batch.clear()
            if limit and n >= limit:
                break
    if batch:
        await conn.copy_records_to_table("notice_stage", records=batch, columns=list(NOTICE_COLS))
    await conn.close()
    return {"worker": worker_no, "lines": n, "errors": errors}


async def load_copy(conn, path: Path, source_id: int, dsn: str, workers: int | None = None,
                    limit: int | None = None) -> dict:
    """Parse the JSONL in parallel into UNLOGGED notice_stage, then upsert into notice."""
    workers = workers or max(2, min(10, (os.cpu_count() or 4) - 2))
    await conn.execute("DROP TABLE IF EXISTS notice_stage")
    await conn.execute("CREATE UNLOGGED TABLE notice_stage (LIKE notice INCLUDING DEFAULTS)")
    ranges = _ranges(path, 1 if limit else workers)
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=len(ranges)) as ex:
        futs = [loop.run_in_executor(ex, _worker, (str(path), a, b, source_id, dsn, i, limit))
                for i, (a, b) in enumerate(ranges)]
        parts = await asyncio.gather(*futs)
    staged = await conn.fetchval("SELECT count(*) FROM notice_stage")
    n = await upsert_from_stage(conn)
    await conn.execute("DROP TABLE notice_stage")
    return {"workers": parts, "staged": staged, "upserted": n}


async def upsert_from_stage(conn) -> int:
    cols = ", ".join(NOTICE_COLS)
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in NOTICE_COLS if c != "object_id")
    r = await conn.execute(
        f"INSERT INTO notice ({cols}) SELECT DISTINCT ON (object_id) {cols} FROM notice_stage ORDER BY object_id "
        f"ON CONFLICT (object_id) DO UPDATE SET {upd}, updated_at = now() "
        # the organizer copy is the cited source for its notices; a live re-fetch of the same objectId does not
        # replace it (the live comparison is recorded as source_check by the bzp_api connector)
        f"WHERE notice.channel = EXCLUDED.channel OR EXCLUDED.channel = 'bzp_copy'")
    return int(r.split()[-1])


async def mark_latest_versions(conn) -> dict:
    """Same (type, bzp_number) published in several versions: the latest version wins."""
    await conn.execute("UPDATE notice SET is_latest = true, superseded_by_id = NULL WHERE NOT is_latest")
    r = await conn.execute("""
        WITH ranked AS (
          SELECT id, notice_type, bzp_number,
                 first_value(id) OVER w AS latest_id, row_number() OVER w AS rn
          FROM notice WHERE bzp_number IS NOT NULL
          WINDOW w AS (PARTITION BY notice_type, bzp_number ORDER BY coalesce(version, 1) DESC, published_at DESC, id DESC)
        )
        UPDATE notice n SET is_latest = false, superseded_by_id = ranked.latest_id
        FROM ranked WHERE n.id = ranked.id AND ranked.rn > 1""")
    return {"superseded": int(r.split()[-1])}


async def load_records(conn, items: list[tuple[dict, str | None, int | None]], channel: str) -> int:
    """Upsert a small list of API records [(record, locator, source_id)] (live delta)."""
    if not items:
        return 0
    await conn.execute("DROP TABLE IF EXISTS notice_stage")
    await conn.execute("CREATE UNLOGGED TABLE notice_stage (LIKE notice INCLUDING DEFAULTS)")
    rows = [notice_row(json.loads(json.dumps(r, ensure_ascii=False).replace("\\u0000", "")), loc or "", channel, sid)
            for r, loc, sid in items]
    await conn.copy_records_to_table("notice_stage", records=rows, columns=list(NOTICE_COLS))
    n = await upsert_from_stage(conn)
    await conn.execute("DROP TABLE notice_stage")
    return n
