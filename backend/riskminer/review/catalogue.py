"""Versioned catalogue edits (api_contract §3.2).

Rows are immutable per version: an edit inserts a new row (same sector+code, version = max+1, status approved, origin SOURCE,
approved_by = user) and retires the previous approved row. One `catalogue_version` row (pack label v1.3 -> v1.4) per request
records the changes; every edit also writes an audit row. Readers filter status = 'approved'."""
from __future__ import annotations

import copy
import csv
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.auth import ApiError
from riskminer.config import REPO_ROOT
from riskminer.review.common import audit, fetch_row, insert_row, jclean, jdump

SECTOR = "wod-kan"
# short table name -> (db table, key column, patchable columns)
TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "risk": ("catalogue_risk", "code", ("name", "description")),
    "subsector": ("catalogue_subsector", "code", ("name", "description")),
    "doc_type": ("catalogue_doc_type", "code", ("name", "phase")),
    "checklist": ("catalogue_checklist", "code", ("text", "phase")),
    "clause": ("catalogue_clause", "code", ("title", "text", "risk_code")),
    "entry": ("catalogue_entry", "code", ("name",)),
}

WEIGHT_LABELS = {
    "subsector_main": "podsektor", "subsectors_all": "podsektory dodatkowe", "works_type": "rodzaj robót", "formula": "formuła (ZiW)",
    "physical_size": "zakres i ilości", "value": "wartość", "text": "opis (tekst)", "period": "okres", "region": "region",
    "funding": "finansowanie", "tech_tags": "technologia", "beneficiary_type": "typ beneficjenta",
}
WEIGHT_ALIASES = {"design_build": "formula", "scope": "physical_size", "budget": "value"}
MAIN_WEIGHTS = ("subsector_main", "formula", "physical_size", "value", "text")


async def _rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def _scalar(db: AsyncSession, sql: str, **p) -> Any:
    return (await db.execute(text(sql), p)).scalar()


def _next_label(last: str | None) -> str:
    m = re.match(r"^v(\d+)\.(\d+)$", last or "")
    return f"v{m.group(1)}.{int(m.group(2)) + 1}" if m else "v1.1"


async def current_label(db: AsyncSession, sector: str = SECTOR) -> str:
    return await _scalar(db, "SELECT label FROM catalogue_version WHERE sector=:s ORDER BY id DESC LIMIT 1", s=sector) or "v1.1"


class Pack:
    """Collects the changes of one request and writes a single catalogue_version row."""

    def __init__(self, db: AsyncSession, actor: str, request_id: str | None, sector: str = SECTOR):
        self.db, self.actor, self.request_id, self.sector = db, actor, request_id, sector
        self.changes: list[dict] = []
        self.label: str | None = None

    def add(self, table: str, code: str, from_v: int | None, to_v: int, before: Any, after: Any) -> None:
        self.changes.append({"table": table, "code": code, "from_version": from_v, "to_version": to_v,
                             "before": jclean(before), "after": jclean(after)})

    async def finish(self, summary: str) -> str:
        if not self.changes:
            return await current_label(self.db, self.sector)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(hashtext('catalogue_version'))"))
        self.label = _next_label(await current_label(self.db, self.sector))
        await self.db.execute(text("""INSERT INTO catalogue_version (sector, label, summary, changes, actor)
                                      VALUES (:s, :l, :sum, CAST(:c AS jsonb), :a)"""),
                              {"s": self.sector, "l": self.label, "sum": summary, "c": jdump(self.changes), "a": self.actor})
        await audit(self.db, self.actor, "catalogue.version", "catalogue_version", None, None,
                    {"label": self.label, "summary": summary, "changes": len(self.changes)}, self.request_id, summary)
        return self.label


def _split(table: str, code: str) -> tuple[str, str | None, str, tuple[str, ...]]:
    if table not in TABLES:
        raise ApiError(404, "Nieznana tabela katalogu.", "not_found")
    db_table, key, cols = TABLES[table]
    entry_table = None
    if table == "entry":
        if ":" not in code:
            raise ApiError(422, "Dla wpisów podaj kod w formie tabela:kod.", "bad_code")
        entry_table, code = code.split(":", 1)
    return db_table, entry_table, code, cols


