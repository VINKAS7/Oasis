"""Part B, step 1: visit the owner's website with a headless browser and keep what each page
shows and offers (text, headings, forms, buttons, JSON-LD, a screenshot).

Each crawl runs in its own thread with its own event loop. Playwright starts a browser
subprocess, which on Windows needs a Proactor loop; uvicorn's loop (a Selector loop under
--reload) cannot do that, so the crawl never shares it.
"""

import asyncio
import json
import logging
import sys
import threading
from collections import deque
from urllib import robotparser
from urllib.parse import urlsplit

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Route, async_playwright

from .. import catalog, db, settings
from ..config import FILES_DIR, USER_AGENT
from . import safety
from .analyze import analyze_run

log = logging.getLogger("agentready.crawler")

MAX_TEXT_CHARS = 60_000
MAX_SCREENSHOT_HEIGHT = 6000

# Runs in the page. Reads what a visitor sees and can do; never reads typed values.
EXTRACT_JS = r"""
() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const labelFor = (el) => {
    if (el.labels && el.labels.length) return clean(el.labels[0].innerText);
    return clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") || "");
  };
  const forms = [...document.forms].slice(0, 20).map((f, i) => ({
    ref: f.id ? `#${f.id}` : `form[${i}]`,
    action: f.getAttribute("action") ? f.action : "",
    method: (f.getAttribute("method") || "get").toLowerCase(),
    fields: [...f.elements]
      .filter((e) => e.name || e.id)
      .filter((e) => !["hidden"].includes(e.type))
      .slice(0, 40)
      .map((e) => ({
        tag: e.tagName.toLowerCase(),
        type: e.type || "",
        name: e.name || "",
        id: e.id || "",
        label: labelFor(e),
        required: !!e.required,
        options: e.tagName === "SELECT" ? [...e.options].slice(0, 30).map((o) => clean(o.text)) : undefined,
      })),
  }));
  return {
    title: clean(document.title),
    lang: document.documentElement.lang || "",
    meta_description: clean(document.querySelector('meta[name="description"]')?.content || ""),
    text: document.body ? document.body.innerText : "",
    headings: [...document.querySelectorAll("h1, h2, h3")]
      .map((h) => ({ level: h.tagName.toLowerCase(), text: clean(h.innerText) }))
      .filter((h) => h.text)
      .slice(0, 60),
    links: [...document.querySelectorAll("a[href]")]
      .map((a) => ({ href: a.href, text: clean(a.innerText).slice(0, 120) }))
      .slice(0, 400),
    forms,
    buttons: [...new Set([...document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]')]
      .map((b) => clean(b.innerText || b.value || b.getAttribute("aria-label")))
      .filter(Boolean))]
      .slice(0, 60),
    json_ld: [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((s) => s.textContent.trim())
      .filter(Boolean)
      .slice(0, 10),
  };
}
"""


def start_crawl(business_id: str, start_url: str) -> int:
    """Queue a crawl of start_url for the business and return the run id."""
    allow_private = settings.get("crawler.allow_private_urls")
    url = safety.check(start_url, allow_private)
    with db.session() as conn:
        busy = conn.execute(
            "SELECT id FROM crawl_runs WHERE business_id = ? AND status IN ('queued', 'crawling', 'analyzing')",
            (business_id,),
        ).fetchone()
        if busy:
            raise RuntimeError("A crawl is already running for this workspace")
        cur = conn.execute(
            "INSERT INTO crawl_runs (business_id, start_url, max_pages, created_at) VALUES (?, ?, ?, ?)",
            (business_id, url, settings.get("crawler.max_pages"), db.now()),
        )
        run_id = int(cur.lastrowid)
    threading.Thread(target=_thread_main, args=(run_id,), name=f"crawl-{run_id}", daemon=True).start()
    return run_id


def start_analysis(run_id: int) -> None:
    """Re-run only the AI pass on an existing crawl (after the admin sets up a provider, say)."""
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE crawl_runs SET status = 'analyzing', finished_at = NULL WHERE id = ? AND status IN ('done', 'failed')"
            " AND pages_done > 0",
            (run_id,),
        )
        if cur.rowcount == 0:
            raise RuntimeError("This crawl is still running or has no pages to analyse")
    threading.Thread(target=_thread_main, args=(run_id, True), name=f"analyze-{run_id}", daemon=True).start()


def _thread_main(run_id: int, analysis_only: bool = False) -> None:
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run(run_id, analysis_only))
    finally:
        loop.close()


def _update(run_id: int, **fields) -> None:
    db.update("crawl_runs", run_id, **fields)


async def _run(run_id: int, analysis_only: bool = False) -> None:
    try:
        if not analysis_only:
            _update(run_id, status="crawling", started_at=db.now())
            await crawl(run_id)
            _update(run_id, status="analyzing")
        await analyze_run(run_id)
        _update(run_id, status="done", error=None, finished_at=db.now())
    except Exception as exc:  # the thread is the last place this can be recorded
        log.exception("crawl %s failed", run_id)
        _update(run_id, status="failed", error=_friendly(exc), finished_at=db.now())


def _friendly(exc: Exception) -> str:
    msg = str(exc)
    if "Executable doesn't exist" in msg or "playwright install" in msg:
        return "The crawler browser is not installed. Run: uv --directory backend run playwright install chromium"
    return msg.splitlines()[0][:500] if msg else exc.__class__.__name__


