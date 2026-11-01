"""Admin-only endpoints: AI providers and keys, which model each task uses, crawler
settings, and the AI usage log. User accounts are managed through better-auth's admin
plugin (/api/auth/admin/*), which enforces the same role."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .. import db, settings, vault
from ..ai import gateway
from ..ai.providers import ProviderConfig, ProviderError
from ..auth import User, require_admin
from ..config import PUBLIC_API_URL
from ..gateway import business_mcp, orders, service
from ..ids import new_id

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

ProviderKind = Literal["anthropic", "openai", "openai_compatible"]
# "none" is for OpenAI-style providers (reasoning_effort); it turns thinking off on Qwen3/Ollama.
Effort = Literal["", "none", "low", "medium", "high", "xhigh", "max"]


def _base_url(v: str) -> str:
    v = v.strip().rstrip("/")
    if v and not re.match(r"^https?://", v):
        raise ValueError("must start with http:// or https://")
    return v


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: ProviderKind
    base_url: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str = Field(min_length=1, max_length=120)
    supports_vision: bool = True
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _check_base(cls, v: str) -> str:
        return _base_url(v)


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: ProviderKind | None = None
    base_url: str | None = Field(default=None, max_length=300)
    # None keeps the stored key, "" removes it.
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, min_length=1, max_length=120)
    supports_vision: bool | None = None
    enabled: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base(cls, v: str | None) -> str | None:
        return _base_url(v) if v is not None else None


class RouteIn(BaseModel):
    provider_id: str | None = None
    model: str = Field(default="", max_length=120)
    effort: Effort = ""
    max_tokens: int | None = Field(default=None, ge=256, le=128_000)
    enabled: bool = True


class TestIn(BaseModel):
    model: str | None = Field(default=None, max_length=120)


def _provider_out(r) -> dict[str, Any]:
    d = dict(r)
    d["has_key"] = bool(d.pop("api_key_enc"))
    d["supports_vision"] = bool(d["supports_vision"])
    d["enabled"] = bool(d["enabled"])
    return d


def _get_provider(conn, provider_id: str):
    p = conn.execute("SELECT * FROM ai_providers WHERE id = ?", (provider_id,)).fetchone()
    if p is None:
        raise HTTPException(404, "Provider not found")
    return p


def _key_fields(api_key: str | None) -> dict[str, Any]:
    if api_key is None:
        return {}
    api_key = api_key.strip()
    if not api_key:
        return {"api_key_enc": None, "api_key_hint": ""}
    try:
        return {"api_key_enc": vault.encrypt(api_key), "api_key_hint": vault.hint(api_key)}
    except vault.VaultError as exc:
        raise HTTPException(500, str(exc)) from exc


# --- overview ----------------------------------------------------------------------------


@router.get("/overview")
def overview() -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with db.session() as conn:
        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        calls = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(ok = 0), 0), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)"
            " FROM ai_calls WHERE created_at >= ?",
            (since,),
        ).fetchone()
        return {
            "users": one('SELECT COUNT(*) FROM "user"'),
            "admins": one("SELECT COUNT(*) FROM \"user\" WHERE ',' || role || ',' LIKE '%,admin,%'"),
            "workspaces": one("SELECT COUNT(*) FROM businesses"),
            "crawls": one("SELECT COUNT(*) FROM crawl_runs"),
            "crawls_running": one("SELECT COUNT(*) FROM crawl_runs WHERE status IN ('queued', 'crawling', 'analyzing')"),
            "providers": one("SELECT COUNT(*) FROM ai_providers WHERE enabled = 1"),
            "alerts_24h": one("SELECT COUNT(*) FROM alerts WHERE created_at >= ?", since),
            "tools": one("SELECT COUNT(*) FROM tools WHERE removed_at IS NULL"),
            "ai_ready": {task: gateway.is_configured(task) for task in gateway.TASKS},
            "ai_24h": {"calls": calls[0], "errors": calls[1], "input_tokens": calls[2], "output_tokens": calls[3]},
        }


# --- providers ---------------------------------------------------------------------------


@router.get("/providers")
def list_providers() -> list[dict[str, Any]]:
    with db.session() as conn:
        return [_provider_out(r) for r in conn.execute("SELECT * FROM ai_providers ORDER BY created_at")]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn) -> dict[str, Any]:
    if body.kind != "openai_compatible" and not (body.api_key or "").strip():
        raise HTTPException(400, "This provider needs an API key")
    if body.kind == "openai_compatible" and not body.base_url:
        raise HTTPException(400, "An OpenAI-compatible provider needs a base URL")
    pid = new_id("aip")
    stamp = db.now()
    keys = _key_fields(body.api_key or "")
    with db.session() as conn:
        conn.execute(
            "INSERT INTO ai_providers (id, name, kind, base_url, api_key_enc, api_key_hint, default_model, supports_vision,"
            " enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, body.name.strip(), body.kind, body.base_url, keys["api_key_enc"], keys["api_key_hint"], body.default_model.strip(),
             int(body.supports_vision), int(body.enabled), stamp, stamp),
        )
        # The first provider becomes the default route so the platform works straight away.
        has_default = conn.execute("SELECT provider_id FROM ai_routes WHERE task = 'default' AND provider_id IS NOT NULL").fetchone()
        if not has_default:
            conn.execute(
                "INSERT INTO ai_routes (task, provider_id, updated_at) VALUES ('default', ?, ?)"
                " ON CONFLICT(task) DO UPDATE SET provider_id = excluded.provider_id, updated_at = excluded.updated_at",
                (pid, stamp),
            )
        return _provider_out(_get_provider(conn, pid))


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderPatch) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True, exclude={"api_key"})
    fields.update(_key_fields(body.api_key))
    for flag in ("supports_vision", "enabled"):
        if flag in fields:
            fields[flag] = int(fields[flag])
    with db.session() as conn:
        _get_provider(conn, provider_id)
    if fields:
        db.update("ai_providers", provider_id, **fields, updated_at=db.now())
    with db.session() as conn:
        return _provider_out(_get_provider(conn, provider_id))


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str) -> None:
    with db.session() as conn:
        _get_provider(conn, provider_id)
        conn.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, body: TestIn, admin: User = Depends(require_admin)) -> dict[str, Any]:
    with db.session() as conn:
        p = _get_provider(conn, provider_id)
    try:
        key = vault.decrypt(p["api_key_enc"]) if p["api_key_enc"] else ""
    except vault.VaultError as exc:
        return {"ok": False, "error": str(exc)}
    route = gateway.Route(
        task="connection_test",
        provider_id=p["id"],
        provider_name=p["name"],
        supports_vision=bool(p["supports_vision"]),
        config=ProviderConfig(kind=p["kind"], api_key=key, base_url=p["base_url"], model=body.model or p["default_model"], max_tokens=1024),
    )
    try:
        result = await gateway.run(
            "connection_test",
            system="",
            messages=[gateway.text_message("Reply with the single word: ready")],
            user_id=admin.id,
            route=route,
        )
    except ProviderError as exc:
        return {"ok": False, "error": str(exc), "model": route.config.model}
    return {"ok": True, "model": route.config.model, "reply": result.text[:200], "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}}


# --- task routing ------------------------------------------------------------------------


@router.get("/routes")
def list_routes() -> dict[str, Any]:
    with db.session() as conn:
        routes = {r["task"]: dict(r) for r in conn.execute("SELECT * FROM ai_routes")}
    for r in routes.values():
        r["enabled"] = bool(r["enabled"])
    tasks = [{"task": "default", "label": "Default", "description": "Used by every task without its own route.", "max_tokens": None}]
    tasks += [{"task": t, **meta} for t, meta in gateway.TASKS.items()]
    return {"tasks": tasks, "routes": routes}


@router.put("/routes/{task}")
def set_route(task: str, body: RouteIn) -> dict[str, Any]:
    if task != "default" and task not in gateway.TASKS:
        raise HTTPException(404, "Unknown task")
    with db.session() as conn:
        if body.provider_id:
            _get_provider(conn, body.provider_id)
        conn.execute(
            "INSERT INTO ai_routes (task, provider_id, model, effort, max_tokens, enabled, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(task) DO UPDATE SET provider_id = excluded.provider_id, model = excluded.model, effort = excluded.effort,"
            " max_tokens = excluded.max_tokens, enabled = excluded.enabled, updated_at = excluded.updated_at",
            (task, body.provider_id, body.model.strip(), body.effort, body.max_tokens, int(body.enabled), db.now()),
        )
    return list_routes()


# --- platform settings -------------------------------------------------------------------


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return settings.get_all()


@router.put("/settings")
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return settings.update(body)
    except KeyError as exc:
        raise HTTPException(400, f"Unknown setting: {exc.args[0]}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


# --- usage and workspaces ----------------------------------------------------------------


@router.get("/ai-calls")
def ai_calls(limit: int = 100, task: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    sql = (
        "SELECT c.*, u.email AS user_email, p.name AS provider_name FROM ai_calls c"
        ' LEFT JOIN "user" u ON u.id = c.user_id LEFT JOIN ai_providers p ON p.id = c.provider_id'
    )
    args: list[Any] = []
    if task:
        sql += " WHERE c.task = ?"
        args.append(task)
    sql += " ORDER BY c.id DESC LIMIT ?"
    with db.session() as conn:
        rs = db.rows(conn.execute(sql, (*args, limit)).fetchall())
    for r in rs:
        r["ok"] = bool(r["ok"])
    return rs


@router.get("/chat-quality")
def chat_quality(days: int = 7) -> dict[str, Any]:
    """How the customer chat is doing: answers, success rate, LLM calls and latency per answer, top problems."""
    from ..chat import trace

    return trace.quality(days)


@router.get("/chat-quality/{turn_id}")
def chat_turn(turn_id: str) -> dict[str, Any]:
    from ..chat import trace

    return trace.turn(turn_id)


@router.get("/workspaces")
def all_workspaces() -> list[dict[str, Any]]:
    with db.session() as conn:
        rs = conn.execute(
            "SELECT b.id, b.name, b.type, b.website_url, b.status, b.created_at, u.email AS owner_email,"
            " (SELECT status FROM crawl_runs r WHERE r.business_id = b.id ORDER BY r.id DESC LIMIT 1) AS crawl_status,"
            " (SELECT ai_status FROM crawl_runs r WHERE r.business_id = b.id ORDER BY r.id DESC LIMIT 1) AS ai_status"
            ' FROM businesses b LEFT JOIN "user" u ON u.id = b.owner_id ORDER BY b.created_at DESC'
        ).fetchall()
        return db.rows(rs)


@router.get("/mcp-servers")
def mcp_servers() -> list[dict[str, Any]]:
    """Every business's own MCP server: who owns it, whether it is published, and the tools it
    exposes (published ones, plus the ones still waiting for a check)."""
    with db.session() as conn:
        businesses = conn.execute(
            "SELECT b.id, b.name, b.type, b.category_label, b.online_only, b.status, b.accepts_orders, b.published_at, b.created_at, u.email AS owner_email,"
            " (SELECT COUNT(*) FROM calls_log c WHERE c.business_id = b.id AND c.created_at >= datetime('now', '-7 days')) AS calls_7d"
            ' FROM businesses b LEFT JOIN "user" u ON u.id = b.owner_id'
            " ORDER BY b.status = 'live' DESC, COALESCE(b.published_at, b.created_at) DESC"
        ).fetchall()
        out = []
        for b in businesses:
            published = {t["tool_id"] for t in service.published_tools(conn, b["id"])}
            tools = conn.execute(
                "SELECT t.id, t.name, t.enabled, v.title, v.badge, v.sensitivity FROM tools t"
                " LEFT JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
                " WHERE t.business_id = ? AND t.removed_at IS NULL ORDER BY t.created_at",
                (b["id"],),
            ).fetchall()
            listed = [{**dict(t), "enabled": bool(t["enabled"]), "published": t["id"] in published} for t in tools]
            if orders.available(conn, dict(b)):  # the order inbox's tools, on the server like the business's own
                listed += [{"id": f"{b['id']}:{e['name']}", "name": e["name"], "title": e["title"], "badge": e["badge"], "enabled": True, "published": True,
                            "sensitivity": "order" if e["requires_user_confirmation"] else "read_only"} for e in orders.tool_entries()]
            out.append({
                **dict(b),
                "online_only": bool(b["online_only"]),
                "accepts_orders": bool(b["accepts_orders"]),
                "server_url": business_mcp.url_for(PUBLIC_API_URL, b["id"]),
                "tools": listed,
            })
        return out


@router.get("/alerts")
def all_alerts(limit: int = 50) -> list[dict[str, Any]]:
    """Blocked and broken tools on every workspace: the platform is alerted too."""
    with db.session() as conn:
        return db.rows(conn.execute(
            "SELECT a.*, b.name AS business_name, t.name AS tool_name FROM alerts a"
            " JOIN businesses b ON b.id = a.business_id LEFT JOIN tools t ON t.id = a.tool_id"
            " ORDER BY a.created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall())
