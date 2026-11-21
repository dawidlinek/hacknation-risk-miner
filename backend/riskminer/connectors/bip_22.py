"""bip_22: targeted BIP (Biuletyn Informacji Publicznej) lookups for the buyers of the 22 pilot projects
(docs/scrape.md §2 P2 row, §5 buyers_bip.csv; docs/research/02_other_sources.md §10).

run():
  1. BIP discovery per buyer, each candidate with a confidence:
       0.90  URL declared by the buyer in its own BZP notices (local BZP copy, "bip" in the URL)
       0.85  central BIP register (aplikacje.gov.pl/app/bip-back/api/subjects), unique gmina-level entry
       0.80  link labelled BIP on the buyer's homepage (homepage URL from its BZP notices)
       0.70  central BIP register, ambiguous (several gmina-level entries match)
       0.60  pattern probe (bip.<homepage host>) that answers with a BIP page
     The best candidate that answers with a page mentioning "Biuletyn"/"BIP" wins -> data/ref/buyers_bip.csv
  2. Per BIP: robots.txt -> Sitemap(s) (robots `Sitemap:` lines, /sitemap.xml) -> keyword filter
     (place names from the pilot titles, reference numbers, "kanalizac", "wodociąg", "WPF", "przedsięwzię",
     committee / contract-register words). Without a sitemap: homepage -> menu sections (uchwały, zarządzenia,
     budżet/WPF, rejestr umów, zamówienia publiczne) depth <= 2. Relevant pages are fetched and their
     attachments (pdf/doc/docx/xls/xlsx/odt) downloaded when the link text / file name matches; text extracted.
parse(): DocumentRecord per relevant page/attachment per project (category in doc_type: wpf, uchwala_budzet,
  zarzadzenie, rejestr_umow, swz (BIP mirror of the tender documents), ogloszenie, inne) + SourceCheck per
  project. Everything is re-derived from data/raw/bip_22 (no network).

Manifest note convention: "bip_22 role=<role> host=<bip host> rm=<rm_id> key=<k>".
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from riskminer.config import settings
from riskminer.connectors import platforms as P
from riskminer.connectors.base import RawStore, ScrapeContext, safe_name
from riskminer.connectors.records import DocumentRecord, SourceCheck

log = logging.getLogger("riskminer.bip_22")

SOURCE = "bip_22"
DEFAULTS = {"min_interval": 1.0, "timeout": 120.0}
REGISTER = "https://aplikacje.gov.pl/app/bip-back/api/subjects"
EZ_TENDER = "https://ezamowienia.gov.pl/mp-readmodels/api/Search/GetTender"
PAGE_CAP = 45          # detail pages per BIP
NAV_CAP = 50           # navigation pages per BIP (no-sitemap mode)
TOPIC_PAGE_CAP = 15    # pages selected only by a water/sewage word in the link text
DOC_CAP = 25           # attachments per BIP
DOC_MAX_BYTES = 30_000_000
SITEMAP_CAP = 12

PLATFORM_HOSTS = ("platformazakupowa", "ezamawiajacy", "logintrade", "ezamowienia", "uzp.gov", "marketplanet",
                  "drive.google", "nbp.pl", "adoptopenjdk", "enmedia", "gov.pl/web", "puesc", "epuap", "mf.gov",
                  "biznes.gov", "ceidg", "krs", "e-propublico", "smartpzp", "eb2b", "gwarancje")

TOPIC = re.compile(r"kanaliz|wodoci[aą]g|wodociag|oczyszczal|[sś]ciek|sciek|uzdatnian|\bsuw\b|przepompown|"
                   r"sieci? wod|sieci? san|deszczow|retencj", re.I)
FIN = re.compile(r"wieloletni\w* prognoz|wieloletniej|\bwpf\b|przedsi[eę]wzi[eę]|przedsiewzie", re.I)
BUDGET = re.compile(r"bud[zż]et|budzet|zmian\w* (w )?bud", re.I)
COMMITTEE = re.compile(r"komisj\w* przetarg|powo[lł]ani\w* komisji|komisji przetargowej|komisja-przetargowa|"
                       r"komisji-przetargowej", re.I)
REGISTRY = re.compile(r"rejestr\w*[ _-]+um[oó]w|rejestr-umow|umowy zawarte|zawartych um[oó]w", re.I)
SWZ_RE = re.compile(r"\bswz\b|\bsiwz\b|specyfikacj\w* warunk[oó]w zam|specyfikacja-warunkow", re.I)
SECTION = re.compile(r"uchwa[lł]|uchwal|zarz[aą]dzen|zarzadzen|bud[zż]et|budzet|wieloletni|\bwpf\b|rejestr|umow|"
                     r"zam[oó]wieni|zamowieni|przetarg|og[lł]oszeni|ogloszeni|inwestycj|finans|rada|wojt|w[oó]jt|"
                     r"burmistrz|prawo-miejscowe|prawo miejscowe|akty", re.I)
DOC_LINK = re.compile(r"\.(pdf|docx?|xlsx?|odt|ods|rtf)(\?|$)|/(download|pobierz|plik|file|attachment|zalacznik)",
                      re.I)
STOP = {"budowa", "budowę", "przebudowa", "rozbudowa", "modernizacja", "gmina", "gminy", "gminie", "sieci",
        "sieć", "kanalizacji", "sanitarnej", "wodociągowej", "wodociągowych", "miejscowości", "miejscowość",
        "zadanie", "etap", "część", "wraz", "oraz", "terenie", "ulicy", "ul", "dla", "formule", "zaprojektuj",
        "wybuduj", "stacji", "uzdatniania", "wody", "oczyszczalni", "ścieków", "drogi", "wojewódzkiej", "nr",
        "aglomeracji", "zwiększenie", "odporności", "hydrologicznej", "poprzez", "deszczowej", "tranzytu",
        "przesyłowego", "rurociągu", "tłocznego", "sołectwo", "długości", "km", "przyłączami", "miasta",
        "budowy", "budowie", "kanalizacja", "wodociąg", "sanitarna", "sanitarnych", "kanalizacyjnej"}


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def _note(**kw: Any) -> str:
    parts = ["bip_22"]
    for k, v in kw.items():
        if v not in (None, ""):
            parts.append(k + "=" + re.sub(r"\s+", "_", str(v)))
    return " ".join(parts)


def _pnote(note: str | None) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", note or ""))


def _pilot() -> list[dict]:
    return json.loads((settings().ref_dir / "pilot_projects.json").read_text(encoding="utf-8"))


def ascii_fold(s: str) -> str:
    s = (s or "").replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(s).lower()).strip("-")


def place_name(buyer_name: str) -> str:
    m = re.search(r"Gmina\s+(?:Miejska\s+|Miasto\s+|Wiejska\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż\-]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ]"
                  r"[\wąćęłńóśźż\-]+)?)", buyer_name or "")
    if m:
        return re.split(r"\s+[–-]\s+|\s+Urz", m.group(1))[0].strip()
    return (buyer_name or "").strip()


def stem(w: str) -> str:
    w = ascii_fold(w).lower()
    return w[: max(5, len(w) - 2)] if len(w) > 5 else w


def project_terms(p: dict, ref: str | None) -> dict[str, list[str]]:
    """Distinctive search terms for one project: place-name stems from the title + reference numbers."""
    gmina = place_name(p.get("buyer_name") or "")
    gm = [ascii_fold(w).lower()[:6] for w in gmina.split()] if gmina else []
    places = []
    for w in re.findall(r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{3,}(?:[-–][A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?", p.get("title") or ""):
        if w.lower() in STOP:
            continue
        s = stem(w)
        if s and not any(s[:5] == g[:5] for g in gm) and s not in places and len(s) >= 5:
            places.append(s)
    refs = [r for r in {ref, *(n.get("number") for n in p.get("notices") or [])} if r]
    return {"places": places[:8], "refs": refs}


def _match_terms(text_ascii_lower: str, terms: dict[str, list[str]], raw_text: str = "") -> list[str]:
    hits = [s for s in terms.get("places", []) if s in text_ascii_lower]
    for r in terms.get("refs", []):
        rr = re.sub(r"\s+", " ", r.lower())
        if rr and (rr in (raw_text or "").lower() or ascii_fold(rr) in text_ascii_lower):
            hits.append(r)
    return hits


WPF_STRICT = re.compile(r"wieloletni\w* prognoz|\bwpf\b|wykaz\w* przedsi[eę]wzi[eę][cć]|wykaz-przedsiewziec", re.I)
ENV = re.compile(r"[sś]rodowiskow\w* uwarunkowa|uwarunkowa\w* [sś]rodowiskow|uwarunkowaniach [sś]rodowiskow|"
                 r"ocen\w* oddzia[lł]ywania|srodowiskowych-uwarunkowan|decyzj\w* o [sś]rodowiskow", re.I)


def categorize(text: str) -> str:
    t = text or ""
    if REGISTRY.search(t):
        return "rejestr_umow"
    if WPF_STRICT.search(t):
        return "wpf"
    if ENV.search(t):
        return "decyzja_srodowiskowa"
    if COMMITTEE.search(t):
        return "zarzadzenie"
    if SWZ_RE.search(t):
        return "swz"
    if re.search(r"zarz[aą]dzeni|zarzadzeni", t, re.I):
        return "zarzadzenie"
    if BUDGET.search(t) and re.search(r"uchwa[lł]|uchwal", t, re.I):
        return "uchwala_budzet"
    if re.search(r"uchwa[lł]|uchwal", t, re.I):
        return "uchwala"
    if re.search(r"og[lł]oszeni|ogloszeni|przetarg|zapytani\w* ofertow|zam[oó]wieni\w* publiczn|zamowieni", t, re.I):
        return "ogloszenie"
    return "inne"


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _norm_base(url: str) -> str:
    url = url.strip().rstrip(".,;)")
    if not re.match(r"https?://", url):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"


def _abs_path(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else settings().raw_dir.parent.parent / p


def _html_text(b: bytes) -> str:
    try:
        t = LexborHTMLParser(b.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""
    for n in t.css("script,style,noscript"):
        n.decompose()
    return P.norm_ws(t.body.text(separator=" ")) if t.body else ""


def _links(b: bytes, base: str) -> list[tuple[str, str]]:
    try:
        t = LexborHTMLParser(b.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return []
    for n in t.css("script,style,svg,noscript"):
        n.decompose()
    out = []
    for a in t.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urllib.parse.urljoin(base, href).split("#")[0]
        if not u.startswith("http"):
            continue
        out.append((u, P.norm_ws(a.text(separator=" ")) or (a.attributes.get("title") or "")))
    return out


# ---------------------------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------------------------

def _bzp_urls(projects: list[dict]) -> dict[str, list[str]]:
    """URLs the buyer declared in its own BZP notices of the pilot procedures (local BZP copy)."""
    path = Path(settings().bzp_copy_path)
    nums = {n["number"]: p["rm_id"] for p in projects for n in p.get("notices") or []}
    out: dict[str, set[str]] = defaultdict(set)
    if not path.exists() or not nums:
        return {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            m = re.search(r'"noticeNumber": "([^"]+)"', line[:3000])
            if not m or m.group(1) not in nums:
                continue
            d = json.loads(line)
            for u in re.findall(r"https?://[^\s<\"']+|www\.[^\s<\"']+", d.get("htmlBody") or ""):
                u = u.rstrip(".,;)")
                if not any(x in u.lower() for x in PLATFORM_HOSTS):
                    out[nums[m.group(1)]].add(u)
    return {k: sorted(v) for k, v in out.items()}


def _register_candidates(ctx: ScrapeContext, p: dict) -> list[dict]:
    gmina = place_name(p.get("buyer_name") or "")
    is_gmina = (p.get("buyer_name") or "").lower().startswith("gmina")
    q = gmina if is_gmina else re.sub(r"\s+w\s+\w+$", "", p.get("buyer_name") or "")[:40]
    qstem = q[:-1] if is_gmina and len(q) > 5 else q
    r = ctx.fetch(REGISTER, params={"archive": "false", "hasContactCard": "true", "name": qstem},
                  rel_path=f"register/{safe_name(qstem)}.json", note=_note(role="register", q=slug(qstem)))
    if not r.ok:
        return []
    try:
        items = (r.json() or {}).get("list") or []
    except ValueError:
        return []
    woj = slug(p.get("woj") or "")
    gslug = slug(gmina)
    hits = []
    for it in items:
        anc = it.get("ancestry") or []
        card = it.get("contactCardUrl") or ""
        if is_gmina:
            if len(anc) < 2 or anc[1] != "Gminy":
                continue
            if gslug not in card or (woj and woj not in card):
                continue
        else:
            if slug(q)[:20] not in slug(it.get("name") or ""):
                continue
        if it.get("url"):
            city_entry = bool(re.search(r"miast|miejsk", it.get("name") or "", re.I))
            city_buyer = bool(re.search(r"miast|miejsk", p.get("buyer_name") or "", re.I))
            if is_gmina and city_entry != city_buyer:
                continue        # e.g. "Gmina Miasto Oława" is not the rural "Gmina Oława"
            hits.append(it)
    conf = 0.85 if len(hits) == 1 else 0.7
    return [{"url": _norm_base(h["url"]), "confidence": conf, "how": f"central BIP register: {h.get('name')} "
             f"({'unique' if len(hits) == 1 else 'ambiguous'} match)", "raw": r.manifest.get("path")} for h in hits]


def _mentions_buyer(b: bytes | None, p: dict) -> bool:
    name = place_name(p.get("buyer_name") or "")
    if not b or not name:
        return False
    t = ascii_fold(b[:300_000].decode("utf-8", "replace")).lower()
    w = ascii_fold(name.split()[0]).lower()
    return w[: max(4, len(w) - 2)] in t


GENERIC_BIP_HOSTS = ("bip.gov.pl", "www.bip.gov.pl", "bip.net.pl", "www.bip.net.pl")
NOT_BUYER_HOST = re.compile(r"ssdip|szkol|przedszkol|gops|mops|\bops\b|zespol|bibliotek|gbas|gzo|zeas|zoz|"
                            r"spzoz|osrodek|kultur|sport", re.I)
# buyer homepages not present in the BZP notices (provenance: the buyer's official domain)
HOMEPAGE_HINTS = {"9720914891": "https://wzdw.pl/"}


def _bip_root(url: str) -> str:
    """Crawl base for a BIP URL: multi-tenant hosts keep the tenant segment, others the site root."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower()
    origin = f"{parts.scheme}://{parts.netloc}"
    segs = [x for x in parts.path.split("/") if x]
    if host.endswith("bip.malopolska.pl") and segs:
        return f"{origin}/{segs[0].split(',')[0]}/"
    if host.startswith(("bip.", "www.bip.")) or ".bip." in host or "biuletyn" in host or host.endswith("bip.net.pl"):
        return origin + "/"
    if segs and segs[0].lower() == "bip":
        return origin + "/bip"
    return url
