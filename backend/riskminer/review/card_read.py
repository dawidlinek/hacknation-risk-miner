"""Read-only context for a review card (GET /api/review-items/{id} only, never the decision path): what the item is about
(subject facts with links), a readable source reference, the proposed risk for catalogue proposals, a strength label and
the gold-example hint for every kind. Polish copy; values come from the database, nothing is invented here."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.review.common import jclean, pl_money

log = logging.getLogger(__name__)

# "type" facet of the queue: event_type for events, review_item.code for the other kinds
TYPE_LABEL = {
    "EV_DOC_SIGNAL": "Sygnał z dokumentu przetargowego",
    "EV_CHANGE_CAUSE_AI": "Przyczyna zmiany umowy (BZP)",
    "EV_DOC_CAUSE": "Przyczyna z dokumentu",
    "EV_LINKED_INVESTMENT_DELAY": "Opóźnienie inwestycji powiązanej",
    "ai_event": "Zdarzenie wskazane przez model",
    "document_cause": "Przyczyna z dokumentu",
    "document_effect": "Skutek z dokumentu",
    "document_change": "Zmiana umowy z dokumentu",
    "document_contract": "Dokument a umowa",
    "link_candidate": "Projekt a postępowanie w BZP",
    "catalogue_proposal": "Nowe ryzyko",
    "value_deviation": "Różnica wartości",
    "part_mismatch": "Niezgodna część zamówienia",
    "part_scope_wider": "Szerszy zakres niż część",
    "contract_notice_missing": "Brak ogłoszenia w BZP",
    "change_count_mismatch": "Niezgodna liczba zmian umowy",
    "dates_inconsistent": "Niespójne daty umów",
    "future_date": "Daty z przyszłości",
}
METHOD_LABEL = {"fuzzy": "przybliżone (NIP, słowa tytułu, CPV, daty)", "exact": "dokładne", "bzp_number": "po numerze ogłoszenia"}
SECTOR_LABEL = {"wod-kan": "wodociągi i kanalizacja", "drogi": "drogi", "budynki": "budynki", "cieplo": "ciepłownictwo"}
EVIDENCE_TITLE = {"notice": "Ogłoszenie BZP", "document": "Dokument"}
# accept-ready: the quote is found verbatim in the source and the model is confident
READY_CONF = 0.6


def _waiting(n: int) -> str:
    m10, m100 = n % 10, n % 100
    if n == 1:
        return "1 podobna sprawa czeka na przegląd"
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return f"{n} podobne sprawy czekają na przegląd"
    return f"{n} podobnych spraw czeka na przegląd"


def type_label(key: str | None) -> str:
    return TYPE_LABEL.get(key or "", "Inne")


def strength(verification: str | None, confidence: float | None) -> dict:
    exact = verification in ("exact", "structured_field")
    conf = float(confidence) if confidence is not None else None
    if exact and (conf is None or conf >= READY_CONF):
        return {"level": "ready", "label": "cytat potwierdzony w źródle"}
    if exact:
        return {"level": "check", "label": "cytat potwierdzony, niska pewność modelu"}
    if verification == "fuzzy":
        return {"level": "check", "label": "cytat zbliżony do źródła, sprawdź"}
    return {"level": "weak", "label": "bez cytatu ze źródła"}


async def _rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def _one(db: AsyncSession, sql: str, **p) -> dict | None:
    rs = await _rows(db, sql, **p)
    return rs[0] if rs else None


def _fact(label: str, value: Any, href: str | None = None) -> dict | None:
    if value is None or value == "":
        return None
    return {"label": label, "value": str(value), "href": href}


def _date(d: Any) -> str | None:
    return d.strftime("%d.%m.%Y") if d is not None and hasattr(d, "strftime") else (str(d) if d else None)


def _doc_href(doc_id: Any, page: Any = None) -> str | None:
    if not doc_id:
        return None
    return f"/api/documents/{doc_id}/file" + (f"#page={page}" if page else "")


async def _project_fact(db, item) -> list[dict | None]:
    if not item.get("rm_id"):
        return []
    return [_fact("Projekt", f"{item['rm_id']}, {item.get('project_title') or ''}".strip(", "), f"/projekty/{item['rm_id']}")]


async def _contract_facts(db, contract_id) -> list[dict | None]:
    if not contract_id:
        return []
    c = await _one(db, """SELECT c.contractor_name, c.signed_on, c.value_amount, c.value_currency, c.value_vat, p.title AS proc_title,
                                 p.buyer_name FROM contract c JOIN procedure p ON p.id = c.procedure_id WHERE c.id = :i""", i=contract_id)
    if not c:
        return []
    val = pl_money(c["value_amount"]) if c.get("value_amount") is not None else None
    return [
        _fact("Zamówienie", c.get("proc_title")),
        _fact("Zamawiający", c.get("buyer_name")),
        _fact("Wykonawca", c.get("contractor_name")),
        _fact("Umowa", ", ".join(x for x in (f"podpisana {_date(c['signed_on'])}" if c.get("signed_on") else None,
                                              f"{val} brutto" if val else None) if x) or None),
    ]


async def _evidence_source(db, item, card) -> dict | None:
    """Readable source of the card's quote: document title and page, or the BZP notice number, with links."""
    ev = card.get("evidence") or {}
    ref = ev.get("ref") or {}
    if not ref:
        det = item.get("detail") or {}
        if det.get("document_id"):
            ref = {"kind": "document", "id": str(det["document_id"])}
        else:
            return None
    if ref.get("kind") == "document" and str(ref.get("id") or "").isdigit():
        d = await _one(db, """SELECT d.id, d.title, d.filename, d.url, d.doc_type, d.pages, t.name AS type_name FROM document d
                              LEFT JOIN catalogue_doc_type t ON t.code = d.doc_type WHERE d.id = :i""", i=int(ref["id"]))
        if not d:
            return None
        page = ref.get("page_no")
        name = d.get("title") or d.get("filename") or "dokument"
        return {"kind": "document", "title": d.get("type_name") or "Dokument", "name": name,
                "label": f"{name}{f', s. {page}' if page else ''}", "page": page,
                "href": _doc_href(d["id"], page), "original_url": d.get("url")}
    if ref.get("kind") == "notice":
        n = await _one(db, "SELECT notice_number, notice_type, published_at, url FROM notice WHERE notice_number = :n LIMIT 1", n=ref.get("id"))
        kind = {"ContractNotice": "Ogłoszenie o zamówieniu", "TenderResultNotice": "Ogłoszenie o wyniku",
                "AgreementUpdateNotice": "Ogłoszenie o zmianie umowy", "ContractPerformingNotice": "Ogłoszenie o wykonaniu umowy",
                "NoticeUpdateNotice": "Ogłoszenie o zmianie ogłoszenia"}.get((n or {}).get("notice_type"), "Ogłoszenie BZP")
        field = f", pole {ref['field_code']}" if ref.get("field_code") else ""
        return {"kind": "notice", "title": kind, "name": ref.get("id"), "label": f"{ref.get('id')}{field}",
                "page": None, "href": (n or {}).get("url") or ref.get("url"), "original_url": (n or {}).get("url") or ref.get("url")}
    return None


