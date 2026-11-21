"""
01_field_inventory.py - field catalogue per notice type and year.

For every notice: parse htmlBody, record which field codes appear (with label) and whether
the value is filled. Output:
  out/field_catalogue.csv   type, code, label (most common), label_variants, n_notices_with_code,
                            fill_rate overall and per publication year (2021..2026)
  out/sections.csv          type, section title, count
Run: python3 -I 01_field_inventory.py [path/to/notices.jsonl]
"""
from __future__ import annotations

import collections
import csv
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bzp_parse as bp  # noqa: E402

DEFAULT = os.path.join(os.path.dirname(__file__), "../../materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl")
OUT = os.path.join(os.path.dirname(__file__), "out")
YEARS = ["2021", "2022", "2023", "2024", "2025", "2026"]


def work(line: str):
    rec = json.loads(line)
    pn = bp.parse_html(rec.get("htmlBody", ""))
    t = rec["noticeType"]
    y = rec["publicationDate"][:4]
    present = {}
    for e in pn.entries:
        key = e.code if e.code else ("<" + ("Część N" if bp._PART_RE.match(e.label) else "Kryterium N" if bp._CRIT_RE.match(e.label) else e.label[:60]) + ">")
        filled = bool(e.value.strip())
        if key not in present:
            present[key] = [e.label[:160], filled]
        else:
            present[key][1] = present[key][1] or filled
    return t, y, present, list(pn.section_texts.keys()), [e.section for e in pn.entries[:1]], pn.template_version


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    os.makedirs(OUT, exist_ok=True)
    n_type_year = collections.Counter()
    code_count = collections.Counter()      # (t, code) -> notices with code
    code_fill = collections.Counter()       # (t, code) -> filled
    code_year = collections.Counter()       # (t, code, y) -> notices with code
    code_year_fill = collections.Counter()
    labels = collections.defaultdict(collections.Counter)
    sect = collections.Counter()
    with open(path, encoding="utf-8") as fh, Pool(max(1, os.cpu_count() - 2)) as pool:
        for t, y, present, stexts, _, _ in pool.imap_unordered(work, fh, chunksize=64):
            n_type_year[(t, y)] += 1
            for code, (label, filled) in present.items():
                code_count[(t, code)] += 1
                code_year[(t, code, y)] += 1
                if filled:
                    code_fill[(t, code)] += 1
                    code_year_fill[(t, code, y)] += 1
                labels[(t, code)][label] += 1
            for s in stexts:
                sect[(t, s)] += 1

    def sort_key(k):
        t, code = k
        if code.startswith("<"):
            return (t, [999], code)
        return (t, [int(x) for x in code.split(".")], code)

    with open(os.path.join(OUT, "field_catalogue.csv"), "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["noticeType", "code", "label", "n_label_variants", "label_variants_top3", "n_with_code", "pct_of_type",
                    "pct_filled_when_present"] + [f"pct_present_{y}" for y in YEARS])
        for k in sorted(code_count, key=sort_key):
            t, code = k
            n_t = sum(v for (tt, _), v in n_type_year.items() if tt == t)
            lab = labels[k].most_common(1)[0][0]
            variants = labels[k].most_common(3)
            row = [t, code, lab, len(labels[k]), " || ".join(f"{l} ({c})" for l, c in variants[1:]),
                   code_count[k], round(100 * code_count[k] / n_t, 2), round(100 * code_fill[k] / code_count[k], 2)]
            for y in YEARS:
                ny = n_type_year[(t, y)]
                row.append(round(100 * code_year[(t, code, y)] / ny, 2) if ny else "")
            w.writerow(row)
    with open(os.path.join(OUT, "sections_free_text.csv"), "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["noticeType", "section", "n"])
        for (t, s), c in sect.most_common():
            w.writerow([t, s, c])
    with open(os.path.join(OUT, "notices_by_type_year.csv"), "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["noticeType"] + YEARS + ["total"])
        for t in sorted({t for t, _ in n_type_year}):
            row = [n_type_year[(t, y)] for y in YEARS]
            w.writerow([t] + row + [sum(row)])
    print("done", sum(n_type_year.values()))


if __name__ == "__main__":
    main()
