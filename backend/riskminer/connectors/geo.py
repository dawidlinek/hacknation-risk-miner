"""Administrative boundaries (województwa / powiaty / gminy) -> data/ref/geo/{woj,pow,gmi}.geojson.

Source: the authoritative PRG (Państwowy Rejestr Granic, GUGiK) through its public WFS
  https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries
  typenames ms:A01_Granice_wojewodztw, ms:A02_Granice_powiatow, ms:A03_Granice_gmin,
  GML 3.2 in EPSG:4326 (lat lon axis order), paged with COUNT/STARTINDEX.
Licence: PRG is open data published by GUGiK free of charge and without reuse restrictions
(Prawo geodezyjne i kartograficzne art. 40a ust. 2 pkt 1); attribution "PRG, GUGiK". No GitHub
mirror is used.

The full-resolution GML (~250 MB) stays in data/raw/geo/. parse() builds web-sized GeoJSON with a
pure-Python, topology-preserving simplification (no extra dependencies):
  * coordinates quantised to 1e-5 deg, rings split into arcs at junction vertices (vertex shared by
    >= 3 rings or where the number of rings sharing consecutive vertices changes), each arc simplified
    once (radial pre-thinning + Douglas-Peucker in a canonical direction) and reused by both
    neighbours, so adjacent units keep identical shared borders (no slivers/gaps);
  * the tolerance grows automatically until the file fits its size cap (woj 1 MB, pow 4 MB, gmi 10 MB).
Feature properties: terc (2/4/7-digit TERYT code), name, level (+ kind for gminy, area_ha).
"""
from __future__ import annotations

import itertools
import json
import logging
import xml.etree.ElementTree as ET
from array import array
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.geo")

SOURCE = "geo"
DEFAULTS = {"min_interval": 1.0, "timeout": 300.0}

WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries"
LICENCE_NOTE = ("PRG (GUGiK) WFS AdministrativeBoundaries; open data, free of charge and without reuse "
                "restrictions (Prawo geodezyjne i kartograficzne art. 40a ust. 2 pkt 1); attribution 'PRG, GUGiK'")
LAYERS: dict[str, dict[str, Any]] = {
    "woj": {"typename": "ms:A01_Granice_wojewodztw", "count": 16, "tol": 0.0015, "cap": 1_000_000, "dec": 4},
    "pow": {"typename": "ms:A02_Granice_powiatow", "count": 50, "tol": 0.0015, "cap": 4_000_000, "dec": 4},
    "gmi": {"typename": "ms:A03_Granice_gmin", "count": 100, "tol": 0.001, "cap": 10_000_000, "dec": 4},
}
RODZ = {"1": "gmina miejska", "2": "gmina wiejska", "3": "gmina miejsko-wiejska", "4": "miasto",
        "5": "obszar wiejski", "8": "dzielnica", "9": "delegatura"}
NS = {"gml": "http://www.opengis.net/gml/3.2", "ms": "http://mapserver.gis.umn.edu/mapserver",
      "wfs": "http://www.opengis.net/wfs/2.0"}
Q = 100_000          # quantisation: 1e-5 deg
KEYM = 10 ** 8       # packed vertex key = x * KEYM + y   (x = lon*Q, y = lat*Q)


def geo_dir() -> Path:
    return settings().ref_dir / "geo"


def wfs_params(typename: str, count: int, start: int) -> dict[str, str]:
    return {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
            "COUNT": str(count), "STARTINDEX": str(start), "SRSNAME": "urn:ogc:def:crs:EPSG::4326"}


