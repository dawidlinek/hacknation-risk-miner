"""Reference class: funnel and progressive widening (analytics.md §3.1)."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from riskminer.analytics.base import BUCKET_LABEL, BUCKETS, FAMILY, SUB_LABEL, WORK_LABEL, CaseBase, acfg, bucket_of


@dataclass
class Features:
    """Analysis inputs (chips). Money is gross PLN; plan in days."""
    subsector_main: str | None = None
    subsectors: list[str] = field(default_factory=list)
    value_gross: float | None = None          # budget, gross
    design_build: bool | None = None
    work_type: str | None = None              # build | renovation | mixed
    plan_days: float | None = None
    length_km: float | None = None
    pumping_stations: int | None = None
    connections: int | None = None
    funding_programme: str | None = None
    deadline: str | None = None               # ISO date overriding the programme default
    announce_date: str | None = None          # ISO date of the planned tender announcement
    woj: str | None = None                    # TERYT woj code "12"
    planned_year: int | None = None
    tech_tags: list[str] = field(default_factory=list)
    text: str = ""                            # description used for the text similarity part
    sector: str = "wod-kan"                   # sector pack (catalogue/<sector>)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Level:
    key: str
    label: str
    filters: dict[str, Any]
    n: int
    n_time: int
    n_cost: int


@dataclass
class RefClass:
    funnel: list[Level]
    chosen: Level                    # level used for shares, tails and the forecast
    mask: np.ndarray
    widened: bool
    widen_note: str | None
    reweight_note: str | None
    n_all: int

    @property
    def n(self) -> int:
        return self.chosen.n

    def label(self) -> str:
        parts = [lv.label for lv in self.funnel[1:]] if not self.widened else [self.chosen.label]
        return ", ".join(parts) if parts else "wszystkie wykonane umowy wod-kan"

    def query_id(self) -> str:
        f = self.chosen.filters
        return "rc:" + "|".join(f"{k}={v}" for k, v in f.items()) if f else "rc:all"

    def to_json(self) -> dict[str, Any]:
        return {"funnel": [asdict(lv) for lv in self.funnel], "chosen": asdict(self.chosen), "widened": self.widened,
                "widen_note": self.widen_note, "reweight_note": self.reweight_note, "n_all": self.n_all}


def _mask(cb: CaseBase, f: dict[str, Any]) -> np.ndarray:
    m = cb.mask_all()
    c = cb.cols
    if "subsector_main" in f:
        m &= c["subsector_main"] == f["subsector_main"]
    if "family" in f:
        fam = [s for s, v in FAMILY.items() if v == f["family"]]
        m &= np.isin(c["subsector_main"], fam)
    if "value_bucket" in f:
        vb = f["value_bucket"]
        m &= np.isin(c["value_bucket"], vb if isinstance(vb, list) else [vb])
    if "design_build" in f:
        m &= c["design_build"] == int(bool(f["design_build"]))
    if "work_type" in f:
        m &= c["work_type"] == f["work_type"]
    return m


def _level(cb: CaseBase, key: str, label: str, f: dict[str, Any]) -> tuple[Level, np.ndarray]:
    m = _mask(cb, f)
    n_time = int((m & np.isfinite(cb["ratio"])).sum())
    n_cost = int((m & cb["cost_ok"]).sum())
    return Level(key=key, label=label, filters=dict(f), n=int(m.sum()), n_time=n_time, n_cost=n_cost), m


def _merge_bucket(b: str, v: float | None) -> list[str]:
    i = BUCKETS.index(b)
    lo, hi = (i - 1 if i > 0 else None), (i + 1 if i + 1 < len(BUCKETS) else None)
    if v is not None and v > 0 and lo is not None and hi is not None:
        # neighbour nearer on the log scale: geometric midpoint of the bucket
        edges = [500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]
        lo_edge = edges[i - 1] if i - 1 < len(edges) else edges[-1]
        hi_edge = edges[i] if i < len(edges) else None
        mid = math.sqrt(lo_edge * hi_edge) if hi_edge else lo_edge
        return [BUCKETS[lo], b] if v < mid else [b, BUCKETS[hi]]
    j = lo if lo is not None else hi
    return sorted([b, BUCKETS[j]], key=BUCKETS.index) if j is not None else [b]


def build(cb: CaseBase, ft: Features) -> RefClass:
    cfg = acfg()
    min_tail = cfg["min_n_tail"]
    bucket = bucket_of(ft.value_gross)
    labels = cb.pack["sub_labels"] or SUB_LABEL

    # 1. the funnel (ordered filters, only those the user gave)
    funnel_spec: list[tuple[str, str, dict]] = [("all", cb.pack["base_label"], {})]
    f: dict[str, Any] = {}
    if ft.subsector_main:
        f = {**f, "subsector_main": ft.subsector_main}
        funnel_spec.append(("subsector", labels.get(ft.subsector_main, ft.subsector_main), f))
    if bucket:
        f = {**f, "value_bucket": bucket}
        funnel_spec.append(("value", BUCKET_LABEL[bucket], f))
    if ft.design_build is not None:
        f = {**f, "design_build": bool(ft.design_build)}
        funnel_spec.append(("formula", "zaprojektuj i wybuduj" if ft.design_build else "samo wykonanie", f))
    funnel: list[Level] = []
    masks: list[np.ndarray] = []
    for key, label, spec in funnel_spec:
        lv, m = _level(cb, key, label, spec)
        funnel.append(lv)
        masks.append(m)
    # work type narrows only when it is distinctive (renovation / mixed); "build" is the default scope of the base
    if ft.work_type in ("renovation", "mixed"):
        lv, m = _level(cb, "work_type", WORK_LABEL[ft.work_type], {**f, "work_type": ft.work_type})
        if lv.n_time >= min_tail:
            funnel.append(lv)
            masks.append(m)
            f = lv.filters

    deepest, deepest_mask = funnel[-1], masks[-1]
    if deepest.n_time >= min_tail:
        return RefClass(funnel=funnel, chosen=deepest, mask=deepest_mask, widened=False, widen_note=None,
                        reweight_note=None, n_all=funnel[0].n)

    # 2. progressive widening: (a) drop work_type, (b) drop design_build, (c) merge value bucket, (d) drop value,
    #    (e) subsector family, (f) all
    cands: list[tuple[str, str, dict, str]] = []
    base = {k: v for k, v in f.items() if k != "work_type"}
    if "work_type" in f:
        cands.append(("w_a", _lab(base, labels), base, "pominięto rodzaj robót"))
    nodb = {k: v for k, v in base.items() if k != "design_build"}
    if "design_build" in base:
        cands.append(("w_b", _lab(nodb, labels), nodb, "pominięto formułę (zaprojektuj i wybuduj)"))
    if bucket:
        merged = {**nodb, "value_bucket": _merge_bucket(bucket, ft.value_gross)}
        cands.append(("w_c", _lab(merged, labels), merged, "połączono sąsiednie przedziały wartości"))
        noval = {k: v for k, v in nodb.items() if k != "value_bucket"}
        cands.append(("w_d", _lab(noval, labels), noval, "pominięto wartość"))
    else:
        noval = nodb
    if ft.subsector_main and ft.subsector_main in FAMILY:
        fam = {"family": FAMILY[ft.subsector_main]}
        cands.append(("w_e", "sieci (SAN, WOD, DESZ)" if fam["family"] == "net" else "obiekty (OCZ, SUW)", fam,
                      "rozszerzono do grupy podsektorów"))
    cands.append(("w_f", cb.pack["base_label"], {}, f"użyto wszystkich umów ({cb.pack['label_short']})"))

    for key, label, spec, note in cands:
        lv, m = _level(cb, key, label, spec)
        if lv.n_time >= min_tail:
            reweight = None
            if "design_build" in base and "design_build" not in spec:
                reweight = _db_gap_note(cb, m)
            return RefClass(funnel=funnel, chosen=lv, mask=m, widened=True,
                            widen_note=f"Za mało podobnych umów (n = {deepest.n}), więc {note}: n = {lv.n}.",
                            reweight_note=reweight, n_all=funnel[0].n)
    lv, m = _level(cb, "all", cb.pack["base_label"], {})
    return RefClass(funnel=funnel, chosen=lv, mask=m, widened=True,
                    widen_note=f"Użyto wszystkich umów ({cb.pack['label_short']}).",
                    reweight_note=None, n_all=funnel[0].n)


def _lab(f: dict, labels: dict | None = None) -> str:
    parts = []
    if "subsector_main" in f:
        parts.append((labels or SUB_LABEL).get(f["subsector_main"], f["subsector_main"]))
    if "value_bucket" in f:
        vb = f["value_bucket"]
        if isinstance(vb, list):
            lo, hi = BUCKET_RANGE[vb[0]][0], BUCKET_RANGE[vb[-1]][1]
            parts.append(f"wartość {lo}–{hi} mln zł" if hi else f"wartość powyżej {lo} mln zł")
        else:
            parts.append(BUCKET_LABEL[vb])
    if "design_build" in f:
        parts.append("zaprojektuj i wybuduj" if f["design_build"] else "samo wykonanie")
    return ", ".join(parts) or "wszystkie wykonane umowy wod-kan"


BUCKET_RANGE = {"<0.5m": ("0", "0,5"), "0.5-1m": ("0,5", "1"), "1-2m": ("1", "2"), "2-5m": ("2", "5"),
                "5-10m": ("5", "10"), ">10m": ("10", None)}


def _db_gap_note(cb: CaseBase, m: np.ndarray) -> str | None:
    late = cb["late"]
    a = m & (cb["design_build"] == 1) & (late >= 0)
    b = m & (cb["design_build"] == 0) & (late >= 0)
    if a.sum() < 10 or b.sum() < 10:
        return None
    pp = (late[a].mean() - late[b].mean()) * 100
    word = "częściej" if pp >= 0 else "rzadziej"
    return (f"W tej grupie umowy „zaprojektuj i wybuduj” kończyły się po terminie o {abs(pp):.0f} pp {word} "
            "niż samo wykonanie.")


def funnel_bar_width(n: int, n_all: int) -> float:
    return max(6.0, math.sqrt(n / n_all) * 100) if n_all else 6.0
