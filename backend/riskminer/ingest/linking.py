"""Link pilot projects (organizer XLSX) to BZP procedures, identifier-first (PLAN §6.1–6.3).

Port of research/bzp_linking/link_projects.py onto the DB (the offline copy = what the mirror serves):
  1. BZP number given  -> notice with that number (exact_id, 1.0); if absent from the source, the
     notices of the same buyer that CITE the number (cross_reference, 0.95), e.g. RM-2026-022 Wolin.
  2. KPO number only   -> the buyer's procedures (client-side NIP filter) scored on title/description
     token overlap + water/sewage CPV + date ≥ 2024 (KPO B3.1.1 era) -> best ≥ 0.25 (fuzzy).
  3. Chain = all notices with the OCID + same-buyer notices citing any of its numbers.
  4. Cross-source validation -> review_item (discrepancy): NIP/province mismatch, część vs lots
     (Zakrzew row 9, Biecz row 8), KPO value vs contract amounts (rows 7/14), missing contract notice (row 22).
Every candidate is stored in link_candidate with its features; the chosen one becomes project_procedure.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from riskminer.config import REPO_ROOT
from riskminer.ingest import ids
from riskminer.ingest.dbutil import audit, upsert_copy

WODKAN_CPV = ("45231", "45232", "45252", "45247", "45330", "45332", "4523")
STOP = set("w i oraz na z do dla od po we ze ul gmina gminy gminie miejscowosci miejscowosc m budowa przebudowa "
           "rozbudowa sieci siec terenie zakresie wraz formule zaprojektuj wybuduj etap czesc".split())
ACCEPT, REVIEW = 0.9, 0.6     # thresholds for automatic decision (PLAN §6.3)
MIN_FUZZY = 0.21               # = research threshold 0.25 on the raw 0..1.2 scale
REFERENCE = REPO_ROOT / "research/bzp_linking/chains.json"


def tokens(s: str | None) -> set[str]:
    return {t[:6] for t in re.findall(r"[a-z0-9]{3,}", ids.fold(s or "")) if t not in STOP}


def _desc(p) -> str:
    return re.sub(r"^.*Opis:", "", p["annotation"] or "", flags=re.S)


async def _notices_of(conn, where: str, *args):
    return await conn.fetch(f"""
        SELECT n.id, n.object_id, n.notice_type, n.notice_number, n.bzp_number, n.ocid, n.published_at, n.buyer_nip,
               n.buyer_name, n.province, n.order_object, n.cpv_raw, n.refs, n.url, n.extracted
        FROM notice n WHERE n.is_latest AND {where}""", *args)


def _score_candidate(group, p) -> tuple[float, dict]:
    title = " ".join({n["order_object"] or "" for n in group})
    want = tokens(p["title"]) | tokens(_desc(p))
    have = tokens(title)
    overlap = want & have
    jac = len(overlap) / max(1, len(tokens(p["title"]) | have))
    cpv = any(c in (n["cpv_raw"] or "") for n in group for c in WODKAN_CPV)
    first = min(n["published_at"] for n in group).date()
    kpo_year = first >= date(2024, 1, 1)
    raw = jac + (0.1 if cpv else 0) + (0.1 if kpo_year else 0)
    score = min(1.0, raw / 1.2)          # normalised to 0..1 (1.0 = all title words + CPV + KPO era)
    return round(score, 3), {"raw_score": round(raw, 3), "title_jaccard": round(jac, 3), "overlap": sorted(overlap), "cpv_wodkan": cpv,
                             "first_published": first.isoformat(), "kpo_era": kpo_year, "nip_match": True,
                             "title": title[:200]}


async def run(conn, rid) -> dict:
    projects = await conn.fetch("SELECT * FROM project WHERE is_pilot ORDER BY rm_id")
    ref = {}
    if REFERENCE.exists():
        ref = {c["project_id"]: c.get("tenderId") for c in json.loads(REFERENCE.read_text(encoding="utf-8"))}
    results, cand_rows, issues = [], [], []
    for p in projects:
        rm, nip = p["rm_id"], p["beneficiary_nip"]
        ext = p["external_ids"] or {}
        res = {"rm_id": rm, "method": None, "ocid": None, "score": None, "flags": []}

        def issue(code, title, severity="medium", **detail):
            issues.append((rm, code, title, severity, detail))

        given = None
        if ext.get("bzp_base"):
            base = ext["bzp_base"]
            hits = await _notices_of(conn, "n.bzp_number = $1", base)
            hits = sorted(hits, key=lambda n: (n["notice_type"] != "ContractNotice", n["published_at"]))
            if hits:
                given = hits[0]
                res.update(method="exact_id", ocid=given["ocid"], score=1.0)
                if given["notice_type"] != "ContractNotice":
                    issue("bzp_not_contract_notice", f"Numer {base} to ogłoszenie typu {given['notice_type']}, "
                          "nie ogłoszenie o zamówieniu", "low", notice=given["notice_number"])
                if ids.digits(given["buyer_nip"]) != nip:
                    issue("nip_mismatch", f"NIP w zestawie ({nip}) różni się od NIP zamawiającego w ogłoszeniu "
                          f"({given['buyer_nip']}, {given['buyer_name']})", "high",
                          dataset_nip=nip, notice_nip=given["buyer_nip"], notice=given["notice_number"])
                    nip = ids.digits(given["buyer_nip"])
            else:
                cites = await _notices_of(conn, "n.refs @> ARRAY[$1]::varchar[] AND n.buyer_nip = $2", base, nip)
                tids = sorted({n["ocid"] for n in cites})
                if tids:
                    res.update(method="cross_reference", ocid=tids[0], score=0.95)
                    issue("contract_notice_missing",
                          f"Ogłoszenie {base} nie występuje w źródle (BZP); {len(cites)} późniejsze ogłoszenia "
                          f"zamawiającego powołują ten numer (postępowanie {tids[0]})", "high",
                          cited_by=[n["notice_number"] for n in cites], ocids=tids)
                    if len(tids) > 1:
                        issue("number_cited_by_many", f"Numer {base} powołują różne postępowania: {tids}", "medium")
                else:
                    issue("bzp_not_found", f"Numer {base} nie znaleziony w BZP (żaden z 4 typów ogłoszeń) ani w "
                          "odwołaniach innych ogłoszeń zamawiającego", "high")
        if res["ocid"] is None:
            org_notices = await _notices_of(conn, "n.buyer_nip = $1", nip)
            groups = defaultdict(list)
            for n in org_notices:
                groups[n["ocid"]].append(n)
            cands = []
            for tid, g in groups.items():
                s, feats = _score_candidate(g, p)
                cands.append((s, tid, feats, g))
            cands.sort(key=lambda c: -c[0])
            for rank, (s, tid, feats, g) in enumerate(cands[:5], 1):
                cand_rows.append((p["id"], tid, "fuzzy", feats, s, rank,
                                  f"NIP zgodny; wspólne słowa tytułu: {', '.join(feats['overlap'][:8]) or 'brak'}; "
                                  f"CPV wod-kan: {'tak' if feats['cpv_wodkan'] else 'nie'}; "
                                  f"pierwsze ogłoszenie {feats['first_published']}",
                                  "accept" if s >= ACCEPT else "review" if s >= MIN_FUZZY else "reject"))
            if cands and cands[0][0] >= MIN_FUZZY:
                res.update(method="fuzzy", ocid=cands[0][1], score=cands[0][0])
                if len(cands) > 1 and cands[1][0] >= cands[0][0] - 0.04:
                    issue("ambiguous_link", f"Niejednoznaczne powiązanie: drugi kandydat w odległości ≤0,05 "
                          f"({cands[1][1]})", "medium", top=[c[:2] for c in cands[:3]])
            else:
                issue("no_procedure_found", "Nie znaleziono postępowania po NIP/nazwie/CPV/dacie", "high")
        else:
            cand_rows.append((p["id"], res["ocid"], res["method"], {"given": ext.get("bzp") or ext.get("kpo"),
                              "nip_match": True}, res["score"], 1,
                              "Powiązanie po identyfikatorze publicznym (numer ogłoszenia BZP)"
                              if res["method"] == "exact_id" else
                              "Numer ogłoszenia z zestawu powołany w późniejszych ogłoszeniach tego zamawiającego",
                              "accept"))
        if res["ocid"] is None:
            results.append(res)
            continue

        # ---- chain + validations -------------------------------------------------------------
        chain = await _notices_of(conn, "n.ocid = $1", res["ocid"])
        nums = sorted({n["bzp_number"] for n in chain if n["bzp_number"]})
        extra = await _notices_of(conn, "n.refs && $1::varchar[] AND n.buyer_nip = $2 AND n.ocid <> $3", nums, nip, res["ocid"])
        res["related_ocids"] = sorted({n["ocid"] for n in extra})
        res["chain"] = [n["notice_number"] for n in sorted(chain, key=lambda n: n["published_at"])]
        provs = {n["province"] for n in chain if n["province"]}
        if p["province"] and provs and p["province"] not in provs:
            issue("province_mismatch", f"Województwo w zestawie ({p['province']}) różni się od ogłoszeń ({sorted(provs)})",
                  "medium", dataset=p["province"], notices=sorted(provs))
        cn = next((n for n in chain if n["notice_type"] == "ContractNotice"), None)
        titles = (cn["order_object"] if cn else None) or " ".join({n["order_object"] or "" for n in chain})
        tt = tokens(p["title"])
        sim = len(tt & tokens(titles)) / max(1, len(tt))
        res["title_similarity"] = round(sim, 2)
        if sim < 0.5:
            issue("low_title_similarity", f"Niska zgodność nazwy przedsięwzięcia z tytułem ogłoszenia ({sim:.2f}): "
                  f"„{titles[:120]}”", "medium", similarity=round(sim, 2))
        # część vs lots
        want_part = p["scope_part"]
        cn_rows = ((cn["extracted"] or {}).get("data") if cn else None) or []
        lot_desc = {r.get("part"): r.get("shortDescription") or "" for r in cn_rows if isinstance(r, dict) and r.get("part")}
        if want_part is not None and len(lot_desc) <= 1:
            nl = await conn.fetchval("SELECT count(*) FROM lot l JOIN procedure pr ON pr.id=l.procedure_id "
                                     "WHERE pr.ocid=$1 AND l.lot_no > 0", res["ocid"])
            if not nl:
                issue("part_but_no_lots", f"Zestaw wskazuje część {want_part}, ale postępowanie nie jest podzielone "
                      "na części", "medium", dataset_part=want_part)
        if len(lot_desc) > 1:
            desc = tokens(p["title"] + " " + _desc(p))
            ptok = {k: tokens(v) for k, v in lot_desc.items()}
            excl = {k: t - set().union(*[o for q, o in ptok.items() if q != k]) for k, t in ptok.items()}
            hit = {k: sorted(desc & e) for k, e in excl.items()}
            matched = sorted(k for k, h in hit.items() if h)
            res["part_evidence"] = hit
            if want_part is not None and matched and want_part not in matched:
                issue("part_mismatch", f"Zestaw wskazuje część {want_part}, ale opis przedsięwzięcia odpowiada części "
                      f"{matched} (wyróżniające słowa: {[hit[k][:4] for k in matched]})", "high",
                      dataset_part=want_part, matched_parts=matched, evidence=hit)
            elif want_part is not None and len(matched) > 1:
                issue("part_scope_wider", f"Zestaw wskazuje część {want_part}, ale opis przedsięwzięcia obejmuje części "
                      f"{matched}", "high", dataset_part=want_part, matched_parts=matched, evidence=hit)
        # KPO / project value vs BZP amounts
        if p["value_amount"] is not None:
            cs = await conn.fetch("""
                SELECT c.lot_no, c.value_amount, max(pf.total_paid_amount) AS paid
                FROM contract c JOIN procedure pr ON pr.id = c.procedure_id
                LEFT JOIN contract_performance pf ON pf.contract_id = c.id
                WHERE pr.ocid = $1 GROUP BY c.id, c.lot_no, c.value_amount""", res["ocid"])
            kpo = float(p["value_amount"])
            opts = {"suma wartości umów": sum(float(c["value_amount"] or 0) for c in cs),
                    "suma wypłat": sum(float(c["paid"] or 0) for c in cs if c["paid"] is not None)}
            for c in cs:
                opts[f"część {c['lot_no']} umowa"] = float(c["value_amount"] or 0)
                if c["paid"] is not None:
                    opts[f"część {c['lot_no']} wypłata"] = float(c["paid"])
            opts = {k: v for k, v in opts.items() if v}
            if opts:
                best = min(opts, key=lambda k: abs(opts[k] - kpo))
                diff = (opts[best] - kpo) / kpo * 100
                res["value_check"] = {"project_value": kpo, "closest": best, "value": round(opts[best], 2),
                                      "diff_pct": round(diff, 2)}
                if abs(diff) > 15:
                    issue("value_deviation", f"Wartość przedsięwzięcia {_pln(kpo)} odbiega od kwot z BZP "
                          f"(najbliższa: {best} {_pln(opts[best])}, {diff:+.1f}%)".replace(".", ","), "high",
                          **res["value_check"])
        results.append(res)

    # ---- persist ------------------------------------------------------------------------------
    pid = {p["rm_id"]: p["id"] for p in projects}
    proc = {r["ocid"]: r["id"] for r in await conn.fetch(
        "SELECT id, ocid FROM procedure WHERE ocid = ANY($1::text[])",
        list({r["ocid"] for r in results if r["ocid"]} | {c[1] for c in cand_rows} |
             {o for r in results for o in r.get("related_ocids", [])}))}
    async with conn.transaction():
        lc = await upsert_copy(
            conn, "link_candidate",
            ("left_table", "left_id", "right_table", "right_id", "right_ref", "method", "features", "score", "rank",
             "explanation", "decision", "review_status", "run_id", "reference_verdict"),
            [("project", c[0], "procedure", proc.get(c[1]), c[1], c[2], c[3], c[4], c[5], c[6], c[7],
              "auto" if c[7] == "accept" else "proposed", rid,
              None) for c in cand_rows],
            ("left_table", "left_id", "right_table", "right_ref", "method"),
            update=["right_id", "features", "score", "rank", "explanation", "decision", "run_id"],
            returning=("id", "left_id", "right_ref"))
        lc_id = {(r["left_id"], r["right_ref"]): r["id"] for r in lc}
        pp = []
        for r in results:
            if not r["ocid"] or r["ocid"] not in proc:
                continue
            prow = next(p for p in projects if p["rm_id"] == r["rm_id"])
            expl = {k: r.get(k) for k in ("method", "score", "title_similarity", "value_check", "part_evidence", "chain",
                                          "related_ocids")}
            pp.append((pid[r["rm_id"]], proc[r["ocid"]], r["method"], r["score"], expl,
                       lc_id.get((pid[r["rm_id"]], r["ocid"])),
                       [prow["scope_part"]] if prow["scope_part"] else [], "CALC",
                       "auto" if (r["score"] or 0) >= ACCEPT else "proposed"))
            for o in r.get("related_ocids", []):
                if o in proc:
                    pp.append((pid[r["rm_id"]], proc[o], "cross_reference_related", 0.5,
                               {"note": "postępowanie powołujące numery z łańcucha (np. powtórzone/dokończenie)"},
                               None, [], "CALC", "proposed"))
        await upsert_copy(conn, "project_procedure",
                          ("project_id", "procedure_id", "method", "score", "explanation", "link_candidate_id", "lots",
                           "origin", "review_status"), pp, ("project_id", "procedure_id"))
        # reference set check (research chains.json = proven 22/22)
        for r in results:
            if r["rm_id"] in ref:
                verdict = "correct" if r["ocid"] == ref[r["rm_id"]] else "wrong" if r["ocid"] else "missing"
                r["reference"] = verdict
                await conn.execute("UPDATE link_candidate SET reference_verdict=$3 WHERE left_table='project' "
                                   "AND left_id=$1 AND right_ref=$2", pid[r["rm_id"]], r["ocid"], verdict)
        await upsert_copy(
            conn, "review_item",
            ("key", "kind", "code", "target_table", "target_id", "project_id", "title", "detail", "severity", "created_by"),
            [(f"link|{rm}|{code}", "discrepancy", code, "project", pid[rm], pid[rm], title, detail, sev, "linker:pilot")
             for rm, code, title, sev, detail in issues],
            ("key",), update=["title", "detail", "severity"])
        # CALC project attributes from the linked procedure (only where empty)
        await conn.execute("""
            UPDATE project p SET subsector_main = coalesce(p.subsector_main, pr.subsector_main),
                   subsectors_extra = CASE WHEN p.subsectors_extra = '{}' THEN
                        array(SELECT unnest(pr.subsectors) EXCEPT SELECT pr.subsector_main) ELSE p.subsectors_extra END,
                   works_type = coalesce(p.works_type, pr.work_type),
                   delivery_model = coalesce(p.delivery_model, CASE WHEN pr.design_build THEN 'design_build' ELSE 'build' END)
            FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
            WHERE pp.project_id = p.id AND pp.method <> 'cross_reference_related'""")
        await audit(conn, "system:linker", "link_pilot", "project", None, None,
                    {"linked": sum(1 for r in results if r["ocid"]), "issues": len(issues)})
    linked = sum(1 for r in results if r["ocid"])
    return {"projects": len(projects), "linked": linked, "by_method": _count(r["method"] for r in results),
            "reference": _count(r.get("reference") for r in results), "issues": len(issues),
            "issue_codes": _count(i[1] for i in issues), "candidates": len(cand_rows),
            "per_project": [{k: r.get(k) for k in ("rm_id", "method", "ocid", "score", "reference")} for r in results]}


def _pln(x: float) -> str:
    return f"{x:,.2f}".replace(",", "\u00a0").replace(".", ",") + " zł"


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[str(x)] = out.get(str(x), 0) + 1
    return out
