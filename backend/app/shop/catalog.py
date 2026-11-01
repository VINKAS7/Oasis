"""A shop's products as catalog items (the shape the cards and the order inbox already use), the
public photo addresses, stock, and the shop's tool, which Oasis makes itself (no AI, no proposal)."""

import json
from typing import Any

from .. import db
from ..config import FILES_DIR, PUBLIC_API_URL
from ..ids import new_id
from ..gateway import matching
from . import templates

TOOL_CREATED_FROM = "shop"


def image_dir(business_id: str, product_id: str):
    return FILES_DIR / business_id / "products" / product_id


def image_path(business_id: str, product_id: str, name: str) -> str:
    """Relative: the owner's pages and the /chat page load it from Oasis itself."""
    return f"/api/public/shops/{business_id}/images/{product_id}/{name}"


def image_url(business_id: str, product_id: str, name: str) -> str:
    """Absolute, so assistants (ChatGPT, Claude) load it through the public address."""
    return PUBLIC_API_URL + image_path(business_id, product_id, name)


def thumb_name(name: str) -> str:
    return name.rsplit(".", 1)[0] + "_t.jpg"


def photo_data_url(business_id: str, product_id: str, index: int = 0) -> str | None:
    """A product's thumbnail as a data: URL, for card views that can't load the photo's address
    (a development tunnel's browser warning page). Live shops and active products only."""
    import base64

    with db.session() as conn:
        b = conn.execute("SELECT status FROM businesses WHERE id = ?", (business_id,)).fetchone()
        p = conn.execute("SELECT images, active FROM products WHERE id = ? AND business_id = ?", (product_id, business_id)).fetchone()
    if b is None or p is None or b["status"] != "live" or not p["active"]:
        return None
    names = json.loads(p["images"] or "[]")
    if not 0 <= index < len(names):
        return None
    path = image_dir(business_id, product_id) / thumb_name(names[index])
    if not path.is_file():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def _money(amount: float | None, currency: str) -> str:
    return "" if amount is None else f"{currency} {amount:.2f}".strip()


def product_out(r: Any) -> dict[str, Any]:
    """A product as the owner edits it."""
    d = dict(r)
    for k in ("images", "attributes", "options", "stock"):
        d[k] = json.loads(d[k] or ("[]" if k == "images" else "{}"))
    d["active"] = bool(d["active"])
    d["image_urls"] = [image_path(d["business_id"], d["id"], n) for n in d["images"]]
    return d


def item(r: Any, template: str) -> dict[str, Any]:
    """A product as a catalog item: what a tool returns and the cards show."""
    p = product_out(r)
    tracked = templates.get(template)["stock"] and bool(p["stock"])
    available = {k: int(v) for k, v in p["stock"].items()} if tracked else None
    in_stock = None if available is None else any(v > 0 for v in available.values())
    return {
        "id": p["id"],
        "name": p["name"],
        "description": p["description"],
        "section": p["category"],
        "price": _money(p["price_amount"], p["currency"]),
        "amount": p["price_amount"],
        "currency": p["currency"],
        "image_url": image_url(p["business_id"], p["id"], p["images"][0]) if p["images"] else "",
        "images": [image_url(p["business_id"], p["id"], n) for n in p["images"]],
        "url": "",
        "options": p["options"],
        "available": available,   # stock per variant ("M/Black": 3); None = not tracked
        "in_stock": in_stock,
        "attributes": p["attributes"],
    }


def items_for(business_id: str) -> list[dict[str, Any]]:
    with db.session() as conn:
        b = conn.execute("SELECT shop_template FROM businesses WHERE id = ?", (business_id,)).fetchone()
        rows = conn.execute("SELECT * FROM products WHERE business_id = ? AND active = 1 ORDER BY sort, created_at", (business_id,)).fetchall()
    return [item(r, (b["shop_template"] if b else "") or "general") for r in rows]