async def _robots(start_url: str) -> robotparser.RobotFileParser | None:
    if not settings.get("crawler.respect_robots"):
        return None
    parts = urlsplit(start_url)
    rp = robotparser.RobotFileParser()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers={"user-agent": USER_AGENT}) as client:
            resp = await client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
        if resp.status_code >= 400:
            return None
        rp.parse(resp.text.splitlines())
        return rp
    except httpx.HTTPError:
        return None


async def crawl(run_id: int) -> None:
    with db.session() as conn:
        run = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
    start_url = run["start_url"]
    max_pages = run["max_pages"]
    cfg = settings.get_all()
    max_depth = cfg["crawler.max_depth"]
    timeout_ms = cfg["crawler.page_timeout_s"] * 1000
    allow_private = cfg["crawler.allow_private_urls"]
    robots = await _robots(start_url)

    shots_dir = FILES_DIR / run["business_id"] / f"crawl_{run_id}"
    shots_dir.mkdir(parents=True, exist_ok=True)

    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    seen = {start_url}
    documents: dict[str, str] = {}
    done = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})

        async def guard(route: Route) -> None:
            req = route.request
            if req.resource_type == "media":
                return await route.abort()
            if req.is_navigation_request():
                try:
                    safety.check(req.url, allow_private)
                except safety.UnsafeURL:
                    return await route.abort("blockedbyclient")
            await route.continue_()

        await context.route("**/*", guard)
        page = await context.new_page()
        try:
            while queue and done < max_pages:
                url, depth = queue.popleft()
                if robots and not robots.can_fetch(USER_AGENT, url):
                    continue
                record = await _visit(page, url, depth, timeout_ms, shots_dir, done + 1)
                if record.get("final_url") and not safety.same_site(record["final_url"], start_url):
                    record["error"] = f"Redirected off the website to {record['final_url']}"
                    record["links"] = []
                done += 1
                for link in record.get("links", []):
                    href = safety.normalize(link["href"]) if link["href"].startswith("http") else ""
                    if not href or not safety.same_site(href, start_url):
                        continue
                    ext = safety.extension(href)
                    if ext in safety.DOCUMENT_EXTENSIONS:
                        documents.setdefault(href, link["text"])
                    elif ext not in safety.SKIP_EXTENSIONS and href not in seen and depth + 1 <= max_depth:
                        seen.add(href)
                        queue.append((href, depth + 1))
                _save_page(run_id, record)
                _update(
                    run_id,
                    pages_done=done,
                    pages_found=min(len(seen), max_pages),
                    documents=json.dumps([{"url": u, "text": t} for u, t in documents.items()]),
                )
        finally:
            await context.close()
            await browser.close()

    if done == 0:
        raise RuntimeError("No page could be crawled (blocked by robots.txt?)")
    with db.session() as conn:
        ok = conn.execute("SELECT COUNT(*) FROM crawl_pages WHERE run_id = ? AND error IS NULL", (run_id,)).fetchone()[0]
    if ok == 0:
        raise RuntimeError("Every page failed to load; check that the website address is right and online")


async def _visit(page, url: str, depth: int, timeout_ms: int, shots_dir, n: int) -> dict:
    record: dict = {"url": url, "depth": depth}
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightError:
            pass  # busy pages (chat widgets, analytics) never go idle; what has loaded is enough
        record["status_code"] = resp.status if resp else None
        record["final_url"] = page.url
        record.update(await page.evaluate(EXTRACT_JS))
        record["text"] = record.get("text", "")[:MAX_TEXT_CHARS]
        try:  # menus, product grids...: repeated item blocks (see catalog.py)
            record["catalogs"] = await page.evaluate(catalog.DETECT_JS)
        except PlaywrightError:
            record["catalogs"] = []
        shot = shots_dir / f"page_{n:03d}.jpg"
        height = await page.evaluate("() => document.documentElement.scrollHeight")
        await page.screenshot(
            path=str(shot),
            type="jpeg",
            quality=60,
            full_page=True,
            clip={"x": 0, "y": 0, "width": 1280, "height": min(int(height or 900), MAX_SCREENSHOT_HEIGHT)},
        )
        record["screenshot_path"] = str(shot.relative_to(FILES_DIR)).replace("\\", "/")
        if resp and resp.status >= 400:
            record["error"] = f"The page answered HTTP {resp.status}"
    except PlaywrightError as exc:
        record["error"] = _friendly(exc)
    return record


def _save_page(run_id: int, r: dict) -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO crawl_pages (run_id, url, depth, status_code, title, meta_description, lang, text, headings,"
            " links, forms, buttons, json_ld, catalogs, screenshot_path, error, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                r.get("final_url") or r["url"],
                r["depth"],
                r.get("status_code"),
                r.get("title", ""),
                r.get("meta_description", ""),
                r.get("lang", ""),
                r.get("text", ""),
                json.dumps(r.get("headings", [])),
                json.dumps(r.get("links", [])),
                json.dumps(r.get("forms", [])),
                json.dumps(r.get("buttons", [])),
                json.dumps(r.get("json_ld", [])),
                json.dumps(r.get("catalogs", [])),
                r.get("screenshot_path"),
                r.get("error"),
                db.now(),
            ),
        )
