"""Review card (J10): question, evidence quote, options with server-computed effects. All copy is Polish."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.review.common import fetch_row, jclean, pl_money

KIND_LABEL = {
    "event": "Zdarzenie ryzyka", "link": "Powiązanie", "discrepancy": "Rozbieżność w danych", "fact": "Fakt z dokumentu",
    "catalogue": "Propozycja do katalogu", "import": "Import danych", "case_candidate": "Zgłoszony przypadek",
}
# frontend tabs (frontend.md ReviewKind) use plural names; api_contract kinds are singular
KINDS = tuple(KIND_LABEL)


async def _scalar(db: AsyncSession, sql: str, **p) -> Any:
    return (await db.execute(text(sql), p)).scalar()


async def _rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def load_item(db: AsyncSession, item_id: int, *, lock: bool = False) -> dict | None:
    q = ("SELECT r.*, p.rm_id, p.title AS project_title FROM review_item r LEFT JOIN project p ON p.id = r.project_id "
         "WHERE r.id = :id")
    if lock:
        q += " FOR UPDATE OF r"
    rs = await _rows(db, q, id=item_id)
    return rs[0] if rs else None


async def risk_name(db: AsyncSession, code: str | None) -> str | None:
    if not code:
        return None
    return await _scalar(db, "SELECT name FROM catalogue_risk WHERE sector='wod-kan' AND code=:c AND status='approved' "
                             "ORDER BY version DESC LIMIT 1", c=code)


def _opt(key: str, action: str, label: str, sub: str | None = None, *, model_pick: bool = False, confidence: float | None = None,
         needs_input: str | None = None, placeholder: str | None = None, effects: list[dict] | None = None) -> dict:
    badge = None
    if model_pick and confidence is not None:
        badge = f"propozycja modelu, {confidence:.2f}".replace(".", ",")
    elif model_pick:
        badge = "propozycja modelu"
    return {"key": key, "action": action, "label": label, "sub": sub, "model_pick": model_pick, "confidence": confidence,
            "badge": badge, "needs_input": needs_input, "input_placeholder": placeholder, "effects": effects or []}


async def evidence_block(db: AsyncSession, item: dict, target: dict | None) -> dict | None:
    """First evidence row of the target claim (notice field or document page) with its quote."""
    ev = None
    if item.get("target_table") and item.get("target_id"):
        rs = await _rows(db, """SELECT e.*, n.notice_number, n.url AS notice_url FROM evidence e LEFT JOIN notice n ON n.id = e.notice_id
                                WHERE e.claim_table = :t AND e.claim_id = :i ORDER BY (e.quote IS NULL), e.id LIMIT 1""",
                         t=item["target_table"], i=item["target_id"])
        ev = rs[0] if rs else None
    det = item.get("detail") or {}
    if ev:
        ref = {"kind": "notice" if ev.get("notice_id") else "document",
               "id": ev.get("notice_number") or str(ev.get("document_id")),
               "label": f"pole {ev['field_code']}" if ev.get("field_code") else (f"s. {ev['page_no']}" if ev.get("page_no") else "źródło"),
               "field_code": ev.get("field_code"), "page_no": ev.get("page_no"), "url": ev.get("notice_url") or ev.get("url")}
        quote = ev.get("quote") or (target or {}).get("cause") or (target or {}).get("summary") or ""
        return {"title": "Ogłoszenie, opis zmiany" if ev.get("notice_id") else "Dokument", "ref": ref,
                "pre": "", "hit": quote, "post": "", "verification": ev.get("verification")}
    if det.get("evidence") and isinstance(det["evidence"], dict):
        return None
    return None


async def build_card(db: AsyncSession, item: dict) -> dict:
    kind = item["kind"]
    det = item.get("detail") or {}
    target = await fetch_row(db, item["target_table"], item["target_id"]) if item.get("target_table") and item.get("target_id") \
        and item["target_table"] in {"risk_event", "link_candidate", "project", "contract_performance", "contract_change", "catalogue_risk",
                                     "contract", "lot", "document", "organization"} else None
    ctx_label = (item.get("rm_id") or "") + (f", {item['project_title']}" if item.get("project_title") else "")
    card: dict[str, Any] = {
        "id": item["id"], "kind": kind, "kind_label": KIND_LABEL.get(kind, kind), "code": item.get("code"),
        "status": item["status"], "severity": item.get("severity"),
        "context": {"label": ctx_label.strip(", ") or None, "href": f"/projekty/{item['rm_id']}" if item.get("rm_id") else None},
        "question": item.get("question") or item["title"], "sub": det.get("sub") or "",
        "target": {"table": item.get("target_table"), "id": item.get("target_id"),
                   "review_status": (target or {}).get("review_status")},
        "evidence": None, "chips": [], "options": [], "gold": None, "llm": None,
    }
    builder = {"event": _event, "link": _link, "discrepancy": _discrepancy, "fact": _fact, "catalogue": _catalogue}.get(kind, _generic)
    await builder(db, item, target, card)
    card["evidence"] = await evidence_block(db, item, target)
    if item.get("options"):  # options stored with the item (written by the LLM batch or the import agent) win
        card["options"] = item["options"]
    return jclean(card)


# ---------------------------------------------------------------------------------------------------------------- event

async def _case_count(db: AsyncSession, code: str | None) -> int:
    if not code:
        return 0
    return await _scalar(db, "SELECT count(*) FROM risk_event WHERE catalogue_code = :c AND review_status IN ('approved','edited')", c=code) or 0


def _cases(n: int) -> str:
    m10, m100 = n % 10, n % 100
    w = "przypadek" if n == 1 else ("przypadki" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else "przypadków")
    return f"{n} zatwierdzony {w}" if n == 1 else f"{n} zatwierdzone {w}" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else f"{n} zatwierdzonych {w}"


async def _event(db, item, target, card):
    pick = item.get("model_pick") or (target or {}).get("catalogue_code")
    conf = item.get("confidence")
    name = await risk_name(db, pick)
    n = await _case_count(db, pick)
    similar = await _scalar(db, """SELECT count(*) FROM review_item WHERE kind='event' AND status='open' AND id <> :id
                                   AND (model_pick = :p OR (:p IS NULL AND model_pick IS NULL))""", id=item["id"], p=pick) or 0
    eff_approve = [{"where": f"Katalog, ryzyko {pick}", "before": _cases(n), "after": _cases(n + 1)},
                   {"where": "Widok publiczny", "before": "zdarzenie ukryte", "after": "zdarzenie widoczne na karcie"}]
    opts = []
    if pick:
        opts.append(_opt(pick, "approve", f"{pick} {name or ''}".strip(), (target or {}).get("cause") or (target or {}).get("summary"),
                         model_pick=True, confidence=conf, effects=eff_approve))
    opts.append(_opt("other", "edit", "Inne ryzyko z katalogu", None, needs_input="value",
                     placeholder="Kod ryzyka (np. R04) i krótkie uzasadnienie",
                     effects=[{"where": "Katalog", "before": "zdarzenie bez zatwierdzonego ryzyka", "after": "zdarzenie przypisane do wskazanego ryzyka"}]))
    opts.append(_opt("not_risk", "reject", "To nie jest zdarzenie ryzyka", None, needs_input="reason",
                     effects=[{"where": "Widok publiczny", "before": "zdarzenie ukryte", "after": "zdarzenie odrzucone, nie pojawi się w raportach"}]))
    card["options"] = opts
    card["sub"] = card["sub"] or "Od przyczyny zależy, przy którym ryzyku ten przypadek będzie liczony w raportach."
    card["gold"] = {"label": "Podobne propozycje w kolejce", "before": f"{similar} czeka na przegląd",
                    "after": "zostaną przeliczone według Twojej decyzji"}
    if target and target.get("llm_call_id"):
        card["llm"] = await _llm(db, target["llm_call_id"])


async def _llm(db, call_id: int) -> dict | None:
    r = await _rows(db, "SELECT provider, model, data_location FROM llm_call WHERE id = :i", i=call_id)
    if not r:
        return None
    return {**r[0], "llm_call_id": call_id} if "data_location" in r[0] else {"provider": r[0].get("provider"), "model": r[0].get("model"), "llm_call_id": call_id}


# ----------------------------------------------------------------------------------------------------------------- link

async def _link(db, item, target, card):
    if target and target.get("left_table") == "document":
        score = target.get("score")
        card["options"] = [
            _opt("accept", "approve", "Tak, to ta umowa", f"dopasowanie {score:.2f}".replace(".", ",") if score is not None else None,
                 model_pick=True, confidence=score,
                 effects=[{"where": "Karta projektu", "before": "zmiana z dokumentu bez umowy", "after": "zmiana przypisana do tej umowy (nadal do zatwierdzenia)"}]),
            _opt("none", "reject", "Nie, to inna umowa", None, needs_input="reason",
                 effects=[{"where": "Karta projektu", "before": "zmiana przypisana do umowy", "after": "zmiana bez umowy, do ustalenia"}]),
        ]
        card["sub"] = card["sub"] or "W BZP nie ma numeru umowy, więc dopasowanie opiera się na dacie, wykonawcy i terminie."
        feats = target.get("features") or {}
        card["chips"] = [{"text": f"{k}: {v}".replace(".", ","), "tone": "ok" if isinstance(v, (int, float)) and v >= 0.8 else "warn"}
                         for k, v in feats.items() if k != "coverage"]
        return
    ref = (target or {}).get("right_ref")
    score = (target or {}).get("score")
    pick_label = f"Postępowanie {ref}" if ref else "Zaproponowane postępowanie"
    card["options"] = [
        _opt("accept", "approve", pick_label, f"dopasowanie {(target or {}).get('method')}, wynik {score:.2f}".replace(".", ",") if score is not None else None,
             model_pick=True, confidence=score,
             effects=[{"where": "Karta projektu", "before": "powiązanie do sprawdzenia", "after": "powiązanie zatwierdzone, ogłoszenia widoczne na przebiegu"}]),
        _opt("other", "edit", "Inne postępowanie", None, needs_input="value", placeholder="Numer BZP, np. 2025/BZP 00307948/01",
             effects=[{"where": "Karta projektu", "before": "powiązanie do sprawdzenia", "after": "powiązanie wskazane przez eksperta"}]),
        _opt("none", "reject", "Brak w BZP", None, needs_input="reason",
             effects=[{"where": "Karta projektu", "before": "powiązanie do sprawdzenia", "after": "projekt bez postępowania w BZP"}]),
    ]
    card["sub"] = card["sub"] or (target or {}).get("explanation") or "Automat nie był pewny, które postępowanie dotyczy tego projektu."
    card["chips"] = [{"text": f"metoda: {(target or {}).get('method')}", "tone": "neutral"}] if target else []


# ------------------------------------------------------------------------------------------------------- discrepancy

async def _discrepancy(db, item, target, card):
    code = item.get("code")
    det = item.get("detail") or {}
    rm = item.get("rm_id") or ""
    where = f"Karta projektu {rm}".strip()
    if code == "value_deviation":
        pv, bv = det.get("project_value"), det.get("value")
        card["sub"] = card["sub"] or (f"W zestawie organizatora: {pl_money(pv)}. Najbliższa kwota z BZP ({det.get('closest')}): {pl_money(bv)}, "
                                      f"różnica {det.get('diff_pct')}%. Zestaw organizatora zostaje bez zmian.")
        card["options"] = [
            _opt("keep_dataset", "approve", "Wartość z zestawu organizatora jest właściwa", "BZP obejmuje tylko część przedsięwzięcia",
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "wyjaśniona: wartość z zestawu"}]),
            _opt("use_bzp", "approve", "Bliżej prawdy jest kwota z BZP", "zapisujemy to jako notatkę, zestaw organizatora nie jest zmieniany",
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "wyjaśniona: kwota z BZP"}]),
            _opt("dismiss", "reject", "To nie jest rozbieżność", None, needs_input="reason",
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "zamknięta bez zmian"}]),
        ]
        card["chips"] = [{"text": f"różnica {det.get('diff_pct')}%", "tone": "warn"}]
    elif code in ("part_mismatch", "part_scope_wider"):
        parts = det.get("matched_parts") or []
        card["options"] = [
            _opt("keep_dataset", "approve", f"Zostaw część {det.get('dataset_part')} z zestawu", None,
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "wyjaśniona: część z zestawu"}]),
            _opt("use_matched", "edit", "Przyjmij części z opisu przedsięwzięcia: " + ", ".join(str(p) for p in parts), "zmieni części powiązanego postępowania",
                 effects=[{"where": "Powiązanie projektu z postępowaniem", "before": f"część {det.get('dataset_part')}",
                           "after": "części " + ", ".join(str(p) for p in parts)}]),
            _opt("dismiss", "reject", "To nie jest rozbieżność", None, needs_input="reason",
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "zamknięta bez zmian"}]),
        ]
    elif code == "contract_notice_missing":
        card["sub"] = card["sub"] or "Późniejsze ogłoszenia powołują się na ogłoszenie, którego nie ma w BZP."
        card["options"] = [
            _opt("accept_missing", "approve", "Ogłoszenia nie ma w BZP, zostaje zapis o braku", None,
                 effects=[{"where": where, "before": "rozbieżność otwarta", "after": "brak ogłoszenia potwierdzony"}]),
            _opt("link_other", "edit", "Wskaż właściwe ogłoszenie", None, needs_input="value", placeholder="Numer BZP, np. 2023/BZP 00110672/01",
                 effects=[{"where": "Powiązanie projektu z postępowaniem", "before": "brak ogłoszenia o zamówieniu", "after": "powiązanie wskazane przez eksperta"}]),
            _opt("dismiss", "reject", "To nie jest rozbieżność", None, needs_input="reason", effects=[]),
        ]
    else:
        card["options"] = [
            _opt("confirm", "approve", "Potwierdzam rozbieżność", None, effects=[{"where": where, "before": "rozbieżność otwarta", "after": "potwierdzona"}]),
            _opt("note", "edit", "Dodaj wyjaśnienie", None, needs_input="reason", effects=[{"where": where, "before": "rozbieżność otwarta", "after": "wyjaśniona"}]),
            _opt("dismiss", "reject", "To nie jest rozbieżność", None, needs_input="reason", effects=[]),
        ]


# ------------------------------------------------------------------------------------------------------------- fact

async def _fact(db, item, target, card):
    field = item.get("target_field")
    val = (target or {}).get(field) if field else None
    shown = "" if val is None else str(val)
    card["options"] = [
        _opt("keep", "approve", f"Odczyt jest poprawny{': ' + shown if shown else ''}", None, model_pick=True, confidence=item.get("confidence"),
             effects=[{"where": "Karta projektu", "before": "wartość niezweryfikowana", "after": "wartość zatwierdzona"}]),
        _opt("edit", "edit", "Popraw wartość", None, needs_input="value", placeholder="Poprawna wartość",
             effects=[{"where": "Karta projektu", "before": shown or "brak", "after": "wartość ekspercka"}]),
        _opt("reject", "reject", "Odczyt jest błędny", None, needs_input="reason",
             effects=[{"where": "Karta projektu", "before": shown or "brak", "after": "wartość odrzucona"}]),
    ]
    card["gold"] = {"label": "Podobne odczyty w kolejce", "before": "czekają na przegląd", "after": "zostaną przeliczone według Twojej decyzji"}
    if item.get("confidence") is not None and item["confidence"] < 0.5:
        card["chips"].append({"text": "niska pewność modelu", "tone": "warn"})


# ------------------------------------------------------------------------------------------------------- catalogue

async def _catalogue(db, item, target, card):
    merge = (item.get("detail") or {}).get("merge_suggestion") or item.get("model_pick")
    code = (target or {}).get("code")
    card["options"] = [
        _opt("add", "approve", "Dodaj do katalogu jako nowe ryzyko", (target or {}).get("description"), model_pick=not merge,
             effects=[{"where": "Katalog wiedzy", "before": "propozycja AI", "after": "ryzyko zatwierdzone w nowej wersji katalogu"}]),
    ]
    if merge:
        opts_merge = _opt(f"merge:{merge}", "edit", f"Połącz z {merge}", "przyczyna trafi do sygnałów wskazanego ryzyka", model_pick=True,
                          effects=[{"where": f"Katalog, ryzyko {merge}", "before": "bez tego sygnału", "after": "z dodanym sygnałem"}])
        card["options"].insert(0, opts_merge)
    card["options"].append(_opt("reject", "reject", "Odrzuć", None, needs_input="reason",
                                effects=[{"where": "Katalog wiedzy", "before": "propozycja AI", "after": "propozycja odrzucona"}]))
    card["sub"] = card["sub"] or (target or {}).get("description") or ""


# -------------------------------------------------------------------------------------------------------------- generic

async def _generic(db, item, target, card):
    card["options"] = [
        _opt("approve", "approve", "Zatwierdź", None, effects=[]),
        _opt("reject", "reject", "Odrzuć", None, needs_input="reason", effects=[]),
    ]
