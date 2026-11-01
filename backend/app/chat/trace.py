"""What happened in each customer-chat answer, for Admin -> Chat quality: the tools called (and
whether they worked), each nudge or forced step, repaired model answers, the claim guard, and how
the answer ended, with timings. No message text is stored, only what the agent did."""

import json
import logging
import time
from typing import Any

from .. import db
from ..ids import new_id

log = logging.getLogger("agentready.chat")

# Kinds of events. turn_end carries the outcome: reply | confirm | fallback | too_slow | error.
PROBLEMS = ("nudge", "forced", "bad_args", "unknown_tool", "repeat", "repair", "retry", "deadline", "claim_guard", "links_removed",
            "fallback", "error", "tool_failed")


class Trace:
    def __init__(self, language: str = "", record: bool = True) -> None:
        self.turn_id = new_id("trn")
        self.language = language
        self.record = record
        self.started = time.monotonic()
        self.step = 0
        self.ended = False

    def ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def event(self, what: str, /, **detail: Any) -> None:
        if not self.record:
            return
        try:
            with db.session() as conn:
                conn.execute("INSERT INTO chat_events (turn_id, kind, detail, ms, created_at) VALUES (?, ?, ?, ?, ?)",
                             (self.turn_id, what, json.dumps(detail, ensure_ascii=False, default=str), self.ms(), db.now()))
        except Exception:  # noqa: BLE001 - tracing must never break an answer
            log.exception("chat trace failed")

    def end(self, outcome: str, **detail: Any) -> None:
        if not self.ended:
            self.ended = True
            self.event("turn_end", outcome=outcome, steps=self.step, language=self.language, **detail)


NO_TRACE = Trace(record=False)


def _pct(values: list[int], p: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))]


def quality(days: int = 7) -> dict[str, Any]:
    """Success rate, LLM calls and steps per answer, latency, and the most common problems."""
    since = f"-{max(1, min(days, 90))} days"
    with db.session() as conn:
        ends = [dict(r) for r in conn.execute(
            "SELECT turn_id, detail, ms, created_at FROM chat_events WHERE kind = 'turn_end' AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) "
            "ORDER BY id DESC", (since,))]
        problems = conn.execute(
            f"SELECT kind, detail FROM chat_events WHERE kind IN ({','.join('?' * len(PROBLEMS))}) "
            "AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
            (*PROBLEMS, since)).fetchall()
        calls = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(ok = 0), 0) AS failed FROM ai_calls WHERE turn_id IS NOT NULL "
                             "AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)", (since,)).fetchone()
        tools = conn.execute(
            "SELECT json_extract(detail, '$.tool') AS tool, COUNT(*) AS n, SUM(json_extract(detail, '$.ok') = 0) AS failed "
            "FROM chat_events WHERE kind = 'tool' AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) GROUP BY tool ORDER BY n DESC", (since,)).fetchall()
        recent_ids = [e["turn_id"] for e in ends[:30]]
        used: dict[str, list[str]] = {}
        if recent_ids:
            for r in conn.execute("SELECT turn_id, json_extract(detail, '$.tool') AS tool FROM chat_events WHERE kind = 'tool' "
                                  f"AND turn_id IN ({','.join('?' * len(recent_ids))}) ORDER BY id", recent_ids):
                used.setdefault(r["turn_id"], []).append(r["tool"])
    for e in ends:
        e["detail"] = json.loads(e["detail"] or "{}")
    outcomes: dict[str, int] = {}
    for e in ends:
        outcomes[e["detail"].get("outcome", "?")] = outcomes.get(e["detail"].get("outcome", "?"), 0) + 1
    kinds: dict[str, int] = {}
    for p in problems:
        detail = json.loads(p["detail"] or "{}")
        label = p["kind"] + (f": {detail['kind']}" if p["kind"] in ("nudge", "forced") and detail.get("kind") else "")
        kinds[label] = kinds.get(label, 0) + 1
    n = len(ends)
    good = outcomes.get("reply", 0) + outcomes.get("confirm", 0)
    latencies = [e["ms"] for e in ends if e["ms"] is not None]
    return {
        "days": days,
        "turns": n,
        "success_rate": round(good / n, 3) if n else None,
        "outcomes": outcomes,
        "llm_calls_per_turn": round(calls["n"] / n, 2) if n else None,
        "llm_calls_failed": calls["failed"],
        "steps_per_turn": round(sum(e["detail"].get("steps", 0) for e in ends) / n, 2) if n else None,
        "latency_ms": {"p50": _pct(latencies, 0.5), "p95": _pct(latencies, 0.95)},
        "problems": sorted(({"kind": k, "count": c} for k, c in kinds.items()), key=lambda x: -x["count"]),
        "tools": [{"tool": r["tool"], "calls": r["n"], "failed": r["failed"] or 0} for r in tools],
        "recent": [{"turn_id": e["turn_id"], "created_at": e["created_at"], "ms": e["ms"], "outcome": e["detail"].get("outcome"),
                    "language": e["detail"].get("language", ""), "steps": e["detail"].get("steps", 0), "tools": used.get(e["turn_id"], [])}
                   for e in ends[:30]],
    }


def turn(turn_id: str) -> dict[str, Any]:
    """Every event and model call of one answer, in order."""
    with db.session() as conn:
        events = [dict(r) for r in conn.execute("SELECT kind, detail, ms, created_at FROM chat_events WHERE turn_id = ? ORDER BY id", (turn_id,))]
        llm = [dict(r) for r in conn.execute(
            "SELECT step, model, ok, error, input_tokens, output_tokens, latency_ms, created_at FROM ai_calls WHERE turn_id = ? ORDER BY id",
            (turn_id,))]
    for e in events:
        e["detail"] = json.loads(e["detail"] or "{}")
    return {"turn_id": turn_id, "events": events, "llm_calls": llm}