_DNS: dict[str, bool] = {}


def _resolves(url: str) -> bool:
    """DNS pre-check for guessed hosts (not an HTTP request): avoids minutes of transport retries."""
    import socket
    host = _host(url).split(":")[0]
    if host not in _DNS:
        try:
            socket.getaddrinfo(host, 443)
            _DNS[host] = True
        except OSError:
            _DNS[host] = False
    return _DNS[host]


def _is_bip_page(b: bytes | None) -> bool:
    if not b:
        return False
    t = b[:200_000].decode("utf-8", "replace")
    return bool(re.search(r"Biuletyn\w*\s+Informacji\s+Publicznej|\bBIP\b", t, re.I))


def discover(ctx: ScrapeContext, p: dict, bzp_urls: list[str]) -> dict:
    rm = p["rm_id"]
    cands: list[dict] = []
    for u in bzp_urls:
        if re.search(r"bip|biuletyn", u, re.I):
            cands.append({"url": _norm_base(u), "confidence": 0.9, "how": "declared by the buyer in its BZP notice"})
    cands += _register_candidates(ctx, p)
    homes = [_norm_base(u) for u in bzp_urls if not re.search(r"bip|biuletyn", u, re.I)]
    if p.get("buyer_nip") in HOMEPAGE_HINTS:
        homes.append(HOMEPAGE_HINTS[p["buyer_nip"]])
    for h in homes[:2]:
        r = ctx.fetch(h, rel_path=f"discovery/home_{safe_name(_host(h))}.html", note=_note(role="home", rm=rm))
        if r.ok and r.content:
            for u, txt in _links(r.content, r.url or h):
                if re.search(r"(^|[/.])bip[./-]|/bip/?$|biuletyn", u, re.I) or re.fullmatch(r"(?i)bip|biuletyn.*", txt):
                    if _host(u) not in GENERIC_BIP_HOSTS and "gov.pl/web/bip" not in u.lower() and \
                            not NOT_BUYER_HOST.search(_host(u)):
                        cands.append({"url": _norm_base(u), "confidence": 0.8, "how": f"BIP link on homepage {h}"})
        host = _host(h).removeprefix("www.")
        cands.append({"url": f"https://bip.{host}/", "confidence": 0.6, "how": f"pattern bip.<homepage host> ({host})"})
    gs = slug(place_name(p.get("buyer_name") or "")).replace("-", "")
    if gs and (p.get("buyer_name") or "").lower().startswith("gmina"):
        for pat in (f"https://bip.gmina{gs}.pl/", f"https://bip.ug{gs}.pl/", f"https://bip.{gs}.pl/",
                    f"https://{gs}.biuletyn.net/", f"https://ug{gs}.bip.gov.pl/", f"https://bip.ug-{gs}.pl/"):
            cands.append({"url": pat, "confidence": 0.5, "how": "common BIP host naming pattern"})
    for c in list(cands):
        c["url"] = _bip_root(c["url"])
        if "://www." in c["url"]:
            cands.append({**c, "url": c["url"].replace("://www.", "://", 1), "confidence": round(c["confidence"] - 0.02, 2),
                          "how": c["how"] + " (without www.)"})
    cands = [c for c in cands if not NOT_BUYER_HOST.search(_host(c["url"]))]
    # dedupe by host keeping the highest confidence
    best: dict[str, dict] = {}
    for c in cands:
        k = _host(c["url"]) + urllib.parse.urlsplit(c["url"]).path.rstrip("/")
        if k not in best or c["confidence"] > best[k]["confidence"]:
            best[k] = c
    ordered = sorted(best.values(), key=lambda c: -c["confidence"])
    chosen = None
    for c in ordered:
        if not _resolves(c["url"]):
            c["status"] = "dns_unresolved"
            c["validated"] = False
            continue
        ok, _ = ctx.check_robots(c["url"])
        r = ctx.fetch(c["url"], rel_path=f"discovery/{safe_name(_host(c['url']))}_{hashlib.sha1(c['url'].encode()).hexdigest()[:6]}.html",
                      note=_note(role="validate", rm=rm, host=_host(c["url"])))
        c["status"] = r.status
        gslug = slug(place_name(p.get("buyer_name") or "")).replace("-", "")
        in_host = bool(gslug) and gslug[:5] in (r.url or c["url"]).lower().replace("-", "")
        c["validated"] = bool(r.ok and _is_bip_page(r.content) and (_mentions_buyer(r.content, p) or in_host))
        c["final_url"] = r.url if r.ok else None
        if c["validated"] and chosen is None:
            chosen = dict(c)
            chosen["url"] = _bip_root(_norm_base(r.url or c["url"]))
            break
        if not ok and chosen is None:
            c["note"] = "robots.txt disallows"
    result = {"rm_id": rm, "buyer_nip": p.get("buyer_nip"), "buyer_name": p.get("buyer_name"),
              "candidates": ordered, "chosen": chosen}
    ctx.save_derived(f"discovery/{rm}.json", json.dumps(result, ensure_ascii=False, indent=1).encode(),
                     url=f"pilot:{rm}", note=_note(role="discovery", rm=rm,
                                                   host=_host(chosen["url"]) if chosen else None))
    return result


