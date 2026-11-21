import re, sys
sys.path.insert(0, __file__.rsplit('/',1)[0])
from html2text import html2text
CODE = re.compile(r'^\s*(\d+(?:\.\d+)*)\.?\)\s*(.*)$')
def fields(html):
    """Ordered list of (code, label, value) from a BZP notice htmlBody."""
    out=[]; cur=None
    for line in html2text(html).split('\n'):
        m=CODE.match(line)
        if m and not re.match(r'^\d{8}-\d', line.strip()):
            code, rest = m.group(1), m.group(2)
            if ':' in rest:
                lab, val = rest.split(':',1)
            else:
                lab, val = rest, ''
            cur=[code, lab.strip(), val.strip()]
            out.append(cur)
        elif cur is not None:
            cur[2]=(cur[2]+'\n'+line.strip()).strip()
    return [tuple(x) for x in out]
def first(fl, code):
    for c,l,v in fl:
        if c==code: return v
    return None
def all_(fl, code):
    return [v for c,l,v in fl if c==code]
def money(s):
    if not s: return None
    m=re.search(r'(-?[\d\s.]*\d(?:,\d{1,2})?)', s.replace('\xa0',' '))
    if not m: return None
    t=m.group(1).replace(' ','')
    if ',' in t: t=t.replace('.','').replace(',','.')
    try: return float(t)
    except ValueError: return None
