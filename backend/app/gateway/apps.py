"""MCP Apps (extension io.modelcontextprotocol/ui): Oasis's item cards inside Claude, ChatGPT and
any assistant that renders MCP Apps.

A catalog tool (get_menu, get_projects, show_items...) points at one HTML view through
_meta.ui.resourceUri. The assistant fetches the view with resources/read, shows it in a sandboxed
frame and hands it the tool's result; the view draws the cards and, when the business takes orders,
sends the order with tools/call after the customer clicks Send. Assistants without MCP Apps simply
ignore the _meta and use the text result as before."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp.server.apps import APP_MIME_TYPE, Apps
from mcp.server.mcpserver.resources import Resource

from .. import db
from ..config import PUBLIC_API_URL

# Assistants cache the view by its URI: change the version when items.html changes. Assistants
# also keep tool lists that name an older version, so earlier URIs keep serving the current view.
RESOURCE_URI = "ui://oasis/items-v7.html"
OLDER_URIS = [f"ui://oasis/items-v{n}.html" for n in range(1, 7)]
# The places view embeds Google Maps (keyless embed: maps.google.com redirects to www.google.com).
MAP_FRAMES = ["https://www.google.com", "https://maps.google.com"]
VIEW = Path(__file__).with_name("widget") / "items.html"
MAX_IMAGE_DOMAINS = 40


def ui_meta() -> dict[str, Any]:
    """The _meta of a tool whose result is shown as cards: the standard key, the older flat key
    (still sent by the official SDKs, so hosts read it) and ChatGPT's alias."""
    return {"ui": {"resourceUri": RESOURCE_URI}, "ui/resourceUri": RESOURCE_URI, "openai/outputTemplate": RESOURCE_URI}


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


def _resource_meta() -> dict[str, Any]:
    """The view's sandbox: images from the businesses, Google Maps in a frame, and the user's
    location (asked by the browser, only when they press "Use my location"). ChatGPT also reads
    its own openai/widgetCSP key."""
    images = image_domains()
    return {
        "ui": {"prefersBorder": False, "csp": {"resourceDomains": images, "connectDomains": [], "frameDomains": MAP_FRAMES},
               "permissions": {"geolocation": {}}},
        "openai/widgetCSP": {"resource_domains": images, "connect_domains": [], "frame_domains": MAP_FRAMES},
    }


class ItemsView(Resource):
    """The cards view. Its CSP is worked out on every read, so pictures of a business published
    since the server started load too."""

    async def read(self) -> str:
        self.meta = _resource_meta()
        return VIEW.read_text(encoding="utf-8")


def extension() -> Apps:
    """The MCP Apps extension with the cards view, for MCPServer(extensions=[...]). It also
    advertises io.modelcontextprotocol/ui in the server's capabilities, which assistants check."""
    apps = Apps()
    for uri in [RESOURCE_URI, *OLDER_URIS]:
        apps.add_resource(_view(uri))
    return apps


def _view(uri: str) -> ItemsView:
    return ItemsView(
        uri=uri,
        name="oasis_items" if uri == RESOURCE_URI else f"oasis_items ({uri.rsplit('/', 1)[-1]})",
        title="Oasis cards",
        description="Cards for businesses (nearest first, with a map) and for a business's menu, products, services or other lists, with ordering.",
        mime_type=APP_MIME_TYPE,
        # Listed with the map frames and the location permission; the image domains are added on each read.
        meta={"ui": {"prefersBorder": False, "csp": {"frameDomains": MAP_FRAMES}, "permissions": {"geolocation": {}}}},
    )
