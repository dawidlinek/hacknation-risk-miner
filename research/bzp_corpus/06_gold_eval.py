"""06_gold_eval.py - merge hand labels with the sample, frequency per category, keyword pre-classifier
precision/recall vs gold. Outputs data/gold_change_reasons.csv, out/gold_category_freq.csv, out/keyword_vs_gold.csv"""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import change_keywords as ck
from gold_labels import LABELS
s = pd.read_csv(os.path.join(HERE, "data/change_reasons_sample.csv"))
s["primary"] = [LABELS[i + 1][0] for i in range(len(s))]
s["secondary"] = [LABELS[i + 1][1] for i in range(len(s))]
s["kw_categories"] = [" ".join(ck.keyword_categories(r, d)) for r, d in zip(s.reason, s.description)]
s.to_csv(os.path.join(HERE, "data/gold_change_reasons.csv"), index=False)
cats = sorted(set(s.primary) | set(x for x in s.secondary if x))
rows = []
for c in cats:
    prim = s.primary == c
    anyl = prim | (s.secondary == c)
    rows.append({"category": c, "name": ck.CATEGORY_NAMES.get(c, "Brak faktycznej przyczyny (formuła ogólna / tylko skutek)" if c == "N-UNSPEC" else c),
                 "n_primary": int(prim.sum()), "pct_primary": round(100 * prim.mean(), 1),
                 "n_any": int(anyl.sum()), "pct_any": round(100 * anyl.mean(), 1),
                 "AU_primary": int((prim & (s.source == "AU")).sum()), "CP_primary": int((prim & (s.source == "CP")).sum())})
f = pd.DataFrame(rows).sort_values("n_primary", ascending=False)
f.to_csv(os.path.join(HERE, "out/gold_category_freq.csv"), index=False)
print(f.to_string())
# keyword vs gold (any-label)
ev = []
for c in ck.PATTERNS:
    gold = (s.primary == c) | (s.secondary == c)
    pred = s.kw_categories.str.split().apply(lambda l: c in l)
    tp = int((gold & pred).sum()); fp = int((~gold & pred).sum()); fn = int((gold & ~pred).sum())
    ev.append({"category": c, "gold_any": int(gold.sum()), "kw_pred": int(pred.sum()), "tp": tp, "fp": fp, "fn": fn,
               "precision": round(tp / (tp + fp), 2) if tp + fp else None, "recall": round(tp / (tp + fn), 2) if tp + fn else None})
e = pd.DataFrame(ev)
e.to_csv(os.path.join(HERE, "out/keyword_vs_gold.csv"), index=False)
print(e.to_string())
print("texts with no kw category:", (s.kw_categories == "").mean().round(3), " gold N-UNSPEC primary:", (s.primary == "N-UNSPEC").mean().round(3))
print(pd.crosstab(s.primary, s.basis))