# ---------------------------------------------------------------------------------------------
# crawl
# ---------------------------------------------------------------------------------------------

def _score(url: str, text: str, terms_all: list[dict]) -> tuple[int, list[str]]:
    s = ascii_fold(urllib.parse.unquote(url) + " " + (text or "")).lower()
    raw = (url + " " + (text or ""))
    hits: list[str] = []
    for terms in terms_all:
        hits += _match_terms(s, terms, raw)
    score = 6 * len(set(hits))
    if TOPIC.search(s):
        score += 3
    if FIN.search(s):
        score += 3
    if COMMITTEE.search(s) or REGISTRY.search(s):
        score += 2
    if SWZ_RE.search(s):
        score += 1
    return score, sorted(set(hits))


def _sitemap_urls(ctx: ScrapeContext, base: str, host_tag: str) -> list[tuple[str, str]]:
    origin = f"{urllib.parse.urlsplit(base).scheme}://{_host(base)}"
    r = ctx.fetch(origin + "/robots.txt", rel_path=f"{host_tag}/robots.txt", note=_note(role="robots", host=host_tag),
                  check_blocked=False, accept_status=(200, 403, 404, 410))
    maps = []
    if r.ok and r.http_status == 200 and "html" not in (r.content_type or ""):
        maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text())
    if not maps:
        maps = [origin + "/sitemap.xml"]
    out: list[tuple[str, str]] = []
    seen = set()
    queue = list(dict.fromkeys(maps))
    n = 0
    while queue and n < SITEMAP_CAP:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        n += 1
        r = ctx.fetch(sm, rel_path=f"{host_tag}/sitemap_{n}.xml", note=_note(role="sitemap", host=host_tag),
                      accept_status=(200, 404, 410))
        if not r.ok or r.http_status != 200 or not r.content or b"<loc" not in r.content[:500_000]:
            continue
        txt = r.text()
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", txt, re.S)
        if "<sitemapindex" in txt[:2000]:
            # newest child sitemaps first (often one per year/section)
            queue += [P.htmllib.unescape(x) for x in locs[::-1]]
        else:
            out += [(P.htmllib.unescape(x), "") for x in locs]
    return out


