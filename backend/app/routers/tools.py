"""Part D: the owner's tool list, its versions, and proposals to change it."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, current_user
from ..checks import pipeline, worker
from ..registry import propose, rules, store
from .workspaces import _owned

router = APIRouter(prefix="/api/workspaces/{business_id}", tags=["tools"])


class ProposeIn(BaseModel):
    source: Literal["crawl", "recording"]
    source_id: str = Field(min_length=1, max_length=80)


class Decision(BaseModel):
    index: int
    decision: Literal["approve", "reject"]
    resolution: Literal["separate", "new_version"] | None = None
    rename_to: str | None = Field(default=None, max_length=60)
    target_tool_id: str | None = None


class DecideIn(BaseModel):
    decisions: list[Decision] = Field(min_length=1, max_length=100)


class ToolPatch(BaseModel):
    enabled: bool


class UseIn(BaseModel):
    version: int


class CheckIn(BaseModel):
    live: bool = False          # run the tool for real once (it may really book, order or send)
    confirm: bool = False       # the owner has read that this really happens on their site
    inputs: dict[str, str | int | float | bool] | None = None


def _check_out(c) -> dict | None:
    if c is None:
        return None
    d = dict(c)
    d["security"] = json.loads(d["security"])
    d["test"] = json.loads(d["test"]) if d["test"] else None
    d["inputs"] = json.loads(d["inputs"]) if d["inputs"] else None
    d["verified"] = bool(d["verified"])
    return d


def _version_out(v, conn=None) -> dict:
    d = dict(v)
    d["verified"] = bool(d.get("verified"))
    if conn is not None:
        d["latest_check"] = _check_out(conn.execute("SELECT * FROM tool_checks WHERE version_id = ? ORDER BY created_at DESC LIMIT 1", (v["id"],)).fetchone())
    d["input_schema"] = json.loads(d["input_schema"])
    d["runner"] = json.loads(d["runner"])
    d["inputs"] = rules.inputs_from_schema(d["input_schema"])
    d["runner_summary"] = rules.describe_runner(d["runner"])
    return d


def _tool_out(conn, t, with_versions: bool = False) -> dict:
    versions = [_version_out(v, conn) for v in conn.execute("SELECT * FROM tool_versions WHERE tool_id = ? ORDER BY version DESC", (t["id"],)).fetchall()]
    current = next((v for v in versions if v["version"] == t["current_version"]), None)
    out = {
        "id": t["id"],
        "name": t["name"],
        "enabled": bool(t["enabled"]),
        "current_version": t["current_version"],
        "latest_version": versions[0]["version"] if versions else None,
        "versions_count": len(versions),
        "current": current,
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
    }
    # A newer version than the one in use is waiting for the checks or the owner.
    out["waiting_version"] = out["latest_version"] if current and out["latest_version"] > current["version"] else None
    out["checking"] = conn.execute("SELECT 1 FROM tool_checks WHERE tool_id = ? AND status IN ('queued', 'running')", (t["id"],)).fetchone() is not None
    out["sample_inputs"] = pipeline.sample_inputs(current["input_schema"]) if current else {}
    if with_versions:
        out["versions"] = versions
    return out


def _proposal_out(p) -> dict:
    d = dict(p)
    d["items"] = json.loads(d["items"])
    return d


@router.get("/tools")
def list_tools(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        ts = conn.execute("SELECT * FROM tools WHERE business_id = ? AND removed_at IS NULL ORDER BY created_at", (business_id,)).fetchall()
        return [_tool_out(conn, t) for t in ts]


@router.get("/tools/{tool_id}")
def get_tool(business_id: str, tool_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        t = conn.execute("SELECT * FROM tools WHERE id = ? AND business_id = ? AND removed_at IS NULL", (tool_id, business_id)).fetchone()
        if t is None:
            raise HTTPException(404, "Tool not found")
        return _tool_out(conn, t, with_versions=True)


@router.patch("/tools/{tool_id}")
def switch_tool(business_id: str, tool_id: str, body: ToolPatch, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        cur = conn.execute(
            "UPDATE tools SET enabled = ?, updated_at = ? WHERE id = ? AND business_id = ? AND removed_at IS NULL",
            (int(body.enabled), db.now(), tool_id, business_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Tool not found")
    return get_tool(business_id, tool_id, user)


@router.post("/tools/{tool_id}/use")
def use_version(business_id: str, tool_id: str, body: UseIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
    try:
        store.use_version(business_id, tool_id, body.version)
    except store.DecisionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return get_tool(business_id, tool_id, user)


@router.delete("/tools/{tool_id}", status_code=204)
def remove_tool(business_id: str, tool_id: str, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _owned(conn, business_id, user)
    try:
        store.remove_tool(business_id, tool_id)
    except store.DecisionError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/proposals")
def list_proposals(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        ps = conn.execute("SELECT * FROM proposals WHERE business_id = ? ORDER BY created_at DESC LIMIT 50", (business_id,)).fetchall()
    return [_proposal_out(p) for p in ps]


@router.post("/proposals", status_code=201)
def create_proposal(business_id: str, body: ProposeIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        busy = conn.execute(
            "SELECT 1 FROM proposals WHERE business_id = ? AND source = ? AND source_id = ? AND status IN ('generating', 'pending')",
            (business_id, body.source, body.source_id),
        ).fetchone()
        if busy:
            raise HTTPException(409, "There is already an open proposal for this. Review or dismiss it first.")
        if body.source == "recording":
            rec = conn.execute("SELECT status FROM recordings WHERE id = ? AND business_id = ?", (body.source_id, business_id)).fetchone()
            if rec is None or rec["status"] != "finished":
                raise HTTPException(400, "Only a finished recording can become a tool")
    if body.source == "crawl":
        try:
            prop_id = propose.from_crawl(business_id, int(body.source_id), user.id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        prop_id = propose.start_from_recording(business_id, body.source_id, user.id)
    return get_proposal(business_id, prop_id, user)


@router.get("/proposals/{prop_id}")
def get_proposal(business_id: str, prop_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        p = conn.execute("SELECT * FROM proposals WHERE id = ? AND business_id = ?", (prop_id, business_id)).fetchone()
        if p is None:
            raise HTTPException(404, "Proposal not found")
    return _proposal_out(p)


@router.post("/proposals/{prop_id}/decide")
def decide(business_id: str, prop_id: str, body: DecideIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
    try:
        created = store.decide(business_id, prop_id, [d.model_dump() for d in body.decisions])
    except store.DecisionError as exc:
        raise HTTPException(400, str(exc)) from exc
    for tool_id, version in created:  # every change is checked straight away
        worker.enqueue_for(tool_id, version, "change")
    return get_proposal(business_id, prop_id, user)


@router.post("/proposals/{prop_id}/dismiss")
def dismiss(business_id: str, prop_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        cur = conn.execute(
            "UPDATE proposals SET status = 'dismissed', decided_at = ? WHERE id = ? AND business_id = ? AND status IN ('pending', 'failed')",
            (db.now(), prop_id, business_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "Only a proposal waiting for a decision can be dismissed")
    return get_proposal(business_id, prop_id, user)


@router.post("/tools/{tool_id}/versions/{version}/check", status_code=202)
def run_check(business_id: str, tool_id: str, version: int, body: CheckIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        v = conn.execute(
            "SELECT v.id FROM tool_versions v JOIN tools t ON t.id = v.tool_id"
            " WHERE t.id = ? AND t.business_id = ? AND t.removed_at IS NULL AND v.version = ?",
            (tool_id, business_id, version),
        ).fetchone()
        if v is None:
            raise HTTPException(404, "Version not found")
        if conn.execute("SELECT 1 FROM tool_checks WHERE version_id = ? AND status IN ('queued', 'running')", (v["id"],)).fetchone():
            raise HTTPException(409, "This version is being checked already")
    if body.live and not body.confirm:
        raise HTTPException(400, "A real test really happens on your site (a booking, order or message). Confirm that you will undo it.")
    check_id = worker.enqueue(v["id"], "live_test" if body.live else "owner", mode="live" if body.live else "auto", inputs=body.inputs)
    return {"check_id": check_id}


@router.get("/checks/{check_id}")
def get_check(business_id: str, check_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        c = conn.execute(
            "SELECT c.* FROM tool_checks c JOIN tools t ON t.id = c.tool_id WHERE c.id = ? AND t.business_id = ?", (check_id, business_id)
        ).fetchone()
        if c is None:
            raise HTTPException(404, "Check not found")
        return _check_out(c)


@router.get("/alerts")
def list_alerts(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        return db.rows(conn.execute(
            "SELECT a.*, t.name AS tool_name FROM alerts a LEFT JOIN tools t ON t.id = a.tool_id"
            " WHERE a.business_id = ? AND a.seen_at IS NULL ORDER BY a.created_at DESC LIMIT 20",
            (business_id,),
        ).fetchall())


@router.post("/alerts/seen", status_code=204)
def alerts_seen(business_id: str, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _owned(conn, business_id, user)
        conn.execute("UPDATE alerts SET seen_at = ? WHERE business_id = ? AND seen_at IS NULL", (db.now(), business_id))
