"""What the Chrome extension recorder needs: who is signed in, which workspaces and flows
they can record, and the extension itself as a download."""

import io
import json
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .. import db, settings
from ..auth import User, current_user
from ..config import ROOT_DIR

router = APIRouter(prefix="/api", tags=["extension"])

EXTENSION_DIR = ROOT_DIR / "extension"


@router.get("/config")
def config(_: User = Depends(current_user)) -> dict:
    """Switches the web app needs to know about."""
    return {"server_recorder": settings.get("recorder.enabled")}


@router.get("/extension/context")
def context(user: User = Depends(current_user)) -> dict:
    """The signed-in owner, their workspaces, and the flows each one still needs recorded."""
    out = []
    with db.session() as conn:
        for b in conn.execute("SELECT * FROM businesses WHERE owner_id = ? ORDER BY created_at DESC", (user.id,)):
            flows: dict[str, dict] = {}
            run = conn.execute("SELECT summary FROM crawl_runs WHERE business_id = ? AND summary IS NOT NULL ORDER BY id DESC LIMIT 1", (b["id"],)).fetchone()
            for t in json.loads(run["summary"]).get("todo", []) if run else []:
                flows[t["flow"]] = {"flow": t["flow"], "title": t["title"], "recorded": 0, "suggested": True}
            for r in conn.execute(
                "SELECT flow_name, MAX(title) AS title, SUM(status = 'finished') AS n FROM recordings WHERE business_id = ? GROUP BY flow_name", (b["id"],)
            ):
                f = flows.setdefault(r["flow_name"], {"flow": r["flow_name"], "title": r["title"], "recorded": 0, "suggested": False})
                f["recorded"] = r["n"] or 0
            out.append({"id": b["id"], "name": b["name"], "type": b["type"], "website_url": b["website_url"], "flows": list(flows.values())})
    return {"user": {"id": user.id, "email": user.email, "name": user.name}, "workspaces": out}


@router.get("/extension/download")
def download(_: User = Depends(current_user)) -> Response:
    if not EXTENSION_DIR.is_dir():
        raise HTTPException(404, "The extension folder is missing from this server")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            if path.is_file():
                z.write(path, f"oasis-recorder/{path.relative_to(EXTENSION_DIR).as_posix()}")
    return Response(buf.getvalue(), media_type="application/zip", headers={"content-disposition": 'attachment; filename="oasis-recorder.zip"'})
