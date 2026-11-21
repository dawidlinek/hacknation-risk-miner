"""NIK (Najwyższa Izba Kontroli) audit results for the water/sewage sector (scrape.md §2 P1, §3.6;
docs/research/02_other_sources.md §8).

Flow:
1. Seed audits first (the 6 already read: P/11/148, P/20/046, S/22/002/LKI, S/23/003/LSZ, I/19/001/KSI,
   I/25/001/DLO), then the topic search
   `POST /kontrole/wyniki-kontroli-nik/fmax,,strona,{N}.html` (X-Requested-With) -> JSON {ilosc, xml},
   10 audits per page, topics: ściek, kanalizac, wodociąg, oczyszczal, wodno-ściek (deduped by NIK id).
2. Audit page `/kontrole/wyniki-kontroli-nik/kontrole,{id}.html` (302 -> /kontrole/P/20/046/) -> PDF
   links: `…typ,kk.pdf` (Informacja o wynikach kontroli) and `…typ,kj.pdf` (wystąpienia pokontrolne).
   P-type (national) audits list the wystąpienia on per-delegatura sub-pages (/kontrole/P/20/046/LWR/),
   which are fetched too.
3. PDFs -> raw; text via `pdftotext` (no -layout: two-column Informacje) -> derived .txt.
   The kk Informacja is always fetched; wystąpienia are capped per audit (`--opt max_kj_per_audit=N`,
   default 15; all kj links are still listed in the record).
4. Per pilot buyer: `jednjednostka=<buyer name stem>` search -> SourceCheck per project.

Options: `--since` = dataodx (default 2000-01-01), `--until` = datadox, `--limit N` = max audits,
`--only <nik ids or numbers>`, `--opt topics=a,b`, `--opt jobs=audits,buyers`, `--opt fetch_pdfs=false`.
"""
from __future__ import annotations

import html as htmlmod
import json
import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext, safe_name
from riskminer.connectors.records import DocumentRecord, ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.nik")

SOURCE = "nik"
DEFAULTS: dict[str, Any] = {"min_interval": 2.0, "timeout": 120.0}

BASE = "https://www.nik.gov.pl"
SEARCH_URL = BASE + "/kontrole/wyniki-kontroli-nik/fmax,,strona,{n}.html"
AUDIT_URL = BASE + "/kontrole/wyniki-kontroli-nik/kontrole,{id}.html"
TOPICS = ["ściek", "kanalizac", "wodociąg", "oczyszczal", "wodno-ściek"]
# nik id -> audit number (already read in research/sources/nik/)
SEED = {"9005": "P/11/148", "22264": "P/20/046", "22650": "S/22/002/LKI", "24611": "S/23/003/LSZ",
        "22446": "I/19/001/KSI", "26070": "I/25/001/DLO"}
PDF_RE = re.compile(r'href="([^"]*?(?:typ,k[jk]?\.pdf|/plik/id,[^"]+?\.pdf))"', re.IGNORECASE)
SUB_RE = re.compile(r'href="(/kontrole/[PSIKD]/\d{2}/\d{3}/[A-Z]{3}/)"')
PILOT_PATH = Path(settings().ref_dir) / "pilot_projects.json"
XHR = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}


# ---------------------------------------------------------------------------------------------
def _form(temat: str = "", since: str = "2000-01-01", until: str | None = None, jednjednostka: str = "") -> dict:
    return {"temat": temat, "numer": "", "dzialy": "0", "jednostka": "", "jednjednostka": jednjednostka,
            "dataodx": since, "datadox": until or datetime.now(UTC).date().isoformat(), "rodzaj": "",
            "zakres": "dowolny"}


def _parse_search(content: bytes | None) -> tuple[int, list[dict]]:
    if not content:
        return 0, []
    try:
        d = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0, []
    total = int(d.get("ilosc") or 0)
    xml = d.get("xml") or ""
    items = []
    if xml.strip():
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except ET.ParseError:
            return total, []
        for k in root.findall("kontrola"):
            items.append({c.tag: (c.text or "").strip() for c in k})
    return total, items


def _to_iso(v: Any, default: str) -> str:
    if v in (None, ""):
        return default
    return str(v)[:10]


def _pdf_kind(url: str) -> str:
    if "typ,kk" in url or "typ,k.pdf" in url:
        return "nik_informacja"
    if "typ,kj" in url:
        return "nik_wystapienie"
    return "nik_pdf"