def crawl_bip(ctx: ScrapeContext, base: str, terms_all: list[dict]) -> dict:
    host_tag = safe_name(_host(base))
    st = {"base": base, "sitemap_urls": 0, "nav_pages": 0, "pages": 0, "docs": 0, "blocked": 0, "mode": ""}
    ok, why = ctx.check_robots(base)
    if not ok:
        ctx.record(base, "blocked", note=_note(role="bip_home", host=host_tag) + f" {why}")
        st["blocked"] += 1
        st["mode"] = "blocked"
        return st
    cand: dict[str, tuple[int, list[str], str]] = {}
    sm = _sitemap_urls(ctx, base, host_tag)
    st["sitemap_urls"] = len(sm)
    if sm:
        st["mode"] = "sitemap"
        for u, _ in sm:
            if _host(u).removeprefix("www.") != _host(base).removeprefix("www."):
                continue
            sc, hits = _score(u, "", terms_all)
            if sc >= 6 or FIN.search(ascii_fold(urllib.parse.unquote(u))):
                cand[u] = (sc, hits, "")
    # navigation crawl (always for the home page; deeper when there is no usable sitemap)
    home = ctx.fetch(base, rel_path=f"{host_tag}/home.html", note=_note(role="bip_home", host=host_tag))
    if home.ok and home.content and len(home.content) < 8000 and re.search(
            rb'id="root"|data-ng-app|/static/js/main', home.content):
        st["spa"] = True      # JavaScript-only BIP: no crawlable HTML (sitemap is the only way in)
    nav_queue: list[tuple[str, int]] = []
    seen_nav = {base}
    if home.ok and home.content:
        for u, txt in _links(home.content, home.url or base):
            if _host(u).removeprefix("www.") != _host(base).removeprefix("www."):
                continue
            sc, hits = _score(u, txt, terms_all)
            if sc >= 6:
                cand.setdefault(u, (sc, hits, txt))
            if SECTION.search(ascii_fold(txt) + " " + ascii_fold(u)) and not DOC_LINK.search(u):
                nav_queue.append((u, 1))
    nav_queue.sort(key=lambda x: 0 if re.search(r"wpf|wieloletn|budzet|zamowien|przetarg|rejestr|zarzadzen|uchwal",
                                                  ascii_fold(x[0]).lower()) else 1)
    if not sm or len(cand) < 5:
        st["mode"] = st["mode"] or "navigation"
        nav_n = 0
        while nav_queue and nav_n < NAV_CAP:
            u, depth = nav_queue.pop(0)
            if u in seen_nav:
                continue
            seen_nav.add(u)
            ok, why = ctx.check_robots(u)
            if not ok:
                continue
            r = ctx.fetch(u, rel_path=f"{host_tag}/nav_{hashlib.sha1(u.encode()).hexdigest()[:10]}.html",
                          note=_note(role="nav", host=host_tag))
            nav_n += 1
            if not r.ok or not r.content or "html" not in (r.content_type or "html"):
                continue
            for u2, txt in _links(r.content, r.url or u):
                if _host(u2).removeprefix("www.") != _host(base).removeprefix("www."):
                    continue
                sc, hits = _score(u2, txt, terms_all)
                if sc >= 6 or (sc >= 3 and (FIN.search(ascii_fold(txt)) or TOPIC.search(ascii_fold(txt)))):
                    cand.setdefault(u2, (sc, hits, txt))
                if depth < 2 and SECTION.search(ascii_fold(txt)) and u2 not in seen_nav and not DOC_LINK.search(u2):
                    nav_queue.append((u2, depth + 1))
        st["nav_pages"] = nav_n
    # detail pages + attachments, best first
    ranked = sorted(cand.items(), key=lambda kv: -kv[1][0])
    n_pages = n_docs = n_fin = n_topic = 0
    for u, (sc, hits, txt) in ranked:
        is_doc = bool(DOC_LINK.search(u))
        if is_doc:
            if n_docs >= DOC_CAP:
                continue
            if _fetch_doc(ctx, u, host_tag, txt, None):
                n_docs += 1
            continue
        if n_pages >= PAGE_CAP:
            continue
        fin_only = not hits and bool(FIN.search(ascii_fold(urllib.parse.unquote(u) + " " + txt)))
        if fin_only:
            if n_fin >= FIN_PAGE_CAP:
                continue
            n_fin += 1
        elif not hits:
            if n_topic >= TOPIC_PAGE_CAP:
                continue
            n_topic += 1
        ok, why = ctx.check_robots(u)
        if not ok:
            st["blocked"] += 1
            continue
        r = ctx.fetch(u, rel_path=f"{host_tag}/page_{hashlib.sha1(u.encode()).hexdigest()[:10]}.html",
                      note=_note(role="page", host=host_tag, key=hashlib.sha1(u.encode()).hexdigest()[:12]))
        n_pages += 1
        if not r.ok or not r.content:
            continue
        if not ("html" in (r.content_type or "") or r.content[:200].lstrip().startswith(b"<")):
            continue
        ptxt = _html_text(r.content)
        page_relevant = _score(u, ptxt[:20000], terms_all)[0] >= 6 or (
            TOPIC.search(ptxt) and (FIN.search(ptxt) or COMMITTEE.search(ptxt) or REGISTRY.search(ptxt)))
        page_fin = bool(FIN.search(ascii_fold(ptxt[:5000])))
        n_here = 0
        for u2, t2 in _links(r.content, r.url or u):
            if not DOC_LINK.search(u2) or n_docs >= DOC_CAP or n_here >= 4:
                continue
            sc2, _ = _score(u2, t2, terms_all)
            lt = ascii_fold(t2 + " " + urllib.parse.unquote(u2)).lower()
            want = sc2 >= 3 or (page_relevant and re.search(r"zalacznik|uchwa|zarz", lt)) or (
                page_fin and re.search(r"zalacznik\w*\s*(nr\s*)?2|przedsiewzi|wykaz", lt))
            if want and _fetch_doc(ctx, u2, host_tag, t2, u):
                n_docs += 1
                n_here += 1
    st["pages"], st["docs"] = n_pages, n_docs
    return st


