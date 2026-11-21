"""GUS REGON BIR1.1 (TEST environment, public test key) -> TERYT symbols + website per NIP (docs/scrape.md §2).

Endpoint: https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc (SOAP 1.2 + WS-Addressing)
  Zaloguj(pKluczUzytkownika=abcde12345abcde12345) -> sid (session header, never cached)
  DaneSzukajPodmioty(Nip)                          -> Regon, Nazwa, Wojewodztwo/Powiat/Gmina, Typ (P/F), SilosID
  DanePobierzPelnyRaport(regon, report)            -> TERYT symbols (adSiedz*_Symbol), website, legal form ...
    report = BIR11OsPrawna (Typ P) | BIR11OsFizycznaDzialalnoscCeidg (Typ F, SilosID 1)

IMPORTANT: the TEST environment returns real identifiers, names and TERYT symbols but ANONYMISED street names /
house numbers ("ul. Test-Wilcza"): every record says so in data.test_environment_note. Production needs a key.
RODO: phone, fax and e-mail fields are dropped; for natural-person businesses (Typ F) the owner's personal
names (imię/nazwisko) are dropped, the registered business name is kept.
Scope: the 20 pilot buyer NIPs first (incl. WZDW Poznań 9720914891, missing from the VAT list), then contractors.
"""
from __future__ import annotations

import csv
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.gus_bir")

SOURCE = "gus_bir"
DEFAULTS = {"min_interval": 1.0, "timeout": 60.0}

URL = "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
TEST_KEY = "abcde12345abcde12345"          # public test key published by GUS
NS_ACT = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/"
TEST_NOTE = ("GUS BIR1.1 TEST environment: identifiers, names and TERYT symbols are real, street names/numbers are "
             "anonymised (e.g. 'ul. Test-...'); do not use the street address")
_DROP = re.compile(r"telefon|faks|fax|email|e_mail|imie|nazwisko", re.IGNORECASE)
_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _env(action: str, body: str) -> str:
    return ('<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
            'xmlns:dat="http://CIS/BIR/PUBL/2014/07/DataContract">'
            '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<wsa:To>{URL}</wsa:To><wsa:Action>{NS_ACT}{action}</wsa:Action></soap:Header>'
            f'<soap:Body>{body}</soap:Body></soap:Envelope>')


def _result(xml_text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_text, re.DOTALL)
    return html.unescape(m.group(1)) if m else ""


def _dane(inner: str) -> list[dict]:
    if not inner.strip():
        return []
    try:
        root = ET.fromstring(inner)
    except ET.ParseError:
        return []
    return [{c.tag: (c.text or "").strip() for c in d} for d in root.iter("dane")]


def nip_valid(nip: str) -> bool:
    if not re.fullmatch(r"\d{10}", nip or ""):
        return False
    s = sum(int(d) * w for d, w in zip(nip[:9], _WEIGHTS, strict=False)) % 11
    return s != 10 and s == int(nip[9])


