"""Part F, the owner's side: publish the business's MCP server, see what AI assistants did, and set rules for tools."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, current_user
from ..config import PUBLIC_API_URL, is_public
from ..gateway import business_mcp, search_index, service, signing
from ..registry.rules import inputs_from_schema
from .workspaces import _owned

router = APIRouter(prefix="/api/workspaces/{business_id}", tags=["live"])


class PublishIn(BaseModel):
    live: bool


class RuleIn(BaseModel):
    input: str = Field(min_length=1, max_length=60)
    kind: Literal["max", "min"]
    value: float
    message: str = Field(default="", max_length=300)


@router.post("/publish")
def publish(business_id: str, body: PublishIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        b = _owned(conn, business_id, user)
        if body.live and not b["online_only"] and (b["lat"] is None or b["lng"] is None):
            raise HTTPException(400, "Add your map location under Edit details first, so assistants can find you nearby (or mark the business as online only).")
        if body.live and not service.published_tools(conn, business_id):
            raise HTTPException(400, "No tool has passed its checks yet. Approve your tools and run their checks first, then publish.")
    if body.live:
        signing.ensure_key(business_id)
    db.update("businesses", business_id, status="live" if body.live else "draft", published_at=db.now() if body.live else None, updated_at=db.now())
    search_index.schedule(business_id)  # found by meaning once live; forgotten once not
    return live(business_id, user)


@router.get("/live")
def live(business_id: str, user: User = Depends(current_user)) -> dict:
    """Everything about how AI assistants see this business."""
    with db.session() as conn:
        b = _owned(conn, business_id, user)
        published = {t["tool_id"]: t for t in service.published_tools(conn, business_id)}
        tools = conn.execute(
            "SELECT t.id, t.name, t.enabled, v.title, v.badge, v.verified FROM tools t LEFT JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
            " WHERE t.business_id = ? AND t.removed_at IS NULL ORDER BY t.created_at",
            (business_id,),
        ).fetchall()
        calls = db.rows(conn.execute("SELECT * FROM calls_log WHERE business_id = ? ORDER BY id DESC LIMIT 30", (business_id,)).fetchall(), ("inputs",))
        demand = db.rows(conn.execute(
            "SELECT keyword, COUNT(*) AS n FROM demand_log WHERE business_id = ? AND created_at >= datetime('now', '-7 days') GROUP BY keyword ORDER BY n DESC LIMIT 10",
            (business_id,),
        ).fetchall())
        stats = conn.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(outcome = 'ok'), 0) AS ok FROM calls_log WHERE business_id = ? AND created_at >= datetime('now', '-7 days')",
            (business_id,),
        ).fetchone()

    def why_not(t) -> str:
        if not t["enabled"]:
            return "Switched off"
        if t["badge"] not in ("safe_working", "sensitive"):
            return {"untested": "Needs a test run", "not_working": "Not working", "blocked": "Blocked"}.get(t["badge"], "Not checked yet")
        return "Needs a real test run" if not t["verified"] else ""

    return {
        "status": b["status"],
        "published_at": b["published_at"],
        "mcp_url": f"{PUBLIC_API_URL}/mcp",
        # The business's own MCP server: its tools directly, served while the business is live.
        "server_url": business_mcp.url_for(PUBLIC_API_URL, business_id),
        # False while the address is localhost: ChatGPT and Claude can't reach it from their servers.
        "public": is_public(),
        "public_key": b["public_key"],
        "tools": [{"id": t["id"], "name": t["name"], "title": t["title"], "published": t["id"] in published, "reason": "" if t["id"] in published else why_not(t)} for t in tools],
        "activity": calls,
        "demand": demand,
        "stats_7d": {"calls": stats["calls"], "ok": stats["ok"]},
    }


@router.get("/tools/{tool_id}/rules")
def list_rules(business_id: str, tool_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        return db.rows(conn.execute("SELECT * FROM owner_rules WHERE business_id = ? AND tool_id = ? ORDER BY id", (business_id, tool_id)).fetchall())


@router.post("/tools/{tool_id}/rules", status_code=201)
def add_rule(business_id: str, tool_id: str, body: RuleIn, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        v = conn.execute(
            "SELECT v.input_schema FROM tools t JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version WHERE t.id = ? AND t.business_id = ?",
            (tool_id, business_id),
        ).fetchone()
        if v is None:
            raise HTTPException(404, "Tool not found")
        numeric = {i["name"] for i in inputs_from_schema(json.loads(v["input_schema"])) if i["type"] in ("integer", "number")}
        if body.input not in numeric:
            raise HTTPException(400, f"Rules work on number inputs: {', '.join(sorted(numeric)) or 'this tool has none'}.")
        conn.execute(
            "INSERT INTO owner_rules (business_id, tool_id, input, kind, value, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (business_id, tool_id, body.input, body.kind, body.value, body.message.strip(), db.now()),
        )
    return list_rules(business_id, tool_id, user)


@router.delete("/tools/{tool_id}/rules/{rule_id}", status_code=204)
def delete_rule(business_id: str, tool_id: str, rule_id: int, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _owned(conn, business_id, user)
        conn.execute("DELETE FROM owner_rules WHERE id = ? AND business_id = ? AND tool_id = ?", (rule_id, business_id, tool_id))