def _returned(content: bytes) -> int:
    head = content[:4000].decode("utf-8", "replace")
    i = head.find('numberReturned="')
    if i < 0:
        return -1
    j = head.find('"', i + 16)
    try:
        return int(head[i + 16:j])
    except ValueError:
        return -1


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        build: bool = True, **opts: Any) -> dict:
    """only = subset of levels (woj,pow,gmi). limit = max pages per level (smoke tests)."""
    levels = [x for x in (only or list(LAYERS)) if x in LAYERS]
    out: dict[str, Any] = {}
    for lvl in levels:
        cfg = LAYERS[lvl]
        start, pages, feats = 0, 0, 0
        while True:
            r = ctx.fetch(WFS, params=wfs_params(cfg["typename"], cfg["count"], start),
                          rel_path=f"{lvl}/{cfg['typename'].split(':')[1]}_{start:05d}.gml", ext=".gml",
                          note=f"{lvl} start={start}; {LICENCE_NOTE}")
            pages += 1
            if not r.ok:
                log.warning("%s page start=%s: %s", lvl, start, r.status)
                break
            n = _returned(r.content or b"")
            feats += max(n, 0)
            if n < cfg["count"] or (limit and pages >= limit):
                break
            start += cfg["count"]
        out[lvl] = {"pages": pages, "features": feats}
    if build:
        out["built"] = build_all(ctx.store, levels)
    return out


# ---- GML -> rings ---------------------------------------------------------------------------
def _poslist(text: str) -> array:
    vals = text.split()
    ring = array("q")
    last = None
    for i in range(0, len(vals) - 1, 2):
        lat = float(vals[i])
        lon = float(vals[i + 1])
        k = round(lon * Q) * KEYM + round(lat * Q)
        if k != last:
            ring.append(k)
            last = k
    if len(ring) > 1 and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _features_from_gml(path: Path, typename: str) -> Iterable[dict]:
    tag = "{{{}}}{}".format(NS["ms"], typename.split(":")[1])
    for _, el in ET.iterparse(str(path), events=("end",)):
        if el.tag != tag:
            continue
        props = {}
        for child in el:
            name = child.tag.split("}")[1]
            if name not in ("msGeometry", "boundedBy"):
                props[name] = (child.text or "").strip()
        polys = []
        for poly in el.iter("{{{}}}Polygon".format(NS["gml"])):
            rings = []
            ext = poly.find("gml:exterior/gml:LinearRing/gml:posList", NS)
            if ext is None or not ext.text:
                continue
            rings.append(_poslist(ext.text))
            for inner in poly.findall("gml:interior/gml:LinearRing/gml:posList", NS):
                if inner.text:
                    rings.append(_poslist(inner.text))
            polys.append(rings)
        el.clear()
        yield {"props": props, "polys": polys}


def load_level(store: RawStore, lvl: str) -> tuple[list[dict], list[dict]]:
    """Features (current versions, deduped by TERYT code) from the latest ok page per STARTINDEX."""
    cfg = LAYERS[lvl]
    latest: dict[str, dict] = {}
    for e in store.entries():
        if e.get("status") != "ok" or not e.get("path") or e.get("url") != WFS:
            continue
        p = e.get("params") or {}
        if p.get("TYPENAMES") != cfg["typename"]:
            continue
        latest[p.get("STARTINDEX", "0")] = e
    feats: list[dict] = []
    seen: set[str] = set()
    used: list[dict] = []
    for start in sorted(latest, key=int):
        e = latest[start]
        path = store.abs(e["path"])
        if not path.exists():
            continue
        used.append(e)
        for f in _features_from_gml(path, cfg["typename"]):
            pr = f["props"]
            code = pr.get("JPT_KOD_JE", "")
            if not code or pr.get("WERSJA_DO") or code in seen:
                continue
            seen.add(code)
            f["raw"] = e
            feats.append(f)
    return feats, used


# ---- topology-preserving simplification ------------------------------------------------------
def _xy(k: int) -> tuple[int, int]:
    return k // KEYM, k % KEYM


def _dp(pts: list[tuple[int, int]], tol: float) -> list[tuple[int, int]]:
    n = len(pts)
    if n <= 2:
        return pts
    # radial pre-thinning
    t2 = (tol / 2) ** 2
    thin = [pts[0]]
    for p in pts[1:-1]:
        q = thin[-1]
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= t2:
            thin.append(p)
    thin.append(pts[-1])
    pts = thin
    n = len(pts)
    if n <= 2:
        return pts
    keep = bytearray(n)
    keep[0] = keep[-1] = 1
    stack = [(0, n - 1)]
    tolsq = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                c = (px - ax) * dy - (py - ay) * dx
                d = c * c / L
            if d > best:
                best, bi = d, i
        if best > tolsq:
            keep[bi] = 1
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for p, k in zip(pts, keep, strict=False) if k]


