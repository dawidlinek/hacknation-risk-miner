"""National linking stage (`link_national`): KPO projects -> procedures, CRU agreements -> contracts.

Pure tests for the name/value rules (the collision cases from docs/scrape.md §3.5), then DB-backed checks against
the loaded DB (run after `riskminer load-all`): the stage runs twice (idempotent), keeps expert decisions, writes at
most 3 candidates per record and scores the 10 pilot reference pairs correctly.
"""
import uuid
from datetime import date

import pytest
import pytest_asyncio

from riskminer.db.session import raw_conn
from riskminer.ingest import link_national as L
from riskminer.ingest import pipeline

# ---------------------------------------------------------------------------------------------
# pure rules
# ---------------------------------------------------------------------------------------------

def test_parse_gmina_kinds_and_suffixes():
    assert L.parse_gmina("GMINA MIASTO ELBLĄG  NA PRAWACH POWIATU") == ("elblag", "urban", False)
    assert L.parse_gmina("Gmina Elbląg") == ("elblag", "plain", False)
    assert L.parse_gmina("GMINA MIEJSKA LUBIN")[1] == "urban"
    assert L.parse_gmina("Miasto i Gmina Uzdrowiskowa Muszyna") == ("muszyna", "mixed", False)
    assert L.parse_gmina("Urząd Gminy w Zakrzewie") == ("zakrzewie", "rural", True)
    assert L.parse_gmina("GminaWitonia")[0] == "witonia"
    assert L.parse_gmina("Mircze Commune")[0] == "mircze"
    assert L.parse_gmina("Gminne Przedsiębiorstwo Komunalne Sp. z o.o.") is None
    assert L.parse_gmina("Sycowska Gospodarka Komunalna Sp. z o.o.") is None      # utility is not the gmina


def test_core_match_collisions():
    assert L.core_matches("kamionka", "kamionka")
    assert not L.core_matches("kamionka wielka", "kamionka")                       # Kamionka vs Kamionka Wielka
    assert not L.core_matches("zakrzewo", "zakrzew")                               # Zakrzew vs Zakrzewo
    assert L.core_matches(L.parse_gmina("Gmina Bobowa (woj. Małopolskie, powiat gorlicki)")[0], "bobowa")
    assert L.core_matches(L.parse_gmina("Gmina Lubichowo - Urząd Gminy Lubichowo")[0], "lubichowo")


def test_norm_org_strips_legal_form():
    assert L.norm_org("Wodociągi i Kanalizacja Spółka z ograniczoną odpowiedzialnością") == "wodociagi i kanalizacja"
    assert L.norm_org("WODKAN Sp. z o. o.") == "wodkan"


def _buyer(key, name, prov, city):
    b = L.Buyer(key, key, {name}, {prov}, {L._norm(city)})
    b.norm_names = {L.norm_org(name)}
    b.gmina = [g for g in [L.parse_gmina(name)] if g]
    return b


def _teryt():
    rows = {"2804012": ("Elbląg", "2"), "2861011": ("Elbląg", "1"), "0608053": ("Kamionka", "3"),
            "1207042": ("Kamionka Wielka", "2"), "2401042": ("Bobrowniki", "2"), "0408023": ("Bobrowniki", "3")}
    gmi, by_name, pow_names = {}, {}, {}
    for terc, (name, rodz) in rows.items():
        gmi[terc] = {"terc": terc, "name": name, "rodz": rodz}
        by_name.setdefault(L._norm(name), []).append(terc)
        pow_names.setdefault(terc[:4], set()).add(L._norm(name))
    return L.Teryt(gmi, by_name, pow_names)


@pytest.mark.parametrize("name,teryt,want,not_want", [
    ("Gmina Elbląg", "2804012", "5783105254", "5783051446"),        # rural gmina, not the city
    ("Gmina Kamionka", "0608053", "7141896261", "7343514860"),       # not Kamionka Wielka (other province too)
    ("GMINA BOBROWNIKI", "2401042", "6252446477", "4660344759"),     # śląskie, not kujawsko-pomorskie
])
def test_resolve_beneficiary_collisions(name, teryt, want, not_want):
    buyers = [_buyer("5783105254", "Gmina Elbląg", "PL28", "Elbląg"),
              _buyer("5783051446", "GMINA MIASTO ELBLĄG  NA PRAWACH POWIATU", "PL28", "Elbląg"),
              _buyer("7141896261", "GMINA KAMIONKA", "PL06", "Kamionka"),
              _buyer("7343514860", "Gmina Kamionka Wielka", "PL12", "Kamionka Wielka"),
              _buyer("6252446477", "GMINA BOBROWNIKI", "PL24", "Bobrowniki"),
              _buyer("4660344759", "GMINA BOBROWNIKI", "PL04", "Bobrowniki")]
    by_prov = {}
    for b in buyers:
        for p in b.provinces:
            by_prov.setdefault(p, []).append(b)
    rec = {"buyer_name": name, "teryt": teryt, "province": None, "data": {}}
    res, geo = L.resolve_beneficiary(rec, by_prov, buyers, _teryt())
    nips = [x["nip"] for x in res]
    assert nips and nips[0] == want and not_want not in nips and not geo.get("ambiguous")


