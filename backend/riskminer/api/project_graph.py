"""Project evidence graph (J8): sources -> fact groups -> conclusions, with fact ids for tracing. Reads only (session B).
Fact grouping is a fixed table: project/organization/links -> Identyfikacja; contract + procedure -> Umowa; change notices -> Zmiany;
performance notices -> Wykonanie; risk events -> Przyczyny; derived numbers -> Wyniki. Source column from the fact's origin:
XLSX organiser row, BZP notices, model reading (origin AI), calculations (origin CALC)."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api.project_views import load_chain, notice_ref, rows, role, zl
from riskminer.api.prov import fmt_num

GROUPS = {"ident": "Identyfikacja", "contract": "Umowa", "changes": "Zmiany", "perf": "Wykonanie", "reasons": "Przyczyny", "results": "Wyniki"}
SRC = {"xlsx": ("Zestaw organizatora", "source"), "bzp": ("Ogłoszenia BZP", "source"), "ai": ("Odczyt modelu", "ai"), "calc": ("Obliczenia", "calc")}
STATUS_LABEL = {"approved": "zatwierdzone", "edited": "poprawione przez eksperta", "proposed": "wniosek AI, do przeglądu", "auto": "obliczenie", "rejected": "odrzucone"}


def _src_of_origin(origin: str) -> str:
    return {"AI": "ai", "CALC": "calc"}.get(origin, "bzp")


async def graph(db: AsyncSession, rm_id: str, user: A.User | None, include_proposed: bool = True) -> dict | None:
    ch = await load_chain(db, rm_id, user)
    if ch is None:
        return None
    p, m = ch["project"], ch["metric"]
    events = [e for e in ch["events"] if include_proposed or user is None or e["origin"] != "AI" or e["review_status"] in ("approved", "edited")]
    facts: list[dict] = []   # {id, group, src}

    def add(fid: str, group: str, src: str) -> None:
        facts.append({"id": fid, "group": group, "src": src})

    pilot = p["id"] is not None
    if pilot:  # organiser dataset row and linking exist only for the 22 pilot projects
        add(f"project:{p['id']}", "ident", "xlsx")
        if ch["org"]:
            add(f"organization:{p.get('beneficiary_org_id')}", "ident", "xlsx")
    for pr in ch["procs"]:
        if pilot:
            add(f"project_procedure:{pr['id']}", "ident", "calc")
        add(f"procedure:{pr['id']}", "contract", "bzp")
    for c in ch["contracts"]:
        add(f"contract:{c['id']}", "contract", _src_of_origin(c["origin"]))
    for c in ch["changes"]:
        add(f"contract_change:{c['id']}", "changes", _src_of_origin(c["origin"]))
    for pf in ch["perf"]:
        add(f"contract_performance:{pf['id']}", "perf", _src_of_origin(pf["origin"]))
    for e in events:
        add(f"risk_event:{e['id']}", "reasons", _src_of_origin(e["origin"]))
    if ch["perf"]:
        add("calc:delay", "results", "calc")
        add("calc:cost", "results", "calc")

    by_group: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        by_group[f["group"]].append(f)

    nodes: list[dict] = []
    links: list[dict] = []
    # --- sources -> groups
    src_counts: dict[str, int] = defaultdict(int)
    for f in facts:
        src_counts[f["src"]] += 1
    n_notices = len(ch["notices"])
    subs = {"xlsx": "XLSX, 1 wiersz", "bzp": f"{n_notices} ogłoszeń", "ai": "tekst ogłoszeń", "calc": "z faktów obok"}
    for key, cnt in src_counts.items():
        nodes.append({"id": f"src:{key}", "column": 0, "label": SRC[key][0], "sub": subs[key], "role": SRC[key][1], "value": cnt})
    pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in facts:
        pair[(f["src"], f["group"])].append(f["id"])
    for (src, g), ids in pair.items():
        links.append({"source": f"src:{src}", "target": f"fact:{g}", "value": len(ids), "fact_ids": ids})
    for g, fs in by_group.items():
        nodes.append({"id": f"fact:{g}", "column": 1, "label": GROUPS[g], "sub": f"{len(fs)} " + ("fakt" if len(fs) == 1 else "fakty" if 2 <= len(fs) % 10 <= 4 and not 12 <= len(fs) % 100 <= 14 else "faktów"),
                      "value": len(fs)})

    # --- conclusions
    concl: list[dict] = []
    details: dict[str, dict] = {}
    open_items = {r["target_id"]: r["id"] for r in await rows(
        db, "SELECT id, target_id FROM review_item WHERE status='open' AND target_table='risk_event' AND target_id = ANY(:ids)",
        ids=[e["id"] for e in events] or [0])} if user else {}

    def feed(cid: str, parts: list[tuple[str, list[str]]]) -> None:
        for g, ids in parts:
            if ids:
                links.append({"source": f"fact:{g}", "target": cid, "value": len(ids), "fact_ids": ids})

    ids = lambda g, pref=None: [f["id"] for f in by_group.get(g, []) if pref is None or f["id"].startswith(pref)]  # noqa: E731
    # link (pilot projects only: national procedures are not linked to anything)
    if pilot:
        link_status = "approved" if all(x["link_status"] in ("approved", "edited") for x in ch["procs"]) and ch["procs"] else "auto"
        concl.append({"id": "concl:link", "label": "Powiązanie z postępowaniem BZP", "sub": "obliczenie" if link_status == "auto" else "zatwierdzone",
                      "role": "calc", "review_status": link_status})
        feed("concl:link", [("ident", ids("ident", "project_procedure")), ("contract", ids("contract", "procedure"))])
        details["concl:link"] = {"kind": "wniosek, obliczenie", "title": "Projekt jest powiązany z postępowaniem BZP",
                                 "rows": [{"k": "metoda", "v": ", ".join(sorted({x["method"] for x in ch["procs"]})) or "brak"},
                                          {"k": "postępowania", "v": ", ".join(x["ocid"] for x in ch["procs"]) or "brak"}],
                                 "evidence": [], "cta": None}
    if ch["perf"]:
        d, c = m.get("delay_days"), m.get("cost_dev_pct")
        concl.append({"id": "concl:delay", "label": "Termin", "sub": f"{'+' if d and d > 0 else ''}{fmt_num(d)} dni", "role": "calc", "review_status": "auto"})
        feed("concl:delay", [("contract", ids("contract", "contract")), ("perf", ids("perf")), ("results", ["calc:delay"])])
        details["concl:delay"] = {"kind": "wniosek, obliczenie", "title": "Opóźnienie względem terminu z umowy",
                                  "rows": [{"k": "wynik", "v": f"{'+' if d and d > 0 else ''}{fmt_num(d)} dni"}, {"k": "metoda", "v": "faktyczny koniec minus planowany koniec"}],
                                  "evidence": [r.model_dump(mode="json", exclude_none=True) for r in (notice_ref(x.get("notice_number"), x.get("notice_url"), "ogł. o wykonaniu", "5.2") for x in ch["perf"]) if r],
                                  "cta": None}
        concl.append({"id": "concl:cost", "label": "Koszt", "sub": f"{'+' if c and c > 0 else ''}{fmt_num(c, 1)}%", "role": "calc", "review_status": "auto"})
        feed("concl:cost", [("contract", ids("contract", "contract")), ("perf", ids("perf")), ("changes", ids("changes")), ("results", ["calc:cost"])])
        details["concl:cost"] = {"kind": "wniosek, obliczenie", "title": "Zapłacono względem wartości umowy",
                                 "rows": [{"k": "wynik", "v": f"{'+' if c and c > 0 else ''}{fmt_num(c, 1)}%"}, {"k": "umowa", "v": zl(m.get("value"))}, {"k": "zapłacono", "v": zl(m.get("paid"))}],
                                 "evidence": details["concl:delay"]["evidence"], "cta": None}
    # risk codes
    names = {r["code"]: r["name"] for r in await rows(db, "SELECT code, name FROM catalogue_risk WHERE sector='wod-kan' AND status='approved'")}
    by_code: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_code[(e.get("catalogue_code") or "?").split(".")[0]].append(e)
    for code, evs in sorted(by_code.items()):
        cid = f"concl:{code}" if code != "?" else "concl:none"
        origins = {e["origin"] for e in evs}
        statuses = {e["review_status"] for e in evs}
        rstat = "proposed" if "proposed" in statuses else ("approved" if statuses <= {"approved", "edited"} else "auto")
        r_ = "ai" if origins == {"AI"} else ("calc" if origins <= {"CALC"} else "source")
        review_item = next((open_items[e["id"]] for e in evs if e["id"] in open_items), None)
        label = f"{code} {names.get(code, 'ryzyko')}" if code != "?" else "Zdarzenia bez kodu ryzyka"
        concl.append({"id": cid, "label": label, "sub": STATUS_LABEL.get(rstat, rstat) if r_ != "ai" or rstat != "proposed" else "wniosek AI", "role": r_,
                      "review_status": rstat, "review_item_id": review_item})
        eids = [f"risk_event:{e['id']}" for e in evs]
        feed(cid, [("reasons", eids), ("changes", [f"contract_change:{e['change_id']}" for e in evs if e.get("change_id")])])
        n_ai = sum(1 for e in evs if e["origin"] == "AI")
        details[cid] = {"kind": "wniosek" + (", odczyt modelu" if n_ai else ", obliczenie"), "title": f"{label}: {evs[0]['summary']}",
                        "rows": [{"k": "skąd", "v": f"{n_ai} z {len(evs)} faktów pochodzi z odczytu modelu" if n_ai else f"{len(evs)} faktów obliczonych z pól ogłoszeń BZP"},
                                 {"k": "status", "v": STATUS_LABEL.get(rstat, rstat)}],
                        "evidence": [{"kind": "notice", "id": e["change_notice"], "label": "pole 5.3", "url": e.get("change_url"), "field_code": "5.3"} for e in evs if e.get("change_notice")],
                        "cta": {"label": "Sprawdź w Przeglądzie", "href": f"/przeglad?item={review_item}"} if (review_item and user) else None}
    for c in concl:
        nodes.append({**c, "column": 2, "value": sum(l["value"] for l in links if l["target"] == c["id"])})
    nodes = [n for n in nodes if n["value"] > 0]
    live = {n["id"] for n in nodes}
    links = [l for l in links if l["source"] in live and l["target"] in live and l["value"] > 0]
    by_role: dict[str, int] = defaultdict(int)
    for f in facts:
        by_role[SRC[f["src"]][1]] += 1
    return {"columns": [{"key": "sources", "label": "Źródła"}, {"key": "facts", "label": "Fakty"}, {"key": "conclusions", "label": "Wnioski"}],
            "nodes": nodes, "links": links, "details": {k: v for k, v in details.items() if k in live},
            "kind": p["kind"], "summary": {"facts": len(facts), "conclusions": len(concl), "by_role": dict(by_role)}, "unverified_hidden": ch["hidden"]}
