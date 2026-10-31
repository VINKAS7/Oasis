"""Part D: the only code that writes tools and versions.

- A new tool starts at version 1 and is in use straight away (there is nothing older).
- An update is a new version; the version in use stays until the new one passes the checks
  (Part E), or the owner switches versions themselves.
- Nothing here removes a tool on a proposal's behalf; only remove_tool(), called by the owner.
"""

import json
import re
from typing import Any

from .. import db
from ..ids import new_id
from ..recorder.clean import snake
from . import rules


class DecisionError(ValueError):
    pass


def _versions(conn, tool_id: str) -> int:
    return conn.execute("SELECT COALESCE(MAX(version), 0) FROM tool_versions WHERE tool_id = ?", (tool_id,)).fetchone()[0]


def _add_version(conn, tool_id: str, tool: dict[str, Any], created_from: str, proposal_id: str | None, reason: str) -> int:
    version = _versions(conn, tool_id) + 1
    conn.execute(
        "INSERT INTO tool_versions (id, tool_id, version, title, description_for_ai, description_for_owner, input_schema, runner,"
        " sensitivity, created_from, proposal_id, reason, content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_id("tv"), tool_id, version, tool["title"], tool["description_for_ai"], tool["description_for_owner"],
            json.dumps(tool["input_schema"]), json.dumps(tool["runner"]), tool["sensitivity"], created_from, proposal_id,
            reason, rules.content_hash(tool), db.now(),
        ),
    )
    conn.execute("UPDATE tools SET updated_at = ? WHERE id = ?", (db.now(), tool_id))
    return version


def _live_tool(conn, business_id: str, tool_id: str):
    t = conn.execute("SELECT * FROM tools WHERE id = ? AND business_id = ? AND removed_at IS NULL", (tool_id, business_id)).fetchone()
    if t is None:
        raise DecisionError("That tool no longer exists")
    return t


def _name_taken(conn, business_id: str, name: str) -> bool:
    return conn.execute("SELECT 1 FROM tools WHERE business_id = ? AND name = ? AND removed_at IS NULL", (business_id, name)).fetchone() is not None


def _apply_item(conn, prop, item: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
    business_id = prop["business_id"]
    created_from = f"{prop['source']}:{prop['source_id']}"
    if any(f["kind"] == "blocked" for f in item["flags"]):
        raise DecisionError(f"{item['tool_name']} breaks a platform rule and can't be approved as it is")
    tool = dict(item["tool"])
    action = item["action"]
    target_id = item.get("target_tool_id")

    if any(f["kind"] == "conflict" for f in item["flags"]):
        resolution = d.get("resolution")
        if resolution == "new_version":
            target_id = d.get("target_tool_id") or next(f["tool_id"] for f in item["flags"] if f["kind"] == "conflict")
            action = "update"
        elif resolution == "separate":
            tool["name"] = d.get("rename_to") or tool["name"]
            action = "add"
        else:
            raise DecisionError(f"{item['tool_name']} clashes with an existing tool: keep it separate or make it a new version")

    if action == "add":
        tool["name"] = snake(tool["name"])
        if not re.match(r"^[a-z][a-z0-9_]{1,59}$", tool["name"]):
            raise DecisionError("Tool names use lowercase letters, digits and underscores, starting with a letter")
        if _name_taken(conn, business_id, tool["name"]):
            raise DecisionError(f"A tool called {tool['name']} already exists; choose another name")
        tool_id = new_id("tool")
        stamp = db.now()
        conn.execute(
            "INSERT INTO tools (id, business_id, name, enabled, current_version, created_at, updated_at) VALUES (?, ?, ?, 1, NULL, ?, ?)",
            (tool_id, business_id, tool["name"], stamp, stamp),
        )
        version = _add_version(conn, tool_id, tool, created_from, prop["id"], item["reason"])
        conn.execute("UPDATE tools SET current_version = ? WHERE id = ?", (version, tool_id))
        return {"tool_id": tool_id, "version": version, "in_use": True}

    t = _live_tool(conn, business_id, target_id)
    version = _add_version(conn, t["id"], {**tool, "name": t["name"]}, created_from, prop["id"], item["reason"])
    if t["current_version"] is None:
        conn.execute("UPDATE tools SET current_version = ? WHERE id = ?", (version, t["id"]))
        return {"tool_id": t["id"], "version": version, "in_use": True}
    return {"tool_id": t["id"], "version": version, "in_use": False}


def decide(business_id: str, prop_id: str, decisions: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Apply the owner's decisions. Returns the (tool id, version) of every new version, to be checked."""
    created: list[tuple[str, int]] = []
    with db.session() as conn:
        prop = conn.execute("SELECT * FROM proposals WHERE id = ? AND business_id = ?", (prop_id, business_id)).fetchone()
        if prop is None:
            raise DecisionError("Proposal not found")
        if prop["status"] != "pending":
            raise DecisionError("This proposal is not waiting for a decision")
        items = json.loads(prop["items"])
        for d in decisions:
            idx = d.get("index")
            if not isinstance(idx, int) or not 0 <= idx < len(items):
                raise DecisionError("Unknown item in the proposal")
            item = items[idx]
            if item["decision"] is not None:
                continue
            if d.get("decision") == "reject":
                item["decision"] = "rejected"
            elif d.get("decision") == "approve":
                item["result"] = _apply_item(conn, prop, item, d)
                item["decision"] = "approved"
                created.append((item["result"]["tool_id"], item["result"]["version"]))
            else:
                raise DecisionError("Each decision is approve or reject")
        done = all(i["decision"] is not None for i in items)
        conn.execute(
            "UPDATE proposals SET items = ?, status = ?, decided_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), "applied" if done else "pending", db.now() if done else None, prop_id),
        )
    return created


def use_version(business_id: str, tool_id: str, version: int) -> None:
    """The owner's switch: roll back (or forward) to any saved version."""
    with db.session() as conn:
        _live_tool(conn, business_id, tool_id)
        if not conn.execute("SELECT 1 FROM tool_versions WHERE tool_id = ? AND version = ?", (tool_id, version)).fetchone():
            raise DecisionError("No such version")
        conn.execute("UPDATE tools SET current_version = ?, updated_at = ? WHERE id = ?", (version, db.now(), tool_id))


def remove_tool(business_id: str, tool_id: str) -> None:
    """Only the owner removes a tool. Its versions stay in the history."""
    with db.session() as conn:
        _live_tool(conn, business_id, tool_id)
        conn.execute("UPDATE tools SET removed_at = ?, enabled = 0, updated_at = ? WHERE id = ?", (db.now(), db.now(), tool_id))