class Simplifier:
    def __init__(self, feats: list[dict]):
        self.feats = feats
        cnt: Counter[int] = Counter()
        for f in feats:
            for poly in f["polys"]:
                for ring in poly:
                    cnt.update(set(ring))
        nodes: set[int] = set()
        for f in feats:
            for poly in f["polys"]:
                for ring in poly:
                    r = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
                    m = len(r)
                    for i in range(m):
                        v = r[i]
                        c = cnt[v]
                        if c >= 3 or cnt[r[i - 1]] != c or cnt[r[(i + 1) % m]] != c:
                            nodes.add(v)
        self.nodes = nodes
        log.info("simplifier: %d features, %d unique vertices, %d junctions", len(feats), len(cnt), len(nodes))
        del cnt

    def _arcs(self, ring: array) -> list[list[int]]:
        r = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
        m = len(r)
        if m < 3:
            return []
        idx = [i for i, v in enumerate(r) if v in self.nodes]
        if not idx:
            i0 = min(range(m), key=r.__getitem__)
            x0, y0 = _xy(r[i0])
            far = max(range(m), key=lambda i: (_xy(r[i])[0] - x0) ** 2 + (_xy(r[i])[1] - y0) ** 2)
            idx = sorted({i0, far})
        if len(idx) == 1:
            i0 = idx[0]
            x0, y0 = _xy(r[i0])
            far = max(range(m), key=lambda i: (_xy(r[i])[0] - x0) ** 2 + (_xy(r[i])[1] - y0) ** 2)
            idx = sorted({i0, far})
        arcs = []
        for j, a in enumerate(idx):
            b = idx[(j + 1) % len(idx)]
            arc = r[a:b + 1] if b > a else r[a:] + r[:b + 1]
            arcs.append(arc)
        return arcs

    def simplify(self, tol_deg: float, dec: int) -> list[dict]:
        tol = tol_deg * Q
        cache: dict[tuple, list[tuple[int, int]]] = {}

        def arc_simpl(arc: list[int]) -> list[tuple[int, int]]:
            rev = arc[0] > arc[-1] or (arc[0] == arc[-1] and len(arc) > 2 and arc[1] > arc[-2])
            a = arc[::-1] if rev else arc
            key = (a[0], a[1] if len(a) > 1 else 0, a[-2] if len(a) > 1 else 0, a[-1], len(a))
            s = cache.get(key)
            if s is None:
                s = _dp([_xy(k) for k in a], tol)
                cache[key] = s
            return s[::-1] if rev else s

        out = []
        for f in self.feats:
            polys_out = []
            for pi, poly in enumerate(f["polys"]):
                rings_out = []
                for ri, ring in enumerate(poly):
                    pts: list[tuple[int, int]] = []
                    for arc in self._arcs(ring):
                        s = arc_simpl(arc)
                        pts.extend(s if not pts else s[1:])
                    coords = []
                    for x, y in pts:
                        c = [round(x / Q, dec), round(y / Q, dec)]
                        if not coords or coords[-1] != c:
                            coords.append(c)
                    if coords and coords[0] != coords[-1]:
                        coords.append(coords[0])
                    if len(coords) < 4:
                        if ri == 0 and pi == 0 and not polys_out:
                            # never lose a whole unit: keep a coarse copy of the original ring
                            raw = [[round(_xy(k)[0] / Q, dec), round(_xy(k)[1] / Q, dec)] for k in ring]
                            coords = [c for i, c in enumerate(raw) if i == 0 or c != raw[i - 1]]
                            if len(coords) < 4:
                                continue
                        else:
                            continue
                    rings_out.append(coords)
                if rings_out:
                    polys_out.append(rings_out)
            out.append({"feat": f, "polys": polys_out})
        return out


