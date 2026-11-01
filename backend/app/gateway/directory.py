"""The shared directory behind find_nearby and search_businesses: live businesses of any kind,
where they are (if anywhere), when they are open, and what they offer. A user's location is
used for one search and never stored.

Relevance mixes two signals: words (matching.py: plurals, spellings, synonyms, typos) and
meaning (search_index.py: embeddings, when the admin set up an embedding model). Without
embeddings, words alone decide."""

import json
import math
import re
from datetime import datetime
from typing import Any

import httpx

from .. import categories, db
from ..config import GEOCODER_CONTACT, USER_AGENT
from . import bm25, matching, search_index

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_geocache: dict[str, tuple[float, float] | None] = {}
WIDEST_KM = 50.0  # how far find_nearby looks when nothing is within the radius


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


# ---- relevance: keywords and meaning ---------------------------------------------------------
# Cosine similarities from the embedding model (qwen3-embedding): below SEM_FLOOR a text has
# nothing to do with the query, from SEM_FULL on it is clearly about it. Measured on live shops:
# the right business scores 0.44-0.70, unrelated ones 0.25-0.42.
SEM_FLOOR, SEM_FULL = 0.35, 0.60
SEM_KEEP = 0.44           # a business kept on meaning alone needs at least this...
SEM_MARGIN = 0.10         # ...and to be close to the best one
MAX_ITEMS = 4


def _sem(sim: float | None) -> float:
    return 0.0 if sim is None else max(0.0, min(1.0, (sim - SEM_FLOOR) / (SEM_FULL - SEM_FLOOR)))


def _kind_filter(type_: str | None) -> tuple[str | None, str]:
    """A type that names a kind of business ("restaurant", "beauty") filters; anything else
    ("pizza", "barber") is what the user wants and joins the query words."""
    t = matching.fold(type_ or "").strip()
    if not t:
        return None, ""
    if t in categories.CATEGORIES or any(t in c["label"].lower() for c in categories.CATEGORIES.values()):
        return t, ""
    return None, type_ or ""


def _is_kind(b: dict[str, Any], t: str) -> bool:
    return t == b["type"] or t in categories.label(b["type"]).lower() or t in (b.get("category_label") or "").lower()


def _item_card(i: dict[str, Any]) -> dict[str, Any]:
    return {"id": i.get("id") or i.get("name"), "name": i["name"], "price": i.get("price") or ""}


def _card(b: dict[str, Any]) -> dict[str, Any]:
    local = not b["online_only"]
    return {
        "business_id": b["id"],
        "name": b["name"],
        "kind": categories.label(b["type"], b.get("category_label", "")),
        "online_only": bool(b["online_only"]),
        "address": b["address"] if local else "",
        "lat": b["lat"] if local else None,
        "lng": b["lng"] if local else None,
        "website": b["website_url"],
        "description": b["description"][:300],
    }