def pilot_nips() -> list[tuple[str, str]]:
    """[(nip, role)] buyers first, then contractors (valid NIPs only, deduped)."""
    p = settings().ref_dir / "pilot_projects.json"
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    if not p.exists():
        return out
    projs = json.loads(p.read_text(encoding="utf-8"))
    for proj in projs:
        n = re.sub(r"\D", "", str(proj.get("buyer_nip") or ""))
        if nip_valid(n) and n not in seen:
            seen.add(n)
            out.append((n, "buyer"))
    for proj in projs:
        for c in proj.get("contractors") or []:
            for raw in (c.get("nip"), c.get("id_raw")):
                for tok in re.findall(r"\d[\d\s-]{8,14}\d", str(raw or "")):
                    n = re.sub(r"\D", "", tok)
                    if nip_valid(n) and n not in seen:
                        seen.add(n)
                        out.append((n, "contractor"))
    return out


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        full_report: bool = True, **opts: Any) -> dict:
    targets = [(re.sub(r"\D", "", x), "only") for x in only] if only else pilot_nips()
    if limit:
        targets = targets[:limit]
    # skip NIPs that already have a stored search answer
    have = set()
    for e in ctx.store.entries():
        if e.get("status") == "ok" and (e.get("note") or "").startswith("search nip="):
            have.add(e["note"].split("=", 1)[1].split()[0])
    todo = [t for t in targets if t[0] not in have]
    out = {"targets": len(targets), "already": len(targets) - len(todo), "searched": 0, "reports": 0}
    if not todo:
        return out
    login = ctx.fetch(URL, method="POST", data=_env("Zaloguj", f"<ns:Zaloguj><ns:pKluczUzytkownika>{TEST_KEY}"
                                                    "</ns:pKluczUzytkownika></ns:Zaloguj>"),
                      headers={"Content-Type": "application/soap+xml; charset=utf-8"}, ttl=timedelta(seconds=0),
                      rel_path="login.xml", note="Zaloguj (test key)", check_blocked=False)
    sid = _result(login.text(), "ZalogujResult") if login.ok else ""
    if not sid:
        log.warning("BIR login failed: %s", login.status)
        return {**out, "login": login.status}
    hdr = {"Content-Type": "application/soap+xml; charset=utf-8", "sid": sid}
    for nip, role in todo:
        body = (f"<ns:DaneSzukajPodmioty><ns:pParametryWyszukiwania><dat:Nip>{nip}</dat:Nip>"
                "</ns:pParametryWyszukiwania></ns:DaneSzukajPodmioty>")
        r = ctx.fetch(URL, method="POST", data=_env("DaneSzukajPodmioty", body), headers=hdr, ttl=None,
                      rel_path=f"search/{nip}.xml", note=f"search nip={nip} role={role}", check_blocked=False)
        out["searched"] += 1
        if not r.ok or not full_report:
            continue
        for d in _dane(_result(r.text(), "DaneSzukajPodmiotyResult")):
            regon, typ, silos = d.get("Regon", ""), d.get("Typ", ""), d.get("SilosID", "")
            if not regon:
                continue
            rep = "BIR11OsPrawna" if typ == "P" else ("BIR11OsFizycznaDzialalnoscCeidg" if silos == "1" else
                                                      "BIR11OsFizycznaDzialalnoscPozostala")
            body = (f"<ns:DanePobierzPelnyRaport><ns:pRegon>{regon}</ns:pRegon><ns:pNazwaRaportu>{rep}"
                    "</ns:pNazwaRaportu></ns:DanePobierzPelnyRaport>")
            rr = ctx.fetch(URL, method="POST", data=_env("DanePobierzPelnyRaport", body), headers=hdr, ttl=None,
                           rel_path=f"report/{regon}_{rep}.xml", note=f"report nip={nip} regon={regon} {rep}",
                           check_blocked=False)
            out["reports"] += int(rr.ok)
    return out


# ---------------------------------------------------------------------------------------------
def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v and not _DROP.search(k)}


def _teryt(rep: dict) -> tuple[str | None, dict]:
    """TERC from the full report symbols (seat address: praw_adSiedz* / fiz_adSiedz*)."""
    for pre in ("praw_adSiedz", "fiz_adSiedz"):
        w = rep.get(f"{pre}Wojewodztwo_Symbol")
        p = rep.get(f"{pre}Powiat_Symbol")
        g = rep.get(f"{pre}Gmina_Symbol")
        if w:
            sym = {"woj": w, "pow": p, "gmi": g, "miejscowosc_simc": rep.get(f"{pre}Miejscowosc_Symbol")}
            if w and p and g and len(g) == 3:
                return f"{w}{p}{g}", sym
            return (f"{w}{p}" if p else w), sym
    return None, {}


def _gmina_rows() -> list[dict]:
    p = settings().ref_dir / "teryt_terc.csv"
    if not p.exists():
        return []
    return [r for r in csv.DictReader(p.open(encoding="utf-8")) if r["level"] == "gmi"]


def gmina_by_name(name: str | None, woj_pow: str | None, rows: list[dict]) -> str | None:
    """'GMINA OŁAWA' with its office in the town Oława -> 0215042 (the rural gmina), 'GMINA ELBLĄG' -> 2804022.
    Plain 'Gmina X': rural / urban-rural gmina named X in the voivodeship (seat powiat breaks ties);
    'Gmina Miasto X' / 'Gmina Miejska X': urban gmina X in the seat powiat."""
    m = re.match(r"^\s*(gmina\s+miasto|gmina\s+miejska|gmina\s+i\s+miasto|gmina)\s+(.+?)\s*$", name or "",
                 re.IGNORECASE)
    if not m or not woj_pow:
        return None
    prefix, nm = m.group(1).lower(), m.group(2).lower()
    in_woj = [r for r in rows if r["terc"].startswith(woj_pow[:2]) and r["name"].lower() == nm]
    want = "1" if ("miasto" in prefix or "miejska" in prefix) else "23"
    cands = [r for r in in_woj if r["rodz"] in want]
    if len(cands) > 1:
        cands = [r for r in cands if r["terc"].startswith(woj_pow[:4])] or cands
    return cands[0]["terc"] if len(cands) == 1 else None


