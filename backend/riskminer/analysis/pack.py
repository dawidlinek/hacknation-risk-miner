"""Analysis pack (api_contract §4): DOCX (python-docx, MIT), PDF (LibreOffice headless via documents.convert), CSV, JSON.

`manifest(report)` lists what goes in and what is excluded (AI conclusions the owner did not approve). `render(db, code, fmt, version)`
builds the file from the stored report (`analysis.service.get_report`), caches it under exports/packs/<code>-v<version>-<hash>.<ext>
and returns (path, filename, media_type). The annex lists every source with URL, page, quote, retrieved_at and sha256.
Session B. Permission checks stay in the analyses router (A)."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import settings

MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
         "csv": "text/csv; charset=utf-8", "json": "application/json"}
FORMATS = ["docx", "pdf", "csv", "json"]
STATE_LABEL = {"BRAK_W_PACZCE": "nie ma w paczce", "DOKUMENT_NIE_WSPOMINA": "dokument nie wspomina", "POTWIERDZONO": "potwierdzono",
               "NIECZYTELNY": "dokument nieczytelny", "BRAK_POTWIERDZENIA": "brak potwierdzenia", "SPRZECZNOSC": "sprzeczność"}
METHOD_NOTE = ("Liczby w tym dokumencie to obliczenia na umowach z ogłoszeń BZP (klasa odniesienia), z liczbą umów n przy każdej wartości. "
               "Wnioski modelu językowego są w pakiecie tylko wtedy, gdy zatwierdził je autor analizy. Założenia ekspertów są oznaczone. "
               "Ryzyka są liczone niezależnie, bez korelacji między nimi.")


# ------------------------------------------------------------------------------------------------------------ selection

def _ai_pending(f: dict) -> bool:
    return (f.get("origin") == "AI" or (f.get("prov") or {}).get("role") == "ai" or f.get("kind") == "ai") \
        and f.get("review_status", (f.get("prov") or {}).get("review_status")) not in ("approved", "edited")


def split_flags(report: dict) -> tuple[list[dict], list[dict]]:
    inc, exc = [], []
    for f in report.get("flags") or []:
        (exc if _ai_pending(f) else inc).append(f)
    return inc, exc


def manifest(report: dict) -> dict:
    inc, exc = split_flags(report)
    clauses = [c for c in report.get("clauses") or [] if c.get("in_pack")]
    qs = report.get("questions") or []
    items = [{"key": "summary", "label": "Podsumowanie", "count_label": "1 zdanie"},
             {"key": "reference_class", "label": "Klasa odniesienia i prognozy", "count_label": f"{len(qs)} pytań"},
             {"key": "flags", "label": "Sygnały ryzyka", "count_label": f"{len(inc)} sygnałów"},
             {"key": "similar_cases", "label": "Podobne przypadki", "count_label": f"{len(report.get('similar_cases') or [])} przypadków"},
             {"key": "clauses", "label": "Proponowane zapisy umowne", "count_label": f"{len(clauses)} zapisów"},
             {"key": "limitations", "label": "Ograniczenia i metoda", "count_label": f"{len(report.get('limitations') or [])} uwag"},
             {"key": "annex", "label": "Załącznik: źródła i cytaty", "count_label": f"{len(collect_refs(report))} źródeł"}]
    return {"items": items, "excluded": [{"item_id": f.get("id"), "title": f.get("title"), "reason": "wniosek AI niezatwierdzony"} for f in exc],
            "formats": FORMATS}


# --------------------------------------------------------------------------------------------------------------- refs

def collect_refs(obj: Any) -> list[dict]:
    """Every distinct ref inside a report (Prov.refs), in first-seen order."""
    seen: dict[tuple, dict] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("refs"), list):
                for r in o["refs"]:
                    if isinstance(r, dict) and r.get("kind") and r.get("id") is not None:
                        seen.setdefault((r["kind"], str(r["id"]), r.get("field_code"), r.get("page_no")), r)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return list(seen.values())


async def resolve_hashes(db: AsyncSession, refs: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    doc_ids = [int(r["id"]) for r in refs if r["kind"] == "document" and str(r["id"]).isdigit()]
    if doc_ids:
        for r in (await db.execute(text("SELECT d.id, d.sha256, d.url, s.retrieved_at FROM document d LEFT JOIN source s ON s.id = d.source_id "
                                        "WHERE d.id = ANY(:i)"), {"i": doc_ids})).mappings():
            out[f"document:{r['id']}"] = {"sha256": r["sha256"], "url": r["url"], "retrieved_at": r["retrieved_at"]}
    nums = [r["id"] for r in refs if r["kind"] == "notice"]
    if nums:
        for r in (await db.execute(text("SELECT n.notice_number, n.url, s.sha256, s.retrieved_at FROM notice n LEFT JOIN source s ON s.id = n.source_id "
                                        "WHERE n.notice_number = ANY(:n)"), {"n": nums})).mappings():
            out[f"notice:{r['notice_number']}"] = {"sha256": r["sha256"], "url": r["url"], "retrieved_at": r["retrieved_at"]}
    return out


# ---------------------------------------------------------------------------------------------------------------- docx

def _h(doc, text_: str, level: int = 1):
    return doc.add_heading(text_, level=level)


def _table(doc, header: list[str], rows: list[list[str]], widths: list[float] | None = None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = h
        for p in c.paragraphs:
            for r in p.runs:
                r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = "" if v is None else str(v)
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
    return t


def _disp(n: Any) -> str:
    if isinstance(n, dict):
        return str(n.get("display") if n.get("display") is not None else n.get("value", ""))
    return "" if n is None else str(n)


def _n_of(n: Any) -> str:
    p = (n or {}).get("prov") if isinstance(n, dict) else None
    return str(p.get("n")) if p and p.get("n") is not None else ""


def _date(s: Any) -> str:
    if not s:
        return ""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return str(s)[:10]


def _owner(r: dict) -> str:
    """Chosen allocation position: key string (buyer|shared|contractor) or index 0|1|2 into positions / the default order."""
    ch = r.get("chosen")
    names = {"buyer": "Zamawiający", "shared": "Wspólnie", "contractor": "Wykonawca"}
    if isinstance(ch, int) and not isinstance(ch, bool):
        pos = r.get("positions") or []
        if 0 <= ch < len(pos) and isinstance(pos[ch], dict):
            return pos[ch].get("label") or names.get(pos[ch].get("key"), "")
        return ["Zamawiający", "Wspólnie", "Wykonawca"][ch] if 0 <= ch < 3 else ""
    return names.get(ch, ch or "")


def risk_register(report: dict, inc_flags: list[dict]) -> list[list[str]]:
    """Rows: code, title, probability / key number, impact, expected cost, owner. Uses report['allocation'] when present."""
    rows: list[list[str]] = []
    alloc = (report.get("allocation") or {}).get("risks") if isinstance(report.get("allocation"), dict) else None
    if alloc:
        for r in alloc:
            ec = (r.get("expected_cost") or {}).get("money") or {}
            rows.append([r.get("code"), r.get("title"), "", _disp(r.get("impact")) or r.get("impact_label") or "",
                         f"{ec.get('amount', '')} {ec.get('currency', '')}".strip(), _owner(r)])
        return rows
    for f in inc_flags:
        for code in f.get("risk_codes") or [""]:
            rows.append([code, f.get("title"), _disp(f.get("number")), "", "", ""])
    return rows


def build_docx(report: dict, annex: list[dict], hashes: dict[str, dict]) -> bytes:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Liberation Sans"
    st.font.size = Pt(10.5)
    code, version = report.get("code") or report.get("id") or "", report.get("version") or ""
    title = doc.add_heading(f"Analiza ryzyk {code}", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p = doc.add_paragraph()
    p.add_run(f"Wersja {version}, wygenerowano {date.today().strftime('%d.%m.%Y')}. Katalog ryzyk {report.get('catalogue_version') or 'v?'}, "
              f"dane z dnia {_date(report.get('data_as_of'))}.").font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    if report.get("sensitivity") == "confidential":
        doc.add_paragraph("Dokument poufny.").runs[0].bold = True
    feats = report.get("features") or []
    if feats:
        _h(doc, "Opis inwestycji", 1)
        _table(doc, ["Cecha", "Wartość"], [[f.get("label"), f.get("display") or f.get("value")] for f in feats if isinstance(f, dict)])
    _h(doc, "Podsumowanie", 1)
    summ = report.get("summary") or {}
    doc.add_paragraph(summ.get("sentence") if isinstance(summ, dict) else str(summ or ""))

    rc = report.get("reference_class") or {}
    _h(doc, "Klasa odniesienia i prognozy", 1)
    funnel = rc.get("funnel") or []
    if funnel:
        _table(doc, ["Krok", "Liczba umów (n)"], [[s.get("label"), s.get("n")] for s in funnel])
    final = rc.get("final") or {}
    if final.get("n") is not None:
        doc.add_paragraph(f"Klasa końcowa: n = {final['n']}.")
    qs = report.get("questions") or []
    if qs:
        doc.add_paragraph()
        _table(doc, ["Pytanie", "Odpowiedź", "Liczba", "n"],
               [[q.get("question"), q.get("answer"), _disp(q.get("key_number")), _n_of(q.get("key_number"))] for q in qs])
        for q in qs:
            rng = q.get("range") or {}
            if rng.get("plain"):
                doc.add_paragraph(f"{q.get('question')} {rng['plain']}.", style="List Bullet")

    inc, exc = split_flags(report)
    _h(doc, "Sygnały ryzyka", 1)
    if inc:
        _table(doc, ["Sygnał", "Opis", "Ryzyko", "Liczba (n)"],
               [[f.get("title"), f.get("text"), ", ".join(f.get("risk_codes") or []), (_disp(f.get("number")) + (f" (n={_n_of(f.get('number'))})" if _n_of(f.get("number")) else "")).strip()]
                for f in inc])
    else:
        doc.add_paragraph("Brak sygnałów w pakiecie.")
    if exc:
        doc.add_paragraph(f"Pominięto {len(exc)} wniosków AI, których autor analizy nie zatwierdził.").runs[0].italic = True

    reg = risk_register(report, inc)
    if reg:
        _h(doc, "Rejestr ryzyk", 1)
        _table(doc, ["Kod", "Ryzyko", "Prawdopodobieństwo / liczba", "Skutek", "Koszt oczekiwany", "Właściciel"], reg)

    alloc = report.get("allocation") if isinstance(report.get("allocation"), dict) else None
    if alloc and alloc.get("balance"):
        _h(doc, "Podział ryzyk", 1)
        b = alloc["balance"]
        doc.add_paragraph(b.get("note") or "")

    sim = report.get("similar_cases") or []
    if sim:
        _h(doc, "Podobne przypadki", 1)
        _table(doc, ["#", "Projekt", "Podobieństwo", "Opóźnienie", "Koszt wobec umowy"],
               [[s.get("rank"), s.get("title"), _disp(s.get("score")), _disp((s.get("outcome") or {}).get("delay_days")),
                 _disp((s.get("outcome") or {}).get("cost_dev_pct"))] for s in sim[:10]])

    gaps = [m for m in (report.get("missing") or report.get("gaps") or []) if isinstance(m, dict)]
    if gaps:
        _h(doc, "Luki w dokumentach", 1)
        _table(doc, ["Dokument", "Stan dowodowy", "Co ogranicza"],
               [[g.get("title") or g.get("doc_type"), STATE_LABEL.get(g.get("evidence_state"), g.get("state_label") or g.get("evidence_state") or ""), g.get("limits")] for g in gaps])

    clauses = [c for c in report.get("clauses") or [] if c.get("in_pack")]
    _h(doc, "Proponowane zapisy umowne", 1)
    if clauses:
        for c in clauses:
            doc.add_paragraph().add_run(f"{c.get('code')}: {c.get('title')}").bold = True
            if c.get("why"):
                doc.add_paragraph(c["why"])
            if c.get("text"):
                doc.add_paragraph(c["text"]).paragraph_format.left_indent = Pt(18)
    else:
        doc.add_paragraph("Nie wybrano zapisów do pakietu.")

    _h(doc, "Ograniczenia", 1)
    for lim in report.get("limitations") or []:
        doc.add_paragraph(lim, style="List Bullet")
    _h(doc, "Metoda", 1)
    doc.add_paragraph(METHOD_NOTE)
    proc = report.get("processing") or []
    if proc:
        doc.add_paragraph("Przetwarzanie modelem: " + "; ".join(f"{x.get('task')}: {x.get('provider')} ({x.get('data_location')})" for x in proc) + ".")

    doc.add_page_break()
    _h(doc, "Załącznik: źródła i cytaty", 1)
    rows = []
    for r in annex:
        k = f"{r['kind']}:{r['id']}"
        h = hashes.get(k, {})
        where = " ".join(x for x in (f"pole {r['field_code']}" if r.get("field_code") else "", f"s. {r['page_no']}" if r.get("page_no") else "") if x)
        rows.append([r.get("label"), f"{r['kind']} {r['id']}" + (f", {where}" if where else ""), r.get("url") or h.get("url") or "",
                     _date(r.get("retrieved_at") or h.get("retrieved_at")), (h.get("sha256") or "")[:16], r.get("quote") or ""])
    _table(doc, ["Opis", "Źródło", "Adres", "Pobrano", "sha256", "Cytat"], rows or [["brak", "", "", "", "", ""]])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------------- csv, json, pdf

def build_csv(report: dict) -> bytes:
    inc, _ = split_flags(report)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["kod", "ryzyko", "liczba", "n", "skutek", "koszt_oczekiwany", "wlasciciel", "pochodzenie", "status"])
    alloc = (report.get("allocation") or {}).get("risks") if isinstance(report.get("allocation"), dict) else None
    if alloc:
        for r in alloc:
            ec = (r.get("expected_cost") or {}).get("money") or {}
            w.writerow([r.get("code"), r.get("title"), "", (r.get("expected_cost") or {}).get("prov", {}).get("n"), _disp(r.get("impact")) or r.get("impact_label") or "",
                        f"{ec.get('amount', '')} {ec.get('currency', '')}".strip(), _owner(r), "obliczenie", "auto"])
    else:
        for f in inc:
            for code in f.get("risk_codes") or [""]:
                p = f.get("prov") or {}
                w.writerow([code, f.get("title"), _disp(f.get("number")), _n_of(f.get("number")), "", "", "", p.get("role") or f.get("origin") or "", f.get("review_status") or p.get("review_status") or ""])
    return ("﻿" + buf.getvalue()).encode()


def build_json(report: dict, annex: list[dict]) -> bytes:
    inc, exc = split_flags(report)
    out = {**report, "flags": inc, "excluded": manifest(report)["excluded"], "annex": annex}
    return json.dumps(out, ensure_ascii=False, indent=1, default=str).encode()


def to_pdf_bytes(docx: bytes) -> bytes:
    import tempfile
    from riskminer.documents.convert import to_pdf
    with tempfile.TemporaryDirectory(prefix="pack_") as d:
        src = Path(d) / "pack.docx"
        src.write_bytes(docx)
        return to_pdf(src, Path(d) / "out").read_bytes()


# ------------------------------------------------------------------------------------------------------------- render

class PackFile:
    def __init__(self, path: Path, filename: str, media_type: str):
        self.path, self.filename, self.media_type = path, filename, media_type


def packs_dir() -> Path:
    d = Path(settings().exports_dir) / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def render(db: AsyncSession, code: str, fmt: str, version: int | None = None) -> PackFile:
    """Build (or fetch from cache) the pack file for an analysis version. Raises analysis.service.NotFound for unknown code/version."""
    if fmt not in MEDIA:
        raise ValueError("unknown format")
    from riskminer.analysis import service as SV
    report = await SV.get_report(db, code, version)
    report.setdefault("code", code)
    v = report.get("version") or version or 1
    refs = collect_refs(report)
    hashes = await resolve_hashes(db, refs)
    key = hashlib.sha256(json.dumps([report, hashes], sort_keys=True, default=str).encode()).hexdigest()[:10]
    path = packs_dir() / f"{code}-v{v}-{key}.{fmt}"
    if not path.exists():
        if fmt == "docx":
            data = build_docx(report, refs, hashes)
        elif fmt == "pdf":
            docx_path = packs_dir() / f"{code}-v{v}-{key}.docx"
            if not docx_path.exists():
                docx_path.write_bytes(build_docx(report, refs, hashes))
            data = await asyncio.to_thread(to_pdf_bytes, docx_path.read_bytes())
        elif fmt == "csv":
            data = build_csv(report)
        else:
            data = build_json(report, refs)
        path.write_bytes(data)
    return PackFile(path, f"{code}-v{v}.{fmt}", MEDIA[fmt])