async def _current(db: AsyncSession, db_table: str, key: str, code: str, entry_table: str | None, sector: str) -> dict:
    extra = " AND table_name = :et" if entry_table else ""
    rs = await _rows(db, f"SELECT * FROM {db_table} WHERE sector=:s AND {key}=:c{extra} AND status='approved' ORDER BY version DESC LIMIT 1 FOR UPDATE",
                     s=sector, c=code, et=entry_table)
    if not rs:
        raise ApiError(404, "Nie ma takiego zatwierdzonego wpisu w katalogu.", "not_found")
    return rs[0]


async def new_version(db: AsyncSession, row: dict, db_table: str, fields: dict, actor: str, *, key_label: str, pack: Pack) -> dict:
    """Insert the next version of `row` with `fields` overridden; retire the old approved row."""
    maxv = await _scalar(db, f"SELECT max(version) FROM {db_table} WHERE sector=:s AND code = :c"
                         + (" AND table_name = :t" if "table_name" in row else ""), s=row["sector"], c=row.get("code"), t=row.get("table_name")) \
        if "code" in row else row["version"]
    new = {k: v for k, v in row.items() if k not in ("id", "created_at", "updated_at")}
    new.update(fields)
    new.update({"version": (maxv or row["version"]) + 1, "status": "approved", "origin": "SOURCE", "approved_by": actor})
    new_id = await insert_row(db, db_table, new)
    await db.execute(text(f"UPDATE {db_table} SET status='retired', approved_by = coalesce(approved_by, 'pack'), updated_at=now() WHERE id=:i"),
                     {"i": row["id"]})
    before = {k: row.get(k) for k in fields}
    pack.add(db_table, key_label, row["version"], new["version"], before, {k: new.get(k) for k in fields})
    await audit(db, actor, "catalogue.edit", db_table, new_id, before, {k: new.get(k) for k in fields}, pack.request_id,
                f"{key_label}: wersja {new['version']}")
    return {**new, "id": new_id}


def _summary_edit(code: str, fields: dict) -> str:
    return f"{code}: zmieniono " + ", ".join(k for k in fields if k != "data").replace("name", "nazwę") + (" i dane" if "data" in fields else "")


async def edit(db: AsyncSession, table: str, code: str, patch: dict, comment: str | None, actor: str, request_id: str | None,
               sector: str = SECTOR) -> dict:
    """PATCH /catalogue/{table}/{code}: {name?, description?, data?: {...merged shallowly}}."""
    db_table, entry_table, c, cols = _split(table, code)
    bad = [k for k in patch if k not in cols and k != "data"]
    if bad:
        raise ApiError(422, f"Pole {bad[0]} nie podlega edycji.", "bad_field")
    if not patch:
        raise ApiError(422, "Brak zmian do zapisania.", "empty_patch")
    row = await _current(db, db_table, "code", c, entry_table, sector)
    fields = {k: v for k, v in patch.items() if k != "data"}
    if "data" in patch:
        if not isinstance(patch["data"], dict):
            raise ApiError(422, "Pole data musi być obiektem.", "bad_field")
        fields["data"] = {**(row.get("data") or {}), **patch["data"]}
    if all(row.get(k) == v for k, v in fields.items()):
        raise ApiError(409, "Ta zmiana nic nie zmienia.", "no_change")
    pack = Pack(db, actor, request_id, sector)
    new = await new_version(db, row, db_table, fields, actor, key_label=code, pack=pack)
    label = await pack.finish(_summary_edit(code, fields) + (f" ({comment})" if comment else ""))
    return {"code": code, "version": new["version"], "status": "approved", "catalogue_version": label}


# --------------------------------------------------------------------------------------------------------- weights

async def _similarity_row(db: AsyncSession, sector: str) -> dict:
    return await _current(db, "catalogue_entry", "code", "default", "similarity", sector)


def _features(row: dict) -> dict[str, dict]:
    return ((row.get("data") or {}).get("similarity") or {}).get("features") or {}


