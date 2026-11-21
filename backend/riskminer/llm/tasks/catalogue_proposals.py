"""`catalogue_proposals`: new risk categories or merges from causes the classifier could not place (3.1 "Propozycje do
katalogu", 3.2 "Propozycje AI"; docs/impl/llm.md §2.8).

Sample: up to 200 texts labelled N-* (except N-UNSPEC / N-FORMAL) or with confidence < 0.5. The model proposes names,
definitions and 3 example ids; code checks the ids, recomputes counts (how many classified texts the examples' codes
cover), dedupes names against the catalogue (rapidfuzz token_set_ratio ≥ 85 → merge suggestion) and inserts
catalogue_risk rows origin AI, status proposed (B's review_sync turns them into review items)."""
from __future__ import annotations

from rapidfuzz import fuzz

from riskminer.llm import gateway
from riskminer.llm.backends.base import Json
from riskminer.llm.gateway import LLMRequest
from riskminer.llm.sanitize import copy_rules
from riskminer.llm.schemas import ProposalBatch

SAMPLE_SQL = """
SELECT a.norm_md5 AS id, a.primary_code, a.confidence, left(coalesce(cc.cause_text, '') || ' | ' || left(coalesce(cc.description_text, ''), 200), 360) AS text
FROM change_cause_ai a JOIN contract_change cc ON cc.id = a.sample_change_id
WHERE a.review_status <> 'rejected' AND ((a.primary_code LIKE 'N-%' AND a.primary_code NOT IN ('N-UNSPEC', 'N-FORMAL'))
      OR a.confidence < 0.5)
ORDER BY md5(a.norm_md5 || $2) LIMIT $1"""


async def propose(sample: int = 200, *, insert: bool = True, seed: str = "1") -> dict:
    from riskminer.db.session import raw_conn

    async with raw_conn() as conn:
        rows = [dict(r) for r in await conn.fetch(SAMPLE_SQL, sample, seed)]
        cat = [dict(r) for r in await conn.fetch(
            "SELECT DISTINCT ON (code) code, name, status FROM catalogue_risk WHERE sector = 'wod-kan' AND status <> 'rejected' "
            "ORDER BY code, version DESC")]
    if not rows:
        return {"proposals": [], "note": "brak próbki"}
    short = {f"c{i}": r for i, r in enumerate(rows, 1)}
    res = await gateway.run(LLMRequest(
        task="catalogue_proposals", sensitivity="public", prompt="catalogue_proposals",
        parts=[Json([{"id": k, "kod_modelu": r["primary_code"], "tekst": r["text"]} for k, r in short.items()], tag="probka")],
        output=ProposalBatch, prompt_vars={"catalogue": "\n".join(f"{c['code']}: {c['name']}" for c in cat if "." not in c["code"])},
        subject="catalogue_proposals", max_output_tokens=3000))
    codes = {c["code"] for c in cat}
    out = []
    for p in res.data.proposals:
        ex = [short[i] for i in p.example_ids if i in short][:3]
        if len(ex) < 2:
            continue
        best = max(cat, key=lambda c: fuzz.token_set_ratio(p.name.lower(), c["name"].lower()))
        score = fuzz.token_set_ratio(p.name.lower(), best["name"].lower())
        merge = p.merge_with if p.merge_with in codes else (best["code"] if score >= 85 else None)
        ex_codes = sorted({e["primary_code"] for e in ex})
        out.append({"name": copy_rules(p.name)[:120], "definition": copy_rules(p.definition), "merge_with": merge,
                    "name_similarity": {"code": best["code"], "score": round(score, 1)},
                    "example_ids": [e["id"] for e in ex], "examples": [e["text"][:200] for e in ex],
                    "example_codes": ex_codes, "rationale": copy_rules(p.rationale)})
    if insert and out:
        async with raw_conn() as conn:
            for o in out:
                if o["merge_with"]:
                    continue           # merges go to the review as notes on the existing risk, not as a new code
                n_texts = await conn.fetchval("SELECT count(*) FROM change_cause_ai WHERE primary_code = ANY($1::text[]) "
                                              "AND review_status <> 'rejected'", o["example_codes"])
                nxt = await conn.fetchval(
                    "SELECT 'R' || lpad((coalesce(max(substring(code from '^R(\\d+)$')::int), 18) + 1)::text, 2, '0') "
                    "FROM catalogue_risk WHERE sector = 'wod-kan'")
                o["code"] = nxt
                o["n_texts_with_example_codes"] = int(n_texts or 0)
                await conn.execute(
                    "INSERT INTO catalogue_risk (code, level, name, description, sector, status, version, origin, proposed_by, data) "
                    "VALUES ($1, 1, $2, $3, 'wod-kan', 'proposed', 1, 'AI', $4, $5) ON CONFLICT DO NOTHING",
                    nxt, o["name"], o["definition"], f"llm:{res.model}",
                    {"merge_suggestion": o["merge_with"], "examples": o["examples"], "example_ids": o["example_ids"],
                     "rationale": o["rationale"], "llm": res.llm_info, "counts_basis": "change_cause_ai, kody przykładów"})
    return {"proposals": out, "processing": res.processing, "sample": len(rows)}