def search(items: list[dict[str, Any]], values: dict[str, Any]) -> list[dict[str, Any]]:
    """The products matching a customer's filters (all optional): words, category, max price, variants."""
    query = str(values.get("search") or "")
    category = str(values.get("category") or "").strip().lower()
    max_price = values.get("max_price")
    out = []
    for i in items:
        if category and category not in i["section"].lower():
            continue
        if isinstance(max_price, (int, float)) and i["amount"] is not None and i["amount"] > max_price:
            continue
        wanted = {axis: str(values.get(axis) or "").strip().lower() for axis in i["options"] if values.get(axis)}
        if any(v not in [x.lower() for x in i["options"][axis]] for axis, v in wanted.items()):
            continue
        # The cards open on what was asked for (colour="Black" -> the black version).
        chosen = {axis: next(x for x in i["options"][axis] if x.lower() == v) for axis, v in wanted.items()}
        out.append({**i, "preselect": chosen} if chosen else i)
    if not query.strip():
        return out
    # Words as customers type them: "black tshirts", "pizzas", "Margarita" (gateway/bm25.py).
    found, how = matching.filter_items(out, query)
    if how == "none":
        return []
    return [{**f, "preselect": {**f.get("preselect", {}), **next((o.get("preselect", {}) for o in out if o["id"] == f["id"]), {})}} for f in found]


# --- the shop's tool --------------------------------------------------------------------------


def tool_spec(template: str, shop_name: str) -> dict[str, Any]:
    t = templates.get(template)
    noun = t["item"]
    nouns = templates.plural(noun)
    name = {"menu": "get_menu", "services": "get_services"}.get(template, "get_products")
    axes = [v["key"] for v in t["variants"]]
    inputs: list[dict[str, Any]] = [
        {"name": "search", "type": "string", "description": f"Words to look for in the {nouns} (name, description, details). Empty: everything.", "required": False, "personal": False},
        {"name": "category", "type": "string", "description": f"{t['category_label']}, e.g. {', '.join(t['category_examples'][:3]) or 'any'}.", "required": False, "personal": False},
        {"name": "max_price", "type": "number", "description": "Highest price.", "required": False, "personal": False},
    ] + [{"name": axis, "type": "string", "description": f"Only {nouns} available in this {axis}.", "required": False, "personal": False} for axis in axes]
    from ..registry.rules import input_schema  # registry imports shop indirectly through the engine

    details = ", ".join(f["label"].lower() for f in t["fields"])
    variants = f" Each {noun} lists its {' and '.join(axes)} options and the stock of each combination (\"available\")." if axes else ""
    return {
        "name": name,
        "title": {"get_menu": "Menu", "get_services": "Services"}.get(name, "Products"),
        "description_for_ai": (
            f"The {nouns} {shop_name} offers, from its Oasis shop: name, description, price, photos"
            f"{', ' + details if details else ''}.{variants} Filter with search, category or max_price; all filters are optional. "
            f"To {t['order_word'].split()[0]} for the customer, use request_order with each {noun}'s id"
            f"{' and the chosen ' + ' and '.join(axes) + ' in options' if axes else ''}; the customer must confirm first."
        ),
        "description_for_owner": f"Shows your {nouns} to AI assistants and the Oasis chat, with photos and prices.",
        "input_schema": input_schema(inputs),
        "runner": {"kind": "shop_catalog", "title": {"get_menu": "Menu", "get_services": "Services"}.get(name, "Products")},
        "sensitivity": "read_only",
    }


def ensure_tool(business_id: str) -> tuple[str, int] | None:
    """The shop's tool exists once the shop has a product. Returns (tool id, version) when it was just
    made (so its check can be queued), else None."""
    from ..registry import store

    with db.session() as conn:
        b = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if b is None or not b["shop_template"]:
            return None
        has = conn.execute(
            "SELECT 1 FROM tools t JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
            " WHERE t.business_id = ? AND t.removed_at IS NULL AND v.runner LIKE '%shop_catalog%'", (business_id,)
        ).fetchone()
        if has or not conn.execute("SELECT 1 FROM products WHERE business_id = ? AND active = 1", (business_id,)).fetchone():
            return None
        spec = tool_spec(b["shop_template"], b["name"])
        return store.add_platform_tool(conn, business_id, spec, TOOL_CREATED_FROM, "Made by Oasis for your shop.")


def take_stock(conn, business_id: str, lines: list[dict[str, Any]]) -> None:
    """When the owner accepts an order: lower the stock of each variant ordered (never below 0)."""
    for line in lines:
        r = conn.execute("SELECT stock FROM products WHERE id = ? AND business_id = ?", (line.get("id"), business_id)).fetchone()
        if r is None:
            continue
        stock = json.loads(r["stock"] or "{}")
        key = line.get("variant", "")
        if key in stock:
            stock[key] = max(0, int(stock[key]) - int(line.get("quantity", 0)))
            conn.execute("UPDATE products SET stock = ?, updated_at = ? WHERE id = ?", (json.dumps(stock), db.now(), line["id"]))


def new_product_id() -> str:
    return new_id("prd")
