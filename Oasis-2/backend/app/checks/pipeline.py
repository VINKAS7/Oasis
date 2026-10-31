"""Part E: one check of one tool version, start to finish.

1. Security checks (security.py). Any failure: badge "blocked".
2. A test run with sample inputs, in the safest mode available:
   - read-only tools run for real;
   - tools that book or change something run against the business's test copy if it has
     one, or book and then cancel straight away with the business's cancel tool, or make one
     real run when the owner asked for it; otherwise a dry run (everything except the
     final submit), which earns "needs a test run", never a pass.
3. A prompt-injection scan of what came back (injection.py).
4. The badge, the owner's message, alerts, and promotion of a passing new version.
"""

import json
import logging
from datetime import date, timedelta
from typing import Any

from .. import db, settings
from ..recorder.clean import MASK
from ..registry.rules import inputs_from_schema
from ..runner import engine
from . import injection, security

log = logging.getLogger("agentready.checks")

GOOD = {"safe_working", "sensitive"}
IDS = ("id", "booking_id", "reservation_id", "order_id", "appointment_id", "reference")
MODE_TEXT = {
    "real": "Ran for real (it only reads information).",
    "staging": "Ran against your test copy of your system.",
    "live_then_cancel": "Ran it for real and undid it straight away with your cancel tool.",
    "live_owner": "Ran it for real once, as you asked. Undo it in your own system if needed (cancel the booking or order).",
    "dry": "Dry run: prepared everything but did not send the final step, so nothing happened on your site.",
    "security_only": "Daily re-check of the security rules; the last test run still stands.",
}


def next_weekday(weekday: int = 4) -> str:
    """The coming Friday (or other weekday), at least two days away."""
    d = date.today() + timedelta(days=2)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


def sample_inputs(schema: dict[str, Any]) -> dict[str, Any]:
    """Believable test values, like "2 people, next Friday, 19:00"."""
    out: dict[str, Any] = {}
    for i in inputs_from_schema(schema):
        n, t = i["name"].lower(), i["type"]
        if t == "date" or "date" in n or "day" in n:
            out[i["name"]] = next_weekday()
        elif t == "time" or "time" in n or "hour" in n:
            out[i["name"]] = "19:00"
        elif t in ("integer", "number") or any(k in n for k in ("people", "guests", "persons", "party", "covers", "count", "number")):
            out[i["name"]] = 2 if t in ("integer", "number") else "2"
        elif t == "boolean":
            out[i["name"]] = False
        elif "mail" in n:
            out[i["name"]] = "test+agentready@example.com"
        elif any(k in n for k in ("phone", "tel", "mobile")):
            out[i["name"]] = "+41 00 000 00 00"
        elif "name" in n or i["personal"]:
            out[i["name"]] = "AgentReady Test"
        else:
            out[i["name"]] = "test"
    return out


def _writes(runner: dict[str, Any]) -> bool:
    if runner.get("kind") == "http_request":
        return (runner.get("method") or "GET") != "GET"
    if runner.get("kind") == "browser_replay":
        return any(s.get("type") in ("click", "submit", "press") for s in runner.get("steps", []))
    return False


def _cancel_tool(conn, business_id: str, tool_id: str):
    for t in conn.execute("SELECT * FROM tools WHERE business_id = ? AND removed_at IS NULL AND id != ? AND name LIKE 'cancel%'", (business_id, tool_id)):
        v = conn.execute("SELECT * FROM tool_versions WHERE tool_id = ? AND version = ?", (t["id"], t["current_version"])).fetchone()
        if v is not None and v["badge"] != "blocked":
            return t, v
    return None


