"""Render chains.json into a Markdown matrix (one row per contract/part)."""
import json, datetime as dt, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
R = json.load(open(HERE / 'chains.json'))
ds = {}
for line in open('/home/dawid-home-pc/Desktop/hacknation-risk-miner/materials/text/05_dane_projekty.txt', encoding='utf-8'):
    if ' | RM-' in line:
        v = [x.strip() for x in line.split(' | ')]
        ds[v[1]] = v
def d(s):
    if not s: return None
    s = s.lstrip('~')[:10]
    try: return dt.date.fromisoformat(s)
    except ValueError: return None
def fm(x):
    return f"{x:,.0f}".replace(',', ' ') if isinstance(x, (int, float)) else '–'
rows = []
hdr = "| # | Dataset key | Method | CN | TRN | Part | Contractor (ID) | Contract PLN | Planned end | Actual end | Delay d | Changes (AUN/CPN) | Paid PLN | Δ cost | Done properly |"
print(hdr); print("|" + "---|" * hdr.count('|')[:-1] if False else "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in R:
    v = ds[r['project_id']]
    s = r.get('summary') or {}
    key = ('BZP ' if v[12].startswith('Ogł') else 'KPO ') + v[13] + (f" ({v[11]})" if v[11] != 'całe postępowanie' else '')
    meth = {'bzp-number': 'number', 'name+NIP+CPV+date': f"search ({r.get('confidence')})",
            'bzp-number via references in follow-up notices': 'refs in CPN/AUN'}.get(r.get('method'), r.get('method'))
    for c in r['contracts'] or [{}]:
        pe, ae = d(c.get('planned_end')), d(c.get('actual_end'))
        delay = (ae - pe).days if pe and ae else None
        cv, paid = c.get('contract_value'), c.get('paid_total')
        dc = f"{(paid - cv) / cv * 100:+.1f}%" if cv and paid else '–'
        approx = '~' if (c.get('planned_end') or '').startswith('~') else ''
        print(f"| {r['lp']} | {key} | {meth} | {s.get('cn') or '**missing**'} | {', '.join(s.get('trn') or []) or '**missing**'} | {c.get('part')} | "
              f"{(c.get("contractor") or "–").replace(chr(10)," ")[:38].strip(" ,")} ({c.get('contractor_id') or '–'}) | {fm(cv)} | {c.get('planned_end') or '–'} | "
              f"{c.get('actual_end') or '–'} | {approx}{delay if delay is not None else '–'} | {c.get('aun', 0)}/{c.get('changes_count') or 0} | "
              f"{fm(paid)} | {dc} | {c.get('properly') or '–'} |")
