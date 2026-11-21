"""Freeze guard (api_contract §2.0, §8.3c): a route may serve a fixture (`X-Fixture: true`) only while its feature flag
is off. Static scan of `api/routers/*.py` for handlers that call `fixture(...)`; no DB, no server.

- A handler calling `fixture(name, flag="x")` fails when `features.x` is true in config.
- A handler calling `fixture(name)` without a flag belongs to a core screen: it fails once `RISKMINER_FREEZE=1`
  (set at the 07:00 freeze), and is listed as a warning before that.
"""
from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path

import pytest

from riskminer.config import app_config

pytestmark = pytest.mark.unit
ROUTERS = Path(__file__).resolve().parents[2] / "riskminer" / "api" / "routers"


def _stubs() -> list[tuple[str, str, str | None]]:
    """-> [(file, handler, flag|None)] for every handler that calls fixture()."""
    out = []
    for f in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "fixture":
                    flag = next((k.value.value for k in call.keywords if k.arg == "flag" and isinstance(k.value, ast.Constant)), None)
                    out.append((f.name, fn.name, flag))
    return out


def test_no_fixture_behind_enabled_flag():
    feats = app_config().get("features") or {}
    bad = [f"{file}:{fn} (flag {flag})" for file, fn, flag in _stubs() if flag and feats.get(flag)]
    assert not bad, "feature flag is on but the route still serves a fixture: " + ", ".join(bad)


def test_core_routes_are_real_at_freeze():
    core = [f"{file}:{fn}" for file, fn, flag in _stubs() if not flag]
    if os.environ.get("RISKMINER_FREEZE") == "1":
        assert not core, "core routes still serving fixtures at freeze: " + ", ".join(core)
    elif core:
        warnings.warn("core routes still on fixtures: " + ", ".join(core), stacklevel=1)