def _ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(ring):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if a == 0:
        return 0.0, ring[0][0], ring[0][1]
    return a / 2, cx / (3 * a), cy / (3 * a)


def _props(lvl: str, pr: dict) -> dict:
    code = pr.get("JPT_KOD_JE", "")
    d = {"terc": code, "name": pr.get("JPT_NAZWA_", ""), "level": lvl}
    if lvl == "gmi" and len(code) == 7:
        d["kind"] = RODZ.get(code[6], "")
    try:
        d["area_ha"] = int(float(pr.get("JPT_POWIER") or 0))
    except ValueError:
        pass
    return d


def _geometry(polys: list) -> dict:
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def build_level(store: RawStore, lvl: str) -> dict:
    cfg = LAYERS[lvl]
    feats, used = load_level(store, lvl)
    if not feats:
        return {"features": 0}
    simp = Simplifier(feats)
    tol = cfg["tol"]
    for _ in range(8):
        res = simp.simplify(tol, cfg["dec"])
        fc = {"type": "FeatureCollection",
              "name": f"PRG {lvl}",
              "attribution": "PRG, GUGiK (open data); simplified for web by Risk Miner",
              "simplification": {"tolerance_deg": tol, "decimals": cfg["dec"], "method": "arc DP, topology-preserving"},
              "features": [{"type": "Feature", "properties": _props(lvl, r["feat"]["props"]),
                            "geometry": _geometry(r["polys"])} for r in res if r["polys"]]}
        body = json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) <= cfg["cap"]:
            break
        log.info("%s: %d bytes > cap %d at tol %.5f, increasing", lvl, len(body), cfg["cap"], tol)
        tol *= 1.4
    p = geo_dir() / f"{lvl}.geojson"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    meta = []
    for r in res:
        if not r["polys"]:
            continue
        best = max((_ring_area_centroid(poly[0]) for poly in r["polys"]), key=lambda t: abs(t[0]))
        xs = [c[0] for poly in r["polys"] for c in poly[0]]
        ys = [c[1] for poly in r["polys"] for c in poly[0]]
        meta.append({"props": r["feat"]["props"], "raw": r["feat"]["raw"],
                     "centroid": [round(best[1], 5), round(best[2], 5)],
                     "bbox": [min(xs), min(ys), max(xs), max(ys)],
                     "n_vertices": sum(len(ring) for poly in r["polys"] for ring in poly)})
    return {"features": len(fc["features"]), "bytes": len(body), "tolerance_deg": round(tol, 6),
            "path": str(p), "pages": len(used), "meta": meta}


def build_all(store: RawStore, levels: Iterable[str] | None = None) -> dict:
    out = {}
    for lvl in levels or LAYERS:
        r = build_level(store, lvl)
        r.pop("meta", None)
        out[lvl] = r
    return out


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    for lvl in LAYERS:
        r = build_level(store, lvl)
        log.info("geo %s: %s features, %s bytes, tol %s", lvl, r.get("features"), r.get("bytes"),
                 r.get("tolerance_deg"))
        for m in r.get("meta", []):
            pr = m["props"]
            code = pr.get("JPT_KOD_JE", "")
            e = m["raw"]
            yield ExternalRecord(
                source=SOURCE, kind="admin_boundary", external_id=code, title=pr.get("JPT_NAZWA_"),
                teryt=code, province=code[:2] or None, url=f"{WFS}?SERVICE=WFS&REQUEST=GetFeature&TYPENAMES="
                f"{LAYERS[lvl]['typename']}", raw_path=e.get("path"), raw_sha256=e.get("sha256"),
                data={**_props(lvl, pr), "centroid": m["centroid"], "bbox": m["bbox"],
                      "n_vertices_simplified": m["n_vertices"], "geojson": f"data/ref/geo/{lvl}.geojson",
                      "prg_jpt_id": pr.get("JPT_ID"), "prg_version": pr.get("WERSJA_OD"),
                      "prg_regon": pr.get("REGON"), "licence": "PRG GUGiK open data"})
