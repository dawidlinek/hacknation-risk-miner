"""Per-platform adapters for procurement-document platforms (docs_22, docs_sample).

Pure functions only: HTML/JSON in -> `Listing` out. No network here; the connectors fetch through
`ScrapeContext.fetch` and hand the bytes to these parsers, so `parse()` can re-run them on raw files.

Platforms (docs/scrape.md §4):
  * ezamowienia   - e-Zamówienia platform. Public read API used by the mp-client SPA:
                    GET /mp-readmodels/api/Search/GetTender?id=<OCID>
                    GET /mp-readmodels/api/Search/GetTenderDocuments?tenderId=<OCID>
                    (`isProceedingOnPlatform` tells whether the procedure is run there at all).
  * platformazakupowa - /transakcja/<id> page: attachment table + public messages ("Komunikaty").
                    robots.txt (2026-11-21) disallows /file/get_new/* (= every attachment download).
  * ezamawiajacy  - Marketplanet: /pn/<buyer>/demand/<id>/notice/public/details (+ ?folder=000N
                    sub-folders: kwota / otwarcie / wyniki). Downloads are POST
                    /repository/download/<token>; tokens are bound to the HTTP session.
  * logintrade    - /zapytania_email,<id>,<hash>.html: attachment list + "Kwota ..." field.
                    robots.txt disallows /DocumentService (= every attachment download).
  * generic       - any other page: same-host links to document files.

RODO: buyer-employee names shown next to platform messages are never copied into Listing.messages.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import io
import json
import re
import subprocess
import tempfile
import urllib.parse
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

DOC_EXTS = (".pdf", ".doc", ".docx", ".zip", ".xls", ".xlsx", ".odt", ".ods", ".rtf", ".txt", ".7z", ".rar",
            ".xml", ".ath", ".kst", ".dwg", ".jpg", ".png", ".tif", ".tiff")
TEXT_EXTS = (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".odt", ".rtf", ".ods", ".html", ".htm", ".xml")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?48[\s-]?)?(?:\(?\d{2,3}\)?[\s-]?)\d{3}[\s-]?\d{2,3}[\s-]?\d{2,3}")


def scrub(text: str) -> str:
    """Drop e-mails / phone numbers from short texts that go into records (RODO)."""
    return PHONE_RE.sub("[tel]", EMAIL_RE.sub("[email]", text or ""))


def norm_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "")).strip()


# ---------------------------------------------------------------------------------------------
# platform detection
# ---------------------------------------------------------------------------------------------

def detect_platform(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    if host.endswith("platformazakupowa.pl"):
        return "platformazakupowa"
    if host.endswith("ezamawiajacy.pl"):
        return "ezamawiajacy"
    if host.endswith("logintrade.net"):
        return "logintrade"
    if host.endswith("ezamowienia.gov.pl"):
        return "ezamowienia"
    if host.endswith("uzp.gov.pl"):
        return "uzp_miniportal"
    return "generic"


def is_procedure_url(url: str) -> bool:
    """True for a URL of one specific procedure, False for a buyer profile / home page."""
    u = url.lower()
    pats = (r"/transakcja/\d+", r"/demand/\d+/notice", r"/demand/notice/public/\d+", r"zapytania_email,\d+",
            r"/mp-client/search/list/ocds-", r"/mp-client/tenders/ocds-")
    if any(re.search(p, u) for p in pats):
        return True
    if detect_platform(url) == "generic":
        return len(urllib.parse.urlsplit(url).path.strip("/")) > 0
    return False


def ezam_buyer(url: str) -> str | None:
    """Marketplanet buyer slug: https://<slug>.ezamawiajacy.pl/pn/<slug>/..."""
    m = re.search(r"/pn/([^/?#]+)/", url)
    if m:
        return m.group(1)
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host.split(".")[0] if host.endswith("ezamawiajacy.pl") else None


# ---------------------------------------------------------------------------------------------
# robots.txt with wildcard semantics (urllib.robotparser ignores '*' / '$' inside paths)
# ---------------------------------------------------------------------------------------------

