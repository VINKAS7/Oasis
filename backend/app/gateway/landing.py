"""The page a browser sees at /mcp: how to add Oasis to ChatGPT, Claude or any MCP client.

ChatGPT, Claude and other MCP clients use the same address, so only a plain browser visit
(GET that accepts HTML, not an event stream) gets the page; every other request goes on to the
MCP server unchanged. The page uses the app's font (Inter); it and the icons are in ASSETS."""

import html
from functools import cache
from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, HTMLResponse

from ..config import PUBLIC_API_URL

DIR = Path(__file__).with_name("landing")
PAGE = DIR / "mcp.html"
PATHS = {"/mcp", "/mcp/"}
# The page's own files, served at /mcp/<name>. The assistants' icons are kept here because
# chatgpt.com refuses to serve its favicon to other sites.
ASSETS = {
    "/mcp/inter.woff2": (DIR / "inter.woff2", "font/woff2"),
    "/mcp/chatgpt.png": (DIR / "chatgpt.png", "image/png"),
    "/mcp/claude.png": (DIR / "claude.png", "image/png"),
}


@cache
def render() -> str:
    return PAGE.read_text(encoding="utf-8").replace("{{MCP_URL}}", html.escape(f"{PUBLIC_API_URL}/mcp"))


def _wants_page(scope: Any) -> bool:
    if scope["path"] not in PATHS:
        return False
    accept = next((v.decode("latin-1").lower() for k, v in scope["headers"] if k == b"accept"), "")
    return "text/html" in accept and "text/event-stream" not in accept


class McpLandingPage:
    """Answers browser visits to /mcp with the connect page; passes everything else on."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        if asset := ASSETS.get(scope["path"]):
            response = FileResponse(asset[0], media_type=asset[1], headers={"Cache-Control": "public, max-age=604800"})
        elif _wants_page(scope):
            response = HTMLResponse(render(), headers={"Cache-Control": "no-cache"})
        else:
            return await self.app(scope, receive, send)
        await response(scope, receive, send)
