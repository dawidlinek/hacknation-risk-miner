"""Build the seed sector pack catalogue/wod-kan/*.yaml from docs/research/03_domain_methodology.md
(YAML blocks + markdown tables), the expert checklist (materials/text/04_poradnik...), and the classifier constants.
Run once: cd backend && uv run python -I ../scripts/build_catalogue_pack.py   (output is committed data, editable by experts)"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from riskminer.parsing import wodkan_classify as wc  # noqa: E402

OUT = ROOT / "catalogue" / "wod-kan"
OUT.mkdir(parents=True, exist_ok=True)
md = (ROOT / "docs/research/03_domain_methodology.md").read_text(encoding="utf-8")
blocks = re.findall(r"```yaml\n(.*?)```", md, re.S)
risk = yaml.safe_load(blocks[0])
sim = yaml.safe_load(blocks[1])
lex = yaml.safe_load(blocks[2])
STATUS = {"approved_by_organizer": "approved", "proposed": "proposed"}
for r in risk["risks"]:
    r["status"] = STATUS.get(r.get("status"), "proposed")
    if r["id"] in ("R16", "R17", "R18"):
        r["status"] = "proposed"          # new L1 categories: need expert approval (demo of catalogue proposals)
        r.setdefault("proposed_by", "analiza korpusu BZP + literatura (03_domain_methodology §2.4)")
hdr = "# Sector pack wod-kan: edit in the panel or here; loaded by `riskminer seed-catalogue`.\n# Source: docs/research/03_domain_methodology.md (+ expert materials). status: approved | proposed.\n"


def _nodash(x):
    """House style: no em dashes, middle dots or dash separators in copy (use commas/colons)."""
    if isinstance(x, str):
        x = x.replace(" — ", ", ").replace(" – ", ", ").replace(" · ", ", ").replace("·", ",")
        return "brak" if x.strip() in ("—", "–") else x.replace("—", "-")
    if isinstance(x, list):
        return [_nodash(v) for v in x]
    if isinstance(x, dict):
        return {k: _nodash(v) for k, v in x.items()}
    return x


def dump(name, obj):
    (OUT / name).write_text(hdr + yaml.safe_dump(_nodash(obj), allow_unicode=True, sort_keys=False, width=140),
                            encoding="utf-8")


dump("risks.yaml", risk)
dump("similarity.yaml", sim)
dump("lexicon.yaml", lex)


def md_table(after_heading: str) -> list[dict]:
    i = md.index(after_heading)
    lines = md[i:].split("\n")
    rows, header = [], None
    for ln in lines[1:]:
        if ln.startswith("|"):
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if header is None:
                header = cells
            elif set(ln.replace("|", "").strip()) <= set("-: "):
                continue
            else:
                rows.append(dict(zip(header, cells)))
        elif header is not None and rows:
            break
    return rows


events = [{"code": r["Code"], "name": r["Event (PL label)"], "rule": r["Detection rule"], "fields": r["Source field(s)"],
           "status": "approved"} for r in md_table("### 2.2 Event vocabulary")]
dump("event_types.yaml", {"event_types": events})
flags = [{"code": r["#"], "text": r["Flag (UI text, PL)"].strip("„”"), "trigger": r["Trigger"],
          "risk_codes": [c.strip() for c in r["Code"].split(",")], "status": "approved"}
         for r in md_table("### 2.6 Red flags")]
dump("red_flags.yaml", {"red_flags": flags})
states = [{"code": r["State (enum)"].replace("Ś", "S"), "label": r["PL label"], "definition": r["Definition"],
           "effect_on_risk": r["Effect on risk"], "effect_on_completeness": r["Effect on completeness C"]}
          for r in md_table("### 6.1 Evidence states")]
dump("evidence_states.yaml", {"evidence_states": states, "document_fetch_states": [
    {"code": "found", "label": "pobrano"}, {"code": "not_in_package", "label": "brak w paczce (platforma dostępna)"},
    {"code": "blocked", "label": "zablokowane (zabezpieczenie platformy)"}, {"code": "link_dead", "label": "link nieaktywny"},
    {"code": "not_applicable", "label": "nie dotyczy"}]})
subs = [{"code": k, "name": v, "status": "approved"} for k, v in wc.SUBSECTOR_NAMES.items()]
dump("subsectors.yaml", {"subsectors": subs, "works_types": [
    {"code": "build", "name": "budowa / rozbudowa"}, {"code": "renovation", "name": "przebudowa / renowacja"},
    {"code": "mixed", "name": "mieszany"}], "delivery_models": [
    {"code": "build", "name": "buduj (projekt zamawiającego)"}, {"code": "design_build", "name": "zaprojektuj i wybuduj"}]})
cpv_labels = {}
for r in md_table("### 7.2 CPV codes"):
    for code in re.findall(r"\d{8}", " ".join(r.values())):
        cpv_labels.setdefault(code, " | ".join(v for v in list(r.values())[1:] if v)[:200])
cpv = [{"cpv": c, "subsector": wc._CPV_SUB.get(c), "strength": "strong", "label": cpv_labels.get(c), "status": "approved"}
       for c in sorted(wc._STRONG_CPV)]
for c, lab in cpv_labels.items():
    if c not in wc._STRONG_CPV:
        cpv.append({"cpv": c, "subsector": None, "strength": "weak", "label": lab, "status": "approved"})
dump("cpv_map.yaml", {"cpv_map": cpv})
docs = [
    ("ogloszenie_zamowienie", "Ogłoszenie o zamówieniu", "postepowanie"), ("swz", "SWZ", "postepowanie"),
    ("pfu", "Program funkcjonalno-użytkowy (PFU)", "przygotowanie"), ("opz", "Opis przedmiotu zamówienia (OPZ)", "postepowanie"),
    ("ppu", "Projektowane postanowienia umowy / wzór umowy", "postepowanie"), ("projekt", "Dokumentacja projektowa", "przygotowanie"),
    ("stwiorb", "STWiORB", "przygotowanie"), ("przedmiar", "Przedmiar robót", "przygotowanie"), ("kosztorys", "Kosztorys inwestorski", "przygotowanie"),
    ("geotech", "Badania / opinia geotechniczna", "przygotowanie"), ("qa", "Wyjaśnienia treści SWZ (pytania i odpowiedzi)", "postepowanie"),
    ("modyfikacja", "Modyfikacja SWZ / zmiana ogłoszenia", "postepowanie"), ("kwota", "Informacja o kwocie (art. 222 ust. 4)", "postepowanie"),
    ("otwarcie", "Informacja z otwarcia ofert", "postepowanie"), ("wybor", "Informacja o wyborze najkorzystniejszej oferty", "postepowanie"),
    ("uniewaznienie", "Unieważnienie postępowania", "postepowanie"), ("ogloszenie_wynik", "Ogłoszenie o wyniku postępowania", "postepowanie"),
    ("umowa", "Umowa (podpisana)", "realizacja"), ("aneks", "Aneks do umowy", "realizacja"),
    ("ogloszenie_zmiana", "Ogłoszenie o zmianie umowy", "realizacja"), ("ogloszenie_wykonanie", "Ogłoszenie o wykonaniu umowy", "odbior"),
    ("dsu", "Decyzja o środowiskowych uwarunkowaniach", "przygotowanie"), ("wodnoprawne", "Pozwolenie / zgłoszenie wodnoprawne", "przygotowanie"),
    ("kio", "Orzeczenie KIO", "postepowanie"), ("nik_informacja", "NIK: informacja o wynikach kontroli", "ewaluacja"),
    ("nik_wystapienie", "NIK: wystąpienie pokontrolne", "ewaluacja"), ("wpf", "WPF / uchwała budżetowa", "przygotowanie"),
    ("inne", "Inne", None)]
dump("doc_types.yaml", {"doc_types": [{"code": c, "name": n, "phase": p, "status": "approved"} for c, n, p in docs]})
poradnik = (ROOT / "materials/text/04_poradnik_inwestycja_wodociagowa.txt").read_text(encoding="utf-8").splitlines()
i = next(k for k, ln in enumerate(poradnik) if ln.startswith("8. Zbiorcza checklista"))
items = [ln.strip() for ln in poradnik[i + 2:i + 11] if ln.strip()]
dump("checklist.yaml", {"checklists": [{"code": "WOD-PREP", "name": "Zbiorcza checklista przygotowania inwestycji wodociągowej",
                                        "source": "Risk_Miner_material_ekspercki_przygotowanie_inw_wodociagowej.docx §8",
                                        "items": [{"code": f"WOD-PREP-{n}", "text": re.sub(r"\s*\([\d.,–;\s]+\)\s*$", "", t),
                                                   "refs": (re.search(r"\(([\d.,–;\s]+)\)\s*$", t) or [None, None])[1],
                                                   "status": "approved"} for n, t in enumerate(items, 1)]}]})
clauses = []
for r in risk["risks"]:
    for n, c in enumerate(r.get("clauses") or [], 1):
        clauses.append({"code": f"{r['id']}-K{n}", "risk_code": r["id"], "text": c,
                        "status": "proposed" if r["status"] == "proposed" else "approved"})
dump("clauses.yaml", {"clauses": clauses})
dump("pack.yaml", {"sector": "wod-kan", "name": "Gospodarka wodno-ściekowa (wod-kan)", "schema_version": 1, "files": sorted(
    p.name for p in OUT.glob("*.yaml") if p.name != "pack.yaml")})
print({p.name: p.stat().st_size for p in OUT.glob("*.yaml")}, len(risk["risks"]), "risks", len(clauses), "clauses", len(items), "checklist")