def _pdftotext(pdf: Path) -> tuple[bytes, int | None]:
    exe = shutil.which("pdftotext")
    if exe:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "o.txt"
            subprocess.run([exe, "-enc", "UTF-8", str(pdf), str(out)], check=False, timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if out.exists():
                b = out.read_bytes()
                return b, b.count(b"\f") or None
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf))
        parts = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
        return "\f".join(parts).encode("utf-8"), len(doc)
    except Exception:  # noqa: BLE001
        return b"", None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(s or "")).strip()


def parse_audit_page(content: bytes, page_url: str) -> dict:
    """Unit, number, date, dział, audited entities (+their PDFs), all PDF links, sub-pages."""
    s = content.decode("utf-8", "replace")
    out: dict[str, Any] = {"page_url": page_url}
    m = re.search(r"<!-- !(/kontrole/[^?]*)\?! -->", s)
    out["path"] = m.group(1) if m else urlsplit(page_url).path
    tree = HTMLParser(s)
    h1 = tree.css_first("h1.main__title")
    out["title"] = _clean(h1.text()) if h1 else None
    for h2 in tree.css("h2.main__title"):
        t = _clean(h2.text())
        if t.startswith("Jednostka kontrolująca"):
            out["unit"] = t.split(":", 1)[1].strip()
    info = tree.css_first("p.info")
    if info:
        t = _clean(info.text(separator="\n"))
        for key, rx in (("number", r"Nr ewidencyjny:\s*([A-Z]/\d{2}/\d{3}(?:/[A-Za-z]{3})?)\b"), ("published", r"Data publikacji:\s*([\d-]+(?: [\d:]+)?)"),
                        ("dzial", r"Dział tematyczny:\s*(.+?)(?:$| Nr | Data )")):
            mm = re.search(rx, t)
            if mm:
                out[key] = mm.group(1).strip()
    entities = []
    lis = []
    for box in tree.css("div.news-box"):
        h3 = box.css_first("h3.news-box__title")
        if h3 and "podmiot" in h3.text().lower():
            lis.extend(box.css("div.news-box > ul.news-box__items > li.news-box__item"))
    for li in lis:
        h4 = li.css_first("h4.news-box__maintitle")
        if not h4:
            continue
        addr = li.css_first("p")
        pdfs = [urljoin(BASE, a.attributes.get("href") or "") for a in li.css("a[href]")
                if ".pdf" in (a.attributes.get("href") or "")]
        entities.append({"name": _clean(h4.text()), "address": _clean(addr.text()) if addr else None, "pdfs": pdfs})
    out["entities"] = entities
    seen, pdfs = set(), []
    for href in PDF_RE.findall(s):
        u = urljoin(BASE, htmlmod.unescape(href))
        if u not in seen:
            seen.add(u)
            pdfs.append(u)
    out["pdfs"] = pdfs
    if not m and out.get("number"):
        out["path"] = "/kontrole/" + out["number"].strip("/") + "/"
    base_path = out["path"]
    out["subpages"] = sorted({u for u in SUB_RE.findall(s) if u.startswith(base_path) and u != base_path})
    return out


# ---------------------------------------------------------------------------------------------
class _Stop(Exception):
    pass


_FAILS = {"n": 0}


def _fetch(ctx: ScrapeContext, url: str, **kw):
    """ctx.fetch + circuit breaker: 3 consecutive transport errors/blocks (NIK answers an overloaded or
    unwelcome client with HTTP/2 stream resets and a robots.txt redirect loop) stop the run."""
    r = ctx.fetch(url, **kw)
    if not r.cached and (r.status == "blocked" or (r.status == "error" and r.http_status is None)):
        _FAILS["n"] += 1
        if _FAILS["n"] >= 3:
            raise _Stop(f"{_FAILS['n']} consecutive failures, last: {url} {r.manifest.get('note', '')[:200]}")
    elif not r.cached:
        _FAILS["n"] = 0
    return r


def run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts) -> dict:
    _FAILS["n"] = 0
    try:
        return _run(ctx, since=since, until=until, limit=limit, only=only, **opts)
    except _Stop as e:
        log.warning("nik: stopped: %s", e)
        ctx.record(BASE, "blocked", note=f"run stopped (site refusing requests): {e}")
        return {"stopped": str(e)}


