"""Owner workspaces (one per business) and their website crawls."""

import json
import re
import shutil
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .. import db, settings
from ..auth import User, current_user
from ..config import FILES_DIR, GEOCODER_CONTACT, USER_AGENT
from ..crawler import crawler, safety
from ..gateway import search_index
from ..ids import new_business_id

router = APIRouter(prefix="/api", tags=["workspaces"])

BusinessType = Literal[
    "restaurant", "cafe", "bar", "hotel", "hostel", "shop", "beauty", "health", "fitness", "services", "professional",
    "education", "activities", "events", "rental", "online", "other",
]
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _with_scheme(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    return url


class DayHours(BaseModel):
    closed: bool = False
    open: str = ""
    close: str = ""

    @field_validator("open", "close")
    @classmethod
    def _time(cls, v: str) -> str:
        if v and not _TIME.match(v):
            raise ValueError("use HH:MM")
        return v


class WorkspaceIn(BaseModel):
    type: BusinessType
    category_label: str = Field(default="", max_length=80)  # the owner's own words: "bike repair shop"
    online_only: bool = False
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    phone: str = Field(default="", max_length=40)
    hours: dict[str, DayHours] = Field(default_factory=dict)
    website_url: str = Field(default="", max_length=500)
    test_url: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=2000)
    crawl_enabled: bool = True  # read the website automatically; off: tools come from recordings only
    shop_template: Literal["", "clothing", "menu", "services", "general"] = ""  # an Oasis shop (no website needed)

    @field_validator("hours")
    @classmethod
    def _days(cls, v: dict[str, DayHours]) -> dict[str, DayHours]:
        unknown = set(v) - set(DAYS)
        if unknown:
            raise ValueError(f"unknown days: {', '.join(sorted(unknown))}")
        return v

    @field_validator("website_url", "test_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _with_scheme(v)


class WorkspacePatch(BaseModel):
    type: BusinessType | None = None
    category_label: str | None = Field(default=None, max_length=80)
    online_only: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = Field(default=None, max_length=40)
    hours: dict[str, DayHours] | None = None
    website_url: str | None = Field(default=None, max_length=500)
    test_url: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    accepts_orders: bool | None = None  # take orders through Oasis's order inbox
    crawl_enabled: bool | None = None  # read the website automatically
    shop_template: Literal["clothing", "menu", "services", "general"] | None = None  # a shop can change template, not stop being a shop

    @field_validator("website_url", "test_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _with_scheme(v) if v is not None else None


RUN_FIELDS = ("summary", "documents")


def _business_out(conn, b) -> dict:
    out = db.row(b, ("hours",))
    out["online_only"] = bool(out.get("online_only"))
    out["accepts_orders"] = bool(out.get("accepts_orders"))
    out["crawl_enabled"] = bool(out.get("crawl_enabled", 1))
    out["pending_orders"] = conn.execute("SELECT COUNT(*) FROM orders WHERE business_id = ? AND status = 'pending'", (b["id"],)).fetchone()[0]
    out.pop("signing_key_enc", None)
    run = conn.execute("SELECT * FROM crawl_runs WHERE business_id = ? ORDER BY id DESC LIMIT 1", (b["id"],)).fetchone()
    out["latest_run"] = db.row(run, RUN_FIELDS)
    return out


def _owned(conn, business_id: str, user: User):
    b = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if b is None or (b["owner_id"] != user.id and not user.is_admin):
        raise HTTPException(404, "Workspace not found")
    return b


def _crawl_allowed(b) -> None:
    if not b["crawl_enabled"]:
        raise HTTPException(409, "Reading the website is switched off for this workspace. Switch it on, or import recordings in Your tools.")


def _check_url(url: str) -> str:
    try:
        return safety.check(url, settings.get("crawler.allow_private_urls"))
    except safety.UnsafeURL as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role, "is_admin": user.is_admin}


@router.get("/workspaces")
def list_workspaces(user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        bs = conn.execute("SELECT * FROM businesses WHERE owner_id = ? ORDER BY created_at DESC", (user.id,)).fetchall()
        return [_business_out(conn, b) for b in bs]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user)) -> dict:
    if body.website_url:
        body.website_url = _check_url(body.website_url)
    if body.test_url:
        body.test_url = _check_url(body.test_url)
    stamp = db.now()
    with db.session() as conn:
        biz_id = new_business_id(conn, body.name)
        conn.execute(
            "INSERT INTO businesses (id, owner_id, type, category_label, online_only, name, address, lat, lng, phone, hours, website_url,"
            " test_url, description, crawl_enabled, shop_template, accepts_orders, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                biz_id, user.id, body.type, body.category_label.strip(), int(body.online_only), body.name.strip(), body.address.strip(), body.lat, body.lng,
                body.phone.strip(), json.dumps({k: v.model_dump() for k, v in body.hours.items()}),
                body.website_url, body.test_url, body.description.strip(),
                int(body.crawl_enabled and not body.shop_template), body.shop_template, int(bool(body.shop_template)), stamp, stamp,
            ),
        )
    if body.website_url and body.crawl_enabled and not body.shop_template:
        crawler.start_crawl(biz_id, body.website_url)
    with db.session() as conn:
        return _business_out(conn, _owned(conn, biz_id, user))


