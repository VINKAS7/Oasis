"""Part C: record one flow while the owner does it in a real browser window.

The window opens on the machine running the API (the owner's laptop at the hackathon).
Like the crawler, each session runs in its own thread with its own event loop. Everything
captured is cleaned (clean.py) the moment it arrives, so raw personal values are never stored.
"""

import asyncio
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Error as PlaywrightError, Frame, Page, Request, Response, Route, async_playwright

from .. import db
from ..config import FILES_DIR, RECORDER_CDP_PORT, RECORDER_HEADLESS
from ..crawler import safety
from . import clean, store

log = logging.getLogger("agentready.recorder")

CAPTURE_JS = (Path(__file__).with_name("capture.js")).read_text(encoding="utf-8")
PANEL_HIDDEN = "#agentready-recorder { display: none !important; }"
# Covered with a grey box in every screenshot, like the values in the JSON.
PERSONAL_INPUTS = (
    "input[type=password], input[type=email], input[type=tel], input[autocomplete~=name], "
    "input[autocomplete^=given], input[autocomplete^=family], input[autocomplete^=cc-], input[autocomplete^=tel], "
    "input[autocomplete^=email], input[autocomplete*=address], input[autocomplete=postal-code]"
)

# Recording id -> live session, so the API can show progress and stop it.
ACTIVE: dict[str, "Recorder"] = {}


