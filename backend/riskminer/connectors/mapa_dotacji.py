"""Mapa Dotacji UE (mapadotacji.gov.pl): KPO investment B3.1.1 project list (docs/scrape.md §3.3).

List pages  /projekty/?search-program=29425&search-number-name-activity=30818&page_no=N (10/page)
Detail page /projekty/{id}/

The CSV export is behind reCAPTCHA and is NOT used. The KPO project number is not shown on the site:
pilot KPO rows are linked on beneficiary + exact total value (to the grosz) -> LinkHint score 1.0.
The site shows no project dates and no beneficiary NIP. Gmina TERYT is resolved locally from the
beneficiary name ("Gmina X") + powiat via data/ref/teryt_terc.csv (method recorded per record).

Options: --limit N (projects), --only id1,id2 (detail pages only), --opt workers=3 (the site answers in
~4-10 s, so 3 requests overlap while the per-host limiter keeps starts >= 1 s apart),
--opt list_ttl_hours=24 (re-fetch list pages older than that, for refreshes; default: cache forever).
RODO: e-mail addresses and phone numbers are scrubbed from the description text in parse().
"""
from __future__ import annotations

import csv
import json
import logging
import math
import re
import unicodedata
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from rapidfuzz import fuzz
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, LinkHint, SourceCheck

log = logging.getLogger("riskminer.connectors.mapa_dotacji")

SOURCE = "mapa_dotacji"
DEFAULTS = {"min_interval": 1.0}

BASE = "https://mapadotacji.gov.pl"
LIST_URL = f"{BASE}/projekty/"
PROGRAM = "29425"        # KPO
ACTIVITY = "30818"       # 3.15. B3.1.1 Inwestycje w infrastrukturę kanalizacyjną i wodociągową
DEFAULT_PAGES = 64

_ID_RE = re.compile(r"/projekty/(\d{4,})/")
_PAGE_RE = re.compile(r"page_no=(\d+)")


def list_params(page: int) -> dict[str, str]:
    return {"search-program": PROGRAM, "search-number-name-activity": ACTIVITY, "page_no": str(page)}


def detail_url(pid: str) -> str:
    return f"{BASE}/projekty/{pid}/"


def _ids_in(html: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _ID_RE.finditer(html):
        seen.setdefault(m.group(1), None)
    return list(seen)


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        pages: int | None = None, details: bool = True, workers: int = 3, list_ttl_hours: float | None = None,
        **opts: Any) -> dict:
    """Fetch list pages then detail pages. The site answers slowly (~10 s/page), so up to `workers`
    requests run concurrently; the shared per-host limiter still keeps starts >= 1 s apart."""
    ids: list[str] = []
    n_list = 0
    workers = max(1, int(workers))

    def fetch_list(page: int):
        return page, ctx.fetch(LIST_URL, params=list_params(page), rel_path=f"list/page_{page:03d}.html",
                               note=f"KPO B3.1.1 list page {page}",
                               ttl=timedelta(hours=list_ttl_hours) if list_ttl_hours else "default")

    if only:
        ids = [str(x).strip() for x in only if str(x).strip()]
    else:
        max_pages = pages or DEFAULT_PAGES
        if limit:
            max_pages = min(max_pages, max(1, math.ceil(limit / 10)))
        _, first = fetch_list(1)
        n_list = 1
        results = {1: first}
        if first.ok and not pages and not limit:
            nums = [int(x) for x in _PAGE_RE.findall(first.text())]
            if nums:
                max_pages = max(nums)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for page, r in ex.map(fetch_list, range(2, max_pages + 1)):
                results[page] = r
                n_list += 1
        for page in sorted(results):
            r = results[page]
            if not r.ok:
                log.warning("list page %s: %s", page, r.status)
                continue
            for i in _ids_in(r.text()):
                if i not in ids:
                    ids.append(i)
    if limit:
        ids = ids[:limit]
    n_ok = 0
    if details and ids:
        def fetch_detail(pid: str):
            return ctx.fetch(detail_url(pid), rel_path=f"detail/{pid}.html", note=f"project {pid}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(fetch_detail, ids):
                n_ok += int(r.ok)
    return {"list_pages": n_list, "project_ids": len(ids), "details_ok": n_ok}


# ---------------------------------------------------------------------------------------------
# parse (raw HTML only + local reference files data/ref/teryt_terc.csv, data/ref/pilot_projects.json)

_MONEY_RE = re.compile(r"(\d[\d\s  ]*,\d{2})")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?i)(?:\b(?:tel|telefon|tel\.\s*kom|kom|fax)\b\.?[:\s]*(?:\+?48)?[\s\d()/-]{9,16}\d"
                       r"|\+48[\s-]?\d{2,3}[\s-]?\d{3}[\s-]?\d{2,3}[\s-]?\d{0,2})")
