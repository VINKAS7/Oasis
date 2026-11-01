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
    limit = settings.get("chat.public_requests_per_minute")
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


class ShownItem(BaseModel):
    business_id: str = Field(max_length=80)
    id: str = Field(max_length=160)
    name: str = Field(max_length=160)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    location: str = Field(default="", max_length=200)
    # The language picked on the chat page (en, fr, it, de): what to answer in when the visitor's own is unclear.
    language: Literal["", "en", "fr", "it", "de"] = ""
    # Businesses found earlier in this chat, so follow-ups ("their menu?") use the real business_id.
    businesses: list[KnownBusiness] = Field(default_factory=list, max_length=20)
    # Items the page showed as cards earlier in this chat, so "order the second one" has real ids.
    items_shown: list[ShownItem] = Field(default_factory=list, max_length=80)


class ConfirmIn(ChatIn):
    business_id: str = Field(min_length=1, max_length=80)
    tool: str = Field(min_length=1, max_length=80)
    inputs: dict[str, Any] = Field(default_factory=dict)
    token: str = Field(min_length=1, max_length=80)  # from the confirm card: this exact action was proposed


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
    return _ndjson(agent.stream([m.model_dump() for m in body.messages], body.location.strip(), [b.model_dump() for b in body.businesses],
                                language=body.language, items_shown=[i.model_dump() for i in body.items_shown]))


@router.post("/confirm")
async def confirm(body: ConfirmIn, request: Request) -> StreamingResponse:
    """The visitor clicked Confirm on an action the assistant prepared: run exactly that call."""
    _rate_limit(_visitor(request))
    if not agent.check_confirm_token(body.token, body.business_id, body.tool, body.inputs):
        raise HTTPException(400, "This confirmation has expired or doesn't match what was proposed. Ask again, then confirm.")
    confirmed = {"business_id": body.business_id, "tool": body.tool, "inputs": body.inputs}
    known = [b.model_dump() for b in body.businesses]
    return _ndjson(agent.stream([m.model_dump() for m in body.messages], body.location.strip(), known, confirmed=confirmed, language=body.language,
                                items_shown=[i.model_dump() for i in body.items_shown]))


class OrderLine(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=20)
    options: dict[str, str] = Field(default_factory=dict)  # an Oasis shop item's size, colour...


class OrderIn(BaseModel):
    business_id: str = Field(min_length=1, max_length=80)
    items: list[OrderLine] = Field(min_length=1, max_length=50)
    customer_name: str = Field(min_length=1, max_length=80)
    customer_contact: str = Field(min_length=3, max_length=120)
    pickup_time: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)


async def _gateway(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await agent.call(tool, args)
    except Exception as exc:  # noqa: BLE001 - MCP errors arrive as exception groups
        raise HTTPException(502, "Can't reach the Oasis directory right now. Please try again.") from exc


@router.post("/order")
async def order(body: OrderIn, request: Request) -> dict[str, Any]:
    """The visitor pressed Send order on the order they reviewed: that click is their confirmation,
    so this exact order goes through the gateway with user_confirmed=true."""
    _rate_limit(_visitor(request))
    inputs = body.model_dump(exclude={"business_id"})
    data = await _gateway("call_business_tool", {"business_id": body.business_id, "tool": "request_order", "inputs": inputs, "user_confirmed": True})
    if not data.get("ok"):
        raise HTTPException(400, data.get("message") or "The order could not be sent.")
    return {k: data.get(k) for k in ("order_id", "status", "status_token", "lines", "total", "currency", "business", "message")}


@router.get("/orders/{order_id}")
async def order_status(order_id: str, business_id: str, token: str) -> dict[str, Any]:
    data = await _gateway("call_business_tool", {"business_id": business_id, "tool": "get_order_status", "inputs": {"order_id": order_id, "status_token": token}})
    if not data.get("ok"):
        raise HTTPException(404, data.get("message") or "Order not found")
    return {k: data.get(k) for k in ("order_id", "status", "owner_note", "updated_at")}
