"""The security scan of an imported recording file (made by the Oasis Recorder extension).

A file comes from outside Oasis and could have been edited, so before it becomes a recording (and
the AI turns it into a tool) it must pass these checks. Cleaning (store.from_upload) has already
masked passwords and personal details again and dropped headers and cookies; the scan reports that
and refuses files that are for another website, talk to private network addresses or have nothing
to learn from. Warnings don't block: the owner sees them, and still approves the tool before it is
added and checked."""

import json
from typing import Any
from urllib.parse import urlsplit

from .. import settings
from ..crawler import safety
from . import clean

PASS, WARN, FAIL = "pass", "warn", "fail"


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def drop_trackers(doc: dict[str, Any]) -> int:
    """Analytics, ads, consent banners and static files (icons, styles, fonts): never part of a
    flow a tool should replay, and they would widen the hosts a tool may contact."""
    dropped = 0
    for s in doc["steps"]:
        kept = [r for r in s["requests"] if not clean.is_noise(r.get("url", ""), (r.get("response") or {}).get("content_type", ""), r.get("body"))]
        dropped += len(s["requests"]) - len(kept)
        s["requests"] = kept
    return dropped


def _urls(doc: dict[str, Any]) -> list[str]:
    out = [doc.get("site") or ""]
    for s in doc["steps"]:
        out.append(s.get("url") or "")
        out += [r.get("url") or "" for r in s["requests"]]
        out += [a.get("frame_url") or "" for a in s["actions"]]
    return [u for u in out if u]


def run(doc: dict[str, Any], business: dict[str, Any], raw_headers: int, trackers: int) -> dict[str, Any]:
    """Scan a cleaned recording document for the workspace `business`."""
    checks = []
    steps = doc["steps"]
    actions = sum(len(s["actions"]) for s in steps)
    requests = sum(len(s["requests"]) for s in steps)
    checks.append(_check("File", PASS, f"An Oasis recording: {len(steps)} steps, {actions} actions, {requests} requests."))
    if not actions and not requests:
        checks.append(_check("Content", FAIL, "The recording has no actions or requests, so there is nothing to build a tool from."))

    # The recording must be of this workspace's website (or its test copy).
    own = {safety.site_key(u) for u in (business.get("website_url"), business.get("test_url")) if u}
    site = doc.get("site") or next((s["url"] for s in steps if s.get("url")), "")
    if not site.startswith(("http://", "https://")):
        checks.append(_check("Website", FAIL, "The file doesn't say which website was recorded."))
    elif not own:
        checks.append(_check("Website", WARN, f"Recorded on {safety.site_key(site)}. This workspace has no website address yet, so this can't be compared."))
    elif safety.site_key(site) not in own:
        checks.append(_check("Website", FAIL, f"Recorded on {safety.site_key(site)}, but this workspace's website is {', '.join(sorted(own))}. Import it in the right workspace."))
    else:
        checks.append(_check("Website", PASS, f"Recorded on this workspace's website ({safety.site_key(site)})."))

    # Every address: http(s) only, no passwords in it, and never a private or local network address.
    allow_private = settings.get("crawler.allow_private_urls")
    hosts: dict[str, str] = {}
    bad: list[str] = []
    for u in _urls(doc):
        parts = urlsplit(u)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            if parts.scheme not in ("", "about", "data", "blob"):
                bad.append(f"{u[:80]} (not a web address)")
            continue
        hosts.setdefault(parts.hostname.lower(), f"{parts.scheme}://{parts.netloc}/")
    unknown = []
    for host, url in hosts.items():
        try:
            safety.check(url, allow_private)
        except safety.UnsafeURL as exc:
            (unknown if str(exc).startswith("Could not find the host") else bad).append(f"{host}: {exc}")
    if bad:
        checks.append(_check("Addresses", FAIL, "Unsafe addresses: " + "; ".join(bad[:5])))
    else:
        checks.append(_check("Addresses", WARN if unknown else PASS,
                             f"{len(hosts)} web address{'es' if len(hosts) != 1 else ''}, none on a private network."
                             + (f" Not found right now: {', '.join(h.split(':')[0] for h in unknown[:5])}." if unknown else "")))

    # Already refused hosts (wrong website, private address) aren't repeated here.
    flagged = {b.split(":")[0] for b in bad} | ({safety.site_key(site)} if any(c["name"] == "Website" and c["status"] == FAIL for c in checks) else set())
    def ours(host: str) -> bool:  # the site itself or one of its subdomains (api.example.com)
        key = safety.site_key(f"https://{host}")
        return any(key == o or key.endswith("." + o) for o in own)

    others = sorted({h for h in hosts if own and not ours(h) and h not in flagged and safety.site_key(f"https://{h}") not in flagged})
    if others:
        checks.append(_check("Other websites", WARN,
                             f"The flow also talks to {', '.join(others[:6])}{'…' if len(others) > 6 else ''}. "
                             "Fine for a booking or payment provider; check the tool before you approve it."))
    if trackers:
        checks.append(_check("Tracking", PASS, f"Removed {trackers} tracking, ad or static-file request{'s' if trackers != 1 else ''} (icons, styles, cookie banners)."))

    masked = json.dumps(steps, ensure_ascii=False).count(clean.MASK)
    checks.append(_check("Personal data", PASS,
                         f"Cleaned again on import: {masked} value{'s' if masked != 1 else ''} masked (passwords, personal details, secrets)"
                         + (f", and the headers and cookies of {raw_headers} request{'s' if raw_headers != 1 else ''} removed." if raw_headers else ".")))
    return {"ok": not any(c["status"] == FAIL for c in checks), "checks": checks}


def raw_header_count(body: Any) -> int:
    """How many requests in the uploaded file carried headers or cookies (removed by cleaning)."""
    n = 0
    for s in body.steps:
        for r in s.requests:
            if any(k.lower() in ("headers", "cookies") for k in r):
                n += 1
    return n
