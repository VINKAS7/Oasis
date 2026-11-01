"""The shared directory behind find_nearby and search_businesses: live businesses of any kind,
where they are (if anywhere), when they are open, and what they offer. A user's location is
used for one search and never stored.

Relevance mixes two signals: words (matching.py: plurals, spellings, synonyms, typos) and
meaning (search_index.py: embeddings, when the admin set up an embedding model). Without
embeddings, words alone decide."""

import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .. import categories, db
from ..config import GEOCODE_COUNTRIES, GEOCODER_CONTACT, TIMEZONE, USER_AGENT
from . import bm25, matching, search_index

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
WIDEST_KM = 50.0  # how far find_nearby looks when nothing is within the radius

# Place names already looked up. Places found are kept (up to GEOCACHE_MAX); "not found" only for a
# while, and a failed request (timeout, rate limit) not at all, so one bad moment doesn't stick.
GEOCACHE_MAX = 2000
MISS_TTL_S = 600
_geocache: "OrderedDict[str, tuple[tuple[float, float] | None, float]]" = OrderedDict()
_geo_lock: asyncio.Lock | None = None
_geo_last = 0.0  # Nominatim's usage policy: at most one request a second


class LocationError(ValueError):
    pass


async def _nominatim(location: str) -> list[dict[str, Any]] | None:
    """Hits for a place name, or None when the geocoder couldn't be asked (try again later)."""
    global _geo_last, _geo_lock
    _geo_lock = _geo_lock or asyncio.Lock()
    params: dict[str, Any] = {"q": location, "format": "jsonv2", "limit": 1}
    if GEOCODE_COUNTRIES:
        params["countrycodes"] = GEOCODE_COUNTRIES
    async with _geo_lock:
        wait = 1.0 - (time.monotonic() - _geo_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=10, headers={"user-agent": f"{USER_AGENT} {GEOCODER_CONTACT}".strip()}) as client:
                resp = await client.get("https://nominatim.openstreetmap.org/search", params=params)
                if resp.status_code == 200 and not resp.json() and GEOCODE_COUNTRIES:
                    # nothing in the preferred countries: anywhere (after the polite pause)
                    await asyncio.sleep(1.0)
                    resp = await client.get("https://nominatim.openstreetmap.org/search",
                                            params={k: v for k, v in params.items() if k != "countrycodes"})
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            _geo_last = time.monotonic()
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


