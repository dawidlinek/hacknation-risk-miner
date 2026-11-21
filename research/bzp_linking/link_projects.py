"""Risk Miner - link the 22 dataset rows to BZP notice chains via the e-Zamowienia API.

Usage:
    python3 link_projects.py [--base https://bzp.cytr.us] [--dataset 05_dane_projekty.txt]

Only the public endpoint GET /mo-board/api/v1/notice is used (same on the mirror and
production). The API cannot filter by NIP or tenderId, so we pull an organisation's
notices by name fragment and filter client-side.
Outputs (next to this script): matrix.csv, matrix.md, chains.json, cache/*.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from html2text import html2text  # noqa: E402

API_PATH = "/mo-board/api/v1/notice"
MAIN_TYPES = ("ContractNotice", "TenderResultNotice", "AgreementUpdateNotice", "ContractPerformingNotice")
PAGE_SIZE = 100  # production max from 11.01.2027 (now 500)
WODKAN_CPV = ("45231", "45232", "45252", "45247", "45330", "45332", "4523")

# --------------------------------------------------------------------------- API


class Api:
    def __init__(self, base: str, delay: float = 0.0):
        self.base = base.rstrip("/")
        self.delay = delay
        self.cache = HERE / "cache"
        self.cache.mkdir(exist_ok=True)
        self.calls = 0

    def get(self, **params) -> list[dict]:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}{API_PATH}?{q}"
        key = self.cache / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if key.exists():
            return json.loads(key.read_text(encoding="utf-8"))
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "risk-miner-research/0.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code == 403:  # production rate limit (30 req/min/IP)
                    time.sleep(20 * (attempt + 1))
                    continue
                if e.code == 400:
                    raise
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"failed: {url}")
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        key.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def get_all(self, **params) -> list[dict]:
        """Follow SearchAfter=<objectId of last item> until a short page."""
        out, after = [], None
        while True:
            page = self.get(PageSize=PAGE_SIZE, SearchAfter=after, **params)
            out.extend(page)
            if len(page) < PAGE_SIZE:
                return out
            after = page[-1]["objectId"]


# --------------------------------------------------------------------------- helpers

BZP_RE = re.compile(r"(\d{4})\s*[/\-_ ]\s*BZP\s*[/\-_ ]?\s*0*(\d{1,8})(?:\s*[/\-_ ]\s*(\d{1,2}))?", re.I)
BZP_RE_ALT = re.compile(r"BZP\s*[/\-_ ]?\s*(\d{4})\s*[/\-_ ]\s*0*(\d{1,8})(?:\s*[/\-_ ]\s*(\d{1,2}))?", re.I)


def norm_bzp(s: str) -> tuple[str, str | None] | None:
    """'2022/BZP 00058537/01' -> ('2022/BZP 00058537', '01'). Accepts sloppy variants."""
    if not s:
        return None
    s = s.replace("–", "-").replace("\xa0", " ")
    m = BZP_RE.search(s) or BZP_RE_ALT.search(s)
    if not m:
        return None
    year, num, ver = m.groups()
    return f"{year}/BZP {int(num):08d}", (f"{int(ver):02d}" if ver else None)


def digits(s) -> str:
    return re.sub(r"\D", "", s or "")


def nip_valid(n: str) -> bool:
    n = digits(n)
    if len(n) != 10:
        return False
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    return sum(int(a) * b for a, b in zip(n, w)) % 11 == int(n[9])


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("ł", "l").replace("Ł", "L"))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


STOP = set("w i oraz na z do dla od po we ze ul gmina gminy gminie miejscowosci miejscowosc m budowa przebudowa "
           "rozbudowa sieci siec terenie zakresie wraz formule zaprojektuj wybuduj etap czesc".split())


def tokens(s: str) -> set[str]:
    return {t[:6] for t in re.findall(r"[a-z0-9]{3,}", fold(s)) if t not in STOP}


def money(s):
    if not s:
        return None
    m = re.search(r"-?\d[\d\s.]*(?:,\d{1,2})?", s.replace("\xa0", " "))
    if not m:
        return None
    t = m.group(0).replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})|(\d{2})\.(\d{2})\.(\d{4})")


DUR_RE = re.compile(r"(\d+)\s*(dni|dzie|tydzie|tygodn|miesi|lat|rok)", re.I)


def planned_end(period, start):
    """'do 2025-08-18' -> date; '13 miesiące' + contract date -> computed date (marked '~')."""
    d = first_date(period)
    if d:
        return d
    m = DUR_RE.search(period or "")
    if not (m and start and first_date(start)):
        return None
    import datetime as dt
    y, mo, dd = map(int, first_date(start).split("-"))
    base = dt.date(y, mo, dd)
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("dni") or unit.startswith("dzie"):
        r = base + dt.timedelta(days=n)
    elif unit.startswith("tyd") or unit.startswith("tyg"):
        r = base + dt.timedelta(weeks=n)
    else:
        months = n * (12 if unit.startswith(("lat", "rok")) else 1)
        y2, m2 = divmod(base.month - 1 + months, 12)
        import calendar
        r = dt.date(base.year + y2, m2 + 1, min(base.day, calendar.monthrange(base.year + y2, m2 + 1)[1]))
    return "~" + r.isoformat()


def first_date(s):
    m = DATE_RE.search(s or "")
    if not m:
        return None
    return m.group(1) or f"{m.group(4)}-{m.group(3)}-{m.group(2)}"


CODE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\)\s*(.*)$")


FOOTER = re.compile(r"^\s*\d{4}-\d{2}-\d{2} Biuletyn Zamówień Publicznych")


def parse_fields(text: str) -> list[list[str]]:
    out, cur = [], None
    for line in text.split("\n"):
        if FOOTER.match(line):
            break
        m = CODE.match(line)
        if m and not re.match(r"^\s*\d{8}-\d", line):
            rest = m.group(2)
            lab, _, val = rest.partition(":")
            cur = [m.group(1), lab.strip(), val.strip()]
            out.append(cur)
        elif cur is not None and not re.match(r"^\s*(SEKCJA|Część \d+$)", line.strip()):
            cur[2] = (cur[2] + "\n" + line.strip()).strip()
    return out


def fget(fl, code, contains=None):
    for c, lab, v in fl:
        if c == code and (contains is None or contains in lab):
            return v
    return None


def fall(fl, code):
    return [v for c, lab, v in fl if c == code]


def split_parts(text: str, marker: str) -> dict[int, str]:
    """Split notice text into {part_no: text}; part 0 = whole text if no parts."""
    pieces = re.split(marker, text)
    if len(pieces) == 1:
        return {0: text}
    parts = {}
    for i in range(1, len(pieces), 2):
        parts[int(pieces[i])] = pieces[i + 1]
    return parts


# --------------------------------------------------------------------------- notice extractors


def notice_url(n):
    return f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{n['objectId']}"


def ex_contract_notice(n):
    t = html2text(n.get("htmlBody") or "")
    fl = parse_fields(t)
    sec4 = t.split("SEKCJA IV", 1)[-1].split("SEKCJA V", 1)[0]
    parts = split_parts(sec4, r"\nCzęść (\d+)\n")
    pinfo = {}
    for p, txt in parts.items():
        pf = parse_fields(txt)
        pinfo[p] = {
            "description": (fget(pf, "4.2.2") or "")[:400],
            "period": fget(pf, "4.2.10"),
            "cpv_main": fget(pf, "4.2.6"),
        }
    return {
        "number": n["noticeNumber"],
        "date": n["publicationDate"][:10],
        "title": n["orderObject"],
        "procedure_mode": fget(fl, "2.16") or fget(fl, "2.15"),
        "parts_count": int(fget(fl, "4.1.9") or 0) or None,
        "submission_deadline": fget(fl, "8.1"),
        "eu_funded": fget(fl, "2.14"),
        "parts": pinfo,
    }


def ex_result_notice(n):
    t = html2text(n.get("htmlBody") or "")
    fl = parse_fields(t)
    head, _, rest = t.partition("SEKCJA V")
    sec4 = head.split("SEKCJA IV", 1)[-1]
    part_vals = {p: money(fget(parse_fields(x), "4.5.5")) for p, x in split_parts(sec4, r"\nCzęść (\d+)\n").items()}
    parts = split_parts("SEKCJA V" + rest, r"SEKCJA V ZAKOŃCZENIE POSTĘPOWANIA \(dla części (\d+)\)")
    out = {}
    for p, txt in parts.items():
        pf = parse_fields(txt)
        out[p] = {
            "outcome": (fget(pf, "5.1") or "")[:120],
            "cancel_reason": (fget(pf, "5.1.1") or fget(pf, "5.2") or "")[:300] if "unieważn" in (fget(pf, "5.1") or "") else None,
            "offers": fget(pf, "6.1"),
            "price_min": money(fget(pf, "6.2")),
            "price_max": money(fget(pf, "6.3")),
            "price_awarded": money(fget(pf, "6.4")),
            "contractor": fget(pf, "7.3.1"),
            "contractor_id": fget(pf, "7.3.2"),
            "contract_date": fget(pf, "8.1"),
            "contract_value": money(fget(pf, "8.2")),
            "period": (fget(pf, "8.3") or "").strip(),
            "part_estimate_net": part_vals.get(p),
        }
    return {
        "number": n["noticeNumber"],
        "date": n["publicationDate"][:10],
        "estimate_net": money(fget(fl, "4.3")),
        "cn_ref": fget(fl, "2.14"),
        "eu_funded": fget(fl, "2.11"),
        "procedureResult": n.get("procedureResult"),
        "parts": out,
    }


def ex_change_notice(n):
    t = html2text(n.get("htmlBody") or "")
    fl = parse_fields(t)
    return {
        "number": n["noticeNumber"],
        "date": n["publicationDate"][:10],
        "cn_ref": fget(fl, "3.1.1"),
        "trn_ref": fget(fl, "4.5"),
        "contract_title": fget(fl, "3.6"),
        "contractor": fget(fl, "4.3.1"),
        "contract_value": money(fget(fl, "4.4")),
        "period": fget(fl, "4.2"),
        "change_date": fget(fl, "5.1"),
        "legal_basis": (fget(fl, "5.2") or "").strip(),
        "reason": (fget(fl, "5.3") or "")[:600],
        "description": (fget(fl, "5.4") or "")[:600],
        "change_value": money(fget(fl, "5.5.1")),
        "price_increase": fget(fl, "5.5.3"),
    }


def ex_performance_notice(n):
    t = html2text(n.get("htmlBody") or "")
    fl = parse_fields(t)
    changes = []
    sec = t.split("5.4.1.)", 1)[-1] if "5.4.1.)" in t else ""
    for blk in re.split(r"5\.4\.2\.\) Numer zmiany:", sec)[1:]:
        bf = parse_fields("5.4.2.) Numer zmiany:" + blk)
        changes.append({
            "no": fget(bf, "5.4.2"),
            "legal_basis": (fget(bf, "5.4.3") or "").strip(),
            "reason": (fget(bf, "5.4.4") or "")[:400],
            "after_change": (fget(bf, "5.4.5") or "")[:400],
            "value": money(fget(bf, "5.4.6")),
            "price_increase": fget(bf, "5.4.8"),
        })
    return {
        "number": n["noticeNumber"],
        "date": n["publicationDate"][:10],
        "cn_ref": fget(fl, "3.2.1"),
        "trn_ref": fget(fl, "4.5"),
        "contract_date": fget(fl, "4.1"),
        "period": (fget(fl, "4.2") or "").strip(),
        "contractor": fget(fl, "4.3.1"),
        "contractor_id": fget(fl, "4.3.2"),
        "contract_value": money(fget(fl, "4.4")),
        "executed": fget(fl, "5.1"),
        "end_date": fget(fl, "5.2"),
        "on_time": fget(fl, "5.3"),
        "changes_count": fget(fl, "5.4.1"),
        "changes": changes,
        "paid_total": money(fget(fl, "5.5")),
        "properly_performed": fget(fl, "5.6"),
        "not_executed_reason": fget(fl, "5.1.1"),
        "extra_info": (t.split("SEKCJA VI", 1)[-1][:400] if "SEKCJA VI" in t else None),
    }


EXTRACT = {
    "ContractNotice": ex_contract_notice,
    "TenderResultNotice": ex_result_notice,
    "AgreementUpdateNotice": ex_change_notice,
    "ContractPerformingNotice": ex_performance_notice,
}

# --------------------------------------------------------------------------- dataset


def load_dataset(path: Path) -> list[dict]:
    rows, header = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== SHEET Opis"):
            break
        if line.startswith("Lp. |"):
            header = [h.strip() for h in line.split(" | ")]
            continue
        if header and re.match(r"^\d+ \| RM-", line):
            vals = [v.strip() for v in line.split(" | ")]
            vals += [""] * (len(header) - len(vals))
            rows.append(dict(zip(header, vals)))
    return rows


def org_fragment(name: str) -> str:
    """Stem of the most distinctive word of the buyer name, for the OrganizationName filter
    (substring, case-insensitive). Stemming survives Polish declension: Kartuzy/Kartuzach -> 'Kartuz'."""
    name = re.split(r"\s+[\u2013-]\s+", name)[0]
    words = [w for w in re.findall(r"\w+", name) if w.lower() not in ("gmina", "miasto", "powiat", "urząd", "miejski", "w")]
    w = max(words, key=len) if words else name
    return w[: max(4, len(w) - 2)] if len(w) > 5 else w


# --------------------------------------------------------------------------- linking


def chain_by_tender(org_notices, tender_id, refs: set[str]):
    """All notices with this tenderId, plus notices whose body references one of `refs` (BZP base numbers)."""
    out = {}
    for n in org_notices:
        if n["tenderId"] == tender_id:
            out[n["objectId"]] = (n, "tenderId")
    for n in org_notices:
        if n["objectId"] in out or not refs:
            continue
        body = n.get("htmlBody") or ""
        if any(r in body for r in refs):
            out[n["objectId"]] = (n, "body-ref")
    return list(out.values())


def score_candidate(group, row):
    """Similarity of a procedure (list of notices) to a KPO dataset row."""
    title = " ".join({n["orderObject"] for n in group})
    want = tokens(row["Nazwa przedsięwzięcia"]) | tokens(re.sub(r"^.*Opis:", "", row["Adnotacja instytucji"]))
    have = tokens(title)
    overlap = want & have
    jac = len(overlap) / max(1, len(tokens(row["Nazwa przedsięwzięcia"]) | have))
    cpv = any(c in (n.get("cpvCode") or "") for n in group for c in WODKAN_CPV)
    first = min(n["publicationDate"] for n in group)[:10]
    kpo_year = first >= "2024-01-01"
    score = jac + (0.1 if cpv else 0) + (0.1 if kpo_year else 0)
    return round(score, 3), sorted(overlap), first


def link_row(api: Api, row: dict, org_cache: dict) -> dict:
    res = {"project_id": row["Identyfikator rekordu"], "lp": row["Lp."], "flags": [], "method": None}
    nip = digits(row["Identyfikator odbiorcy"])
    if not nip_valid(nip):
        res["flags"].append(f"dataset NIP {nip} fails checksum")
    idtype, ident = row["Rodzaj identyfikatora publicznego"], row["Identyfikator publiczny"]
    scope = row["Zakres rekordu"]
    want_part = int(re.search(r"\d+", scope).group()) if re.search(r"część\s*\d+", scope) else None

    cn = None
    tender_id = None
    if idtype.startswith("Ogłoszenie BZP"):
        nb = norm_bzp(ident)
        res["bzp_normalised"] = nb
        if nb:
            base, ver = nb
            full = f"{base}/{ver or '01'}"
            hits = api.get(NoticeType="ContractNotice", NoticeNumber=full, PageSize=10)
            if not hits:  # maybe the number is not a contract notice, or version differs
                for t in MAIN_TYPES:
                    hits = api.get(NoticeType=t, NoticeNumber=base, PageSize=10)
                    if hits:
                        res["flags"].append(f"given number is a {t}, not a ContractNotice")
                        break
            if hits:
                cn = hits[0]
                tender_id = cn["tenderId"]
                res["method"] = "bzp-number"
            else:
                res["flags"].append("BZP number not found in API (any of 4 types)")

    frags = [org_fragment(row["Nazwa odbiorcy"])]
    if cn is not None:
        if digits(cn["organizationNationalId"]) != nip:
            res["flags"].append(f"NIP mismatch: dataset {nip} vs notice {cn['organizationNationalId']} ({cn['organizationName']})")
            nip = digits(cn["organizationNationalId"])  # follow the notice
        frags.append(cn["organizationName"])
    pool = {}
    for frag in frags:
        if frag not in org_cache:
            allnot = []
            for t in MAIN_TYPES:
                allnot += api.get_all(NoticeType=t, OrganizationName=frag, PublicationDateFrom="2021-01-01T00:00:00",
                                      PublicationDateTo="2026-12-31T23:59:59")
            org_cache[frag] = allnot
        for n in org_cache[frag]:
            pool[n["objectId"]] = n
    org_notices = [n for n in pool.values() if digits(n["organizationNationalId"]) == nip]
    res["org_fragment"] = frags
    res["org_notices"] = len(org_notices)

    if cn is None and res.get("bzp_normalised"):
        base = res["bzp_normalised"][0]
        refd = [n for n in org_notices if base in (n.get("htmlBody") or "")]
        if refd:
            tids = sorted({n["tenderId"] for n in refd})
            tender_id = tids[0]
            res["method"] = "bzp-number via references in follow-up notices"
            res["flags"].append(f"{base} absent from API as a notice; {len(refd)} follow-up notice(s) cite it (tenderId {tender_id})")
            if len(tids) > 1:
                res["flags"].append(f"number cited by several procedures: {tids}")
    candidates = []
    if cn is None and tender_id is None:
        # name/NIP/CPV/date search - group the organisation's notices into procedures
        groups = defaultdict(list)
        for n in org_notices:
            groups[n["tenderId"]].append(n)
        for tid, g in groups.items():
            s, ov, first = score_candidate(g, row)
            candidates.append({"tenderId": tid, "score": s, "overlap": ov, "first": first,
                               "title": g[0]["orderObject"][:120],
                               "types": sorted({n["noticeType"] for n in g})})
        candidates.sort(key=lambda c: -c["score"])
        res["candidates"] = candidates[:3]
        if candidates and candidates[0]["score"] >= 0.25:
            tender_id = candidates[0]["tenderId"]
            res["method"] = "name+NIP+CPV+date"
            res["confidence"] = candidates[0]["score"]
            if len(candidates) > 1 and candidates[1]["score"] >= candidates[0]["score"] - 0.05:
                res["flags"].append("ambiguous: runner-up candidate within 0.05")
        else:
            res["flags"].append("no procedure found by name search")
    if tender_id is None:
        return res

    # gather the chain
    refs = set()
    group = [n for n in org_notices if n["tenderId"] == tender_id]
    for n in group:
        refs.add(n["bzpNumber"])
    chain = chain_by_tender(org_notices, tender_id, refs)
    # body-ref expansion: notices referencing a number of the chain but with other tenderId
    res["tenderId"] = tender_id
    res["notices"] = []
    by_type = defaultdict(list)
    for n, how in sorted(chain, key=lambda x: x[0]["publicationDate"]):
        ex = EXTRACT[n["noticeType"]](n)
        ex.update({"type": n["noticeType"], "linked_by": how, "objectId": n["objectId"], "url": notice_url(n),
                   "orgName": n["organizationName"], "province": n["organizationProvince"]})
        by_type[n["noticeType"]].append(ex)
        res["notices"].append(ex)
    if cn is None and by_type["ContractNotice"]:
        cn = next(n for n, _ in chain if n["noticeType"] == "ContractNotice")
    # also referenced CN number from follow-up notices (when CN itself is absent from the API)
    referenced_cn = {norm_bzp(x.get("cn_ref") or "")[0] for x in res["notices"] if norm_bzp(x.get("cn_ref") or "")}
    res["referenced_cn"] = sorted(referenced_cn)

    # validations
    teryt = "PL" + row["Kod województwa (TERYT)"].zfill(2)
    provs = {x["province"] for x in res["notices"]}
    if provs and teryt not in provs:
        res["flags"].append(f"province mismatch: dataset {teryt} vs notices {sorted(provs)}")
    titles = " ".join(x.get("title") or "" for x in by_type["ContractNotice"]) or (group[0]["orderObject"] if group else "")
    sim = len(tokens(row["Nazwa przedsięwzięcia"]) & tokens(titles)) / max(1, len(tokens(row["Nazwa przedsięwzięcia"])))
    res["title_similarity"] = round(sim, 2)
    if sim < 0.5:
        res["flags"].append(f"low title similarity {sim:.2f}: notice '{titles[:90]}'")

    # summary
    s = res["summary"] = {}
    cnx = by_type["ContractNotice"][0] if by_type["ContractNotice"] else None
    s["cn"] = cnx["number"] if cnx else None
    s["cn_date"] = cnx["date"] if cnx else None
    s["parts_count"] = (cnx or {}).get("parts_count")
    trns = by_type["TenderResultNotice"]
    s["trn"] = [x["number"] for x in trns]
    parts = {}
    for x in trns:
        for p, d in x["parts"].items():
            parts[p] = d
    s["estimate_net"] = trns[-1]["estimate_net"] if trns else None
    s["parts"] = parts
    s["aun"] = [x["number"] for x in by_type["AgreementUpdateNotice"]]
    s["cpn"] = [x["number"] for x in by_type["ContractPerformingNotice"]]
    if want_part is not None:
        s["dataset_part"] = want_part
        if s["parts_count"] in (None, 0, 1) and len(parts) <= 1:
            res["flags"].append(f"dataset says część {want_part} but procedure is not divided into parts")
    if cnx and len(cnx["parts"]) > 1:
        desc = tokens(row["Nazwa przedsięwzięcia"] + " " + re.sub(r"^.*Opis:", "", row["Adnotacja instytucji"]))
        ptok = {p: tokens(d["description"]) for p, d in cnx["parts"].items()}
        excl = {p: t - set().union(*[o for q, o in ptok.items() if q != p]) for p, t in ptok.items()}
        hit = {p: sorted(desc & e) for p, e in excl.items()}
        res["part_evidence"] = hit
        matched = [p for p, h in hit.items() if h]
        if want_part is not None and matched and want_part not in matched:
            res["flags"].append(f"dataset says część {want_part}, but project description matches część {matched} "
                                f"(exclusive terms {[hit[p][:4] for p in matched]})")
        elif want_part is not None and len(matched) > 1:
            res["flags"].append(f"dataset says część {want_part}, but project description covers części {matched}")
    return res


def kpo_value_check(res, row):
    m = re.search(r"Wartość przedsięwzięcia:\s*([\d\s]+,\d{2})", row["Adnotacja instytucji"])
    if not m or not res.get("contracts"):
        return
    kpo = money(m.group(1))
    cs = res["contracts"]
    opts = {"sum contract values": sum(c["contract_value"] or 0 for c in cs),
            "sum paid": sum(c["paid_total"] or 0 for c in cs if c.get("paid_total"))}
    for c in cs:
        opts[f"part {c['part']} contract"] = c["contract_value"] or 0
        opts[f"part {c['part']} paid"] = c["paid_total"] or 0
    best = min(opts, key=lambda k: abs(opts[k] - kpo))
    diff = (opts[best] - kpo) / kpo * 100
    res["kpo_value"] = {"kpo": kpo, "closest": best, "value": round(opts[best], 2), "diff_pct": round(diff, 2)}
    if abs(diff) > 15:
        res["flags"].append(f"KPO project value {kpo:,.2f} far from BZP amounts (closest {best} {opts[best]:,.2f}, {diff:+.1f}%)")


def contract_rows(res):
    """Flatten to one row per contract (part)."""
    s = res.get("summary") or {}
    parts = s.get("parts") or {}
    cpns = [x for x in res.get("notices", []) if x["type"] == "ContractPerformingNotice"]
    auns = [x for x in res.get("notices", []) if x["type"] == "AgreementUpdateNotice"]
    rows = []
    if not parts:  # result notice missing from the API: rebuild contracts from performance/change notices
        for i, c in enumerate(cpns or auns, 1):
            parts[f"cpn{i}"] = {"outcome": "zawarciem umowy (z ogł. o wykonaniu)", "contractor": c.get("contractor"),
                                "contractor_id": c.get("contractor_id"), "contract_date": c.get("contract_date"),
                                "contract_value": c.get("contract_value"), "period": c.get("period")}
    for p, d in sorted(parts.items(), key=lambda kv: str(kv[0])):
        cv = d.get("contract_value")
        match = [c for c in cpns if cv and c.get("contract_value") and abs(c["contract_value"] - cv) < 1]
        if not match and len(parts) == 1:
            match = cpns
        ch = [a for a in auns if cv and a.get("contract_value") and abs(a["contract_value"] - cv) < 1]
        if not ch and len(parts) == 1:
            ch = auns
        c = match[-1] if match else {}
        pe = planned_end(d.get("period"), d.get("contract_date"))
        rows.append({
            "part": p, "outcome": "umowa" if "zawarciem umowy" in (d.get("outcome") or "") else (d.get("outcome") or "")[:40],
            "offers": d.get("offers"), "estimate_part_net": d.get("part_estimate_net"),
            "price_awarded": d.get("price_awarded"), "contractor": d.get("contractor"), "contractor_id": d.get("contractor_id"),
            "contract_date": d.get("contract_date"), "contract_value": cv, "planned_end": pe,
            "planned_period": d.get("period"),
            "aun": len(ch), "aun_bases": sorted({a["legal_basis"] for a in ch}),
            "cpn": c.get("number"), "actual_end": c.get("end_date"), "on_time": c.get("on_time"),
            "changes_count": c.get("changes_count"), "paid_total": c.get("paid_total"),
            "properly": c.get("properly_performed"),
            "change_bases": sorted({x["legal_basis"] for x in c.get("changes", [])}),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://bzp.cytr.us")
    ap.add_argument("--dataset", default="/home/dawid-home-pc/Desktop/hacknation-risk-miner/materials/text/05_dane_projekty.txt")
    ap.add_argument("--delay", type=float, default=0.0, help="use 2.1 on production (30 req/min)")
    a = ap.parse_args()
    api = Api(a.base, a.delay)
    rows = load_dataset(Path(a.dataset))
    org_cache = {}
    results = []
    for row in rows:
        r = link_row(api, row, org_cache)
        r["contracts"] = contract_rows(r)
        kpo_value_check(r, row)
        results.append(r)
        print(r["project_id"], r.get("method"), r.get("tenderId"), len(r.get("notices", [])), r["flags"], flush=True)
    for r in results:
        for x in r.get("notices", []):
            pass
    (HERE / "chains.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(HERE / "matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["project_id", "dataset_id", "method", "cn", "trn", "part", "contractor", "contractor_id", "contract_value",
                    "planned_end", "aun", "cpn", "actual_end", "on_time", "changes", "paid_total", "flags"])
        for r, row in zip(results, rows):
            cs = r["contracts"] or [{}]
            for c in cs:
                w.writerow([r["project_id"], row["Identyfikator publiczny"], r.get("method"), (r.get("summary") or {}).get("cn"),
                            ";".join((r.get("summary") or {}).get("trn") or []), c.get("part"), c.get("contractor"),
                            c.get("contractor_id"), c.get("contract_value"), c.get("planned_end"), c.get("aun"), c.get("cpn"),
                            c.get("actual_end"), c.get("on_time"), c.get("changes_count"), c.get("paid_total"),
                            " | ".join(r["flags"])])
    print("API calls (uncached):", api.calls)


if __name__ == "__main__":
    main()
