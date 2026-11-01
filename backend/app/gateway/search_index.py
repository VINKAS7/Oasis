"""Search by meaning: a vector for every live business and every item it lists (an Oasis shop's
products, a crawled menu...), made by the embedding model the admin routes the
"search_embeddings" task to (e.g. qwen3-embedding on local Ollama).

Vectors live in the search_vectors table and are refreshed in the background whenever a
business is published, its products change or its catalog is read again; unchanged texts are
not embedded twice. When no embedding model is set up, or it fails, similar() returns None and
the directory ranks by keywords alone, so search never breaks."""

import array
import asyncio
import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from typing import Any

from .. import categories, db, vault
from ..ai import gateway
from ..ai.providers import ProviderError

TASK = "search_embeddings"
# Qwen3-Embedding works best with an instruction on the query side only.
QUERY_PREFIX = "Instruct: Given a customer's request, find the businesses, products, dishes or services that match it\nQuery: "
BATCH = 32
MAX_TEXT = 1500
SWEEP_EVERY_S = 600
QUERY_TIMEOUT_S = 10
BACKOFF_S = 60  # after a failure, don't call the model again for a while (search stays fast)

log = logging.getLogger("oasis.search")
_loop: asyncio.AbstractEventLoop | None = None
_lock = asyncio.Lock()
_pending: set[str | None] = set()
_scheduled = False
_vectors: dict[str, dict[str, array.array]] | None = None  # model -> "kind:ref" -> vector
_queries: "OrderedDict[tuple[str, str], array.array]" = OrderedDict()
_failed_until = 0.0  # query embeddings: skip the model until then (a query failed just now)
RETRIES = 2          # per indexing batch, with a growing pause


def _dot(a: array.array, b: array.array) -> float:
    return math.fsum(x * y for x, y in zip(a, b))


_sumprod = getattr(math, "sumprod", _dot)  # Python 3.12+; the slower sum elsewhere


def _route() -> gateway.Route | None:
    try:
        return gateway.resolve(TASK)
    except (gateway.AINotConfigured, vault.VaultError):
        return None


def _unit(values: list[float]) -> array.array:
    norm = math.sqrt(math.fsum(v * v for v in values)) or 1.0
    return array.array("f", (v / norm for v in values))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


# ---- what gets embedded ----------------------------------------------------------------------

def items_of(conn, business: dict[str, Any]) -> list[dict[str, Any]]:
    """What a business lists: an Oasis shop's active products, else the last items its catalog tools returned."""
    if business.get("shop_template"):
        from ..shop import catalog

        rows = conn.execute("SELECT * FROM products WHERE business_id = ? AND active = 1 ORDER BY sort, created_at", (business["id"],)).fetchall()
        return [catalog.item(r, business["shop_template"]) for r in rows]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for (items,) in conn.execute("SELECT items FROM item_snapshots WHERE business_id = ? ORDER BY fetched_at DESC", (business["id"],)):
        for i in json.loads(items):
            if isinstance(i, dict) and i.get("name") and (i.get("id") or i["name"]) not in seen:
                seen.add(i.get("id") or i["name"])
                out.append(i)
    return out


def item_ref(business_id: str, item: dict[str, Any]) -> str:
    return f"{business_id}:{item.get('id') or item.get('name')}"


