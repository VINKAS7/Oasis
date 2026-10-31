"""Recording files: one JSON file per recording in database/files/<business>/recordings/<id>/,
next to its step screenshots."""

import base64
import json
import shutil
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .. import db
from ..config import FILES_DIR
from . import clean

if TYPE_CHECKING:
    from .session import Recorder

FORMAT = "agentready.recording/1"


def rec_dir(business_id: str, rec_id: str):
    return FILES_DIR / business_id / "recordings" / rec_id


def _counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "steps_count": len(steps),
        "actions_count": sum(len(s.get("actions", [])) for s in steps),
        "requests_count": sum(len(s.get("requests", [])) for s in steps),
    }


def _tidy(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop steps where nothing happened (redirect hops), keep the last page, renumber."""
    kept = [s for i, s in enumerate(steps) if s["actions"] or s["requests"] or s["owner_note"] or i == len(steps) - 1]
    for n, s in enumerate(kept, start=1):
        s["n"] = n
    return kept


def write(business_id: str, rec_id: str, doc: dict[str, Any]) -> str:
    d = rec_dir(business_id, rec_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "recording.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str((d / "recording.json").relative_to(FILES_DIR)).replace("\\", "/")


def read(file_path: str) -> dict[str, Any]:
    return json.loads((FILES_DIR / file_path).read_text(encoding="utf-8"))


def save_live(rec: "Recorder") -> None:
    steps = _tidy(rec.snapshot())
    # Screenshots were saved under the step's original number; rename to match.
    for s in steps:
        if s["screenshot"] and s["screenshot"] != f"step{s['n']}.jpg":
            src, dst = rec.dir / s["screenshot"], rec.dir / f"step{s['n']}.jpg"
            if src.exists():
                src.replace(dst)
            s["screenshot"] = dst.name
    used = {s["screenshot"] for s in steps}
    for shot in rec.dir.glob("step*.jpg"):  # also leftover step*.tmp.jpg files
        if shot.name not in used:
            shot.unlink(missing_ok=True)
    doc = {
        "format": FORMAT,
        "flow": rec.flow,
        "title": rec.title,
        "business_id": rec.business_id,
        "recording_id": rec.id,
        "recorded_at": rec.started,
        "site": rec.start_url,
        "source": "browser",
        "steps": steps,
    }
    path = write(rec.business_id, rec.id, doc)
    db.update("recordings", rec.id, status="finished", file_path=path, finished_at=db.now(), **_counts(steps))


def discard(rec_id: str, business_id: str) -> None:
    with db.session() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
    shutil.rmtree(rec_dir(business_id, rec_id), ignore_errors=True)


# --- uploads -----------------------------------------------------------------------------


class UploadAction(BaseModel, extra="allow"):
    type: str
    selector: str = ""


class UploadStep(BaseModel, extra="allow"):
    n: int | None = None
    # A screenshot taken by the Chrome extension, as base64 JPEG/PNG (personal fields already covered).
    screenshot_data: str | None = Field(default=None, max_length=4_000_000)
    owner_note: str = Field(default="", max_length=500)
    page: str = ""
    url: str = ""
    actions: list[UploadAction] = Field(default_factory=list, max_length=500)
    requests: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class UploadRecording(BaseModel, extra="allow"):
    flow: str = Field(min_length=1, max_length=80)
    title: str = ""
    site: str = ""
    recorded_at: str = ""
    source: str = ""
    steps: list[UploadStep] = Field(min_length=1, max_length=100)


def from_upload(business_id: str, rec_id: str, up: UploadRecording) -> dict[str, Any]:
    """Store an uploaded recording, cleaned again: an upload is never trusted to be masked."""
    known: set[str] = set()
    steps = []
    for n, s in enumerate(up.steps, start=1):
        actions = [clean.clean_action(a.model_dump(), known) for a in s.actions]
        steps.append({
            "n": n,
            "page": clean.mask_text(s.page, known),
            "url": clean.mask_url(s.url, known) if s.url else "",
            "owner_note": clean.mask_text(s.owner_note, known),
            "screenshot": None,
            "actions": actions,
            "requests": [],
        })
    # Requests second, so personal values typed in any step are known when masking bodies.
    for step, s in zip(steps, up.steps):
        step["requests"] = [clean.mask_data({k: v for k, v in r.items() if k.lower() not in ("headers", "cookies")}, known) for r in s.requests]
    flow = clean.snake(up.flow)
    return {
        "format": FORMAT,
        "flow": flow,
        "title": up.title or flow.replace("_", " ").capitalize(),
        "business_id": business_id,
        "recording_id": rec_id,
        "recorded_at": up.recorded_at or db.now(),
        "site": up.site,
        "source": "extension" if up.source == "extension" else "upload",
        "steps": steps,
    }


def save_screenshots(business_id: str, rec_id: str, up: UploadRecording, doc: dict[str, Any]) -> None:
    """Keep the extension's step screenshots; anything that isn't a JPEG or PNG is dropped."""
    d = rec_dir(business_id, rec_id)
    d.mkdir(parents=True, exist_ok=True)
    for step, s in zip(doc["steps"], up.steps):
        if not s.screenshot_data:
            continue
        data = s.screenshot_data.split(",", 1)[-1]
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            continue
        if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG")) or len(raw) > 3_000_000:
            continue
        name = f"step{step['n']}.jpg"
        (d / name).write_bytes(raw)
        step["screenshot"] = name


def counts(doc: dict[str, Any]) -> dict[str, int]:
    return _counts(doc["steps"])
