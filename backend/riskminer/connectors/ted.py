"""TED API v3 (api.ted.europa.eu) - docs/scrape.md §2 `ted`, §3.4.

Jobs (`--opt mode=all|buyers|national|xml`):

* buyers   - per pilot buyer NIP: identifier variants (`{nip}`, `NIP {nip}`, `PL{nip}`, 3-3-2-2 and
             3-2-2-3 hyphenations, REGON when found in data/raw/vat_whitelist) on
             `organisation-identifier-buyer` OR `buyer-identifier`, plus a `buyer-name~"..."` query
             restricted to `buyer-country=POL`. -> SourceCheck per buyer (organization) and per pilot
             project, with n_hits / n_relevant (water/sewage CPV or keyword in title).
* national - PL water/sewage corpus: buyer-country=POL + water/sewage CPVs, notice types cn/can/
             can-modif since 2021 (one ITERATION query per publication year).
* xml      - XML of every can-modif notice found (https://ted.europa.eu/en/notice/{pub}/xml, 1 req/s):
             eForms efac:ContractModification (ChangeDescription, ReasonCode add-wss/mod-cir,
             ReasonDescription, ChangedNoticeIdentifier) or legacy F20 (INFO_MODIFICATIONS, ...).

`--since YYYY-MM-DD` (default 2021-01-01) / `--until` bound the national corpus. `--limit N` caps the
number of XML downloads. `--only` filters buyers by NIP / rm_id. Every call goes through ctx.fetch.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, LinkHint, SourceCheck
from riskminer.validators import nip_valid

log = logging.getLogger("riskminer.connectors.ted")

SOURCE = "ted"
DEFAULTS: dict[str, Any] = {"min_interval": 0.7, "timeout": 120.0}   # API ~1.4 req/s (429s seen at 2.5/s); XML: 1 req/s

API = "https://api.ted.europa.eu/v3/notices/search"
XML_URL = "https://ted.europa.eu/en/notice/{pub}/xml"
DETAIL_URL = "https://ted.europa.eu/en/notice/-/detail/{pub}"
PAGE = 250

# docs/research/03_domain_methodology.md §7.2 + scrape brief
NATIONAL_CPV = ("45231300 45232400 45232410 45232411 45232420 45232421 45232423 45232424 45232430 45232440 "
                "45232150 45232151 45232100 45252100 45252120 45252121 45252122 45252126 45252127 45252130 "
                "45252140 45252200 45232130 45232454 45231000 45232000 45252000").split()
WODKAN_CPV = set(NATIONAL_CPV) | set(("45231100 45231110 45232153 45232154 44162500 45255600 45232422 45232460 "
                                      "42996000 45232431 45252210 45262220 45232450 45232451 45232452 45232453 "
                                      "45332000 45332300 45330000 45232152").split())
WODKAN_CPV_STRICT = WODKAN_CPV - {"45231000", "45232000", "45252000", "45330000", "45232452", "45232451", "45232460"}
WODKAN_TITLE = re.compile(r"kanaliz|wodoci[aą]g|ściek|sciek|oczyszczal|uzdatni|przepompown|deszczow|stacj\w* uzdat|"
                          r"wastewater|sewer|sewage|water supply|water treatment", re.I)
NOTICE_TYPES = "cn-standard cn-social cn-desg can-standard can-social can-desg can-modif".split()

FIELDS = ["publication-number", "notice-type", "publication-date", "notice-title", "title-proc", "description-proc",
          "buyer-name", "buyer-city", "buyer-post-code",
          "buyer-country", "organisation-identifier-buyer", "classification-cpv", "main-classification-proc",
          "procedure-identifier", "internal-identifier-proc", "document-url-lot", "estimated-value-proc",
          "estimated-value-cur-proc", "result-value-notice", "result-value-cur-notice", "total-value",
          "total-value-cur", "winner-name", "winner-identifier", "received-submissions-type-val",
          "modification-previous-notice-identifier", "modification-justification", "modification-description",
          "modification-reason-description", "contract-conclusion-date", "notice-version",
          "place-of-performance-subdiv-proc"]

BUYER_FIELDS = FIELDS
# same-name gminas: buyer post-code prefix required for name-only hits (Bobrowniki śl., Zakrzew maz., Zduny wlkp.)
POSTCODE = {"6252446477": ("42-58",), "7962959318": ("26-65",), "6211694095": ("63-76",)}

OCID_RE = re.compile(r"ocds-148610-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
JUSTIFICATION_PL = {"add-wss": "art. 455 ust. 1 pkt 3 (additional works/supplies/services)",
                    "mod-cir": "art. 455 ust. 1 pkt 4 (unforeseeable circumstances)",
                    "mod-rev": "art. 455 ust. 1 pkt 1 (review clause in the contract documents)",
                    "mod-nons": "non-substantial modification (art. 454; dir. 2014/24 art. 72(1)(e))",
                    "mod-minv": "art. 455 ust. 2 (de minimis value)",
                    "mod-repl": "art. 455 ust. 1 pkt 2 (replacement contractor)",
                    "mod-other": "other"}


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def nip_ok(n: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", n or "")) and nip_valid(n)    # shared rule: riskminer/validators.py


def nip_variants(nip: str) -> list[str]:
    return [nip, f"NIP {nip}", f"PL{nip}", f"NIP: {nip}", f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}",
            f"{nip[:3]}-{nip[3:5]}-{nip[5:7]}-{nip[7:]}"]


def pilot_projects() -> list[dict]:
    p = settings().ref_dir / "pilot_projects.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def regons() -> dict[str, str]:
    """NIP -> REGON from the vat_whitelist raw store (if another connector fetched it); best effort."""
    out: dict[str, str] = {}
    d = settings().raw_dir / "vat_whitelist"
    if not d.exists():
        return out
    for f in d.rglob("*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stack = [j]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("nip") and x.get("regon"):
                    out.setdefault(str(x["nip"]), str(x["regon"]))
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return out


def buyer_name_phrase(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.split(r"\s+[–-]\s+|,", name)[0].strip()
    return name


def buyers() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in pilot_projects():
        b = out.setdefault(p["buyer_nip"], {"nip": p["buyer_nip"], "name": p["buyer_name"],
                                             "phrase": buyer_name_phrase(p["buyer_name"]),
                                             "city": p.get("buyer_city"), "rm_ids": [], "projects": []})
        b["rm_ids"].append(p["rm_id"])
        b["projects"].append(p)
    return out


def _q(v: str) -> str:
    return v if re.fullmatch(r"[0-9A-Za-z]+", v) else '"' + v.replace('"', "") + '"'


def id_query(nip: str, regon: str | None) -> str:
    vals = nip_variants(nip) + ([regon] if regon else [])
    lst = " ".join(_q(v) for v in vals)
    return f"(organisation-identifier-buyer IN ({lst}) OR buyer-identifier IN ({lst}))"


def name_query(phrase: str) -> str:
    return f'buyer-name~"{phrase}" AND buyer-country=POL'


def national_query(year_from: str, year_to: str) -> str:
    return (f"buyer-country=POL AND classification-cpv IN ({' '.join(NATIONAL_CPV)}) AND notice-type IN "
            f"({' '.join(NOTICE_TYPES)}) AND publication-date>={year_from} AND publication-date<={year_to}")


def _first(v: Any) -> Any:
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _lang(v: Any, prefer: tuple[str, ...] = ("pol", "eng")) -> Any:
    """Multilingual dict -> preferred language value (str or list)."""
    if isinstance(v, dict):
        for k in prefer:
            if k in v:
                return v[k]
        return next(iter(v.values()), None)
    return v


def _str(v: Any) -> str | None:
    v = _lang(v)
    if isinstance(v, list):
        v = " | ".join(str(x) for x in v if x is not None)
    return str(v) if v not in (None, "") else None


def _list(v: Any) -> list:
    v = _lang(v)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _dec(v: Any) -> Decimal | None:
    v = _first(v)
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _pubdate(s: Any) -> date | None:
    s = _first(s)
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def nips_from(vals: list) -> list[str]:
    out = []
    for v in vals:
        for m in re.finditer(r"(?<!\d)(?:PL)?(\d{3}-?\d{2,3}-?\d{2,3}-?\d{2,3})(?!\d)", str(v)):
            d = re.sub(r"\D", "", m.group(1))
            if nip_ok(d) and d not in out:
                out.append(d)
    return out


def own_title(title: str | None) -> str:
    """eForms titles are 'Polska – <main CPV label> – <title>'; legacy ones 'Polska-City: <CPV label>'."""
    if not title:
        return ""
    parts = title.split(" – ")
    return " – ".join(parts[2:]) if len(parts) >= 3 else ("" if re.match(r"^Polska-[^:]+:", title) else title)


def is_wodkan(cpvs: list[str], title: str | None) -> tuple[bool, bool]:
    c = any(x[:8] in WODKAN_CPV_STRICT for x in cpvs)
    t = bool(WODKAN_TITLE.search(own_title(title)))
    return c, t


# ---------------------------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------------------------
def search_iter(ctx: ScrapeContext, query: str, *, group: str, label: str, fields: list[str] = FIELDS,
                max_pages: int | None = None) -> tuple[list[dict], int | None, str]:
    """ITERATION pagination. -> (notices, total, status ok|partial|error)."""
    notices: list[dict] = []
    total = None
    token = None
    page = 1
    status = "ok"
    while True:
        body: dict[str, Any] = {"query": query, "fields": fields, "limit": PAGE, "paginationMode": "ITERATION"}
        if token:
            body["iterationNextToken"] = token
        r = ctx.fetch(API, method="POST", json_body=body, rel_path=f"search/{group}/{label}/p{page:04d}.json",
                      note=f"ted search {group}/{label} page={page}", accept_status=(200,),
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
        if not r.ok:
            status = "error" if page == 1 else "partial"
            log.warning("ted search %s/%s page %s: %s %s", group, label, page, r.status, (r.content or b"")[:300])
            break
        d = r.json()
        if page == 1:
            total = d.get("totalNoticeCount")
        got = d.get("notices") or []
        notices.extend(got)
        token = d.get("iterationNextToken")
        if not got or not token or (total is not None and len(notices) >= total):
            break
        if max_pages and page >= max_pages:
            status = "partial"
            break
        page += 1
    return notices, total, status


def run(ctx: ScrapeContext, *, since: str | None = None, until: str | None = None, limit: int | None = None,
        only: list[str] | None = None, mode: str = "all", max_pages: int | None = None, **opts: Any) -> dict:
    stats: dict[str, Any] = {"buyers": 0, "buyer_notices": 0, "national_notices": 0, "xml": 0, "xml_failed": 0}
    modif: list[str] = []
    legacy: list[str] = []          # pre-eForms CN/CAN (no title-proc in the API) -> XML for title/description

    if mode in ("all", "buyers"):
        rg = regons()
        for nip, b in buyers().items():
            if only and nip not in only and not any(r in only for r in b["rm_ids"]):
                continue
            stats["buyers"] += 1
            n1, t1, _ = search_iter(ctx, id_query(nip, rg.get(nip)), group="buyers", label=f"{nip}_id",
                                    fields=BUYER_FIELDS)
            n2, t2, _ = search_iter(ctx, name_query(b["phrase"]), group="buyers", label=f"{nip}_name",
                                    fields=BUYER_FIELDS)
            stats["buyer_notices"] += len(n1) + len(n2)
            modif += [n["publication-number"] for n in n1 + n2 if n.get("notice-type") == "can-modif"]
            log.info("ted buyer %s %s: id=%s name=%s", nip, b["phrase"], t1, t2)

    if mode in ("all", "national", "xml"):
        y0 = int((since or "2021-01-01")[:4])
        y1 = int((until or date.today().isoformat())[:4])
        for y in range(y0, y1 + 1):
            f = (since or "2021-01-01").replace("-", "") if y == y0 else f"{y}0101"
            t = (until.replace("-", "") if until and y == y1 else f"{y}1231")
            ns, tot, st = search_iter(ctx, national_query(f, t), group="national", label=f"pl_wodkan_{f}_{t}",
                                      max_pages=max_pages)
            stats["national_notices"] += len(ns)
            modif += [n["publication-number"] for n in ns if n.get("notice-type") == "can-modif"]
            legacy += [n["publication-number"] for n in ns if n.get("notice-type") != "can-modif"
                       and "procedure-identifier" not in n and "title-proc" not in n]
            log.info("ted national %s: total=%s got=%s (%s)", y, tot, len(ns), st)

    if mode in ("all", "xml", "national") and not opts.get("no_xml"):
        todo = list(dict.fromkeys(modif + (legacy if opts.get("xml_scope") in ("legacy", "all") else [])))
        log.info("ted xml todo: %s (can-modif %s, legacy CN/CAN %s)", len(todo), len(set(modif)), len(set(legacy)))
        for i, pub in enumerate(todo):
            if limit and i >= limit:
                break
            r = ctx.fetch(XML_URL.format(pub=pub), rel_path=f"xml/{pub}.xml", min_interval=1.0,
                          note=f"ted notice xml {pub}", check_blocked=False)
            stats["xml"] += 1
            if not r.ok:
                stats["xml_failed"] += 1
            if (i + 1) % 200 == 0:
                log.info("ted xml %s/%s", i + 1, len(todo))
    return stats


# ---------------------------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------------------------
def _t(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    s = re.sub(r"[ \t]+", " ", "".join(el.itertext())).strip()
    return s or None


def _loc(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xml(content: bytes) -> dict:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return {"xml_error": str(e)[:200]}
    out: dict[str, Any] = {}
    if _loc(root.tag) == "TED_EXPORT":
        out["xml_schema"] = "legacy"
        forms = [f for fs in root.iter() if _loc(fs.tag) == "FORM_SECTION" for f in fs]
        f = next((x for x in forms if (x.attrib.get("LG") or "").upper() == "PL"), forms[0] if forms else None)
        mods = []
        if f is not None:
            out["legacy_form"] = _loc(f.tag)

            def first(tag: str, within: ET.Element | None = None) -> ET.Element | None:
                return next((x for x in (within if within is not None else f).iter() if _loc(x.tag) == tag), None)

            oc = first("OBJECT_CONTRACT")
            if oc is not None:
                out["title"] = _t(first("TITLE", oc))
                sd = next((x for x in oc if _loc(x.tag) == "SHORT_DESCR"), None) or first("SHORT_DESCR", oc)
                out["short_description"] = _t(sd)
                ve = first("VAL_ESTIMATED_TOTAL", oc)
                if ve is not None:
                    out["estimated_total"], out["estimated_currency"] = _t(ve), ve.attrib.get("CURRENCY")
                vt = next((x for x in oc if _loc(x.tag) == "VAL_TOTAL"), None)
                if vt is not None:
                    out["total_amount"], out["total_currency"] = _t(vt), vt.attrib.get("CURRENCY")
            acb = first("ADDRESS_CONTRACTING_BODY")
            out["buyer_national_ids"] = [_t(x) for x in (acb.iter() if acb is not None else []) if _loc(x.tag) == "NATIONALID" and _t(x)]
            if acb is not None:
                out["buyer_post_code"] = _t(first("POSTAL_CODE", acb))
                out["buyer_town"] = _t(first("TOWN", acb))
                nuts = first("NUTS", acb)
                out["buyer_nuts"] = nuts.attrib.get("CODE") if nuts is not None else None
            out["contractor_national_ids"] = list(dict.fromkeys(
                _t(n) for a in f.iter() if _loc(a.tag) == "ADDRESS_CONTRACTOR" for n in a.iter()
                if _loc(n.tag) == "NATIONALID" and _t(n)))
            urls = [_t(x) for x in f.iter() if _loc(x.tag) in ("URL_DOCUMENT", "URL_GENERAL", "URL_BUYER", "URL_PARTICIPATION")]
            out["urls"] = [u for u in urls if u]
            ref = first("REFERENCE_NUMBER")
            out["internal_id"] = _t(ref)
            if _loc(f.tag).startswith("F20"):
                info = first("INFO_MODIFICATIONS")
                m: dict[str, Any] = {}
                if info is not None:
                    m["change_description"] = _t(first("SHORT_DESCR", info))
                    for x in info.iter():
                        if _loc(x.tag) == "ADDITIONAL_NEED":
                            m["reason_code"] = "add-wss"
                            m["reason_description"] = _t(x)
                        elif _loc(x.tag) == "UNFORESEEN_CIRCUMSTANCE":
                            m["reason_code"] = "mod-cir"
                            m["reason_description"] = _t(x)
                        elif _loc(x.tag) in ("VAL_TOTAL_BEFORE", "VAL_TOTAL_AFTER"):
                            m[_loc(x.tag).lower()] = _t(x)
                            m["currency"] = x.attrib.get("CURRENCY")
                m["previous_notice"] = _t(first("NOTICE_NUMBER_OJ"))
                m["contract_conclusion_date"] = _t(first("DATE_CONCLUSION_CONTRACT"))
                mods.append(m)
        out["modifications"] = mods
    else:
        out["xml_schema"] = "eforms"
        mods = []
        for cm in root.iter():
            if _loc(cm.tag) != "ContractModification":
                continue
            m: dict[str, Any] = {"changes": [], "reasons": []}
            for x in cm:
                lt = _loc(x.tag)
                if lt == "ChangedNoticeIdentifier":
                    m["previous_notice"] = _t(x)
                elif lt == "ModifiedContractIdentifier":
                    m["modified_contract"] = _t(x)
                elif lt == "Change":
                    for y in x.iter():
                        if _loc(y.tag) == "ChangeDescription" and _t(y):
                            m["changes"].append(_t(y))
                elif lt == "ChangeReason":
                    rc = next((y for y in x.iter() if _loc(y.tag) == "ReasonCode"), None)
                    rd = next((y for y in x.iter() if _loc(y.tag) == "ReasonDescription"), None)
                    m["reasons"].append({"code": _t(rc), "description": _t(rd)})
            m["change_description"] = "\n".join(m["changes"]) or None
            m["reason_code"] = next((r["code"] for r in m["reasons"] if r.get("code")), None)
            m["reason_description"] = "\n".join(r["description"] for r in m["reasons"] if r.get("description")) or None
            mods.append(m)
        out["modifications"] = mods
        tot = next((x for x in root.iter() if _loc(x.tag) == "TotalAmount"), None)
        if tot is not None:
            out["total_amount"] = _t(tot)
            out["total_currency"] = tot.attrib.get("currencyID")
        out["payable_amounts"] = [(_t(x), x.attrib.get("currencyID")) for x in root.iter() if _loc(x.tag) == "PayableAmount"]
        # organisations: id -> CompanyID / name (no contact persons)
        orgs: dict[str, dict] = {}
        for o in root.iter():
            if _loc(o.tag) != "Organization":
                continue
            oid = cid = name = None
            for y in o.iter():
                lt = _loc(y.tag)
                if lt == "ID" and (y.attrib.get("schemeName") == "organization") and not oid:
                    oid = _t(y)
                elif lt == "CompanyID" and not cid:
                    cid = _t(y)
                elif lt == "PartyName" and not name:
                    name = _t(next((z for z in y if _loc(z.tag) == "Name"), None))
            if oid:
                orgs[oid] = {"company_id": cid, "name": name}
        buyer_ids = []
        for cp in root.iter():
            if _loc(cp.tag) == "ContractingParty":
                for y in cp.iter():
                    if _loc(y.tag) == "ID" and _t(y) and _t(y).startswith("ORG-"):
                        buyer_ids.append(_t(y))
        out["buyer_company_ids"] = [orgs[b]["company_id"] for b in dict.fromkeys(buyer_ids) if b in orgs and orgs[b]["company_id"]]
        ten = []
        for tp in root.iter():
            if _loc(tp.tag) == "TenderingParty":
                for y in tp.iter():
                    if _loc(y.tag) == "ID" and _t(y) and _t(y).startswith("ORG-") and _t(y) in orgs:
                        ten.append({"org": _t(y), **orgs[_t(y)]})
        out["tenderers"] = ten
        pp = next((x for x in root if _loc(x.tag) == "ProcurementProject"), None)
        if pp is not None:
            out["title"] = _t(next((x for x in pp if _loc(x.tag) == "Name"), None))
            out["short_description"] = _t(next((x for x in pp if _loc(x.tag) == "Description"), None))
        cf = next((x for x in root.iter() if _loc(x.tag) == "ContractFolderID"), None)
        out["contract_folder_id"] = _t(cf)
        uris = [_t(x) for x in root.iter() if _loc(x.tag) in ("URI", "WebsiteURI")]
        out["urls"] = [u for u in uris if u]
        iid = [x for x in root.iter() if _loc(x.tag) == "ID" and x.attrib.get("schemeName") == "InternalID"]
        out["internal_id"] = _t(iid[0]) if iid else None
    blob = content.decode("utf-8", "replace")
    out["ocids"] = sorted(set(m.lower() for m in OCID_RE.findall(blob)))
    return out


# ---------------------------------------------------------------------------------------------
# parse (raw -> records)
# ---------------------------------------------------------------------------------------------
def parse(store: RawStore) -> Iterable[Any]:
    idx = store.index()
    pages: dict[tuple[str, str], dict[int, dict]] = defaultdict(dict)
    xmls: dict[str, dict] = {}
    for e in sorted(idx.values(), key=lambda e: e.get("fetched_at") or ""):
        if e.get("status") not in ("ok", "empty") or not e.get("path"):
            continue
        p = e["path"]
        if e.get("url") == API:
            m = re.search(r"/search/([^/]+)/([^/]+)/p(\d+)(?:__\w+)?\.json$", p)
            if m:
                pages[(m[1], m[2])][int(m[3])] = e
        elif "/notice/" in (e.get("url") or "") and e["url"].endswith("/xml"):
            pub = e["url"].split("/notice/")[1].split("/")[0]
            xmls[pub] = e

    notices: dict[str, dict] = {}
    src: dict[str, dict] = {}
    groups: dict[str, set] = defaultdict(set)
    by_query: dict[tuple[str, str], list[str]] = {}
    totals: dict[tuple[str, str], int | None] = {}
    first_entry: dict[tuple[str, str], dict] = {}
    for q, pg in pages.items():
        ids: list[str] = []
        for n in sorted(pg):
            e = pg[n]
            try:
                d = json.loads(store.abs(e["path"]).read_bytes())
            except (OSError, ValueError):
                continue
            if n == 1:
                totals[q] = d.get("totalNoticeCount")
                first_entry[q] = e
            for x in d.get("notices") or []:
                pub = x.get("publication-number")
                if not pub:
                    continue
                ids.append(pub)
                x = {k: v for k, v in x.items() if k != "links"}
                if pub not in notices or len(x) > len(notices[pub]):
                    notices[pub] = x
                    src[pub] = e
                groups[pub].add(q[0] if q[0] == "national" else f"buyer:{q[1].split('_')[0]}")
        by_query[q] = ids

    id_hit_nip: dict[str, str] = {}
    for (g, lab), pubs in by_query.items():
        if g == "buyers" and lab.endswith("_id"):
            for pub in pubs:
                id_hit_nip.setdefault(pub, lab.split("_")[0])
    records: dict[str, ExternalRecord] = {}
    for pub, x in notices.items():
        notice_title = _str(x.get("notice-title"))
        xd: dict[str, Any] = {}
        if pub in xmls:
            try:
                xd = parse_xml(store.abs(xmls[pub]["path"]).read_bytes())
            except OSError:
                xd = {}
        proc_title = _str(x.get("title-proc")) or xd.get("title")
        title = proc_title or notice_title
        description = _str(x.get("description-proc")) or xd.get("short_description")
        cpvs = sorted(set(str(c) for c in _list(x.get("classification-cpv"))))
        main_cpv = sorted(set(str(c) for c in _list(x.get("main-classification-proc"))))
        bid_raw = _list(x.get("organisation-identifier-buyer"))
        bnips = nips_from(bid_raw)
        doc_urls = _list(x.get("document-url-lot"))
        ocids = sorted(set(m.lower() for u in doc_urls for m in OCID_RE.findall(str(u))))
        val = cur = None
        for vk, ck in (("result-value-notice", "result-value-cur-notice"), ("total-value", "total-value-cur"),
                       ("estimated-value-proc", "estimated-value-cur-proc")):
            if _dec(x.get(vk)) is not None:
                val, cur = _dec(x.get(vk)), _first(_list(x.get(ck))) if x.get(ck) else None
                vkind = vk
                break
        else:
            vkind = None
        wc, wt = is_wodkan(cpvs + main_cpv, notice_title)
        if proc_title:
            wt = bool(WODKAN_TITLE.search(proc_title))
        cpv_order = [str(c) for c in _list(x.get("classification-cpv"))]
        main_or_first = main_cpv or cpv_order[:1]
        wm = any(c[:8] in WODKAN_CPV_STRICT for c in main_or_first)
        wt = wt and any(c[:2] in ("45", "71") for c in cpvs + main_cpv)
        data: dict[str, Any] = {
            "notice_type": x.get("notice-type"), "notice_title": notice_title, "description": description,
            "cpv": cpvs, "main_cpv": main_cpv,
            "procedure_id": _first(x.get("procedure-identifier")), "internal_id": _str(x.get("internal-identifier-proc")),
            "ocid": ocids[0] if ocids else None, "ocids": ocids, "document_urls": doc_urls[:5],
            "buyer_identifiers_raw": bid_raw, "buyer_nips": bnips, "buyer_city": _str(x.get("buyer-city")),
            "nuts": _list(x.get("place-of-performance-subdiv-proc")), "buyer_post_code": _list(x.get("buyer-post-code"))[:3], "notice_version": _first(x.get("notice-version")),
            "value_field": vkind, "winner_names": _list(x.get("winner-name"))[:10],
            "winner_identifiers": _list(x.get("winner-identifier"))[:10],
            "received_submissions": _list(x.get("received-submissions-type-val"))[:5],
            "contract_conclusion_date": _list(x.get("contract-conclusion-date"))[:5],
            "wodkan_cpv": wc, "wodkan_main_cpv": wm, "wodkan_title": wt, "groups": sorted(groups[pub]),
            "search_raw_path": src[pub].get("path"),
        }
        if x.get("notice-type") == "can-modif":
            data["modification_reason_code"] = _list(x.get("modification-justification"))
            data["modification_description"] = _str(x.get("modification-description"))
            data["modification_reason_description"] = _str(x.get("modification-reason-description"))
            data["previous_notice_id"] = _list(x.get("modification-previous-notice-identifier"))
        raw_e = src[pub]
        if pub in xmls:
            xe = xmls[pub]
            mods = xd.get("modifications") or []
            m0 = mods[0] if mods else {}
            codes = [m.get("reason_code") for m in mods if m.get("reason_code")]
            if codes:
                data["modification_reason_code"] = codes
            if codes:
                data["modification_reason_pzp"] = [JUSTIFICATION_PL.get(c, c) for c in codes]
            if m0.get("reason_description"):
                data["modification_reason_description"] = "\n".join(m["reason_description"] for m in mods if m.get("reason_description"))
            if m0.get("change_description"):
                data["modification_description"] = "\n".join(m["change_description"] for m in mods if m.get("change_description"))
            prev = [m.get("previous_notice") for m in mods if m.get("previous_notice")]
            if prev:
                data["previous_notice_id"] = prev
            if mods:
                data["modified_contract"] = [m.get("modified_contract") for m in mods if m.get("modified_contract")]
            for k in ("val_total_before", "val_total_after"):
                if m0.get(k):
                    data[k] = m0[k]
            data["xml_schema"] = xd.get("xml_schema")
            data["xml_raw_path"] = xe.get("path")
            if xd.get("total_amount"):
                data["xml_total_amount"] = xd["total_amount"]
                data["xml_total_currency"] = xd.get("total_currency")
            data["tenderer_ids"] = [t for t in dict.fromkeys(
                [t.get("company_id") for t in xd.get("tenderers") or []] + (xd.get("contractor_national_ids") or [])) if t]
            if not data["ocid"] and xd.get("ocids"):
                data["ocid"], data["ocids"] = xd["ocids"][0], xd["ocids"]
            if not bnips:
                bnips = nips_from(xd.get("buyer_company_ids") or xd.get("buyer_national_ids") or [])
                data["buyer_nips"] = bnips
            if not data["buyer_post_code"] and xd.get("buyer_post_code"):
                data["buyer_post_code"] = [xd["buyer_post_code"]]
            if xd.get("buyer_nuts"):
                data["buyer_nuts"] = xd["buyer_nuts"]
            if not data["procedure_id"] and xd.get("contract_folder_id"):
                data["procedure_id"] = xd["contract_folder_id"]
            if not data["internal_id"] and xd.get("internal_id"):
                data["internal_id"] = xd["internal_id"]
            if val is None:
                v = xd.get("total_amount") or m0.get("val_total_after")
                if v:
                    try:
                        val, cur, data["value_field"] = Decimal(v), xd.get("total_currency") or m0.get("currency"), "xml_total"
                    except InvalidOperation:
                        pass
        if not bnips and pub in id_hit_nip:
            bnips = [id_hit_nip[pub]]
            data["buyer_nip_basis"] = "matched buyer identifier query (NIP/REGON variant)"
        text_parts = [title, description, data.get("modification_description"), data.get("modification_reason_description")]
        records[pub] = ExternalRecord(
            source=SOURCE, kind="ted_notice", external_id=pub, title=title,
            published_on=_pubdate(x.get("publication-date")), buyer_nip=bnips[0] if bnips else None,
            buyer_name=_str(x.get("buyer-name")), value_amount=val, value_currency=str(cur) if cur else None,
            value_vat_basis="net" if val is not None else None, url=DETAIL_URL.format(pub=pub),
            raw_path=raw_e.get("path"), raw_sha256=raw_e.get("sha256"),
            text="\n\n".join(t for t in text_parts if t) or None, data=data)
    # OCID propagation: can-modif / CAN notices usually lack document-url-lot; reuse the OCID of another
    # notice of the same procedure (procedure-identifier = eForms ContractFolderID).
    proc_ocid: dict[str, str] = {}
    for r in records.values():
        pid = r.data.get("procedure_id")
        if pid and r.data.get("ocid"):
            proc_ocid.setdefault(str(pid), r.data["ocid"])
    for r in records.values():
        pid = r.data.get("procedure_id")
        if not r.data.get("ocid") and pid and str(pid) in proc_ocid:
            r.data["ocid"] = proc_ocid[str(pid)]
            r.data["ocid_basis"] = "procedure-identifier shared with a notice that has the OCID in document-url-lot"
    yield from records.values()

    # ---- per-buyer / per-project checks ------------------------------------------------------
    from rapidfuzz import fuzz
    rg = regons()
    for nip, b in buyers().items():
        qi, qn = ("buyers", f"{nip}_id"), ("buyers", f"{nip}_name")
        if qi not in pages and qn not in pages:
            continue
        id_hits = list(dict.fromkeys(by_query.get(qi, [])))
        name_hits_all = list(dict.fromkeys(by_query.get(qn, [])))
        phrase_l = b["phrase"].lower()
        city_l = (b.get("city") or "").lower()
        name_hits = []
        for pub in name_hits_all:
            r = records.get(pub)
            if not r:
                continue
            bn = (r.buyer_name or "").lower()
            bc = (r.data.get("buyer_city") or "").lower()
            same_nip = nip in (r.data.get("buyer_nips") or [])
            name_ok = bool(re.search(re.escape(phrase_l) + r"(?![\w-])(?!\s+wielk)", bn))
            city_ok = not city_l or city_l.split()[0] in bc or city_l.split()[0] in bn
            pc = [str(v) for v in _list(notices.get(pub, {}).get("buyer-post-code"))]
            if nip in POSTCODE:
                city_ok = city_ok and any(c.startswith(POSTCODE[nip]) for c in pc)
            if same_nip or (name_ok and city_ok):
                name_hits.append(pub)
        hits = list(dict.fromkeys(id_hits + name_hits))
        relevant = [p for p in hits if records.get(p) and (records[p].data["wodkan_main_cpv"] or records[p].data["wodkan_title"])]
        checked = None
        fe = first_entry.get(qi) or first_entry.get(qn)
        if fe:
            checked = datetime.strptime(fe["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
        query = {"api": API, "id_query": id_query(nip, rg.get(nip)), "name_query": name_query(b["phrase"]),
                 "id_total": totals.get(qi), "name_total": totals.get(qn),
                 "relevance": "main CPV (or first CPV if no main) in water/sewage set (45231300, 452321x, 452324x, 452521x, ...) or wod-kan keyword in the notice's own title (works/design CPV 45*/71*)"}
        note = (f"TED searched by identifier variants ({len(id_hits)} notices) and buyer-name~\"{b['phrase']}\" in POL "
                f"({len(name_hits_all)} notices, {len(name_hits)} kept after name+city(+post-code) check); "
                f"{len(hits)} distinct notices of this buyer, {len(relevant)} water/sewage-related")
        if relevant:
            note += ": " + ", ".join(relevant[:15])
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query=query, n_hits=len(hits),
                          n_relevant=len(relevant), result="found" if relevant else "not_found", matched_ids=relevant,
                          note=note, checked_at=checked, raw_path=fe.get("path") if fe else None)
        for pub in hits:
            r = records[pub]
            yield LinkHint(source=SOURCE, left_type="organization", left_key=nip, right_type="external_record",
                           right_key=f"ted_notice:{pub}",
                           method="exact_id" if pub in id_hits else "buyer_name+city",
                           score=1.0 if pub in id_hits else 0.6,
                           features={"buyer_name": r.buyer_name, "buyer_identifiers_raw": r.data.get("buyer_identifiers_raw"),
                                     "wodkan": bool(r.data["wodkan_main_cpv"] or r.data["wodkan_title"])},
                           explanation=("buyer identifier matches NIP variant" if pub in id_hits else
                                        f"buyer name contains {b['phrase']!r} and city matches"))
        for p in b["projects"]:
            ocid = (p.get("tender_id") or "").lower()
            pm = []
            for pub in hits:
                r = records[pub]
                feats: dict[str, Any] = {}
                if ocid and ocid in (r.data.get("ocids") or []):
                    feats["ocid"] = True
                sim = fuzz.token_set_ratio((p["title"] or "").lower(), (r.title or "").lower())
                feats["title_similarity"] = sim
                if feats.get("ocid") or sim >= 85:
                    pm.append(pub)
                    yield LinkHint(source=SOURCE, left_type="project", left_key=p["rm_id"], right_type="external_record",
                                   right_key=f"ted_notice:{pub}", method="exact_id" if feats.get("ocid") else "buyer+title_similarity",
                                   score=1.0 if feats.get("ocid") else 0.7, features=feats,
                                   explanation="TED notice of the same buyer matches the project's OCID/title")
            yield SourceCheck(source=SOURCE, subject_type="project", subject_key=p["rm_id"],
                              query={**query, "project_match": "OCID in document-url-lot, or title token_set_ratio >= 85",
                                     "ocid": p.get("tender_id")},
                              n_hits=len(hits), n_relevant=len(relevant), result="found" if pm else "not_found",
                              matched_ids=pm,
                              note=(("searched, 0 matches for this procurement on TED" if not pm else f"matched {', '.join(pm)}")
                                    + f"; buyer has {len(hits)} TED notices, {len(relevant)} water/sewage-related"
                                    + (" (" + ", ".join(relevant[:10]) + ")" if relevant else "")
                                    + "; dataset procurements are below the EU threshold (BZP only)" * (not pm)),
                              checked_at=checked, raw_path=fe.get("path") if fe else None)
