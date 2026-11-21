"""Similar cases: weighted structured similarity + BM25 text part, with per-feature contributions (§3.4).

S = Σ_{i∈A} w_i s_i / Σ_{i∈A} w_i over features present on both sides; c_i = w_i s_i / Σ_A w (sums to S);
coverage = Σ_A w. Pool = every an_contract row; rows linked to the 22 pilot projects are tagged.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from riskminer.analytics.base import FAMILY, CaseBase
from riskminer.analytics.refclass import Features

DEFAULT_W = {"subsector_main": 0.20, "subsectors_all": 0.05, "works_type": 0.07, "formula": 0.08, "value": 0.12,
             "physical_size": 0.10, "tech_tags": 0.07, "period": 0.06, "funding": 0.04, "beneficiary_type": 0.03,
             "region": 0.05, "text": 0.13}

NEIGHBOURS = {"02": ["08", "16", "30"], "04": ["10", "14", "22", "28", "30"], "06": ["14", "18", "20", "26"],
              "08": ["02", "30", "32"], "10": ["04", "14", "16", "24", "26", "30"], "12": ["18", "24", "26"],
              "14": ["04", "06", "10", "20", "26", "28"], "16": ["02", "10", "24", "30"], "18": ["06", "12", "26"],
              "20": ["06", "14", "28"], "22": ["04", "28", "30", "32"], "24": ["10", "12", "16", "26"],
              "26": ["06", "10", "12", "14", "18", "24"], "28": ["04", "14", "20", "22"],
              "30": ["02", "04", "08", "10", "16", "22", "32"], "32": ["08", "22", "30"]}

# technical components (tags), matched in title + description
TAGS: list[tuple[str, str]] = [
    ("przepompownie", r"przepompowni|pompowni"),
    ("rurociąg tłoczny", r"tłoczn"),
    ("przyłącza", r"przyłącz|przykanalik|sięgacz"),
    ("kanalizacja grawitacyjna", r"grawitac"),
    ("kanalizacja ciśnieniowa", r"(?<!pod)ciśnieniow"),
    ("kanalizacja podciśnieniowa", r"podciśnieniow"),
    ("oczyszczalnia", r"oczyszczal"),
    ("stacja uzdatniania", r"uzdatnian|\bsuw\b"),
    ("hydranty", r"hydrant"),
    ("zbiornik", r"zbiornik"),
    ("odtworzenie nawierzchni", r"odtworzeni\w* nawierzch|nawierzchni"),
    ("przewierty", r"przewiert|przecisk|bezwykop"),
    ("kolektor", r"kolektor"),
    ("renowacja", r"renowac|rękaw"),
    ("studnie", r"studni"),
]
_TAG_RX = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in TAGS]

FEATURE_LABEL = {"subsector_main": "podsektor", "subsectors_all": "podsektory", "works_type": "rodzaj robót",
                 "formula": "formuła", "value": "wartość", "physical_size": "długość sieci",
                 "tech_tags": "elementy", "period": "okres", "funding": "finansowanie",
                 "beneficiary_type": "zamawiający", "region": "województwo", "text": "opis (tekst)"}
GROUP = {"subsector_main": "podsektor", "subsectors_all": "podsektor", "formula": "formula", "works_type": "zakres",
         "physical_size": "zakres", "tech_tags": "zakres", "value": "wartosc", "period": "wartosc", "text": "tekst",
         "funding": "inne", "beneficiary_type": "inne", "region": "inne"}
GROUP_LABEL = {"podsektor": "podsektor", "formula": "formuła", "zakres": "zakres i ilości", "wartosc": "wartość",
               "tekst": "opis (tekst)", "inne": "inne cechy"}


def _tag_rx_for(cb: CaseBase) -> list[tuple[str, re.Pattern]]:
    tags = cb.pack.get("tech_tags")
    return [(n, re.compile(p, re.I)) for n, p in tags] if tags else _TAG_RX


def tag_mask(text: str, rx_list: list[tuple[str, re.Pattern]] | None = None) -> int:
    m = 0
    for i, (_, rx) in enumerate(rx_list or _TAG_RX):
        if rx.search(text or ""):
            m |= 1 << i
    return m


def tag_names(mask: int, rx_list: list[tuple[str, re.Pattern]] | None = None) -> list[str]:
    names = [n for n, _ in (rx_list or _INDEX.get("tag_rx") or _TAG_RX)]
    return [names[i] for i in range(len(names)) if mask >> i & 1]


# --- BM25 ------------------------------------------------------------------------------------------------------------

STOP = {"gmina", "gminy", "gminie", "miejsc", "budowa", "budowy", "etap", "etapi", "częś", "czesc", "zadani", "ulica",
        "ulicy", "ul", "wraz", "oraz", "teren", "terenie", "zakres", "zamowi", "realiz", "wykona", "inwest", "projek",
        "dokume", "robot", "roboty", "przedm", "umowy", "umowa", "dla", "przy", "nad", "pod", "the", "nr", "km",
        "mb", "sieci", "siec", "miasta", "miasto", "obreb", "powiat", "woj", "msc"}


def fold(s: str) -> str:
    s = s.lower().replace("ł", "l")
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def tokens(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-ząćęłńóśźż]{3,}", (s or "").lower()):
        t = fold(w)[:6]
        if t not in STOP:
            out.append(t)
    return out


@dataclass
class BM25:
    postings: dict[str, tuple[np.ndarray, np.ndarray]]
    idf: dict[str, float]
    dl: np.ndarray
    avgdl: float
    k1: float = 1.2
    b: float = 0.75

    @classmethod
    def build(cls, docs: list[str]) -> BM25:
        post: dict[str, tuple[list[int], list[int]]] = {}
        dl = np.zeros(len(docs))
        for i, d in enumerate(docs):
            toks = tokens(d)
            dl[i] = len(toks)
            for t, c in Counter(toks).items():
                p = post.setdefault(t, ([], []))
                p[0].append(i)
                p[1].append(c)
        n = len(docs)
        idf = {t: math.log(1 + (n - len(p[0]) + 0.5) / (len(p[0]) + 0.5)) for t, p in post.items()}
        postings = {t: (np.array(p[0]), np.array(p[1], dtype=float)) for t, p in post.items()}
        return cls(postings=postings, idf=idf, dl=dl, avgdl=float(dl.mean()) if n else 1.0)

    def score(self, query: str) -> tuple[np.ndarray, list[str]]:
        s = np.zeros(self.dl.size)
        qt = [t for t in dict.fromkeys(tokens(query)) if t in self.postings]
        norm = self.k1 * (1 - self.b + self.b * self.dl / self.avgdl)
        for t in qt:
            ids, tf = self.postings[t]
            s[ids] += self.idf[t] * tf * (self.k1 + 1) / (tf + norm[ids])
        return s, qt


_INDEX: dict[str, Any] = {}


_INDEXES: dict[str, dict[str, Any]] = {}       # one index per case base (sector + load), kept across requests


def _prep(cb: CaseBase, activate: bool = True) -> dict[str, Any]:
    """Index of `cb` (built once per case base). `activate=False` builds it without making it the current one, for
    background threads (the request path reads the current index through is_pilot/rm_id/case_tags)."""
    global _INDEX
    hit = _INDEXES.get(cb.data_version)
    if hit is not None:
        if activate:
            _INDEX = hit
        return hit
    ix = _build_index(cb)
    for k in [k for k in _INDEXES if k.split("@")[0] == cb.data_version.split("@")[0]]:
        _INDEXES.pop(k)                         # older load of the same sector
    _INDEXES[cb.data_version] = ix
    if activate:
        _INDEX = ix
    return ix


def _build_index(cb: CaseBase) -> dict[str, Any]:
    _INDEX: dict[str, Any] = {}                 # local on purpose: published only when complete
    texts = [f"{t or ''} {(d or '')[:600]}" for t, d in zip(cb["title"], cb["cp_description"], strict=True)]
    _INDEX["version"] = cb.data_version
    _INDEX["bm25"] = BM25.build(texts)
    _INDEX["tag_rx"] = _tag_rx_for(cb)
    _INDEX["tags"] = np.array([tag_mask(f"{t or ''} {d or ''}", _INDEX["tag_rx"])
                               for t, d in zip(cb["title"], cb["cp_description"], strict=True)], dtype=np.uint32)
    years = np.array([d.astype("datetime64[Y]").astype(int) + 1970 if not np.isnat(d) else -1
                      for d in cb["signed_on"]], dtype=float)
    _INDEX["year"] = np.where(years > 0, years, np.nan)
    pil = np.zeros(cb.n, dtype=bool)
    rm = np.empty(cb.n, dtype=object)
    fund = np.empty(cb.n, dtype=object)
    for i, pid in enumerate(cb["procedure_id"]):
        p = cb.pilots.get(int(pid))
        if p:
            pil[i] = True
            rm[i] = p[0]["rm_id"]
            fund[i] = p[0].get("funding_programme")
    _INDEX["pilot"], _INDEX["rm_id"], _INDEX["funding"] = pil, rm, fund
    return _INDEX


def _regime(y: float) -> int:
    return 0 if y <= 2021 else (1 if y <= 2023 else 2)


def _family_of_programme(code: str | None) -> str | None:
    if not code:
        return None
    c = code.upper()
    if any(k in c for k in ("KPO", "FENIKS", "FEP", "RPO", "POIIS", "PROW", "UE", "EU")):
        return "EU"
    if any(k in c for k in ("RFIL", "PIS", "ŁAD", "LAD", "RZĄD")):
        return "national"
    if "OWN" in c or "WŁAS" in c:
        return "own"
    return None


def log_gauss(a: np.ndarray, b: float, sigma: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.exp(-np.log(a / b) ** 2 / (2 * sigma ** 2))


@dataclass
class Scored:
    S: np.ndarray
    coverage: np.ndarray
    s: dict[str, np.ndarray]                 # per-feature s_i (nan = absent)
    w: dict[str, float]
    matched_terms: list[str] = field(default_factory=list)
    user_tags: int = 0


def score_pool(cb: CaseBase, ft: Features, weights: dict | None = None) -> Scored:
    ix = _prep(cb)
    W = dict(DEFAULT_W)
    for k, v in (weights or {}).items():
        if isinstance(v, dict) and "w" in v:
            W[k] = float(v["w"])
    s: dict[str, np.ndarray] = {}
    n = cb.n
    nan = np.full(n, np.nan)
    sub = cb["subsector_main"]
    if ft.subsector_main:
        u = ft.subsector_main
        x = np.where(sub == u, 1.0, 0.0)
        sec = np.array([u in (ss or []) for ss in cb["subsectors"]], dtype=bool) | (np.isin(sub, ft.subsectors or []))
        x = np.where((x == 0) & sec, 0.6, x)
        fu = FAMILY.get(u)
        fam = np.array([fu is not None and FAMILY.get(v) == fu for v in sub], dtype=bool)
        x = np.where((x == 0) & fam, 0.3, x)
        s["subsector_main"] = x
        us = set(ft.subsectors or []) | {u}
        s["subsectors_all"] = np.array([len(us & (set(ss or []) | {m})) / len(us | (set(ss or []) | {m}))
                                        for ss, m in zip(cb["subsectors"], sub, strict=True)])
    else:
        s["subsector_main"] = s["subsectors_all"] = nan
    wt = cb["work_type"]
    if ft.work_type in ("build", "renovation", "mixed"):
        x = np.where(wt == ft.work_type, 1.0, np.where((wt == "mixed") | (ft.work_type == "mixed"), 0.5, 0.0))
        s["works_type"] = np.where(np.isin(wt, ["build", "renovation", "mixed"]), x, np.nan)
    else:
        s["works_type"] = nan
    db = cb["design_build"]
    s["formula"] = np.where(db >= 0, (db == int(bool(ft.design_build))).astype(float), np.nan) \
        if ft.design_build is not None else nan
    s["value"] = log_gauss(cb["value_gross"], ft.value_gross, 0.693) if ft.value_gross else nan
    s["physical_size"] = log_gauss(cb["length_km"], ft.length_km, 0.693) if ft.length_km else nan
    tags = ix["tags"]
    ut = tag_mask(ft.text or "", ix["tag_rx"])
    if ft.length_km and ft.pumping_stations:
        ut |= 1 << 0
    if ut:
        inter = np.bitwise_count(tags & np.uint32(ut)).astype(float)
        union = np.bitwise_count(tags | np.uint32(ut)).astype(float)
        s["tech_tags"] = np.where(tags > 0, inter / np.maximum(union, 1), np.nan)
    else:
        s["tech_tags"] = nan
    yr = ft.planned_year
    if yr:
        y = ix["year"]
        x = np.exp(-np.abs(y - yr) / 3.0)
        reg = np.array([_regime(v) if np.isfinite(v) else -1 for v in y])
        s["period"] = np.where(reg == _regime(yr), x, x * 0.7)
    else:
        s["period"] = nan
    uf = _family_of_programme(ft.funding_programme)
    if uf:
        eu = cb["eu_funded"]
        cand = np.where(eu == 1, "EU", np.where(eu == 0, "other", None))
        pf = np.array([_family_of_programme(f) for f in ix["funding"]], dtype=object)
        cand = np.where(pf != None, pf, cand)
        s["funding"] = np.array([np.nan if c is None else (1.0 if c == uf else 0.0) for c in cand])
    else:
        s["funding"] = nan
    s["beneficiary_type"] = nan
    if ft.woj:
        woj = cb["woj"]
        nb = NEIGHBOURS.get(ft.woj, [])
        s["region"] = np.where(woj == ft.woj, 1.0, np.where(np.isin(woj, nb), 0.5, 0.2))
    else:
        s["region"] = nan
    terms: list[str] = []
    if ft.text and len(ft.text) >= 10:
        raw, terms = ix["bm25"].score(ft.text)
        if raw.max() > 0:
            c0, c1 = np.median(raw), np.percentile(raw, 99)
            s["text"] = np.clip((raw - c0) / max(c1 - c0, 1e-9), 0, 1)
        else:
            s["text"] = nan
    else:
        s["text"] = nan
    num = np.zeros(n)
    den = np.zeros(n)
    for k, arr in s.items():
        w = W.get(k, 0.0)
        pres = np.isfinite(arr)
        num += np.where(pres, w * np.nan_to_num(arr), 0)
        den += np.where(pres, w, 0)
    S = np.where(den > 0, num / np.maximum(den, 1e-12), 0.0)
    return Scored(S=S, coverage=den, s=s, w=W, matched_terms=terms, user_tags=ut)


def contributions(sc: Scored, i: int) -> list[dict[str, Any]]:
    den = sum(sc.w[k] for k, a in sc.s.items() if np.isfinite(a[i]))
    out = []
    for k, a in sc.s.items():
        if np.isfinite(a[i]) and den > 0:
            out.append({"feature": k, "label": FEATURE_LABEL[k], "s": float(a[i]), "w": sc.w[k] / den,
                        "c": sc.w[k] * float(a[i]) / den, "gap": sc.w[k] * (1 - float(a[i])) / den})
    return out


def grouped(contribs: list[dict]) -> list[dict[str, Any]]:
    g: dict[str, float] = {}
    for c in contribs:
        key = GROUP[c["feature"]]
        g[key] = g.get(key, 0.0) + c["c"]
    order = ["podsektor", "formula", "zakres", "wartosc", "tekst", "inne"]
    return [{"feature": k, "label": GROUP_LABEL[k], "value": round(g[k], 4)} for k in order if k in g]


def top(cb: CaseBase, sc: Scored, k: int = 30, min_s: float = 0.0, min_cov: float = 0.5,
        max_per_buyer_top10: int = 2) -> list[int]:
    ok = (sc.coverage >= min_cov) & (sc.S >= min_s)
    idx = np.flatnonzero(ok)
    idx = idx[np.argsort(-sc.S[idx], kind="mergesort")]
    out: list[int] = []
    per_buyer: dict[str, int] = {}
    for i in idx:
        b = cb["buyer_nip"][i] or f"#{i}"
        if len(out) < 10 and per_buyer.get(b, 0) >= max_per_buyer_top10:
            continue
        per_buyer[b] = per_buyer.get(b, 0) + 1
        out.append(int(i))
        if len(out) >= k:
            break
    return out


def is_pilot(i: int) -> bool:
    return bool(_INDEX.get("pilot") is not None and _INDEX["pilot"][i])


def rm_id(i: int) -> str | None:
    return _INDEX["rm_id"][i] if _INDEX.get("rm_id") is not None else None


def case_tags(i: int) -> list[str]:
    return tag_names(int(_INDEX["tags"][i]), _INDEX.get("tag_rx")) if _INDEX.get("tags") is not None else []
