"""Runs a tool version. Tools are declarative (no code), so running one means: fill the
customer's values into the recorded request or steps, and only ever talk to allowed hosts.

Used by the checks (Part E) and, later, by the MCP gateway (Part F).
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Route, async_playwright

from .. import catalog
from ..config import USER_AGENT
from ..crawler import safety
from ..recorder.clean import MASK
from ..registry.rules import inputs_from_schema

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_WHOLE = re.compile(r"^\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}$")
TEXT_LIMIT = 20_000
TIMEOUT_S = 20
# Less text than this in the raw HTML: probably a JavaScript app (React, Vue...) showing a
# loading screen until its scripts run, so the page is rendered in a browser instead.
THIN_TEXT = 300


class InputError(ValueError):
    pass


class NotAllowed(RuntimeError):
    pass


@dataclass
class Tool:
    name: str
    runner: dict[str, Any]
    input_schema: dict[str, Any]


@dataclass
class Context:
    site: str                      # the business website
    allowed_hosts: set[str]        # where the tool may send anything
    allow_private: bool
    business: dict[str, Any] = field(default_factory=dict)
    base_override: str = ""        # a test copy of the booking system


@dataclass
class RunResult:
    ok: bool
    message: str
    output: Any = None
    text: str = ""
    status: int | None = None
    failed_step: int | None = None
    request: dict[str, Any] | None = None   # what was (or would be) sent, personal values masked
    sent: bool = False                      # something was really sent to the business


# --- inputs ---------------------------------------------------------------------------------


def validate_inputs(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for spec in inputs_from_schema(schema):
        name, kind = spec["name"], spec["type"]
        if name not in values or values[name] in (None, ""):
            if spec["required"]:
                raise InputError(f"Missing input: {name}")
            continue
        v = values[name]
        try:
            if kind == "integer":
                v = int(v)
            elif kind == "number":
                v = float(v)
            elif kind == "boolean":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
            elif kind == "date":
                date.fromisoformat(str(v))
                v = str(v)
            elif kind == "time":
                if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(v)):
                    raise ValueError
                v = str(v)
            else:
                v = str(v)
        except (TypeError, ValueError) as exc:
            raise InputError(f"{name} should be a {kind}") from exc
        out[name] = v
    return out


def _fill(template: str, values: dict[str, Any]) -> Any:
    whole = _WHOLE.match(template or "")
    if whole:
        return values.get(whole.group(1), "")
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), template or "")


def _cast(value: Any, kind: str) -> Any:
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
    except (TypeError, ValueError):
        return value
    return str(value)


def _set_path(body: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = body
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _masked(values: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    personal = {i["name"] for i in inputs_from_schema(schema) if i["personal"]}
    return {k: (MASK if k in personal else v) for k, v in values.items()}


# --- addresses -----------------------------------------------------------------------------


def resolve_url(ctx: Context, url: str) -> str:
    full = urljoin(ctx.site, url)
    if ctx.base_override and safety.same_site(full, ctx.site):
        base = urlsplit(ctx.base_override)
        parts = urlsplit(full)
        full = urlunsplit((base.scheme, base.netloc, parts.path, parts.query, ""))
    return full


def ensure_allowed(ctx: Context, url: str) -> None:
    host = urlsplit(url).hostname or ""
    if urlsplit(url).scheme not in ("http", "https"):
        raise NotAllowed(f"Only web addresses may be used, not {urlsplit(url).scheme}:")
    if host not in ctx.allowed_hosts and not safety.same_site(url, ctx.site):
        raise NotAllowed(f"{host} is not an address this tool may contact")
    try:
        safety.check(url, ctx.allow_private)
    except safety.UnsafeURL as exc:
        raise NotAllowed(str(exc)) from exc


# --- page text -----------------------------------------------------------------------------


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "article", "main",
                     "header", "footer", "nav", "aside", "ul", "ol", "table", "form", "title", "dt", "dd"):
            self.parts.append("\n")
        elif tag in ("td", "th"):
            # Without a separator "CHF 25" and "30 min" in the next cell read as "CHF 2530 min".
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(p.parts))
    text = re.sub(r"(?m)^[ \t]*\|[ \t]*", "", text)  # a row's first cell needs no separator
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:TEXT_LIMIT]


# --- runners -------------------------------------------------------------------------------


def build_request(tool: Tool, ctx: Context, values: dict[str, Any]) -> dict[str, Any]:
    r = tool.runner
    url = resolve_url(ctx, str(_fill(r.get("url", ""), values)))
    body: dict[str, Any] = {}
    for f in r.get("body_fields", []):
        _set_path(body, f["path"], _cast(_fill(str(f.get("value", "")), values), f.get("type", "string")))
    return {"method": r.get("method") or "GET", "url": url, "format": r.get("body_format", "json"), "body": body}


async def _http(tool: Tool, ctx: Context, values: dict[str, Any], dry: bool) -> RunResult:
    req = build_request(tool, ctx, values)
    ensure_allowed(ctx, req["url"])
    preview = {**req, "body": _masked(req["body"], tool.input_schema) if req["body"] else None}
    if dry:
        return RunResult(True, "Prepared the request but did not send it (dry run).", request=preview)
    kwargs: dict[str, Any] = {}
    if req["method"] != "GET" and req["body"]:
        if req["format"] == "form":
            kwargs["content"] = urlencode({k: v for k, v in req["body"].items()})
            kwargs["headers"] = {"content-type": "application/x-www-form-urlencoded"}
        else:
            kwargs["json"] = req["body"]
    elif req["body"]:
        kwargs["params"] = req["body"]
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, headers={"user-agent": USER_AGENT}) as client:
        try:
            resp = await client.request(req["method"], req["url"], **kwargs)
        except httpx.HTTPError as exc:
            return RunResult(False, f"Could not reach {urlsplit(req['url']).hostname} ({exc.__class__.__name__}).", request=preview, sent=True)
    text = resp.text[:TEXT_LIMIT]
    try:
        data = resp.json()
    except ValueError:
        data = None
    expected = tool.runner.get("success_status") or 0
    ok = resp.status_code == expected if expected else 200 <= resp.status_code < 300
    if not ok:
        return RunResult(False, f"The business answered HTTP {resp.status_code} instead of {expected or '2xx'}: {text[:200]}", output=data,
                         text=text, status=resp.status_code, request=preview, sent=True)
    fields = tool.runner.get("result_fields") or []
    if fields and isinstance(data, dict):
        missing = [f for f in fields if f not in data]
        if missing:
            return RunResult(False, f"The answer is missing {', '.join(missing)}.", output=data, text=text, status=resp.status_code, request=preview, sent=True)
        output = {f: data[f] for f in fields}
    else:
        output = data if data is not None else text[:2000]
    return RunResult(True, f"Worked: HTTP {resp.status_code}.", output=output, text=text, status=resp.status_code, request=preview, sent=True)


async def _page(tool: Tool, ctx: Context) -> RunResult:
    urls = tool.runner.get("source_urls") or []
    if not urls:
        return RunResult(False, "The tool has no page to read.")
    pages = []
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, headers={"user-agent": USER_AGENT}) as client:
        for u in urls:
            url = resolve_url(ctx, u)
            for _ in range(4):  # follow redirects ourselves, so each hop is checked
                ensure_allowed(ctx, url)
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    return RunResult(False, f"Could not open {url}: {exc.__class__.__name__}")
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                break
            if resp.status_code != 200:
                return RunResult(False, f"{urlsplit(url).path or '/'} answered HTTP {resp.status_code}.", status=resp.status_code)
            is_html = "html" in resp.headers.get("content-type", "")
            text = html_text(resp.text) if is_html else resp.text[:TEXT_LIMIT]
            if is_html and len(text) < THIN_TEXT:
                try:
                    rendered = await _rendered_text(ctx, url)
                except PlaywrightError:
                    rendered = ""
                if len(rendered) > len(text):
                    text = rendered
            if len(text) < 30:
                return RunResult(False, f"{urlsplit(url).path or '/'} has almost no text (it may need JavaScript).", status=200)
            pages.append({"url": url, "text": text})
    joined = "\n\n".join(p["text"] for p in pages)
    return RunResult(True, f"Read {len(pages)} page{'s' if len(pages) != 1 else ''}.", output={"pages": pages}, text=joined, status=200)


@asynccontextmanager
async def _rendered_page(ctx: Context, url: str) -> AsyncIterator[Any]:
    """The page after its scripts ran, as a visitor's browser shows it. Same rules as a replay:
    navigation only to the tool's own site, nothing on private addresses. Images, media and
    fonts are not loaded (their addresses are still in the page)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=USER_AGENT)

            async def guard(route: Route) -> None:
                req = route.request
                if req.resource_type in ("image", "media", "font"):
                    return await route.abort()
                try:
                    if req.is_navigation_request() or req.method != "GET":
                        ensure_allowed(ctx, req.url)
                    else:
                        safety.check(req.url, ctx.allow_private)  # scripts and data the app loads
                except (NotAllowed, safety.UnsafeURL):
                    return await route.abort("blockedbyclient")
                await route.continue_()

            await context.route("**/*", guard)
            page = await context.new_page()
            await page.goto(url, wait_until="load", timeout=TIMEOUT_S * 1000)
            try:  # apps fetch their content after load; don't wait forever on ones that keep polling
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightError:
                pass
            yield page
        finally:
            await browser.close()


