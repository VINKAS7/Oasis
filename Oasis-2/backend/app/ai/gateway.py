"""The one door every AI request goes through.

Callers name a task ("page_analysis", "site_summary", "assistant"); the gateway looks up
which provider, model and key the admin assigned to it (or the default route), makes the
call, and writes a row to ai_calls. No other module talks to an AI provider or sees a key.
"""

import time
from dataclasses import dataclass
from typing import Any

from .. import db, vault
from .providers import Completion, ProviderConfig, ProviderError, complete, parse_json

TASKS: dict[str, dict[str, Any]] = {
    "page_analysis": {
        "label": "Page analysis",
        "description": "Reads each crawled page and sorts what it finds into information and visitor actions.",
        "max_tokens": 8000,
    },
    "site_summary": {
        "label": "Site summary",
        "description": "Turns the page analyses into the owner's 'Tools ready' and 'To-do' lists.",
        "max_tokens": 16000,
    },
    "tool_proposal": {
        "label": "Tool proposal",
        "description": "Turns a recorded flow into a proposed tool, compared with the tools that already exist.",
        "max_tokens": 16000,
    },
    "safety_scan": {
        "label": "Safety scan",
        "description": "Checks what a tool returns for hidden instructions aimed at AI assistants (prompt injection).",
        "max_tokens": 2000,
    },
    "client_chat": {
        "label": "Customer chat",
        "description": "Answers visitors on the public /chat page, using the businesses' tools through the MCP gateway.",
        "max_tokens": 1500,
    },
    "assistant": {
        "label": "Owner assistant",
        "description": "General requests from the owner app through POST /api/ai/complete.",
        "max_tokens": 4000,
    },
}
# Tasks a signed-in user may call directly through /api/ai/complete. The rest run server-side only.
USER_TASKS = {"assistant"}


class AINotConfigured(RuntimeError):
    pass


@dataclass
class Route:
    task: str
    provider_id: str
    provider_name: str
    supports_vision: bool
    config: ProviderConfig


@dataclass
class AIResult:
    text: str
    data: Any
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


def resolve(task: str) -> Route:
    if task not in TASKS:
        raise AINotConfigured(f"Unknown AI task: {task}")
    with db.session() as conn:
        routes = {r["task"]: r for r in conn.execute("SELECT * FROM ai_routes WHERE task IN (?, 'default')", (task,))}
        route = routes.get(task)
        if route is not None and not route["enabled"]:
            raise AINotConfigured(f"The admin has switched off the '{task}' task")
        if route is None or not route["provider_id"]:
            route = routes.get("default")
        if route is None or not route["provider_id"]:
            raise AINotConfigured("No AI provider is set up yet. An admin can add one in Admin → AI providers.")
        provider = conn.execute("SELECT * FROM ai_providers WHERE id = ?", (route["provider_id"],)).fetchone()
    if provider is None or not provider["enabled"]:
        raise AINotConfigured("The AI provider for this task is missing or disabled")
    api_key = vault.decrypt(provider["api_key_enc"]) if provider["api_key_enc"] else ""
    if not api_key and provider["kind"] != "openai_compatible":
        raise AINotConfigured(f"Provider '{provider['name']}' has no API key")
    return Route(
        task=task,
        provider_id=provider["id"],
        provider_name=provider["name"],
        supports_vision=bool(provider["supports_vision"]),
        config=ProviderConfig(
            kind=provider["kind"],
            api_key=api_key,
            base_url=provider["base_url"],
            model=route["model"] or provider["default_model"],
            effort=route["effort"] or "",
            max_tokens=route["max_tokens"] or TASKS[task]["max_tokens"],
        ),
    )


def is_configured(task: str) -> bool:
    try:
        resolve(task)
        return True
    except (AINotConfigured, vault.VaultError):
        return False


async def run(
    task: str,
    *,
    system: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any] | None = None,
    user_id: str | None = None,
    business_id: str | None = None,
    route: Route | None = None,
) -> AIResult:
    route = route or resolve(task)
    if not route.supports_vision:
        messages = [{**m, "content": [p for p in m["content"] if p["type"] != "image"]} for m in messages]
    started = time.monotonic()
    result: Completion | None = None
    error: str | None = None
    try:
        result = await complete(route.config, system=system, messages=messages, json_schema=json_schema)
        data = parse_json(result.text) if json_schema is not None else None
        return AIResult(
            text=result.text,
            data=data,
            provider=route.provider_name,
            model=route.config.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    except ProviderError as exc:
        error = str(exc)
        raise
    finally:
        with db.session() as conn:
            conn.execute(
                "INSERT INTO ai_calls (task, user_id, business_id, provider_id, provider_kind, model, ok, error,"
                " input_tokens, output_tokens, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task,
                    user_id,
                    business_id,
                    route.provider_id,
                    route.config.kind,
                    route.config.model,
                    int(error is None),
                    error,
                    result.input_tokens if result else None,
                    result.output_tokens if result else None,
                    int((time.monotonic() - started) * 1000),
                    db.now(),
                ),
            )


def text_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}
