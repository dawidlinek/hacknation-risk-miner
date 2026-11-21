"""08_causes_by_year.py - keyword-based change-cause shares by contract year (wod-kan core; AU + CP-embedded
changes, one vote per change). Output out/wow_change_causes_by_year.csv. Rough (keyword precision see keyword_vs_gold.csv)."""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import change_keywords as ck
D = os.path.join(HERE, "data")
c = pd.read_csv(os.path.join(D, "contracts_reference.csv.gz"), low_memory=False, usecols=["objectId", "relevance", "scope", "contract_year"])
c = c[c.relevance.isin(["core", "cpv_only"]) & (c.scope == "works")]
pc = pd.read_csv(os.path.join(D, "perf_changes.csv.gz"), low_memory=False).merge(c, on="objectId")
pc["kw"] = [ck.keyword_categories(r, d) for r, d in zip(pc.reason, pc.description)]
rows = []
for y, g in pc.groupby("contract_year"):
    ex = g.kw.explode().dropna().value_counts()
    rows.append({"contract_year": y, "n_changes": len(g), **{k: round(100 * ex.get(k, 0) / len(g), 1) for k in ck.CATEGORY_NAMES if ex.get(k, 0) or k in ex}})
t = pd.DataFrame(rows).fillna(0)
t.to_csv(os.path.join(HERE, "out/wow_change_causes_by_year.csv"), index=False)
print(t.to_string())
# evidence search for rarely seen catalogue items
au = pd.read_csv(os.path.join(D, "changes.csv.gz"), low_memory=False, usecols=["noticeNumber", "reason"])
allr = pd.concat([pc[["noticeNumber", "reason"]], au]).dropna()
for name, pat in {"R15": r"nie\s+(?:osiągnięto|uzyskano)\s+(?:wymaganych\s+)?(?:parametr|efekt)|parametr\w*\s+ścieków\s+oczyszczonych|efekt\w*\s+ekologiczn",
                  "R05": r"spor\w*\s+(?:co\s+do|dotycząc)|odpowiedzialnoś\w*\s+(?:za\s+wykonanie|stron)|nie\s+należał\w*\s+do\s+zakresu\s+wykonawcy",
                  "R14": r"koszt\w*\s+eksploatac|energooszczędn|obniżeni\w*\s+koszt\w*\s+(?:eksploat|utrzym)",
                  "R11": r"związani\w*\s+ofertą|odwołani\w*\s+(?:do\s+)?(?:kio|krajowej)"}.items():
    m = allr[allr.reason.str.contains(pat, case=False, regex=True)]
    print(name, len(m))
    for t_ in m.reason.head(3): print("   ", t_[:230].replace("\n", " "))