async def _rendered_text(ctx: Context, url: str) -> str:
    async with _rendered_page(ctx, url) as page:
        text = await page.evaluate("document.body ? document.body.innerText : ''")
    text = re.sub(r"[ \t]+", " ", text or "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:TEXT_LIMIT]


async def _items(tool: Tool, ctx: Context) -> RunResult:
    """A catalog (menu, products...) as items: name, description, price, image, link. Read with the
    selector the crawl found, or from the page's JSON-LD; see catalog.py."""
    sources = tool.runner.get("sources") or []
    if not sources:
        return RunResult(False, "The tool has no page to read.")
    items: list[dict[str, Any]] = []
    for src in sources:
        url = resolve_url(ctx, src.get("url", ""))
        ensure_allowed(ctx, url)
        try:
            async with _rendered_page(ctx, url) as page:
                if src.get("jsonld"):
                    raw = catalog.jsonld_items(await page.evaluate(catalog.JSONLD_JS))
                else:
                    raw = await page.evaluate(catalog.ITEMS_JS, {"selector": src.get("item_selector", ""), "names": src.get("names", [])})
        except PlaywrightError as exc:
            return RunResult(False, f"Could not open {urlsplit(url).path or '/'}: {str(exc).splitlines()[0][:120]}")
        items += catalog.normalize(raw, url)
    if not items:
        return RunResult(False, "No items were found where the list used to be. The page may have changed: crawl the website again.", status=200)
    items = list({i["id"]: i for i in reversed(items)}.values())[::-1][: catalog.MAX_ITEMS]  # one of each across pages
    title = tool.runner.get("title") or "Items"
    text = "\n".join(f"{i['name']} | {i['price'] or 'no price'} | {i['description']}" for i in items)
    return RunResult(True, f"Found {len(items)} items.", output={"title": title, "items": items}, text=text, status=200)


def _owner(tool: Tool, ctx: Context) -> RunResult:
    b = ctx.business
    out: dict[str, Any] = {}
    for f in tool.runner.get("fields", []):
        v = b.get(f)
        if f == "hours" and isinstance(v, str):
            v = json.loads(v or "{}")
        if v not in (None, "", {}):
            out[f] = v
    if not out:
        return RunResult(False, "The workspace details this tool answers from are empty.")
    return RunResult(True, "Answered from the workspace details.", output=out, text=json.dumps(out, ensure_ascii=False))


async def _replay(tool: Tool, ctx: Context, values: dict[str, Any], dry: bool) -> RunResult:
    steps = tool.runner.get("steps") or []
    final = max((i for i, s in enumerate(steps) if s.get("type") in ("click", "submit", "press")), default=-1)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        async def guard(route: Route) -> None:
            req = route.request
            try:
                if req.is_navigation_request() or req.method != "GET":
                    ensure_allowed(ctx, req.url)
            except NotAllowed:
                return await route.abort("blockedbyclient")
            await route.continue_()

        await context.route("**/*", guard)
        page = await context.new_page()
        try:
            for n, step in enumerate(steps, start=1):
                kind, sel = step.get("type"), step.get("selector", "")
                value = _fill(str(step.get("value", "")), values)
                if dry and n - 1 == final:
                    text = html_text(await page.content())
                    return RunResult(True, f"Ran {n - 1} of {len(steps)} steps; stopped before the final one (dry run).", text=text)
                try:
                    if kind == "goto":
                        url = resolve_url(ctx, value or step.get("page", ""))
                        ensure_allowed(ctx, url)
                        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_S * 1000)
                    elif kind == "fill":
                        await page.fill(sel, str(value), timeout=10_000)
                    elif kind == "select":
                        try:
                            await page.select_option(sel, value=str(value), timeout=10_000)
                        except PlaywrightError:
                            await page.select_option(sel, label=str(value), timeout=10_000)
                    elif kind in ("check", "uncheck"):
                        await (page.check if kind == "check" else page.uncheck)(sel, timeout=10_000)
                    elif kind == "click":
                        await page.click(sel, timeout=10_000)
                    elif kind == "press":
                        await page.press(sel, str(value) or "Enter", timeout=10_000)
                    elif kind == "submit":
                        await page.locator(sel).evaluate("f => f.requestSubmit ? f.requestSubmit() : f.submit()")
                    if kind in ("click", "press", "submit"):
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except PlaywrightError:
                            pass
                except PlaywrightError as exc:
                    reason = str(exc).splitlines()[0][:200]
                    return RunResult(False, f"Step {n} ({kind} {sel}) failed: {reason}", failed_step=n, sent=n - 1 >= final >= 0)
            text = html_text(await page.content())
            return RunResult(True, f"Ran all {len(steps)} steps.", output={"final_page": page.url, "text": text[:4000]}, text=text, sent=final >= 0)
        finally:
            await browser.close()


async def run(tool: Tool, ctx: Context, values: dict[str, Any], *, dry: bool = False) -> RunResult:
    """Run the tool. Raises InputError for bad inputs and NotAllowed for forbidden addresses."""
    values = validate_inputs(tool.input_schema, values)
    kind = tool.runner.get("kind")
    if kind == "http_request":
        return await _http(tool, ctx, values, dry)
    if kind == "page_extract":
        return await _page(tool, ctx)
    if kind == "item_list":
        return await _items(tool, ctx)
    if kind == "owner_data":
        return _owner(tool, ctx)
    if kind == "browser_replay":
        return await _replay(tool, ctx, values, dry)
    raise NotAllowed(f"Unknown way of running a tool: {kind}")
