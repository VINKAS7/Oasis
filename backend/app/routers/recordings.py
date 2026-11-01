"""Part C: recording the flows the AI cannot safely work out (bookings, cancellations, orders)."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import db, settings
from ..auth import User, current_user
from ..config import FILES_DIR
from ..crawler import safety
from ..ids import new_id
from ..recorder import compare as compare_mod
from ..recorder import scan, session, store
from ..registry import propose
from ..recorder.clean import mask_text, snake
from .workspaces import _owned

router = APIRouter(prefix="/api/workspaces/{business_id}", tags=["recordings"])


class StartIn(BaseModel):
    flow: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=120)
    start_url: str = Field(default="", max_length=500)


class PatchIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    notes: dict[int, str] = Field(default_factory=dict)  # step number -> owner note


def _row_out(r) -> dict:
    d = dict(r)
    live = session.ACTIVE.get(d["id"])
    if live is not None:
        d["live_steps"] = live.snapshot()
    return d


def _get(conn, business_id: str, rec_id: str):
    r = conn.execute("SELECT * FROM recordings WHERE id = ? AND business_id = ?", (rec_id, business_id)).fetchone()
    if r is None:
        raise HTTPException(404, "Recording not found")
    return r


def _flow(name: str) -> str:
    flow = snake(name)
    if not re.match(r"^[a-z][a-z0-9_]{1,59}$", flow):
        raise HTTPException(400, "Name the flow in a few words, for example: book table")
    return flow


@router.get("/recordings")
def list_recordings(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        rs = conn.execute("SELECT * FROM recordings WHERE business_id = ? ORDER BY uploaded_at DESC", (business_id,)).fetchall()
    return [dict(r) for r in rs]


@router.post("/recordings", status_code=201)
def start_recording(business_id: str, body: StartIn, user: User = Depends(current_user)) -> dict:
    cfg = settings.get_all()
    if not cfg["recorder.enabled"]:
        raise HTTPException(403, "Live recording is switched off on this server. Upload a recording file instead.")
    flow = _flow(body.flow)
    with db.session() as conn:
        b = _owned(conn, business_id, user)
        if conn.execute("SELECT 1 FROM recordings WHERE business_id = ? AND status = 'recording'", (business_id,)).fetchone():
            raise HTTPException(409, "A recording is already running for this workspace. Finish or discard it first.")
    start_url = body.start_url.strip() or b["website_url"]
    if not start_url:
        raise HTTPException(400, "Add the website address first")
    try:
        start_url = safety.check(start_url, cfg["crawler.allow_private_urls"])
    except safety.UnsafeURL as exc:
        raise HTTPException(400, str(exc)) from exc
    rec_id = new_id("rec")
    title = body.title.strip() or flow.replace("_", " ").capitalize()
    with db.session() as conn:
        conn.execute(
            "INSERT INTO recordings (id, business_id, flow_name, title, source, status, created_by, uploaded_at)"
            " VALUES (?, ?, ?, ?, 'browser', 'recording', ?, ?)",
            (rec_id, business_id, flow, title, user.id, db.now()),
        )
        row = _get(conn, business_id, rec_id)
    session.start(rec_id, business_id, flow, title, start_url, cfg["recorder.max_minutes"])
    return _row_out(row)


def _save_upload(business_id: str, rec_id: str, body: store.UploadRecording, doc: dict, user: User, report: dict | None = None):
    store.save_screenshots(business_id, rec_id, body, doc)
    path = store.write(business_id, rec_id, doc)
    stamp = db.now()
    with db.session() as conn:
        conn.execute(
            "INSERT INTO recordings (id, business_id, flow_name, title, source, status, file_path, steps_count, actions_count,"
            " requests_count, created_by, uploaded_at, finished_at, scan) VALUES (?, ?, ?, ?, ?, 'finished', ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec_id, business_id, doc["flow"], doc["title"], doc["source"], path, *store.counts(doc).values(), user.id, stamp, stamp,
             json.dumps(report) if report else None),
        )
        return _row_out(_get(conn, business_id, rec_id))


@router.post("/recordings/upload", status_code=201)
def upload_recording(business_id: str, body: store.UploadRecording, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
    rec_id = new_id("rec")
    doc = store.from_upload(business_id, rec_id, body)
    _flow(doc["flow"])
    return _save_upload(business_id, rec_id, body, doc, user)


@router.post("/recordings/import")
def import_recording(business_id: str, body: store.UploadRecording, user: User = Depends(current_user)) -> dict:
    """A recording file from the Oasis Recorder extension, imported in Your tools: cleaned again,
    security-scanned, and when it passes, saved and handed to the AI to build the tool proposal
    the owner approves. A file that fails the scan is not kept."""
    with db.session() as conn:
        business = dict(_owned(conn, business_id, user))
    rec_id = new_id("rec")
    doc = store.from_upload(business_id, rec_id, body)
    _flow(doc["flow"])
    trackers = scan.drop_trackers(doc)
    report = scan.run(doc, business, scan.raw_header_count(body), trackers)
    if not report["ok"]:
        return {"ok": False, "scan": report}
    recording = _save_upload(business_id, rec_id, body, doc, user, report)
    proposal_id = propose.start_from_recording(business_id, rec_id, user.id)
    return {"ok": True, "scan": report, "recording": recording, "proposal_id": proposal_id}


@router.get("/recordings/{rec_id}")
def get_recording(business_id: str, rec_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        r = _get(conn, business_id, rec_id)
    out = _row_out(r)
    out["document"] = store.read(r["file_path"]) if r["file_path"] else None
    return out


@router.patch("/recordings/{rec_id}")
def update_recording(business_id: str, rec_id: str, body: PatchIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        r = _get(conn, business_id, rec_id)
    if not r["file_path"]:
        raise HTTPException(409, "The recording is not finished yet")
    doc = store.read(r["file_path"])
    for step in doc["steps"]:
        if step["n"] in body.notes:
            step["owner_note"] = mask_text(body.notes[step["n"]][:500], set())
    if body.title is not None and body.title.strip():
        doc["title"] = body.title.strip()
        db.update("recordings", rec_id, title=doc["title"])
    store.write(business_id, rec_id, doc)
    return get_recording(business_id, rec_id, user)


@router.post("/recordings/{rec_id}/finish", status_code=202)
def finish_recording(business_id: str, rec_id: str, user: User = Depends(current_user)) -> dict:
    return _stop(business_id, rec_id, user, "finish")


@router.post("/recordings/{rec_id}/cancel", status_code=202)
def cancel_recording(business_id: str, rec_id: str, user: User = Depends(current_user)) -> dict:
    return _stop(business_id, rec_id, user, "cancel")


def _stop(business_id: str, rec_id: str, user: User, outcome: str) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        _get(conn, business_id, rec_id)
    live = session.ACTIVE.get(rec_id)
    if live is None:
        raise HTTPException(409, "This recording is not running")
    live.request_stop(outcome)
    return {"ok": True}


@router.delete("/recordings/{rec_id}", status_code=204)
def delete_recording(business_id: str, rec_id: str, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _owned(conn, business_id, user)
        _get(conn, business_id, rec_id)
    if rec_id in session.ACTIVE:
        raise HTTPException(409, "Finish or discard the running recording first")
    store.discard(rec_id, business_id)


@router.get("/recordings/{rec_id}/download")
def download_recording(business_id: str, rec_id: str, user: User = Depends(current_user)) -> Response:
    with db.session() as conn:
        _owned(conn, business_id, user)
        r = _get(conn, business_id, rec_id)
    if not r["file_path"]:
        raise HTTPException(409, "The recording is not finished yet")
    body = json.dumps(store.read(r["file_path"]), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers={"content-disposition": f'attachment; filename="{r["flow_name"]}-{rec_id}.json"'})


@router.get("/recordings/{rec_id}/screenshots/{name}")
def recording_screenshot(business_id: str, rec_id: str, name: str, user: User = Depends(current_user)) -> FileResponse:
    with db.session() as conn:
        _owned(conn, business_id, user)
        _get(conn, business_id, rec_id)
    if not re.match(r"^step\d{1,3}\.jpg$", name):
        raise HTTPException(404, "No screenshot")
    path = store.rec_dir(business_id, rec_id) / name
    if not path.resolve().is_relative_to(FILES_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "No screenshot")
    return FileResponse(path, media_type="image/jpeg", headers={"cache-control": "no-cache"})


@router.get("/flows/{flow}/compare")
def compare_flow(business_id: str, flow: str, a: str | None = None, b: str | None = None, user: User = Depends(current_user)) -> dict:
    """Compare two finished recordings of a flow: the two newest, or the ones named by a and b."""
    with db.session() as conn:
        _owned(conn, business_id, user)
        if a and b:
            picked = [_get(conn, business_id, a), _get(conn, business_id, b)]
        else:
            picked = conn.execute(
                "SELECT * FROM recordings WHERE business_id = ? AND flow_name = ? AND status = 'finished' ORDER BY uploaded_at DESC LIMIT 2",
                (business_id, flow),
            ).fetchall()[::-1]
    if len(picked) < 2 or not all(r["file_path"] for r in picked):
        raise HTTPException(409, "Record this flow twice, with different values, to compare")
    result = compare_mod.compare(store.read(picked[0]["file_path"]), store.read(picked[1]["file_path"]))
    result["recordings"] = [{"id": r["id"], "title": r["title"], "uploaded_at": r["uploaded_at"]} for r in picked]
    return result