_KPO_RE = re.compile(r"^KPOD\.03\.15-IW\.(\d{2})-(\d{4})/(\d{2})$")


def money(s: str | None) -> Decimal | None:
    if not s:
        return None
    m = _MONEY_RE.search(s)
    if not m:
        return None
    try:
        return Decimal(re.sub(r"[\s  ]", "", m.group(1)).replace(",", "."))
    except InvalidOperation:
        return None


def _txt(node) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip() if node is not None else ""


def _scrub(t: str) -> str:
    """RODO: drop e-mail addresses and phone numbers from free-text descriptions."""
    t = _EMAIL_RE.sub("[e-mail usunięty]", t)
    return _PHONE_RE.sub("[telefon usunięty]", t)


def parse_list_page(html: str) -> list[dict]:
    tree = HTMLParser(html)
    out = []
    for tr in tree.css("table.project-searching-results tbody tr"):
        a = tr.css_first("td.see-all a") or tr.css_first("td.first a")
        if a is None:
            continue
        m = _ID_RE.search(a.attributes.get("href") or "")
        if not m:
            continue
        tds = tr.css("td")
        prices = tr.css("td.price")
        out.append({
            "id": m.group(1),
            "title": _txt(tr.css_first("td.second h3")),
            "beneficiary": _txt(tds[2]) if len(tds) > 2 else "",
            "value_total": money(_txt(prices[0])) if prices else None,
            "value_eu": money(_txt(prices[1])) if len(prices) > 1 else None,
            "voivodeship": _txt(tds[5]) if len(tds) > 5 else "",
            "category": _txt(tr.css_first("td.smaller")),
        })
    return out


def parse_detail(html: str) -> dict:
    tree = HTMLParser(html)
    fields: dict[str, list[str]] = {}
    cont = tree.css_first("div.single-project-info-container")
    label = None
    if cont is not None:
        for n in cont.css("div"):
            cls = n.attributes.get("class") or ""
            if "single-project-info-item-text-up" in cls:
                label = _txt(n).lower()
            elif "single-project-info-item-text-down" in cls and label:
                v = _txt(n)
                if v:
                    fields.setdefault(label, []).append(v)
    desc_node = tree.css_first("div.single-project-desc-container")
    desc = ""
    if desc_node is not None:
        parts = [_txt(p) for p in desc_node.css("p, li")]
        desc = "\n".join(p for p in parts if p) or _txt(desc_node)
    title = _txt(tree.css_first("div.single-project-title h2")) or _txt(tree.css_first("span.breadcrumb_last"))
    cats = [_txt(c) for c in tree.css("div.single-project-cat div.categories *") if _txt(c)]

    def one(k: str) -> str:
        return (fields.get(k) or [""])[0]

    powiaty: list[str] = []
    for v in fields.get("powiat", []):
        powiaty.extend(x.strip() for x in re.split(r",\s*(?=[^()]*(?:\(|$))", v) if x.strip())
    return {
        "title": title,
        "beneficiary": one("nazwa beneficjenta"),
        "value_total": money(one("wartość projektu")),
        "value_eu": money(one("dofinansowanie z ue")),
        "voivodeship": one("województwo"),
        "voivodeships": fields.get("województwo", []),
        "powiaty": powiaty,
        "program": one("program"),
        "measure": one("działanie"),
        "fund": one("fundusz"),
        "perspective": one("perspektywa"),
        "category": ", ".join(dict.fromkeys(cats)),
        "description": _scrub(desc),
        "other_fields": {k: v for k, v in fields.items() if k not in {
            "nazwa beneficjenta", "wartość projektu", "dofinansowanie z ue", "województwo", "powiat", "program",
            "działanie", "fundusz", "perspektywa"}},
    }


# ---- TERYT resolution --------------------------------------------------------------------------
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l")
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


_GMINA_PREFIX = re.compile(
    r"^(gmina\s+i\s+miasto|gmina\s+miasto|gmina\s+miejska|gmina\s+wiejska|gmina|gminy|urz[aą]d\s+gminy|"
    r"miasto\s+i\s+gmina|miasto)\s+",
    re.IGNORECASE)