def gmina_terc(unit: str | None, gminas: set[str]) -> str | None:
    """BIR gives the seat's unit (rodz 4/5 = town/rural part of an urban-rural gmina, 8/9 = city district or
    delegatura); map it to the gmina TERC (rodz 1-3)."""
    if not unit or len(unit) != 7:
        return unit
    if unit[6] in "123":
        return unit
    base = unit[:6]
    cands = [base + r for r in "321" if base + r in gminas] if unit[6] in "45" else []
    if unit[6] in "89":
        cands = [c for c in sorted(gminas) if c.startswith(unit[:4]) and c[6] == "1"][:1]
    return cands[0] if cands else unit


def parse(store: RawStore) -> Iterable[ExternalRecord | SourceCheck]:
    grows = _gmina_rows()
    gminas = {r["terc"] for r in grows}
    searches: dict[str, dict] = {}
    reports: dict[str, list[dict]] = {}
    for e in store.entries():
        note = e.get("note") or ""
        if e.get("status") != "ok" or not e.get("path"):
            if note.startswith("search nip="):
                searches.setdefault(note.split("=", 1)[1].split()[0], e)
            continue
        if note.startswith("search nip="):
            searches[note.split("=", 1)[1].split()[0]] = e
        elif note.startswith("report nip="):
            reports.setdefault(note.split("=", 1)[1].split()[0], []).append(e)
    for nip, e in sorted(searches.items()):
        role = (e.get("note") or "").split("role=")[-1] if "role=" in (e.get("note") or "") else None
        checked = datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if e.get("status") != "ok":
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query={"nip": nip},
                              result="blocked" if e.get("status") == "blocked" else "error", checked_at=checked,
                              note=f"HTTP {e.get('http_status')} {e.get('note', '')}")
            continue
        text = Path(store.abs(e["path"])).read_text(encoding="utf-8", errors="replace")
        hits = _dane(_result(text, "DaneSzukajPodmiotyResult"))
        err = next((h for h in hits if h.get("ErrorCode")), None)
        hits = [h for h in hits if not h.get("ErrorCode") and h.get("Regon")]
        if not hits:
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query={"nip": nip},
                              result="not_found", checked_at=checked, raw_path=e["path"],
                              note="no entity for this NIP in the BIR test environment"
                                   + (f" (ErrorCode {err.get('ErrorCode')}: {err.get('ErrorMessagePl', '')})" if err else ""))
            continue
        ids = []
        for h in hits:
            regon = h.get("Regon", "")
            rep: dict = {}
            rep_e = None
            for re_ in reports.get(nip, []):
                if f"regon={regon}" in (re_.get("note") or ""):
                    rt = Path(store.abs(re_["path"])).read_text(encoding="utf-8", errors="replace")
                    rows = _dane(_result(rt, "DanePobierzPelnyRaportResult"))
                    if rows:
                        rep, rep_e = rows[0], re_
            unit, sym = _teryt(rep)
            seat_gmina = gmina_terc(unit, gminas)
            by_name = gmina_by_name(h.get("Nazwa"), unit, grows)
            terc = by_name or seat_gmina
            sym.update(terc_unit=unit, seat_gmina_terc=seat_gmina, gmina_terc_by_name=by_name,
                       basis="entity name within seat powiat" if by_name else "seat address")
            website = rep.get("praw_adresStronyinternetowej") or rep.get("fiz_adresStronyinternetowej") or None
            ext = regon or nip
            ids.append(ext)
            yield ExternalRecord(
                source=SOURCE, kind="bir_entity", external_id=ext, title=h.get("Nazwa"), buyer_nip=nip,
                buyer_regon=regon or None, buyer_name=h.get("Nazwa"), teryt=terc,
                province=(h.get("Wojewodztwo") or "").lower() or None, url=URL,
                raw_path=(rep_e or e)["path"], raw_sha256=(rep_e or e).get("sha256"),
                data={"search": _clean({k: v for k, v in h.items() if k not in ("Ulica", "NrNieruchomosci", "NrLokalu")}),
                      "report_name": (rep_e or {}).get("note", "").split()[-1] if rep_e else None,
                      "report": _clean({k: v for k, v in rep.items() if "Ulica" not in k and "Nieruchomosci" not in k
                                        and "Lokalu" not in k}),
                      "teryt_symbols": sym, "website": website, "entity_type": h.get("Typ"),
                      "pilot_role": role, "test_environment_note": TEST_NOTE})
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query={"nip": nip},
                          n_hits=len(hits), n_relevant=len(hits), result="found", matched_ids=ids, checked_at=checked,
                          raw_path=e["path"], note=f"{len(hits)} REGON unit(s); {TEST_NOTE}")
