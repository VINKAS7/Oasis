"""MCP Apps (extension io.modelcontextprotocol/ui): Oasis's views inside Claude, ChatGPT and any
assistant that renders MCP Apps.

- items: business cards (nearest first, with a map) and a business's menu, products, services or
  other lists, with filters, photos and ordering (find_nearby, search_businesses, show_items and
  every catalog tool of a business);
- ask: a question the user answers with a tap: yes/no, one or several choices, a range, a rating,
  a number, a date, a time or a short text (ask_user);
- business: one business with its open/closed status, hours, map and contact buttons (get_business_info).

A tool points at its view through _meta.ui.resourceUri. The assistant fetches the view with
resources/read, shows it in a sandboxed frame and hands it the tool's input and result. Assistants
without MCP Apps simply ignore the _meta and use the text result as before."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp.server.apps import APP_MIME_TYPE, Apps
from mcp.server.mcpserver.resources import Resource

from .. import db
from ..config import PUBLIC_API_URL

DIR = Path(__file__).with_name("widget")
# The places and business views embed Google Maps (keyless embed: maps.google.com redirects to www.google.com).
MAP_FRAMES = ["https://www.google.com", "https://maps.google.com"]
MAX_IMAGE_DOMAINS = 40

# Assistants cache a view by its URI: change the version when its file changes. They also keep
# tool lists that name an older version, so earlier URIs keep serving the current view.
VIEWS: dict[str, dict[str, Any]] = {
    "items": {"uri": "ui://oasis/items-v8.html", "older": [f"ui://oasis/items-v{n}.html" for n in range(1, 8)], "file": "items.html",
              "title": "Oasis cards", "frames": MAP_FRAMES, "geolocation": True, "images": True,
              "description": "Cards for businesses (nearest first, with a map) and for a business's menu, products, services or other "
                             "lists, with search, filters, photos and ordering."},
    "ask": {"uri": "ui://oasis/ask-v1.html", "older": [], "file": "ask.html", "title": "Oasis question", "frames": [], "geolocation": False,
            "images": False, "description": "A question the user answers with a tap: yes/no, choices, a range, a rating, a number, a date or a time."},
    "business": {"uri": "ui://oasis/business-v1.html", "older": [], "file": "business.html", "title": "Oasis business", "frames": MAP_FRAMES,
                 "geolocation": False, "images": False,
                 "description": "One business: open now or not, opening hours, map, and buttons to call, visit the website or get directions."},
}
RESOURCE_URI = VIEWS["items"]["uri"]


def ui_meta(view: str = "items") -> dict[str, Any]:
    """The _meta of a tool whose result is shown in a view: the standard key, the older flat key
    (still sent by the official SDKs, so hosts read it) and ChatGPT's alias."""
    uri = VIEWS[view]["uri"]
    meta: dict[str, Any] = {"ui": {"resourceUri": uri}, "ui/resourceUri": uri, "openai/outputTemplate": uri}
    if view == "ask":
        meta["openai/widgetAccessible"] = True  # the card sends the answer as a follow-up message
    return meta


def image_domains() -> list[str]:
    """Where live businesses' item pictures come from. The view's sandbox only loads images from
    origins listed in its CSP, and they are the businesses' own sites (or their image hosts)."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT s.items FROM item_snapshots s JOIN businesses b ON b.id = s.business_id WHERE b.status = 'live'"
        ).fetchall()
    origins: set[str] = set()
    for r in rows:
        for item in json.loads(r["items"]):
            parts = urlsplit(item.get("image_url") or "")
            if parts.scheme == "https" and parts.netloc:
                origins.add(f"https://{parts.netloc}")
    public = urlsplit(PUBLIC_API_URL)
    if public.scheme == "https" and public.netloc:  # photos of Oasis shops
        origins.add(f"https://{public.netloc}")
    return sorted(origins)[:MAX_IMAGE_DOMAINS]


def _ui(view: str, images: list[str]) -> dict[str, Any]:
    spec = VIEWS[view]
    csp: dict[str, Any] = {"resourceDomains": images, "connectDomains": [], "frameDomains": spec["frames"]}
    ui: dict[str, Any] = {"prefersBorder": False, "csp": csp}
    if spec["geolocation"]:
        ui["permissions"] = {"geolocation": {}}
    return ui


def _resource_meta(view: str) -> dict[str, Any]:
    """A view's sandbox: images from the businesses (items), Google Maps in a frame (items, business),
    and the user's location (items: asked by the browser only when they press "Use my location").
    ChatGPT also reads its own openai/widgetCSP key."""
    images = image_domains() if VIEWS[view]["images"] else []
    return {
        "ui": _ui(view, images),
        "openai/widgetCSP": {"resource_domains": images, "connect_domains": [], "frame_domains": VIEWS[view]["frames"]},
        "openai/widgetDescription": VIEWS[view]["description"],
    }


def page(view: str) -> str:
    """A view's HTML with the shared theme and bridge put in (the sandbox can't load other files)."""
    text = (DIR / VIEWS[view]["file"]).read_text(encoding="utf-8")
    if "/* @theme */" in text:
        text = text.replace("/* @theme */", (DIR / "theme.css").read_text(encoding="utf-8"))
    if "<!-- @bridge -->" in text:
        text = text.replace("<!-- @bridge -->", "<script>\n" + (DIR / "bridge.js").read_text(encoding="utf-8") + "\n</script>")
    return text


class View(Resource):
    """One view. Its CSP is worked out on every read, so pictures of a business published since the
    server started load too."""

    view: str = "items"

    async def read(self) -> str:
        self.meta = _resource_meta(self.view)
        return page(self.view)


# Kept for imports elsewhere: the items view's class under its old name.
ItemsView = View


def extension() -> Apps:
    """The MCP Apps extension with every view, for MCPServer(extensions=[...]). It also advertises
    io.modelcontextprotocol/ui in the server's capabilities, which assistants check."""
    apps = Apps()
    for key, spec in VIEWS.items():
        for uri in [spec["uri"], *spec["older"]]:
            name = f"oasis_{key}" if uri == spec["uri"] else f"oasis_{key} ({uri.rsplit('/', 1)[-1]})"
            apps.add_resource(View(uri=uri, name=name, title=spec["title"], description=spec["description"], mime_type=APP_MIME_TYPE,
                                   view=key, meta={"ui": _ui(key, [])}))
    return apps