class Recorder:
    def __init__(self, rec_id: str, business_id: str, flow: str, title: str, start_url: str, max_minutes: int) -> None:
        self.id = rec_id
        self.business_id = business_id
        self.flow = flow
        self.title = title
        self.start_url = start_url
        self.max_minutes = max_minutes
        self.dir = FILES_DIR / business_id / "recordings" / rec_id
        self.started = db.now()
        self.steps: list[dict[str, Any]] = []
        self.known: set[str] = set()  # personal values typed in this session, masked everywhere
        self.outcome = "finish"
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop: asyncio.Event | None = None
        self.page: Page | None = None
        self._req_step: dict[int, int] = {}
        self._bodies: dict[int, asyncio.Future] = {}
        self._write_bodies: dict[int, bytes] = {}
        self._personal_selectors: set[str] = set()
        self._shot_tasks: dict[str, asyncio.Task] = {}
        self._last_progress = 0.0
        self._url = start_url  # raw URL of the current step's page (step["url"] is masked)
        self._new_step(start_url)

    # --- called from API threads ---------------------------------------------------------

    def request_stop(self, outcome: str) -> None:
        self.outcome = outcome
        if self.loop and self.stop:
            self.loop.call_soon_threadsafe(self.stop.set)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.steps]

    # --- steps ---------------------------------------------------------------------------

    @property
    def step(self) -> dict[str, Any]:
        return self.steps[-1]

    def _new_step(self, url: str, force: bool = False) -> None:
        self._url = url
        if self.steps and not force and not self.step["actions"] and not self.step["requests"] and not self.step["owner_note"]:
            self.step.update(url=clean.mask_url(url, self.known), page=self._page_label(url))
            return
        n = len(self.steps) + 1
        self.steps.append({"n": n, "page": self._page_label(url), "url": clean.mask_url(url, self.known), "owner_note": "", "screenshot": None, "actions": [], "requests": []})

    def _page_label(self, url: str) -> str:
        if safety.same_site(url, self.start_url):
            parts = urlsplit(url)
            return parts.path + (f"?{parts.query}" if parts.query else "")
        return clean.mask_url(url, self.known)

    def _state(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "step": self.step["n"],
            "note": self.step["owner_note"],
            "actions": len(self.step["actions"]),
            "requests": sum(len(s["requests"]) for s in self.steps),
        }

    def _progress(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_progress < 1.0:
            return
        self._last_progress = time.monotonic()
        db.update(
            "recordings",
            self.id,
            steps_count=len(self.steps),
            actions_count=sum(len(s["actions"]) for s in self.steps),
            requests_count=sum(len(s["requests"]) for s in self.steps),
        )

    # --- browser events ------------------------------------------------------------------

    async def _binding(self, source: dict[str, Any], kind: str, data: dict[str, Any]) -> Any:
        frame: Frame = source["frame"]
        if kind == "state":
            return self._state()
        if kind == "note":
            self.step["owner_note"] = clean.mask_text(str(data.get("text", ""))[:500], self.known)
            return None
        if kind == "next_step":
            self.step["owner_note"] = clean.mask_text(str(data.get("text", ""))[:500], self.known)
            await self._screenshot()
            self._new_step(frame.page.url, force=True)
            await self._screenshot()
            return self._state()
        if kind in ("finish", "cancel"):
            if kind == "finish":
                self.step["owner_note"] = clean.mask_text(str(data.get("text", ""))[:500], self.known) or self.step["owner_note"]
            self.outcome = kind
            self.stop.set()
            return None
        if kind not in ("click", "fill", "select", "check", "uncheck", "press", "submit"):
            return None

        action = clean.clean_action({"type": kind, **data}, self.known)
        if frame != frame.page.main_frame:
            action["frame_url"] = clean.mask_url(frame.url, self.known)
        elif action.get("personal") and action.get("selector"):
            self._personal_selectors.add(action["selector"])
        actions = self.step["actions"]
        # Typing fires several events for one field; keep only its final value.
        if kind == "fill" and actions and actions[-1]["type"] == "fill" and actions[-1]["selector"] == action.get("selector"):
            actions[-1] = action
        else:
            actions.append(action)
        if kind in ("click", "press", "submit"):
            await self._screenshot()  # now, before the page moves on
        else:
            self._schedule_screenshot("action", 0.6)
        self._progress()
        return None

    def _attach(self, page: Page) -> None:
        self.page = page

        def navigated(frame: Frame) -> None:
            if frame == page.main_frame and frame.url.startswith("http"):
                self.page = page
                if frame.url.split("#")[0] != self._url.split("#")[0] or self.step["actions"]:
                    self._new_step(frame.url)
                self._schedule_screenshot("load", 0.8)

        def closed(_: Page) -> None:
            if not page.context.pages and self.stop:
                self.stop.set()  # the owner closed the last window: treat it as Finish

        page.on("framenavigated", navigated)
        page.on("close", closed)

    def _on_request(self, request: Request) -> None:
        self._req_step[id(request)] = self.step["n"]

    def _on_response(self, response: Response) -> None:
        # Start reading the body right away: pages often navigate as soon as they have the
        # answer, and then the browser drops the body.
        req = response.request
        ct = response.headers.get("content-type", "")
        if req.resource_type in ("xhr", "fetch") and req.method == "GET" and ("json" in ct or "text" in ct):
            future = asyncio.ensure_future(response.body())
            future.add_done_callback(lambda f: f.cancelled() or f.exception())  # a lost body is expected, not an error
            self._bodies[id(req)] = future

    async def _route(self, route: Route) -> None:
        """Requests that change something (the booking POST) pass through here, so their
        answer is kept even when the page navigates away the moment it arrives."""
        req = route.request
        if req.resource_type in ("xhr", "fetch") and req.method != "GET" and not clean.is_tracker(req.url):
            try:
                resp = await route.fetch()
            except PlaywrightError:
                await route.abort("failed")  # never send it twice
                return
            self._write_bodies[id(req)] = await resp.body()
            await route.fulfill(response=resp)
            return
        await route.continue_()

    async def _on_finished(self, request: Request) -> None:
        await self._capture_request(request, failed=None)

    async def _on_failed(self, request: Request) -> None:
        await self._capture_request(request, failed=request.failure or "failed")

    async def _capture_request(self, request: Request, failed: str | None) -> None:
        n = self._req_step.pop(id(request), self.step["n"])
        if failed:
            self._bodies.pop(id(request), None)
            self._write_bodies.pop(id(request), None)
        if request.resource_type not in clean.KEPT_RESOURCE_TYPES or clean.is_tracker(request.url):
            return
        if request.resource_type == "document" and request.method == "GET":
            return  # page loads are already the steps
        try:
            headers = await request.all_headers()
            entry: dict[str, Any] = {
                "method": request.method,
                "url": self._page_label(request.url),
                "type": request.resource_type,
                "content_type": headers.get("content-type", "").split(";")[0],
                "body": clean.parse_body(request.post_data, headers.get("content-type", ""), self.known),
            }
            if failed:
                entry["error"] = failed
            else:
                response = await request.response()
                if response is not None:
                    ct = response.headers.get("content-type", "")
                    body = None
                    raw = self._write_bodies.pop(id(request), None)
                    pending = self._bodies.pop(id(request), None)
                    if raw is None and pending is not None:
                        try:
                            raw = await pending
                        except PlaywrightError:
                            raw = None
                    if raw is not None and ("json" in ct or "text" in ct):
                        body = clean.parse_body(raw.decode("utf-8", "replace"), ct, self.known)
                    entry["response"] = {"status": response.status, "content_type": ct.split(";")[0], "body": body}
        except PlaywrightError:
            return
        step = next((s for s in self.steps if s["n"] == n), self.step)
        step["requests"].append(entry)
        self._progress()

    # --- screenshots ---------------------------------------------------------------------

    def _schedule_screenshot(self, slot: str, delay: float) -> None:
        """Debounced screenshot of the current step. Skipped if a new step has started."""
        previous = self._shot_tasks.get(slot)
        if previous and not previous.done():
            previous.cancel()
        n = self.step["n"]

        async def later() -> None:
            await asyncio.sleep(delay)
            if self.step["n"] == n:
                await self._screenshot()

        self._shot_tasks[slot] = asyncio.ensure_future(later())

    async def _screenshot(self) -> None:
        page = self.page
        if page is None or page.is_closed():
            return
        step, url = self.step, page.url
        tmp = self.dir / f"step{step['n']}.tmp.jpg"
        masks = [page.locator(PERSONAL_INPUTS), *(page.locator(sel) for sel in self._personal_selectors)]
        try:
            await page.screenshot(path=str(tmp), type="jpeg", quality=65, style=PANEL_HIDDEN, mask=masks, mask_color="#a8a29e", timeout=5000)
        except PlaywrightError:
            return  # the page was mid-navigation; the next event takes another
        if self.step is not step or page.url != url:
            tmp.unlink(missing_ok=True)  # the page moved on while we took it: it shows the next step
            return
        tmp.replace(self.dir / f"step{step['n']}.jpg")
        step["screenshot"] = f"step{step['n']}.jpg"

    # --- run -----------------------------------------------------------------------------

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        self.dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="agentready-rec-") as profile:
            async with async_playwright() as pw:
                # A persistent context on a throwaway profile: one window, no stray blank
                # tab, and closing the window ends the recording.
                args = [f"--remote-debugging-port={RECORDER_CDP_PORT}"] if RECORDER_CDP_PORT else []
                context: BrowserContext = await pw.chromium.launch_persistent_context(
                    profile, headless=RECORDER_HEADLESS, args=args, viewport={"width": 1280, "height": 820}
                )
                closed = False

                def on_close(_: BrowserContext) -> None:
                    nonlocal closed
                    closed = True
                    self.stop.set()

                context.on("close", on_close)
                await context.expose_binding("__arRecord", self._binding)
                await context.add_init_script(CAPTURE_JS)
                await context.route("**/*", self._route)
                context.on("page", self._attach)
                context.on("request", self._on_request)
                context.on("response", self._on_response)
                context.on("requestfinished", self._on_finished)
                context.on("requestfailed", self._on_failed)
                if context.pages:
                    page = context.pages[0]
                    self._attach(page)  # opened with the window, before our "page" handler existed
                else:
                    page = await context.new_page()
                try:
                    await page.goto(self.start_url, wait_until="domcontentloaded", timeout=30_000)
                except PlaywrightError as exc:
                    log.warning("recording %s: start page did not load: %s", self.id, exc)
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=self.max_minutes * 60)
                except TimeoutError:
                    self.outcome = "finish"
                if self.outcome == "finish" and not closed:
                    await self._screenshot()
                if not closed:
                    try:
                        await context.close()
                    except PlaywrightError:
                        pass


def start(rec_id: str, business_id: str, flow: str, title: str, start_url: str, max_minutes: int) -> None:
    rec = Recorder(rec_id, business_id, flow, title, start_url, max_minutes)
    ACTIVE[rec_id] = rec
    threading.Thread(target=_thread_main, args=(rec,), name=f"record-{rec_id}", daemon=True).start()


def _thread_main(rec: Recorder) -> None:
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        loop.run_until_complete(rec.run())
        if rec.outcome == "cancel":
            store.discard(rec.id, rec.business_id)
        else:
            store.save_live(rec)
    except Exception as exc:  # the thread is the last place this can be recorded
        log.exception("recording %s failed", rec.id)
        msg = str(exc).splitlines()[0][:400] if str(exc) else exc.__class__.__name__
        if "Missing X server" in msg or "DISPLAY" in msg:
            msg = "The recorder needs a screen: it opens a browser window on the computer running AgentReady. Upload a recording instead."
        db.update("recordings", rec.id, status="failed", error=msg, finished_at=db.now())
    finally:
        ACTIVE.pop(rec.id, None)
        loop.close()