async def put_weights(db: AsyncSession, weights: dict[str, float], comment: str | None, actor: str, request_id: str | None,
                      sector: str = SECTOR) -> dict:
    """Validate (>= 0, known keys, sum 1 +- 0.001) and store as a new version of catalogue_entry(similarity, default).
    A subset keeps its previous combined share and the other features stay unchanged (so five sliders never zero the rest)."""
    row = await _similarity_row(db, sector)
    feats = copy.deepcopy(_features(row))
    given = {WEIGHT_ALIASES.get(k, k): float(v) for k, v in weights.items()}
    unknown = [k for k in given if k not in feats]
    if unknown:
        raise ApiError(422, f"Nieznana cecha podobieństwa: {unknown[0]}.", "bad_feature")
    if any(v < 0 for v in given.values()):
        raise ApiError(422, "Wagi nie mogą być ujemne.", "bad_weight")
    old = {k: float(f.get("w") or 0) for k, f in feats.items()}
    if set(given) == set(feats):
        new = given
        if abs(sum(new.values()) - 1) > 0.001:
            raise ApiError(422, "Wagi muszą się sumować do 1.", "bad_sum")
    else:
        share = sum(old[k] for k in given)
        tot = sum(given.values())
        if tot <= 0:
            raise ApiError(422, "Suma wybranych wag musi być dodatnia.", "bad_sum")
        new = {**old, **{k: v / tot * share for k, v in given.items()}}
    for k, w in new.items():
        feats[k]["w"] = round(w, 4)
    data = copy.deepcopy(row["data"])
    data["similarity"]["features"] = feats
    data["similarity"]["version"] = int(data["similarity"].get("version") or 1) + 1
    pack = Pack(db, actor, request_id, sector)
    await new_version(db, row, "catalogue_entry", {"data": data}, actor, key_label="similarity:default", pack=pack)
    moved = [f"{WEIGHT_LABELS.get(k, k)} {round(old[k] * 100)} → {round(new[k] * 100)}" for k in new if round(old[k] * 100) != round(new[k] * 100)]
    summary = "wagi: " + (", ".join(moved) or "bez zmian") + (f" ({comment})" if comment else "")
    label = await pack.finish(summary)
    return {"weights": [{"feature": k, "label": WEIGHT_LABELS.get(k, k), "w": new[k]} for k in new], "catalogue_version": label, "summary": summary}


# ------------------------------------------------------------------------------------------------------- proposals

async def approve_proposal(db: AsyncSession, t: dict, actor: str, request_id: str | None) -> list[dict]:
    pack = Pack(db, actor, request_id, t["sector"])
    before = {k: t.get(k) for k in ("status", "origin", "approved_by")}
    after = {"status": "approved", "origin": "SOURCE", "approved_by": actor}
    await db.execute(text("UPDATE catalogue_risk SET status='approved', origin='SOURCE', approved_by=:a, updated_at=now() WHERE id=:i"),
                     {"a": actor, "i": t["id"]})
    pack.add("catalogue_risk", t["code"], None, t["version"], before, after)
    await pack.finish(f"dodano ryzyko {t['code']} {t['name']}")
    return [{"table": "catalogue_risk", "id": t["id"], "before": jclean(before), "after": after}]


async def merge_proposal(db: AsyncSession, t: dict, into: str, actor: str, request_id: str | None) -> list[dict]:
    pack = Pack(db, actor, request_id, t["sector"])
    row = await _current(db, "catalogue_risk", "code", into, None, t["sector"])
    data = dict(row.get("data") or {})
    signals = list(data.get("signals") or [])
    if t["name"] not in signals:
        signals.append(t["name"])
    data["signals"] = signals
    await new_version(db, row, "catalogue_risk", {"data": data}, actor, key_label=into, pack=pack)
    before = {k: t.get(k) for k in ("status", "data")}
    after = {"status": "rejected", "data": {**(t.get("data") or {}), "merged_into": into}}
    await db.execute(text("UPDATE catalogue_risk SET status='rejected', data = data || CAST(:d AS jsonb), updated_at=now() WHERE id=:i"),
                     {"d": jdump({"merged_into": into}), "i": t["id"]})
    pack.add("catalogue_risk", t["code"], None, t["version"], before, after)
    await pack.finish(f"{t['code']} połączone z {into}")
    return [{"table": "catalogue_risk", "id": t["id"], "before": jclean(before), "after": jclean(after)}]


async def reject_proposal(db: AsyncSession, t: dict, reason: str | None, actor: str, request_id: str | None) -> list[dict]:
    pack = Pack(db, actor, request_id, t["sector"])
    before = {k: t.get(k) for k in ("status", "data")}
    after = {"status": "rejected", "data": {**(t.get("data") or {}), "reject_reason": reason}}
    await db.execute(text("UPDATE catalogue_risk SET status='rejected', data = data || CAST(:d AS jsonb), updated_at=now() WHERE id=:i"),
                     {"d": jdump({"reject_reason": reason}), "i": t["id"]})
    pack.add("catalogue_risk", t["code"], None, t["version"], before, after)
    await pack.finish(f"odrzucono propozycję {t['code']} {t['name']}")
    return [{"table": "catalogue_risk", "id": t["id"], "before": jclean(before), "after": jclean(after)}]


