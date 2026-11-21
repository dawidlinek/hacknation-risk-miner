"""KIO rulings (orzeczenia.uzp.gov.pl) - docs/scrape.md §2 `kio`, §3.5.

Two jobs, both resumable (every request is cached by the raw store):

* buyers   - exact-phrase search for each of the 20 pilot buyers (e.g. `"Gmina Nowogard"`), drop
             items with lexical relevance 0, fetch Details for the rest and keep a hit only when the
             Details `Zamawiający` matches the buyer (name collisions handled: city vs rural gmina,
             Kamionka vs Kamionka Wielka, two Bobrowniki / Zakrzew / Zduny -> text context check).
             Emits a SourceCheck per buyer NIP and per pilot project, LinkHints for verified matches
             (and weak "mentioned in text" hints for rulings of other buyers that cite the buyer).
* national - water/sewage corpus: phrases "kanalizacji sanitarnej", "sieci wodociągowej",
             "oczyszczalni ścieków", "stacji uzdatniania wody" -> Details + full text per relevant hit.
             Text source: `content=html` (default; /Home/ContentHtml, ~0.1 s, same text as the PDF) or
             `content=pdf` (/Home/PdfContent ~300 KB, ~5 s server time each -> ~4 h for the corpus).
             Per-buyer name matches always get the PDF.

Options (`--opt k=v`): mode=all|buyers|national, phrases=[...], max_pages=N, pdf=true|false (text at all),
content=html|pdf (national text source).
`--limit N` caps the number of rulings fetched (Details+PDF) in national mode; `--only` filters
buyers by NIP or rm_id (or national phrases by substring). `--since/--until` -> `Dt` date filter.

Network: every call goes through ctx.fetch (1 req/s). RODO: the chairman's name shown on Details is
not copied into records; KIO pseudonymises natural-person parties in the texts.
"""
from __future__ import annotations

import html as htmlmod
import json
import logging
import re
import subprocess
import tempfile
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext, request_key
from riskminer.connectors.records import ExternalRecord, LinkHint, SourceCheck

log = logging.getLogger("riskminer.connectors.kio")

SOURCE = "kio"
DEFAULTS: dict[str, Any] = {"min_interval": 1.0, "timeout": 90.0}

BASE = "https://orzeczenia.uzp.gov.pl"
SEARCH_URL = f"{BASE}/Home/GetResults"
PAGE_SIZE = 10
NATIONAL_PHRASES = ["kanalizacji sanitarnej", "sieci wodociągowej", "oczyszczalni ścieków", "stacji uzdatniania wody"]
XHR = {"X-Requested-With": "XMLHttpRequest"}

WODKAN_RE = re.compile(r"kanalizac|wodoci[aą]g|oczyszczal|ściek|uzdatnian|przepompown|sieci wodoc|deszczow", re.I)

# Buyers whose plain name collides with another gmina of the same name: the ruling text must carry
# a positive context marker (powiat / postal code / NIP) and no negative one.
CONTEXT: dict[str, tuple[str, str]] = {
    "6252446477": (r"będzi|bedzi|42-58\d|6252446477|625-244-64-77", r"lipno|lipnow|87-61\d"),          # Bobrowniki (śląskie)
    "7962959318": (r"radomsk|radom\b|26-652|7962959318|796-295-93-18", r"lubelsk|23-21\d|bełżyc"),     # Zakrzew (mazowieckie)
    "6211694095": (r"krotosz|63-760|6211694095|621-169-40-95", r"łowic|lowic|99-4\d\d"),                # Zduny (wielkopolskie)
}
CITY_COLLISION = {"9121715754", "6871783356", "5783105254"}   # Gmina Oława / Sanok / Elbląg (rural vs city)


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _norm(s: str | None) -> str:
    s = htmlmod.unescape(s or "")
    s = s.replace("​", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", _norm(s).lower().replace("ł", "l"))
    return "".join(c for c in s if not unicodedata.combining(c))


def _date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7,
          "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10, "pazdziernika": 10, "listopada": 11,
          "grudnia": 12}