@router.get("/workspaces/{business_id}")
def get_workspace(business_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        return _business_out(conn, _owned(conn, business_id, user))


@router.patch("/workspaces/{business_id}")
def update_workspace(business_id: str, body: WorkspacePatch, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if "hours" in fields:
        fields["hours"] = json.dumps(fields["hours"] or {})
    for key in ("online_only", "accepts_orders", "crawl_enabled"):
        if key in fields:
            fields[key] = int(bool(fields[key]))
    for key in ("website_url", "test_url"):
        if fields.get(key):
            fields[key] = _check_url(fields[key])
    with db.session() as conn:
        _owned(conn, business_id, user)
    if fields:
        db.update("businesses", business_id, **fields, updated_at=db.now())
        search_index.schedule(business_id)
    with db.session() as conn:
        return _business_out(conn, _owned(conn, business_id, user))


@router.delete("/workspaces/{business_id}", status_code=204)
def delete_workspace(business_id: str, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _owned(conn, business_id, user)
        busy = conn.execute(
            "SELECT 1 FROM crawl_runs WHERE business_id = ? AND status IN ('queued', 'crawling', 'analyzing')", (business_id,)
        ).fetchone()
        if busy:
            raise HTTPException(409, "Wait for the running crawl to finish before deleting this workspace")
        if conn.execute("SELECT 1 FROM recordings WHERE business_id = ? AND status = 'recording'", (business_id,)).fetchone():
            raise HTTPException(409, "Finish or discard the running recording before deleting this workspace")
        conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
    shutil.rmtree(FILES_DIR / business_id, ignore_errors=True)


@router.post("/workspaces/{business_id}/crawl", status_code=202)
def start_crawl(business_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        b = _owned(conn, business_id, user)
    if not b["website_url"]:
        raise HTTPException(400, "Add the website address first")
    _crawl_allowed(b)
    _check_url(b["website_url"])
    try:
        run_id = crawler.start_crawl(business_id, b["website_url"])
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


@router.post("/workspaces/{business_id}/crawls/{run_id}/analyze", status_code=202)
def reanalyze(business_id: str, run_id: int, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _crawl_allowed(_owned(conn, business_id, user))  # the analysis opens the site's pages again
        if not conn.execute("SELECT 1 FROM crawl_runs WHERE id = ? AND business_id = ?", (run_id, business_id)).fetchone():
            raise HTTPException(404, "Crawl not found")
    try:
        crawler.start_analysis(run_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


@router.get("/workspaces/{business_id}/crawls")
def list_crawls(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _owned(conn, business_id, user)
        runs = conn.execute(
            "SELECT id, status, ai_status, pages_done, created_at, finished_at FROM crawl_runs WHERE business_id = ? ORDER BY id DESC LIMIT 20",
            (business_id,),
        ).fetchall()
        return db.rows(runs)


@router.get("/workspaces/{business_id}/crawls/{run_id}")
def get_crawl(business_id: str, run_id: int, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        run = conn.execute("SELECT * FROM crawl_runs WHERE id = ? AND business_id = ?", (run_id, business_id)).fetchone()
        if run is None:
            raise HTTPException(404, "Crawl not found")
        pages = conn.execute(
            "SELECT id, url, depth, status_code, title, error, screenshot_path IS NOT NULL AS has_screenshot, analysis,"
            " json_array_length(forms) AS form_count, length(text) AS text_length"
            " FROM crawl_pages WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    out = db.row(run, RUN_FIELDS)
    out["pages"] = []
    for p in db.rows(pages, ("analysis",)):
        a = p.pop("analysis") or {}
        p["has_screenshot"] = bool(p["has_screenshot"])
        p["page_kind"] = a.get("page_kind")
        p["purpose"] = a.get("purpose")
        p["analysis_error"] = a.get("error")
        p["injection_suspected"] = bool(a.get("injection_suspected"))
        out["pages"].append(p)
    return out


def _page(conn, business_id: str, page_id: int):
    p = conn.execute(
        "SELECT p.* FROM crawl_pages p JOIN crawl_runs r ON r.id = p.run_id WHERE p.id = ? AND r.business_id = ?",
        (page_id, business_id),
    ).fetchone()
    if p is None:
        raise HTTPException(404, "Page not found")
    return p


@router.get("/workspaces/{business_id}/pages/{page_id}")
def get_page(business_id: str, page_id: int, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        p = _page(conn, business_id, page_id)
    out = db.row(p, ("headings", "links", "forms", "buttons", "json_ld", "analysis"))
    out["has_screenshot"] = bool(out.pop("screenshot_path"))
    return out


@router.get("/workspaces/{business_id}/pages/{page_id}/screenshot")
def get_screenshot(business_id: str, page_id: int, user: User = Depends(current_user)) -> FileResponse:
    with db.session() as conn:
        _owned(conn, business_id, user)
        p = _page(conn, business_id, page_id)
    if not p["screenshot_path"]:
        raise HTTPException(404, "No screenshot")
    path = (FILES_DIR / p["screenshot_path"]).resolve()
    if not path.is_relative_to(FILES_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "No screenshot")
    return FileResponse(path, media_type="image/jpeg", headers={"cache-control": "private, max-age=3600"})


@router.get("/geocode")
async def geocode(q: str, _: User = Depends(current_user)) -> list[dict]:
    """Address search for the workspace form, through OpenStreetMap's Nominatim."""
    q = q.strip()
    if len(q) < 3:
        return []
    agent = f"{USER_AGENT} {GEOCODER_CONTACT}".strip()
    try:
        async with httpx.AsyncClient(timeout=10, headers={"user-agent": agent}) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search", params={"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 0}
            )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Address search is unavailable right now") from exc
    return [{"label": r["display_name"], "lat": float(r["lat"]), "lng": float(r["lon"])} for r in resp.json()]