# ---------------------------------------------------------------------------------------------------- versions, restore

async def versions(db: AsyncSession, sector: str = SECTOR) -> list[dict]:
    rs = await _rows(db, "SELECT label, summary, actor, created_at AS at FROM catalogue_version WHERE sector=:s ORDER BY id DESC", s=sector)
    return [{"label": r["label"], "summary": r["summary"], "actor": _actor_label(r["actor"]), "at": r["at"].isoformat()} for r in rs]


def _actor_label(a: str) -> str:
    return "ekspert" if a.startswith("user:") else ("system" if a.startswith("system") else a)


async def diff(db: AsyncSession, label: str, against: str | None, sector: str = SECTOR) -> dict:
    rs = await _rows(db, "SELECT id, label, changes FROM catalogue_version WHERE sector=:s ORDER BY id", s=sector)
    ids = {r["label"]: r["id"] for r in rs}
    if label not in ids:
        raise ApiError(404, "Nie ma takiej wersji katalogu.", "not_found")
    lo = ids.get(against, 0) if against else ids[label] - 1
    if against and against not in ids:
        raise ApiError(404, "Nie ma takiej wersji katalogu.", "not_found")
    ch: list[dict] = []
    for r in rs:
        if lo < r["id"] <= ids[label]:
            ch.extend(r["changes"] or [])
    return {"label": label, "against": against, "changes": ch}


async def restore(db: AsyncSession, label: str, reason: str | None, actor: str, request_id: str | None, sector: str = SECTOR) -> dict:
    """Re-apply the pre-change values of every change after `label` as new versions (never rewinds ids)."""
    rs = await _rows(db, "SELECT id, label, changes FROM catalogue_version WHERE sector=:s ORDER BY id DESC", s=sector)
    ids = {r["label"]: r["id"] for r in rs}
    if label not in ids:
        raise ApiError(404, "Nie ma takiej wersji katalogu.", "not_found")
    if rs[0]["label"] == label:
        raise ApiError(409, "To jest bieżąca wersja katalogu.", "no_change")
    pack = Pack(db, actor, request_id, sector)
    seen: set[tuple[str, str]] = set()
    for r in rs:
        if r["id"] <= ids[label]:
            break
        for ch in reversed(r["changes"] or []):
            if not ch.get("before") or ch["table"] not in {v[0] for v in TABLES.values()} or ch.get("from_version") is None:
                continue
            key = (ch["table"], ch["code"])
            if key in seen:  # an older change of the same row overrides: apply it after, keep walking
                pass
            seen.add(key)
            code = ch["code"]
            entry_table = None
            if ch["table"] == "catalogue_entry" and ":" in code:
                entry_table, code = code.split(":", 1)
            row = await _current(db, ch["table"], "code", code, entry_table, sector)
            await new_version(db, row, ch["table"], ch["before"], actor, key_label=ch["code"], pack=pack)
    new_label = await pack.finish(f"przywrócono wersję {label}" + (f" ({reason})" if reason else ""))
    return {"catalogue_version": new_label, "restored_from": label}


# ------------------------------------------------------------------------------------------------------------- view

def _keyword_quality() -> dict[str, dict]:
    p = REPO_ROOT / "research/bzp_corpus/out/keyword_vs_gold.csv"
    out: dict[str, dict] = {}
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8")):
            out[r["category"]] = r
    return out


def _num(value: float | None, unit: str, n: int, method: str, refs: list[dict]) -> dict:
    ok = value is not None and n >= 10
    return {"value": value if ok else None, "display": f"{value:.2f}".replace(".", ",") if ok else "za mało danych", "unit": unit,
            "prov": {"role": "calc", "review_status": "auto", "n": n, "method": method, "refs": refs, **({} if ok else {"insufficient": True})}}


