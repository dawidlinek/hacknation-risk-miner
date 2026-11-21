"""Registered tools of the import agent (api_contract §3.5 step 2). Only these functions touch uploaded files:
no shell, no network, no file goes to a model whole. Each call returns (out_text, data) and is logged by the service
in import_session.tool_calls with its duration."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from pathlib import Path

from riskminer.api.prov import fmt_num
from riskminer.imports import registry, rules

MAX_SAMPLE = 20
MAX_CLASSIFY = 40
TABULAR = {".xlsx", ".xlsm", ".csv"}
DOCS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".xlsx", ".xls", ".zip"}


# files that may carry a project record as text (one row like the organizer XLSX, a pipe table, "Kolumna: wartość" lines)
RECORD_KINDS = {"txt", "md", "json", "docx", "pdf", "tsv"}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv", ".zip": "zip", ".pdf": "pdf", ".docx": "docx",
            ".doc": "doc", ".odt": "odt", ".markdown": "md"}.get(ext, ext.lstrip(".") or "bin")


def _known(h) -> bool:
    known = {registry.norm(x) for f in registry.KNOWN_FORMATS.values() for x in f["headers"]}
    return bool(h) and (registry.field_for(str(h)) is not None or registry.norm(str(h)) in known)


def _shape(rows: list[list]) -> tuple[list[str], list[list]]:
    """Rows of cells -> (headers, data). Horizontal (header row + records) or vertical (one record as
    'Kolumna | Wartość' pairs, the way a record is written in a letter or a Word table) are both accepted."""
    rows = [[("" if v is None else v) for v in r] for r in rows if r and any(str(v or "").strip() for v in r)]
    if not rows:
        return [], []
    width = max(len(r) for r in rows)
    first_known = sum(1 for h in rows[0] if _known(str(h).strip()))
    col0_known = sum(1 for r in rows if _known(str(r[0]).strip()))
    if width <= 3 and col0_known >= 3 and col0_known > first_known:
        pairs = [r for r in rows if _known(str(r[0]).strip())]
        headers = [str(r[0]).strip() for r in pairs]
        return headers, [[(r[1] if len(r) > 1 else None) for r in pairs]]
    headers = [str(h).strip() for h in rows[0]]
    return headers, [r + [None] * (len(headers) - len(r)) for r in rows[1:]]


_KV = re.compile(r"^\s*[-*\u2022]?\s*\**([^:|\n]{2,80}?)\**\s*[:=]\s*(.*)$")


def _text_rows(text: str) -> list[list]:
    """Plain text -> rows: a pipe table (also Markdown, also the '=== SHEET' dumps), tab/semicolon lines, or
    'Kolumna: wartość' lines (continuation lines are appended to the previous value)."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    body = [ln for ln in lines if ln.strip() and not ln.startswith("=== ")]
    pipe = [ln for ln in body if ln.count("|") >= 2]
    if len(pipe) >= 2 and len(pipe) >= len(body) * 0.6:
        out = []
        for ln in pipe:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue                                   # markdown separator row
            out.append(cells)
        return out
    for sep in ("\t", ";"):
        multi = [ln for ln in body if ln.count(sep) >= 3]
        if len(multi) >= 2 and len(multi) >= len(body) * 0.6:
            return [list(r) for r in csv.reader(io.StringIO("\n".join(multi)), delimiter=sep)]
    pairs: list[list] = []
    for ln in body:
        m = _KV.match(ln)
        if m and _known(m.group(1).strip()):
            pairs.append([m.group(1).strip(), m.group(2).strip()])
        elif pairs:                                       # continuation of a wrapped value (may itself contain ':')
            pairs[-1][1] = (str(pairs[-1][1]) + " " + ln.strip()).strip()
    if len(pairs) >= 3:
        return pairs
    # a two-column table printed to PDF: "Identyfikator rekordu RM-2026-023" lines (no colon), wrapped values continue
    names = sorted({x for f in registry.KNOWN_FORMATS.values() for x in f["headers"]}, key=len, reverse=True)
    pairs = []
    for ln in body:
        low = ln.strip().lower()
        h = next((n for n in names if low.startswith(n.lower()) and (len(low) == len(n) or not low[len(n)].isalnum())), None)
        if h:
            pairs.append([h, ln.strip()[len(h):].strip(" :\t")])
        elif pairs:
            pairs[-1][1] = (str(pairs[-1][1]) + " " + ln.strip()).strip()
    return pairs if len(pairs) >= 3 else []


def _docx_rows(path: Path) -> list[list]:
    from docx import Document
    doc = Document(str(path))
    best: list[list] = []
    for t in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        h, _d = _shape(rows)
        if sum(1 for x in h if _known(x)) > sum(1 for x in _shape(best)[0] if _known(x)):
            best = rows
    if best:
        return best
    return _text_rows("\n".join(p.text for p in doc.paragraphs))


