"""National list on Projekty (GET /api/projects/national). Reads only: the transactional fixtures never touch the main DB."""
from __future__ import annotations

URL = "/api/projects/national"


async def test_page_shape_and_provenance(client):
    r = await client.get(URL, params={"page_size": 20})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] > 10000 and d["page"] == 1 and d["page_size"] == 20 and len(d["items"]) == 20
    for it in d["items"]:
        assert it["id"].startswith("ocds-") and it["href"] == f"/projekty/{it['id']}"
        assert it["status"] in ("completed", "ongoing", "none")
        assert it["value"]["vat_basis"] in (None, "gross", "net", "unknown")
        for k in ("delay_days", "changes"):
            assert it[k]["prov"]["role"] == "calc" and it[k]["prov"]["method"] and it[k]["prov"]["refs"]
        if it["status"] == "ongoing":
            assert it["actual_end_label"] == "w toku" and it["actual_end_on"] is None


async def test_pagination_is_disjoint_and_capped(client):
    a = (await client.get(URL, params={"page_size": 10, "page": 1})).json()
    b = (await client.get(URL, params={"page_size": 10, "page": 2})).json()
    assert not {x["id"] for x in a["items"]} & {x["id"] for x in b["items"]}
    assert a["total"] == b["total"]
    assert (await client.get(URL, params={"page_size": 101})).status_code == 422
    assert (await client.get(URL, params={"page": 0})).status_code == 422
    far = (await client.get(URL, params={"page": 10**6})).json()
    assert far["items"] == [] and far["total"] == a["total"]


async def test_filters(client):
    base = (await client.get(URL)).json()["total"]
    done = (await client.get(URL, params={"status": "completed", "page_size": 100})).json()
    assert 0 < done["total"] < base and all(x["status"] == "completed" for x in done["items"])
    assert all(x["actual_end_on"] for x in done["items"] if x["status"] == "completed" and x["actual_end_on"] is not None)
    wide = (await client.get(URL, params={"woj": "14", "page_size": 100})).json()
    assert 0 < wide["total"] < base and all(x["woj"] == "14" for x in wide["items"])
    yrs = (await client.get(URL, params={"year_from": 2022, "year_to": 2022, "page_size": 100})).json()
    assert yrs["total"] > 0 and all(x["signed_on"] is None or x["signed_on"].startswith("2022") for x in yrs["items"])
    allrel = (await client.get(URL, params={"relevance": "all"})).json()["total"]
    assert allrel > base


async def test_search_title_buyer_gmina(client):
    row = (await client.get(URL, params={"page_size": 50, "status": "completed"})).json()["items"][0]
    for needle in (row["title"].split()[0], row["buyer"].split()[0], row["gmina"] or row["buyer"].split()[0]):
        res = (await client.get(URL, params={"q": needle, "page_size": 100})).json()
        assert res["total"] > 0
    both = (await client.get(URL, params={"q": f"{row['buyer'].split()[0]} zzzzqq"})).json()
    assert both["total"] == 0
    assert (await client.get(URL, params={"q": "%_'; drop table procedure;--"})).status_code == 200


async def test_sorting(client):
    d = (await client.get(URL, params={"sort": "delay", "page_size": 50})).json()["items"]
    vals = [x["delay_days"]["value"] for x in d if x["delay_days"]["value"] is not None]
    assert vals == sorted(vals, reverse=True) and len(vals) == len(d)
    a = (await client.get(URL, params={"sort": "delay_asc", "page_size": 50, "status": "completed"})).json()["items"]
    av = [x["delay_days"]["value"] for x in a if x["delay_days"]["value"] is not None]
    assert av == sorted(av)
    v = (await client.get(URL, params={"sort": "value", "page_size": 50})).json()["items"]
    amounts = [float(x["value"]["amount"]) for x in v if x["value"]["amount"] is not None]
    assert amounts == sorted(amounts, reverse=True)
    s = (await client.get(URL, params={"sort": "signed", "page_size": 50})).json()["items"]
    dates = [x["signed_on"] for x in s if x["signed_on"]]
    assert dates == sorted(dates, reverse=True)
    assert (await client.get(URL, params={"sort": "drop"})).status_code == 422


async def test_row_opens_the_automatic_card(client):
    it = (await client.get(URL, params={"status": "completed", "page_size": 1})).json()["items"][0]
    card = await client.get(f"/api/projects/{it['id']}/card")
    assert card.status_code == 200


async def test_does_not_shadow_project_routes(client):
    assert (await client.get("/api/projects/stats")).status_code == 200