async def view(db: AsyncSession, sector: str = SECTOR) -> dict:
    risks = await _rows(db, "SELECT * FROM catalogue_risk WHERE sector=:s AND status='approved' AND level = 1 ORDER BY code", s=sector)
    ccount = {r["catalogue_code"]: r["n"] for r in await _rows(db, """
        SELECT split_part(catalogue_code, '.', 1) AS catalogue_code, count(*) AS n FROM risk_event
        WHERE catalogue_code IS NOT NULL AND review_status IN ('approved','edited') GROUP BY 1""")}
    pcount = {r["catalogue_code"]: r["n"] for r in await _rows(db, """
        SELECT split_part(catalogue_code, '.', 1) AS catalogue_code, count(*) AS n FROM risk_event
        WHERE catalogue_code IS NOT NULL AND review_status = 'proposed' AND origin='AI' GROUP BY 1""")}
    subs = await _rows(db, "SELECT code, name, data FROM catalogue_risk WHERE sector=:s AND status IN ('approved','proposed') AND level > 1 ORDER BY code", s=sector)
    sub_by_parent: dict[str, list[str]] = {}
    for s in subs:
        sub_by_parent.setdefault(s["code"].split(".")[0], []).append(f"{s['code']} {s['name']}")
    kq = _keyword_quality()
    out_risks = []
    for r in risks:
        d = r.get("data") or {}
        parts = []
        if d.get("signals"):
            parts.append({"k": "sygnał w dokumentach", "v": "; ".join(d["signals"])})
        if sub_by_parent.get(r["code"]):
            parts.append({"k": "podrodzaje", "v": "; ".join(sub_by_parent[r["code"]][:6])})
        if d.get("mitigation"):
            parts.append({"k": "środki zaradcze", "v": d["mitigation"] if isinstance(d["mitigation"], str) else "; ".join(d["mitigation"])})
        q = kq.get(r["code"])
        quality = None
        if q and q.get("precision") not in (None, "") and q.get("recall") not in (None, ""):
            n = int(float(q.get("gold_any") or 0))
            quality = {"note": f"reguły wyłapują {q.get('tp')} z {n}",
                       "precision": _num(float(q["precision"]), "share", n, "keyword_vs_gold", [{"kind": "file", "id": "research/bzp_corpus/out/keyword_vs_gold.csv", "label": "zbiór wzorcowy"}]),
                       "recall": _num(float(q["recall"]), "share", n, "keyword_vs_gold", [{"kind": "file", "id": "research/bzp_corpus/out/keyword_vs_gold.csv", "label": "zbiór wzorcowy"}]),
                       "review_href": f"/przeglad?kind=event&code={r['code']}"}
        out_risks.append({"code": r["code"], "name": r["name"], "effects": d.get("effects_text"), "description": r.get("description"),
                          "version": r["version"], "parts": parts, "counts": {"approved": ccount.get(r["code"], 0), "proposed": pcount.get(r["code"], 0)},
                          "quality": quality})
    props = await _rows(db, """SELECT c.id, c.code, c.name, c.description, c.data, c.status, c.origin, c.proposed_by,
                               (SELECT id FROM review_item ri WHERE ri.target_table='catalogue_risk' AND ri.target_id=c.id AND ri.status='open' LIMIT 1) AS review_item_id
                               FROM catalogue_risk c WHERE c.sector=:s AND c.status='proposed' AND c.origin='AI' ORDER BY c.id""", s=sector)
    sim = await _similarity_row(db, sector)
    feats = _features(sim)
    weights = [{"feature": k, "label": WEIGHT_LABELS.get(k, k), "w": f.get("w"), "main": k in MAIN_WEIGHTS} for k, f in feats.items()]
    simple = lambda t, cols: _rows(db, f"SELECT {cols} FROM {t} WHERE sector=:s AND status='approved' ORDER BY 1", s=sector)  # noqa: E731
    return {"version": await current_label(db, sector), "risks": out_risks,
            "proposals": [{"id": p["id"], "review_item_id": p["review_item_id"], "title": p["name"], "description": p.get("description"),
                           "evidence_text": (p.get("data") or {}).get("evidence_text"), "merge_suggestion": (p.get("data") or {}).get("merge_suggestion"),
                           "origin": p["origin"], "status": p["status"]} for p in props],
            "weights": weights, "subsectors": await simple("catalogue_subsector", "code, name"),
            "doc_types": await simple("catalogue_doc_type", "code, name, phase"),
            "checklists": await simple("catalogue_checklist", "code, phase, text"),
            "clauses": await simple("catalogue_clause", "code, risk_code, title, text"),
            "versions": await versions(db, sector)}
