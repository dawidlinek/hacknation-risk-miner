"""`classify_causes`: national change-cause classification (docs/impl/llm.md §2.3).

Unique cause texts (dedupe by `rm_cause_norm` in SQL, migration 0008) are packed 25 per call, classified by the `bulk`
alias, quote-verified inside the item's own text and stored in `change_cause_ai` (origin AI, review_status proposed),
idempotent per (norm_md5, model, prompt_version), so a run can be stopped and resumed. Keyword codes
(`contract_change.cause_codes_kw`) order the work and give agreement, they do not replace the model.

After a run, `propose_events` turns (a) the pilot projects' changes and (b) a review sample (lowest confidence,
keyword disagreement, largest delta) into AI `risk_event` proposals for the Przegląd queue (B's review_sync)."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from riskminer.llm import gateway, labels
from riskminer.llm.backends.base import Text
from riskminer.llm.errors import BudgetExceeded, LLMError
from riskminer.llm.gateway import LLMRequest
from riskminer.llm.verify import match_in_text

PACK = 25
HIGH_PRECISION_KW = {"N-COVID", "R12", "R03", "N-WEATHER", "R02"}     # precision ≥ 0.82 on gold (bucket 4)


@lru_cache
def batch_model() -> type[BaseModel]:
    code_t = Literal[tuple(labels.codes())]  # type: ignore[valid-type]
    item = create_model("CauseItemOut", id=(str, ...), primary=(code_t, ...), secondary=(code_t | None, None),
                        quote=(str, ...), confidence=(float, Field(0.5, ge=0, le=1)))
    return create_model("CauseBatchOut", items=(list[item], ...))  # type: ignore[valid-type]


def item_text(cause: str | None, descr: str | None) -> str:
    c = (cause or "").strip()
    d = (descr or "").strip()[:600]
    return f"Przyczyna: {c or '(brak)'}\nOpis zmiany: {d or '(brak)'}"


def prompt_vars(examples: list[dict] | None = None) -> dict:
    lab = "\n".join(f"{k}: {v}" for k, v in labels.labels().items())
    ex = ""
    if examples:
        ex = "\nPrzykłady zatwierdzone przez eksperta:\n" + "\n".join(
            f"<przyklad kod=\"{e['code']}\">{e['text'][:400]}</przyklad>" for e in examples[:8])
    return {"labels": lab, "examples": ex}


@dataclass
class Classified:
    id: str
    primary: str
    secondary: str | None
    quote: str
    verification: str
    confidence: float
    llm_call_id: int | None
    provider: str
    model: str
    prompt_version: str


@dataclass
class BatchOutcome:
    done: list[Classified] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str | None = None


async def classify_pack(items: list[dict], *, alias: str | None = None, subject: str | None = None,
                        examples: list[dict] | None = None, run_budget: bool = True) -> BatchOutcome:
    """items: [{id, text}] (≤ 25). Ids are replaced by short local ids in the prompt and mapped back."""
    local = {f"i{n}": it for n, it in enumerate(items, 1)}
    body = "\n".join(f'<item id="{lid}">\n{it["text"]}\n</item>' for lid, it in local.items())
    out = BatchOutcome()
    try:
        res = await gateway.run(LLMRequest(
            task="classify_causes", sensitivity="public", prompt="classify_causes", parts=[Text(body)],
            output=batch_model(), prompt_vars=prompt_vars(examples), alias=alias, subject=subject,
            timeout_kind="batch_call", run_budget_key="classify_causes" if run_budget else None,
            max_output_tokens=max(2048, 160 * len(items))))
    except BudgetExceeded:
        raise
    except LLMError as e:
        out.failed = [it["id"] for it in items]
        out.error = f"{e.code}: {str(e)[:200]}"
        return out
    out.cost_usd = res.cost_usd
    seen: set[str] = set()
    for r in res.data.items:
        it = local.get(r.id)
        if it is None or r.id in seen:
            continue
        seen.add(r.id)
        prim = labels.normalise_code(r.primary)
        if prim is None:
            continue
        qc = match_in_text(r.quote, it["text"])
        out.done.append(Classified(id=it["id"], primary=prim, secondary=labels.normalise_code(r.secondary),
                                   quote=r.quote[:300], verification=qc.status, confidence=float(r.confidence),
                                   llm_call_id=res.llm_call_id, provider=res.provider, model=res.model,
                                   prompt_version=res.prompt_version))
    out.missing = [it["id"] for lid, it in local.items() if lid not in seen]
    return out


async def classify_items(items: list[dict], *, alias: str | None = None, subject: str | None = None,
                         examples: list[dict] | None = None, concurrency: int = 16, pack: int = PACK,
                         run_budget: bool = True) -> tuple[list[Classified], list[str]]:
    """Classify any number of {id, text}; ids missing from a packed answer are retried one by one."""
    packs = [items[i:i + pack] for i in range(0, len(items), pack)]
    sem = asyncio.Semaphore(concurrency)

    async def one(p, sub):
        async with sem:
            return await classify_pack(p, alias=alias, subject=sub, examples=examples, run_budget=run_budget)

    res = await asyncio.gather(*(one(p, f"{subject}:{i}" if subject else None) for i, p in enumerate(packs)))
    done = [c for r in res for c in r.done]
    by_id = {it["id"]: it for it in items}
    retry = [by_id[i] for r in res for i in r.missing]
    failed = [i for r in res for i in r.failed]
    if retry:
        res2 = await asyncio.gather(*(one([it], f"{subject}:retry" if subject else None) for it in retry))
        done += [c for r in res2 for c in r.done]
        failed += [i for r in res2 for i in r.missing + r.failed]
    return done, failed


# ---------------------------------------------------------------------------------------------------------------------
# national run (DB)
# ---------------------------------------------------------------------------------------------------------------------
UNIQUE_SQL = """
WITH g AS (
  SELECT md5(rm_cause_norm(cc.cause_text, cc.description_text)) AS norm_md5, min(cc.id) AS sample_id, count(*) AS n,
         max(abs(coalesce(cc.delta_value_amount, 0))) AS max_delta
  FROM contract_change cc JOIN procedure p ON p.id = cc.procedure_id
  WHERE (cc.cause_text IS NOT NULL OR cc.description_text IS NOT NULL)
    AND p.sector = $3 AND p.relevance = ANY($4::text[])
  GROUP BY 1)
