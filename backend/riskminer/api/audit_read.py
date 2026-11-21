"""Audit log presentation (api_contract §2.8): actor kind/label, Polish action phrase, before/after text, restore support."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORY_SQL = {
    "expert": "a.actor LIKE 'user:%'",
    "model": "a.actor LIKE 'model:%'",
    "import": "(a.action LIKE 'import%' OR a.action LIKE 'link%' OR a.action LIKE 'derive%' OR a.action = 'seed')",
    "catalogue": "a.action LIKE 'catalogue%'",
    "system": "(a.actor LIKE 'system:%' AND NOT (a.action LIKE 'import%' OR a.action LIKE 'link%' OR a.action LIKE 'derive%' OR a.action = 'seed'))",
}
TABLE_NOUN = {"risk_event": "zdarzenie ryzyka", "project_procedure": "powiązanie z postępowaniem", "link_candidate": "kandydata powiązania",
              "project": "rekord projektu", "contract_performance": "dane o wykonaniu umowy", "contract_change": "zmianę umowy",
              "catalogue_risk": "ryzyko w katalogu", "catalogue_entry": "wpis w katalogu", "catalogue_clause": "zapis umowny",
              "catalogue_version": "wersję katalogu", "review_item": "sprawę w kolejce", "gold_example": "wzorcowy przykład",
              "document": "dokument", "analysis": "analizę"}
VERBS = {"auth.login": "zalogował się", "review.approve": "zatwierdził", "review.edit": "poprawił", "review.reject": "odrzucił", "review.undo": "cofnął decyzję dla",
         "review.skip": "pominął", "review.mark_gold": "oznaczył jako wzorzec", "link.correct": "poprawił", "catalogue.edit": "zmienił",
         "catalogue.version": "zapisał", "audit.restore": "przywrócił", "review.sync": "zsynchronizował kolejkę:",
         "import": "zaimportował", "link_pilot": "powiązał", "link_national": "powiązał", "seed": "wczytał", "derive": "wyliczył"}


def actor_kind(actor: str) -> str:
    return "expert" if actor.startswith("user:") else ("model" if actor.startswith("model:") else "system")


def actor_label(actor: str) -> str:
    if actor.startswith("user:"):
        return "Ekspert"
    if actor.startswith("model:"):
        name = actor.split("/", 1)[-1] if "/" in actor else actor.split(":", 1)[1]
        return f"Model {name}"
    if actor.startswith("anon:"):
        return "Użytkownik anonimowy"
    return "System"


def short(v: Any, limit: int = 160) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if "changes" in v and isinstance(v["changes"], list):
            parts = []
            for c in v["changes"]:
                f = c.get("fields") if isinstance(c, dict) and "fields" in c else c
                if isinstance(f, dict):
                    parts.extend(f"{k}: {short(x, 40)}" for k, x in f.items())
            return "; ".join(parts)[:limit]
        return "; ".join(f"{k}: {short(x, 40)}" for k, x in v.items())[:limit]
    if isinstance(v, list):
        return ", ".join(short(x, 30) for x in v)[:limit]
    return str(v)[:limit]


def action_label(row: dict) -> str:
    if row.get("_label"):
        return row["_label"]
    verb = VERBS.get(row["action"]) or next((v for k, v in VERBS.items() if row["action"].startswith(k)), row["action"])
    noun = TABLE_NOUN.get(row.get("table_name") or "", "")
    return f"{verb} {noun}".strip()


def restorable(row: dict) -> bool:
    """Expert decisions (review.approve|edit|reject) that changed rows can be restored: restore is a new edit, never a delete."""
    b = row.get("before")
    return (actor_kind(row["actor"]) == "expert" and row["action"] in ("review.approve", "review.edit", "review.reject")
            and isinstance(b, dict) and any(isinstance(c, dict) and c.get("fields") for c in b.get("changes") or []))


async def object_ref(db: AsyncSession, table: str | None, row_id: int | None) -> dict:
    if table == "project" and row_id:
        rm = (await db.execute(text("SELECT rm_id, title FROM project WHERE id=:i"), {"i": row_id})).first()
        if rm:
            return {"label": f"projekt {rm[0]}", "href": f"/projekty/{rm[0]}"}
    if table in ("project_procedure", "risk_event") and row_id:
        col = "project_id"
        rm = (await db.execute(text(f"SELECT p.rm_id FROM {table} t JOIN project p ON p.id=t.{col} WHERE t.id=:i"), {"i": row_id})).first()
        if rm:
            return {"label": f"{TABLE_NOUN.get(table)} w {rm[0]}", "href": f"/projekty/{rm[0]}"}
    if table and table.startswith("catalogue"):
        return {"label": "Katalogu wiedzy", "href": "/katalog"}
    return {"label": TABLE_NOUN.get(table or "", table or "rekord"), "href": None}


def entry(row: dict, version: str | None = None, obj: dict | None = None) -> dict:
    return {"id": row["id"], "audit_id": row["id"], "at": row["at"].isoformat(), "derived": row["id"] < 0, "actor_kind": actor_kind(row["actor"]),
            "actor_label": actor_label(row["actor"]), "action": row["action"], "action_label": action_label(row),
            "object": obj, "table": row.get("table_name"), "row_id": row.get("row_id"), "before": short(row.get("before")), "after": short(row.get("after")), "why": row.get("note") or "",
            "note": row.get("note"), "ref": None, "version": version, "can_restore": restorable(row), "restorable": restorable(row)}
