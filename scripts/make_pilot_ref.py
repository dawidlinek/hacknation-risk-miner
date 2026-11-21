"""Seed data/ref/pilot_projects.json (22 pilot projects) for the connectors, from the research linking
output + one streaming pass over the BZP copy (CN field 3.1 platform URL, contractor NIPs).
The pipeline regenerates the same file from the DB after `riskminer link-pilot`.
Run: cd backend && uv run python -I ../scripts/make_pilot_ref.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from riskminer.parsing.bzp_parse import parse_html, nip  # noqa: E402

chains = json.loads((ROOT / "research/bzp_linking/chains.json").read_text())
rows = {}
for line in (ROOT / "materials/text/05_dane_projekty.txt").read_text().splitlines():
    if line.startswith("Lp. |"):
        header = [h.strip() for h in line.split(" | ")]
    elif re.match(r"^\d+ \| RM-", line):
        v = [x.strip() for x in line.split(" | ")]
        v += [""] * (len(header) - len(v))
        rows[v[1]] = dict(zip(header, v))
tids = {c["tenderId"]: c["project_id"] for c in chains if c.get("tenderId")}
extra = {pid: {"platform_urls": [], "notice_object_ids": []} for pid in tids.values()}
src = ROOT / "materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl"
with src.open(encoding="utf-8") as fh:
    for line in fh:
        i = line.find('"tenderId": "')
        if i < 0:
            continue
        tid = line[i + 13 : line.find('"', i + 13)]
        if tid not in tids:
            continue
        rec = json.loads(line)
        pid = tids[tid]
        extra[pid]["notice_object_ids"].append(rec["objectId"])
        if rec["noticeType"] == "ContractNotice":
            pn = parse_html(rec.get("htmlBody", ""))
            for code in ("3.1", "3.5"):
                v = pn.first(code)
                if v:
                    for u in re.findall(r"https?://[^\s<>\"']+", v):
                        u = u.rstrip(".,;)")
                        if u not in extra[pid]["platform_urls"]:
                            extra[pid]["platform_urls"].append(u)
out = []
for c in chains:
    r = rows[c["project_id"]]
    contractors = []
    for k in c.get("contracts") or []:
        cid = re.sub(r"\D", "", k.get("contractor_id") or "")
        contractors.append({"name": k.get("contractor"), "id_raw": k.get("contractor_id"),
                            "nip": cid if len(cid) == 10 else None, "regon": cid if len(cid) in (9, 14) else None})
    out.append({
        "rm_id": c["project_id"], "lp": int(r["Lp."]), "buyer_nip": r["Identyfikator odbiorcy"],
        "buyer_name": r["Nazwa odbiorcy"], "buyer_city": r["Siedziba odbiorcy"],
        "woj_teryt": r["Kod województwa (TERYT)"].zfill(2), "woj": r["Województwo"],
        "title": r["Nazwa przedsięwzięcia"], "scope": r["Zakres rekordu"],
        "public_id_type": r["Rodzaj identyfikatora publicznego"], "public_id": r["Identyfikator publiczny"],
        "kpo_number": r["Identyfikator publiczny"] if r["Rodzaj identyfikatora publicznego"].startswith("Projekt KPO") else None,
        "annotation": r["Adnotacja instytucji"],
        "tender_id": c.get("tenderId"), "link_method": c.get("method"),
        "notices": [{"type": n["type"], "number": n["number"], "objectId": n["objectId"], "url": n["url"],
                     "date": n["date"]} for n in c.get("notices", [])],
        "contractors": contractors,
        "platform_urls": extra.get(c["project_id"], {}).get("platform_urls", []),
    })
p = ROOT / "data/ref/pilot_projects.json"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("wrote", p, len(out), "projects;", sum(bool(o["platform_urls"]) for o in out), "with platform URLs")
