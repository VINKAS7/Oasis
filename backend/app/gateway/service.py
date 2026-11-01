"""Part F: what the gateway does on every call, independent of MCP.

call_tool() checks that the business is live and the tool is published (enabled, passed its
checks with a real test), applies the owner's rules, makes sensitive tools wait for the
user's yes, enforces the per-tool limit, runs the tool through the same runner the checks
use, logs the call, and signs the answer."""

import asyncio
import json
import sys
import time
from collections import defaultdict, deque
from typing import Any

from .. import categories, db, settings
from ..checks import security
from ..recorder.clean import MASK, mask_data
from ..registry.rules import inputs_from_schema
from ..runner import engine
from . import orders, signing

PUBLISHED = {"safe_working", "sensitive"}
BUSINESS_LIMIT_PER_MIN = 120
_calls: dict[str, deque[float]] = defaultdict(deque)
# A catalog (item_list tool, no inputs) read from the website is reused this long: opening the
# menu again, or a second visitor asking, doesn't start another browser. Signed afresh each time.
CATALOG_FRESH_S = 900
_catalogs: dict[tuple[str, int], tuple[float, Any]] = {}


class GatewayError(Exception):
    """An answer for the user's assistant (not a server failure)."""

    def __init__(self, outcome: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.extra = extra


def _live_business(conn, business_id: str):
    b = conn.execute("SELECT * FROM businesses WHERE id = ? AND status = 'live'", (business_id,)).fetchone()
    if b is None:
        raise GatewayError("not_found", f"No live business with the id {business_id}. Use find_nearby to look businesses up.")
    return b


def business_info(business_id: str) -> dict[str, Any]:
    with db.session() as conn:
        b = _live_business(conn, business_id)
    return {
        "business_id": b["id"],
        "name": b["name"],
        "kind": categories.label(b["type"], b["category_label"]),
        "category": b["type"],
        "online_only": bool(b["online_only"]),
        "description": b["description"],
        "address": "" if b["online_only"] else b["address"],
        "lat": None if b["online_only"] else b["lat"],
        "lng": None if b["online_only"] else b["lng"],
        "phone": b["phone"],
        "opening_hours": json.loads(b["hours"] or "{}"),
        "website": b["website_url"],
        "public_key": signing.ensure_key(b["id"]),
        "public_key_note": "Ed25519. Answers from call_business_tool are signed with this key.",
    }


def published_tools(conn, business_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT t.id AS tool_id, t.name, v.* FROM tools t JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
        " WHERE t.business_id = ? AND t.removed_at IS NULL AND t.enabled = 1 AND v.verified = 1 AND v.badge IN ('safe_working', 'sensitive')"
        " ORDER BY t.created_at",
        (business_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_tools(business_id: str) -> list[dict[str, Any]]:
    with db.session() as conn:
        business = dict(_live_business(conn, business_id))
        tools = published_tools(conn, business_id)
        takes_orders = orders.available(conn, business)
        rules = conn.execute("SELECT * FROM owner_rules WHERE business_id = ? AND active = 1", (business_id,)).fetchall()
    out = []
    for t in tools:
        sensitive = t["badge"] == "sensitive"
        tool_rules = [f"{r['input']} {'at most' if r['kind'] == 'max' else 'at least'} {r['value']:g}" for r in rules if r["tool_id"] == t["tool_id"]]
        out.append({
            "name": t["name"],
            "title": t["title"],
            "description": t["description_for_ai"],
            "input_schema": json.loads(t["input_schema"]),
            "badge": t["badge"],
            "requires_user_confirmation": sensitive,
            "owner_rules": tool_rules,
            "note": "Ask the user first, then call with user_confirmed=true." if sensitive else "Read-only; call freely.",
            # A list of items (menu, products, projects...): assistants that render MCP Apps show it as cards.
            "shows_as_cards": json.loads(t["runner"]).get("kind") in ("item_list", "shop_catalog"),
        })
    if takes_orders:
        out += orders.tool_entries()
    return out


def _mask(inputs: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    personal = {i["name"] for i in inputs_from_schema(schema) if i["personal"]}
    return {k: (MASK if k in personal else v) for k, v in inputs.items()}


def _log(business_id: str, tool: dict[str, Any] | None, name: str, outcome: str, inputs: dict[str, Any], result: Any = None, message: str = "", started: float | None = None) -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO calls_log (business_id, tool_id, tool_name, version, outcome, inputs, result, message, duration_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                business_id,
                tool["tool_id"] if tool else None,
                name,
                tool["version"] if tool else None,
                outcome,
                json.dumps(inputs, ensure_ascii=False, default=str),
                json.dumps(result, ensure_ascii=False, default=str)[:4000] if result is not None else None,
                message[:500],
                int((time.monotonic() - started) * 1000) if started else None,
                db.now(),
            ),
        )


def _rate_ok(key: str, limit: int) -> bool:
    window = _calls[key]
    cutoff = time.monotonic() - 60
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= limit:
        return False
    window.append(time.monotonic())
    return True


def _run_isolated(tool: engine.Tool, ctx: engine.Context, values: dict[str, Any]) -> engine.RunResult:
    """Runs in a worker thread with its own event loop: replaying steps starts a browser, which
    on Windows needs a Proactor loop that the web server's loop may not be."""
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(engine.run(tool, ctx, values))
    finally:
        loop.close()


async def call_tool(business_id: str, name: str, inputs: dict[str, Any], user_confirmed: bool) -> dict[str, Any]:
    started = time.monotonic()
    inputs = dict(inputs or {})
    with db.session() as conn:
        business = dict(_live_business(conn, business_id))
    if name in orders.NAMES:  # the Oasis order inbox, not a tool of the business's own
        try:
            return await orders.request(business, inputs, user_confirmed) if name == orders.REQUEST else orders.status(business, inputs)
        except orders.OrderError as exc:
            raise GatewayError(exc.outcome, exc.message, **exc.extra) from exc
    with db.session() as conn:
        tool = next((t for t in published_tools(conn, business_id) if t["name"] == name), None)
        if tool is None:
            _log(business_id, None, name, "not_published", inputs, message="Not a published tool")
            raise GatewayError("not_published", f"{business['name']} has no published tool called {name}. Use list_business_tools.")
        rules = conn.execute("SELECT * FROM owner_rules WHERE tool_id = ? AND active = 1", (tool["tool_id"],)).fetchall()
    schema = json.loads(tool["input_schema"])
    masked = _mask(inputs, schema)

    try:
        values = engine.validate_inputs(schema, inputs)
    except engine.InputError as exc:
        _log(business_id, tool, name, "bad_input", masked, message=str(exc), started=started)
        raise GatewayError("bad_input", str(exc), input_schema=schema) from exc

    for r in rules:
        v = values.get(r["input"])
        if isinstance(v, (int, float)) and ((r["kind"] == "max" and v > r["value"]) or (r["kind"] == "min" and v < r["value"])):
            msg = r["message"] or f"{business['name']} handles {r['input']} {'above' if r['kind'] == 'max' else 'below'} {r['value']:g} personally."
            contact = f" Phone: {business['phone']}." if business["phone"] else ""
            _log(business_id, tool, name, "rule", masked, message=msg, started=started)
            raise GatewayError("owner_rule", msg + contact, rule={"input": r["input"], r["kind"]: r["value"]})

    if tool["badge"] == "sensitive" and not user_confirmed:
        _log(business_id, tool, name, "needs_confirmation", masked, started=started)
        raise GatewayError(
            "needs_user_confirmation",
            f"“{tool['title']}” takes an action (books, orders or sends something) or uses personal details. Tell the user exactly what will happen "
            f"(for example: “Shall I {tool['title'].lower()} at {business['name']} with these details?”), and only after they say yes, "
            "call again with user_confirmed=true.",
            would_send=masked,
        )

    limit = tool["rate_limit"] or security.RATE_LIMITS.get(tool["sensitivity"], 10)
    if not _rate_ok(f"tool:{tool['tool_id']}", limit) or not _rate_ok(f"biz:{business_id}", BUSINESS_LIMIT_PER_MIN):
        _log(business_id, tool, name, "rate_limited", masked, started=started)
        raise GatewayError("rate_limited", f"Too many requests for {name} right now (at most {limit} a minute). Try again shortly.")

    ctx = engine.Context(
        site=business["website_url"],
        allowed_hosts=security.allowed_hosts(business, tool["created_from"]),
        allow_private=settings.get("crawler.allow_private_urls"),
        business=business,
    )
    run_tool = engine.Tool(name, json.loads(tool["runner"]), schema)
    cache_key = (tool["tool_id"], tool["version"])
    cacheable = run_tool.runner.get("kind") == "item_list" and not values
    cached = _catalogs.get(cache_key) if cacheable else None
    reused = bool(cached and time.monotonic() - cached[0] < CATALOG_FRESH_S)
    if reused:
        result = engine.RunResult(ok=True, output=cached[1], message="")
    else:
        try:
            result = await asyncio.to_thread(_run_isolated, run_tool, ctx, values)
        except engine.NotAllowed as exc:
            _log(business_id, tool, name, "failed", masked, message=str(exc), started=started)
            raise GatewayError("failed", f"The tool could not run: {exc}") from exc
        if not result.ok:
            if cached:  # the site is down or changed: the last good copy beats nothing
                result, reused = engine.RunResult(ok=True, output=cached[1], message=""), True
            else:
                _log(business_id, tool, name, "failed", masked, message=result.message, started=started)
                raise GatewayError("failed", f"{business['name']}'s system did not accept this: {result.message}")
        elif cacheable:
            _catalogs[cache_key] = (time.monotonic(), result.output)

    personal_values = {str(inputs[k]) for k, v in masked.items() if v == MASK and k in inputs}
    _log(business_id, tool, name, "ok", masked, result=mask_data(result.output, personal_values), message=result.message, started=started)
    signed = signing.sign(business_id, {"business_id": business_id, "business_name": business["name"], "tool": name, "version": tool["version"], "result": result.output})
    out = {"ok": True, "business": business["name"], "tool": name, "result": result.output, "signed": signed}
    if run_tool.runner.get("kind") in ("item_list", "shop_catalog"):
        if run_tool.runner.get("kind") == "item_list" and not reused:
            orders.save_snapshot(business_id, tool["tool_id"], result.output)
        with db.session() as conn:
            out["can_order"] = orders.available(conn, business)
        has_options = any(i.get("options") for i in (result.output or {}).get("items", []) if isinstance(i, dict))
        out["note"] = (("Each item has an id; order with call_business_tool(request_order)"
                        + (", giving each item's chosen options (e.g. size and colour) in options" if has_options else "") + ".") if out["can_order"]
                       else "This business doesn't take orders through Oasis.")
    return out
