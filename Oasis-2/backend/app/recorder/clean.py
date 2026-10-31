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
)
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
    return any(t in low for t in TRACKERS)


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
