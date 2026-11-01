"""Who is calling: a busy auth service (429) is never mistaken for "not signed in"."""

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app import auth

SESSION = {"user": {"id": "usr_1", "email": "a@b.c", "name": "A", "role": "user"}}


def fake(statuses, monkeypatch):
    calls = []

    async def get(path, headers=None):
        code = statuses[min(len(calls), len(statuses) - 1)]
        calls.append(code)
        return httpx.Response(code, json=SESSION if code == 200 else {"message": "x"})

    monkeypatch.setattr(auth._client, "get", get)
    monkeypatch.setattr(auth, "_cache", {})
    return calls


def test_rate_limited_then_ok(monkeypatch):
    calls = fake([429, 200], monkeypatch)
    user = asyncio.run(auth._lookup("better-auth.session_token=x"))
    assert user and user.id == "usr_1" and calls == [429, 200]


def test_still_busy_is_503_not_signed_out(monkeypatch):
    calls = fake([429], monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(auth._lookup("better-auth.session_token=y"))
    assert e.value.status_code == 503 and len(calls) == 3
    assert auth._cache == {}  # a failure is not cached as "no user"


def test_no_session_is_none(monkeypatch):
    async def get(path, headers=None):
        return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})

    monkeypatch.setattr(auth._client, "get", get)
    monkeypatch.setattr(auth, "_cache", {})
    assert asyncio.run(auth._lookup("better-auth.session_token=z")) is None
