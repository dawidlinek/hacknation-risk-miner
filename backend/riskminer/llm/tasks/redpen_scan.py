"""`redpen_scan`: signals per page with verified quotes (screen 1.3, flags in 1.2; docs/impl/llm.md §2.2).

Page-tagged text in windows of 6 pages with 1 page overlap, scanned in parallel. Every note's quote is verified on the
document (page corrected when found elsewhere); unverified notes get one re-quote retry and are otherwise stored as
`verification = 'unverified'` (red in the UI, never bulk-approvable, hidden in public mode). Missing-clause checks are
code rules owned by session A (`analytics/flags.py`), not this task.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from riskminer.config import settings
from riskminer.llm import gateway
from riskminer.llm.backends.base import PageText, Text
from riskminer.llm.errors import LLMError, SovereignUnavailable
from riskminer.llm.gateway import LLMRequest, LLMResult
from riskminer.llm.sanitize import copy_rules, scrub_contact
from riskminer.llm.schemas import Note, RedPenWindow
from riskminer.llm.verify import QuoteCheck, verify_quote

WINDOW = 6
OVERLAP = 1


@lru_cache
def catalogue(sector: str = "wod-kan") -> dict[str, Any]:
    from pathlib import Path

    base = Path(settings().catalogue_dir) / sector
    risks = yaml.safe_load((base / "risks.yaml").read_text(encoding="utf-8"))["risks"]
    clauses = yaml.safe_load((base / "clauses.yaml").read_text(encoding="utf-8"))["clauses"]
    codes = {r["id"]: r for r in risks}
    lines = []
    for r in risks:
        if r.get("status") == "rejected":
            continue
        pats = []
        for s in r.get("signals") or []:
            pats += [p for p in (s.get("patterns") or [])][:3]
        hint = f" ({'; '.join(pats[:4])})" if pats else ""
        indent = "  " if "." in r["id"] else ""
        lines.append(f"{indent}{r['id']}: {r['name']}{hint}")
    cl = [f"{c['code']}: {c['risk_code']}" for c in clauses if c.get("status") != "rejected"]
    return {"codes": codes, "clauses": {c["code"]: c for c in clauses}, "text": "\n".join(lines), "clauses_text": ", ".join(cl)}


def windows(pages: list[int], size: int = WINDOW, overlap: int = OVERLAP) -> list[list[int]]:
    if not pages:
        return []
    step = max(1, size - overlap)
    out = []
    for i in range(0, len(pages), step):
        w = pages[i:i + size]
        if out and set(w) <= set(out[-1]):
            break
        out.append(w)
        if i + size >= len(pages):
            break
    return out


@dataclass
class RedPenResult:
    document_id: int
    notes: list[dict[str, Any]] = field(default_factory=list)
    failed_pages: list[list[int]] = field(default_factory=list)
    processing: dict | None = None
    sovereign_unavailable: bool = False
    errors: list[str] = field(default_factory=list)
    llm_call_ids: list[int] = field(default_factory=list)


def _check_note(n: Note, pages: dict[int, str], cat: dict) -> tuple[QuoteCheck, str | None]:
    """Verify quote and catalogue codes. Returns (quote check, problem or None)."""
    code = (n.code or "").strip().upper()
    if code not in cat["codes"]:
        base = code.split(".")[0]
        if base in cat["codes"]:
            n.code = base
        else:
            return QuoteCheck("unverified", stated_page=n.page), f"nieznany kod {code}"
    else:
        n.code = code
    if n.clause_hint:
        cl = cat["clauses"].get(n.clause_hint.strip())
        if not cl or not (cl["risk_code"] == n.code or cl["risk_code"].split(".")[0] == n.code.split(".")[0]):
            n.clause_hint = None
    return verify_quote(n.quote, pages, n.page), None


async def _scan_window(doc: dict, wp: list[int], sens: str, subject: str | None, extra: str | None = None,
                       alias: str | None = None) -> LLMResult:
    cat = catalogue()
    parts = [Text(f"Dokument id={doc['id']} ({doc.get('doc_type') or 'dokument'}), strony {wp[0]} do {wp[-1]} z {len(doc['pages'])}.")]
    parts += [PageText(doc["id"], p, doc["pages"][p]) for p in wp]
    return await gateway.run(LLMRequest(
        task="redpen_scan", sensitivity=sens, prompt="redpen_scan", parts=parts, output=RedPenWindow,  # type: ignore[arg-type]
        prompt_vars={"catalogue": cat["text"], "clauses": cat["clauses_text"], "doc_type": doc.get("doc_type") or "dokument"},
        input_refs=[f"document:{doc['id']}"], subject=subject, timeout_kind="document", extra_user=extra,
        max_output_tokens=6000, alias=alias))


def _overlaps(a: dict, b: dict) -> bool:
    if a["page_no"] != b["page_no"] or a["code"].split(".")[0] != b["code"].split(".")[0]:
        return False
    if a.get("char_start") is None or b.get("char_start") is None:
        return a["quote"][:60] == b["quote"][:60]
    return a["char_start"] < b["char_end"] and b["char_start"] < a["char_end"]


async def redpen_scan(doc: dict, *, sensitivity: str = "public", subject: str | None = None,
                      alias: str | None = None) -> RedPenResult:
    """Scan one document ({id, doc_type, filename, sensitivity, pages: {page_no: text}}). Never raises for model
    failures: failed windows are listed in `failed_pages` (shown as 'strony X do Y nieprzeczytane')."""
    cat = catalogue()
    sens = "confidential" if (doc.get("sensitivity") == "confidential" or sensitivity == "confidential") else "public"
    pages_sorted = sorted(p for p, t in doc["pages"].items() if (t or "").strip())
    wins = windows(pages_sorted)
    res = RedPenResult(document_id=doc["id"])
    results = await asyncio.gather(*(_scan_window(doc, w, sens, subject, alias=alias) for w in wins), return_exceptions=True)
    raw_notes: list[tuple[Note, QuoteCheck, LLMResult, list[int]]] = []
    retry: list[tuple[list[int], list[Note]]] = []
    for w, r in zip(wins, results):
        if isinstance(r, SovereignUnavailable):
            res.sovereign_unavailable = True
            res.failed_pages.append([w[0], w[-1]])
            continue
        if isinstance(r, BaseException):
            res.errors.append(f"strony {w[0]}-{w[-1]}: {getattr(r, 'code', type(r).__name__)}")
            res.failed_pages.append([w[0], w[-1]])
            continue
        res.processing = res.processing or r.processing
        if r.llm_call_id:
            res.llm_call_ids.append(r.llm_call_id)
        bad = []
        for n in r.data.notes:
            qc, problem = _check_note(n, doc["pages"], cat)
            if problem:
                continue
            if qc.ok:
                raw_notes.append((n, qc, r, w))
            else:
                bad.append(n)
        if bad:
            retry.append((w, bad))
    # one re-quote retry per window that had unverified quotes
    if retry:
        async def requote(w: list[int], bad: list[Note]):
            msg = ("Te cytaty nie występują dosłownie w tekście tych stron. Zwróć te same uwagi jeszcze raz, z cytatami "
                   "skopiowanymi dosłownie z tekstu (bez zmian, bez skrótów), albo pomiń uwagę:\n" +
                   "\n".join(f"- {n.code} s. {n.page}: {n.quote}" for n in bad))
            try:
                return await _scan_window(doc, w, sens, subject, extra=msg, alias=alias)
            except LLMError:
                return None
        rr = await asyncio.gather(*(requote(w, bad) for w, bad in retry))
        for (w, bad), r in zip(retry, rr):
            fixed: set[int] = set()
            if r is not None:
                if r.llm_call_id:
                    res.llm_call_ids.append(r.llm_call_id)
                for n in r.data.notes:
                    qc, problem = _check_note(n, doc["pages"], cat)
                    if not problem and qc.ok:
                        for i, b in enumerate(bad):
                            if i not in fixed and b.code.split(".")[0] == n.code.split(".")[0]:
                                fixed.add(i)
                                break
                        raw_notes.append((n, qc, r, w))
            for i, b in enumerate(bad):
                if i not in fixed:
                    raw_notes.append((b, QuoteCheck("unverified", stated_page=b.page), r or results[wins.index(w)], w))  # type: ignore[arg-type]
    # build, dedupe across overlapping windows, number
    built: list[dict] = []
    for n, qc, r, w in raw_notes:
        item = {"code": n.code, "page_no": qc.page or n.page, "stated_page": n.page, "pkt": n.pkt,
                "quote": scrub_contact(n.quote), "title": copy_rules(n.title)[:90], "why": copy_rules(n.why),
                "strength": n.strength, "suggested_clause": n.clause_hint, "verification": qc.status,
                "score": qc.score, "reason": qc.reason, "page_mismatch": qc.page_mismatch or None,
                "char_start": qc.char_start, "char_end": qc.char_end, "llm": r.llm_info if r else None,
                "llm_call_id": r.llm_call_id if r else None, "window": [w[0], w[-1]]}
        dup = next((b for b in built if _overlaps(b, item)), None)
        if dup:
            if dup["verification"] == "unverified" and item["verification"] != "unverified":
                built[built.index(dup)] = item
            continue
        built.append(item)
    built.sort(key=lambda x: (x["verification"] == "unverified", x["page_no"] or 0, x["char_start"] or 0))
    for i, b in enumerate(built, 1):
        b["n"] = str(i)
    res.notes = built
    return res


def note_items(res: RedPenResult, doc: dict) -> list[dict[str, Any]]:
    """analysis_item insert dicts (section 'redpen_note', origin AI, review_status proposed)."""
    out = []
    for b in res.notes:
        body = {"kind": "found", "n": b["n"], "title": b["title"], "text": b["why"], "why": b["why"],
                "risk_codes": [b["code"]], "risk_code": b["code"], "page_no": b["page_no"], "char_start": b["char_start"],
                "char_end": b["char_end"], "clause_ref": b["pkt"], "locator": b["pkt"], "suggested_clause": b["suggested_clause"],
                "strength": b["strength"], "doc_type": doc.get("doc_type"), "verification": b["verification"],
                "quote_score": b["score"], "verification_reason": b["reason"], "page_mismatch": b["page_mismatch"],
                "llm": b["llm"], "bulk_approvable": b["verification"] != "unverified"}
        out.append({"section": "redpen_note", "key": f"redpen:{doc['id']}:{b['n']}", "title": b["title"],
                    "catalogue_code": b["code"][:12], "origin": "AI", "review_status": "proposed", "body": body,
                    "document_id": doc["id"], "page_no": b["page_no"], "quote": b["quote"],
                    "verification": b["verification"], "llm_call_id": b["llm_call_id"], "rank": int(b["n"])})
    return out
