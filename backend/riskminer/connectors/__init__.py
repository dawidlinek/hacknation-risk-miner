"""Connector registry.

A connector is a module `riskminer.connectors.<source>` exposing:

    SOURCE = "ted"
    DEFAULTS = {"min_interval": 1.0, "ttl_hours": None}      # ScrapeContext.create kwargs
    def run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts) -> dict
        # fetch -> raw files + manifest lines; return stats
    def parse(store: RawStore) -> Iterable[AnyRecord]
        # re-derive normalised records from the raw files only (no network)

Run with `uv run riskminer scrape <source> [--since D] [--until D] [--limit N] [--only a,b]`.
"""
from __future__ import annotations

import importlib
from types import ModuleType

KNOWN = [
    # P0
    "bzp_api", "vat_whitelist", "teryt", "geo",
    # P1
    "mapa_dotacji", "ted", "kio", "nik", "cru", "docs_22",
    # P2
    "docs_sample", "kposk", "gus_bdl", "gus_price_index", "fe_projects", "nfosigw", "bip_22", "gus_bir",
    # P3
    "krs", "bk2021", "bzp_roads",
]


def get(source: str) -> ModuleType:
    return importlib.import_module(f"riskminer.connectors.{source}")


def available() -> list[str]:
    out = []
    for s in KNOWN:
        try:
            get(s)
            out.append(s)
        except ModuleNotFoundError:
            continue
    return out