async def _rank(query: str, type_: str | None, keywords: list[str], businesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The businesses that offer what was asked, best first, each with its matching items.
    Keywords must all appear; the query matches by words (BM25) and by meaning (embeddings)."""
    kind, extra = _kind_filter(type_)
    if kind:
        businesses = [b for b in businesses if _is_kind(b, kind)]
    text = " ".join(x for x in (query, extra) if x).strip()
    words = matching.terms(text)
    required = [t for k in keywords for t in matching.terms(k)]
    lex = search_index.lexical()
    sims = await search_index.similar(text) if words else None
    scored = []
    with db.session() as conn:
        for b in businesses:
            doc = lex.business_docs.get(b["id"])
            items = search_index.items_of(conn, b)
            if doc is None:  # published a moment ago: count its words now
                doc = search_index.business_fields(conn, b, items)
            all_fields = tuple(bm25.BUSINESS_FIELDS)
            missing = [k for k in required if not lex.businesses.says(doc, k, all_fields)]
            if missing:  # nearby or the right kind, but without what the user wanted: demand the owner missed
                for k in missing:
                    conn.execute("INSERT INTO demand_log (business_id, keyword, created_at) VALUES (?, ?, ?)", (b["id"], k, db.now()))
                continue
            scored.append({"b": b, "doc": doc, "items": items, "bm": lex.businesses.score(doc, words) if words else 0.0})
    if not words:
        return [{**_card(s["b"]), "match": "all", "matching_items": []} for s in scored]
    best_bm = max((s["bm"] for s in scored), default=0.0) or 1.0
    for s in scored:
        b = s["b"]
        own = sims.get(f"business:{b['id']}") if sims else None
        item_sims = [sims.get(f"item:{search_index.item_ref(b['id'], i)}") for i in s["items"]] if sims else []
        best_item = max((x for x in item_sims if x is not None), default=None)
        candidates = [x for x in (own, best_item * 0.97 if best_item is not None else None) if x is not None]
        s["sim"] = max(candidates) if candidates else None
        context = {t for t in words if lex.businesses.says(s["doc"], t, ("name", "kind"))}
        shown, exact_items = bm25.select_items(s["items"], words, lex.items, lex.options, sims, _sem,
                                               lambda i, bid=b["id"]: f"item:{search_index.item_ref(bid, i)}", context)
        s["exact"] = (exact_items and shown is not s["items"]) or all(lex.businesses.says(s["doc"], t, ("name", "kind", "description")) for t in words)
        s["shown"] = shown if shown is not s["items"] else []
        s["score"] = 0.5 * s["bm"] / best_bm + 0.5 * _sem(s["sim"]) if sims else s["bm"] / best_bm
    top_sim = max((s["sim"] for s in scored if s["sim"] is not None), default=None)
    kept = []
    for s in scored:
        by_meaning = s["sim"] is not None and top_sim is not None and s["sim"] >= SEM_KEEP and s["sim"] >= top_sim - SEM_MARGIN
        if not (s["exact"] or by_meaning or (sims is None and s["score"] >= 0.5)):
            continue
        named = matching.name_similarity(text, s["b"]["name"]) >= 0.6  # the query is its name: every item fits
        kept.append({**_card(s["b"]), "match": "exact" if s["exact"] else "similar", "score": round(s["score"], 3),
                     "matching_items": [] if named else [_item_card(i) for i in s["shown"][:MAX_ITEMS]]})
    return sorted(kept, key=lambda r: (r["match"] != "exact", -r["score"]))


# ---- the directory's questions ---------------------------------------------------------------

def _live(where: str = "", args: tuple = ()) -> list[dict[str, Any]]:
    with db.session() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM businesses WHERE status = 'live'{where}", args)]


async def search(query: str, type_: str | None, limit: int = 20) -> list[dict[str, Any]]:
    """Any live business, online or local, that offers what the query asks for, best first. A
    query that names a business finds it first, even when misspelled."""
    found = await _rank(query, type_, [], _live())
    named = resolve(query, strict=True)
    if named and (not found or found[0]["business_id"] != named):
        b = _live(" AND id = ?", (named,))
        if b:
            found = [{**_card(b[0]), "match": "name", "matching_items": []}] + [f for f in found if f["business_id"] != named]
    return found[:limit]


async def find(query: str, type_: str | None, here: tuple[float, float], radius_km: float, keywords: list[str],
               open_at: str | None, day: str | None) -> dict[str, Any]:
    """Places near `here` that offer what was asked, nearest first. When none is within the
    radius, the nearest ones up to WIDEST_KM. Online-only businesses that match come separately."""
    radius_km = max(0.1, min(radius_km or 5.0, WIDEST_KM))
    words = _words(keywords)
    places = [b for b in _live(" AND online_only = 0 AND lat IS NOT NULL AND lng IS NOT NULL")
              if distance_km(here, (b["lat"], b["lng"])) <= WIDEST_KM]
    hits = await _rank(query, type_, words, places)
    for h in hits:
        h["distance_km"] = round(distance_km(here, (h["lat"], h["lng"])), 2)
    hits = _open_then(hits, places, open_at, day)
    hits.sort(key=lambda h: h["distance_km"])
    close = [h for h in hits if h["distance_km"] <= radius_km]
    online = await _online(query, type_, words)
    return {"businesses": (close or hits)[:20], "online": online, "radius_km": radius_km, "widened": not close and bool(hits)}


async def find_anywhere(query: str, type_: str | None, keywords: list[str], open_at: str | None, day: str | None) -> dict[str, Any]:
    """`find` when the user's location is unknown: the local places that offer what was asked,
    best match first and without distances, so the user sees them before sharing a location."""
    words = _words(keywords)
    places = _live(" AND online_only = 0")
    hits = _open_then(await _rank(query, type_, words, places), places, open_at, day)
    return {"businesses": hits[:20], "online": await _online(query, type_, words), "widened": False}


def _words(keywords: list[str] | None) -> list[str]:
    return [k.strip() for k in keywords or [] if k.strip()]


def _open_then(hits: list[dict[str, Any]], places: list[dict[str, Any]], open_at: str | None, day: str | None) -> list[dict[str, Any]]:
    """With open_at, keeps only the places open then (on `day`, default today), marking each."""
    if not open_at:
        return hits
    day = (day or DAYS[datetime.now().weekday()]).lower()[:3]
    hours = {b["id"]: json.loads(b["hours"] or "{}") for b in places}
    for h in hits:
        h["open_at_requested_time"] = is_open(hours.get(h["business_id"], {}), day, open_at)
    return [h for h in hits if h["open_at_requested_time"] is not False]


async def _online(query: str, type_: str | None, words: list[str]) -> list[dict[str, Any]]:
    """Online-only businesses that match, shown apart from the places (only for a real query)."""
    if not ((query or "").strip() or _kind_filter(type_)[1]):
        return []
    return (await _rank(query, type_, words, _live(" AND online_only = 1")))[:5]


def resolve(ref: str, strict: bool = False) -> str | None:
    """A live business's id from its id, its name, or a near spelling of its name ("Trattoria
    Basilco"). strict: only a confident name match (used to spot names inside search queries)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    live = _live()
    if any(b["id"] == ref for b in live):
        return ref
    best, score = None, 0.0
    for b in live:
        s = matching.name_similarity(ref, b["name"])
        if s > score:
            best, score = b["id"], s
    return best if score >= (0.85 if strict else 0.6) else None


async def rank_items(business_id: str, items: list[dict[str, Any]], query: str) -> tuple[list[dict[str, Any]], bool]:
    """One business's items that match a query, best first, and whether they match it exactly
    (when nothing does, the closest by meaning, or every item). Colour and size words filter, and
    each item carries `preselect` when the query names one of its options."""
    words = matching.terms(query)
    if not words or not items:
        return items, True
    lex = search_index.lexical()
    doc = lex.business_docs.get(business_id) or {}
    context = {t for t in words if doc and lex.businesses.says(doc, t, ("name", "kind"))}
    sims = await search_index.similar(query)
    return bm25.select_items(items, words, lex.items, lex.options, sims, _sem,
                             lambda i: f"item:{search_index.item_ref(business_id, i)}", context)
