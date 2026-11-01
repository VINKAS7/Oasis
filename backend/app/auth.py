"""Who is calling. The auth service (better-auth) is the source of truth: we forward the
browser's cookie to /api/auth/get-session and trust its answer, cached for a few seconds
because the UI polls crawl progress."""

import asyncio
import time
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, Request

from .config import AUTH_URL

_CACHE_TTL_S = 5.0
_cache: dict[str, tuple[float, "User | None"]] = {}
_client = httpx.AsyncClient(base_url=AUTH_URL, timeout=5.0)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return "admin" in [r.strip() for r in (self.role or "").split(",")]


async def _lookup(cookie: str, authorization: str = "") -> "User | None":
    key = f"{cookie}|{authorization}"
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    headers = {"cookie": cookie}
    if authorization:
        headers["authorization"] = authorization
    for attempt in range(3):
        try:
            resp = await _client.get("/api/auth/get-session", headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "The auth service is not reachable") from exc
        # Only a real answer (200: a session or none; 401) says who this is. A busy or failing auth
        # service (429, 5xx) is asked again, then reported as such: never "not signed in", never cached.
        if resp.status_code in (200, 401):
            break
        await asyncio.sleep(0.3 * (attempt + 1))
    else:
        raise HTTPException(503, "The sign-in service is busy. Try again in a moment.")
    try:
        data = resp.json() if resp.status_code == 200 else None
    except ValueError:  # an empty body: no session
        data = None
    user = None
    if data and data.get("user") and not data["user"].get("banned"):
        u = data["user"]
        user = User(id=u["id"], email=u["email"], name=u.get("name") or "", role=u.get("role") or "user")
    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = (time.monotonic() + _CACHE_TTL_S, user)
    return user


async def current_user(request: Request) -> User:
    cookie = request.headers.get("cookie", "")
    # The Chrome extension sends the session token as a bearer token instead of a cookie.
    authorization = request.headers.get("authorization", "")
    bearer = authorization if authorization.lower().startswith("bearer ") else ""
    user = await _lookup(cookie, bearer) if ("session_token" in cookie or bearer) else None
    if user is None:
        raise HTTPException(401, "Sign in first")
    return user


async def optional_user(request: Request) -> "User | None":
    """The signed-in user, or None (public pages that show owners a little more)."""
    try:
        return await current_user(request)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user
