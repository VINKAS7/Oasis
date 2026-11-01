"""The Oasis order inbox: customers (through any assistant, or the /chat page) order items
from a business's catalog; the owner accepts or declines in their workspace.

It works for any business whose catalog Oasis can read (an item_list tool), whether or not
its website takes orders itself. Two rules keep it honest:
- prices come from the last items the business's own tool returned (item_snapshots), never from
  the assistant, so an assistant can't change what something costs;
- an order is only sent with user_confirmed=true, after the customer said yes.

Both tools are reached like any business tool: call_business_tool(business_id, "request_order", ...)
on the gateway, or directly on the business's own MCP server."""

import json
import re
import secrets
import time
from typing import Any

from .. import db
from ..ids import new_id
from ..recorder.clean import MASK

REQUEST = "request_order"
STATUS = "get_order_status"
NAMES = {REQUEST, STATUS}
MAX_LINES = 50
MAX_QUANTITY = 20

REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "What to order: the item id (or exact name) from the business's catalog tool, and how many.",
            "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_QUANTITY},
                "options": {"type": "object", "description": "For items with options (size, colour...): the customer's choice, e.g. {\"size\": \"M\", \"colour\": \"Black\"}.",
                            "additionalProperties": {"type": "string"}}}, "required": ["id", "quantity"]},
        },
        "customer_name": {"type": "string", "description": "The customer's name.", "x-personal": True},
        "customer_contact": {"type": "string", "description": "A phone number or email the business can reach the customer at.", "x-personal": True},
        "pickup_time": {"type": "string", "description": "When the customer wants it, e.g. 'today 19:00' (optional)."},
        "note": {"type": "string", "description": "Anything the business should know (optional)."},
    },
    "required": ["items", "customer_name", "customer_contact"],
}
STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}, "status_token": {"type": "string"}},
    "required": ["order_id", "status_token"],
}


