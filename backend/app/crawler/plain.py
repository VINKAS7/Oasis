"""Reading a page without the browser: one plain request (Oasis's own user agent) and the HTML it
returns. Used when the headless browser can't open a site, for example when its bot protection
drops automated browsers but still serves ordinary requests. Gives the same record as the browser
(title, text, headings, links, forms, buttons, JSON-LD), without a screenshot or catalogs: those
need a browser. Never pretends to be anything else."""

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from ..config import USER_AGENT
from ..runner.engine import html_text
from . import safety

MAX_HTML = 3_000_000
REDIRECTS = 4


class _Page(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title, self.lang, self.description = "", "", ""
        self.headings: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.buttons: list[str] = []
        self.json_ld: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self._stack: list[tuple[str, dict[str, str]]] = []  # open tags whose text we collect
        self._text: dict[int, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "meta" and a.get("name", "").lower() == "description":
            self.description = " ".join(a.get("content", "").split())
        elif tag == "form" and len(self.forms) < 20:
            self.forms.append({"ref": f"#{a['id']}" if a.get("id") else f"form[{len(self.forms)}]",
                               "action": urljoin(self.base, a["action"]) if a.get("action") else "",
                               "method": (a.get("method") or "get").lower(), "fields": []})
        elif tag in ("input", "select", "textarea") and self.forms and (a.get("name") or a.get("id")) and a.get("type") != "hidden":
            fields = self.forms[-1]["fields"]
            if len(fields) < 40:
                fields.append({"tag": tag, "type": a.get("type", ""), "name": a.get("name", ""), "id": a.get("id", ""),
                               "label": a.get("aria-label") or a.get("placeholder", ""), "required": "required" in a})
            if tag == "input" and a.get("type") in ("submit", "button") and a.get("value"):
                self.buttons.append(a["value"])
        if tag in ("title", "h1", "h2", "h3", "a", "button") or (tag == "script" and a.get("type") == "application/ld+json"):
            self._stack.append((tag, a))
            self._text[len(self._stack)] = []

    def handle_data(self, data: str) -> None:
        for depth in self._text:
            self._text[depth].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack or self._stack[-1][0] != tag:
            return
        depth = len(self._stack)
        _, a = self._stack.pop()
        raw = "".join(self._text.pop(depth, []))
        text = " ".join(raw.split())
        if tag == "title" and not self.title:
            self.title = text
        elif tag in ("h1", "h2", "h3") and text and len(self.headings) < 60:
            self.headings.append({"level": tag, "text": text})
        elif tag == "a" and a.get("href") and len(self.links) < 400:
            self.links.append({"href": urljoin(self.base, a["href"]), "text": text[:120]})
        elif tag == "button" and text:
            self.buttons.append(text)
        elif tag == "script" and raw.strip() and len(self.json_ld) < 10:
            self.json_ld.append(raw.strip())


async def fetch(url: str, depth: int, allow_private: bool, timeout_s: float) -> dict[str, Any]:
    """The page as a crawl record. Each redirect hop is checked like the browser's navigations."""
    record: dict[str, Any] = {"url": url, "depth": depth, "fetched_by": "http"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, headers={"user-agent": USER_AGENT}) as client:
            current = url
            for _ in range(REDIRECTS + 1):
                safety.check(current, allow_private)
                resp = await client.get(current)
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                break
    except (httpx.HTTPError, safety.UnsafeURL) as exc:
        record["error"] = f"Could not load the page ({exc.__class__.__name__}: {str(exc)[:120]})"
        return record
    record["status_code"] = resp.status_code
    record["final_url"] = current
    if resp.status_code >= 400:
        record["error"] = f"The page answered HTTP {resp.status_code}"
        return record
    if "html" not in resp.headers.get("content-type", "html"):
        record["error"] = f"Not a web page ({resp.headers.get('content-type')})"
        return record
    html = resp.text[:MAX_HTML]
    page = _Page(current)
    try:
        page.feed(html)
    except Exception:  # broken markup: keep what was read so far
        pass
    record.update({
        "title": page.title, "lang": page.lang, "meta_description": page.description,
        "text": html_text(html), "headings": page.headings, "links": page.links, "forms": page.forms,
        "buttons": list(dict.fromkeys(b for b in page.buttons if b))[:60], "json_ld": page.json_ld, "catalogs": [],
    })
    return record