def _json_rows(raw: bytes) -> list[list]:
    import json as _json
    data = _json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, dict):
        inner = next((v for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
        data = inner if inner is not None else [data.get("record") if isinstance(data.get("record"), dict) else data]
    recs = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    headers: list[str] = []
    for r in recs:
        headers += [k for k in r if k not in headers]
    return [headers] + [[r.get(h) for h in headers] for r in recs] if recs else []


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _csv_rows(text: str) -> list[list]:
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=";,\t|")
        delim = dialect.delimiter
    except csv.Error:                                     # one-row files often defeat the sniffer
        head = text.split("\n", 1)[0]
        delim = max(";,\t|", key=head.count)
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _pl_files(n: int) -> str:
    return "plik" if n == 1 else "pliki" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "plików"


def list_archive(path: Path) -> tuple[str, dict]:
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        size = sum(i.file_size for i in z.infolist())
    types = Counter(Path(n).suffix.lower() or "(bez rozszerzenia)" for n in names)
    out = f"{fmt_num(len(names))} {_pl_files(len(names))}, {len(types)} typów"
    return out, {"files": len(names), "types": dict(types.most_common(20)), "uncompressed_bytes": size, "names": names[:200]}


def _read_table(path: Path, n: int) -> tuple[str | None, list[str], list[list], int]:
    """-> (sheet, headers, first n rows, total rows). XLSX: the sheet 'Projekty' if present, else the sheet whose first
    row has the most known column names (an 'Opis kolumn' sheet can be longer than a one-row data sheet).
    CSV/TSV, TXT/MD, JSON, DOCX and PDF with text are read through `_shape` (horizontal or vertical record)."""
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv"):
        rows = _csv_rows(_decode(path.read_bytes()[:5_000_000]))
        headers, data = _shape(rows)
        return None, headers, data[:n], len(data)
    if ext in (".txt", ".md", ".markdown", ".json", ".docx", ".pdf"):
        if ext == ".json":
            rows = _json_rows(path.read_bytes()[:5_000_000])
        elif ext == ".docx":
            rows = _docx_rows(path)
        elif ext == ".pdf":
            from riskminer.documents.upload import pdf_pages
            rows = _text_rows("\n".join(pdf_pages(path)))
        else:
            rows = _text_rows(_decode(path.read_bytes()[:5_000_000]))
        headers, data = _shape(rows)
        return None, headers, data[:n], len(data)
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Projekty" in wb.sheetnames:
        ws = wb["Projekty"]
    else:
        def score(w):
            first = next(w.iter_rows(min_row=1, max_row=1, values_only=True), ()) or ()
            return (sum(1 for h in first if _known(str(h).strip() if h is not None else "")), w.max_row or 0)
        ws = max(wb.worksheets, key=score)
    all_rows = [list(r) for r in ws.iter_rows(values_only=True) if r and any(v not in (None, "") for v in r)]
    wb.close()
    headers, data = _shape(all_rows)
    return ws.title, headers, data[:n], len(data)


def read_all_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[list]]:
    sheet, headers, rows, total = _read_table(path, limit or 10**7)
    return headers, rows


def sample_rows(path: Path, n: int = MAX_SAMPLE) -> tuple[str, dict]:
    n = min(n, MAX_SAMPLE)
    sheet, headers, rows, total = _read_table(path, n)
    keep = [i for i, h in enumerate(headers) if not rules.is_pii_header(h)]
    dropped = [headers[i] for i in range(len(headers)) if i not in keep]
    sample = [[r[i] if i < len(r) else None for i in keep] for r in rows]
    out = f"{len(headers)} kolumn{', arkusz ' + sheet if sheet else ''}, {fmt_num(total)} wierszy"
    if dropped:
        out += f"; pominięto {len(dropped)} kolumn z danymi osobowymi"
    return out, {"sheet": sheet, "headers": [headers[i] for i in keep], "all_headers": headers, "pii_dropped": dropped,
                 "rows": [[None if v is None else str(v)[:200] for v in r] for r in sample], "total_rows": total}


def match_schema(headers: list[str], importers: list[dict]) -> tuple[str, dict]:
    """Known formats + approved importers in the DB; best header overlap."""
    cands = [{"name": k, "version": None, "headers": v["headers"], "importer_id": None} for k, v in registry.KNOWN_FORMATS.items()]
    cands += [{"name": i["name"], "version": i["version"], "headers": (i["spec"] or {}).get("headers") or [],
               "importer_id": i["id"]} for i in importers]
    best, score = None, 0.0
    for c in cands:
        s = registry.match_fraction(headers, c["headers"])
        if s > score:
            best, score = c, s
    matched = sum(1 for h in headers if registry.norm(h) in {registry.norm(x) for x in (best or {}).get("headers", [])})
    if best and score > 0:
        out = f"„{best['name']}”, {matched} z {len(headers)}"
    else:
        out = "brak znanego formatu"
    return out, {"best": best["name"] if best else None, "importer_id": (best or {}).get("importer_id"),
                 "version": (best or {}).get("version"), "score": round(score, 3), "matched": matched, "total": len(headers)}


def classify_docs(names: list[str], sample: int = MAX_CLASSIFY) -> tuple[str, dict]:
    """Document types from file names (deterministic classifier of the document connectors; no model)."""
    from riskminer.connectors.platforms import classify
    labels = {"swz": "SWZ", "pfu": "PFU", "ppu": "PPU", "opz": "OPZ", "projekt": "projekty", "przedmiar": "przedmiary",
              "stwiorb": "STWiORB", "qa": "pytania i odpowiedzi", "otwarcie": "protokoły otwarcia", "wybor": "wybór oferty",
              "kwota": "kwota na sfinansowanie", "umowa": "umowy", "aneks": "aneksy", "inne": "inne"}
    picked = [n for n in names if Path(n).suffix.lower() in DOCS][:sample]
    c = Counter(classify(Path(n).name)[0] for n in picked)
    out = ", ".join(f"{labels.get(k, k)} {v}" for k, v in c.most_common(6)) or "brak dokumentów"
    return out, {"sampled": len(picked), "types": dict(c)}
