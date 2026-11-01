"""Part C cleaning: what a recording may keep. Passwords, cookies, tokens and personal
details are masked before anything is stored; images, fonts and tracking are dropped."""

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MASK = "[MASKED]"
BODY_LIMIT = 20_000

# Field names (after snake_casing) that hold a guest's personal details or a secret.
_PERSONAL = re.compile(
    r"(^|_)(name|firstname|lastname|fullname|surname|vorname|nachname|guest|email|e_mail|mail|phone|telephone|tel|mobile|"
    r"handy|address|street|strasse|city|zip|postcode|postal|plz|birthday|birthdate|dob|card|cc|ccnum|cvc|cvv|iban|"
    r"password|passwd|pwd|pin)($|_)"
)
_SECRET = re.compile(r"(password|passwd|pwd|token|csrf|xsrf|secret|session|sessid|auth|api_?key|signature|nonce|cookie)", re.I)
_PERSONAL_AUTOCOMPLETE = re.compile(r"^(name|given-name|family-name|additional-name|nickname|email|tel.*|street-address|address-.*|postal-code|country|cc-.*|bday.*|username|current-password|new-password|one-time-code)$")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<![\w-])(?:\+|00)\d[\d\s\-/().]{6,}\d|\b0\d{2}[\s\-/]?\d{3}[\s\-/]?\d{2}[\s\-/]?\d{2}\b")
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")

TRACKERS = (
    "google-analytics.com", "googletagmanager.com", "doubleclick.net", "googleadservices.com", "google.com/recaptcha",
    "facebook.net", "facebook.com/tr", "connect.facebook", "hotjar.com", "hotjar.io", "segment.io", "segment.com",
    "mixpanel.com", "amplitude.com", "sentry.io", "clarity.ms", "bing.com/bat", "tiktok.com", "linkedin.com/px",
    "plausible.io", "matomo", "cookiebot.com", "onetrust.com", "intercom.io", "fullstory.com", "newrelic.com", "nr-data.net",
    # consent banners, surveys and ads
    "cookielaw.org", "usercentrics.eu", "didomi.io", "trustarc.com", "qualtrics.com", "adtrafficquality.google",
    "googlesyndication.com", "googletagservices.com", "criteo.", "adnxs.com", "taboola.com", "outbrain.com", "scorecardresearch.com",
    "pinterest.com", "google.com/rmkt", "google.com/pagead", "/_sec/",  # ads; Akamai bot-protection sensor
)
# Google Analytics 4 served from the site's own domain (data.example.com/g/collect?tid=G-...).
_GA4 = re.compile(r"/g/collect\b|[?&]tid=G-", re.I)
# Files a page loads to look right (icons, styles, fonts, scripts): never part of what a tool does.
STATIC_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".css", ".js", ".mjs", ".map",
                     ".woff", ".woff2", ".ttf", ".otf", ".eot")
STATIC_TYPES = ("image/", "font/", "text/css", "text/javascript", "application/javascript", "application/x-javascript")
KEPT_RESOURCE_TYPES = {"document", "xhr", "fetch"}


def snake(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s or "")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def key_is_secret(key: str) -> bool:
    return bool(_SECRET.search(key))


def key_is_sensitive(key: str) -> bool:
    return bool(_PERSONAL.search(snake(key)) or _SECRET.search(key))


def field_is_personal(field: dict[str, Any]) -> bool:
    if (field.get("input_type") or "").lower() in ("password", "email", "tel"):
        return True
    if _PERSONAL_AUTOCOMPLETE.match((field.get("autocomplete") or "").lower()):
        return True
    return any(_PERSONAL.search(snake(field.get(k) or "")) for k in ("name", "id", "label"))


def is_tracker(url: str) -> bool:
    low = url.lower()
    return any(t in low for t in TRACKERS) or bool(_GA4.search(url))


def _machine_body(body: Any) -> bool:
    """Analytics or bot-protection traffic told by its body: a Snowplow event ("schema": "iglu:..."),
    or a single field of scrambled sensor data (long, mostly symbols)."""
    if not isinstance(body, dict):
        return False
    if str(body.get("schema", "")).startswith("iglu:"):
        return True
    if len(body) == 1:
        v = next(iter(body.values()))
        if isinstance(v, str) and len(v) > 200 and sum(not c.isalnum() and not c.isspace() for c in v) / len(v) > 0.25:
            return True
    return False


def is_noise(url: str, content_type: str = "", body: Any = None) -> bool:
    """Tracking, ads, consent banners, bot-protection sensors and static files (icons, styles, fonts, scripts)."""
    path = urlsplit(url).path.lower()
    return is_tracker(url) or path.endswith(STATIC_EXTENSIONS) or (content_type or "").lower().startswith(STATIC_TYPES) or _machine_body(body)


def mask_text(text: str, known: set[str]) -> str:
    """Mask personal values typed during this recording, plus anything shaped like an email,
    phone number or token."""
    for value in sorted(known, key=len, reverse=True):
        if len(value) >= 3:
            text = text.replace(value, MASK)
    text = _EMAIL.sub(MASK, text)
    text = _JWT.sub(MASK, text)
    return _PHONE.sub(MASK, text)


def mask_data(value: Any, known: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: (MASK if key_is_sensitive(k) and not isinstance(v, (dict, list)) else mask_data(v, known)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_data(v, known) for v in value]
    if isinstance(value, str):
        return mask_text(value, known)
    return value


def mask_response(value: Any, known: set[str]) -> Any:
    """What a website answered. Its own data stays readable (station, product and service names);
    only secrets (tokens, keys), values the customer typed, emails and phone numbers are masked."""
    if isinstance(value, dict):
        return {k: (MASK if key_is_secret(k) and not isinstance(v, (dict, list)) else mask_response(v, known)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_response(v, known) for v in value]
    if isinstance(value, str):
        return mask_text(value, known)
    return value


def mask_url(url: str, known: set[str]) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, MASK if key_is_sensitive(k) else mask_text(v, known)) for k, v in parse_qsl(parts.query, keep_blank_values=True)], safe="[]")
    return urlunsplit((parts.scheme, parts.netloc, mask_text(parts.path, known), query, ""))


def parse_body(raw: str | None, content_type: str, known: set[str]) -> Any:
    """A request or response body as data (JSON or form fields) when possible, masked."""
    if raw is None or raw == "":
        return None
    ct = (content_type or "").lower()
    if "json" in ct or raw.lstrip().startswith(("{", "[")):
        try:
            return mask_data(json.loads(raw), known)
        except ValueError:
            pass
    if "x-www-form-urlencoded" in ct:
        return mask_data(dict(parse_qsl(raw, keep_blank_values=True)), known)
    if "multipart/form-data" in ct:
        return "[multipart body omitted]"
    if "html" in ct:
        return "[html page]"
    text = raw if len(raw) <= BODY_LIMIT else raw[:BODY_LIMIT] + " [cut]"
    return mask_text(text, known)


def clean_action(action: dict[str, Any], known: set[str]) -> dict[str, Any]:
    """Mask the value of a recorded action. Personal values are remembered so the same
    text is also masked wherever it shows up in requests."""
    out = {k: v for k, v in action.items() if v not in (None, "")}
    personal = bool(action.get("personal")) or field_is_personal(action)
    if "value" in action:
        value = str(action.get("value") or "")
        if personal:
            if value and value != MASK:
                known.add(value)
            out["value"] = MASK
            out["personal"] = True
        else:
            out["value"] = mask_text(value, known)
    if "text" in out:
        out["text"] = mask_text(out["text"], known)
    return out