_TEXT_DONE: set[str] = set()
FIN_PAGE_CAP = 8


def _fetch_doc(ctx: ScrapeContext, url: str, host_tag: str, link_text: str, parent: str | None) -> bool:
    ok, why = ctx.check_robots(url)
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    if not ok:
        ctx.record(url, "blocked", note=_note(role="doc", host=host_tag, key=key) + f" {why}")
        return False
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]) or "doc"
    r = ctx.fetch(url, rel_path=f"{host_tag}/docs/{key}_{safe_name(name, 80)}", check_blocked=False,
                  note=_note(role="doc", host=host_tag, key=key, parent=hashlib.sha1((parent or "").encode()).hexdigest()[:12]
                             if parent else None))
    if not r.ok or not r.content:
        return False
    if len(r.content) > DOC_MAX_BYTES:
        return True
    ext = P.sniff_ext(r.content, name)
    if ext in P.TEXT_EXTS and ext not in (".html", ".htm"):
        if key not in _TEXT_DONE:
            _TEXT_DONE.add(key)
            text, pages, method = P.extract_text(r.content, ext)
            ctx.save_derived(f"{host_tag}/text/{key}.txt", text.encode("utf-8"), url=url,
                             note=_note(role="text", host=host_tag, key=key),
                             extra={"pages": pages, "method": method, "chars": len(text), "link_text": link_text[:300],
                                    "parent_url": parent})
    return True


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------