class Teryt:
    def __init__(self) -> None:
        self.woj: dict[str, str] = {}                     # folded name -> code
        self.pow: dict[tuple[str, str], list[str]] = {}   # (woj, folded powiat name) -> codes
        self.gmi: dict[tuple[str, str], list[dict]] = {}  # (woj, folded gmina name) -> rows
        self.gmi_pl: dict[str, list[dict]] = {}           # folded gmina name -> rows (whole country)
        p = settings().ref_dir / "teryt_terc.csv"
        if not p.exists():
            return
        for r in csv.DictReader(p.open(encoding="utf-8")):
            if r["level"] == "woj":
                self.woj[_fold(r["name"])] = r["woj"]
            elif r["level"] == "pow":
                self.pow.setdefault((r["woj"], _fold(r["name"])), []).append(r["terc"])
            elif r["level"] == "gmi":
                self.gmi.setdefault((r["woj"], _fold(r["name"])), []).append(r)
                self.gmi_pl.setdefault(_fold(r["name"]), []).append(r)

    def resolve(self, voivodeship: str, powiaty: list[str], beneficiary: str) -> dict:
        woj = self.woj.get(_fold(voivodeship))
        if not woj:
            # e.g. "projekt ogólnopolski" on a gmina's project: try a nationally unique gmina name
            m = _GMINA_PREFIX.match((beneficiary or "").strip())
            if m:
                prefix = m.group(1).lower()
                cands = self.gmi_pl.get(_fold(beneficiary.strip()[m.end():]), [])
                if len(cands) > 1:
                    want = {"1"} if ("miejska" in prefix or prefix in ("gmina miasto", "miasto")) else {"2", "3"}
                    cands = [c for c in cands if c["rodz"] in want] or cands
                if len(cands) == 1:
                    return {"woj": cands[0]["woj"], "powiaty": [], "teryt": cands[0]["terc"],
                            "method": "beneficiary_gmina_name_national", "gmina": cands[0]["name"],
                            "kind": cands[0]["kind"], "note": f"voivodeship on site: {voivodeship!r}"}
                if cands:
                    return {"teryt": None, "method": "none", "candidates": [c["terc"] for c in cands]}
            return {"teryt": None, "method": "none"}
        pow_codes: list[str] = []
        for pw in powiaty:
            m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", pw)
            name, pw_woj = (m.group(1), self.woj.get(_fold(m.group(2)), woj)) if m else (pw, woj)
            pow_codes.extend(self.pow.get((pw_woj, _fold(name)), []))
        ben = beneficiary or ""
        out: dict[str, Any] = {"woj": woj, "powiaty": pow_codes}
        m = _GMINA_PREFIX.match(ben.strip())
        if m:
            prefix = m.group(1).lower()
            name = ben.strip()[m.end():]
            cands = self.gmi.get((woj, _fold(name)), [])
            if pow_codes:
                inpow = [c for c in cands if c["terc"][:4] in pow_codes]
                cands = inpow or cands
            if len(cands) > 1:
                want = {"1"} if ("miejska" in prefix or prefix in ("gmina miasto", "miasto")) else {"2", "3"}
                pref = [c for c in cands if c["rodz"] in want]
                cands = pref or cands
            if len(cands) == 1:
                out.update(teryt=cands[0]["terc"], method="beneficiary_gmina_name", gmina=cands[0]["name"],
                           kind=cands[0]["kind"])
                return out
            if cands:
                out["candidates"] = [c["terc"] for c in cands]
        if len(pow_codes) == 1:
            out.update(teryt=pow_codes[0], method="powiat")
        else:
            out.update(teryt=woj, method="voivodeship")
        return out


