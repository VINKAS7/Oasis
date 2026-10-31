"""Oasis platform API."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db
from .checks import worker
from .config import AUTH_URL, FRONTEND_DIST
from .gateway import business_mcp, mcp_server
from .routers import admin, ai, chat, extension, live, orders, recordings, tools, workspaces

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    worker.start()  # tool checks: after every change, and daily
    # The MCP gateway at /mcp, and each business's own MCP server at /mcp/b/{business_id}.
    async with mcp_server.mcp.session_manager.run(), business_mcp.mcp.session_manager.run():
        yield


app = FastAPI(title="Oasis API", version="0.1.0", lifespan=lifespan)
app.include_router(workspaces.router)
app.include_router(recordings.router)
app.include_router(tools.router)
app.include_router(extension.router)
app.include_router(live.router)
app.include_router(orders.router)

# The MCP gateway (Part F) and the per-business servers: their routes go first, ahead of the UI's catch-all.
for route in [*reversed(mcp_server.http_app().routes), *reversed(business_mcp.http_app().routes)]:
    app.router.routes.insert(0, route)
app.include_router(ai.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


_auth_client = httpx.AsyncClient(base_url=AUTH_URL, timeout=15.0)
_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "keep-alive", "accept-encoding"}


@app.api_route("/api/auth/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def auth_proxy(path: str, request: Request) -> Response:
    """Forward sign-up, sign-in and session calls to the better-auth service, so the UI,
    the API and auth share one origin (in development Vite does this instead)."""
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    try:
        upstream = await _auth_client.request(
            request.method, f"/api/auth/{path}", params=request.query_params, headers=headers, content=await request.body()
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "The auth service is not reachable") from exc
    response = Response(content=upstream.content, status_code=upstream.status_code)
    for key, value in upstream.headers.multi_items():
        if key.lower() not in _HOP_HEADERS and key.lower() != "content-encoding":
            response.headers.append(key, value)
    return response


# In production the built UI is served from here; in development Vite serves it.
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and file.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