async def locate(location: str) -> tuple[float, float]:
    """'47.56, 7.59' or a place name, through OpenStreetMap's Nominatim (cached in memory only).
    Places in GEOCODE_COUNTRIES (default Switzerland) are preferred, then anywhere."""
    m = _COORDS.match(location or "")
    if m:
        return float(m.group(1)), float(m.group(2))
    key = " ".join((location or "").lower().split())
    if not key:
        raise LocationError("Say where the user is: a place name or 'lat, lng'.")
    cached = _geocache.get(key)
    if cached and (cached[0] is not None or time.monotonic() - cached[1] < MISS_TTL_S):
        _geocache.move_to_end(key)
        found = cached[0]
    else:
        hits = await _nominatim(location.strip())
        if hits is None:
            raise LocationError(f"The map service didn't answer for “{location}”. Try again, or give 'lat, lng'.")
        found = (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None
        _geocache[key] = (found, time.monotonic())
        while len(_geocache) > GEOCACHE_MAX:
            _geocache.popitem(last=False)
    if found is None:
        raise LocationError(f"Could not find “{location}”. Try a street or landmark with the city, or 'lat, lng'.")
    return found


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


_HHMM = re.compile(r"^\s*(\d{1,2})(?:[:.h](\d{2}))?\s*$")


def minutes(text: Any) -> int | None:
    """"9:00", "09:00", "9.30", "18h" -> minutes after midnight; None if it isn't a time."""
    m = _HHMM.match(str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return h * 60 + mi if 0 <= h <= 24 and 0 <= mi < 60 else None


def _span(h: Any) -> "tuple[int, int] | bool | None":
    """A day's (open, close) in minutes; False when closed; None when unknown."""
    if not isinstance(h, dict) or not h:
        return None
    if h.get("closed"):
        return False
    start, end = minutes(h.get("open")), minutes(h.get("close"))
    return None if start is None or end is None else (start, end)


def is_open(hours: dict[str, Any], day: str, at: str) -> bool | None:
    """True/False if the owner gave hours for that day, None if unknown. A place that closes after
    midnight (18:00-02:00) is open at 01:00 the next day too."""
    t = minutes(at)
    if t is None or day not in DAYS:
        return None
    prev = _span(hours.get(DAYS[(DAYS.index(day) - 1) % 7]))
    if isinstance(prev, tuple) and prev[1] <= prev[0] and t < prev[1]:
        return True  # still the previous evening's opening
    span = _span(hours.get(day))
    if not isinstance(span, tuple):
        return span
    start, end = span
    return start <= t < end if start < end else t >= start


def _local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(TIMEZONE))
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now()


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


Kind = tuple[frozenset[str], frozenset[str]]  # category keys, and the type's own words


def _kind_filter(type_: str | None) -> tuple[Kind | None, str]:
    """A type that names a kind of business ("restaurant", "beauty", "bar") filters; anything else
    ("pizza", "barber") is what the user wants and joins the query words. Whole words only: "bar"
    is a bar, not a barbershop; "spa" isn't "spaghetti"."""
    t = matching.fold(type_ or "").strip()
    words = frozenset(matching.tokens(t)) - {"or", "and"}
    if not t or not words:
        return None, ""
    keys = frozenset(k for k, c in categories.CATEGORIES.items() if k == t or words <= set(matching.tokens(c["label"])))
    if keys:
        return (keys, words), ""
    return None, type_ or ""


def _is_kind(b: dict[str, Any], kind: Kind) -> bool:
    keys, words = kind
    return b["type"] in keys or (bool(b.get("category_label")) and words <= set(matching.tokens(b["category_label"])))


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


KEYWORD_KEEP = 0.5             # without a vector, a business is kept on words when it scores this much of the best...
STRONG = bm25.BUSINESS_STRONG  # ...and says a query word where it matters (not only deep in its website text)
MODE_MEANING, MODE_WORDS = "meaning+keywords", "keywords"


async def _rank(query: str, type_: str | None, keywords: list[str], businesses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """The businesses that offer what was asked, best first, each with its matching items, and the
    search mode. Keywords must all appear; the query matches by words (BM25) and by meaning
    (embeddings). A business without a vector yet (or during an embedding outage) is judged on words."""
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
    mode = MODE_MEANING if sims else MODE_WORDS
    if not words:
        return [{**_card(s["b"]), "match": "all", "matching_items": []} for s in scored], mode
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
        s["words"] = s["bm"] / best_bm
        s["score"] = 0.5 * s["words"] + 0.5 * _sem(s["sim"]) if s["sim"] is not None else s["words"]
        s["strong"] = any(lex.businesses.says(s["doc"], t, STRONG) for t in words)
    top_sim = max((s["sim"] for s in scored if s["sim"] is not None), default=None)
    kept = []
    for s in scored:
        by_meaning = s["sim"] is not None and top_sim is not None and s["sim"] >= SEM_KEEP and s["sim"] >= top_sim - SEM_MARGIN
        by_words = s["sim"] is None and s["strong"] and s["words"] >= KEYWORD_KEEP
        if not (s["exact"] or by_meaning or by_words):
            continue
        named = matching.name_similarity(text, s["b"]["name"]) >= 0.6  # the query is its name: every item fits
        kept.append({**_card(s["b"]), "match": "exact" if s["exact"] else "similar", "score": round(s["score"], 3),
                     "matching_items": [] if named else [_item_card(i) for i in s["shown"][:MAX_ITEMS]]})
    return sorted(kept, key=lambda r: (r["match"] != "exact", -r["score"])), mode


# ---- the directory's questions ---------------------------------------------------------------

def _live(where: str = "", args: tuple = ()) -> list[dict[str, Any]]:
    with db.session() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM businesses WHERE status = 'live'{where}", args)]


async def search(query: str, type_: str | None, limit: int = 20, with_mode: bool = False):
    """Any live business, online or local, that offers what the query asks for, best first. A
    query that names a business finds it first, even when misspelled. with_mode: (results, mode)."""
    found, mode = await _rank(query, type_, [], _live())
    named = resolve(query, strict=True)
    if named and (not found or found[0]["business_id"] != named):
        b = _live(" AND id = ?", (named,))
        if b:
            found = [{**_card(b[0]), "match": "name", "matching_items": []}] + [f for f in found if f["business_id"] != named]
    return (found[:limit], mode) if with_mode else found[:limit]


async def find(query: str, type_: str | None, here: tuple[float, float], radius_km: float, keywords: list[str],
               open_at: str | None, day: str | None) -> dict[str, Any]:
    """Places near `here` that offer what was asked, nearest first. When none is within the
    radius, the nearest ones up to WIDEST_KM. Online-only businesses that match come separately."""
    radius_km = max(0.1, min(radius_km or 5.0, WIDEST_KM))
    words = _words(keywords)
    places = [b for b in _live(" AND online_only = 0 AND lat IS NOT NULL AND lng IS NOT NULL")
              if distance_km(here, (b["lat"], b["lng"])) <= WIDEST_KM]
    hits, mode = await _rank(query, type_, words, places)
    for h in hits:
        h["distance_km"] = round(distance_km(here, (h["lat"], h["lng"])), 2)
    hits = _open_then(hits, places, open_at, day)
    # Places that offer exactly what was asked come first, nearest first; then the merely similar ones.
    hits.sort(key=lambda h: (h["match"] == "similar", h["distance_km"]))
    close = [h for h in hits if h["distance_km"] <= radius_km]
    online = await _online(query, type_, words)
    return {"businesses": (close or hits)[:20], "online": online, "radius_km": radius_km, "widened": not close and bool(hits),
            "search_mode": mode}


async def find_anywhere(query: str, type_: str | None, keywords: list[str], open_at: str | None, day: str | None) -> dict[str, Any]:
    """`find` when the user's location is unknown: the local places that offer what was asked,
    best match first and without distances, so the user sees them before sharing a location."""
    words = _words(keywords)
    places = _live(" AND online_only = 0")
    ranked, mode = await _rank(query, type_, words, places)
    hits = _open_then(ranked, places, open_at, day)
    return {"businesses": hits[:20], "online": await _online(query, type_, words), "widened": False, "search_mode": mode}


def _words(keywords: list[str] | None) -> list[str]:
    return [k.strip() for k in keywords or [] if k.strip()]


def _open_then(hits: list[dict[str, Any]], places: list[dict[str, Any]], open_at: str | None, day: str | None) -> list[dict[str, Any]]:
    """With open_at, keeps only the places open then (on `day`, default today), marking each."""
    if not open_at:
        return hits
    day = (day or DAYS[_local_now().weekday()]).lower()[:3]
    hours = {b["id"]: json.loads(b["hours"] or "{}") for b in places}
    for h in hits:
        h["open_at_requested_time"] = is_open(hours.get(h["business_id"], {}), day, open_at)
    return [h for h in hits if h["open_at_requested_time"] is not False]


async def _online(query: str, type_: str | None, words: list[str]) -> list[dict[str, Any]]:
    """Online-only businesses that match, shown apart from the places (only for a real query)."""
    if not ((query or "").strip() or _kind_filter(type_)[1]):
        return []
    return (await _rank(query, type_, words, _live(" AND online_only = 1")))[0][:5]


NAME_SURE = 0.85      # a name (or near spelling) is taken as that business only from this similarity...
NAME_MARGIN = 0.10    # ...and clearly ahead of every other business's name
NAME_CANDIDATE = 0.6  # names at least this close are offered when it's ambiguous
_ID_SHAPE = re.compile(r"^biz_[a-z0-9_]+$")


def resolve_ref(ref: str) -> dict[str, Any]:
    """Which live business a reference means, without guessing:
    {"status": "ok", "business_id", "name", "resolved_from"?} | {"status": "ambiguous", "candidates"} | {"status": "not_found"}.

    An exact id wins. Something shaped like an id (biz_...) that isn't one is not found: it was made
    up, and matching it to a similar name would pick some other business. A name or near spelling
    ("Trattoria Basilco") resolves when one business is clearly meant; "Cafe Centr" with both a Café
    Central and a Café Centrale is ambiguous."""
    ref = (ref or "").strip()
    if not ref:
        return {"status": "not_found"}
    live = _live()
    for b in live:
        if b["id"] == ref:
            return {"status": "ok", "business_id": b["id"], "name": b["name"]}
    if _ID_SHAPE.match(ref):
        return {"status": "not_found"}
    scored = sorted(((matching.name_similarity(ref, b["name"]), b) for b in live), key=lambda x: -x[0])
    exact = [b for sc, b in scored if sc >= 1.0]
    best = None
    if len(exact) == 1:
        best = exact[0]
    elif not exact and scored and scored[0][0] >= NAME_SURE and (len(scored) == 1 or scored[0][0] - scored[1][0] >= NAME_MARGIN):
        best = scored[0][1]
    if best is None:
        near = exact or ([b for sc, b in scored if sc >= NAME_CANDIDATE and sc >= scored[0][0] - NAME_MARGIN] if scored else [])
        if len(near) > 1:
            return {"status": "ambiguous", "candidates": [{"business_id": b["id"], "name": b["name"]} for b in near[:5]]}
        return {"status": "not_found"}
    out = {"status": "ok", "business_id": best["id"], "name": best["name"]}
    if best["name"] != ref:
        out["resolved_from"] = ref
    return out


def resolve(ref: str, strict: bool = False) -> str | None:
    """A live business's id from its id, its name, or a clear near spelling of its name; None when
    nothing (or more than one business) fits. `strict` is kept for callers: the rules are the same."""
    r = resolve_ref(ref)
    return r["business_id"] if r["status"] == "ok" else None


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
