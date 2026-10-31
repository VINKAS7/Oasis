"""The shared directory behind find_nearby and search_businesses: live businesses of any kind,
where they are (if anywhere), when they are open, and what they offer. A user's location is
used for one search and never stored."""

import json
import math
import re
from datetime import datetime
from typing import Any

import httpx

from .. import categories, db
from ..config import GEOCODER_CONTACT, USER_AGENT

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_geocache: dict[str, tuple[float, float] | None] = {}


class LocationError(ValueError):
    pass


async def locate(location: str) -> tuple[float, float]:
    """'47.56, 7.59' or a place name, through OpenStreetMap's Nominatim (cached in memory only)."""
    m = _COORDS.match(location or "")
    if m:
        return float(m.group(1)), float(m.group(2))
    key = (location or "").strip().lower()
    if not key:
        raise LocationError("Say where the user is: a place name or 'lat, lng'.")
    if key not in _geocache:
        try:
            async with httpx.AsyncClient(timeout=10, headers={"user-agent": f"{USER_AGENT} {GEOCODER_CONTACT}".strip()}) as client:
                resp = await client.get("https://nominatim.openstreetmap.org/search", params={"q": location, "format": "jsonv2", "limit": 1})
            hits = resp.json() if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            hits = []
        _geocache[key] = (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None
    if _geocache[key] is None:
        raise LocationError(f"Could not find “{location}”. Try a street or landmark with the city, or 'lat, lng'.")
    return _geocache[key]


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def is_open(hours: dict[str, Any], day: str, at: str) -> bool | None:
    """True/False if the owner gave hours for that day, None if unknown. Handles past-midnight closing."""
    h = hours.get(day)
    if not h:
        return None
    if h.get("closed"):
        return False
    start, end = h.get("open"), h.get("close")
    if not start or not end:
        return None
    return start <= at < end if start < end else (at >= start or at < end)


def corpus(conn, business: dict[str, Any]) -> str:
    """What a business offers, as text to match keywords against: its description, the website
    analysis, and the descriptions of its tools."""
    parts = [business["name"], business["type"], categories.label(business["type"]), business.get("category_label", ""), business["description"]]
    run = conn.execute("SELECT id, summary FROM crawl_runs WHERE business_id = ? AND summary IS NOT NULL ORDER BY id DESC LIMIT 1", (business["id"],)).fetchone()
    if run:
        parts.append(json.loads(run["summary"]).get("overview", ""))
        for (analysis,) in conn.execute("SELECT analysis FROM crawl_pages WHERE run_id = ? AND analysis IS NOT NULL", (run["id"],)):
            for info in json.loads(analysis).get("information", []):
                parts += [info.get("topic", ""), info.get("summary", ""), *info.get("facts", [])]
    for (desc,) in conn.execute(
        "SELECT v.description_for_ai FROM tools t JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
        " WHERE t.business_id = ? AND t.removed_at IS NULL AND t.enabled = 1",
        (business["id"],),
    ):
        parts.append(desc)
    return " ".join(p for p in parts if p).lower()


def matches_type(business: dict[str, Any], type_: str | None) -> bool:
    """A category id ("beauty") or free words ("barber", "bike repair") matched against how
    the business describes itself."""
    if not type_:
        return True
    t = type_.strip().lower()
    return t == business["type"] or t in categories.label(business["type"]).lower() or t in (business.get("category_label") or "").lower()


def _card(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "business_id": b["id"],
        "name": b["name"],
        "kind": categories.label(b["type"], b.get("category_label", "")),
        "online_only": bool(b["online_only"]),
        "address": "" if b["online_only"] else b["address"],
        "website": b["website_url"],
        "description": b["description"][:300],
    }


def search(query: str, type_: str | None, limit: int = 20) -> list[dict[str, Any]]:
    """Any live business, online or local, whose description and offer mention every word."""
    words = [w for w in (query or "").lower().split() if len(w) > 1]
    results = []
    with db.session() as conn:
        for b in map(dict, conn.execute("SELECT * FROM businesses WHERE status = 'live'").fetchall()):
            if not matches_type(b, type_):
                continue
            text = corpus(conn, b)
            missing = [w for w in words if w not in text]
            if type_ and missing:  # the right kind of business without what was asked for
                for w in missing:
                    conn.execute("INSERT INTO demand_log (business_id, keyword, created_at) VALUES (?, ?, ?)", (b["id"], w, db.now()))
            if missing:
                continue
            results.append({**_card(b), "score": sum(text.count(w) for w in words)})
    return sorted(results, key=lambda r: -r["score"])[:limit]


async def find(type_: str | None, location: str, radius_km: float, keywords: list[str], open_at: str | None, day: str | None) -> list[dict[str, Any]]:
    here = await locate(location)
    radius_km = max(0.1, min(radius_km or 2.0, 25.0))
    day = (day or DAYS[datetime.now().weekday()]).lower()[:3]
    words = [k.strip().lower() for k in keywords or [] if k.strip()]
    results = []
    with db.session() as conn:
        live = conn.execute("SELECT * FROM businesses WHERE status = 'live' AND online_only = 0 AND lat IS NOT NULL AND lng IS NOT NULL").fetchall()
        for b in map(dict, live):
            if not matches_type(b, type_):
                continue
            d = distance_km(here, (b["lat"], b["lng"]))
            if d > radius_km:
                continue
            text = corpus(conn, b)
            missing = [w for w in words if w not in text]
            # Nearby but without what the user wanted: that's demand the owner missed.
            for w in missing:
                conn.execute("INSERT INTO demand_log (business_id, keyword, created_at) VALUES (?, ?, ?)", (b["id"], w, db.now()))
            if missing:
                continue
            hours = json.loads(b["hours"] or "{}")
            open_state = is_open(hours, day, open_at) if open_at else None
            if open_at and open_state is False:
                continue
            results.append({**_card(b), "distance_km": round(d, 2), "open_at_requested_time": open_state})
    return sorted(results, key=lambda r: r["distance_km"])[:20]
