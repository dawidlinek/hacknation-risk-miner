"""Auth: signed session cookie, demo users from env, FastAPI dependencies, CSRF guard, rate limit.

Users come from `RISKMINER_USERS` (`name:role:scrypt_hash;name2:role:hash`, roles expert|admin); there is no user table.
Generate a hash with `python -m riskminer.api.auth hash-password` (reads the password from stdin or a prompt).
Anonymous visitors get a random `anon_id` in the same cookie: it owns their analyses/questions and keys rate limits.

Cookie `rm_session` = itsdangerous URLSafeTimedSerializer payload {"a": anon_id, "u": name|None, "r": role|None}.
Secret: `RISKMINER_SESSION_SECRET` (random per process when unset: sessions then die on restart).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "rm_session"
MAX_AGE = 12 * 3600
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "ex-ante"
ROLES = ("expert", "admin")

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


# ---- errors ------------------------------------------------------------------------------------------------------

class ApiError(HTTPException):
    """HTTPException carrying a machine code: body `{"detail": <Polish message>, "code": <code>}`.
    Register `api_error_handler` for `ApiError` in main.py to expose `code`; without it only `detail` is returned."""

    def __init__(self, status_code: int, detail: str, code: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


async def api_error_handler(request: Request, exc: ApiError):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status_code, headers=exc.headers)


# ---- passwords ---------------------------------------------------------------------------------------------------

def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=128 * 1024 * 1024)
    b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")  # noqa: E731
    return f"scrypt${n}${r}${p}${b(salt)}${b(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b, dk_b = stored.split("$")
        if scheme != "scrypt":
            return False
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        salt, want = base64.urlsafe_b64decode(pad(salt_b)), base64.urlsafe_b64decode(pad(dk_b))
        got = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(want),
                             maxmem=128 * 1024 * 1024)
        return hmac.compare_digest(got, want)
    except Exception:
        return False


@dataclass(frozen=True)
class User:
    name: str
    role: str  # expert | admin (the demo user has role admin = full rights)
    persona: str | None = None  # demo user marker ("demo")
    read_only: bool = False

    @property
    def actor(self) -> str:
        return f"user:{self.name}"


# Demo-only one-click login (no password): ONE user with full rights (expert + admin). Old persona names
# (juror, expert, admin) are still accepted and map to the same user, so old links and cookies keep working.
DEMO_USER = {"name": "Ekspert (demo)", "role": "admin", "persona": "demo",
             "label": "Ekspert (demo)", "description": "zatwierdza, poprawia i odrzuca wnioski, edytuje katalog, ustawienia i wersje"}
DEMO_PERSONAS: dict[str, dict] = {"demo": DEMO_USER}


def demo_login_enabled() -> bool:
    return (_env("RISKMINER_DEMO_LOGIN") or "true").lower() not in ("0", "false", "no")


def demo_user(persona: str | None = None) -> User:
    return User(DEMO_USER["name"], DEMO_USER["role"], persona="demo", read_only=False)


def load_users(raw: str | None = None) -> dict[str, tuple[str, str]]:
    """{name: (role, hash)} from `name:role:hash;...`. Malformed entries are skipped."""
    raw = _env("RISKMINER_USERS") if raw is None else raw
    out: dict[str, tuple[str, str]] = {}
    for part in (raw or "").split(";"):
        bits = part.strip().split(":", 2)
        if len(bits) == 3 and bits[1] in ROLES and bits[0] and bits[2]:
            out[bits[0]] = (bits[1], bits[2])
    return out


@lru_cache
def _dotenv_all() -> dict[str, str]:
    from dotenv import dotenv_values  # pydantic-settings dependency
    from riskminer.config import REPO_ROOT
    try:
        return {k: v for k, v in dotenv_values(REPO_ROOT / ".env").items() if v is not None}
    except Exception:
        return {}


def _dotenv_value(key: str) -> str | None:
    return _dotenv_all().get(key)


def _env(key: str) -> str | None:
    return os.environ.get(key) or _dotenv_value(key)


def authenticate(username: str, password: str) -> User | None:
    rec = load_users().get(username)
    if rec is None:
        # constant-ish time for unknown users
        verify_password(password, hash_password("x", n=2**10))
        return None
    role, stored = rec
    return User(username, role) if verify_password(password, stored) else None


# ---- session cookie ----------------------------------------------------------------------------------------------

_PROCESS_SECRET = secrets.token_urlsafe(32)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_env("RISKMINER_SESSION_SECRET") or _PROCESS_SECRET, salt="rm-session")


def _secure() -> bool:
    return (_env("RISKMINER_COOKIE_SECURE") or "").lower() in ("1", "true", "yes")


@dataclass
class Session:
    anon_id: str
    user: User | None = None

    @property
    def actor(self) -> str:
        return self.user.actor if self.user else f"anon:{self.anon_id[:8]}"


def new_anon_id() -> str:
    return secrets.token_hex(4)


def _read(request: Request) -> Session | None:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    try:
        d = _serializer().loads(tok, max_age=MAX_AGE)
    except BadSignature:
        return None
    if d.get("p") and demo_login_enabled():  # any demo cookie (also the old juror/expert/admin ones) is the one demo user
        user = demo_user()
    else:
        user = User(d["u"], d["r"]) if d.get("u") and d.get("r") in ROLES and not d.get("p") else None
    return Session(anon_id=d.get("a") or new_anon_id(), user=user)


def write_cookie(response: Response, s: Session) -> None:
    tok = _serializer().dumps({"a": s.anon_id, "u": s.user.name if s.user else None, "r": s.user.role if s.user else None,
                               "p": s.user.persona if s.user else None})
    response.set_cookie(COOKIE, tok, max_age=MAX_AGE, httponly=True, samesite="lax", secure=_secure(), path="/")


async def session(request: Request, response: Response) -> Session:
    """Current session; creates (and sets) an anonymous one when the cookie is missing or invalid."""
    s = _read(request)
    if s is None:
        s = Session(anon_id=new_anon_id())
        write_cookie(response, s)
    request.state.rm_session = s
    return s


async def current_user(s: Session = Depends(session)) -> User | None:
    return s.user


async def require_login(s: Session = Depends(session)) -> User:
    if s.user is None:
        raise ApiError(401, "Zaloguj się, żeby wykonać tę czynność.", "login_required")
    return s.user


async def require_writer(user: User = Depends(require_login)) -> User:
    """Logged in and allowed to change data (expert or admin; the single demo user is both)."""
    if user.read_only:
        raise ApiError(403, "To konto jest tylko do odczytu.", "read_only")
    return user


async def require_admin(user: User = Depends(require_login)) -> User:
    if user.role != "admin":
        raise ApiError(403, "Ta czynność wymaga uprawnień administratora.", "admin_required")
    return user


async def csrf_guard(request: Request) -> None:
    """Non-GET requests must carry `X-Requested-With: ex-ante` (cookies are SameSite=Lax)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise ApiError(403, "Brak nagłówka X-Requested-With.", "csrf")


