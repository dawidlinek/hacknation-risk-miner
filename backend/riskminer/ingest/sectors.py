"""Sector of a procedure from the sector packs (catalogue/<sector>/pack.yaml `assign:` block): a new sector is data.

Order: the roads channel is `drogi`; a procedure classified as water/sewage (relevance core or component) stays
`wod-kan`; otherwise the packs with an `assign` block are tried by ascending `priority`:
  cpv_main_prefixes           main CPV starts with one of these
  cpv_any_exact               or one of these codes is among all CPVs of the procedure
  exclude_cpv_main_prefixes   unless the main CPV starts with one of these
Anything else stays `wod-kan` (the default corpus sector, relevance none), as before.

`run(conn)` re-applies the rules to existing procedures (only rows whose sector changes are updated); derive uses
`assign_sector` for new loads. rc_contract takes the sector from procedure, so `refresh_rc` follows.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from riskminer.config import settings

WATER = ("core", "component")


@lru_cache
def rules() -> tuple[tuple[int, str, dict], ...]:
    out = []
    root = Path(settings().catalogue_dir)
    for pack in sorted(root.glob("*/pack.yaml")):
        d = yaml.safe_load(pack.read_text(encoding="utf-8")) or {}
        a = d.get("assign")
        if a and d.get("sector"):
            out.append((int(a.get("priority", 100)), d["sector"], a))
    return tuple(sorted(out, key=lambda r: (r[0], r[1])))


def assign_sector(roads: bool, relevance: str | None, cpv_main: str | None, cpv_all: list[str] | None,
                  rule_set: tuple | None = None) -> str:
    if roads:
        return "drogi"
    if relevance in WATER:
        return "wod-kan"
    main = (cpv_main or "").replace("-", "")
    allc = {(c or "").replace("-", "")[:8] for c in (cpv_all or [])}
    for _, sector, a in (rule_set if rule_set is not None else rules()):
        if any(main.startswith(p) for p in a.get("exclude_cpv_main_prefixes") or []):
            continue
        if any(main.startswith(p) for p in a.get("cpv_main_prefixes") or []) or allc & set(a.get("cpv_any_exact") or []):
            return sector
    return "wod-kan"


async def run(conn, rid) -> dict[str, Any]:
    rows = await conn.fetch("SELECT id, sector, relevance, cpv_main, cpv_all FROM procedure")
    rs = rules()
    changes, by = [], {}
    for r in rows:
        new = assign_sector(r["sector"] == "drogi", r["relevance"], r["cpv_main"], r["cpv_all"], rs)
        by[new] = by.get(new, 0) + 1
        if new != r["sector"]:
            changes.append((r["id"], new))
    if changes:
        async with conn.transaction():
            await conn.execute("CREATE TEMP TABLE tmp_sector (id bigint, sector text) ON COMMIT DROP")
            await conn.copy_records_to_table("tmp_sector", records=changes)
            await conn.execute("UPDATE procedure p SET sector = t.sector, updated_at = now() FROM tmp_sector t WHERE p.id = t.id")
    return {"rules": [{"priority": p, "sector": s} for p, s, _ in rs], "procedures_by_sector": by, "changed": len(changes)}