def run(ctx: ScrapeContext, *, since: str | None = None, until: str | None = None, limit: int | None = None,
        only: list[str] | None = None, **opts: Any) -> dict:
    for e in ctx.store.entries():
        n = _pnote(e.get("note"))
        if n.get("role") == "text" and e.get("status") == "ok":
            _TEXT_DONE.add(n.get("key", ""))
    projects = _pilot()
    if only:
        projects = [p for p in projects if p["rm_id"] in set(only)]
    if limit:
        projects = projects[: int(limit)]
    # reference numbers (e-Zamówienia read API) for keyword matching
    refs: dict[str, str | None] = {}
    for p in projects:
        ref = None
        if p.get("tender_id"):
            r = ctx.fetch(EZ_TENDER, params={"id": p["tender_id"]}, rel_path=f"ezamowienia/{p['rm_id']}.json",
                          note=_note(role="ezgov_tender", rm=p["rm_id"]), min_interval=2.5)
            if r.ok:
                try:
                    ref = (r.json() or {}).get("referenceNumber")
                except ValueError:
                    ref = None
        refs[p["rm_id"]] = ref
    bzp = _bzp_urls(projects)
    ctx.save_derived("discovery/bzp_declared_urls.json", json.dumps(bzp, ensure_ascii=False, indent=1).encode(),
                     url="bzp_copy:" + str(settings().bzp_copy_path), note=_note(role="bzp_urls"))
    # discovery: one per buyer (NIP), shared by its projects
    by_buyer: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        by_buyer[p.get("buyer_nip") or p["rm_id"]].append(p)
    disc: dict[str, dict] = {}
    for nip, ps in by_buyer.items():
        urls = sorted({u for p in ps for u in bzp.get(p["rm_id"], [])})
        d = discover(ctx, ps[0], urls)
        for p in ps:
            dd = {**d, "rm_id": p["rm_id"]}
            disc[p["rm_id"]] = dd
            if p is not ps[0]:
                ctx.save_derived(f"discovery/{p['rm_id']}.json", json.dumps(dd, ensure_ascii=False, indent=1).encode(),
                                 url=f"pilot:{p['rm_id']}", note=_note(role="discovery", rm=p["rm_id"],
                                 host=_host(d["chosen"]["url"]) if d.get("chosen") else None))
    _write_buyers_csv(projects, disc)
    # crawl each BIP once, in parallel across hosts
    bases: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        ch = disc[p["rm_id"]].get("chosen")
        if ch:
            bases[ch["url"]].append(p)
    out: dict[str, Any] = {"projects": len(projects), "bips": len(bases), "per_bip": {}}

    def work(base: str, ps: list[dict]) -> tuple[str, dict]:
        terms_all = [project_terms(p, refs.get(p["rm_id"])) for p in ps]
        try:
            return base, crawl_bip(ctx, base, terms_all)
        except Exception as e:  # noqa: BLE001
            log.exception("bip crawl %s", base)
            ctx.record(base, "error", note=_note(role="bip_home", host=safe_name(_host(base))) + f" {type(e).__name__}: {e}"[:300])
            return base, {"error": str(e)[:300]}

    with ThreadPoolExecutor(max_workers=int(opts.get("workers", 4))) as ex:
        futs = [ex.submit(work, b, ps) for b, ps in bases.items()]
        for f in as_completed(futs):
            b, s = f.result()
            out["per_bip"][b] = s
    out["no_bip"] = [p["rm_id"] for p in projects if not disc[p["rm_id"]].get("chosen")]
    return out


