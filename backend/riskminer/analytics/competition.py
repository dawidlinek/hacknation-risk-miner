"""Tender outcomes by year from `lot` (analytics.md §3.6). Denominators as in the research: cancelled, price-above-
budget and single-offer shares over all result lots; P(>=2) over lots with at least one offer."""
from __future__ import annotations

import numpy as np

from riskminer.analytics.base import CaseBase


def tenders_by_year(cb: CaseBase, subsector: str | None = None) -> list[dict]:
    L = cb.lots
    pub = L["published_on"]
    ok = ~np.isnat(pub)
    if subsector:
        ok &= L["subsector_main"] == subsector
    years = pub.astype("datetime64[Y]").astype(int) + 1970
    basis = np.array([str(b or "") for b in L["cancel_basis"]], dtype=object)
    out = []
    for y in sorted({int(v) for v in years[ok]}):
        m = ok & (years == y)
        n = int(m.sum())
        if n == 0:
            continue
        offers = L["n_offers"][m]
        pos = offers[np.isfinite(offers) & (offers > 0)]
        out.append({
            "year": y, "lots": n,
            "cancelled_pct": round(float((L["cancelled"][m] == 1).mean() * 100), 1),
            "cancelled_price_pct": round(float(np.char.startswith(basis[m].astype(str), "art. 255 pkt 3").mean() * 100),
                                         1),
            "single_offer_pct": round(float((offers == 1).mean() * 100), 1),
            "ge2_pct": round(float((pos >= 2).mean() * 100), 1) if pos.size else None,
            "median_offers": float(np.median(offers[np.isfinite(offers)])) if np.isfinite(offers).any() else None,
            "prov": {"role": "calc", "review_status": "auto", "n": n, "method": "share(lot | result notice year)",
                     "refs": [{"kind": "query", "id": f"lot:year={y}" + (f"|sub={subsector}" if subsector else ""),
                               "label": "ogłoszenia o wyniku (pola 5.1, 5.2, 6.1)"}]},
        })
    return out