def _flat(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_flat(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, (list, tuple)):
        return ", ".join(_flat(v) for v in value)
    return str(value)


def _documents(conn, b: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(kind, ref, text) for a business and each of its items."""
    items = items_of(conn, b)
    kind = categories.label(b["type"], b.get("category_label", ""))
    parts = [f"{b['name']} — {kind}.", b["description"]]
    run = conn.execute("SELECT summary FROM crawl_runs WHERE business_id = ? AND summary IS NOT NULL ORDER BY id DESC LIMIT 1", (b["id"],)).fetchone()
    if run:
        parts.append(json.loads(run["summary"]).get("overview", ""))
    sections = sorted({i.get("section") for i in items if i.get("section")})
    if sections:
        parts.append("Sections: " + ", ".join(sections) + ".")
    if items:
        parts.append("Offers: " + ", ".join(i["name"] for i in items[:60]) + ".")
    if not b["online_only"] and b["address"]:
        parts.append(f"Located at {b['address']}.")
    docs = [("business", b["id"], " ".join(p for p in parts if p)[:MAX_TEXT])]
    for i in items:
        text = f"{i['name']}" + (f" ({i['section']})" if i.get("section") else "") + f" — {kind} {b['name']}."
        for extra in (i.get("description"), _flat(i.get("attributes") or {}), _flat(i.get("options") or {})):
            if extra:
                text += f" {extra}"
        docs.append(("item", item_ref(b["id"], i), text[:MAX_TEXT]))
    return docs


# ---- keeping the index fresh -----------------------------------------------------------------

def start() -> None:
    """From the app's lifespan: remember the loop, index everything once, then sweep now and then."""
    global _loop
    _loop = asyncio.get_running_loop()
    _loop.create_task(_sweeper())


async def _sweeper() -> None:
    while True:
        try:
            await refresh()
        except Exception:  # noqa: BLE001 - the sweeper must survive anything
            log.exception("search index sweep failed")
        await asyncio.sleep(SWEEP_EVERY_S)


def schedule(business_id: str | None = None) -> None:
    """Refresh one business's vectors (None: all) soon, in the background. Safe from any thread."""
    global _scheduled
    forget_lexical()  # words are recounted on the next search
    _pending.add(business_id)
    if _loop is None or _scheduled:
        return
    _scheduled = True

    def kick() -> None:
        _loop.create_task(_drain())  # type: ignore[union-attr]

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        kick()
    else:
        _loop.call_soon_threadsafe(kick)


async def _drain() -> None:
    global _scheduled
    await asyncio.sleep(1.0)  # gather a burst of changes (several products saved at once)
    ids = set(_pending)
    _pending.clear()
    _scheduled = False
    try:
        await refresh(None if None in ids else sorted(i for i in ids if i))
    except Exception:  # noqa: BLE001
        log.exception("search index refresh failed")


async def refresh(business_ids: list[str] | None = None) -> int:
    """Embed what changed for these businesses (None: every live one); drop what's gone. Returns how many texts were embedded."""
    global _vectors
    route = _route()
    if route is None:
        return 0
    model = route.config.model
    async with _lock:
        with db.session() as conn:
            where, args = ("", ()) if business_ids is None else (f" AND id IN ({','.join('?' * len(business_ids))})", tuple(business_ids))
            live = [dict(r) for r in conn.execute(f"SELECT * FROM businesses WHERE status = 'live'{where}", args)]
            if business_ids is None:
                conn.execute("DELETE FROM search_vectors WHERE business_id NOT IN (SELECT id FROM businesses WHERE status = 'live')")
            else:
                gone = set(business_ids) - {b["id"] for b in live}
                for bid in gone:
                    conn.execute("DELETE FROM search_vectors WHERE business_id = ?", (bid,))
            docs = [(b["id"], *d) for b in live for d in _documents(conn, b)]
            ids = [b["id"] for b in live]
            existing = {}
            if ids:
                existing = {(r["kind"], r["ref"]): (r["model"], r["text_hash"]) for r in conn.execute(
                    f"SELECT kind, ref, model, text_hash FROM search_vectors WHERE business_id IN ({','.join('?' * len(ids))})", ids)}
        wanted = {(kind, ref) for _, kind, ref, _ in docs}
        todo = [d for d in docs if existing.get((d[1], d[2])) != (model, _digest(d[3]))]
        stale = [k for k in existing if k not in wanted]
        made: list[tuple[str, str, str, str, bytes]] = []
        failed = 0
        for at in range(0, len(todo), BATCH):
            chunk = todo[at:at + BATCH]
            vectors = None
            for attempt in range(RETRIES + 1):
                try:
                    vectors = await gateway.embed([d[3] for d in chunk], route=route)
                    break
                except ProviderError as exc:
                    if attempt == RETRIES:
                        log.warning("search index: embedding a batch failed (%s); those texts are found by words until the next sweep", exc)
                    else:
                        await asyncio.sleep(2 * (attempt + 1))
            if vectors is None:
                failed += 1
                if failed >= 3:  # the model is down: stop for now, the sweep tries again
                    break
                continue
            made += [(kind, ref, bid, _digest(text), _unit(v).tobytes()) for (bid, kind, ref, text), v in zip(chunk, vectors)]
        with db.session() as conn:
            for kind, ref in stale:
                conn.execute("DELETE FROM search_vectors WHERE kind = ? AND ref = ?", (kind, ref))
            conn.executemany(
                "INSERT INTO search_vectors (kind, ref, business_id, model, text_hash, vector, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(kind, ref) DO UPDATE SET business_id = excluded.business_id, model = excluded.model,"
                " text_hash = excluded.text_hash, vector = excluded.vector, updated_at = excluded.updated_at",
                [(kind, ref, bid, model, h, vec, db.now()) for kind, ref, bid, h, vec in made],
            )
        if made or stale:
            _vectors = None
            log.info("search index: %d embedded, %d removed (%s)", len(made), len(stale), model)
        return len(made)


# ---- searching -------------------------------------------------------------------------------

def _all_vectors(model: str) -> dict[str, array.array]:
    global _vectors
    if _vectors is None:
        _vectors = {}
        with db.session() as conn:
            for r in conn.execute("SELECT kind, ref, model, vector FROM search_vectors"):
                v = array.array("f")
                v.frombytes(r["vector"])
                _vectors.setdefault(r["model"], {})[f"{r['kind']}:{r['ref']}"] = v
    return _vectors.get(model, {})


async def similar(query: str) -> dict[str, float] | None:
    """Cosine similarity of the query with every indexed business ("business:<id>") and item
    ("item:<business id>:<item id>"). None when search by meaning isn't available right now."""
    global _failed_until
    query = " ".join((query or "").split())[:300]
    route = _route()
    if not query or route is None or time.monotonic() < _failed_until:
        return None
    model = route.config.model
    key = (model, query.lower())
    q = _queries.get(key)
    if q is None:
        try:
            vectors = await asyncio.wait_for(gateway.embed([QUERY_PREFIX + query], route=route), QUERY_TIMEOUT_S)
        except (ProviderError, asyncio.TimeoutError) as exc:
            _failed_until = time.monotonic() + BACKOFF_S
            log.warning("search: query embedding failed (%s); keyword search only", exc.__class__.__name__)
            return None
        q = _unit(vectors[0])
        _queries[key] = q
        while len(_queries) > 256:
            _queries.popitem(last=False)
    else:
        _queries.move_to_end(key)
    index = _all_vectors(model)
    if not index:
        schedule()  # the embedding model was just set up or changed: build the index now
        return None
    return {ref: _sumprod(q, v) for ref, v in index.items() if len(v) == len(q)}


# ---- words: BM25 statistics (built from the database, with or without an embedding model) ----

LEXICAL_TTL_S = 300
_lexical: "Lexical | None" = None
_lexical_at = 0.0


class Lexical:
    """BM25 indexes over every live item and business, the catalogue's option words, and each
    business's own document (to tell which query words a business itself explains)."""

    def __init__(self, items: list[dict[str, Any]], business_docs: dict[str, dict[str, list[str]]]):
        from . import bm25

        self.items = bm25.Index([bm25.item_fields(i) for i in items], bm25.ITEM_FIELDS, bm25.ITEM_STRONG)
        self.businesses = bm25.Index(list(business_docs.values()), bm25.BUSINESS_FIELDS, bm25.BUSINESS_STRONG)
        self.business_docs = business_docs
        self.options = bm25.option_vocab(items)


def business_fields(conn, b: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, list[str]]:
    from .bm25 import toks

    web: list[Any] = [i.get("description", "") for i in items]
    run = conn.execute("SELECT id, summary FROM crawl_runs WHERE business_id = ? AND summary IS NOT NULL ORDER BY id DESC LIMIT 1", (b["id"],)).fetchone()
    if run:
        web.append(json.loads(run["summary"]).get("overview", ""))
        for (analysis,) in conn.execute("SELECT analysis FROM crawl_pages WHERE run_id = ? AND analysis IS NOT NULL", (run["id"],)):
            for info in json.loads(analysis).get("information", []):
                web += [info.get("topic", ""), info.get("summary", ""), *info.get("facts", [])]
    for (desc,) in conn.execute(
        "SELECT v.description_for_ai FROM tools t JOIN tool_versions v ON v.tool_id = t.id AND v.version = t.current_version"
        " WHERE t.business_id = ? AND t.removed_at IS NULL AND t.enabled = 1",
        (b["id"],),
    ):
        web.append(desc)
    return {
        "name": toks(b["name"]),
        "kind": toks([b["type"], categories.label(b["type"]), b.get("category_label", "")]),
        "items": toks([[i.get("name", ""), i.get("section", ""), i.get("options") or {}, i.get("attributes") or {}] for i in items]),
        "description": toks(b["description"]),
        "web": toks(web),
    }


def lexical() -> Lexical:
    """The current BM25 statistics; rebuilt after a change (see schedule) or every few minutes."""
    global _lexical, _lexical_at
    if _lexical is None or time.monotonic() - _lexical_at > LEXICAL_TTL_S:
        items, docs = [], {}
        with db.session() as conn:
            for b in map(dict, conn.execute("SELECT * FROM businesses WHERE status = 'live'")):
                mine = items_of(conn, b)
                items += mine
                docs[b["id"]] = business_fields(conn, b, mine)
        _lexical, _lexical_at = Lexical(items, docs), time.monotonic()
    return _lexical


def forget_lexical() -> None:
    global _lexical
    _lexical = None
