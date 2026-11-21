"""Gold-set benchmark for classify_causes (docs/impl/llm.md §4): 150 hand-labelled causes, zero-shot.

Metrics: primary accuracy, primary in {gold primary, gold secondary}, macro-F1 (classes with support ≥ 3, and all),
per-class precision/recall, Cohen's κ, quote verification rate, latency p50/p95, cost per 1,000 items, 95% bootstrap
CIs. Results go to `model_eval` and exports/eval/<run>.json. Gold N-WEATHER is mapped to R16 (labels.ALIASES).

    uv run python -m riskminer.llm.eval.gold --aliases fast,strong
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path

from riskminer.config import REPO_ROOT, settings
from riskminer.llm import labels
from riskminer.llm.tasks.classify_causes import classify_items, item_text


def gold_rows() -> tuple[list[dict], str]:
    from riskminer.llm.config import llm_config
    p = REPO_ROOT / (llm_config().eval.get("gold_set") or "research/bzp_corpus/data/gold_change_reasons.csv")
    raw = p.read_bytes()
    return list(csv.DictReader(raw.decode("utf-8").splitlines())), hashlib.sha256(raw).hexdigest()


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if not n:
        return 0.0
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0


def per_class(gold: list[str], pred: list[str]) -> dict[str, dict]:
    out = {}
    for c in sorted(set(gold) | set(pred)):
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        out[c] = {"support": tp + fn, "tp": tp, "precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3)}
    return out


def bootstrap_ci(hits: list[int], n_boot: int = 1000, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    n = len(hits)
    if not n:
        return [0.0, 0.0]
    vals = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return [round(vals[int(0.025 * n_boot)], 3), round(vals[int(0.975 * n_boot) - 1], 3)]


async def eval_alias(alias: str, rows: list[dict], variant: str = "packed25") -> dict:
    from riskminer.db.session import raw_conn
    from riskminer.llm.config import llm_config

    cfg = llm_config()
    prov, model = cfg.resolve(alias)
    run = f"eval:{alias}:{variant}:{int(time.time())}"
    items = [{"id": r["sample_id"], "text": item_text(r["reason"], r["description"])} for r in rows]
    t0 = time.time()
    done, failed = await classify_items(items, alias=alias, subject=run, pack=25 if variant == "packed25" else 1,
                                        concurrency=8, run_budget=False)
    wall = time.time() - t0
    by = {c.id: c for c in done}
    gold, pred, hits, hits_ps, ver = [], [], [], [], Counter()
    confusion: dict[str, Counter] = {}
    for r in rows:
        g = labels.normalise_code(r["primary"]) or r["primary"]
        s = labels.normalise_code(r.get("secondary")) if r.get("secondary") else None
        c = by.get(r["sample_id"])
        p = c.primary if c else "MISSING"
        gold.append(g)
        pred.append(p)
        hits.append(int(p == g))
        hits_ps.append(int(p in (g, s)))
        ver[c.verification if c else "missing"] += 1
        confusion.setdefault(g, Counter())[p] += 1
    pc = per_class(gold, pred)
    f1_3 = [v["f1"] for k, v in pc.items() if v["support"] >= 3]
    f1_all = [v["f1"] for v in pc.values() if v["support"] > 0]
    async with raw_conn() as conn:
        lat = [r["latency_ms"] for r in await conn.fetch(
            "SELECT latency_ms FROM llm_call WHERE subject LIKE $1 AND status = 'ok'", run + "%")]
        cost = float(await conn.fetchval("SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE subject LIKE $1", run + "%") or 0)
    n = len(rows)
    metrics = {
        "accuracy": round(sum(hits) / n, 3), "accuracy_ci95": bootstrap_ci(hits),
        "accuracy_primary_or_secondary": round(sum(hits_ps) / n, 3), "accuracy_ps_ci95": bootstrap_ci(hits_ps),
        "macro_f1_support3": round(statistics.mean(f1_3), 3) if f1_3 else None,
        "macro_f1_all": round(statistics.mean(f1_all), 3) if f1_all else None,
        "kappa": kappa(gold, pred), "quotes_verified": round((ver["exact"] + ver["fuzzy"]) / n, 3),
        "json_missing": len(failed) + ver["missing"], "latency_p50_ms": int(statistics.median(lat)) if lat else None,
        "latency_p95_ms": int(sorted(lat)[int(0.95 * (len(lat) - 1))]) if lat else None, "wall_s": round(wall, 1),
        "cost_usd": round(cost, 4), "cost_per_1000_usd": round(cost / n * 1000, 3), "calls": len(lat),
    }
    return {"alias": alias, "provider": prov.id, "model": model, "variant": variant, "n": n, "metrics": metrics,
            "per_class": pc, "confusion": {g: dict(c) for g, c in confusion.items()}, "run": run,
            "data_location": prov.data_location}


async def run_eval(aliases: list[str] | None = None, variant: str = "packed25") -> dict:
    from riskminer.db.session import raw_conn
    from riskminer.llm import prompts

    rows, sha = gold_rows()
    aliases = aliases or ["fast"]
    pv = prompts.load("classify_causes").ref
    out = {"gold_sha256": sha, "prompt_version": pv, "results": []}
    for a in aliases:
        try:
            res = await eval_alias(a, rows, variant)
        except Exception as e:  # noqa: BLE001  e.g. sovereign provider down
            out["results"].append({"alias": a, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            continue
        out["results"].append(res)
        if not res["metrics"]["calls"]:
            res["error"] = "no successful calls (provider down or billing)"
            continue
        async with raw_conn() as conn:
            await conn.execute(
                "INSERT INTO model_eval (task, gold_sha256, alias, provider, model, prompt_version, variant, n, metrics, "
                "per_class, confusion, cost_usd) VALUES ('classify_causes', $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                sha, a, res["provider"], res["model"], pv, variant, res["n"], res["metrics"], res["per_class"],
                res["confusion"], res["metrics"]["cost_usd"])
    d = Path(settings().exports_dir) / "eval"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"classify_causes_{time.strftime('%Y%m%d_%H%M')}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    out["file"] = str(path)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aliases", default="fast")
    ap.add_argument("--variant", default="packed25", choices=["packed25", "single"])
    a = ap.parse_args()
    res = asyncio.run(run_eval(a.aliases.split(","), a.variant))
    for r in res["results"]:
        m = r.get("metrics") or {}
        print(r["alias"], r.get("model"), r.get("error") or
              f"acc {m['accuracy']} {m['accuracy_ci95']} | p/s {m['accuracy_primary_or_secondary']} | F1(≥3) {m['macro_f1_support3']} "
              f"| κ {m['kappa']} | quotes {m['quotes_verified']} | p50 {m['latency_p50_ms']} ms | ${m['cost_usd']}")
    print(res["file"])


if __name__ == "__main__":
    main()