# --------------------------------------------------------------------------------------------------------- per kind

async def _about_event(db, item, card, target) -> dict:
    t = target or {}
    facts = await _project_fact(db, item)
    etype = t.get("event_type")
    facts.append(_fact("Rodzaj", type_label(etype) if etype else None))
    if t.get("change_id"):
        ch = await _one(db, """SELECT cc.change_no, cc.changed_on, cc.delta_days, cc.delta_value_amount, n.notice_number, n.url
                               FROM contract_change cc LEFT JOIN notice n ON n.id = cc.notice_id WHERE cc.id = :i""", i=t["change_id"])
        if ch:
            bits = [f"z {_date(ch['changed_on'])}" if ch.get("changed_on") else None,
                    f"termin {ch['delta_days']:+.0f} dni" if ch.get("delta_days") else None,
                    f"kwota {pl_money(ch['delta_value_amount'])}" if ch.get("delta_value_amount") else None]
            facts.append(_fact("Zmiana umowy", ", ".join(b for b in bits if b) or ch.get("notice_number"), ch.get("url")))
    facts += await _contract_facts(db, t.get("contract_id"))
    pick = item.get("model_pick")
    risk = None
    if pick:
        risk = await _one(db, """SELECT code, name, description FROM catalogue_risk WHERE sector='wod-kan' AND code = :c
                                 AND status IN ('approved','proposed') ORDER BY (status='approved') DESC, version DESC LIMIT 1""", c=pick)
    if risk:
        facts.append(_fact("Ryzyko według modelu", f"{risk['code']} {risk['name']}", "/katalog"))
        # display only: a sub-risk (R12.1) is still a proposal, so the built option carries the bare code; name it
        for o in card.get("options") or []:
            if o.get("key") == risk["code"] and str(o.get("label") or "").strip() == risk["code"]:
                o["label"] = f"{risk['code']} {risk['name']}"
    return {"title": t.get("summary") or item.get("title"), "lead": t.get("cause") if t.get("cause") != t.get("summary") else None,
            "facts": facts, "risk": risk}


