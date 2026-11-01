"""Part E, step 1: security checks on a tool before it ever runs. One finding per rule, each
with a plain sentence; any failed rule makes the tool "blocked"."""

import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from .. import db
from ..crawler import safety
from ..recorder import store as rec_store
from ..recorder.clean import MASK, is_noise, key_is_secret
from ..registry import rules

KINDS = {"http_request", "browser_replay", "page_extract", "item_list", "owner_data", "shop_catalog"}
STEP_TYPES = {"goto", "fill", "select", "check", "uncheck", "click", "press", "submit"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
RATE_LIMITS = {"read_only": 60, "booking": 10, "personal_data": 10, "payment": 3}  # calls per minute

_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")
# Long values mixing upper case, lower case and digits look like keys; plain ids (UUIDs) don't.
_LONG_TOKEN = re.compile(r"\b(?=[\w-]*[A-Z])(?=[\w-]*[a-z])(?=[\w-]*\d)[\w-]{40,}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+|00)\d[\d\s\-/().]{6,}\d")


def allowed_hosts(business: dict[str, Any], created_from: str) -> set[str]:
    """The business's own site, its test copy, and any host the owner's recording talked to."""
    hosts = {urlsplit(business.get("website_url") or "").hostname, urlsplit(business.get("test_url") or "").hostname}
    kind, _, source_id = created_from.partition(":")
    if kind == "recording":
        with db.session() as conn:
            r = conn.execute("SELECT file_path FROM recordings WHERE id = ?", (source_id,)).fetchone()
        if r and r["file_path"]:
            doc = rec_store.read(r["file_path"])
            for s in doc["steps"]:
                # Tracking, ads and static files never count as hosts a tool may contact.
                for u in [s.get("url", ""), *(q["url"] for q in s["requests"] if not is_noise(q["url"], (q.get("response") or {}).get("content_type", ""), q.get("body")))]:
                    if u.startswith("http"):
                        hosts.add(urlsplit(u).hostname)
    return {h for h in hosts if h}


def _urls(runner: dict[str, Any], site: str) -> list[str]:
    urls = []
    if runner.get("kind") == "http_request":
        urls.append(urljoin(site, re.sub(r"\{\{.*?\}\}", "x", runner.get("url", ""))))
        urls += [urljoin(site, re.sub(r"\{\{.*?\}\}", "x", str(lk.get("url", "")))) for lk in rules.lookups(runner)]
    for s in runner.get("steps", []):
        if s.get("type") == "goto":
            urls.append(urljoin(site, s.get("value") or s.get("page") or ""))
    urls += [urljoin(site, u) for u in runner.get("source_urls", [])]
    urls += [urljoin(site, s.get("url", "")) for s in runner.get("sources", [])]  # item_list
    return urls


def _literals(runner: dict[str, Any]) -> list[tuple[str, str]]:
    """(where, value) for every value written into the tool rather than given by the customer."""
    out = [("address", runner.get("url", ""))]
    out += [(f"field {f.get('path')}", str(f.get("value", ""))) for f in runner.get("body_fields", [])]
    out += [(f"step {i}", str(s.get("value", ""))) for i, s in enumerate(runner.get("steps", []), start=1)]
    for lk in rules.lookups(runner):
        out += [(f"lookup {lk.get('name')} address", str(lk.get("url", "")))]
        out += [(f"lookup {lk.get('name')} field {f.get('path')}", str(f.get("value", ""))) for f in lk.get("body_fields", [])]
    return [(w, v) for w, v in out if v and not re.fullmatch(r"\{\{\s*\w+\s*\}\}", v)]


def check(version: dict[str, Any], business: dict[str, Any], allow_private: bool) -> tuple[list[dict[str, Any]], int]:
    """Findings for every rule, and the calls-per-minute limit for the tool."""
    runner = version["runner"]
    site = business.get("test_url") or business.get("website_url") or ""
    findings: list[dict[str, Any]] = []

    def rule(name: str, ok: bool, message: str) -> None:
        findings.append({"rule": name, "ok": ok, "message": message})

    # Right address only
    hosts = allowed_hosts(business, version["created_from"])
    bad = []
    for url in _urls(runner, business.get("website_url") or site):
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme not in ("http", "https"):
            bad.append(f"{urlsplit(url).scheme}: address")
        elif host not in hosts:
            bad.append(host)
        elif not allow_private:
            try:
                safety.check(url, False)
            except safety.UnsafeURL:
                bad.append(f"{host} (private network)")
    rule("right_address", not bad,
         f"Only talks to {', '.join(sorted(hosts)) or 'your website'}." if not bad else f"Would contact {', '.join(sorted(set(bad)))}, which is not allowed.")

    # No dangerous powers: only the known, declarative ways of running
    problems = []
    kind = runner.get("kind")
    if kind not in KINDS:
        problems.append(f"unknown kind {kind}")
    if kind == "http_request" and (runner.get("method") or "GET") not in METHODS:
        problems.append(f"method {runner.get('method')}")
    for s in runner.get("steps", []):
        if s.get("type") not in STEP_TYPES:
            problems.append(f"step type {s.get('type')}")
        if "javascript:" in str(s.get("selector", "")).lower() or "javascript:" in str(s.get("value", "")).lower():
            problems.append("a javascript: value")
    if "headers" in runner or any("headers" in lk for lk in rules.lookups(runner)):
        problems.append("custom headers")
    for lk in rules.lookups(runner):
        if (lk.get("method") or "GET") not in ("GET", "POST"):
            problems.append(f"lookup method {lk.get('method')}")
    rule("no_dangerous_powers", not problems,
         "Only sends web requests or replays recorded steps; no files, commands or scripts." if not problems else f"Not allowed: {', '.join(problems)}.")

    # No secrets written into the tool
    secrets = []
    for f in runner.get("body_fields", []) + [f for lk in rules.lookups(runner) for f in lk.get("body_fields", [])]:
        if key_is_secret(f.get("path", "").split(".")[-1]) and not rules.placeholders(str(f.get("value", ""))):
            secrets.append(f"field {f.get('path')}")
    for where, value in _literals(runner):
        if _JWT.search(value) or (_LONG_TOKEN.search(value) and where != "address"):
            secrets.append(where)
    secrets = list(dict.fromkeys(secrets))
    rule("no_secrets", not secrets, "No passwords, keys or tokens are written into the tool." if not secrets else f"A secret seems to be written into: {', '.join(secrets)}.")

    # No personal data written into the tool
    personal = [w for w, v in _literals(runner) if MASK in v or _EMAIL.search(v) or _PHONE.search(v)]
    rule("no_personal_data", not personal, "No customer's details are written into the tool; they are inputs." if not personal else f"Personal details are written into: {', '.join(personal)}.")

    # Every placeholder has an input
    used = set()
    for _, v in [("address", runner.get("url", ""))] + [(None, str(f.get("value", ""))) for f in runner.get("body_fields", [])] + [(None, str(s.get("value", ""))) for s in runner.get("steps", [])]:
        used |= rules.placeholders(v)
    for lk in rules.lookups(runner):
        for v in [str(lk.get("url", ""))] + [str(f.get("value", "")) for f in lk.get("body_fields", [])]:
            used |= rules.placeholders(v)
    looked_up = {str(lk.get("name", "")) for lk in rules.lookups(runner)}
    missing = used - set(version["input_schema"].get("properties", {})) - looked_up
    rule("inputs_match", not missing, "Every value the customer gives is declared." if not missing else f"Uses {', '.join(sorted(missing))} without asking for it.")

    # Sensitivity label and limits
    floor = rules._floor({**version, "runner": runner})
    label = version["sensitivity"]
    if rules.SENSITIVITY_ORDER.index(label) < rules.SENSITIVITY_ORDER.index(floor):
        label = floor
    limit = RATE_LIMITS[label]
    findings.append({"rule": "sensitivity", "ok": True, "message": f"Labelled “{rules.SENSITIVITY_WORDS[label]}”.", "value": label})
    findings.append({"rule": "limits", "ok": True, "message": f"At most {limit} calls per minute.", "value": limit})
    return findings, limit


def passed(findings: list[dict[str, Any]]) -> bool:
    return all(f["ok"] for f in findings)


def dumps(findings: list[dict[str, Any]]) -> str:
    return json.dumps(findings, ensure_ascii=False)
