"""The AI gateway's public door: the owner app asks for completions here and never sees
which provider, model or key the admin chose."""

import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, settings, vault
from ..ai import gateway
from ..ai.providers import ProviderError
from ..auth import User, current_user

router = APIRouter(prefix="/api/ai", tags=["ai"])

_recent: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(user_id: str) -> None:
    limit = settings.get("ai.user_requests_per_minute")
    window = _recent[user_id]
    cutoff = time.monotonic() - 60
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(429, f"At most {limit} AI requests per minute; try again shortly")
    window.append(time.monotonic())


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class CompleteIn(BaseModel):
    task: str = "assistant"
    system: str = Field(default="", max_length=4000)
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    business_id: str | None = None


@router.get("/status")
def status(_: User = Depends(current_user)) -> dict:
    return {"tasks": {task: gateway.is_configured(task) for task in gateway.TASKS}}


@router.post("/complete")
async def complete(body: CompleteIn, user: User = Depends(current_user)) -> dict:
    if body.task not in gateway.USER_TASKS:
        raise HTTPException(403, "This AI task is not available to the app")
    if body.business_id:
        with db.session() as conn:
            owner = conn.execute("SELECT owner_id FROM businesses WHERE id = ?", (body.business_id,)).fetchone()
        if owner is None or (owner["owner_id"] != user.id and not user.is_admin):
            raise HTTPException(404, "Workspace not found")
    _rate_limit(user.id)
    try:
        result = await gateway.run(
            body.task,
            system=body.system,
            messages=[{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in body.messages],
            user_id=user.id,
            business_id=body.business_id,
        )
    except gateway.AINotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except vault.VaultError as exc:
        raise HTTPException(503, "The AI provider key cannot be read; ask an admin to re-enter it") from exc
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "text": result.text,
        "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
    }