def _text_date(text: str | None) -> date | None:
    """Ruling date from the header ('Warszawa, dnia 13 sierpnia 2025 r.' / 'z dnia 23 sierpnia 2022 r.')."""
    if not text:
        return None
    m = re.search(r"dni(?:a|u)\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text[:1500], re.I)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def _float(s: str | None) -> float | None:
    try:
        return float((s or "").replace(",", "."))
    except ValueError:
        return None


def pilot_projects() -> list[dict]:
    p = settings().ref_dir / "pilot_projects.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def buyer_phrase(name: str) -> str:
    name = _norm(name)
    if "Zarząd Dróg Wojewódzkich" in name:
        return "Wielkopolski Zarząd Dróg Wojewódzkich"
    name = re.split(r"\s+-\s+|,", name)[0].strip()
    return name


def buyers() -> dict[str, dict]:
    """NIP -> {name, phrase, city, rm_ids, projects}"""
    out: dict[str, dict] = {}
    for p in pilot_projects():
        b = out.setdefault(p["buyer_nip"], {"nip": p["buyer_nip"], "name": p["buyer_name"],
                                             "phrase": buyer_phrase(p["buyer_name"]), "city": p.get("buyer_city"),
                                             "rm_ids": [], "projects": []})
        b["rm_ids"].append(p["rm_id"])
        b["projects"].append(p)
    return out


def _core_regex(phrase: str) -> re.Pattern:
    core = re.sub(r"^gmina\s+", "", _fold(phrase))
    parts = []
    for w in core.split():
        parts.append(re.escape(w[:-1] if len(w) > 4 else w) + r"\w*")
    return re.compile(r"\b" + r"\W+".join(parts), re.I)


def zamawiajacy_match(nip: str, phrase: str, zam: str, text: str = "") -> tuple[str, str]:
    """-> (verdict, reason) with verdict in match | ambiguous | no."""
    z = _fold(zam)
    if not z:
        return "no", "no Zamawiający on Details"
    if "zarzad drog wojew" in _fold(phrase):
        ok = ("wielkopolski zarzad drog wojew" in z) or "wzdw" in z
        return ("match", "WZDW name") if ok else ("no", "different buyer")
    if not _core_regex(phrase).search(z):
        return "no", "buyer name not in Zamawiający"
    if not re.search(r"gmin|urzad|wojt|burmistrz", z):
        return "no", "name only as a place (not the gmina itself)"
    if "kamionka" in _fold(phrase) and "kamionka wielka" in z:
        return "no", "Kamionka Wielka (different gmina)"
    if "zakrzew" in _fold(phrase) and re.search(r"zakrzewo\b", z) and not re.search(r"zakrzew(a|ie)?\b", z):
        return "no", "Zakrzewo (different gmina)"
    core = re.sub(r"^gmina\s+", "", _fold(phrase))
    if re.search(r"zwiazek|zwiazk|spolka|sp\. z o|przedsiebiorstw|zaklad", z) and \
            not re.search(r"(gmin[aey]?|gmine)\s+" + _core_regex(core).pattern.lstrip("\\b"), z):
        return "no", "different entity (union/company) named after the place"
    if nip in CITY_COLLISION and re.search(r"miast|miejsk|powiat", z):
        return "no", "city/powiat, not the rural gmina"
    if nip in CONTEXT:
        pos, neg = CONTEXT[nip]
        t = text or ""
        if re.search(neg, t, re.I) and not re.search(pos, t, re.I):
            return "no", "same-name gmina in another voivodeship (text context)"
        if re.search(pos, t, re.I):
            return "match", "name + text context"
        return "ambiguous", "same-name gmina exists; no context marker in text"
    return "match", "name"


# ---------------------------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------------------------
def parse_search(html: str) -> dict:
    tree = HTMLParser(html)
    total = None
    rc = tree.css_first("span.result-count-info")
    if rc:
        m = re.search(r"(\d+)", rc.text())
        total = int(m.group(1)) if m else None
    last_page = 1
    for a in tree.css("ul.pagination a[data-page]"):
        try:
            last_page = max(last_page, int(a.attributes.get("data-page") or 1))
        except ValueError:
            pass
    items = []
    for it in tree.css("div.search-list-item"):
        a = it.css_first("a.link-details")
        if not a:
            continue
        m = re.search(r"/Home/Details/(\d+)", a.attributes.get("href") or "")
        if not m:
            continue
        rec: dict[str, Any] = {"id": m.group(1)}
        for p in it.css("p"):
            lab = p.css_first("label")
            if not lab:
                continue
            k = _norm(lab.text()).rstrip(":")
            v = _norm(p.text()).replace(_norm(lab.text()), "", 1).strip()
            if k.startswith("Rodzaj dokumentu"):
                rec["doc_type"] = v
            elif k.startswith("Sygnatura"):
                rec["sygnatura"] = v
            elif k.startswith("Data wydania"):
                rec["date"] = v
        org = it.css_first("div.search-result-item__rate-wrapper")
        if org:
            rec["organ"] = _norm(org.text()).replace("Organ wydający:", "").strip()
        lex = sem = None
        for s in it.css("div.search-result-item__ranks small"):
            t = _norm(s.text())
            mm = re.search(r"semantycznego:\s*([\d.,]+)", t)
            if mm:
                sem = _float(mm.group(1))
                continue
            mm = re.search(r"wyszukiwania:\s*([\d.,]+)", t)
            if mm:
                lex = _float(mm.group(1))
        rec["lexical"] = lex
        rec["semantic"] = sem
        frag = it.css_first("p.fragment")
        rec["fragment"] = _norm(frag.text())[:600] if frag else None
        items.append(rec)
    return {"total": total, "last_page": last_page, "items": items}


def parse_details(html: str) -> dict:
    tree = HTMLParser(html)
    out: dict[str, Any] = {}
    h = tree.css_first("h2.section-title")
    if h:
        out["title_sygnatura"] = _norm(h.text()).replace("Pobierz metrykę PDF", "").strip()
    fields = {"Organ wydający": "organ", "Rodzaj dokumentu": "doc_type", "Data wydania": "date",
              "Zamawiający": "zamawiajacy", "Miejscowość": "miejscowosc", "Tryb postępowania": "tryb",
              "Rodzaj zamówienia": "rodzaj_zamowienia"}
    box = tree.css_first("div.details-metrics") or tree
    for p in box.css("p"):
        lab = p.css_first("label")
        if not lab:
            continue
        k = _norm(lab.text())
        v = _norm(p.text()).replace(k, "", 1).strip()
        for pref, key in fields.items():
            if k.startswith(pref):
                out[key] = v
    sygs = []
    for li in box.css("ul li"):
        t = _norm(li.text())
        if "/" in t:
            s, _, outcome = t.rpartition(" / ")
            for one in re.split(r"\s*[|;,]\s*", s.strip() or t):
                if one:
                    sygs.append({"sygnatura": one, "outcome": outcome.strip()})
    out["sygnatury"] = sygs

    def section(title: str) -> str | None:
        m = re.search(r"<b>\s*" + re.escape(title) + r".*?</b>\s*<p[^>]*>(.*?)</p>", html, re.S)
        if not m:
            return None
        return _norm(re.sub(r"<[^>]+>", " ", m.group(1))) or None

    arts = section("Kluczowe przepisy ustawy Pzp")
    out["articles"] = [a.strip() for a in re.split(r"[|;]", arts) if a.strip()] if arts else []
    th = section("Zagadnienia merytoryczne")
    out["thematic_index"] = [a.strip() for a in re.split(r"[|;]", th) if a.strip()] if th else []
    return out


def pdf_to_text(path: Path) -> str:
    try:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _fold(s)).strip("_")[:60]