def actor_of(s: Session) -> str:
    return s.actor


def request_id(request: Request | None = None) -> str | None:
    from riskminer.api.middleware import request_id_var
    return request_id_var.get() or ((request.headers.get("x-request-id") or "")[:64] if request else None) or None


def is_public(user: User | None) -> bool:
    return user is None


def public_filter(user: User | None, alias: str = "", *, origin_col: str = "origin", status_col: str = "review_status") -> str:
    """SQL fragment hiding unverified AI rows from anonymous callers; empty-true for logged-in users."""
    if user is not None:
        return "true"
    a = f"{alias}." if alias else ""
    return f"({a}{origin_col} <> 'AI' OR {a}{status_col} IN ('approved','edited'))"


def public_doc_filter(user: User | None, alias: str = "d") -> str:
    """Confidential documents: anonymous callers see public ones only; an expert also sees their own uploads; admin sees all
    (owners reach their own through the analysis, api_contract §3.3)."""
    if user is not None and user.role == "admin":
        return "true"
    base = f"{alias}.sensitivity IS NULL OR {alias}.sensitivity = 'public'"
    if user is None:
        return f"({base})"
    actor = user.actor.replace("'", "''")
    return f"({base} OR {alias}.data->>'owner_user' = '{actor}')"


# ---- rate limit (in-process token bucket) ------------------------------------------------------------------------

_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(key: str, per_min: int, *, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    q = _hits[key]
    while q and q[0] <= now - 60:
        q.popleft()
    if len(q) >= per_min:
        return True
    q.append(now)
    return False


def rate_limit(bucket: str, per_min: int = 10):
    """Dependency factory: `Depends(rate_limit("ask", 10))` limits per anon id / user and per client IP."""
    async def dep(request: Request, s: Session = Depends(session)) -> None:
        ip = request.client.host if request.client else "?"
        for k in (f"{bucket}:id:{s.actor}", f"{bucket}:ip:{ip}"):
            if rate_limited(k, per_min):
                raise ApiError(429, "Za dużo pytań, spróbuj za minutę.", "rate_limited", {"Retry-After": "60"})
    return dep


if __name__ == "__main__":  # python -m riskminer.api.auth hash-password
    if len(sys.argv) > 1 and sys.argv[1] == "hash-password":
        import getpass
        pw = sys.stdin.readline().rstrip("\n") if not sys.stdin.isatty() else getpass.getpass("Hasło: ")
        print(hash_password(pw))
    else:
        print("usage: python -m riskminer.api.auth hash-password  (password on stdin or prompt)")
