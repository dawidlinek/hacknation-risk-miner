"""Request middleware (api_contract §2.0). Owned by the lead (S0).

- `X-Request-ID`: accepted or generated, echoed back, available as `request_id_var.get()` for `audit_log.request_id`.
- CSRF guard: non-GET/HEAD/OPTIONS requests under /api need `X-Requested-With: ex-ante` (SameSite=Lax cookies).
  Switch: `api.require_xrw` in config (default true).
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from riskminer.config import app_config

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
XRW_VALUE = "ex-ante"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:64]
        token = request_id_var.set(rid)
        try:
            if (request.method not in SAFE_METHODS and request.url.path.startswith("/api/")
                    and (app_config().get("api") or {}).get("require_xrw", True)
                    and request.headers.get("x-requested-with") != XRW_VALUE):
                return JSONResponse({"detail": "Brak nagłówka X-Requested-With: ex-ante.", "code": "csrf_header_missing"},
                                    status_code=403, headers={"X-Request-ID": rid})
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)