def _search_form(phrase: str, page: int, dt: str | None) -> dict:
    f = {"Phrase": f'"{phrase}"', "Fle": "1", "SCnt": "1", "Kind": "KIO", "Pg": str(page),
         "CountStats": "True" if page == 1 else "False"}
    if dt:
        f["Dt"] = dt
    return f


def search_all(ctx: ScrapeContext, phrase: str, *, group: str, dt: str | None, max_pages: int | None) -> tuple[list[dict], int | None, list[str]]:
    items: list[dict] = []
    total = None
    errors: list[str] = []
    page, last = 1, 1
    while page <= last:
        form = _search_form(phrase, page, dt)
        r = ctx.fetch(SEARCH_URL, method="POST", data=form, headers=XHR,
                      rel_path=f"search/{group}/{_slug(phrase)}/p{page:03d}.html",
                      note=f"kio search {group} phrase={phrase!r} page={page}")
        if not r.ok:
            errors.append(f"p{page}:{r.status}")
            if page == 1:
                break
            page += 1
            continue
        res = parse_search(r.text())
        if page == 1:
            total = res["total"]
            last = res["last_page"] if res["total"] else 0
            if total:
                last = max(last, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            if max_pages:
                last = min(last, max_pages)
        for it in res["items"]:
            it["page"] = page
            items.append(it)
        if not res["items"]:
            break
        page += 1
    return items, total, errors


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", html)
    txt = htmlmod.unescape(re.sub(r"<[^>]+>", " ", html)).replace("\u200b", "")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in txt.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_ruling(ctx: ScrapeContext, rid: str, *, pdf: bool = True, content: str = "pdf") -> dict:
    """Details + full text. content='pdf' -> PdfContent (~300 KB, ~5 s server time) + pdftotext;
    content='html' -> ContentHtml (same text as served in the Details iframe, ~50 KB, ~0.1 s)."""
    out: dict[str, Any] = {"id": rid}
    d = ctx.fetch(f"{BASE}/Home/Details/{rid}", rel_path=f"details/{rid}.html", note=f"kio details {rid}")
    out["details_status"] = d.status
    if d.ok:
        out["details"] = parse_details(d.text())
    if pdf and content == "html":
        url = f"{BASE}/Home/ContentHtml/{rid}?Kind=KIO&flection=0"
        h = ctx.fetch(url, rel_path=f"html/{rid}.html", note=f"kio content html {rid}")
        out["html_status"] = h.status
        if h.ok:
            rel = f"text/{rid}.html.txt"
            key = request_key("DERIVED", url, {"p": rel})
            e = ctx.store.index().get(key)
            if not (e and e.get("path") and ctx.store.abs(e["path"]).exists()):
                text = html_to_text(h.text())
                ctx.save_derived(rel, text.encode("utf-8"), url=url, note=f"text of kio ContentHtml {rid}",
                                 status="ok" if text.strip() else "empty", extra={"derived_from": ctx.store.rel(h.path)})
    elif pdf:
        url = f"{BASE}/Home/PdfContent/{rid}?Kind=KIO"
        p = ctx.fetch(url, rel_path=f"pdf/{rid}.pdf", note=f"kio pdf {rid}", check_blocked=False)
        out["pdf_status"] = p.status
        if p.ok and p.path:
            out["text"] = _derive_text(ctx, url, rid, p.path)
    return out


def _derive_text(ctx: ScrapeContext, url: str, rid: str, pdf_path: Path) -> str:
    rel = f"text/{rid}.txt"
    key = request_key("DERIVED", url, {"p": rel})
    e = ctx.store.index().get(key)
    if e and e.get("path") and ctx.store.abs(e["path"]).exists():
        return ctx.store.abs(e["path"]).read_text(encoding="utf-8", errors="replace")
    text = pdf_to_text(pdf_path)
    ctx.save_derived(rel, text.encode("utf-8"), url=url, note=f"pdftotext of kio pdf {rid}",
                     status="ok" if text.strip() else "empty", extra={"derived_from": ctx.store.rel(pdf_path)})
    return text


def run(ctx: ScrapeContext, *, since: str | None = None, until: str | None = None, limit: int | None = None,
        only: list[str] | None = None, mode: str = "all", phrases: list[str] | None = None,
        max_pages: int | None = None, pdf: bool = True, content: str = "html", **opts: Any) -> dict:
    dt = None
    if since or until:
        f = datetime.strptime(since, "%Y-%m-%d").strftime("%d-%m-%Y") if since else "01-01-2000"
        t = datetime.strptime(until, "%Y-%m-%d").strftime("%d-%m-%Y") if until else date.today().strftime("%d-%m-%Y")
        dt = f"{f} - {t}"
    stats: dict[str, Any] = {"buyers": 0, "buyer_hits": 0, "buyer_details": 0, "national_hits": 0,
                             "national_rulings": 0}
    done: set[str] = set()

    if mode in ("all", "buyers"):
        for nip, b in buyers().items():
            if only and not (nip in only or any(r in only for r in b["rm_ids"])) and not any(o in ("buyers",) for o in only):
                continue
            stats["buyers"] += 1
            items, total, _err = search_all(ctx, b["phrase"], group="buyers", dt=dt, max_pages=max_pages)
            rel = [i for i in items if (i.get("lexical") or 0) > 0]
            stats["buyer_hits"] += len(rel)
            for it in rel:
                rid = it["id"]
                d = ctx.fetch(f"{BASE}/Home/Details/{rid}", rel_path=f"details/{rid}.html", note=f"kio details {rid}")
                stats["buyer_details"] += 1
                if not d.ok:
                    continue
                det = parse_details(d.text())
                verdict, _ = zamawiajacy_match(nip, b["phrase"], det.get("zamawiajacy", ""))
                # PDF for every name-match (needed for same-name disambiguation + project linking)
                if verdict != "no" or (nip in CONTEXT and _core_regex(b["phrase"]).search(_fold(det.get("zamawiajacy", "")))):
                    if pdf:
                        fetch_ruling(ctx, rid, pdf=True)
                    done.add(rid)
                elif pdf:   # ruling of another buyer that mentions this one: cheap HTML text only
                    fetch_ruling(ctx, rid, pdf=True, content="html")
            log.info("kio buyer %s %s: total=%s relevant=%s", nip, b["phrase"], total, len(rel))

    if mode in ("all", "national"):
        phr = phrases or NATIONAL_PHRASES
        if only:
            sel = [p for p in phr if any(o.lower() in p.lower() for o in only)]
            phr = sel or phr
        ids: list[str] = []
        seen: set[str] = set()
        for ph in phr:
            items, total, _err = search_all(ctx, ph, group="national", dt=dt, max_pages=max_pages)
            for it in items:
                if (it.get("lexical") or 0) > 0 and it["id"] not in seen:
                    seen.add(it["id"])
                    ids.append(it["id"])
            log.info("kio national %r: total=%s relevant_unique_so_far=%s", ph, total, len(ids))
        stats["national_hits"] = len(ids)
        n = 0
        for rid in ids:
            if limit and n >= limit:
                break
            fetch_ruling(ctx, rid, pdf=pdf, content=content)
            n += 1
            if n % 100 == 0:
                log.info("kio national rulings fetched: %s/%s", n, len(ids))
        stats["national_rulings"] = n
    return stats


# ---------------------------------------------------------------------------------------------
# parse (raw -> records, no network)
# ---------------------------------------------------------------------------------------------
def _latest(store: RawStore) -> list[dict]:
    idx = store.index()
    return [e for e in idx.values() if e.get("status") in ("ok", "empty") and e.get("path")]


def parse(store: RawStore) -> Iterable[Any]:
    entries = _latest(store)
    searches: dict[tuple[str, str], dict[int, dict]] = defaultdict(dict)    # (group, phrase) -> page -> entry
    details: dict[str, dict] = {}
    pdfs: dict[str, dict] = {}
    texts: dict[str, dict] = {}
    html_texts: dict[str, dict] = {}
    htmls: dict[str, dict] = {}
    for e in entries:
        url = e.get("url", "")
        path = e.get("path") or ""
        if url == SEARCH_URL and e.get("method") == "POST":
            body = e.get("body") or {}
            if isinstance(body, str):
                continue
            ph = (body.get("Phrase") or "").strip('"')
            group = "buyers" if "/search/buyers/" in path else "national"
            try:
                pg = int(body.get("Pg") or 1)
            except ValueError:
                pg = 1
            if body.get("Dt"):
                group += f"|{body['Dt']}"
            searches[(group, ph)][pg] = e
        elif "/Home/Details/" in url:
            details[url.rsplit("/", 1)[-1]] = e
        elif "/Home/PdfContent/" in url and e.get("method") == "DERIVED":
            texts[re.search(r"PdfContent/(\d+)", url).group(1)] = e
        elif "/Home/ContentHtml/" in url and e.get("method") == "DERIVED":
            html_texts[re.search(r"ContentHtml/(\d+)", url).group(1)] = e
        elif "/Home/ContentHtml/" in url:
            htmls[re.search(r"ContentHtml/(\d+)", url).group(1)] = e
        elif "/Home/PdfContent/" in url:
            pdfs[re.search(r"PdfContent/(\d+)", url).group(1)] = e

    for rid, e in html_texts.items():      # PDF-derived text wins; ContentHtml text otherwise
        texts.setdefault(rid, e)
    # search hits per id
    hits: dict[str, dict] = {}
    totals: dict[tuple[str, str], int | None] = {}
    first_page_entry: dict[tuple[str, str], dict] = {}
    items_by_query: dict[tuple[str, str], list[dict]] = {}
    for q, pages in searches.items():
        its: list[dict] = []
        for pg in sorted(pages):
            e = pages[pg]
            try:
                res = parse_search(store.abs(e["path"]).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if pg == 1:
                totals[q] = res["total"]
                first_page_entry[q] = e
            its.extend(res["items"])
        items_by_query[q] = its
        for it in its:
            if (it.get("lexical") or 0) <= 0:
                continue
            h = hits.setdefault(it["id"], {"phrases": [], "lexical": {}, "semantic": {}, "search": it})
            if q[1] not in h["phrases"]:
                h["phrases"].append(q[1])
            h["lexical"][q[1]] = it.get("lexical")
            h["semantic"][q[1]] = it.get("semantic")

    def read(e: dict | None) -> str:
        if not e:
            return ""
        try:
            return store.abs(e["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # rulings (ExternalRecord): every relevant id with Details
    parsed: dict[str, dict] = {}
    sig_count: dict[str, int] = defaultdict(int)
    for rid in hits:
        if rid not in details:
            continue
        det = parse_details(read(details[rid]))
        det["_text"] = read(texts.get(rid))
        parsed[rid] = det
        s0 = (det.get("sygnatury") or [{}])[0].get("sygnatura") or hits[rid]["search"].get("sygnatura") or f"id:{rid}"
        det["_sig"] = s0
        sig_count[s0] += 1

    ext_id: dict[str, str] = {}
    for rid, det in parsed.items():
        s0 = det["_sig"]
        eid = s0 if sig_count[s0] == 1 else f"{s0}#{rid}"
        ext_id[rid] = eid
        h = hits[rid]
        text = det.pop("_text") or None
        det.pop("_sig", None)
        pdf_e = pdfs.get(rid)
        groups = sorted({("buyers" if any(q[0].startswith("buyers") and q[1] == p for q in searches) else "national")
                         for p in h["phrases"]})
        data = {
            "kio_id": rid,
            "doc_type": det.get("doc_type") or h["search"].get("doc_type"),
            "sygnatury": det.get("sygnatury"),
            "outcome": "; ".join(sorted({s.get("outcome", "") for s in det.get("sygnatury") or [] if s.get("outcome")})) or None,
            "zamawiajacy": det.get("zamawiajacy"),
            "miejscowosc": det.get("miejscowosc"),
            "tryb": det.get("tryb"),
            "rodzaj_zamowienia": det.get("rodzaj_zamowienia") or None,
            "articles": det.get("articles"),
            "thematic_index": det.get("thematic_index"),
            "matched_phrases": h["phrases"],
            "search_groups": groups,
            "lexical_relevance": h["lexical"],
            "semantic_relevance": h["semantic"],
            "wodkan_text": bool(WODKAN_RE.search((text or "")[:20000])) if text else None,
            "pdf_raw_path": pdf_e.get("path") if pdf_e else None,
            "content_html_raw_path": htmls[rid].get("path") if rid in htmls else None,
            "text_basis": ("pdf" if rid in texts and "/PdfContent/" in texts[rid].get("url", "") else
                           "content_html" if rid in texts else None),
            "pdf_url": f"{BASE}/Home/PdfContent/{rid}?Kind=KIO",
            "text_path": texts[rid]["path"] if rid in texts else None,
            "details_raw_path": details[rid].get("path"),
        }
        pub_date = _date(det.get("date") or h["search"].get("date"))
        if pub_date is None:
            pub_date = _text_date(text)
            data["date_basis"] = "ruling text header" if pub_date else "missing on site"
        yield ExternalRecord(
            source=SOURCE, kind="kio_ruling", external_id=eid,
            title=f"{data['doc_type'] or 'orzeczenie'} {eid}" + (f" - {det.get('zamawiajacy')}" if det.get("zamawiajacy") else ""),
            published_on=pub_date,
            buyer_name=det.get("zamawiajacy"),
            url=f"{BASE}/Home/Details/{rid}",
            raw_path=details[rid].get("path"), raw_sha256=details[rid].get("sha256"),
            text=text, data=data,
        )

    # per-buyer / per-project checks
    for nip, b in buyers().items():
        qs = [q for q in searches if q[0] == "buyers" and q[1] == b["phrase"]]
        if not qs:
            continue
        q = qs[0]
        fe = first_page_entry.get(q)
        its = items_by_query.get(q, [])
        rel_ids = [i["id"] for i in its if (i.get("lexical") or 0) > 0]
        verified, ambiguous, mentions = [], [], []
        missing_details = 0
        for rid in dict.fromkeys(rel_ids):
            if rid not in parsed:
                missing_details += 1
                continue
            det = parsed[rid]
            v, why = zamawiajacy_match(nip, b["phrase"], det.get("zamawiajacy", ""), read(texts.get(rid)))
            row = {"id": rid, "ext": ext_id[rid], "zam": det.get("zamawiajacy"), "why": why, "date": det.get("date")}
            (verified if v == "match" else ambiguous if v == "ambiguous" else mentions).append(row)
        query = {"site": BASE, "endpoint": "/Home/GetResults", "Phrase": f'"{b["phrase"]}"', "Fle": 1, "SCnt": 1,
                 "Kind": "KIO", "filter": "lexical relevance > 0; Details Zamawiający must match buyer"}
        total = totals.get(q)
        checked = datetime.strptime(fe["fetched_at"], "%Y-%m-%dT%H:%M:%SZ") if fe else None
        status = "found" if verified else ("partial" if missing_details else "not_found")
        wodkan_v = [r["ext"] for r in verified if WODKAN_RE.search(read(texts.get(r["id"]))[:20000] or "")]
        note = (f"{total or 0} search results, {len(set(rel_ids))} with lexical relevance > 0; "
                f"{len(verified)} verified (Zamawiający = buyer), {len(wodkan_v)} of them water/sewage-related"
                + (f": {', '.join(wodkan_v[:10])}" if wodkan_v else "")
                + (f"; {len(ambiguous)} ambiguous same-name: {', '.join(r['ext'] for r in ambiguous[:10])}" if ambiguous else "")
                + (f"; {len(mentions)} rulings of other buyers mention the phrase" if mentions else "")
                + (f"; {missing_details} hits without Details fetched" if missing_details else ""))
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query=query,
                          n_hits=total or 0, n_relevant=len(verified), result=status,
                          matched_ids=[r["ext"] for r in verified], note=note, checked_at=checked,
                          raw_path=fe.get("path") if fe else None)
        for r in verified:
            yield LinkHint(source=SOURCE, left_type="organization", left_key=nip, right_type="external_record",
                           right_key=f"kio_ruling:{r['ext']}", method="buyer_name+details_zamawiajacy", score=0.8,
                           features={"zamawiajacy": r["zam"], "reason": r["why"], "phrase": b["phrase"]},
                           explanation=f"KIO Details 'Zamawiający' = {r['zam']!r} matches {b['name']}")
        for r in ambiguous:
            yield LinkHint(source=SOURCE, left_type="organization", left_key=nip, right_type="external_record",
                           right_key=f"kio_ruling:{r['ext']}", method="buyer_name_ambiguous", score=0.4,
                           features={"zamawiajacy": r["zam"], "reason": r["why"]},
                           explanation=f"'Zamawiający' {r['zam']!r} has the same name as {b['name']} but no context marker")
        for r in mentions:
            if not WODKAN_RE.search(read(texts.get(r["id"]))[:20000] or (hits[r["id"]]["search"].get("fragment") or "")):
                continue
            yield LinkHint(source=SOURCE, left_type="organization", left_key=nip, right_type="external_record",
                           right_key=f"kio_ruling:{r['ext']}", method="text_mention", score=0.2,
                           features={"zamawiajacy": r["zam"], "fragment": hits[r["id"]]["search"].get("fragment")},
                           explanation=f"Ruling concerns {r['zam']!r}; the text mentions {b['phrase']} (e.g. as a reference/evidence)")

        # per project
        for p in b["projects"]:
            ids_re = [re.escape(n["number"].split("/BZP ")[-1].split("/")[0]) for n in p.get("notices") or [] if n.get("number")]
            ocid = p.get("tender_id") or ""
            first_date = min((n.get("date") or "9999") for n in p.get("notices") or [{}]) if p.get("notices") else None
            proj_match, cands = [], []
            from rapidfuzz import fuzz
            for r in verified + ambiguous:
                t = read(texts.get(r["id"]))
                dt_r = _date(r.get("date"))
                after = (dt_r is None or not first_date or dt_r.isoformat() >= first_date)
                feats: dict[str, Any] = {"after_first_notice": after}
                if any(re.search(x, t) for x in ids_re if x) or (ocid and ocid[-36:] in t):
                    feats["identifier_in_text"] = True
                sim = fuzz.partial_ratio(_fold(p["title"])[:200], _fold(t[:15000])) if t else 0
                feats["title_similarity"] = sim
                if feats.get("identifier_in_text") or (after and sim >= 85):
                    proj_match.append(r["ext"])
                    yield LinkHint(source=SOURCE, left_type="project", left_key=p["rm_id"], right_type="external_record",
                                   right_key=f"kio_ruling:{r['ext']}",
                                   method="exact_id" if feats.get("identifier_in_text") else "buyer+title_similarity",
                                   score=1.0 if feats.get("identifier_in_text") else 0.7, features=feats,
                                   explanation=f"KIO ruling for {b['name']} matches project title/identifier")
                else:
                    cands.append(r["ext"])
            pst = "found" if proj_match else ("partial" if missing_details else "not_found")
            yield SourceCheck(source=SOURCE, subject_type="project", subject_key=p["rm_id"],
                              query={**query, "project_match": "BZP no./OCID in ruling text, or title similarity >= 85 and ruling after first notice"},
                              n_hits=total or 0, n_relevant=len(proj_match), result=pst, matched_ids=proj_match,
                              note=(f"buyer {b['name']}: {len(verified)} verified KIO rulings"
                                    + (f" (other rulings of this buyer, not this procurement: {', '.join(cands[:10])})" if cands else "")
                                    + ("; no KIO appeal found for this procurement" if not proj_match else "")),
                              checked_at=checked, raw_path=fe.get("path") if fe else None)