async def _about_link(db, item, card, target) -> dict:
    t = target or {}
    facts = await _project_fact(db, item)
    title = item.get("title")
    p_title = None
    if t.get("right_table") == "procedure" and t.get("right_id"):
        p = await _one(db, """SELECT p.title, p.buyer_name, p.ocid, (SELECT n.url FROM notice n WHERE n.procedure_id = p.id
                              ORDER BY n.published_at NULLS LAST LIMIT 1) AS url,
                              (SELECT n.notice_number FROM notice n WHERE n.procedure_id = p.id ORDER BY n.published_at NULLS LAST LIMIT 1) AS nn
                              FROM procedure p WHERE p.id = :i""", i=t["right_id"])
        if p:
            p_title = p.get("title")
            facts += [_fact("Postępowanie w BZP", p.get("title"), p.get("url")), _fact("Zamawiający", p.get("buyer_name")),
                      _fact("Pierwsze ogłoszenie", p.get("nn"), p.get("url"))]
            title = f"Projekt {item.get('rm_id') or ''} a postępowanie „{(p.get('title') or '')[:140]}”".replace("  ", " ")
    elif t.get("left_table") == "document":
        facts += await _contract_facts(db, (item.get("detail") or {}).get("contract_id"))
    if t.get("explanation") and t["explanation"] != card.get("sub"):
        facts.append(_fact("Dlaczego model tak sądzi", t["explanation"]))
    if t.get("right_table") == "procedure" and p_title:
        # display only (the decision keys and actions stay as built): name the procedure instead of its OCID
        for o in card.get("options") or []:
            if o.get("key") == "accept" and str(o.get("label") or "").startswith("Postępowanie ocds-"):
                o["label"] = f"Tak, to postępowanie „{p_title[:120]}”"
            if o.get("sub"):
                o["sub"] = str(o["sub"]).replace(f"dopasowanie {t.get('method')}", f"dopasowanie {METHOD_LABEL.get(t.get('method'), t.get('method'))}")
    card["chips"] = [{**c, "text": f"dopasowanie {METHOD_LABEL.get(t.get('method'), t.get('method'))}"} if str(c.get("text", "")).startswith("metoda: ")
                     else c for c in card.get("chips") or []]
    return {"title": title, "lead": None, "facts": facts}


async def _about_discrepancy(db, item, card, target) -> dict:
    facts = await _project_fact(db, item)
    det = item.get("detail") or {}
    facts.append(_fact("Rodzaj", type_label(item.get("code"))))
    if det.get("n") is not None:
        facts.append(_fact("Liczba rekordów", det["n"]))
    if item.get("target_table") == "contract" and item.get("target_id"):
        facts += await _contract_facts(db, item["target_id"])
    if det.get("rule"):
        facts.append(_fact("Co robimy z tymi danymi", "wyłączone ze statystyk klasy referencyjnej i z sygnałów monitoringu"
                           if "excluded" in str(det["rule"]) else det["rule"]))
    return {"title": item.get("title"), "lead": None, "facts": facts}


async def _about_fact(db, item, card, target) -> dict:
    facts = await _project_fact(db, item)
    t = target or {}
    facts += await _contract_facts(db, t.get("contract_id"))
    det = item.get("detail") or {}
    if det.get("old_end") or det.get("new_end"):
        facts.append(_fact("Termin", f"{det.get('old_end') or '?'} → {det.get('new_end') or '?'}"))
    return {"title": item.get("title"), "lead": None, "facts": facts}