def robots_rules(txt: str, ua_token: str = "riskminer") -> list[tuple[bool, str]]:
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    cur_agents: list[str] = []
    cur_rules: list[tuple[bool, str]] = []
    last_was_rule = False
    for raw in (txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if last_was_rule:
                groups.append((cur_agents, cur_rules))
                cur_agents, cur_rules = [], []
            cur_agents.append(v.lower())
            last_was_rule = False
        elif k in ("allow", "disallow"):
            last_was_rule = True
            if v or k == "allow":
                cur_rules.append((k == "allow", v))
    if cur_agents:
        groups.append((cur_agents, cur_rules))
    specific = [r for a, r in groups if any(x != "*" and x in ua_token.lower() for x in a)]
    if specific:
        return [x for r in specific for x in r]
    return [x for a, r in groups if "*" in a for x in r]


def robots_allows(rules: list[tuple[bool, str]], url: str) -> tuple[bool, str | None]:
    """Longest matching rule wins (Google semantics); returns (allowed, matching rule)."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    best: tuple[int, bool, str] | None = None
    for allow, pat in rules:
        if not pat:
            continue
        rx = "^" + re.escape(pat).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        if re.match(rx, path) or re.match(rx, urllib.parse.unquote(path)):
            score = len(pat)
            if best is None or score > best[0] or (score == best[0] and allow):
                best = (score, allow, pat)
    if best is None:
        return True, None
    return best[1], ("Allow: " if best[1] else "Disallow: ") + best[2]


# ---------------------------------------------------------------------------------------------
# listing model
# ---------------------------------------------------------------------------------------------

@dataclass
class ListedFile:
    name: str
    url: str
    method: str = "GET"
    size_text: str | None = None
    size_bytes: int | None = None
    published: str | None = None
    section: str | None = None           # Postępowanie | Publiczna wiadomość | <folder title>
    context: str = ""                    # message text / folder title (classification hint)
    key: str = ""                        # stable id, independent of session tokens

    def make_key(self, platform: str, proc_id: str) -> str:
        base = f"{platform}|{proc_id}|{self.name}|{self.published or ''}|{self.size_text or ''}"
        if platform in ("platformazakupowa", "logintrade", "generic", "ezamowienia"):
            base = f"{platform}|{proc_id}|{self.url}"
        self.key = hashlib.sha1(base.encode()).hexdigest()[:16]
        return self.key


@dataclass
class Message:
    date: str | None
    text: str
    file_urls: list[str] = field(default_factory=list)
    buyer_notice: bool = False           # "Komunikat Zamawiającego" (system/buyer notice)


@dataclass
class Listing:
    platform: str
    url: str
    status: str = "ok"                   # ok | blocked | link_dead | not_found | error
    note: str = ""
    proc_id: str = ""
    ref_number: str | None = None
    title: str | None = None
    files: list[ListedFile] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    subpages: list[tuple[str, str]] = field(default_factory=list)   # (url, title)

    def to_dict(self) -> dict:
        return asdict(self)


def _size_to_bytes(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"([\d.,]+)\s*(kB|KB|MB|GB|B)?", s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = (m.group(2) or "kB").lower()
    mult = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3}.get(unit, 1000)
    return int(v * mult)


def _abs(base: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    return urllib.parse.urljoin(base, href)


# ---------------------------------------------------------------------------------------------
# platformazakupowa.pl
# ---------------------------------------------------------------------------------------------

def parse_platformazakupowa(html: str, url: str) -> Listing:
    t = LexborHTMLParser(html)
    m = re.search(r"/transakcja/(\d+)", url)
    lst = Listing("platformazakupowa", url, proc_id=m.group(1) if m else "")
    h1 = None
    for h in t.css("h1"):
        if "Postępowanie" in h.text() or "ID:" in h.text():
            h1 = h
            break
    if h1 is None:
        lst.status = "not_found"
        lst.note = "no procedure header on page (removed / not public?)"
        return lst
    head = norm_ws(h1.text())
    mh = re.search(r"ID:\s*(\d+)\s*:?\s*(.*)$", head)
    if mh:
        lst.proc_id = lst.proc_id or mh.group(1)
        rest = mh.group(2).strip()
        mbzp = re.match(r"(\d{4}/BZP\s+\d+(?:/\d+)?)\s+(.*)$", rest)
        if mbzp:
            lst.ref_number, lst.title = mbzp.group(1), mbzp.group(2)
            rest = ""
        mref = re.match(r"([A-ZĄĆĘŁŃÓŚŹŻ0-9][\w./\-–]*\d[\w./\-]*)\s+(.*)$", rest)
        if mref and re.search(r"\d", mref.group(1)) and len(mref.group(1)) < 40:
            lst.ref_number, lst.title = mref.group(1), mref.group(2)
        elif rest:
            lst.title = rest
    for h in t.css("h3"):
        if norm_ws(h.text()) == "Terminy" and h.parent is not None:
            txt = norm_ws(h.parent.text(separator=" "))
            for lab, key in (("Zamieszczenia", "published"), ("Składania", "submission"),
                             ("Otwarcie ofert", "opening")):
                mm = re.search(lab + r"\s+(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?)", txt)
                if mm:
                    lst.meta[key] = mm.group(1)
            mm = re.search(r"Tryb\s+(.*?)\s+Rodzaj\s+(.*)$", txt)
            if mm:
                lst.meta["tryb"], lst.meta["rodzaj"] = mm.group(1), mm.group(2)[:60]
    # attachment table
    seen = set()
    for a in t.css("a.proceeding-file-download"):
        href = a.attributes.get("href") or ""
        tr = a.parent
        while tr is not None and tr.tag != "tr":
            tr = tr.parent
        if tr is None:
            continue
        tds = [norm_ws(td.text(separator=" ")) for td in tr.css("td")]
        if len(tds) < 5:
            continue
        u = _abs(url, href)
        if u in seen:
            continue
        seen.add(u)
        f = ListedFile(name=tds[0], url=u, size_text=(tds[2] + " kB") if tds[2] else None,
                       size_bytes=_size_to_bytes((tds[2] + " kB") if tds[2] else None),
                       published=tds[3] or None, section=tds[4] or None)
        lst.files.append(f)
    # public messages ("Komunikaty")
    for tbl in t.css("table.on-table-align-top"):
        for tr in tbl.css("tr"):
            tds = tr.css("td")
            if len(tds) != 3 or tds[1].css_first("strong") is None:
                continue
            date = norm_ws(tds[0].text(separator=" ")) or None
            who = norm_ws(tds[1].text(separator=" "))
            body = tds[2]
            urls = [_abs(url, a.attributes.get("href") or "") for a in body.css("a")
                    if "/file/" in (a.attributes.get("href") or "")]
            # body text without the attachment list
            txt = body.html or ""
            txt = re.split(r"<h4[^>]*>\s*Załączniki", txt)[0]
            txt = norm_ws(LexborHTMLParser(txt).text(separator=" ")) if txt else ""
            lst.messages.append(Message(date=date, text=scrub(txt)[:4000], file_urls=urls,
                                        buyer_notice=who.lower().startswith("komunikat")))
    by_url = {f.url: f for f in lst.files}
    for msg in lst.messages:
        for u in msg.file_urls:
            if u in by_url:
                by_url[u].context = (by_url[u].context + " " + msg.text).strip()[:500]
    for f in lst.files:
        f.make_key(lst.platform, lst.proc_id)
    return lst


def platformazakupowa_profile_links(html: str, base: str) -> list[tuple[str, str]]:
    """(transakcja url, row text) pairs from a buyer profile page (/pn/<buyer>)."""
    t = LexborHTMLParser(html)
    out, seen = [], set()
    for a in t.css("a"):
        href = a.attributes.get("href") or ""
        if re.search(r"/transakcja/\d+", href):
            u = _abs(base, href)
            if u in seen:
                continue
            seen.add(u)
            node = a
            for _ in range(4):
                if node.parent is not None and node.parent.tag not in ("body",):
                    node = node.parent
            out.append((u, norm_ws(node.text(separator=" "))[:400]))
    return out


# ---------------------------------------------------------------------------------------------
# ezamawiajacy.pl (Marketplanet)
# ---------------------------------------------------------------------------------------------

def parse_ezamawiajacy(html: str, url: str, folder_title: str | None = None) -> Listing:
    t = LexborHTMLParser(html)
    m = re.search(r"/notice/public/(\d+)/details", url) or re.search(r"/demand/(\d+)/notice", url)
    lst = Listing("ezamawiajacy", url, proc_id=m.group(1) if m else "")
    rows = t.css("tr.fileDataRow")
    if not rows and ("Kod weryfikacyjny" in html or "Zaloguj przy pomocy" in html or "_1op_redirect" in html) \
            and "Rozmiar pliku" not in html:
        lst.status = "blocked"
        lst.note = "login required: procedure details are not public on this platform (redirect to Marketplanet login)"
        return lst
    if not rows and "mp_gridTable" not in html:
        lst.status = "not_found"
        lst.note = "no file table on page"
        return lst
    after_up = False
    for tr in rows:
        tds = [norm_ws(td.text(separator=" ")) for td in tr.css("td")]
        sc = tr.css_first("script")
        s = sc.text() if sc else ""
        if len(tds) >= 3 and tds[2] == "W górę":
            after_up = True
            continue
        mfold = re.search(r"enterFolderUrl:\s*'([^']+)'", s)
        if mfold:
            lst.subpages.append((_abs(url, mfold.group(1)), tds[2] if len(tds) > 2 else ""))
            continue
        mp = re.search(r"downloadPostUrl:\s*'([^']+)'", s)
        mg = re.search(r"downloadUrl:\s*'([^']+)'", s)
        if not (mp or mg) or len(tds) < 6:
            continue
        name, desc, date, size = tds[2], tds[3], tds[4], tds[5]
        if not mp:
            # "Ogłoszenie" rows open an iframe shell around the BZP notice (no content of their own):
            # keep only their dates as evidence of notice versions (original + changes)
            if date and date not in lst.meta.setdefault("notice_versions", []):
                lst.meta["notice_versions"].append(date)
            continue
        f = ListedFile(name=name, url=_abs(url, mp.group(1)), method="POST")
        f.size_text = size if size and size != "-" else None
        f.size_bytes = _size_to_bytes(f.size_text)
        f.published = date or None
        f.section = folder_title if (folder_title and after_up) else "Postępowanie"
        f.context = " ".join(x for x in (desc, folder_title if after_up else "") if x)
        lst.files.append(f)
    # folder links outside the grid scripts
    for a in t.css("a"):
        href = a.attributes.get("href") or ""
        if "?folder=" in href:
            u = _abs(url, href)
            if all(u != x for x, _ in lst.subpages):
                lst.subpages.append((u, norm_ws(a.text())))
    # procedure number / title, when present
    txt = norm_ws(t.body.text(separator=" ")) if t.body else ""
    mref = re.search(r"Numer postępowania:?\s*([\w./\-]+)", txt)
    if mref:
        lst.ref_number = mref.group(1)
    for f in lst.files:
        f.make_key(lst.platform, ezam_buyer(url) or "")
    return lst


def ezamawiajacy_search_rows(html: str, base: str) -> list[dict]:
    """Rows of /pn/<buyer>/demand/notice/publicpzp/<state>/list (search results)."""
    t = LexborHTMLParser(html)
    out = []
    buyer = ezam_buyer(base) or ""
    for tr in t.css("tr.dataRow"):
        tds = [norm_ws(td.text(separator=" ")) for td in tr.css("td")]
        rid = tr.attributes.get("id")
        if not rid or len(tds) < 2:
            continue
        out.append({"id": rid, "number": tds[0], "title": tds[1], "dates": tds[5:7],
                    # the row id is the notice id (…/demand/<id>/notice/… shows a login wall instead)
                    "url": _abs(base, f"/pn/{buyer}/demand/notice/public/{rid}/details")})
    return out


# ---------------------------------------------------------------------------------------------
# logintrade.net
# ---------------------------------------------------------------------------------------------

PERSONAL_LABELS = re.compile(r"osob|kontakt|e-?mail|telefon|tel\.|faks|fax", re.I)


def parse_logintrade(html: str, url: str) -> Listing:
    t = LexborHTMLParser(html)
    m = re.search(r"zapytania_email,(\d+),", url)
    lst = Listing("logintrade", url, proc_id=m.group(1) if m else "")
    if "attachmentList" not in html and "content-block" not in html:
        lst.status = "not_found"
        lst.note = "no procedure content on page"
        return lst
    for div in t.css("div.attachment"):
        name = div.css_first(".attachment-name")
        a = div.css_first("a")
        if not name or not a:
            continue
        size = div.css_first(".attachment-size")
        date = div.css_first(".attachment-date")
        f = ListedFile(name=norm_ws(name.text()), url=_abs(url, a.attributes.get("href") or ""),
                       size_text=norm_ws(size.text()) if size else None,
                       published=norm_ws(date.text()) if date else None, section="Załączniki")
        f.size_bytes = int(div.attributes.get("data-size") or 0) or _size_to_bytes(f.size_text)
        lst.files.append(f)
    for lab in t.css("h4.label"):
        k = norm_ws(lab.text())
        v = lab.next
        while v is not None and (v.tag in ("-text",) or "value" not in (v.attributes.get("class") or "")):
            v = v.next
        if v is None:
            continue
        val = norm_ws(v.text(separator=" "))
        if PERSONAL_LABELS.search(k):
            continue
        lst.meta[k[:80]] = scrub(val)[:1500]
        if re.search(r"kwot", k, re.I) and re.search(r"przeznacz|sfinansow", k, re.I):
            lst.messages.append(Message(date=None, text=f"{k}: {val}"[:500], buyer_notice=True))
    lst.ref_number = lst.meta.get("Znak sprawy")
    h = t.css_first("title")
    lst.title = lst.meta.get("Nazwa") or lst.meta.get("Przedmiot") or (norm_ws(h.text())[:300] if h else None)
    for f in lst.files:
        f.make_key(lst.platform, lst.proc_id)
    return lst


# ---------------------------------------------------------------------------------------------
# generic page
# ---------------------------------------------------------------------------------------------

def parse_generic(html: str, url: str) -> tuple[Listing, list[str]]:
    """Files linked from the page (same host) + same-host HTML links to follow (depth handled by caller)."""
    t = LexborHTMLParser(html)
    host = urllib.parse.urlsplit(url).netloc
    lst = Listing("generic", url, proc_id=urllib.parse.urlsplit(url).path)
    follow: list[str] = []
    seen = set()
    for a in t.css("a"):
        href = a.attributes.get("href") or ""
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = _abs(url, href).split("#")[0]
        if urllib.parse.urlsplit(u).netloc != host or u in seen:
            continue
        seen.add(u)
        path = urllib.parse.urlsplit(u).path.lower()
        label = norm_ws(a.text())
        if path.endswith(DOC_EXTS) or re.search(r"download|pobierz|attachment|zalacznik|plik", path):
            name = urllib.parse.unquote(path.rsplit("/", 1)[-1]) or label
            lst.files.append(ListedFile(name=name if "." in name else (label or name), url=u, context=label))
        else:
            follow.append(u)
    for f in lst.files:
        f.make_key(lst.platform, host)
    return lst, follow


# ---------------------------------------------------------------------------------------------
# e-Zamówienia read API
# ---------------------------------------------------------------------------------------------

def parse_ezamowienia_tender(js: Any) -> dict:
    if not isinstance(js, dict):
        return {}
    keep = ("objectId", "referenceNumber", "title", "bzpNumber", "state", "stage", "isProceedingOnPlatform",
            "amountToFinanced", "amountToFinancedCurrency", "isAmountToFinancedPublished", "organizationName",
            "organizationCity", "tenderType", "isTenderAmountBelowEU", "numberOfLots", "initiationDate",
            "tedContractNoticeNumber", "noticeBzpNumberOfTenderResult")
    out = {k: js.get(k) for k in keep if k in js}
    out["lots_amountToFinanced"] = [l.get("amountToFinanced") for l in (js.get("lots") or [])
                                    if l.get("amountToFinanced") is not None]
    return out


def parse_ezamowienia_documents(js: Any, tender_id: str) -> list[ListedFile]:
    out = []
    for d in js or []:
        if not isinstance(d, dict):
            continue
        did = d.get("objectId") or d.get("id") or d.get("documentId")
        name = d.get("fileName") or d.get("name") or d.get("title") or str(did)
        if not did:
            continue
        f = ListedFile(name=name, url=f"https://ezamowienia.gov.pl/mp-readmodels/api/Tender/DownloadDocument/"
                                      f"{tender_id}/{did}",
                       published=(d.get("publicationDate") or d.get("createDate") or "")[:19] or None,
                       section="e-Zamówienia", context=str(d.get("documentType") or d.get("description") or ""))
        f.make_key("ezamowienia", tender_id)
        out.append(f)
    return out


# ---------------------------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------------------------

_RULES: list[tuple[str, str]] = [
    # order matters: most specific first
    ("uniewaznienie", r"uniewa[żz]ni|art\.? ?255 "),
    ("kwota", r"kwot[aęy]\b.*(przeznacz|sfinansow|finansow)|(przeznacz|sfinansow)\w*.*kwot|informacj\w* o kwocie|"
              r"\bkwota\b|kwoty przeznacz|przeznaczy\w* na sfinansowanie|art\.? ?222 ust\.? ?4"),
    ("otwarcie", r"otwarci\w* ofert|z otwarcia|zotwarcia|informacja z otwarcia|ofert z otwarcia|zestawieni\w* ofert|art\.? ?222 ust\.? ?5"),
    ("wybor", r"wyb[oó]r\w*\s+(najkorzystniejsz|ofert)|o wyborze|wyborze|wynik\w* post[eę]powania|o wynikach|"
              r"informacj\w* o wyniku|rozstrzygni[eę]ci|zawiadomienie o wyborze|najkorzystniejszej ofert"),
    ("modyfikacja", r"zmian\w* tre[sś]ci|modyfikacj|zmiana swz|zmiany swz|zmian\w* ogłoszeni|zmianie ogłoszeni|"
                    r"zmianie og[lł]oszenia|sprostowani|zmiana termin|przedłużeni\w* termin|ogloszenie o zmianie|art\.? ?286"),
    ("qa", r"wyja[sś]nieni|odpowied\w* na pytani|pytania i odpowiedzi|pytania_i_odpowiedzi|pytanie|\bq&a\b|"
           r"odpowiedzi|odpowied[zź]|art\.? ?284"),
    ("pfu", r"\bpfu\b|program\w* funkcjonalno"),
    ("przedmiar", r"przedmiar"),
    ("kosztorys", r"kosztorys"),
    ("stwiorb", r"stwi?orb|stwior|specyfikacj\w* techniczn\w*|\bsst\b|\bsstwiorb\b|\bstwio\b|warunk\w* wykonania i odbioru"),
    ("ppu", r"\bppu\b|\bipu\b|\bswu\b|projektowan\w* postanowie|istotn\w* postanowie|wz[oó]r umowy|wzor_umowy|"
            r"projekt\w* umowy|postanowienia umowy|wz[oó]r_umowy|umowa - wz[oó]r|umowa_wzor"),
    ("aneks", r"\baneks"),
    ("opz", r"\bopz\b|opis\w* przedmiotu zam[oó]wienia"),
    ("projekt", r"projekt\w* budowlan|projekt\w* wykonawcz|projekt\w* techniczn|dokumentacj\w* projektow|"
                r"dokumentacj\w* techniczn|dokumentacj\w* budowlan|\bpzt\b|rysun|\bpb\b|\bpw\b|projekt_|\bpzt|"
                r"dokumentacja do post|dokumentacj\w*\b|operat|mapa do cel|pozwoleni\w* wodnoprawn|"
                r"decyzj\w* (o )?pozwol|uzgodnieni|opini\w* geotechn|geotechni|badani\w* gruntu|"
                r"warunki techniczne|warunki .* ps |projekt|opis\w* techniczn|\bprofil|mapa|studni|schemat|"
                r"\brzut|przekr[oó]j|plan\w* (sytuac|instalac|zagosp)|zagospodarowani|bran[żz]|\bpt\b|"
                r"szczeg[oó][lł]|przepompowni|\bbioz\b|geodez|inwentaryzac|\bdwg\b"),
    ("swz", r"\bswz\b|\bsiwz\b|specyfikacj\w* warunk[oó]w zam[oó]wienia|specyfikacja_warunkow"),
    ("umowa", r"\bumowa\b|\bumowy\b"),
]
_RULES_C = [(k, re.compile(p, re.I)) for k, p in _RULES]

# "Załącznik nr 3 do SWZ - formularz ..." etc. are attachments to the SWZ, not the SWZ itself
_FORMS = re.compile(r"formularz|o[sś]wiadczeni|jedz|\bespd\b|wykaz\w* (rob|os[oó]b|us[lł])|zobowi[aą]zani|"
                    r"pe[lł]nomocn|grupy kapita|za[lł](\.|ącznik\w*|acznik\w*|_)?\s*(nr|od)?\s*\d+\s*(-|do|–)\s*\d+|"
                    r"za[lł]\. nr 1 - 9|za[lł]aczniki_od|edytowaln", re.I)
_NOTICE = re.compile(r"og[lł]oszeni\w* o zam[oó]wieniu|^og[lł]oszenie(\s|$|\.|_)|og[lł]oszenie_o_zam|"
                     r"ogloszenie o zamowieniu|podgląd ogłoszenia", re.I)


def _norm_name(name: str) -> str:
    s = re.sub(r"\.(pdf|docx?|zip|xlsx?|odt|rtf|txt|7z|rar|ath|kst|html?)$", "", name or "", flags=re.I)
    return re.sub(r"[_]+", " ", s)


def classify(name: str, context: str = "", text_head: str = "", size_bytes: int | None = None
             ) -> tuple[str, str, str]:
    """-> (doc_type, subtype, basis). basis = filename | context | text | heuristic | default."""
    n = _norm_name(name)
    if re.search(r"og[lł]oszeni\w* o wyniku", n, re.I):
        return "wybor", "ogloszenie_o_wyniku", "filename"
    if _NOTICE.search(n) and not re.search(r"zmian", n, re.I):
        return "inne", "ogloszenie", "filename"
    attachment_to_swz = bool(re.search(r"za[lł]\w*\.?\s*(nr\.?\s*)?\d+\w?\s*(do|-)?\s*(swz|siwz)", n, re.I))
    for k, rx in _RULES_C:
        if rx.search(n):
            if k == "swz" and attachment_to_swz:
                continue            # "Załącznik nr 9 do SWZ" is not the SWZ itself
            if k == "umowa" and attachment_to_swz:
                continue
            if k in ("swz",) and _FORMS.search(n):
                return "inne", "formularze", "filename"
            if k == "projekt" and re.fullmatch(r"\s*projekt\s*", n, re.I) is None and _FORMS.search(n):
                return "inne", "formularze", "filename"
            return k, "", "filename"
    if _FORMS.search(n):
        return "inne", "formularze", "filename"
    ctx = norm_ws(context)
    if ctx:
        for k, rx in _RULES_C:
            if k in ("projekt", "umowa", "swz"):
                continue
            if rx.search(ctx):
                return k, "", "context"
    head = norm_ws(text_head)[:2500]
    if head:
        h = head[:1200]
        mn = re.search(r"og[lł]oszenie o (zam[oó]wieniu|wykonaniu umowy|wyniku post[eę]powania|zmianie og[lł]oszenia|"
                       r"udzieleniu zam[oó]wienia|zmianie umowy)", h[:600], re.I)
        if mn:
            kind = mn.group(1).lower()
            if "zmianie" in kind:
                return "modyfikacja", "ogloszenie_o_zmianie", "text"
            if "wyniku" in kind or "udzieleniu" in kind:
                return "wybor", "ogloszenie_o_wyniku", "text"
            return "inne", "ogloszenie", "text"
        for k, rx in _RULES_C:
            if k == "umowa":
                continue
            if rx.search(h):
                if k == "swz" and _FORMS.search(h[:400]):
                    return "inne", "formularze", "text"
                return k, "", "text"
    if re.search(r"\.zip$|\.7z$|\.rar$", name or "", re.I) and (size_bytes or 0) > 20_000_000:
        return "projekt", "large_archive", "heuristic"
    if re.search(r"\.(dwg|dxf|jpg|png|tiff?)$", name or "", re.I):
        return "projekt", "rysunek", "heuristic"
    if re.search(r"\.(ath|kst)$", name or "", re.I):
        return "kosztorys", "", "heuristic"
    return "inne", "", "default"


DESIGN_BUILD_RE = re.compile(r"zaprojektuj\w*\s+i\s+(wybuduj|wykona)|zaprojektowani\w*\s+i\s+(wykonani|budow|wybudow)|"
                             r"formule\s+[„\"]?zaprojektuj|projektuj i buduj|design\s*(and|&|-)\s*build", re.I)


def is_design_build(*texts: str) -> bool:
    return any(DESIGN_BUILD_RE.search(t or "") for t in texts)


AMOUNT_RE = re.compile(r"(\d{1,3}(?:[  .]\d{3})+(?:[,.]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:zł|PLN|złotych)",
                       re.IGNORECASE)
BARE_AMOUNT_RE = re.compile(r"(\d{1,3}(?:[  .]\d{3})+(?:[,.]\d{1,2})?|\d{4,}(?:[.,]\d{1,2})?)(?![\d/])")
KWOTA_ANCHOR = re.compile(r"(zamierza|planuje)\w*\s+(\w+\s+){0,3}przeznaczy|przeznaczy\w* na (sfinansowanie|realizacj)|"
                          r"kwot\w*,? jak\w* (zamawiaj\w* )?(zamierza|planuje)|kwota przeznaczona", re.IGNORECASE)


def _amount_value(raw: str) -> float | None:
    raw = raw.replace(" ", " ").strip()
    m = re.match(r"^(.*?)(?:[.,](\d{1,2}))?$", raw)
    if not m:
        return None
    whole = re.sub(r"[ .,]", "", m.group(1))
    if not whole.isdigit():
        return None
    return float(f"{int(whole)}.{m.group(2) or '0'}")


def find_amounts(text: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(text or ""):
        v = _amount_value(m.group(1))
        if v is not None and v >= 1000:
            out.append(v)
    return out


def find_amount(text: str) -> float | None:
    """Amount allocated (art. 222 ust. 4): amounts after the 'zamierza przeznaczyć' anchor; sum of per-lot
    amounts when the text lists lots/parts, else the first amount after the anchor."""
    text = text or ""
    m = KWOTA_ANCHOR.search(text)
    seg = text[m.start():] if m else text
    vals = find_amounts(seg)
    if not vals:   # amounts written without "zł"
        vals = [v for v in (_amount_value(x) for x in BARE_AMOUNT_RE.findall(seg))
                if v and v >= 1000 and not (1990 <= v <= 2100 and float(v).is_integer())]
    if not vals:
        return None
    if len(vals) > 1 and re.search(r"cz[eę][sś]ć|cz[eę][sś]ci|zadani\w* nr|pakiet", seg, re.IGNORECASE) \
            and not re.search(r"w tym", seg, re.IGNORECASE):
        return round(sum(vals), 2)
    return vals[0]


# ---------------------------------------------------------------------------------------------
# text extraction (local only)
# ---------------------------------------------------------------------------------------------

def sniff_ext(content: bytes, name: str = "", ctype: str = "") -> str:
    n = (name or "").lower()
    if content[:4] == b"%PDF":
        return ".pdf"
    if content[:2] == b"PK":
        if re.search(r"\.(docx|xlsx|odt|ods|pptx)$", n):
            return "." + n.rsplit(".", 1)[-1]
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
            if "word/document.xml" in names:
                return ".docx"
            if "xl/workbook.xml" in names:
                return ".xlsx"
            if "content.xml" in names and "mimetype" in names:
                return ".odt"
        except zipfile.BadZipFile:
            pass
        return ".zip"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".xls" if n.endswith(".xls") else ".doc"
    if content[:5] == b"{\\rtf":
        return ".rtf"
    if content[:6] == b"7z\xbc\xaf\x27\x1c":
        return ".7z"
    if content[:4] == b"Rar!":
        return ".rar"
    head = content[:400].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return ".html"
    m = re.search(r"\.([a-z0-9]{2,5})$", n)
    if m:
        return "." + m.group(1)
    return ".bin"


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
        out = []
        for n in sorted(parts, key=lambda x: (not x.endswith("document.xml"), x)):
            xml = z.read(n).decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<w:tab/>", "\t", xml)
            xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
            out.append(htmllib.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(out)


def _odt_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:p>|</text:h>", "\n", xml)
    return htmllib.unescape(re.sub(r"<[^>]+>", "", xml))


def _xlsx_text(content: bytes, max_cells: int = 200_000) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out, n = [], 0
    for ws in wb.worksheets:
        out.append(f"## {ws.title}")
        for row in ws.iter_rows(values_only=True):
            vals = [str(v) for v in row if v is not None and str(v).strip()]
            if vals:
                out.append("\t".join(vals))
                n += len(vals)
            if n > max_cells:
                break
    return "\n".join(out)


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _soffice_text(content: bytes, ext: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{ext}"
        src.write_bytes(content)
        _run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{td}/lo",
              "--convert-to", "txt:Text (encoded):UTF8", "--outdir", td, str(src)], timeout=240)
        out = Path(td) / "in.txt"
        return out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""


def extract_text(content: bytes, ext: str) -> tuple[str, int | None, str]:
    """-> (text, pages, method). Never raises; empty text when unsupported/failed."""
    ext = ext.lower()
    try:
        if ext == ".pdf":
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "in.pdf"
                src.write_bytes(content)
                r = _run(["pdftotext", "-enc", "UTF-8", "-layout", str(src), "-"], timeout=300)
                text = r.stdout.decode("utf-8", "replace")
                pages = None
                ri = _run(["pdfinfo", str(src)], timeout=60)
                mm = re.search(rb"Pages:\s+(\d+)", ri.stdout)
                if mm:
                    pages = int(mm.group(1))
                return text, pages, "pdftotext"
        if ext == ".docx":
            return _docx_text(content), None, "docx-xml"
        if ext in (".odt",):
            return _odt_text(content), None, "odt-xml"
        if ext in (".xlsx",):
            return _xlsx_text(content), None, "openpyxl"
        if ext in (".doc", ".rtf", ".xls", ".ods"):
            return _soffice_text(content, ext), None, "soffice"
        if ext in (".txt", ".xml", ".csv"):
            try:
                return content.decode("utf-8"), None, "decode"
            except UnicodeDecodeError:
                return content.decode("cp1250", "replace"), None, "decode"
        if ext in (".html", ".htm"):
            t = LexborHTMLParser(content.decode("utf-8", "replace"))
            body = t.body
            return norm_ws(body.text(separator="\n")) if body else "", None, "html"
    except Exception as e:  # noqa: BLE001
        return "", None, f"failed: {type(e).__name__}: {e}"[:200]
    return "", None, "unsupported"


def zip_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            raw = name.encode("cp437")
            for enc in ("utf-8", "cp852", "cp1250"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
        except UnicodeEncodeError:
            pass
    return name


def listing_summary(lst: Listing) -> dict:
    d = lst.to_dict()
    d["n_files"] = len(lst.files)
    return json.loads(json.dumps(d, ensure_ascii=False, default=str))


def classify_member(path: str, text_head: str = "") -> tuple[str, str, str]:
    """Archive member: own name first, then the nearest folder name, else design documentation."""
    parts = [x for x in re.split(r"[/\\]", path or "") if x]
    base = parts[-1] if parts else path
    t, sub, basis = classify(base, "", text_head)
    if t != "inne" or sub in ("formularze", "ogloszenie"):
        return t, sub, basis
    for folder in reversed(parts[:-1]):
        ft, fsub, _ = classify(folder)
        if ft in ("stwiorb", "przedmiar", "kosztorys", "pfu", "qa", "projekt", "ppu", "swz"):
            if ft == "swz":
                break
            return ft, fsub, "folder"
    return "projekt", "archive_default", "archive"
