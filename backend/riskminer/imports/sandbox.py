"""Registered tools of the import agent (api_contract §3.5 step 2). Only these functions touch uploaded files:
no shell, no network, no file goes to a model whole. Each call returns (out_text, data) and is logged by the service
in import_session.tool_calls with its duration."""
from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from pathlib import Path

from riskminer.api.prov import fmt_num
from riskminer.imports import registry, rules

MAX_SAMPLE = 20
MAX_CLASSIFY = 40
TABULAR = {".xlsx", ".xlsm", ".csv"}
DOCS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".xlsx", ".xls", ".zip"}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv", ".zip": "zip", ".pdf": "pdf", ".docx": "docx",
            ".doc": "doc", ".odt": "odt"}.get(ext, ext.lstrip(".") or "bin")


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
    """-> (sheet, headers, first n rows, total rows). XLSX: the sheet 'Projekty' if present, else the largest."""
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()[:5_000_000]
        for enc in ("utf-8-sig", "cp1250"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=";,\t")
        rows = list(csv.reader(io.StringIO(text), dialect))
        return None, [h.strip() for h in rows[0]], rows[1:n + 1], max(0, len(rows) - 1)
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Projekty"] if "Projekty" in wb.sheetnames else max(wb.worksheets, key=lambda w: w.max_row or 0)
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(it, [])]
    rows, total = [], 0
    for r in it:
        if not r or not any(v not in (None, "") for v in r):
            continue
        total += 1
        if len(rows) < n:
            rows.append(list(r))
    wb.close()
    return ws.title, headers, rows, total


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
