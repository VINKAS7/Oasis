"""Part D rulebook: the platform, not the AI, decides what a proposal may do.

The AI suggests tools; normalise() and check() turn a suggestion into a clean tool and attach
flags the owner must see: name or job clashes, addresses outside the business, hard-coded
personal values, placeholders without inputs. Sensitivity can only go up here, never down.
"""

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..crawler import safety
from ..recorder.clean import MASK, field_is_personal, snake

SENSITIVITY_ORDER = ["read_only", "booking", "personal_data", "payment"]
SENSITIVITY_WORDS = {
    "read_only": "only reads information",
    "booking": "takes an action (books, orders or sends something)",
    "personal_data": "handles personal data",
    "payment": "handles money",
}
INPUT_TYPES = {"string", "integer", "number", "boolean", "date", "time"}
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_PAYMENT = re.compile(r"(pay|payment|checkout|card|stripe|paypal|twint|invoice|charge)", re.I)


def placeholders(text: str) -> set[str]:
    return {m.group(1) for m in _PLACEHOLDER.finditer(text or "")}


def input_schema(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """The tool's inputs as JSON Schema, the form MCP clients expect."""
    props: dict[str, Any] = {}
    required = []
    for i in inputs:
        t = i.get("type", "string")
        prop: dict[str, Any] = {"description": i.get("description", "")}
        if t == "date":
            prop.update(type="string", format="date")
        elif t == "time":
            prop.update(type="string", pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description=(prop["description"] + " (HH:MM)").strip())
        else:
            prop["type"] = t
        if i.get("personal"):
            prop["x-personal"] = True
        props[i["name"]] = prop
        if i.get("required", True):
            required.append(i["name"])
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def inputs_from_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    req = set(schema.get("required", []))
    out = []
    for name, prop in schema.get("properties", {}).items():
        t = prop.get("type", "string")
        if prop.get("format") == "date":
            t = "date"
        elif prop.get("pattern", "").startswith("^([01]"):
            t = "time"
        out.append({"name": name, "type": t, "description": prop.get("description", ""), "required": name in req, "personal": bool(prop.get("x-personal"))})
    return out


def content_hash(tool: dict[str, Any]) -> str:
    keys = ("title", "description_for_ai", "description_for_owner", "input_schema", "runner", "sensitivity")
    return hashlib.sha256(json.dumps({k: tool.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()[:16]


def job_key(runner: dict[str, Any]) -> str | None:
    """What a tool does in the outside world, to spot two tools doing the same job."""
    if runner.get("kind") == "http_request":
        return f"{runner.get('method', 'GET')} {urlsplit(runner.get('url', '')).path}"
    if runner.get("kind") == "browser_replay":
        submits = [s for s in runner.get("steps", []) if s.get("type") in ("click", "submit")]
        if submits:
            return f"replay {submits[-1].get('page', '')} {submits[-1].get('selector', '')}"
    if runner.get("kind") == "page_extract":
        return "extract " + ",".join(sorted(runner.get("source_urls", [])))
    return None


def _floor(tool: dict[str, Any]) -> str:
    """The least sensitive label this tool can honestly carry."""
    runner = tool["runner"]
    level = "read_only"
    writes = (runner.get("kind") == "http_request" and runner.get("method", "GET") != "GET") or (
        runner.get("kind") == "browser_replay" and any(s.get("type") in ("click", "submit", "press") for s in runner.get("steps", []))
    )
    if writes:
        level = "booking"
    if any(i.get("personal") for i in inputs_from_schema(tool["input_schema"])):
        level = "personal_data"
    text = json.dumps(runner) + tool.get("title", "") + tool.get("description_for_ai", "")
    if writes and _PAYMENT.search(text):
        level = "payment"
    return level


def normalise(raw: dict[str, Any], personal_names: set[str]) -> dict[str, Any]:
    """An AI (or fallback) tool suggestion in the registry's shape."""
    inputs = []
    seen = set()
    for i in raw.get("inputs", []):
        name = snake(i.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        t = i.get("type", "string") if i.get("type") in INPUT_TYPES else "string"
        personal = bool(i.get("personal")) or name in personal_names or field_is_personal({"name": name})
        inputs.append({"name": name, "type": t, "description": i.get("description", ""), "required": i.get("required", True), "personal": personal})
    runner = dict(raw.get("runner") or {})
    name = snake(raw.get("name", ""))
    return {
        "name": name,
        "title": (raw.get("title") or name.replace("_", " ").capitalize()).strip(),
        "description_for_ai": (raw.get("description_for_ai") or "").strip(),
        "description_for_owner": (raw.get("description_for_owner") or "").strip(),
        "input_schema": input_schema(inputs),
        "runner": runner,
        "sensitivity": raw.get("sensitivity") if raw.get("sensitivity") in SENSITIVITY_ORDER else "read_only",
    }


def _runner_strings(runner: dict[str, Any]) -> list[str]:
    out = [runner.get("url", "")]
    out += [str(f.get("value", "")) for f in runner.get("body_fields", [])]
    out += [str(s.get("value", "")) for s in runner.get("steps", [])]
    return out


def check(tool: dict[str, Any], *, site: str, seen_hosts: set[str], seen_requests: set[str]) -> list[dict[str, str]]:
    """Flags for one tool. kind "blocked" means it can't be approved as it is."""
    flags: list[dict[str, str]] = []
    runner = tool["runner"]
    kind = runner.get("kind")
    declared = set(tool["input_schema"]["properties"])

    if not tool["name"] or not re.match(r"^[a-z][a-z0-9_]{1,59}$", tool["name"]):
        flags.append({"kind": "blocked", "message": f"“{tool['name']}” is not a usable tool name."})
    if not tool["description_for_ai"]:
        flags.append({"kind": "warning", "message": "The tool has no description for AI assistants."})

    used = set()
    for text in _runner_strings(runner):
        used |= placeholders(text)
        if MASK in text:
            flags.append({"kind": "blocked", "message": "A masked personal value is written into the tool. Personal details must be inputs the customer gives."})
            break
    missing = used - declared
    if missing:
        flags.append({"kind": "blocked", "message": f"The tool uses {', '.join(sorted(missing))} but doesn't ask for it."})
    unused = declared - used
    if unused and kind in ("http_request", "browser_replay"):
        flags.append({"kind": "warning", "message": f"Asks for {', '.join(sorted(unused))} but never uses it."})

    if kind == "http_request":
        method = runner.get("method", "GET")
        url = urljoin(site, runner.get("url", ""))
        host = urlsplit(url).hostname or ""
        if url.startswith("http") and host and host not in seen_hosts and not safety.same_site(url, site):
            flags.append({"kind": "blocked", "message": f"Sends data to {host}, which is neither your website nor part of your recording."})
        if f"{method} {urlsplit(url).path}" not in seen_requests:
            flags.append({"kind": "warning", "message": f"{method} {urlsplit(url).path} was not in your recording. Check that this is right."})
    elif kind == "browser_replay":
        for step in runner.get("steps", []):
            if step.get("type") == "goto":
                url = urljoin(site, step.get("value") or step.get("page") or "")
                host = urlsplit(url).hostname or ""
                if host and host not in seen_hosts and not safety.same_site(url, site):
                    flags.append({"kind": "blocked", "message": f"Opens {host}, which is neither your website nor part of your recording."})
    elif kind not in ("page_extract", "owner_data"):
        flags.append({"kind": "blocked", "message": f"Unknown way of running a tool: {kind}."})

    floor = _floor(tool)
    if SENSITIVITY_ORDER.index(tool["sensitivity"]) < SENSITIVITY_ORDER.index(floor):
        flags.append({"kind": "note", "message": f"Marked as “{SENSITIVITY_WORDS[floor]}” (the suggestion said “{SENSITIVITY_WORDS[tool['sensitivity']]}”)."})
        tool["sensitivity"] = floor
    return flags


def describe_runner(runner: dict[str, Any]) -> str:
    """One plain sentence about what the tool does when called."""
    kind = runner.get("kind")
    if kind == "http_request":
        fixed = [f for f in runner.get("body_fields", []) if not placeholders(str(f.get("value", "")))]
        pairs = ", ".join("{}={}".format(f["path"], f["value"]) for f in fixed[:4])
        extra = f"; always sends {pairs}" if fixed else ""
        return f"Sends {runner.get('method', 'GET')} {runner.get('url', '')} directly{extra}."
    if kind == "browser_replay":
        return f"Replays {len(runner.get('steps', []))} recorded steps in a hidden browser with the customer's values."
    if kind == "page_extract":
        return f"Reads {', '.join(urlsplit(u).path or '/' for u in runner.get('source_urls', [])) or 'your website'} and returns what it finds (refreshed daily)."
    if kind == "owner_data":
        return f"Answers from your workspace details ({', '.join(runner.get('fields', []))})."
    return "Unknown."
