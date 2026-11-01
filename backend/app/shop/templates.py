"""Shop templates: which fields a product has, which variants it can come in, and how ordering is
worded. One source for the owner's product editor (GET /api/shop/templates), the tool description
assistants read, and the checks on what an owner saves."""

from typing import Any

# A field: key, label, kind (text | longtext | tags | number | select), hint, choices (tags/select).
TEMPLATES: dict[str, dict[str, Any]] = {
    "clothing": {
        "label": "Clothing brand",
        "description": "Clothes and accessories in sizes and colours, with stock per size and colour.",
        "item": "product",
        "category_label": "Category",
        "category_examples": ["T-shirts", "Shirts", "Trousers", "Jackets", "Accessories"],
        "fields": [
            {"key": "material", "label": "Material", "kind": "text", "hint": "e.g. 100% organic cotton"},
            {"key": "fit", "label": "Fit", "kind": "select", "choices": ["Regular", "Slim", "Relaxed", "Oversized"]},
            {"key": "care", "label": "Care", "kind": "text", "hint": "e.g. machine wash 30°C"},
        ],
        "variants": [
            {"key": "size", "label": "Sizes", "suggestions": ["XS", "S", "M", "L", "XL", "XXL"]},
            {"key": "colour", "label": "Colours", "suggestions": ["Black", "White", "Navy", "Grey", "Sand", "Olive"]},
        ],
        "stock": True,
        "when_label": "Pickup or delivery note",
        "order_word": "order",
    },
    "menu": {
        "label": "Food menu",
        "description": "Dishes and drinks by menu section, with dietary tags and allergens, ordered for pickup.",
        "item": "dish",
        "category_label": "Menu section",
        "category_examples": ["Starters", "Mains", "Pizza", "Desserts", "Drinks"],
        "fields": [
            {"key": "dietary", "label": "Dietary", "kind": "tags", "choices": ["Vegetarian", "Vegan", "Gluten-free", "Lactose-free", "Halal", "Spicy"]},
            {"key": "allergens", "label": "Allergens", "kind": "text", "hint": "e.g. gluten, milk, nuts"},
        ],
        "variants": [],
        "stock": False,
        "when_label": "Pickup time",
        "order_word": "order",
    },
    "services": {
        "label": "Services",
        "description": "Services with a duration and price; customers request a time and you confirm it.",
        "item": "service",
        "category_label": "Group",
        "category_examples": ["Haircuts", "Colour", "Treatments", "Consultations"],
        "fields": [
            {"key": "duration_min", "label": "Duration (minutes)", "kind": "number", "hint": "e.g. 45"},
            {"key": "includes", "label": "What's included", "kind": "longtext"},
        ],
        "variants": [],
        "stock": False,
        "when_label": "Requested date and time",
        "order_word": "booking request",
    },
    "general": {
        "label": "General shop",
        "description": "Any products with photos, prices and descriptions; optional variants.",
        "item": "product",
        "category_label": "Category",
        "category_examples": [],
        "fields": [],
        "variants": [{"key": "option", "label": "Options", "suggestions": []}],
        "stock": True,
        "when_label": "When do you want it?",
        "order_word": "order",
    },
}

MAX_OPTION_VALUES = 20


def plural(noun: str) -> str:
    """dish -> dishes, product -> products."""
    return noun + ("es" if noun.endswith(("s", "sh", "ch", "x")) else "s")


def get(template: str) -> dict[str, Any]:
    return TEMPLATES.get(template) or TEMPLATES["general"]


def clean_attributes(template: str, attrs: dict[str, Any]) -> dict[str, Any]:
    """Only the template's fields, as plain values."""
    out: dict[str, Any] = {}
    for f in get(template)["fields"]:
        v = attrs.get(f["key"])
        if v in (None, "", []):
            continue
        if f["kind"] == "tags":
            v = [str(x)[:40] for x in (v if isinstance(v, list) else [v]) if str(x).strip()][:12]
        elif f["kind"] == "number":
            try:
                v = float(v)
                v = int(v) if v.is_integer() else v
            except (TypeError, ValueError):
                continue
        else:
            v = str(v).strip()[:500 if f["kind"] == "longtext" else 120]
        out[f["key"]] = v
    return out


def clean_options(template: str, options: dict[str, Any]) -> dict[str, list[str]]:
    """Only the template's variant axes, each a list of distinct short values."""
    out: dict[str, list[str]] = {}
    for v in get(template)["variants"]:
        values = options.get(v["key"]) or []
        seen: list[str] = []
        for x in values if isinstance(values, list) else []:
            x = str(x).strip()[:30]
            if x and x not in seen:
                seen.append(x)
        if seen:
            out[v["key"]] = seen[:MAX_OPTION_VALUES]
    return out


def variant_keys(options: dict[str, list[str]]) -> list[str]:
    """Every combination, as "M/Black" (axes in template order). [""] when there are no variants."""
    keys = [""]
    for values in options.values():
        keys = [f"{k}/{v}" if k else v for k in keys for v in values]
    return keys


def variant_key(options: dict[str, list[str]], chosen: dict[str, Any]) -> str | None:
    """The key for the options a customer chose, or None when a choice is missing or unknown."""
    parts = []
    for axis, values in options.items():
        v = str(chosen.get(axis, "")).strip()
        match = next((x for x in values if x.lower() == v.lower()), None)
        if match is None:
            return None
        parts.append(match)
    return "/".join(parts)
