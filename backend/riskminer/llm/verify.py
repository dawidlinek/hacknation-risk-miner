"""Quote + number verifier (docs/impl/llm.md §3).

Every AI claim carries a verbatim quote. `verify_quote` finds it in the page text (exact → fuzzy → cross-page → table
cells → unverified) and returns character offsets into the ORIGINAL page text. `numbers_supported` checks that every
number the model claims is printed inside the verified quote (Polish number formats, unit multipliers), because models
invent totals.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Literal

from rapidfuzz import fuzz

Status = Literal["exact", "fuzzy", "unverified"]

QUOTES = dict.fromkeys(map(ord, "„”“«»‘’‚′″"), '"')
DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
BULLETS = set("•●▪◦■□")
MIN_FUZZY = 90.0
MIN_TOKENS_FUZZY = 4


def normalize_with_map(s: str) -> tuple[str, list[int]]:
    """Normalised text plus a back-map: normalised index -> original index."""
    out: list[str] = []
    back: list[int] = []
    prev_space = True
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "­":                      # soft hyphen
            i += 1
            continue
        if ch == "-" and i + 1 < n and s[i + 1] in "\r\n":   # line-break hyphenation: "-\n" + lowercase
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            if j < n and s[j].islower():
                i = j
                continue
        c = unicodedata.normalize("NFKC", ch).translate(QUOTES).translate(DASHES).lower()
        for cc in c:
            if cc.isspace() or cc in BULLETS:
                if not prev_space:
                    out.append(" ")
                    back.append(i)
                prev_space = True
            else:
                out.append(cc)
                back.append(i)
                prev_space = False
        i += 1
    if out and out[-1] == " ":
        out.pop()
        back.pop()
    return "".join(out), back


def normalize(s: str) -> str:
    return normalize_with_map(s or "")[0]


def _norm_quote(q: str) -> str:
    return normalize(q).strip(' ."\'').removesuffix("...").removesuffix("…").strip()


@dataclass
class QuoteCheck:
    status: Status
    page: int | None = None              # page where the quote was found (file page, 1-based)
    stated_page: int | None = None
    page_mismatch: bool = False
    score: float = 0.0
    char_start: int | None = None        # offsets into the original page text
    char_end: int | None = None
    reason: str | None = None            # cross_page | table | None
    pages: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("exact", "fuzzy")

    def as_dict(self) -> dict:
        return asdict(self)


def _span(back: list[int], i: int, j: int) -> tuple[int, int]:
    j = max(j, i + 1)
    return back[i], back[min(j, len(back)) - 1] + 1


def match_in_text(quote: str, text: str, min_score: float = MIN_FUZZY) -> QuoteCheck:
    """Exact, then fuzzy (partial_ratio_alignment ≥ min_score) inside one text. No page logic."""
    nq = _norm_quote(quote)
    if not nq:
        return QuoteCheck("unverified")
    nt, back = normalize_with_map(text or "")
    if not nt:
        return QuoteCheck("unverified")
    i = nt.find(nq)
    if i >= 0:
        a, b = _span(back, i, i + len(nq))
        return QuoteCheck("exact", score=100.0, char_start=a, char_end=b)
    if len(nq.split()) < MIN_TOKENS_FUZZY:
        return QuoteCheck("unverified")
    al = fuzz.partial_ratio_alignment(nq, nt)
    if al is not None and al.score >= min_score:
        a, b = _span(back, al.dest_start, al.dest_end)
        return QuoteCheck("fuzzy", score=round(al.score, 1), char_start=a, char_end=b)
    return QuoteCheck("unverified", score=round(al.score, 1) if al else 0.0)


TOK = re.compile(r"\w+", re.UNICODE)


def _table_coverage(quote: str, text: str) -> tuple[float, tuple[int, int] | None]:
    """Cells read out of order: share of quote tokens (multiset) inside the best window of ~1.6x the quote length."""
    nq = normalize(quote)
    qt = TOK.findall(nq)
    if len(qt) < MIN_TOKENS_FUZZY:
        return 0.0, None
    nt, back = normalize_with_map(text or "")
    toks = [(m.group(), m.start(), m.end()) for m in TOK.finditer(nt)]
    if not toks:
        return 0.0, None
    need = Counter(qt)
    w = max(len(qt), int(len(qt) * 1.6))
    best, best_span = 0.0, None
    step = max(1, len(qt) // 4)
    for s in range(0, max(1, len(toks) - w + 1), step):
        win = toks[s:s + w]
        have = Counter(t for t, _, _ in win)
        cov = sum(min(c, have[t]) for t, c in need.items()) / len(qt)
        if cov > best:
            best, best_span = cov, _span(back, win[0][1], win[-1][2])
            if best >= 0.999:
                break
    return best, best_span


def verify_quote(quote: str, pages: dict[int, str], stated_page: int | None = None,
                 min_score: float = MIN_FUZZY) -> QuoteCheck:
    """Find `quote` in `pages` ({page_no: text}). Order (first hit wins):
    1 exact on the stated page; 2 exact on another page (page corrected, page_mismatch); 3 fuzzy on stated, then other
    pages; 4 cross-page (tail of p-1 + head of p, p + head of p+1); 5 table cells on the stated page; 6 unverified."""
    if not quote or not pages:
        return QuoteCheck("unverified", stated_page=stated_page)
    order = ([stated_page] if stated_page in pages else []) + [p for p in sorted(pages) if p != stated_page]
    fuzzy_hits: list[tuple[int, QuoteCheck]] = []
    best_score = 0.0
    for p in order:
        r = match_in_text(quote, pages[p], min_score)
        best_score = max(best_score, r.score)
        if r.status == "exact":
            return QuoteCheck("exact", page=p, stated_page=stated_page, page_mismatch=(stated_page is not None and p != stated_page),
                              score=100.0, char_start=r.char_start, char_end=r.char_end, pages=[p])
        if r.status == "fuzzy":
            fuzzy_hits.append((p, r))
    if fuzzy_hits:
        p, r = next(((p, r) for p, r in fuzzy_hits if p == stated_page), max(fuzzy_hits, key=lambda x: x[1].score))
        return QuoteCheck("fuzzy", page=p, stated_page=stated_page, page_mismatch=(stated_page is not None and p != stated_page),
                          score=r.score, char_start=r.char_start, char_end=r.char_end, pages=[p])
    if stated_page is not None:
        for a, b in ((stated_page - 1, stated_page), (stated_page, stated_page + 1)):
            if a in pages and b in pages:
                tail = pages[a][-1500:]
                joined = tail + "\n" + pages[b][:1500]
                r = match_in_text(quote, joined, min_score)
                if r.ok:
                    # offsets are reported on the first page of the pair when the match starts there
                    start = r.char_start or 0
                    if start < len(tail):
                        cs = len(pages[a]) - len(tail) + start
                        return QuoteCheck("fuzzy", page=a, stated_page=stated_page, page_mismatch=a != stated_page,
                                          score=r.score, char_start=cs, char_end=len(pages[a]), reason="cross_page", pages=[a, b])
                    cs = start - len(tail) - 1
                    return QuoteCheck("fuzzy", page=b, stated_page=stated_page, page_mismatch=b != stated_page,
                                      score=r.score, char_start=max(cs, 0), char_end=(r.char_end or 0) - len(tail) - 1,
                                      reason="cross_page", pages=[a, b])
        if stated_page in pages:
            cov, span = _table_coverage(quote, pages[stated_page])
            if cov >= 0.9 and span:
                return QuoteCheck("fuzzy", page=stated_page, stated_page=stated_page, score=round(cov * 100, 1),
                                  char_start=span[0], char_end=span[1], reason="table", pages=[stated_page])
    return QuoteCheck("unverified", stated_page=stated_page, score=round(best_score, 1))


# ------------------------------------------------------------------------------------------------------------------
# Polish numbers
# ------------------------------------------------------------------------------------------------------------------
DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
NUM_RE = re.compile(r"(?<![\w,.])(\d{1,3}(?:[    .]\d{3})+(?:,\d+)?|\d+(?:[,.]\d+)?)(?![\d])")
UNIT_RE = re.compile(r"\s*(mld|mln|milion\w*|tys\.?|tysi\w*|mies\w*|km\b|mb\b|m\.b\.|m3|m³|m2|m²|m\b|zł|pln\b|%|dni\b|dzie\w*|lat\b|rok\w*|szt)",
                     re.IGNORECASE)
MULT = {"mld": 1e9, "mln": 1e6, "milion": 1e6, "tys": 1e3, "tysi": 1e3}


@dataclass
class NumTok:
    value: float           # with multiplier applied (7 mln → 7e6)
    raw: float             # as printed
    unit: str | None       # normalised unit: km, m, pln, pct, months, days, years, m3, m2, count, date
    text: str


def _to_float(t: str) -> float | None:
    t = re.sub(r"[    ]", "", t)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    elif re.fullmatch(r"\d+\.\d+", t) and len(t.split(".")[1]) == 3 and "," not in t:
        t = t.replace(".", "")       # 6.000 → 6000 (Polish thousands)
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _unit(u: str | None) -> tuple[str | None, float]:
    if not u:
        return None, 1.0
    u = u.lower().strip().rstrip(".")
    for k, m in MULT.items():
        if u.startswith(k):
            return "mult", m
    if u == "km":
        return "km", 1.0
    if u in ("mb", "m.b", "m"):
        return "m", 1.0
    if u in ("m3", "m³"):
        return "m3", 1.0
    if u in ("m2", "m²"):
        return "m2", 1.0
    if u in ("zł", "pln"):
        return "pln", 1.0
    if u == "%":
        return "pct", 1.0
    if u.startswith("mies"):
        return "months", 1.0
    if u.startswith(("dni", "dzie")):
        return "days", 1.0
    if u.startswith(("lat", "rok")):
        return "years", 1.0
    if u == "szt":
        return "count", 1.0
    return None, 1.0


def parse_numbers(s: str | None) -> list[NumTok]:
    """All numbers in a Polish text, with unit multipliers (mln, tys., mld) applied and units normalised."""
    if not s:
        return []
    out: list[NumTok] = []
    masked = s
    for m in DATE_RE.finditer(s):
        if m.group(3):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        out.append(NumTok(value=y * 10000 + mo * 100 + d, raw=y * 10000 + mo * 100 + d, unit="date", text=m.group()))
        masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    for m in NUM_RE.finditer(masked):
        v = _to_float(m.group(1))
        if v is None:
            continue
        um = UNIT_RE.match(masked, m.end())
        unit, mult = _unit(um.group(1) if um else None)
        if unit == "mult":
            rest = UNIT_RE.match(masked, um.end()) if um else None
            unit2, _ = _unit(rest.group(1) if rest else None)
            out.append(NumTok(value=v * mult, raw=v, unit=unit2 or "pln", text=m.group()))
        else:
            out.append(NumTok(value=v, raw=v, unit=unit, text=m.group()))
        # "1 234" may also be two numbers ("3 120" = 3 and 120): keep the parts as weaker candidates
        if re.search(r"[    ]", m.group(1)):
            for part in re.split(r"[    ]", m.group(1)):
                pv = _to_float(part)
                if pv is not None:
                    out.append(NumTok(value=pv, raw=pv, unit=None, text=part))
    return out


def _equivalents(v: float, unit: str | None) -> set[float]:
    eq = {v}
    if unit == "km":
        eq.add(v * 1000)
    if unit == "m":
        eq.add(v / 1000)
    return eq


def numbers_supported(claimed: list[float] | float | None, quote: str | None, *, unit: str | None = None,
                      money: bool = False) -> bool:
    """Every claimed number must equal (money: within 0.5%; otherwise exact to 1e-6) a number printed in the quote.
    Units: km ↔ m/mb converted; 'mln'/'tys.' multipliers applied on the quote side; the claim may also equal the raw
    printed figure (7 for '7 mln zł')."""
    if claimed is None:
        return True
    vals = [claimed] if isinstance(claimed, (int, float)) else list(claimed)
    if not vals:
        return True
    toks = parse_numbers(quote)
    cands: set[float] = set()
    for t in toks:
        cands |= _equivalents(t.value, t.unit) | _equivalents(t.raw, t.unit)
        if t.unit == "date":
            y, md = divmod(int(t.value), 10000)
            cands |= {float(y), float(md // 100), float(md % 100)}
    claim_eq: set[float] = set()
    for v in vals:
        claim_eq = _equivalents(float(v), unit) | {float(v)}
        if not any(_close(c, x, money) for c in claim_eq for x in cands):
            return False
    return True


def _close(a: float, b: float, money: bool) -> bool:
    if money:
        return abs(a - b) <= max(abs(a), abs(b)) * 0.005
    return abs(a - b) < 1e-6 or (abs(a) > 100 and abs(a - b) <= abs(a) * 1e-9)


def numbers_in_text(s: str | None) -> list[float]:
    """Plain list of values (multipliers applied), for chat answers and NL→SQL sentences."""
    return [t.value for t in parse_numbers(s) if t.unit != "date"]