SELECT g.norm_md5, g.sample_id, g.n, g.max_delta, c.cause_text, c.description_text, c.cause_codes_kw
FROM g JOIN contract_change c ON c.id = g.sample_id
WHERE NOT EXISTS (SELECT 1 FROM change_cause_ai a WHERE a.norm_md5 = g.norm_md5 AND a.model = $1 AND a.prompt_version = $2)
"""


def bucket(kw: list[str] | None) -> int:
    kw = [k for k in (kw or []) if k]
    if not kw:
        return 1
    if len(kw) > 1:
        return 2
    return 4 if kw[0] in HIGH_PRECISION_KW else 3


async def national_run(*, limit: int | None = None, buckets: tuple[int, ...] = (1, 2, 3, 4), alias: str | None = None,
                       run_id: str | None = None, chunk: int = 1000, concurrency: int = 16,
                       sector: str = "wod-kan", relevance: tuple[str, ...] = ("core", "component"),
                       progress: Any = None) -> dict:
    """Classify unique cause texts not yet classified with the current model + prompt. Resumable."""
    from riskminer.db.session import raw_conn
    from riskminer.llm import prompts
    from riskminer.llm.config import llm_config

    cfg = llm_config()
    al = alias or (cfg.tasks.get("classify_causes") or {}).get("public", "bulk")
    _, model = cfg.resolve(al)
    pv = prompts.load("classify_causes").ref
    run_id = run_id or time.strftime("%Y%m%d%H%M") + "-" + uuid.uuid4().hex[:4]
    async with raw_conn() as conn:
        rows = [dict(r) for r in await conn.fetch(UNIQUE_SQL, model, pv, sector, list(relevance))]
    for r in rows:
        r["bucket"] = bucket(r["cause_codes_kw"])
    rows = [r for r in rows if r["bucket"] in buckets]
    rows.sort(key=lambda r: (r["bucket"], -r["n"]))
    if limit:
        rows = rows[:limit]
    stats = {"run_id": run_id, "sector": sector, "relevance": list(relevance), "model": model, "prompt_version": pv, "todo": len(rows), "done": 0, "failed": 0,
             "unverified": 0, "agree_kw": 0, "cost_usd": 0.0, "stopped": None}
    t0 = time.time()
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        items = [{"id": r["norm_md5"], "text": item_text(r["cause_text"], r["description_text"])} for r in part]
        try:
            done, failed = await classify_items(items, alias=al, subject=f"run:classify_causes:{run_id}:{i // chunk}",
                                                concurrency=concurrency)
        except BudgetExceeded as e:
            stats["stopped"] = f"budget: {e}"
            break
        meta = {r["norm_md5"]: r for r in part}
        recs = []
        for c in done:
            m = meta[c.id]
            kw = [k for k in (m["cause_codes_kw"] or []) if k]
            kw_n = [labels.normalise_code(k) or k for k in kw]
            agrees = (c.primary in kw_n) if kw_n else None
            stats["agree_kw"] += bool(agrees)
            stats["unverified"] += c.verification == "unverified"
            recs.append((c.id, m["sample_id"], m["n"], c.primary, c.secondary, c.quote, c.verification, c.confidence,
                         kw, agrees, c.provider, c.model, c.prompt_version, c.llm_call_id, run_id))
        async with raw_conn() as conn:
            await conn.executemany(
                "INSERT INTO change_cause_ai (norm_md5, sample_change_id, n_changes, primary_code, secondary_code, quote, "
                "verification, confidence, kw_codes, agrees_kw, provider, model, prompt_version, llm_call_id, run_id) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) "
                "ON CONFLICT (norm_md5, model, prompt_version) DO NOTHING", recs)
            stats["cost_usd"] = round(float(await conn.fetchval(
                "SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE subject LIKE $1", f"run:classify_causes:{run_id}%")), 4)
        stats["done"] += len(done)
        stats["failed"] += len(failed)
        stats["elapsed_s"] = int(time.time() - t0)
        if progress:
            await progress(dict(stats))
    return stats


async def propose_events(run_id: str | None = None, sample: int = 40) -> dict:
    """AI risk_event proposals (review_status proposed) for the review queue: every pilot-project change plus a review
    sample of at most `sample` national changes. Key 'ai:cause:<change_id>' keeps it idempotent."""
    from riskminer.db.session import raw_conn

    base = """
    SELECT v.change_id, cc.contract_id, cc.procedure_id, pp.project_id, v.primary_code, v.secondary_code, v.confidence,
           v.quote, v.verification, v.llm_call_id, v.model, cc.cause_text, cc.description_text, cc.cause_codes_kw,
           cc.delta_days, cc.delta_value_amount, cc.delta_value_currency, cc.delta_value_vat, cc.changed_on, cc.notice_id,
           coalesce(nt.source_id, cc.source_id) AS source_id
    FROM v_change_cause_ai v JOIN contract_change cc ON cc.id = v.change_id
    LEFT JOIN notice nt ON nt.id = cc.notice_id
    LEFT JOIN LATERAL (SELECT project_id FROM project_procedure WHERE procedure_id = cc.procedure_id LIMIT 1) pp ON true
    WHERE v.review_status = 'proposed' AND v.verification IN ('exact', 'fuzzy')
      AND NOT EXISTS (SELECT 1 FROM risk_event e WHERE e.key = 'ai:cause:' || v.change_id)"""
    async with raw_conn() as conn:
        pilot = [dict(r) for r in await conn.fetch(base + " AND pp.project_id IS NOT NULL")]
        # stratified review sample: per catalogue code (N-UNSPEC / N-FORMAL excluded), keyword disagreement first,
        # then lowest confidence, then the largest value change; round-robin over codes up to `sample`
        cand = [dict(r) for r in await conn.fetch(base + """ AND pp.project_id IS NULL
            AND v.primary_code NOT IN ('N-UNSPEC', 'N-FORMAL')
            ORDER BY (CASE WHEN NOT (v.primary_code = ANY(coalesce(cc.cause_codes_kw, '{}'))) AND cardinality(cc.cause_codes_kw) > 0
                      THEN 0 ELSE 1 END), v.confidence ASC NULLS FIRST, abs(coalesce(cc.delta_value_amount, 0)) DESC
            LIMIT 4000""")]
        per: dict[str, list[dict]] = {}
        for r in cand:
            per.setdefault(r["primary_code"], []).append(r)
        nat = []
        while len(nat) < sample and any(per.values()):
            for code in sorted(per, key=lambda c: -len(per[c])):
                if per[code] and len(nat) < sample:
                    nat.append(per[code].pop(0))
        n = 0
        for r in pilot + nat:
            name = labels.labels().get(r["primary_code"], r["primary_code"])
            summary = f"Zmiana umowy: przyczyna według modelu {r['primary_code']} ({name.split(':')[0]})"
            eid = await conn.fetchval(
                "INSERT INTO risk_event (project_id, procedure_id, contract_id, change_id, event_type, catalogue_code, "
                "summary, cause, impact_days, impact_value_amount, impact_value_currency, impact_value_vat, occurred_on, "
                "conf_data_quality, llm_call_id, key, source_id, origin, review_status) VALUES ($1,$2,$3,$4,'EV_CHANGE_CAUSE_AI',$5,"
                "$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'AI','proposed') ON CONFLICT (key) DO NOTHING RETURNING id",
                r["project_id"], r["procedure_id"], r["contract_id"], r["change_id"], r["primary_code"][:12], summary,
                (r["cause_text"] or r["description_text"] or "")[:2000], r["delta_days"], r["delta_value_amount"],
                r["delta_value_currency"], r["delta_value_vat"], r["changed_on"], r["confidence"], r["llm_call_id"],
                f"ai:cause:{r['change_id']}", r["source_id"])
            if eid:
                n += 1
                await conn.execute(
                    "INSERT INTO evidence (claim_table, claim_id, claim_field, notice_id, source_id, quote, verification, note) "
                    "VALUES ('risk_event', $1, 'catalogue_code', $2, $3, $4, $5, $6)",
                    eid, r["notice_id"], r["source_id"], r["quote"], r["verification"],
                    f"model {r['model']}, drugi kod {r['secondary_code'] or 'brak'}")
    return {"pilot": len(pilot), "sample": len(nat), "inserted": n}