def _write_buyers_csv(projects: list[dict], disc: dict[str, dict]) -> None:
    path = settings().ref_dir / "buyers_bip.csv"
    rows = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            rows = {r["rm_id"]: r for r in csv.DictReader(fh)}
    for p in projects:
        d = disc[p["rm_id"]]
        ch = d.get("chosen") or {}
        rows[p["rm_id"]] = {"rm_id": p["rm_id"], "buyer_nip": p.get("buyer_nip"), "buyer_name": p.get("buyer_name"),
                            "bip_url": ch.get("url", ""), "confidence": ch.get("confidence", 0.0),
                            "how_found": ch.get("how", "not found: " + "; ".join(
                                f"{c['url']} ({c.get('status')})" for c in d.get("candidates", [])[:4]))}
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["rm_id", "buyer_nip", "buyer_name", "bip_url", "confidence", "how_found"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


# ---------------------------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------------------------

def parse(store: RawStore) -> Iterable[DocumentRecord | SourceCheck]:
    entries = store.entries()
    disc: dict[str, dict] = {}
    refs: dict[str, str | None] = {}
    by_host: dict[str, list[dict]] = defaultdict(list)
    texts: dict[tuple[str, str], dict] = {}
    for e in entries:
        n = _pnote(e.get("note"))
        e["_n"] = n
        role = n.get("role")
        if role == "discovery" and e.get("status") == "ok":
            b = _read(e.get("path"))
            if b:
                d = json.loads(b)
                disc[d["rm_id"]] = d
        elif role == "ezgov_tender" and e.get("status") == "ok":
            b = _read(e.get("path"))
            try:
                refs[n.get("rm", "")] = (json.loads(b or b"null") or {}).get("referenceNumber")
            except ValueError:
                pass
        elif role in ("page", "doc", "nav", "bip_home", "sitemap", "robots", "validate"):
            by_host[n.get("host", "")].append(e)
        elif role == "text" and e.get("status") == "ok":
            texts[(n.get("host", ""), n.get("key", ""))] = e
    platforms_blocked = ("platformazakupowa", "logintrade")
    for p in _pilot():
        rm = p["rm_id"]
        d = disc.get(rm)
        if d is None:
            continue
        ch = d.get("chosen")
        terms = project_terms(p, refs.get(rm))
        blocked_platform = any(any(x in u for x in platforms_blocked) for u in p.get("platform_urls") or [])
        base_data = {"buyer": p.get("buyer_name"), "ocid": p.get("tender_id"), "bip_url": ch.get("url") if ch else None,
                     "bip_confidence": ch.get("confidence") if ch else None, "terms": terms}
        if not ch:
            yield SourceCheck(source=SOURCE, subject_type="project", subject_key=rm, query={"candidates": [
                c["url"] for c in d.get("candidates", [])]}, n_hits=0, result="error",
                note="BIP base URL not found/validated (candidates: " + "; ".join(
                    f"{c['url']}={c.get('status')}" for c in d.get("candidates", [])[:5]) + ")")
            continue
        host_tag = safe_name(_host(ch["url"]))
        es = by_host.get(host_tag, [])
        recs: list[DocumentRecord] = []
        seen = set()
        n_pages = n_docs = 0
        blocked = [e for e in es if e.get("status") == "blocked"]
        for e in es:
            role = e["_n"].get("role")
            if role not in ("page", "doc") or e.get("status") != "ok" or e["url"] in seen:
                continue
            seen.add(e["url"])
            b = _read(e.get("path"))
            if b is None:
                continue
            text_path = None
            pages = None
            if role == "page":
                n_pages += 1
                text = _html_text(b)
                kind = "page"
            else:
                n_docs += 1
                te = texts.get((host_tag, e["_n"].get("key", "")))
                text = (_read(te.get("path")) or b"").decode("utf-8", "replace") if te else ""
                text_path = te.get("path") if te else None
                pages = te.get("pages") if te else None
                kind = "attachment"
            link_text = (texts.get((host_tag, e["_n"].get("key", ""))) or {}).get("link_text") or ""
            hay = ascii_fold(urllib.parse.unquote(e["url"]) + " " + link_text + " " + text[:200_000]).lower()
            hits = _match_terms(hay, terms, text[:200_000] + " " + link_text)
            ref_hit = any(h in terms.get("refs", []) for h in hits)
            # water/sewage words must occur near the place name (menus mention "wodociągi" on every page)
            topic = False
            head = ascii_fold(urllib.parse.unquote(e["url"]) + " " + link_text + " " + (_title_of(b) if kind == "page" else "")).lower()
            if TOPIC.search(head):
                topic = True
            for h in hits:
                for m in re.finditer(re.escape(ascii_fold(h).lower()), hay):
                    if TOPIC.search(hay[max(0, m.start() - 400): m.start() + 400]):
                        topic = True
                        break
                if topic:
                    break
            if not hits and kind == "attachment":
                topic = bool(TOPIC.search(hay))
            if hits and not (topic or ref_hit):
                hits = []          # place name alone (e.g. a playground in the same village) is not enough
            if not hits and not (topic and kind == "attachment" and WPF_STRICT.search(hay)):
                continue
            title_txt = _title_of(b) if kind == "page" else ""
            cat = categorize(urllib.parse.unquote(e["url"]) + " " + link_text + " " + title_txt)
            if cat == "inne" and kind == "attachment":
                cat = categorize(text[:1500])
            swz_mirror = cat == "swz" and bool(hits)
            snippet = ""
            if hits:
                i = hay.find(ascii_fold(hits[0]).lower())
                snippet = P.scrub(text[max(0, i - 150): i + 250]) if i >= 0 else ""
            needs_ocr = bool(kind == "attachment" and text_path and pages and len(text.strip()) < 100 * pages)
            note = "BIP page mentioning the project" if kind == "page" else "BIP attachment mentioning the project"
            if not hits:
                note = "BIP financial-plan attachment (WPF/przedsięwzięcia) mentioning water/sewage works; project not named"
            if swz_mirror and blocked_platform:
                note += "; mirrors tender documents that are robots-blocked on the procurement platform"
            recs.append(DocumentRecord(
                source=SOURCE, subject_type="project", subject_key=rm, doc_type=cat,
                title=(link_text or _title_of(b) or e["url"])[:300] if kind == "attachment" else (_title_of(b) or e["url"])[:300],
                filename=urllib.parse.unquote(urllib.parse.urlsplit(e["url"]).path.rsplit("/", 1)[-1])[:200] or None,
                url=e["url"], raw_path=e.get("path"), raw_sha256=e.get("sha256"), text_path=text_path, pages=pages,
                fetch_state="found", note=note,
                data={**base_data, "kind": kind, "category": cat, "matched_terms": hits, "water_sewage_topic": topic,
                      "swz_mirror": swz_mirror, "snippet": snippet, "needs_ocr": needs_ocr or None,
                      "relevance": "named" if hits else "topic_only"}))
        yield from recs
        named = [r for r in recs if r.data.get("relevance") == "named"]
        if named:
            result = "found"
        elif recs:
            result = "partial"
        elif blocked and not (n_pages or n_docs):
            result = "blocked"
        else:
            result = "not_found"
        spa = False
        for e in es:
            if e["_n"].get("role") in ("bip_home", "validate") and e.get("status") == "ok" and not spa:
                hb = _read(e.get("path")) or b""
                spa = len(hb) < 8000 and bool(re.search(rb'id="root"|data-ng-app|/static/js/main', hb))
        ts = [e.get("fetched_at") for e in es if e.get("fetched_at")]
        if spa and not recs:
            result = "blocked" if not (n_pages or n_docs) else result
        yield SourceCheck(
            source=SOURCE, subject_type="project", subject_key=rm,
            query={"bip_url": ch["url"], "terms": terms}, n_hits=len(recs), n_relevant=len(named), result=result,
            matched_ids=sorted({r.doc_type for r in named if r.doc_type}),
            note=(("JavaScript-only BIP (no crawlable HTML, no sitemap): content not reachable without running its "
                   "front-end; " if spa and not (n_pages or n_docs) else "") +
                  f"bip={ch['url']} (confidence {ch.get('confidence')}, {ch.get('how')}); pages fetched={n_pages}, "
                  f"attachments={n_docs}, blocked={len(blocked)}; categories="
                  f"{sorted({r.doc_type for r in recs})}; swz_mirror={any(r.data.get('swz_mirror') for r in recs)}")[:1000],
            checked_at=datetime.strptime(max(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if ts else None)


def _read(rel: str | None) -> bytes | None:
    p = _abs_path(rel)
    return p.read_bytes() if p and p.exists() else None


def _title_of(b: bytes) -> str:
    m = re.search(rb"<title[^>]*>(.*?)</title>", b[:50_000], re.S | re.I)
    return P.norm_ws(m.group(1).decode("utf-8", "replace")) if m else ""
