"""Derive the case base from `notice` rows (latest versions only), idempotently.

notice ──(tenderId/OCID)──> procedure ──> lot (CN 4.2.x + TR 4.5.x / V–VIII)
                                     └──> contract (TR part awarded; else rebuilt from CP / AU)
                                            ├──> contract_performance (CP: 5.1–5.6, CALC delay/cost)
                                            └──> contract_change (AU 5.x + CP 5.4.x blocks)
Matching CP/AU -> contract inside a procedure: result-notice no. (4.5) + contractor NIP + contract value
(+ lot markers). Contract values, prices and payments are GROSS; estimates are NET (art. 28 Pzp).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from riskminer.ingest import sectors
from riskminer.ingest.dbutil import upsert_copy
from riskminer.parsing import bzp_parse as bp
from riskminer.parsing.change_keywords import keyword_categories, what_changed
from riskminer.parsing.wodkan_classify import classify

log = logging.getLogger("riskminer.derive")

ABBR = {"ContractNotice": "CN", "TenderResultNotice": "TR", "AgreementUpdateNotice": "AU",
        "ContractPerformingNotice": "CP", "NoticeUpdateNotice": "NU"}


def _d(s: Any) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _dec(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        v = Decimal(str(x)).quantize(Decimal("0.01"))
        return v if abs(v) < Decimal("1e15") else None
    except Exception:  # noqa: BLE001
        return None


def _nip(s: Any) -> str | None:
    d = re.sub(r"\D", "", str(s or ""))
    return d if len(d) == 10 else None


def nip_valid(n: str | None) -> bool:
    if not n or len(n) != 10 or not n.isdigit():
        return False
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    return sum(int(a) * b for a, b in zip(n, w)) % 11 == int(n[9])


def _norm_name(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip().lower()


def _cpvs(raw: str | None) -> list[str]:
    return bp.cpv_codes(raw)


def _f(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _int(x: Any) -> int | None:
    try:
        return int(round(float(x))) if x is not None else None
    except (TypeError, ValueError):
        return None


def _match_score(c: dict, ref: str | None, nip: str | None, value: float | None, parts: list[int]) -> float:
    # hard disqualifiers: a different contractor or a different lot is a different contract
    if nip and c.get("contractor_nip") and _nip(c["contractor_nip"]) and _nip(nip) and _nip(c["contractor_nip"]) != _nip(nip):
        return -1.0
    if parts and c.get("lot_no") not in (None, 0) and c.get("lot_no") not in parts:
        return -1.0
    s = 0.0
    if ref and c.get("result_notice_no") == ref:
        s += 2
    if nip and c.get("contractor_nip") == nip:
        s += 2
    cv = c.get("value")
    if value is not None and cv is not None:
        if abs(cv - value) < 1:
            s += 2
        elif value and abs(cv - value) / abs(value) < 0.01:
            s += 1
    if parts and c.get("lot_no") in parts:
        s += 1
    return s


async def run(conn, rid) -> dict:
    rows = await conn.fetch("""
        SELECT id, object_id, notice_type, notice_number, bzp_number, version, ocid, published_at, buyer_nip,
               buyer_name, buyer_city, province, order_object, cpv_raw, refs, extracted, source_id, url,
               raw_json->>'orderType' AS order_type, raw_json->>'tenderType' AS tender_type,
               raw_json->>'clientType' AS client_type, (raw_json->>'isTenderAmountBelowEU')::boolean AS below_eu,
               raw_json->>'organizationId' AS org_id, channel
        FROM notice WHERE is_latest AND ocid IS NOT NULL ORDER BY published_at, id""")
    by_ocid: dict[str, list] = defaultdict(list)
    for r in rows:
        by_ocid[r["ocid"]].append(r)
    all_cn_numbers = {r["bzp_number"] for r in rows if r["notice_type"] == "ContractNotice"}
    log.info("derive: %d notices in %d procedures", len(rows), len(by_ocid))

    proc_recs, lot_recs, contract_recs, perf_recs, change_recs = [], [], [], [], []
    orgs: dict[str, dict] = {}
    contract_meta: dict[str, dict] = {}       # contract key -> {ocid, ...}

    def org(nip: str | None, name: str | None, role: str, extra: dict | None = None):
        if not nip:
            return
        o = orgs.setdefault(nip, {"nip": nip, "name": name, "roles": set(), "extra": {}})
        if name:
            o["name"] = name
        o["roles"].add(role)
        if extra:
            o["extra"].update({k: v for k, v in extra.items() if v})

    for ocid, ns in by_ocid.items():
        types = {ABBR.get(n["notice_type"], "?") for n in ns}
        cns = [n for n in ns if n["notice_type"] == "ContractNotice"]
        trs = [n for n in ns if n["notice_type"] == "TenderResultNotice"]
        aus = [n for n in ns if n["notice_type"] == "AgreementUpdateNotice"]
        cps = [n for n in ns if n["notice_type"] == "ContractPerformingNotice"]
        cn = cns[0] if cns else None
        cn_rows = (cn["extracted"] or {}).get("data") or [] if cn else []
        cn_rows = cn_rows if isinstance(cn_rows, list) else []
        cn0 = cn_rows[0] if cn_rows else {}
        last = ns[-1]
        title = (cn0.get("title") if cn0 else None) or (cn["order_object"] if cn else None) or ns[0]["order_object"]
        desc = cn0.get("shortDescription") if cn0 else None
        if not desc:
            for n in cps + aus:
                dd = ((n["extracted"] or {}).get("data") or {})
                if isinstance(dd, dict) and dd.get("description"):
                    desc = dd["description"]
                    break
        cpv_all: list[str] = []
        for n in ([cn] if cn else []) + ns:
            for c in _cpvs(n["cpv_raw"]):
                if c not in cpv_all:
                    cpv_all.append(c)
        cpv_main = (_cpvs(cn["cpv_raw"]) or [None])[0] if cn else (cpv_all or [None])[0]
        order_type = (cn or ns[0])["order_type"]
        tag = classify(title, desc, cpv_main, " ".join(cpv_all), order_type)
        # result-notice rows (one per lot) -------------------------------------------------
        tr_rows = []
        for t in trs:
            data = (t["extracted"] or {}).get("data") or []
            for row in (data if isinstance(data, list) else []):
                tr_rows.append((t, row))
        est = None
        if tr_rows:
            parts_est = [r.get("estimatedValueNet") for _, r in tr_rows if r.get("part") is not None]
            if parts_est and all(v is not None for v in parts_est):
                est = sum(parts_est)
            else:
                est = tr_rows[0][1].get("estimatedValueNet")
        if est is None and cn_rows:
            vals = [r.get("estimatedValueNet") for r in cn_rows if r.get("estimatedValueNet") is not None]
            est = sum(vals) if vals and len(vals) == len(cn_rows) else (vals[0] if vals else None)
        cited_cn = None
        for n in cps + aus + trs:
            dd = (n["extracted"] or {}).get("data")
            dd = dd[0] if isinstance(dd, list) and dd else dd
            if isinstance(dd, dict) and dd.get("contractNoticeRef") and "BZP" in str(dd.get("contractNoticeRef")):
                cited_cn = dd["contractNoticeRef"]
                break
        eu = None
        for n in ([cn] if cn else []) + cps + aus:
            dd = (n["extracted"] or {}).get("data")
            dd = dd[0] if isinstance(dd, list) and dd else dd
            if isinstance(dd, dict) and dd.get("euFunded") is not None:
                eu = dd["euFunded"]
                break
        cancelled = all(r.get("cancelled") for _, r in tr_rows) if tr_rows else None
        n_lots = max([r.get("nParts") or 1 for r in cn_rows] + [r.get("nParts") or 1 for _, r in tr_rows] + [1])
        platform = ((cn["extracted"] or {}).get("platform_urls") or [None])[0] if cn else None
        buyer_nip = _nip(last["buyer_nip"])
        org(buyer_nip, last["buyer_name"], "buyer", {"city": last["buyer_city"], "province": last["province"],
                                                    "bzp_org_id": last["org_id"]})
        proc_recs.append((
            ocid, (cn["bzp_number"] if cn else cited_cn), cn is None and bool(cited_cn) and cited_cn not in all_cn_numbers,
            title, buyer_nip, last["buyer_name"], last["province"], last["buyer_city"], cpv_main, cpv_all,
            (cn0.get("procedure") if cn0 else None) or (tr_rows[0][1].get("procedure") if tr_rows else None),
            order_type, (cn or ns[0])["tender_type"], (cn or ns[0])["client_type"],
            _dec(est), "PLN" if est is not None else None, "net" if est is not None else None,
            (cn or ns[0])["below_eu"], eu, cn0.get("euProject") if cn0 else None, n_lots, platform,
            ns[0]["published_at"].date() if ns[0]["published_at"] else None,
            last["published_at"].date() if last["published_at"] else None,
            sorted(types), cancelled, tag.relevance, tag.primary, tag.subsectors, tag.scope_kind, tag.work_type,
            tag.design_build, tag.why, (cn or ns[0])["source_id"], "SOURCE", "auto",
            sectors.assign_sector(all(n["channel"] == "bzp_roads" for n in ns), tag.relevance, cpv_main, cpv_all),
        ))
        # lots ------------------------------------------------------------------------------
        lots: dict[int, dict] = {}
        for r in cn_rows:
            ln = r.get("part") or 0
            lots[ln] = {"description": r.get("shortDescription"), "cpv": r.get("cpvMainForm") or cpv_main,
                        "duration_raw": r.get("durationRaw"), "est": r.get("estimatedValueNet") if r.get("part") else None,
                        "cn_id": cn["id"] if cn else None}
        for t, r in tr_rows:
            ln = r.get("part") or 0
            lot = lots.setdefault(ln, {})
            lot.update({"outcome": r.get("outcome"), "cancelled": r.get("cancelled"), "cancel_basis": r.get("cancelBasis"),
                        "cancel_reason": r.get("cancelReason"), "n_offers": r.get("nOffers"), "n_sme": r.get("nOffersSME"),
                        "n_rej": r.get("nRejected"), "min": r.get("minOffer"), "max": r.get("maxOffer"),
                        "win": r.get("winningOffer"), "tr_id": t["id"]})
            if r.get("part") is not None and r.get("estimatedValueNet") is not None:
                lot["est"] = r.get("estimatedValueNet")
            elif ln == 0 and lot.get("est") is None:
                lot["est"] = r.get("estimatedValueNet")
        for ln, lot in lots.items():
            lot_recs.append((ocid, ln, lot.get("description"), lot.get("cpv"), lot.get("duration_raw"), _dec(lot.get("est")),
                             "PLN" if lot.get("est") is not None else None, "net" if lot.get("est") is not None else None,
                             lot.get("outcome"), lot.get("cancelled"), lot.get("cancel_basis"), lot.get("cancel_reason"),
                             _int(lot.get("n_offers")), _int(lot.get("n_sme")), _int(lot.get("n_rej")), _dec(lot.get("min")),
                             _dec(lot.get("max")), _dec(lot.get("win")), lot.get("cn_id"), lot.get("tr_id"),
                             (cn or ns[0])["source_id"], "SOURCE", "auto"))
        # contracts ---------------------------------------------------------------------------
        contracts: list[dict] = []
        for t, r in tr_rows:
            if r.get("cancelled") or not (r.get("contractValue") or r.get("contractorName") or r.get("contractDate")):
                continue
            key = f"tr|{t['object_id']}|{r.get('part') or 0}"
            c = {"key": key, "lot_no": r.get("part") or 0, "contractor_name": r.get("contractorName"),
                 "contractor_nip": r.get("contractorNip"), "signed_on": _d(r.get("contractDate")),
                 "duration_raw": r.get("durationRaw"), "planned_days": r.get("plannedDays"),
                 "planned_end": _d(r.get("plannedEnd")), "computed": r.get("durationKind") == "days",
                 "value": r.get("contractValue"), "terms": "result_notice", "tr_id": t["id"],
                 "result_notice_no": t["bzp_number"], "source_id": t["source_id"]}
            contracts.append(c)
            org(c["contractor_nip"], c["contractor_name"], "contractor")

        def attach(n, d: dict, terms: str) -> dict:
            parts = (n["extracted"] or {}).get("parts") or []
            best, best_s = None, 0.0
            for c in contracts:
                s = _match_score(c, d.get("resultNoticeRef"), d.get("contractorNip"), d.get("contractValue"), parts)
                if s > best_s:
                    best, best_s = c, s
            if best is not None and best_s >= 2:
                return best
            if len(contracts) == 1 and not d.get("contractorNip") and best_s >= 0:
                return contracts[0]
            c = {"key": f"{ABBR[n['notice_type']].lower()}|{n['object_id']}", "lot_no": parts[0] if len(parts) == 1 else None,
                 "contractor_name": d.get("contractorName"), "contractor_nip": d.get("contractorNip"),
                 "signed_on": _d(d.get("contractDate")), "duration_raw": d.get("durationRaw"),
                 "planned_days": d.get("plannedDays"), "planned_end": _d(d.get("plannedEnd")),
                 "computed": d.get("durationKind") == "days", "value": d.get("contractValue"), "terms": terms,
                 "tr_id": None, "result_notice_no": d.get("resultNoticeRef"), "source_id": n["source_id"]}
            contracts.append(c)
            org(c["contractor_nip"], c["contractor_name"], "contractor")
            return c

        for n in cps:
            d = (n["extracted"] or {}).get("data") or {}
            if not isinstance(d, dict) or d.get("_parse_error"):
                continue
            c = attach(n, d, "performance_notice")
            perf_recs.append((c["key"], ocid, n["id"], d.get("executed"), _d(d.get("execDate")), d.get("onTimeDeclared"),
                              d.get("nChanges"), _dec(d.get("paid")), d.get("paidCurrency") or ("PLN" if d.get("paid") is not None else None),
                              "gross" if d.get("paid") is not None else None, d.get("properlyPerformed"),
                              d.get("notExecutedReason"), d.get("improperReason"), _dec(d.get("contractValue")),
                              _d(d.get("contractDate")), _d(d.get("plannedEnd")), _f(d.get("plannedDays")),
                              _int(d.get("actualDays")), _int(d.get("delayDays")), _f(d.get("costDevPct")),
                              n["source_id"], "SOURCE", "auto"))
            for i, ch in enumerate(d.get("changes") or []):
                txt_r, txt_d = ch.get("reason"), ch.get("description")
                change_recs.append((f"cp|{n['object_id']}|{i}", c["key"], ocid, n["id"], "performance_block", ch.get("no"),
                                    None, (ch.get("basis") or "").split(), ch.get("basis_raw"),
                                    what_changed(txt_r, txt_d), bp.extension_days(txt_d) or bp.extension_days(txt_r),
                                    _dec(ch.get("value_change")), (ch.get("currency") or "PLN")[:3] if ch.get("value_change") is not None else None,
                                    "unknown" if ch.get("value_change") is not None else None, None, ch.get("price_increase"),
                                    txt_r, txt_d, keyword_categories(txt_r, txt_d), "5.4.2", n["source_id"], "SOURCE", "auto"))
        for n in aus:
            d = (n["extracted"] or {}).get("data") or {}
            if not isinstance(d, dict) or d.get("_parse_error"):
                continue
            c = attach(n, d, "change_notice")
            txt_r, txt_d = d.get("reason"), d.get("changeDescription")
            change_recs.append((f"au|{n['object_id']}", c["key"], ocid, n["id"], "change_notice", n["bzp_number"],
                                _d(d.get("changeDate")), (d.get("basis") or "").split(), d.get("basisRaw"),
                                what_changed(txt_r, txt_d), _f(d.get("extensionDays")), _dec(d.get("valueChange")),
                                (d.get("valueChangeCurrency") or "PLN")[:3] if d.get("valueChange") is not None else None,
                                "unknown" if d.get("valueChange") is not None else None, _f(d.get("valueChangePct")),
                                d.get("priceIncrease"), txt_r, txt_d, keyword_categories(txt_r, txt_d), "5.1",
                                n["source_id"], "SOURCE", "auto"))
        for c in contracts:
            contract_meta[c["key"]] = {"ocid": ocid}
            contract_recs.append((c["key"], ocid, c["lot_no"], c["contractor_name"], _nip(c["contractor_nip"]),
                                  c["contractor_nip"], c["signed_on"], c["duration_raw"], _f(c["planned_days"]),
                                  c["planned_end"], c["computed"], _dec(c["value"]), "PLN" if c["value"] is not None else None,
                                  "gross" if c["value"] is not None else None, c["terms"], c["tr_id"],
                                  c["result_notice_no"], c["source_id"], "SOURCE", "auto"))

    stats: dict[str, Any] = {"procedures": len(proc_recs), "lots": len(lot_recs), "contracts": len(contract_recs),
                             "performance": len(perf_recs), "changes": len(change_recs), "organizations": len(orgs)}
    async with conn.transaction():
        # organizations
        await upsert_copy(conn, "organization", ("nip", "name", "name_norm", "roles", "province", "city", "nip_valid",
                                                 "bzp_org_ids", "origin", "review_status"),
                          [(o["nip"], o["name"] or o["nip"], _norm_name(o["name"]), sorted(o["roles"]),
                            o["extra"].get("province"), o["extra"].get("city"), nip_valid(o["nip"]),
                            [o["extra"]["bzp_org_id"]] if o["extra"].get("bzp_org_id") else [], "SOURCE", "auto")
                           for o in orgs.values()], ("nip",),
                          update=["name", "name_norm", "roles", "province", "city", "nip_valid", "bzp_org_ids"])
        # procedures
        pcols = ("ocid", "contract_notice_no", "contract_notice_missing", "title", "buyer_nip", "buyer_name", "province",
                 "city", "cpv_main", "cpv_all", "mode", "order_type", "tender_type", "client_type", "estimated_value_amount",
                 "estimated_value_currency", "estimated_value_vat", "below_eu", "eu_funded", "eu_project", "n_lots",
                 "platform_url", "first_published_on", "last_published_on", "notice_types", "cancelled", "relevance",
                 "subsector_main", "subsectors", "scope_kind", "work_type", "design_build", "classify_why", "source_id",
                 "origin", "review_status", "sector")
        await upsert_copy(conn, "procedure", pcols, proc_recs, ("ocid",))
        await conn.execute("UPDATE procedure p SET buyer_org_id = o.id FROM organization o WHERE p.buyer_nip = o.nip "
                           "AND p.buyer_org_id IS DISTINCT FROM o.id")
        await conn.execute("UPDATE notice n SET procedure_id = p.id FROM procedure p WHERE n.ocid = p.ocid "
                           "AND n.procedure_id IS DISTINCT FROM p.id")
        pid = {r["ocid"]: r["id"] for r in await conn.fetch("SELECT id, ocid FROM procedure")}
        # lots
        lcols = ("procedure_id", "lot_no", "description", "cpv_main", "duration_raw", "estimated_value_amount",
                 "estimated_value_currency", "estimated_value_vat", "outcome", "cancelled", "cancel_basis", "cancel_reason",
                 "n_offers", "n_offers_sme", "n_rejected", "min_offer_amount", "max_offer_amount", "winning_offer_amount",
                 "contract_notice_id", "result_notice_id", "source_id", "origin", "review_status")
        await upsert_copy(conn, "lot", lcols, [(pid[r[0]], *r[1:]) for r in lot_recs], ("procedure_id", "lot_no"))
        lot_id = {(r["procedure_id"], r["lot_no"]): r["id"] for r in await conn.fetch("SELECT id, procedure_id, lot_no FROM lot")}
        # contracts
        ccols = ("key", "procedure_id", "lot_no", "contractor_name", "contractor_nip", "contractor_id_raw", "signed_on",
                 "duration_raw", "planned_duration_days", "planned_end_on", "planned_end_computed", "value_amount",
                 "value_currency", "value_vat", "terms_source", "result_notice_id", "result_notice_no", "source_id",
                 "origin", "review_status")
        await upsert_copy(conn, "contract", ccols, [(r[0], pid[r[1]], *r[2:]) for r in contract_recs], ("key",))
        await conn.execute("""UPDATE contract c SET lot_id = l.id FROM lot l
                              WHERE l.procedure_id = c.procedure_id AND l.lot_no = coalesce(c.lot_no, 0)
                                AND c.lot_id IS DISTINCT FROM l.id""")
        await conn.execute("UPDATE contract c SET contractor_org_id = o.id FROM organization o "
                           "WHERE c.contractor_nip = o.nip AND c.contractor_org_id IS DISTINCT FROM o.id")
        cid = {r["key"]: r["id"] for r in await conn.fetch("SELECT id, key FROM contract WHERE key IS NOT NULL")}
        # performance
        pfcols = ("contract_id", "procedure_id", "notice_id", "executed", "completed_on", "on_time_declared", "changes_count",
                  "total_paid_amount", "total_paid_currency", "total_paid_vat", "properly_performed", "not_executed_reason",
                  "improper_reason", "contract_value_amount", "signed_on", "planned_end_on", "planned_days", "actual_days",
                  "delay_days", "cost_dev_pct", "source_id", "origin", "review_status")
        await upsert_copy(conn, "contract_performance", pfcols,
                          [(cid.get(r[0]), pid[r[1]], *r[2:]) for r in perf_recs], ("notice_id",))
        # changes
        chcols = ("key", "contract_id", "procedure_id", "notice_id", "kind", "change_no", "changed_on", "legal_basis",
                  "legal_basis_raw", "change_types", "delta_days", "delta_value_amount", "delta_value_currency",
                  "delta_value_vat", "delta_value_pct", "price_increase", "cause_text", "description_text",
                  "cause_codes_kw", "field_code", "source_id", "origin", "review_status")
        await upsert_copy(conn, "contract_change", chcols,
                          [(r[0], cid.get(r[1]), pid[r[2]], *r[3:]) for r in change_recs], ("key",))
        stats["lot_ids"] = len(lot_id)
        stats["perf_duplicates"] = await mark_perf_duplicates(conn)
        stats["evidence"] = await write_evidence(conn)
    await conn.execute("REFRESH MATERIALIZED VIEW rc_contract")
    stats["rc_contract"] = await conn.fetchval("SELECT count(*) FROM rc_contract")
    return stats


async def mark_perf_duplicates(conn) -> int:
    """Same contract (tenderId + contractor NIP/name + contract value) re-published as another performance
    notice: keep the latest publication, flag the others (research/bzp_corpus: 213 such notices)."""
    await conn.execute("UPDATE contract_performance SET is_duplicate = false, duplicate_of_id = NULL WHERE is_duplicate")
    r = await conn.execute("""
        WITH k AS (
          SELECT pf.id, first_value(pf.id) OVER w AS keep_id, row_number() OVER w AS rn
          FROM contract_performance pf JOIN notice n ON n.id = pf.notice_id
          WINDOW w AS (PARTITION BY pf.procedure_id,
                                    coalesce(n.extracted->'data'->>'contractorNip', n.extracted->'data'->>'contractorName', ''),
                                    coalesce(n.extracted->'data'->>'contractValue', '')
                       ORDER BY n.published_at DESC, n.id DESC))
        UPDATE contract_performance pf SET is_duplicate = true, duplicate_of_id = k.keep_id
        FROM k WHERE pf.id = k.id AND k.rn > 1""")
    return int(r.split()[-1])


# field codes per claim (structured-field evidence, verification = structured_field, state = POTWIERDZONO)
_EVIDENCE_SQL = [
    ("contract", "value", "8.2", "c.value_amount IS NOT NULL AND c.terms_source='result_notice'", "c.result_notice_id"),
    ("contract", "signed_on", "8.1", "c.signed_on IS NOT NULL AND c.terms_source='result_notice'", "c.result_notice_id"),
    ("contract", "planned_end_on", "8.3", "c.planned_end_on IS NOT NULL AND c.terms_source='result_notice'", "c.result_notice_id"),
]
_EVIDENCE_PERF = [("completed_on", "5.2"), ("total_paid", "5.5"), ("on_time_declared", "5.3"), ("executed", "5.1"),
                  ("properly_performed", "5.6"), ("changes_count", "5.4.1")]


async def write_evidence(conn) -> int:
    await conn.execute("DELETE FROM evidence WHERE verification = 'structured_field' "
                       "AND claim_table IN ('contract','contract_performance','contract_change')")
    n = 0
    for table, field, code, cond, notice_col in _EVIDENCE_SQL:
        r = await conn.execute(f"""
            INSERT INTO evidence (claim_table, claim_id, claim_field, source_id, notice_id, field_code, url, retrieved_at,
                                  verification, evidence_state)
            SELECT '{table}', c.id, '{field}', n.source_id, n.id, '{code}', n.url, s.retrieved_at, 'structured_field', 'POTWIERDZONO'
            FROM contract c JOIN notice n ON n.id = {notice_col} LEFT JOIN source s ON s.id = n.source_id WHERE {cond}""")
        n += int(r.split()[-1])
    for field, code in _EVIDENCE_PERF:
        r = await conn.execute(f"""
            INSERT INTO evidence (claim_table, claim_id, claim_field, source_id, notice_id, field_code, url, retrieved_at,
                                  verification, evidence_state)
            SELECT 'contract_performance', p.id, '{field}', n.source_id, n.id, '{code}', n.url, s.retrieved_at,
                   'structured_field', 'POTWIERDZONO'
            FROM contract_performance p JOIN notice n ON n.id = p.notice_id LEFT JOIN source s ON s.id = n.source_id""")
        n += int(r.split()[-1])
    r = await conn.execute("""
        INSERT INTO evidence (claim_table, claim_id, claim_field, source_id, notice_id, field_code, url, retrieved_at,
                              verification, evidence_state, quote)
        SELECT 'contract_change', ch.id, 'cause_text', n.source_id, n.id,
               CASE WHEN ch.kind = 'change_notice' THEN '5.3' ELSE '5.4.4' END, n.url, s.retrieved_at,
               'structured_field', 'POTWIERDZONO', left(ch.cause_text, 2000)
        FROM contract_change ch JOIN notice n ON n.id = ch.notice_id LEFT JOIN source s ON s.id = n.source_id
        WHERE ch.cause_text IS NOT NULL""")
    n += int(r.split()[-1])
    return n
