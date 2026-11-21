"""Auth endpoints (api_contract §2.1, §5): login, logout, me. Session cookie `rm_session`, demo users from RISKMINER_USERS.
The CSRF header (X-Requested-With: ex-ante) is enforced by RequestContextMiddleware."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A

from riskminer.db.session import get_session
from riskminer.review.common import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class DemoLoginIn(BaseModel):
    """Body is optional. `persona` is accepted for old links (juror, expert, admin) and ignored: one demo user."""
    persona: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    name: str
    role: str
    initials: str
    persona: str | None = None
    read_only: bool = False


class SessionOut(BaseModel):
    """`user` is the api_contract shape; `role`/`name`/`initials` are the flat shape the frontend session type uses
    (role `public` when anonymous)."""
    user: UserOut | None
    anon_id: str
    role: str
    name: str | None
    initials: str | None
    persona: str | None = None
    read_only: bool = False


def _initials(name: str) -> str:
    parts = [p for p in "".join(c if c.isalnum() else " " for c in name).split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + parts[1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()


def _out(s: A.Session) -> SessionOut:
    u = UserOut(name=s.user.name, role=s.user.role, initials=_initials(s.user.name), persona=s.user.persona, read_only=s.user.read_only) if s.user else None
    return SessionOut(user=u, anon_id=s.anon_id, role=s.user.role if s.user else "public",
                      name=u.name if u else None, initials=u.initials if u else None,
                      persona=s.user.persona if s.user else None, read_only=s.user.read_only if s.user else False)


@router.post("/login", response_model=SessionOut, summary="Logowanie (ciasteczko sesji rm_session)")
async def login(body: LoginIn, response: Response, s: A.Session = Depends(A.session), db: AsyncSession = Depends(get_session)):
    if A.rate_limited(f"login:{s.anon_id}", 10):
        raise A.ApiError(429, "Za dużo prób logowania, spróbuj za minutę.", "rate_limited", {"Retry-After": "60"})
    user = A.authenticate(body.username.strip(), body.password)
    if user is None:
        raise A.ApiError(401, "Nieprawidłowy login lub hasło.", "bad_credentials")
    s2 = A.Session(anon_id=s.anon_id, user=user)  # anon id is kept: analyses created before login stay owned
    A.write_cookie(response, s2)
    await audit(db, user.actor, "auth.login", None, None, None, {"role": user.role, "method": "password"}, A.request_id())
    await db.commit()
    return _out(s2)


@router.post("/logout", status_code=204, summary="Wylogowanie")
async def logout(response: Response, s: A.Session = Depends(A.session)):
    A.write_cookie(response, A.Session(anon_id=s.anon_id, user=None))


@router.get("/me", response_model=SessionOut, summary="Bieżąca sesja (role=public, gdy niezalogowany)")
async def me(s: A.Session = Depends(A.session)):
    return _out(s)


@router.get("/demo-personas", summary="DEMO: konto demonstracyjne (logowanie jednym kliknięciem)")
async def demo_personas():
    """Demo-only mechanism: lists the single one-click demo user, or an empty list when `RISKMINER_DEMO_LOGIN=false`."""
    if not A.demo_login_enabled():
        return []
    return [{"persona": k, "label": v["label"], "description": v["description"], "role": v["role"]}
            for k, v in A.DEMO_PERSONAS.items()]


@router.post("/demo-login", response_model=SessionOut, summary="DEMO: logowanie jednym kliknięciem, bez hasła (tylko wersja demonstracyjna)",
             description="**Tylko do demonstracji.** Jedno konto bez hasła, „Ekspert (demo)”, z pełnymi uprawnieniami (zatwierdza, poprawia, "
                         "odrzuca, edytuje katalog). Treść żądania jest pusta; stare pole `persona` jest przyjmowane i pomijane. "
                         "Każde logowanie trafia do dziennika zmian. Wyłączane zmienną `RISKMINER_DEMO_LOGIN=false`.")
async def demo_login(response: Response, body: DemoLoginIn | None = None, s: A.Session = Depends(A.session), db: AsyncSession = Depends(get_session)):
    if not A.demo_login_enabled():
        raise A.ApiError(403, "Logowanie demonstracyjne jest wyłączone.", "demo_login_disabled")
    if A.rate_limited(f"login:{s.anon_id}", 30):
        raise A.ApiError(429, "Za dużo prób logowania, spróbuj za minutę.", "rate_limited", {"Retry-After": "60"})
    user = A.demo_user()
    s2 = A.Session(anon_id=s.anon_id, user=user)
    A.write_cookie(response, s2)
    await audit(db, user.actor, "auth.login", None, None, None, {"role": user.role, "persona": user.persona, "read_only": user.read_only,
                                                                 "method": "demo"}, A.request_id(), "logowanie demo")
    await db.commit()
    return _out(s2)