class OrderError(Exception):
    def __init__(self, outcome: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.outcome, self.message, self.extra = outcome, message, extra


def catalog_tools(conn, business_id: str) -> list[dict[str, Any]]:
    from .service import published_tools  # service imports this module

    return [t for t in published_tools(conn, business_id) if json.loads(t["runner"]).get("kind") in ("item_list", "shop_catalog")]


def available(conn, business: dict[str, Any]) -> bool:
    return bool(business["accepts_orders"]) and bool(catalog_tools(conn, business["id"]))


def tool_entries() -> list[dict[str, Any]]:
    """How the two order tools appear in list_business_tools (same shape as published tools)."""
    return [
        {"name": REQUEST, "title": "Order", "badge": "sensitive", "requires_user_confirmation": True, "owner_rules": [],
         "description": "Send an order for items from this business's catalog. The business confirms or declines it; prices come from the catalog.",
         "input_schema": REQUEST_SCHEMA, "note": "Show the customer the items, quantities and total first; call with user_confirmed=true only after they say yes."},
        {"name": STATUS, "title": "Order status", "badge": "safe_working", "requires_user_confirmation": False, "owner_rules": [],
         "description": "Whether the business accepted or declined an order (pending, accepted, declined).",
         "input_schema": STATUS_SCHEMA, "note": "Read-only; call freely."},
    ]


def save_snapshot(business_id: str, tool_id: str, output: Any) -> None:
    items = (output or {}).get("items") if isinstance(output, dict) else None
    if not items:
        return
    with db.session() as conn:
        conn.execute(
            "INSERT INTO item_snapshots (tool_id, business_id, items, fetched_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(tool_id) DO UPDATE SET items = excluded.items, fetched_at = excluded.fetched_at",
            (tool_id, business_id, json.dumps(items, ensure_ascii=False), db.now()),
        )
    from . import search_index

    search_index.schedule(business_id)  # its items, as found by meaning


def _known_items(business_id: str) -> list[dict[str, Any]]:
    with db.session() as conn:
        ids = [t["tool_id"] for t in catalog_tools(conn, business_id)]
        rows = conn.execute(f"SELECT items FROM item_snapshots WHERE tool_id IN ({','.join('?' * len(ids))})", ids).fetchall() if ids else []
    return [i for r in rows for i in json.loads(r["items"])]


async def _catalog(business_id: str) -> list[dict[str, Any]]:
    """The items to price an order from. An Oasis shop: its products, as they are now. Otherwise the
    last items its catalog tool returned; when none has run yet, run the first one."""
    from ..shop import catalog as shop_catalog

    with db.session() as conn:
        is_shop = bool(conn.execute("SELECT shop_template FROM businesses WHERE id = ?", (business_id,)).fetchone()[0])
    if is_shop:
        return shop_catalog.items_for(business_id)
    items = _known_items(business_id)
    if not items:
        from .service import GatewayError, call_tool

        with db.session() as conn:
            tools = catalog_tools(conn, business_id)
        if tools:
            try:
                await call_tool(business_id, tools[0]["name"], {}, False)
            except GatewayError as exc:
                raise OrderError("failed", f"The catalog could not be read right now: {exc.message}") from exc
        items = _known_items(business_id)
    return items


def _lines(requested: Any, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(requested, list) or not requested:
        raise OrderError("bad_input", "Add at least one item: [{\"id\": ..., \"quantity\": 1}].")
    if len(requested) > MAX_LINES:
        raise OrderError("bad_input", f"At most {MAX_LINES} different items per order.")
    by_id = {i["id"]: i for i in catalog}
    by_name = {i["name"].strip().lower(): i for i in catalog}
    lines: dict[str, dict[str, Any]] = {}
    for r in requested:
        r = r if isinstance(r, dict) else {}
        key = str(r.get("id") or r.get("name") or "").strip()
        item = by_id.get(key) or by_name.get(key.lower())
        if item is None:
            raise OrderError("bad_input", f"“{key}” is not in the catalog. Use the item ids from the catalog tool.")
        try:
            qty = int(r.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 0
        if not 1 <= qty <= MAX_QUANTITY:
            raise OrderError("bad_input", f"Quantities go from 1 to {MAX_QUANTITY} ({item['name']}).")
        options = item.get("options") or {}
        variant = ""
        if options:  # sizes, colours...: the customer must choose, and the choice must exist
            from ..shop.templates import variant_key

            chosen = r.get("options") if isinstance(r.get("options"), dict) else {}
            variant = variant_key(options, chosen) or ""
            if not variant:
                choices = "; ".join(f"{axis}: {', '.join(values)}" for axis, values in options.items())
                raise OrderError("bad_input", f"Choose the options for {item['name']} ({choices}).")
        line = lines.setdefault(f"{item['id']}|{variant}", {"id": item["id"], "name": item["name"] + (f" ({variant.replace('/', ', ')})" if variant else ""),
                                                            "quantity": 0, "amount": item.get("amount"), "currency": item.get("currency", ""),
                                                            **({"variant": variant, "options": dict(zip(options, variant.split("/")))} if variant else {})})
        line["quantity"] = min(MAX_QUANTITY, line["quantity"] + qty)
        available = item.get("available")
        if isinstance(available, dict) and variant in available and line["quantity"] > int(available[variant]):
            left = int(available[variant])
            raise OrderError("bad_input", f"Only {left} left of {line['name']}." if left else f"{line['name']} is sold out.")
        if isinstance(available, dict) and not options and "" in available and line["quantity"] > int(available[""]):
            left = int(available[""])
            raise OrderError("bad_input", f"Only {left} left of {item['name']}." if left else f"{item['name']} is sold out.")
    return list(lines.values())


def _total(lines: list[dict[str, Any]]) -> tuple[float | None, str]:
    currencies = {l["currency"] for l in lines if l["amount"] is not None}
    if len(currencies) > 1:
        raise OrderError("bad_input", "These items are priced in different currencies; order them separately.")
    if any(l["amount"] is None for l in lines):
        return None, next(iter(currencies), "")  # some price unknown: the business names the total
    return round(sum(l["amount"] * l["quantity"] for l in lines), 2), next(iter(currencies), "")


def _summary(business_name: str, lines: list[dict[str, Any]], total: float | None, currency: str) -> str:
    items = ", ".join(f"{l['quantity']}× {l['name']}" for l in lines)
    price = f"{currency} {total:.2f}".strip() if total is not None else "price confirmed by the business"
    return f"{items} from {business_name}, total {price}"


async def request(business: dict[str, Any], inputs: dict[str, Any], user_confirmed: bool) -> dict[str, Any]:
    from .service import _log, _rate_ok  # one rate limiter and call log for every tool

    started = time.monotonic()
    with db.session() as conn:
        if not available(conn, business):
            contact = " ".join(x for x in (business["phone"], business["website_url"]) if x)
            raise OrderError("not_available", f"{business['name']} doesn't take orders through Oasis. {('Contact: ' + contact) if contact else ''}".strip())
    lines = _lines(inputs.get("items"), await _catalog(business["id"]))
    total, currency = _total(lines)
    name = str(inputs.get("customer_name") or "").strip()[:80]
    contact = str(inputs.get("customer_contact") or "").strip()[:120]
    if not name:
        raise OrderError("bad_input", "Add the customer's name (customer_name).")
    if "@" not in contact and len(re.sub(r"\D", "", contact)) < 6:
        raise OrderError("bad_input", "Add a phone number or email the business can reach the customer at (customer_contact).")
    pickup = str(inputs.get("pickup_time") or "").strip()[:40]
    note = str(inputs.get("note") or "").strip()[:300]
    summary = _summary(business["name"], lines, total, currency)
    logged = {"items": [f"{l['quantity']}× {l['name']}" for l in lines], "customer_name": MASK, "customer_contact": MASK, "pickup_time": pickup}

    if not user_confirmed:
        _log(business["id"], None, REQUEST, "needs_confirmation", logged, started=started)
        raise OrderError("needs_user_confirmation", f"Tell the customer exactly what will be ordered ({summary}) and only after they say yes, call again with user_confirmed=true.",
                         would_send={"items": logged["items"], "total": f"{currency} {total:.2f}".strip() if total is not None else "", "pickup_time": pickup})
    if not _rate_ok(f"orders:{business['id']}", 20):
        raise OrderError("rate_limited", "Too many orders for this business right now. Try again in a minute.")

    order_id, token, stamp = new_id("ord"), secrets.token_urlsafe(18), db.now()
    with db.session() as conn:
        conn.execute(
            "INSERT INTO orders (id, business_id, items, total, currency, customer_name, customer_contact, pickup_time, note, status, status_token, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (order_id, business["id"], json.dumps(lines, ensure_ascii=False), total, currency, name, contact, pickup, note, token, stamp, stamp),
        )
    _log(business["id"], None, REQUEST, "ok", logged, result={"order_id": order_id, "total": total}, message=summary, started=started)
    return {"ok": True, "business": business["name"], "order_id": order_id, "status": "pending", "status_token": token,
            "lines": lines, "total": total, "currency": currency,
            "message": f"{_order_word(business).capitalize()} sent: {summary}. {business['name']} will accept or decline it; check with get_order_status."}


def _order_word(business: dict[str, Any]) -> str:
    """"order", or the shop template's own word ("booking request" for services)."""
    from ..shop import templates

    template = business.get("shop_template") or ""
    return templates.get(template)["order_word"] if template else "order"


def status(business: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    with db.session() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id = ? AND business_id = ?", (str(inputs.get("order_id", "")), business["id"])).fetchone()
    if o is None or not secrets.compare_digest(o["status_token"], str(inputs.get("status_token", ""))):
        raise OrderError("not_found", "No order with that id and token.")
    return {"ok": True, "business": business["name"], "order_id": o["id"], "status": o["status"], "owner_note": o["owner_note"],
            "total": o["total"], "currency": o["currency"], "updated_at": o["updated_at"]}
