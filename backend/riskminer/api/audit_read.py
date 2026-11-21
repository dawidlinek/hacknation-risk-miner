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


# Full Polish predicates for actions that are not "verb + object" (the object noun would be garbled or missing).
PHRASES = {
    "auth.login": "zalogował się", "analysis.create": "utworzył analizę", "analysis.run": "uruchomił analizę",
    "analysis.features": "zaktualizował cechy analizy", "analysis_item.script_fix": "poprawił znaki w uwadze modelu",
    "document.upload": "wgrał dokument", "document.link": "powiązał dokument z projektem", "monitoring.alert": "zapisał alert monitoringu",
    "demo.cleanup": "usunął artefakty testowe przed pokazem", "seed": "wczytał katalog ryzyk", "derive.quality": "sprawdził jakość danych o zmianach umów",
    "import": "zaimportował dane projektów", "import.upload": "wgrał plik do importu", "import.inspect": "przejrzał plik importu",
    "import.propose_mapping": "zaproponował mapowanie kolumn", "link_national": "powiązał ogłoszenia z projektami w całym kraju",
    "link_pilot": "powiązał projekty pilotażowe", "review.sync": "zsynchronizował kolejkę przeglądu", "test": "dodał wpis testowy", "question.save": "zapisał pytanie do pamięci", "demo.baseline": "zapisał stan wyjściowy dla pokazu",
}
FIELDS = {
    "owner": "właściciel", "tytul": "tytuł",
    "role": "rola", "method": "metoda", "persona": "profil", "read_only": "tylko do odczytu", "n": "liczba uwag", "code": "kod",
    "version": "wersja", "pages": "strony", "chunks": "fragmenty", "filename": "plik", "sensitivity": "poufność", "text_status": "tekst",
    "analysis_code": "analiza", "project_rm_id": "projekt", "rows": "wiersze", "issues": "uwagi", "linked": "powiązano", "mapped": "zmapowano kolumn",
    "questions": "pytania", "calls": "kroki", "files": "pliki", "name": "nazwa", "bytes": "bajty", "changed": "zmieniono", "skipped": "pominięto",
    "created": "utworzono", "alert": "alert", "risk_events": "zdarzenia ryzyka", "link_candidate": "kandydat powiązania",
    "contract_change": "zmiana umowy", "score": "wynik", "features": "cechy", "budzet": "budżet", "sektor": "sektor", "formula": "formuła",
    "podsektor": "podsektor", "dlugosc_km": "długość (km)", "termin_mies": "termin (mies.)", "finansowanie": "finansowanie",
    "rodzaj_robot": "rodzaj robót", "przepompownie": "przepompownie", "amount": "kwota", "currency": "waluta", "deleted": "usunięto",
    "rule": "reguła", "reason": "powód", "why": "uzasadnienie", "text": "treść", "status": "status", "resolution": "decyzja", "option": "opcja",
    "item": "sprawa", "project": "projekt", "contract": "umowa", "contractor": "wykonawca", "marked_duplicate": "oznaczono duplikatów",
    "review_items": "sprawy do przeglądu", "analyses": "analizy", "link": "powiązania", "event": "zdarzenia", "catalogue": "katalog",
    "dismissed": "odrzucone", "cru": "CRU", "kpo": "KPO", "reference": "wzorzec", "candidates": "kandydaci", "resolved_by": "rozstrzygnął",
    "coverage": "pokrycie", "document": "dokument", "job": "zadania", "evidence": "dowody", "risk_event": "zdarzenia ryzyka", "analysis": "analizy",
    "review_item": "sprawy do przeglądu", "title": "tytuł", "ocid": "ocid",
}
VALUES = {"expert": "ekspert", "public": "publiczny", "confidential": "poufny", "ok": "odczytany", "open": "otwarta", "demo": "demo",
          "juror": "juror", "keep_dataset": "zostaw dane ze zbioru", "design_build": "projektuj i buduj", "build": "budowa",
          "exact_id": "zgodny identyfikator", "accept": "przyjęte", "reject": "odrzucone", "review": "do przeglądu"}
