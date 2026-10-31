"""Part E, step 4: keep checking. One background thread runs checks one at a time (the test
runs may start a browser), after every change and once a day for every tool in use."""

import asyncio
import json
import logging
import queue
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from ..ids import new_id
from . import pipeline

log = logging.getLogger("agentready.checks")

DAILY = timedelta(hours=24)
SCHEDULE_EVERY_S = 600

_queue: "queue.Queue[str]" = queue.Queue()
_started = False
_lock = threading.Lock()


def enqueue(version_id: str, trigger: str, mode: str = "auto", inputs: dict[str, Any] | None = None) -> str:
    with db.session() as conn:
        v = conn.execute("SELECT tool_id, version FROM tool_versions WHERE id = ?", (version_id,)).fetchone()
        check_id = new_id("chk")
        conn.execute(
            "INSERT INTO tool_checks (id, tool_id, version_id, version, trigger, mode, inputs, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (check_id, v["tool_id"], version_id, v["version"], trigger, mode, json.dumps(inputs) if inputs else None, db.now()),
        )
    _queue.put(check_id)
    return check_id


def enqueue_for(tool_id: str, version: int, trigger: str) -> str:
    with db.session() as conn:
        v = conn.execute("SELECT id FROM tool_versions WHERE tool_id = ? AND version = ?", (tool_id, version)).fetchone()
    return enqueue(v["id"], trigger)


def schedule_due() -> int:
    """Queue a daily re-check for every version in use or waiting, if its last check is old."""
    cutoff = (datetime.now(timezone.utc) - DAILY).isoformat(timespec="seconds")
    with db.session() as conn:
        due = conn.execute(
            "SELECT v.id FROM tool_versions v JOIN tools t ON t.id = v.tool_id"
            " WHERE t.removed_at IS NULL AND v.version >= COALESCE(t.current_version, 0)"
            " AND (v.checked_at IS NULL OR v.checked_at < ?)"
            " AND NOT EXISTS (SELECT 1 FROM tool_checks c WHERE c.version_id = v.id AND c.status IN ('queued', 'running'))",
            (cutoff,),
        ).fetchall()
    for r in due:
        enqueue(r["id"], "daily")
    return len(due)


def _loop() -> None:
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    last_schedule = 0.0
    while True:
        try:
            check_id = _queue.get(timeout=30)
        except queue.Empty:
            check_id = None
        if check_id:
            loop.run_until_complete(pipeline.run_check(check_id))
        if time.monotonic() - last_schedule > SCHEDULE_EVERY_S:
            last_schedule = time.monotonic()
            try:
                schedule_due()
            except Exception:  # never let the scheduler kill the worker
                log.exception("scheduling daily checks failed")


def start() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    with db.session() as conn:
        waiting = [r["id"] for r in conn.execute("SELECT id FROM tool_checks WHERE status = 'queued' ORDER BY created_at")]
    for check_id in waiting:
        _queue.put(check_id)
    threading.Thread(target=_loop, name="tool-checks", daemon=True).start()
