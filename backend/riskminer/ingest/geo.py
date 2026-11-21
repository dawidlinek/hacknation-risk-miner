"""Geography for the monitoring map: region centroids and buyer TERYT codes.

centroids(conn): ref_geo_centroid from data/ref/geo/{woj,pow,gmi}.geojson (PRG, GUGiK; area-weighted polygon centroid).

geo_buyers(conn): organization.teryt for buyers (7 digits = gmina, 4 = powiat, 2 = województwo), never guessed:
  1. gus_bir       GUS BIR record of the buyer (pilot buyers)                                     confidence 1.0
  2. name          'Gmina X' / 'Miasto i Gmina X' / 'Urząd Gminy X': gmina name + type (TERYT rodz) in the
                   buyer's province; unique match only                                             confidence 0.95
  3. name_powiat   'Powiat X' / 'Starostwo Powiatowe w X'                                          confidence 0.9
  4. name_woj      'Województwo X' / marshal office / regional roads authority                    confidence 0.9
  5. city          utilities and other units: the seat city -> its gmina (town part -> its urban-rural
                   gmina); unique match in the province only                                       confidence 0.7
  The method and confidence go to organization.data (teryt_method, teryt_confidence); rows a human set
  (teryt_method = 'expert') are never touched.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from riskminer.config import settings
from riskminer.ingest import ids
from riskminer.ingest.link_national import _COMPAT, _norm, core_matches, parse_gmina

_POWIAT = re.compile(r"^(?:powiat|starostwo powiatowe w|starostwo powiatu|zarzad drog powiatowych w|"
                     r"powiatowy zarzad drog w)\s+(?P<core>.+)$")
_WOJ = re.compile(r"(?:^wojewodztwo|urzad marszalkowski wojewodztwa|zarzad drog wojewodzkich|"
                  r"zarzad melioracji i urzadzen wodnych wojewodztwa)\s+(?P<core>[a-z -]+)")
_WOJ_BY_NAME = {ids.fold(v).replace("-", " "): k for k, v in ids.WOJ.items()}
# adjective forms used in names: 'Mazowiecki Zarząd Dróg Wojewódzkich', 'Wielkopolski Zarząd ...'
_WOJ_ADJ = {"dolnoslaski": "02", "kujawsko pomorski": "04", "lubelski": "06", "lubuski": "08", "lodzki": "10",
            "malopolski": "12", "mazowiecki": "14", "opolski": "16", "podkarpacki": "18", "podlaski": "20",
            "pomorski": "22", "slaski": "24", "swietokrzyski": "26", "warminsko mazurski": "28",
            "wielkopolski": "30", "zachodniopomorski": "32"}


def _centroid(geom: dict) -> tuple[float, float] | None:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    a_sum = cx = cy = 0.0
    for poly in polys:
        ring = poly[0]
        a = x = y = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            f = x0 * y1 - x1 * y0
            a += f
            x += (x0 + x1) * f
            y += (y0 + y1) * f
        if a:
            a_sum += a / 2
            cx += x / 6
            cy += y / 6
    if not a_sum:
        return None
    return cx / a_sum, cy / a_sum


async def centroids(conn) -> dict:
    rows = []
    for level in ("woj", "pow", "gmi"):
        p = Path(settings().ref_dir) / "geo" / f"{level}.geojson"
        if not p.exists():
            continue
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            c = _centroid(f["geometry"])
            if c:
                rows.append((str(f["properties"]["terc"]), level, f["properties"].get("name"), round(c[0], 5), round(c[1], 5)))
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE tmp_cent (terc text, level text, name text, lon float8, lat float8) ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_cent", records=rows)
        await conn.execute("""INSERT INTO ref_geo_centroid (terc, level, name, lon, lat)
                              SELECT terc, level, name, lon, lat FROM tmp_cent
                              ON CONFLICT (terc) DO UPDATE SET level = EXCLUDED.level, name = EXCLUDED.name,
                                lon = EXCLUDED.lon, lat = EXCLUDED.lat""")
    return {"centroids": len(rows)}


async def geo_buyers(conn) -> dict:
    ter = await conn.fetch("SELECT terc, level, name, kind, woj, pow, rodz FROM ref_teryt")
    gmi_by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)    # (woj, name) -> gmina rows
    town_by_name: dict[tuple[str, str], list[str]] = defaultdict(list)    # (woj, town) -> gmina terc7
    pow_by_name: dict[tuple[str, str], list[str]] = defaultdict(list)     # (woj, powiat core) -> terc4
    for r in ter:
        n = _norm(r["name"])
        if r["level"] == "gmi":
            gmi_by_name[(r["woj"], n)].append(dict(r))
            if r["rodz"] in ("1", "3"):                     # urban gmina or urban-rural gmina seated in that town
                town_by_name[(r["woj"], n)].append(r["terc"])
        elif r["level"] == "part" and r["rodz"] == "4":     # 'miasto' part of an urban-rural gmina
            town_by_name[(r["woj"], n)].append(r["terc"][:6] + "3")
        elif r["level"] == "pow":
            pow_by_name[(r["woj"], n)].append(r["terc"])
    bir = {r["buyer_nip"]: r["teryt"] for r in await conn.fetch(
        "SELECT buyer_nip, teryt FROM external_record WHERE kind = 'bir_entity' AND teryt IS NOT NULL AND buyer_nip IS NOT NULL")}
    orgs = await conn.fetch("""SELECT id, nip, name, province, city, teryt, data FROM organization
                               WHERE 'buyer' = ANY(roles) AND coalesce(data->>'teryt_method', '') <> 'expert'""")
    out: list[tuple] = []
    stats: dict[str, int] = defaultdict(int)
    for o in orgs:
        woj = (o["province"] or "")[2:4] if (o["province"] or "").startswith("PL") else None
        terc = method = None
        conf = 0.0
        name_n = _norm(o["name"])
        regional = bool(_POWIAT.match(name_n) or _WOJ.search(name_n)
                        or any(name_n.startswith(a + " zarzad") for a in _WOJ_ADJ))
        if o["nip"] and bir.get(o["nip"]) and not regional:   # BIR = registered seat; not for county/regional units
            terc, method, conf = bir[o["nip"]], "gus_bir", 1.0
        g = parse_gmina(o["name"]) if not terc else None
        if g and woj and not g[2]:                           # not a locative 'Urząd Gminy w X'
            core, kind, _ = g
            toks = core.split()
            cands: list[dict] = []
            for k in range(len(toks), 0, -1):                # 'kartuzy urzad miejski w kartuzach' -> 'kartuzy'
                cand = " ".join(toks[:k])
                if (woj, cand) in gmi_by_name and core_matches(core, cand):
                    cands = [r for r in gmi_by_name[(woj, cand)] if _COMPAT[r["rodz"]].get(kind, 0) > 0]
                    break
            if len(cands) > 1 and kind == "plain":
                # 'Gmina X' next to an urban 'Miasto X' / 'Gmina Miejska X': the plain name is the rural gmina
                rural = [r for r in cands if r["rodz"] == "2"]
                if len(rural) == 1:
                    cands = rural
            if len(cands) > 1:                               # prefer the exact type when several fit
                best = max(_COMPAT[r["rodz"]].get(kind, 0) for r in cands)
                cands = [r for r in cands if _COMPAT[r["rodz"]].get(kind, 0) == best]
            if len(cands) == 1:
                terc, method, conf = cands[0]["terc"], "name", 0.95
            elif len(cands) > 1:
                stats["ambiguous_name"] += 1
        if not terc and woj:
            m = _POWIAT.match(name_n)
            if m:
                core = m.group("core").strip()
                for cand in (core, re.sub(r"(?:ski|cki|dzki)(?:ego|m)?$", "", core)):
                    hits = [t for (w, n), ts in pow_by_name.items() if w == woj and (n == cand or n.startswith(cand))
                            for t in ts] if cand else []
                    if len(set(hits)) == 1:
                        terc, method, conf = hits[0], "name_powiat", 0.9
                        break
        if not terc:
            m = _WOJ.search(name_n)
            code = None
            if m:
                code = _WOJ_BY_NAME.get(m.group("core").strip())
            if not code:
                for adj, c in _WOJ_ADJ.items():
                    if name_n.startswith(adj + " zarzad drog wojewodzkich") or name_n.startswith(adj + " zarzad melioracji"):
                        code = c
                        break
            if code and (not woj or code == woj):
                terc, method, conf = code, "name_woj", 0.9
        if not terc and woj and o["city"] and not g:          # a gmina-type name never falls back to its seat city
            cands = sorted(set(town_by_name.get((woj, _norm(o["city"])), [])))
            if len(cands) == 1:
                terc, method, conf = cands[0], "city", 0.7
            elif len(cands) > 1:
                stats["ambiguous_city"] += 1
        if terc:
            stats[method] += 1
            if terc != o["teryt"] or (o["data"] or {}).get("teryt_method") != method:
                out.append((o["id"], terc, method, conf))
        else:
            stats["unresolved"] += 1
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE tmp_geo (id bigint, teryt text, method text, conf float8) ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_geo", records=out)
        r = await conn.execute("""UPDATE organization o SET teryt = t.teryt,
                                    data = o.data || jsonb_build_object('teryt_method', t.method, 'teryt_confidence', t.conf)
                                  FROM tmp_geo t WHERE o.id = t.id""")
    stats["buyers"] = len(orgs)
    stats["updated"] = int(r.split()[-1])
    return dict(stats)


async def run(conn, rid) -> dict:
    res = await centroids(conn)
    res.update(await geo_buyers(conn))
    return res