def _run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts) -> dict:
    jobs = opts.get("jobs") or ["audits", "buyers"]
    if isinstance(jobs, str):
        jobs = [j.strip() for j in jobs.split(",") if j.strip()]
    d_since = _to_iso(since, "2000-01-01")
    d_until = _to_iso(until, datetime.now(UTC).date().isoformat())
    topics = opts.get("topics") or TOPICS
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    max_kj = int(opts.get("max_kj_per_audit", 15))
    fetch_pdfs = str(opts.get("fetch_pdfs", "true")).lower() not in ("0", "false", "no")
    search_ttl = timedelta(hours=24)
    out: dict[str, Any] = {}

    audits: dict[str, dict] = {k: {"id": k, "numer": v, "topics": [], "seed": True} for k, v in SEED.items()}
    if "audits" in jobs:
        for topic in topics:
            n = 1
            while True:
                r = _fetch(ctx, SEARCH_URL.format(n=n), method="POST", data=_form(topic, d_since, d_until),
                              headers=XHR, rel_path=f"search/{safe_name(topic)}_{d_since}_{d_until}_p{n}.json",
                              note=f"job=search topic={topic}", ttl=search_ttl, check_blocked=False)
                total, items = _parse_search(r.content if r.status == "ok" else None)
                for it in items:
                    a = audits.setdefault(it.get("id", ""), {"id": it.get("id"), "topics": []})
                    a.update({k: v for k, v in it.items() if k != "id"})
                    if topic not in a["topics"]:
                        a["topics"].append(topic)
                if r.status != "ok" or not items or n * 10 >= total or n > 40:
                    break
                n += 1
        out["audits_listed"] = len(audits)
        order = list(SEED) + [k for k in audits if k not in SEED]
        if only:
            want = {str(x) for x in only}
            order = [k for k in order if k in want or audits[k].get("numer") in want]
        if limit:
            order = order[: int(limit)]
        done_txt = _derived_index(ctx.store)
        n_pdf = n_pages = 0
        for aid in order:
            n_p, n_d = _fetch_audit(ctx, aid, max_kj, fetch_pdfs, done_txt)
            n_pages += n_p
            n_pdf += n_d
        out.update({"audits_fetched": len(order), "pages": n_pages, "pdfs": n_pdf})
    if "buyers" in jobs:
        out["buyers"] = _job_buyers(ctx, d_since, d_until, max_kj)
    return out


def _derived_index(store: RawStore) -> set[str]:
    return {e.get("src_sha256") for e in store.entries() if e.get("method") == "DERIVED" and e.get("src_sha256")}


def _fetch_audit(ctx: ScrapeContext, aid: str, max_kj: int, fetch_pdfs: bool, done_txt: set[str]) -> tuple[int, int]:
    url = AUDIT_URL.format(id=aid)
    r = _fetch(ctx, url, rel_path=f"audit/{aid}/page.html", note=f"job=audit nik_id={aid}")
    if r.status != "ok" or not r.content:
        return 1, 0
    page = parse_audit_page(r.content, r.url)
    pdfs = list(page["pdfs"])
    n_pages = 1
    for sp in page["subpages"]:
        rs = _fetch(ctx, BASE + sp, rel_path=f"audit/{aid}/sub_{safe_name(sp.strip('/').split('/')[-1])}.html",
                       note=f"job=audit_sub nik_id={aid}")
        n_pages += 1
        if rs.status == "ok" and rs.content:
            for u in parse_audit_page(rs.content, rs.url)["pdfs"]:
                if u not in pdfs:
                    pdfs.append(u)
    if not fetch_pdfs:
        return n_pages, 0
    kk = [u for u in pdfs if _pdf_kind(u) != "nik_wystapienie"]
    kj = [u for u in pdfs if _pdf_kind(u) == "nik_wystapienie"][:max_kj]
    n = 0
    for u in kk + kj:
        fname = safe_name(urlsplit(u).path.rsplit("/", 1)[-1], 150)
        rp = _fetch(ctx, u, rel_path=f"audit/{aid}/pdf/{fname}", ext=".pdf",
                       note=f"job=pdf nik_id={aid} kind={_pdf_kind(u)}", check_blocked=False,
                       empty_if=lambda b: not b.startswith(b"%PDF"))
        n += 1
        if rp.status == "ok" and rp.path and rp.sha256 not in done_txt:
            txt, pages = _pdftotext(rp.path)
            if txt.strip():
                ctx.save_derived(f"audit/{aid}/txt/{Path(fname).stem}.txt", txt, url=u,
                                 note=f"pdftotext (no -layout) nik_id={aid}",
                                 extra={"src_sha256": rp.sha256, "src_path": ctx.store.rel(rp.path), "pages": pages})
                done_txt.add(rp.sha256)
    return n_pages, n


