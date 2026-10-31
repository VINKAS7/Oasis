"""Platform settings the admin edits (crawler limits, AI analysis switches), stored in app_settings."""

import json
from typing import Any

from . import db

DEFAULTS: dict[str, Any] = {
    "crawler.max_pages": 30,
    "crawler.max_depth": 3,
    "crawler.page_timeout_s": 20,
    "crawler.respect_robots": True,
    # Off by default: the crawler would otherwise reach localhost and private networks (SSRF).
    # Turn it on to crawl a demo site running on this computer.
    "crawler.allow_private_urls": False,
    # Owners record with the Chrome extension. This older server-side recorder opens a browser
    # window on the machine running the API; useful for a demo on one laptop, off by default.
    "recorder.enabled": False,
    "recorder.max_minutes": 20,
    "ai.analyze_pages": True,
    "ai.send_screenshots": False,
    "ai.user_requests_per_minute": 20,
}


def get_all() -> dict[str, Any]:
    with db.session() as conn:
        stored = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM app_settings")}
    return {k: stored.get(k, v) for k, v in DEFAULTS.items()}


def get(key: str) -> Any:
    return get_all()[key]


def update(values: dict[str, Any]) -> dict[str, Any]:
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise KeyError(", ".join(sorted(unknown)))
    with db.session() as conn:
        for key, value in values.items():
            expected = type(DEFAULTS[key])
            if expected is int and not isinstance(value, bool):
                value = int(value)
            elif not isinstance(value, expected):
                raise ValueError(f"{key} must be {expected.__name__}")
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
    return get_all()