def _cancel_inputs(schema: dict[str, Any], booked: Any, inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Fill the cancel tool from the first answer (its id) and the first call's own inputs."""
    output = booked if isinstance(booked, dict) else {}
    values: dict[str, Any] = {}
    for i in inputs_from_schema(schema):
        n = i["name"]
        if n in output:
            values[n] = output[n]
        elif (n.endswith("_id") or n in ("id", "booking", "reservation", "order", "appointment")) and any(k in output for k in IDS):
            values[n] = next(output[k] for k in IDS if k in output)
        elif n in inputs:
            values[n] = inputs[n]
        elif i["required"]:
            return None
    return values


def _owner_message(badge: str, title: str, result: engine.RunResult | None, findings: list[dict[str, Any]], scan: dict[str, Any] | None) -> str:
    if badge == "blocked":
        if scan and scan.get("suspicious"):
            return f"What “{title}” returns contains text aimed at AI assistants. Check the page it reads; the tool stays unpublished."
        failed = [f["message"] for f in findings if not f["ok"]]
        return f"“{title}” broke a security rule and will not be published: {' '.join(failed)}"
    if badge == "not_working" and result is not None:
        if result.failed_step:
            return f"Step {result.failed_step} of “{title}” no longer works on your website. Please re-record step {result.failed_step}."
        return f"“{title}” did not work: {result.message} Please re-record it or check your website."
    if badge == "untested":
        return f"“{title}” passed the security checks. Run a real test to publish it."
    return ""


def _alert(conn, business_id: str, tool_id: str, version: int, level: str, message: str) -> None:
    conn.execute(
        "INSERT INTO alerts (business_id, tool_id, version, level, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (business_id, tool_id, version, level, message, db.now()),
    )


def _jsonable(value: Any, limit: int = 4000) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= limit else text[:limit] + " [cut]"


async def run_check(check_id: str) -> None:
    with db.session() as conn:
        chk = conn.execute("SELECT * FROM tool_checks WHERE id = ?", (check_id,)).fetchone()
        if chk is None or chk["status"] != "queued":
            return
        v = conn.execute("SELECT * FROM tool_versions WHERE id = ?", (chk["version_id"],)).fetchone()
        tool = conn.execute("SELECT * FROM tools WHERE id = ?", (chk["tool_id"],)).fetchone()
        business = dict(conn.execute("SELECT * FROM businesses WHERE id = ?", (tool["business_id"],)).fetchone())
        conn.execute("UPDATE tool_checks SET status = 'running' WHERE id = ?", (check_id,))
    try:
        await _run(chk, dict(v), dict(tool), business)
    except Exception as exc:  # recorded on the check, so the owner sees it
        log.exception("check %s failed", check_id)
        db.update("tool_checks", check_id, status="error", error=str(exc)[:400] or exc.__class__.__name__, finished_at=db.now())


async def _run(chk, v: dict[str, Any], tool: dict[str, Any], business: dict[str, Any]) -> None:
    version = {
        "runner": json.loads(v["runner"]),
        "input_schema": json.loads(v["input_schema"]),
        "sensitivity": v["sensitivity"],
        "created_from": v["created_from"],
    }
    allow_private = settings.get("crawler.allow_private_urls")
    findings, limit = security.check(version, business, allow_private)
    sensitivity = next(f["value"] for f in findings if f["rule"] == "sensitivity")
    result: engine.RunResult | None = None
    scan: dict[str, Any] | None = None
    test: dict[str, Any] | None = None
    badge, verified = "blocked", False

    if security.passed(findings):
        writes = _writes(version["runner"])
        with db.session() as conn:
            cancel = _cancel_tool(conn, business["id"], tool["id"]) if writes else None
        if not writes:
            mode = "real"
        elif chk["mode"] == "live":
            mode = "live_owner"
        elif business.get("test_url"):
            mode = "staging"
        elif chk["trigger"] == "daily":
            mode = "security_only"  # never book for real on a schedule
        elif cancel is not None:
            mode = "live_then_cancel"
        else:
            mode = "dry"

        inputs = {**sample_inputs(version["input_schema"]), **json.loads(chk["inputs"] or "{}")}
        ctx = engine.Context(
            site=business["website_url"],
            allowed_hosts=security.allowed_hosts(business, v["created_from"]),
            allow_private=allow_private,
            business=business,
            base_override=business.get("test_url", "") if mode == "staging" else "",
        )
        cancelled = None
        if mode == "security_only":
            # The last real test result stands; only the security rules were re-checked.
            badge, verified = (v["badge"], bool(v["verified"])) if v["badge"] != "unchecked" else ("untested", False)
            test = {"mode": mode, "mode_text": MODE_TEXT[mode], "ok": True, "message": "Security rules still pass."}
        else:
            run_tool = engine.Tool(tool["name"], version["runner"], version["input_schema"])
            try:
                result = await engine.run(run_tool, ctx, inputs, dry=mode == "dry")
            except (engine.InputError, engine.NotAllowed) as exc:
                result = engine.RunResult(False, str(exc))
            if mode == "live_then_cancel" and result.ok and cancel is not None:
                ct, cv = cancel
                schema = json.loads(cv["input_schema"])
                values = _cancel_inputs(schema, result.output, inputs)
                if values is None:
                    cancelled = {"ok": False, "message": f"Could not tell {ct['name']} what to cancel. Please undo the test yourself."}
                else:
                    try:
                        c = await engine.run(engine.Tool(ct["name"], json.loads(cv["runner"]), schema), ctx, values)
                        cancelled = {"ok": c.ok, "message": f"Cancelled with {ct['name']}." if c.ok else f"{ct['name']} failed: {c.message} Please undo the test yourself."}
                    except (engine.InputError, engine.NotAllowed) as exc:
                        cancelled = {"ok": False, "message": f"{ct['name']} could not run: {exc}. Please undo the test yourself."}
            scan = await injection.scan(result.text, business["id"]) if result.text else None
            if scan and scan["suspicious"]:
                badge = "blocked"
            elif not result.ok:
                badge = "not_working"
            elif mode == "dry":
                badge = "untested"
            else:
                badge = "safe_working" if sensitivity == "read_only" else "sensitive"
                verified = True
            personal = {i["name"] for i in inputs_from_schema(version["input_schema"]) if i["personal"]}
            test = {
                "mode": mode,
                "mode_text": MODE_TEXT[mode],
                "inputs": {k: (MASK if k in personal else val) for k, val in inputs.items()},
                "ok": result.ok,
                "message": result.message,
                "status": result.status,
                "failed_step": result.failed_step,
                "request": result.request,
                "output": _jsonable(result.output),
                "sent": result.sent,
                "cancelled": cancelled,
                "injection": scan,
            }
    if test is not None:
        test["owner_message"] = _owner_message(badge, v["title"], result, findings, scan)
    else:
        test = {"owner_message": _owner_message(badge, v["title"], None, findings, None)}

    with db.session() as conn:
        conn.execute(
            "UPDATE tool_checks SET status = 'done', badge = ?, verified = ?, security = ?, test = ?, finished_at = ? WHERE id = ?",
            (badge, int(verified), security.dumps(findings), json.dumps(test, ensure_ascii=False, default=str), db.now(), chk["id"]),
        )
        conn.execute(
            "UPDATE tool_versions SET badge = ?, verified = ?, checked_at = ?, rate_limit = ?, sensitivity = ? WHERE id = ?",
            (badge, int(verified), db.now(), limit, sensitivity, v["id"]),
        )
        current = conn.execute("SELECT current_version FROM tools WHERE id = ?", (tool["id"],)).fetchone()["current_version"]
        # The doc's rule: a new version replaces the old one only once it passes every check.
        if badge in GOOD and verified and (current is None or v["version"] > current):
            conn.execute("UPDATE tools SET current_version = ?, updated_at = ? WHERE id = ?", (v["version"], db.now(), tool["id"]))
            test["promoted"] = True
            conn.execute("UPDATE tool_checks SET test = ? WHERE id = ?", (json.dumps(test, ensure_ascii=False, default=str), chk["id"]))
        if badge == "blocked":
            _alert(conn, business["id"], tool["id"], v["version"], "blocked", test["owner_message"])
        elif badge == "not_working" and v["version"] == current:
            _alert(conn, business["id"], tool["id"], v["version"], "broken", test["owner_message"])