def _buyer_stem(name: str) -> str:
    name = re.split(r"\s[–-]\s", name)[0]
    words = [w for w in re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", name) if w.lower() not in ("gmina", "w", "miasto")]
    if not words:
        return name
    if not name.lower().startswith("gmina"):
        return " ".join(words[:3])
    w = words[0]
    return w[:-1] if len(w) > 5 else w


def _pilot() -> list[dict]:
    return json.loads(PILOT_PATH.read_text(encoding="utf-8")) if PILOT_PATH.exists() else []


def _job_buyers(ctx: ScrapeContext, d_since: str, d_until: str, max_kj: int = 15) -> dict:
    done = 0
    extra: dict[str, dict] = {}
    for nip, name in sorted({(p["buyer_nip"], p["buyer_name"]) for p in _pilot()}):
        stem = _buyer_stem(name)
        n = 1
        while True:
            r = _fetch(ctx, SEARCH_URL.format(n=n), method="POST", data=_form("", d_since, d_until, stem),
                          headers=XHR, rel_path=f"buyers/{nip}_{safe_name(stem)}_p{n}.json",
                          note=f"job=buyer nip={nip} stem={stem}", ttl=timedelta(hours=24), check_blocked=False)
            total, items = _parse_search(r.content if r.status == "ok" else None)
            extra.update({it["id"]: it for it in items if it.get("id") and WATER_RX.search(it.get("temat") or "")})
            if r.status != "ok" or not items or n * 10 >= total or n >= 5:
                break
            n += 1
        done += 1
    # water-related audits found via the buyer search but missed by the topic search: fetch them too
    done_txt = _derived_index(ctx.store)
    have = {(e.get("note") or "").split("nik_id=", 1)[-1] for e in ctx.store.entries()
            if (e.get("note") or "").startswith("job=audit ") and e.get("status") == "ok"}
    todo = [a for a in extra if a not in have]
    for aid in todo:
        _fetch_audit(ctx, aid, max_kj, True, done_txt)
    return {"buyers_searched": done, "extra_audits_fetched": len(todo)}


# ---------------------------------------------------------------------------------------------
# raw -> records
# ---------------------------------------------------------------------------------------------
def _note_val(note: str, key: str) -> str | None:
    m = re.search(rf"{key}=(\S+)", note or "")
    return m.group(1) if m else None


def _read(store: RawStore, e: dict) -> bytes | None:
    if not e.get("path"):
        return None
    p = store.abs(e["path"])
    return p.read_bytes() if p.exists() else None


WATER_RX = re.compile(r"(?<!w)ściek|kanaliz|wodoci|oczyszczal|wodno|wod[ayę] ", re.IGNORECASE)


def parse(store: RawStore) -> Iterable[ExternalRecord | DocumentRecord | SourceCheck]:
    entries = store.entries()
    listed: dict[str, dict] = {k: {"id": k, "numer": v, "topics": [], "seed": True} for k, v in SEED.items()}
    pages: dict[str, tuple[dict, dict]] = {}
    subs: dict[str, list[tuple[dict, dict]]] = {}
    pdfs: dict[str, dict[str, dict]] = {}
    texts: dict[str, dict] = {}      # src_sha256 -> derived entry
    buyer_entries: dict[str, list[dict]] = {}
    for e in entries:
        note = e.get("note") or ""
        if e.get("method") == "DERIVED":
            if e.get("src_sha256"):
                texts[e["src_sha256"]] = e
            continue
        if note.startswith("job=search") and e.get("status") == "ok":
            topic = note.split("topic=", 1)[1] if "topic=" in note else ""
            for it in _parse_search(_read(store, e))[1]:
                a = listed.setdefault(it.get("id", ""), {"id": it.get("id"), "topics": []})
                a.update({k: v for k, v in it.items() if k != "id"})
                if topic and topic not in a["topics"]:
                    a["topics"].append(topic)
        elif note.startswith("job=audit_sub") and e.get("status") == "ok":
            aid = _note_val(note, "nik_id")
            c = _read(store, e)
            if aid and c:
                subs.setdefault(aid, []).append((e, parse_audit_page(c, e["url"])))
        elif note.startswith("job=audit ") and e.get("status") == "ok":
            aid = _note_val(note, "nik_id")
            c = _read(store, e)
            if aid and c:
                pages[aid] = (e, parse_audit_page(c, e["url"]))
        elif note.startswith("job=pdf"):
            aid = _note_val(note, "nik_id")
            if aid:
                pdfs.setdefault(aid, {})[e["url"]] = e
        elif note.startswith("job=buyer"):
            buyer_entries.setdefault(_note_val(note, "nip") or "", []).append(e)

    entities_by_id: dict[str, list[dict]] = {}
    number_count: dict[str, int] = {}
    for aid, (_pe, page) in pages.items():
        k = (page.get("number") or listed.get(aid, {}).get("numer") or f"nik-id-{aid}").upper().replace("NIK-ID-", "nik-id-")
        number_count[k] = number_count.get(k, 0) + 1
    for aid, (pe, page) in pages.items():
        meta = listed.get(aid, {"id": aid, "topics": []})
        number = (page.get("number") or meta.get("numer") or f"nik-id-{aid}").upper().replace("NIK-ID-", "nik-id-")
        if number_count.get(number, 0) > 1:
            number = f"{number}#{aid}"          # two NIK pages share one audit number
        all_pdfs = list(page["pdfs"])
        entities = list(page["entities"])
        for _se, sp in subs.get(aid, []):
            entities.extend({**ent, "delegatura_page": sp.get("path")} for ent in sp["entities"])
            all_pdfs.extend(u for u in sp["pdfs"] if u not in all_pdfs)
        entities_by_id[aid] = entities
        entities_by_id.setdefault("num:" + number.split("#")[0], []).extend(entities)
        ent_by_pdf = {u: ent["name"] for ent in entities for u in ent.get("pdfs", [])}
        pdf_list, kk_text = [], None
        subject_key = f"nik_audit:{number}"
        for u in all_pdfs:
            fe = pdfs.get(aid, {}).get(u)
            te = texts.get(fe.get("sha256")) if fe and fe.get("status") == "ok" else None
            kind = _pdf_kind(u)
            pdf_list.append({"url": u, "doc_type": kind, "entity": ent_by_pdf.get(u),
                             "fetched": bool(fe and fe.get("status") == "ok"),
                             "raw_path": fe.get("path") if fe else None, "text_path": te.get("path") if te else None})
            if fe is None:
                continue
            ok = fe.get("status") == "ok"
            yield DocumentRecord(
                source=SOURCE, subject_type="external_record", subject_key=subject_key, doc_type=kind,
                title=("Informacja o wynikach kontroli " if kind == "nik_informacja" else "Wystąpienie pokontrolne ")
                + number + (f" – {ent_by_pdf[u]}" if u in ent_by_pdf else ""),
                filename=urlsplit(u).path.rsplit("/", 1)[-1], url=u,
                raw_path=fe.get("path") if ok else None, raw_sha256=fe.get("sha256") if ok else None,
                text_path=te.get("path") if te else None, pages=te.get("pages") if te else None,
                fetch_state="found" if ok else ("blocked" if fe.get("status") == "blocked" else "link_dead"),
                note=(fe.get("note") or "") + ("; no text layer (scanned PDF), OCR needed" if ok and not te else ""),
                data={"entity": ent_by_pdf.get(u), "nik_id": aid, "needs_ocr": bool(ok and not te)},
            )
            if te and kk_text is None and (kind == "nik_informacja" or not any(
                    _pdf_kind(x) == "nik_informacja" for x in all_pdfs)):
                p = store.abs(te["path"])
                if p.exists():
                    kk_text = p.read_text(encoding="utf-8", errors="replace")[:150_000]
        pub = page.get("published") or meta.get("publikacjaOdWyswietl") or ""
        try:
            pub_d = date.fromisoformat(pub[:10]) if pub else None
        except ValueError:
            pub_d = None
        title = page.get("title") or meta.get("temat")
        topic_hits = sorted(set(meta.get("topics", [])) | {t for t in TOPICS if t.lower() in (title or "").lower()})
        yield ExternalRecord(
            source=SOURCE, kind="nik_audit", external_id=number, title=title, published_on=pub_d,
            url=AUDIT_URL.format(id=aid), raw_path=pe.get("path"), raw_sha256=pe.get("sha256"), text=kk_text,
            data={"nik_id": aid, "kk_id": meta.get("kkId"), "unit": page.get("unit"),
                  "unit_code": next((m.group(1).upper() for u in all_pdfs
                                     if (m := re.search(r"pobierz,([a-z]{3})[~_]", u))), None),
                  "dzial": page.get("dzial"),
                  "page_url": page.get("page_url"), "page_path": page.get("path"),
                  "published": pub or None, "listed_from": meta.get("publikacjaOd"),
                  "moderated": meta.get("dataModeracji"), "topic_hits": topic_hits, "seed": bool(meta.get("seed")),
                  "water_relevant": bool(WATER_RX.search(title or "")),
                  "audited_entities": [{k: v for k, v in ent.items() if k != "pdfs"} for ent in entities],
                  "n_subpages": len(page["subpages"]), "pdfs": pdf_list,
                  "n_pdfs": len(pdf_list), "n_pdfs_fetched": sum(1 for x in pdf_list if x["fetched"])},
        )

    # per pilot project: was the buyer among NIK-audited entities?
    for p in _pilot():
        es = buyer_entries.get(p["buyer_nip"])
        if not es:
            continue
        items, ok = {}, False
        for e in es:
            if e.get("status") == "ok":
                ok = True
                for it in _parse_search(_read(store, e))[1]:
                    items[it.get("id")] = it
        relevant = [it for it in items.values() if WATER_RX.search(it.get("temat") or "")]
        stem = (es[-1].get("note") or "").split("stem=", 1)[-1]
        city = _fold(p.get("buyer_city") or "")
        verified, unverified = [], []
        for it in relevant:
            ents = entities_by_id.get(it.get("id") or "") or entities_by_id.get("num:" + (it.get("numer") or "").upper())
            is_gmina = p["buyer_name"].lower().startswith("gmina")
            hit = [x for x in ents or [] if _fold(stem) in _fold(f"{x.get('name')} {x.get('address')}")
                   and (not city or city in _fold(f"{x.get('name')} {x.get('address')}"))
                   and (not is_gmina or (re.search(r"urzad|gmin", _fold(x.get("name") or ""))
                                         and not re.search(r"urzad miasta(?! i gminy)", _fold(x.get("name") or ""))))]
            (verified if hit else unverified).append((it, hit, ents is not None))
        if not ok:
            result = "blocked" if any(e.get("status") == "blocked" for e in es) else "error"
        elif verified:
            result = "found"
        elif any(not fetched for _, _, fetched in unverified):
            result = "partial"          # candidate audit page not fetched -> cannot rule it out
        else:
            result = "not_found"
        parts = [f"NIK search by audited-entity name '{stem}': {len(items)} audits, {len(relevant)} water/sewage-related"]
        if not ok:
            parts = [f"NIK search by audited-entity name '{stem}' failed ({', '.join(sorted({str(e.get('http_status')) for e in es}))})"]
        for it, hit, _ in verified:
            parts.append(f"{it.get('numer')}: audited entity matches buyer ({hit[0].get('name')}, {hit[0].get('address')})")
        for it, _, fetched in unverified:
            parts.append(f"{it.get('numer')}: name-substring hit only, " + (
                "no audited entity matches buyer name+city (likely another unit)" if fetched else "audit page not fetched"))
        yield SourceCheck(
            source=SOURCE, subject_type="project", subject_key=p["rm_id"],
            query={"jednjednostka": stem, "buyer_nip": p["buyer_nip"], "url": SEARCH_URL.format(n=1)},
            n_hits=len(items), n_relevant=len(verified),
            result=result,
            matched_ids=[it.get("numer") for it, _, _ in verified if it.get("numer")],
            note="; ".join(parts),
            checked_at=max((datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                            for e in es if e.get("fetched_at")), default=None),
            raw_path=es[-1].get("path"),
        )


_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(_FOLD).lower()).strip()
