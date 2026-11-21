"""Stub responses (api_contract §2.0 "Fixtures"). Owned by the lead (S0).

`fixture(name, flag=...)` returns `<name>.json` with headers `X-Fixture: true` and `X-Fixture-Flag: <flag>`.
Contract tests fail on `X-Fixture: true` after the 07:00 freeze for every route whose flag is on.
When a session makes an endpoint real it simply stops calling `fixture()`; delete the JSON file only if no route uses it.
Set `api.serve_fixtures: false` in config to make every remaining stub answer 501 instead (freeze rehearsal).
"""
from __future__ import annotations

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from riskminer.config import app_config

DIR = Path(__file__).parent


@cache
def _load(name: str) -> Any:
    return json.loads((DIR / f"{name}.json").read_text(encoding="utf-8"))


def fixture_data(name: str) -> Any:
    """Deep copy of a fixture (safe to mutate)."""
    return copy.deepcopy(_load(name))


def fixture(name: str, *, flag: str | None = None, status_code: int = 200, override: dict | None = None) -> JSONResponse:
    if (app_config().get("api") or {}).get("serve_fixtures", True) is False:
        return JSONResponse({"detail": "Ta funkcja nie jest jeszcze gotowa.", "code": "not_implemented"}, status_code=501,
                            headers={"X-Fixture": "off", **({"X-Fixture-Flag": flag} if flag else {})})
    data = fixture_data(name)
    if override and isinstance(data, dict):
        data.update(override)
    headers = {"X-Fixture": "true"}
    if flag:
        headers["X-Fixture-Flag"] = flag
    return JSONResponse(data, status_code=status_code, headers=headers)