def test_value_rules():
    v = L._kpo_value(5350782.65, [{"lot": 0, "value": 5350782.65, "paid": None}], 4350229.80)
    assert v["exact"] and v["score"] == 1.0
    v = L._kpo_value(3373482.44, [{"lot": 0, "value": 3348882.44, "paid": None}], None)
    assert not v["exact"] and v["rel_diff"] < 0.01
    c = L._cru_value(342000.0, 420660.0)                                            # CRU net, BZP gross
    assert c["exact"] and c["basis"] == "CRU netto x 1,23"
    assert L._cru_value(100000.0, 150000.0)["score"] == 0.0
    assert L._kpo_date(date(2025, 5, 1)) == 1.0 and L._kpo_date(date(2023, 2, 1)) < 0.5


# ---------------------------------------------------------------------------------------------
# DB-backed (loaded DB)
# ---------------------------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def first_run():
    return await pipeline._stage("link_national", "link", {}, L.run)


async def _counts(c):
    return {(r["method"], r["decision"]): r["n"] for r in await c.fetch(
        "SELECT method, decision, count(*) n FROM link_candidate WHERE method = ANY($1::text[]) GROUP BY 1, 2",
        [L.KPO_METHOD, L.CRU_METHOD])}


async def test_reference_pairs(first_run):
    ref = first_run["reference"]
    assert ref["pairs"] == 10 and ref["beneficiary_found"] == 10
    assert ref["in_top3"] >= 9 and ref["top1_correct"] >= 8
    assert ref["accepted"] == ref["accepted_correct"], "no wrong automatic accept on the reference pairs"
    async with raw_conn() as c:
        n = await c.fetchval("SELECT count(*) FROM link_candidate WHERE method=$1 AND reference_verdict='correct'",
                             L.KPO_METHOD)
    assert n == ref["in_top3"]
    assert "—" not in first_run["report_pl"] and "·" not in first_run["report_pl"]


async def test_candidate_shape(first_run):
    async with raw_conn() as c:
        bad = await c.fetchval("""SELECT count(*) FROM (SELECT left_id, method, count(*) n, max(rank) r
                                  FROM link_candidate WHERE method = ANY($1::text[]) GROUP BY 1, 2) x
                                  WHERE n > 3 OR r > 3""", [L.KPO_METHOD, L.CRU_METHOD])
        status = await c.fetchval("""SELECT count(*) FROM link_candidate WHERE method = ANY($1::text[])
                                     AND review_status IN ('auto', 'proposed')
                                     AND (decision = 'accept') <> (review_status = 'auto')""", [L.KPO_METHOD, L.CRU_METHOD])
        thr = await c.fetchval("""SELECT count(*) FROM link_candidate WHERE method = ANY($1::text[])
                                  AND review_status IN ('auto', 'proposed') AND NOT (
                                  decision = CASE WHEN score >= 0.9 THEN 'accept' WHEN score >= 0.6 THEN 'review'
                                                  ELSE 'reject' END)""", [L.KPO_METHOD, L.CRU_METHOD])
        sides = await c.fetch("SELECT method, right_table, count(*) FROM link_candidate WHERE method = ANY($1::text[]) "
                              "GROUP BY 1, 2", [L.KPO_METHOD, L.CRU_METHOD])
        # one BZP contract keeps at most one automatically accepted CRU agreement
        dup = await c.fetchval("""SELECT count(*) FROM (SELECT right_id FROM link_candidate WHERE method=$1
                                  AND decision='accept' GROUP BY 1 HAVING count(*) > 1) x""", L.CRU_METHOD)
        agg = await c.fetchval("""SELECT count(*) FROM link_candidate lc JOIN external_record e ON e.id = lc.left_id
                                  WHERE lc.method=$1 AND e.data->'flags' ? 'aggregate_or_programme_entry'""", L.KPO_METHOD)
    assert bad == 0 and status == 0 and thr == 0 and dup == 0 and agg == 0
    assert {(r["method"], r["right_table"]) for r in sides} == {(L.KPO_METHOD, "procedure"), (L.CRU_METHOD, "contract")}
    assert first_run["kpo"]["beneficiary_resolved"] >= 500 and first_run["cru"]["top1_by_decision"].get("accept", 0) > 100


async def test_rerun_idempotent_and_keeps_expert_rows(first_run):
    marker = f"EXPERT-TEST-{uuid.uuid4().hex[:8]}"          # unique: safe if two test sessions overlap
    async with raw_conn() as c:
        before = await _counts(c)
        row = await c.fetchrow("SELECT id, explanation, score FROM link_candidate WHERE method=$1 AND rank = 1 "
                               "AND review_status IN ('auto', 'proposed') ORDER BY id LIMIT 1", L.KPO_METHOD)
        await c.execute("UPDATE link_candidate SET review_status='approved', explanation=$2, score=0.5 WHERE id=$1",
                        row["id"], marker)
    try:
        second = await pipeline._stage("link_national", "link", {}, L.run)
        async with raw_conn() as c:
            after = await _counts(c)
            kept = await c.fetchrow("SELECT review_status, explanation, score FROM link_candidate WHERE id=$1", row["id"])
    finally:   # undo the simulated expert approval (only our own marker)
        async with raw_conn() as c:
            await c.execute("UPDATE link_candidate SET review_status = CASE WHEN decision = 'accept' THEN 'auto' "
                            "ELSE 'proposed' END, explanation=$3, score=$4 WHERE id=$1 AND explanation=$2",
                            row["id"], marker, row["explanation"], row["score"])
    assert second["skipped_expert_rows"] >= 1 and second["stale_removed"] == 0
    assert kept["review_status"] == "approved" and kept["explanation"] == marker
    assert sum(before.values()) == sum(after.values())
    assert second["reference"]["top1_correct"] == first_run["reference"]["top1_correct"]