async def _proposal(db, item, target) -> dict | None:
    t = target or {}
    if not t.get("code"):
        return None
    data = t.get("data") or {}
    sector = t.get("sector") or "wod-kan"
    code = t["code"]
    # sector copies carry no data of their own: the analysis was done on the wod-kan corpus, say so instead of copying silently
    base = t
    if not data and sector != "wod-kan":
        b = await _one(db, """SELECT * FROM catalogue_risk WHERE sector='wod-kan' AND code = :c ORDER BY version DESC LIMIT 1""", c=code)
        if b:
            base, data = b, b.get("data") or {}
    emp = ((data.get("effects") or {}).get("empirical") or {})
    # how many classified change causes carry this code (or the codes of its examples)
    codes = [code]
    if data.get("example_ids"):
        rs = await _rows(db, "SELECT DISTINCT primary_code FROM change_cause_ai WHERE norm_md5 = ANY(:ids)", ids=list(data["example_ids"]))
        codes = [r["primary_code"] for r in rs] or codes
    cnt = await _one(db, """SELECT count(*) AS texts, coalesce(sum(n_changes), 0) AS changes FROM change_cause_ai
                            WHERE primary_code = ANY(:c) AND review_status <> 'rejected'""", c=codes) or {}
    # example quotes with the BZP notice they come from
    ex_sql = """SELECT a.quote, a.verification, coalesce(cc.cause_text, cc.description_text) AS cause, n.notice_number, n.url,
                       cc.changed_on, p.title AS proc_title
                FROM change_cause_ai a JOIN contract_change cc ON cc.id = a.sample_change_id
                LEFT JOIN notice n ON n.id = cc.notice_id LEFT JOIN procedure p ON p.id = cc.procedure_id
                WHERE {w} AND a.review_status <> 'rejected'
                ORDER BY (a.verification = 'exact') DESC, a.confidence DESC NULLS LAST, a.n_changes DESC NULLS LAST, a.id LIMIT 3"""
    if data.get("example_ids"):
        exs = await _rows(db, ex_sql.format(w="a.norm_md5 = ANY(:ids)"), ids=list(data["example_ids"]))
    else:
        exs = await _rows(db, ex_sql.format(w="a.primary_code = :c AND a.quote IS NOT NULL"), c=code)
    examples = [{"quote": (e.get("quote") or e.get("cause") or "")[:400], "verified": e.get("verification") == "exact",
                 "label": ", ".join(x for x in (e.get("notice_number"), _date(e.get("changed_on"))) if x) or "ogłoszenie BZP",
                 "context": e.get("proc_title"), "href": e.get("url")} for e in exs if e.get("quote") or e.get("cause")]
    if not examples:
        examples = [{"quote": q, "verified": False, "label": "przykład z próbki modelu", "context": None, "href": None}
                    for q in (data.get("examples") or [])[:3]]
    # closest existing risks: the parent, the merge suggestion, and approved risks that share event types
    closest: list[dict] = []
    seen: set[str] = set()

    async def add(c: str | None, why: str):
        if not c or c in seen or c == code:
            return
        r = await _one(db, """SELECT code, name, description FROM catalogue_risk WHERE sector = :s AND code = :c AND status = 'approved'
                              ORDER BY version DESC LIMIT 1""", s=sector, c=c)
        if r:
            seen.add(c)
            closest.append({**r, "why": why})

    await add(t.get("parent_code"), "ryzyko nadrzędne")
    await add((item.get("detail") or {}).get("merge_suggestion") or data.get("merge_suggestion"), "model proponuje połączenie")
    # the existing risks the classifier weighed as second choice for the same change causes
    second = await _rows(db, """SELECT secondary_code AS code, count(*) AS n FROM change_cause_ai WHERE primary_code = ANY(:c)
                                AND secondary_code ~ '^R[0-9]{2}$' AND review_status <> 'rejected' GROUP BY 1 ORDER BY 2 DESC LIMIT 2""", c=codes)
    for r in second:
        await add(r["code"], f"model rozważał je jako drugą możliwość w {r['n']} przyczynach")
    evs = list(data.get("events") or [])
    if evs:
        rs = await _rows(db, """SELECT code FROM catalogue_risk WHERE sector = :s AND status='approved' AND level = 1
                                AND (data->'events') ?| CAST(:e AS text[]) ORDER BY code LIMIT 3""", s=sector, e=evs)
        for r in rs:
            await add(r["code"], "te same rodzaje zdarzeń")
    ev_names = {r["code"]: r["name"] for r in await _rows(db, "SELECT DISTINCT ON (code) code, name FROM catalogue_entry WHERE table_name='event_type' AND code = ANY(:e) ORDER BY code, version DESC", e=evs)} \
        if evs else {}
    signals = []
    for s in data.get("signals") or []:
        txt = s.get("rule") or ", ".join(str(p) for p in (s.get("patterns") or [])[:4])
        if txt:
            signals.append({"text": txt, "strength": s.get("strength"), "doc_types": s.get("doc_types") or []})
    llm = data.get("llm") or {}
    return jclean({
        "code": code, "name": t.get("name"), "description": t.get("description") or base.get("description"),
        "sector": sector, "sector_label": SECTOR_LABEL.get(sector, sector),
        "copied_from_wodkan": base is not t,
        "parent_code": t.get("parent_code"), "level": t.get("level"),
        "rationale": data.get("rationale"),
        "proposed_by": (f"model {llm.get('model')}" if llm.get("model") else None) or t.get("proposed_by") or data.get("proposed_by"),
        "events": [{"code": e, "name": ev_names.get(e, e)} for e in evs],
        "cases": {"texts": int(cnt.get("texts") or 0), "changes": int(cnt.get("changes") or 0), "codes": codes},
        "empirical": {"n": emp.get("n"), "source": emp.get("source"), "category": emp.get("category"), "p_late": emp.get("p_late"),
                      "delay_p50": (emp.get("delay_days") or {}).get("p50"), "delay_p75": (emp.get("delay_days") or {}).get("p75"),
                      "cost_p75": (emp.get("cost_pct") or {}).get("p75"), "cost_p90": (emp.get("cost_pct") or {}).get("p90")} if emp else None,
        "signals": signals, "clauses": list(data.get("clauses") or [])[:2], "mitigations": list(data.get("mitigations") or [])[:4],
        "examples": examples, "closest": closest,
    })


