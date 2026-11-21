"""National document sample for `docs_sample` (docs/scrape.md §4) -> data/ref/doc_sample.csv.

Strata (each procedure once, pilot procedures excluded, core water/sewage works only):
  overrun 50, delay 50, art. 455 ust. 1 pkt 4 changes 30, design-build 30 (5 per subsector), random controls 50.
Within a stratum, procedures on platforms whose documents are publicly downloadable come first
(ezamawiajacy / e-Zamówienia / other); platformazakupowa.pl and logintrade forbid attachment downloads in
robots.txt, so they are used only to fill a stratum.
"""
from __future__ import annotations

import csv
from pathlib import Path

from riskminer.config import settings

PLATFORM_RANK = """CASE
  WHEN p.platform_url ILIKE '%ezamawiajacy.pl%' THEN 1
  WHEN p.platform_url ILIKE '%ezamowienia.gov.pl%' THEN 2
  WHEN p.platform_url ILIKE '%platformazakupowa.pl%' OR p.platform_url ILIKE '%logintrade%' THEN 9
  WHEN p.platform_url ILIKE '%uzp.gov.pl%' OR p.platform_url IS NULL THEN 8
  ELSE 3 END"""

BASE = f"""
  FROM rc_contract r JOIN procedure p ON p.id = r.procedure_id
  WHERE r.relevance = 'core' AND r.scope_kind = 'works'
    AND p.id NOT IN (SELECT procedure_id FROM project_procedure)
"""

STRATA = [
    ("overrun", 50, f"SELECT DISTINCT ON (p.id) p.id, r.cost_dev_pct AS metric, {PLATFORM_RANK} AS prank {BASE} AND r.cost_dev_pct > 5",
     "metric DESC", "Największe przekroczenie kosztu: wypłata {m:+.1f}% vs wartość umowy"),
    ("delay", 50, f"SELECT DISTINCT ON (p.id) p.id, r.delay_days AS metric, {PLATFORM_RANK} AS prank {BASE} AND r.late AND r.delay_days > 60",
     "metric DESC", "Najdłuższe opóźnienie: +{m:.0f} dni"),
    ("art455_1_4", 30, f"""SELECT DISTINCT ON (p.id) p.id, 1.0 AS metric, {PLATFORM_RANK} AS prank {BASE}
        AND EXISTS (SELECT 1 FROM contract_change ch WHERE ch.procedure_id = p.id AND ch.kind = 'change_notice'
                    AND '455.1.4' = ANY(ch.legal_basis))""", "random()", "Ogłoszenie o zmianie umowy z art. 455 ust. 1 pkt 4"),
    ("design_build", 30, f"SELECT DISTINCT ON (p.id) p.id, 0.0 AS metric, {PLATFORM_RANK} AS prank, p.subsector_main AS sub {BASE} AND r.design_build",
     "random()", "Formuła zaprojektuj i wybuduj (podsektor {sub})"),
    ("control", 50, f"""SELECT DISTINCT ON (p.id) p.id, 0.0 AS metric, {PLATFORM_RANK} AS prank {BASE}
        AND r.on_time_declared AND coalesce(r.changes_count, 0) = 0 AND abs(coalesce(r.cost_dev_pct, 0)) < 0.5""",
     "random()", "Próba kontrolna: w terminie, bez zmian, bez przekroczenia kosztu"),
]


async def run(conn, rid=None) -> dict:
    await conn.execute("SELECT setseed(0.42)")
    chosen: dict[int, dict] = {}
    counts = {}
    for name, n, sql, order, reason in STRATA:
        rows = await conn.fetch(f"SELECT * FROM ({sql}) q ORDER BY prank, {order}")
        picked = []
        if name == "design_build":   # 5 per subsector, all 6 represented when available
            per: dict[str, int] = {}
            for r in rows:
                if r["id"] in chosen or per.get(r["sub"], 0) >= 5:
                    continue
                per[r["sub"]] = per.get(r["sub"], 0) + 1
                picked.append(r)
                if len(picked) >= n:
                    break
        else:
            for r in rows:
                if r["id"] not in chosen:
                    picked.append(r)
                if len(picked) >= n:
                    break
        for r in picked:
            chosen[r["id"]] = {"stratum": name, "reason": reason.format(m=float(r["metric"] or 0), sub=r.get("sub") if "sub" in r else ""),
                               "metric": r["metric"], "platform_rank": r["prank"]}
        counts[name] = len(picked)
    procs = await conn.fetch("""SELECT id, ocid, contract_notice_no, title, buyer_nip, buyer_name, province, subsector_main,
                                       design_build, platform_url FROM procedure WHERE id = ANY($1::bigint[])""", list(chosen))
    out = Path(settings().ref_dir) / "doc_sample.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ocid", "contract_notice_no", "title", "buyer_nip", "buyer_name", "province", "subsector_main",
                    "design_build", "platform_url", "stratum", "reason", "metric", "platform_rank"])
        for p in sorted(procs, key=lambda p: (chosen[p["id"]]["stratum"], chosen[p["id"]]["platform_rank"])):
            c = chosen[p["id"]]
            w.writerow([p["ocid"], p["contract_notice_no"], p["title"], p["buyer_nip"], p["buyer_name"], p["province"],
                        p["subsector_main"], p["design_build"], p["platform_url"], c["stratum"], c["reason"], c["metric"],
                        c["platform_rank"]])
    return {"path": str(out), "procedures": len(chosen), "by_stratum": counts,
            "downloadable_platform_share": round(sum(1 for c in chosen.values() if c["platform_rank"] <= 3) / max(1, len(chosen)), 2)}