# ---- pilot linking ---------------------------------------------------------------------------
def _norm_ben(s: str) -> str:
    s = _fold(s)
    s = re.sub(r"\b(gmina|miasto|miejska|wiejska|i|urzad|miejski|gminy|w)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def kpo_number_check(kpo: str | None, woj_teryt: str | None) -> dict:
    if not kpo:
        return {"kpo_number": None, "valid": None}
    m = _KPO_RE.match(kpo.strip())
    if not m:
        return {"kpo_number": kpo, "valid": False, "problem": "does not match KPOD.03.15-IW.nn-nnnn/yy"}
    nn = int(m.group(1))
    exp = 12 + int(woj_teryt) // 2 if woj_teryt and woj_teryt.isdigit() else None
    ok = exp is None or nn == exp
    d = {"kpo_number": kpo, "valid": ok, "iw": nn, "expected_iw": exp, "seq": m.group(2), "call_year": "20" + m.group(3)}
    if not ok:
        d["problem"] = f"IW.{nn} implies voivodeship {(nn - 12) * 2:02d}, buyer is in {woj_teryt}"
    return d


def _pilot_kpo_rows() -> list[dict]:
    p = settings().ref_dir / "pilot_projects.json"
    if not p.exists():
        return []
    rows = []
    for proj in json.loads(p.read_text(encoding="utf-8")):
        ann = proj.get("annotation") or ""
        if not proj.get("kpo_number") and "Wartość przedsięwzięcia" not in ann:
            continue
        mv = re.search(r"Wartość przedsięwzięcia:\s*([\d\s ]+,\d{2})", ann)
        mc = re.search(r"dofinansowanie:\s*([\d\s ]+,\d{2})", ann)
        rows.append({**proj, "_value": money(mv.group(1)) if mv else None, "_cofin": money(mc.group(1)) if mc else None})
    return rows


def parse(store: RawStore) -> Iterable[ExternalRecord | LinkHint | SourceCheck]:
    list_rows: dict[str, dict] = {}
    list_src: dict[str, dict] = {}
    details: dict[str, tuple[dict, dict]] = {}
    for e in store.entries():
        if e.get("status") != "ok" or not e.get("path"):
            continue
        p = store.abs(e["path"])
        if not p.exists():
            continue
        if e.get("url") == LIST_URL:
            for r in parse_list_page(p.read_text(encoding="utf-8", errors="replace")):
                list_rows[r["id"]] = r
                list_src[r["id"]] = {**e, "_page": (e.get("params") or {}).get("page_no")}
        else:
            m = re.match(r"^https://mapadotacji\.gov\.pl/projekty/(\d+)/$", e.get("url", ""))
            if m:
                details[m.group(1)] = (e, parse_detail(p.read_text(encoding="utf-8", errors="replace")))
    ter = Teryt()
    projects: list[ExternalRecord] = []
    for pid in sorted(set(list_rows) | set(details), key=int):
        lr = list_rows.get(pid, {})
        e, d = details.get(pid, (list_src.get(pid), {}))
        if e is None:
            continue
        title = d.get("title") or lr.get("title")
        ben = d.get("beneficiary") or lr.get("beneficiary") or ""
        total = d.get("value_total") if d.get("value_total") is not None else lr.get("value_total")
        eu = d.get("value_eu") if d.get("value_eu") is not None else lr.get("value_eu")
        woj_name = d.get("voivodeship") or lr.get("voivodeship") or ""
        tr = ter.resolve(woj_name, d.get("powiaty") or [], ben)
        flags = []
        if re.search(r"ministerstwo", ben, re.IGNORECASE) or (total is not None and total > Decimal(100000000)):
            flags.append("aggregate_or_programme_entry")
        if not d:
            flags.append("detail_page_missing")
        if lr and d and lr.get("value_total") is not None and lr.get("value_total") != d.get("value_total"):
            flags.append("list_detail_value_mismatch")
        data = {
            "mapa_id": pid, "beneficiary": ben, "value_total": total, "value_eu": eu,
            "cofinancing_rate": float(round(eu / total, 4)) if total and eu is not None else None,
            "voivodeship": woj_name, "powiaty": d.get("powiaty") or [], "program": d.get("program"),
            "measure": d.get("measure"), "fund": d.get("fund"), "perspective": d.get("perspective"),
            "category": d.get("category") or lr.get("category"), "teryt_resolution": tr,
            "list_page": (list_src.get(pid) or {}).get("_page"),
            "list_raw_path": (list_src.get(pid) or {}).get("path"),
            "dates": None, "kpo_number_shown": False, "flags": flags,
            "other_fields": d.get("other_fields") or {},
        }
        rec = ExternalRecord(
            source=SOURCE, kind="kpo_project", external_id=pid, title=title, buyer_name=ben or None,
            teryt=tr.get("teryt"), province=woj_name or None, value_amount=total,
            value_currency="PLN" if total is not None else None, value_vat_basis="unknown",
            url=detail_url(pid), raw_path=e.get("path"), raw_sha256=e.get("sha256"),
            text=d.get("description") or None, data=data)
        projects.append(rec)
        yield rec

    # ---- link the pilot KPO rows on beneficiary + exact value ---------------------------------
    for proj in _pilot_kpo_rows():
        rm = proj["rm_id"]
        kchk = kpo_number_check(proj.get("kpo_number"), proj.get("woj_teryt"))
        val, cof = proj["_value"], proj["_cofin"]
        bnorm = _norm_ben(proj.get("buyer_name") or "")
        hits = []
        for r in projects:
            d = r.data
            exact_v = val is not None and d["value_total"] == val
            exact_c = cof is not None and d["value_eu"] == cof
            bsim = fuzz.token_set_ratio(bnorm, _norm_ben(d["beneficiary"])) if bnorm else 0
            woj_ok = proj.get("woj_teryt") and (d["teryt_resolution"].get("woj") == proj.get("woj_teryt"))
            if not (exact_v or exact_c or (bsim >= 95 and woj_ok)):
                continue
            ben_ok = bsim >= 90 and woj_ok
            if exact_v and ben_ok:
                score, method = 1.0, "exact_value+beneficiary"
            elif exact_v and exact_c:
                score, method = 0.85, "exact_value+exact_cofinancing"
            elif exact_v:
                score, method = 0.6, "exact_value"
            elif exact_c and ben_ok:
                score, method = 0.8, "exact_cofinancing+beneficiary"
            elif ben_ok:
                score, method = 0.3, "beneficiary_only"
            else:
                score, method = 0.2, "exact_cofinancing"
            hits.append((score, method, r, {"pilot_value": val, "mapa_value": d["value_total"],
                                            "pilot_cofinancing": cof, "mapa_cofinancing": d["value_eu"],
                                            "value_exact": exact_v, "cofinancing_exact": exact_c,
                                            "beneficiary_similarity": round(bsim, 1),
                                            "pilot_buyer": proj.get("buyer_name"), "mapa_beneficiary": d["beneficiary"],
                                            "voivodeship_match": bool(woj_ok), "kpo_number_check": kchk}))
        hits.sort(key=lambda h: -h[0])
        strong = [h for h in hits if h[0] >= 0.6]
        for score, method, r, feat in (strong or hits[:5]):
            yield LinkHint(
                source=SOURCE, left_type="project", left_key=rm, right_type="external_record",
                right_key=f"kpo_project:{r.external_id}", method=method, score=score, features=feat,
                explanation=(f"Mapa Dotacji project {r.external_id} '{(r.title or '')[:80]}' "
                             f"({feat['mapa_beneficiary']}, {feat['mapa_value']} zł) vs pilot {rm} "
                             f"({feat['pilot_buyer']}, {feat['pilot_value']} zł): {method}"))
        best = [h for h in hits if h[0] >= 0.8]
        note = f"{len(projects)} KPO B3.1.1 projects scanned; "
        note += (f"best {best[0][1]} -> {best[0][2].external_id}" if best else
                 ("only weak candidates" if hits else "no project with this value/beneficiary"))
        if kchk.get("valid") is False:
            note += f"; KPO number check: {kchk.get('problem')}"
        elif kchk.get("valid"):
            note += f"; KPO number {kchk['kpo_number']} structure ok (IW.{kchk['iw']})"
        yield SourceCheck(
            source=SOURCE, subject_type="project", subject_key=rm,
            query={"value": str(val) if val is not None else None, "cofinancing": str(cof) if cof is not None else None,
                   "beneficiary": proj.get("buyer_name"), "kpo_number": proj.get("kpo_number")},
            n_hits=len(hits), n_relevant=len(best), result="found" if best else "not_found",
            matched_ids=[h[2].external_id for h in best], note=note)

    # ---- per-buyer check: which KPO B3.1.1 projects does each pilot buyer have? --------------
    p = settings().ref_dir / "pilot_projects.json"
    buyers: dict[str, dict] = {}
    if p.exists():
        for proj in json.loads(p.read_text(encoding="utf-8")):
            if proj.get("buyer_nip"):
                buyers.setdefault(proj["buyer_nip"], proj)
    for nip, proj in sorted(buyers.items()):
        bnorm = _norm_ben(proj.get("buyer_name") or "")
        matched = [r.external_id for r in projects
                   if bnorm and r.data["teryt_resolution"].get("woj") in (proj.get("woj_teryt"), None)
                   and fuzz.token_set_ratio(bnorm, _norm_ben(r.data["beneficiary"])) >= 90]
        yield SourceCheck(
            source=SOURCE, subject_type="organization", subject_key=nip,
            query={"beneficiary": proj.get("buyer_name"), "woj": proj.get("woj_teryt"),
                   "filter": "KPO B3.1.1 (search-program=29425, activity=30818)"},
            n_hits=len(matched), n_relevant=len(matched), result="found" if matched else "not_found",
            matched_ids=matched,
            note=(f"{len(matched)} KPO B3.1.1 project(s) with this beneficiary in the voivodeship"
                  if matched else "searched all KPO B3.1.1 projects on Mapa Dotacji: none for this beneficiary"))