async def _about_catalogue(db, item, card, target) -> dict:
    t = target or {}
    sector = t.get("sector") or "wod-kan"
    facts = [_fact("Kod", t.get("code")), _fact("Sektor", SECTOR_LABEL.get(sector, sector)),
             _fact("Poziom", "podkategoria" if t.get("parent_code") else "ryzyko główne")]
    return {"title": f"{t.get('code') or ''} {t.get('name') or item.get('title')}".strip(), "lead": t.get("description"), "facts": facts}


# plain questions for data discrepancies stored without one (the item title stays as the subject)
DISCREPANCY_QUESTION = {
    "change_count_mismatch": "Ile zmian tej umowy było naprawdę?",
    "value_deviation": "Która wartość przedsięwzięcia jest właściwa?",
    "part_mismatch": "Którą część przetargu łączymy z projektem?",
    "part_scope_wider": "Którą część przetargu łączymy z projektem?",
    "contract_notice_missing": "Czy ogłoszenia o zamówieniu naprawdę nie ma w BZP?",
    "dates_inconsistent": "Czy słusznie wyłączamy te umowy ze statystyk?",
    "future_date": "Czy daty z przyszłości to błąd w danych BZP?",
}

ABOUT = {"event": _about_event, "link": _about_link, "discrepancy": _about_discrepancy, "fact": _about_fact, "catalogue": _about_catalogue}


async def enrich(db: AsyncSession, item: dict, card: dict) -> dict:
    """Adds `about`, `source`, `strength`, `proposal` and a default `gold` hint to a built card. Never raises: on any error the
    card keeps its base fields and the error is logged."""
    try:
        from riskminer.review.common import fetch_row
        target = None
        if item.get("target_table") and item.get("target_id"):
            try:
                target = await fetch_row(db, item["target_table"], item["target_id"])
            except Exception:  # target table outside the review whitelist (e.g. rc_contract)
                target = None
        about = await ABOUT.get(item["kind"], _about_discrepancy)(db, item, card, target)
        about["facts"] = [f for f in about.get("facts") or [] if f]
        card["about"] = jclean(about)
        card["source"] = jclean(await _evidence_source(db, item, card))
        ev = card.get("evidence") or {}
        card["strength"] = strength(ev.get("verification"), item.get("confidence"))
        if item["kind"] == "discrepancy" and not item.get("question") and item.get("code") in DISCREPANCY_QUESTION:
            card["question"] = DISCREPANCY_QUESTION[item["code"]]
        if item["kind"] == "catalogue":
            card["proposal"] = await _proposal(db, item, target)
            p = card["proposal"] or {}
            if p.get("name"):
                card["question"] = f"Czy dodać do katalogu nowe ryzyko {p['code']} „{p['name']}”?"
        if card.get("gold") is None:
            similar = (await db.execute(text("""SELECT count(*) FROM review_item WHERE kind = :k AND status = 'open' AND id <> :i
                                                AND code IS NOT DISTINCT FROM :c"""), {"k": item["kind"], "i": item["id"], "c": item.get("code")})).scalar() or 0
            card["gold"] = {"label": "Zbiór wzorcowych przykładów", "before": _waiting(similar),
                            "after": "Twoja decyzja zapisana jako wzorcowy przykład"}
    except Exception:  # the base card is still useful; a broken context block must not hide the decision
        log.exception("review card context failed for item %s", item.get("id"))
    return card
