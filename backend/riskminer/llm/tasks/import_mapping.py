"""`import_mapping`: field suggestions for columns the import rules could not map (2.1 import agent, docs/impl/llm.md §2.6).

Called by session D's `imports/service.py` as `await propose(headers=, sample=, fields=)` → {column: field}. The model sees
only headers, ≤ 5 sample values per column (personal data already dropped by the sandbox) and the target-field
registry; it proposes, the rules in `imports/rules.py` validate, nothing it writes is executed."""
from __future__ import annotations

from typing import Any

from riskminer.llm import gateway
from riskminer.llm.backends.base import Json
from riskminer.llm.gateway import LLMRequest
from riskminer.llm.sanitize import scrub_contact
from riskminer.llm.schemas import ImportMapping

LAST: dict[str, Any] = {}   # last full answer (mapping rows with confidence/why, questions), for the tool-call log


def _columns(headers: list[str], sample: dict, per_col: int = 5) -> list[dict]:
    hdrs = sample.get("headers") or []
    rows = sample.get("rows") or []
    out = []
    for h in headers:
        vals: list[str] = []
        if h in hdrs:
            i = hdrs.index(h)
            for r in rows:
                v = r[i] if isinstance(r, (list, tuple)) and i < len(r) else (r.get(h) if isinstance(r, dict) else None)
                if v not in (None, "") and len(vals) < per_col:
                    vals.append(scrub_contact(str(v))[:80])
        out.append({"kolumna": h, "przyklady": vals})
    return out


async def propose(*, headers: list[str], sample: dict, fields: list[str], sensitivity: str = "public",
                  subject: str | None = None) -> dict[str, str]:
    from riskminer.imports.registry import TARGET_FIELDS

    if not headers:
        return {}
    flist = "\n".join(f"{f}: {TARGET_FIELDS.get(f, (f,))[0]}" for f in fields)
    res = await gateway.run(LLMRequest(
        task="import_mapping", sensitivity=sensitivity, prompt="import_mapping",  # type: ignore[arg-type]
        parts=[Json(_columns(headers, sample), tag="kolumny")], output=ImportMapping, prompt_vars={"fields": flist},
        subject=subject or "import", max_output_tokens=2000))
    m: ImportMapping = res.data
    allowed = set(fields)
    used: set[str] = set()
    out: dict[str, str] = {}
    for row in sorted(m.mapping, key=lambda r: -r.confidence):
        if row.column in headers and row.field in allowed and row.field not in used and row.confidence >= 0.5:
            out[row.column] = row.field
            used.add(row.field)
    LAST.clear()
    LAST.update({"mapping": [r.model_dump() for r in m.mapping], "questions": [q.model_dump() for q in m.questions],
                 "summary": m.summary, "processing": res.processing, "llm_call_id": res.llm_call_id})
    return out