# Technical fields that tell a reader nothing (hashes, internal ids, paths); the full record stays in the export.
HIDDEN = {"sha256", "data_version", "redpen_job_id", "source_id", "jobs", "backup", "key", "inserted", "project_id", "contract_id",
          "document_id", "id", "by_decision", "top1_by_decision", "top1_by_contractor", "accepted_by_sector", "with_changes", "buyer_via_nip",
          "buyer_via_regon", "buyer_unresolved", "cru_agreements", "in_top3", "per"}


def _label(k: str) -> str:
    return FIELDS.get(k) or k.replace("_", " ")


def _val(v: Any, depth: int = 0) -> str:
    """One readable value: Polish yes/no, money, short ids, nested objects as 'label: value, label: value'."""
    if isinstance(v, bool):
        return "tak" if v else "nie"
    if v is None:
        return ""
    if isinstance(v, str):
        if len(v) >= 32 and all(c in "0123456789abcdef" for c in v):
            return v[:8] + "…"
        return VALUES.get(v, v)
    if isinstance(v, (int, float)):
        return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)
    if isinstance(v, list):
        items = [_val(x, depth + 1) for x in v[:6]]
        return ", ".join(i for i in items if i) + ("…" if len(v) > 6 else "")
    if isinstance(v, dict):
        if "amount" in v and "currency" in v:
            return f"{v['amount']} {v['currency']}"
        if depth >= 2:
            return f"{len(v)} pól"
        parts = [f"{_label(k)}: {_val(x, depth + 1)}" for k, x in v.items() if k not in HIDDEN and _val(x, depth + 1) != ""]
        return ", ".join(parts[:6])
    return str(v)


def short(v: Any, limit: int = 240) -> str:
    """Before/after text for the Historia: 'Etykieta: wartość; Etykieta: wartość', Polish labels, empty and technical fields dropped."""
    if v is None:
        return ""
    if isinstance(v, dict):
        if "changes" in v and isinstance(v["changes"], list):
            fields: dict[str, Any] = {}
            for c in v["changes"]:
                f = c.get("fields") if isinstance(c, dict) and "fields" in c else c
                if isinstance(f, dict):
                    fields.update(f)
            v = fields
        out = []
        for k, x in v.items():
            if k in HIDDEN:
                continue
            t = _val(x)
            if t != "":
                out.append(f"{_label(k)}: {t}")
        text_ = "; ".join(out)
    elif isinstance(v, list):
        text_ = _val(v)
    else:
        text_ = _val(v)
    return text_ if len(text_) <= limit else text_[: limit - 1].rstrip() + "…"


def action_label(row: dict) -> str:
    if row.get("_label"):
        return row["_label"]
    act = row["action"]
    if act in PHRASES:
        return PHRASES[act]
    verb = VERBS.get(act) or next((v for k, v in VERBS.items() if act.startswith(k)), None)
    if verb is None:
        return "wykonał operację"
    noun = TABLE_NOUN.get(row.get("table_name") or "", "")
    return f"{verb} {noun}".strip()


def restorable(row: dict) -> bool:
    """Expert decisions (review.approve|edit|reject) that changed rows can be restored: restore is a new edit, never a delete."""
    b = row.get("before")
    return (actor_kind(row["actor"]) == "expert" and row["action"] in ("review.approve", "review.edit", "review.reject")
            and isinstance(b, dict) and any(isinstance(c, dict) and c.get("fields") for c in b.get("changes") or []))


async def object_ref(db: AsyncSession, table: str | None, row_id: int | None) -> dict | None:
    if not table:
        return None
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
    return None  # the action phrase already names the object; a bare noun would only repeat it


def entry(row: dict, version: str | None = None, obj: dict | None = None) -> dict:
    return {"id": row["id"], "audit_id": row["id"], "at": row["at"].isoformat(), "derived": row["id"] < 0, "actor_kind": actor_kind(row["actor"]),
            "actor_label": actor_label(row["actor"]), "action": row["action"], "action_label": action_label(row),
            "object": obj, "table": row.get("table_name"), "row_id": row.get("row_id"), "before": short(row.get("before")), "after": short(row.get("after")), "why": row.get("note") or "",
            "note": row.get("note"), "ref": None, "version": version, "can_restore": restorable(row), "restorable": restorable(row)}
