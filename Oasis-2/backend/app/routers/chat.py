"""The public customer chat (/chat). No login: visitors are rate-limited by IP instead.
Answers stream as NDJSON, one event per line (see chat/agent.py for the event types)."""

import json
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import settings
from ..chat import agent

router = APIRouter(prefix="/api/chat", tags=["chat"])

_recent: dict[str, deque[float]] = defaultdict(deque)
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _visitor(request: Request) -> str:
    """The visitor's IP. X-Forwarded-For is trusted only from a proxy on this machine (Vite in
    development), so a visitor can't pick their own rate-limit bucket."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if peer in _LOOPBACK and forwarded:
        return forwarded.split(",")[0].strip()
    return peer


def _rate_limit(key: str) -> None:
    limit = settings.get("ai.user_requests_per_minute")
    window = _recent[key]
    cutoff = time.monotonic() - 60
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(429, f"You're sending messages quickly. Please wait a minute (at most {limit} a minute).")
    window.append(time.monotonic())


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class KnownBusiness(BaseModel):
    business_id: str = Field(max_length=80)
    name: str = Field(max_length=120)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    location: str = Field(default="", max_length=200)
    # Businesses found earlier in this chat, so follow-ups ("their menu?") use the real business_id.
    businesses: list[KnownBusiness] = Field(default_factory=list, max_length=20)


class ConfirmIn(ChatIn):
    business_id: str = Field(min_length=1, max_length=80)
    tool: str = Field(min_length=1, max_length=80)
    inputs: dict[str, Any] = Field(default_factory=dict)


def _ndjson(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def lines() -> AsyncIterator[str]:
        async for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    # no-transform/X-Accel-Buffering: proxies must pass each line on as it comes.
    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"cache-control": "no-cache, no-transform", "x-accel-buffering": "no"})


@router.post("")
async def chat(body: ChatIn, request: Request) -> StreamingResponse:
    if body.messages[-1].role != "user":
        raise HTTPException(400, "The last message must be the visitor's")
    _rate_limit(_visitor(request))
    return _ndjson(agent.stream([m.model_dump() for m in body.messages], body.location.strip(), [b.model_dump() for b in body.businesses]))


@router.post("/confirm")
async def confirm(body: ConfirmIn, request: Request) -> StreamingResponse:
    """The visitor clicked Confirm on an action the assistant prepared: run exactly that call."""
    _rate_limit(_visitor(request))
    confirmed = {"business_id": body.business_id, "tool": body.tool, "inputs": body.inputs}
    known = [b.model_dump() for b in body.businesses]
    return _ndjson(agent.stream([m.model_dump() for m in body.messages], body.location.strip(), known, confirmed=confirmed))
