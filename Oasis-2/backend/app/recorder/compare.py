"""Part C, "record twice": what differs between two recordings of the same flow is an input
(people, date, time, name); what stays the same is fixed (restaurant id, page address).
Also points at the request that most likely did the job (the booking POST)."""

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .clean import MASK, is_tracker, snake

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_TIME = re.compile(r"^\d{1,2}:\d{2}$")
_INT = re.compile(r"^-?\d+$")
VALUE_ACTIONS = ("fill", "select", "check", "uncheck")


def _type_of(values: list[Any]) -> str:
    vals = [str(v) for v in values if v not in (None, MASK)]
    if vals and all(_DATE.match(v) for v in vals):
        return "date"
    if vals and all(_TIME.match(v) for v in vals):
        return "time"
    if vals and all(_INT.match(v) for v in vals):
        return "integer"
    if all(isinstance(v, bool) for v in values if v is not None):
        return "boolean"
    return "string"


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(value, list):
        out = {}
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{prefix}[{i}]"))
        return out
    return {prefix or "(body)": value}


def _request_key(r: dict[str, Any]) -> str:
    return f"{r.get('method', 'GET')} {urlsplit(str(r.get('url', ''))).path}"


def _request_fields(r: dict[str, Any]) -> dict[str, Any]:
    fields = {f"query.{k}": v for k, v in parse_qsl(urlsplit(str(r.get("url", ""))).query)}
    body = r.get("body")
    if body is not None and not (isinstance(body, str) and body.startswith("[")):
        fields.update({f"body.{k}" if k != "(body)" else "body": v for k, v in _flatten(body).items()})
    return fields


def _field_name(action: dict[str, Any]) -> str:
    for key in ("name", "id", "label"):
        if action.get(key):
            return snake(action[key])
    return snake(action.get("selector", "value")) or "value"


def _action_value(a: dict[str, Any]) -> Any:
    if a["type"] in ("check", "uncheck"):
        return a["type"] == "check"
    return a.get("value")


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    inputs: dict[str, dict[str, Any]] = {}
    fixed: list[dict[str, Any]] = []
    warnings: list[str] = []

    def add_input(name: str, va: Any, vb: Any, where: str, personal: bool) -> None:
        item = inputs.setdefault(name, {"name": name, "examples": [], "where": [], "personal": False})
        for v in (va, vb):
            if v is not None and str(v) not in {str(e) for e in item["examples"]}:
                item["examples"].append(v)
        if where not in item["where"]:
            item["where"].append(where)
        item["personal"] = item["personal"] or personal

    sa_all, sb_all = a["steps"], b["steps"]
    if len(sa_all) != len(sb_all):
        warnings.append(f"The recordings have {len(sa_all)} and {len(sb_all)} steps; steps were matched in order.")

    for sa, sb in zip(sa_all, sb_all):
        n = sa["n"]
        b_actions = {(x["type"] if x["type"] not in ("check", "uncheck") else "check", x.get("selector")): x for x in sb["actions"] if x["type"] in VALUE_ACTIONS}
        for x in sa["actions"]:
            if x["type"] not in VALUE_ACTIONS:
                continue
            kind = "check" if x["type"] in ("check", "uncheck") else x["type"]
            y = b_actions.get((kind, x.get("selector")))
            where = f"step {n}: {x.get('label') or x.get('selector')}"
            if y is None:
                warnings.append(f"Step {n}: “{x.get('label') or x.get('selector')}” appears in only one recording.")
                continue
            va, vb = _action_value(x), _action_value(y)
            personal = bool(x.get("personal") or y.get("personal"))
            if personal or va != vb:
                add_input(_field_name(x), va, vb, where, personal)
            else:
                fixed.append({"where": where, "value": va})

        b_requests = {}
        for r in sb["requests"]:
            b_requests.setdefault(_request_key(r), r)
        for r in sa["requests"]:
            if r.get("method", "GET") == "GET" and not r.get("body") and "?" not in str(r.get("url", "")):
                continue
            key = _request_key(r)
            other = b_requests.get(key)
            if other is None:
                continue
            fa, fb = _request_fields(r), _request_fields(other)
            for field in sorted(set(fa) | set(fb)):
                va, vb = fa.get(field), fb.get(field)
                where = f"step {n}: {key} {field}"
                personal = MASK in (va, vb)
                if personal or va != vb:
                    add_input(snake(field.split(".")[-1].split("[")[0]) or "value", va, vb, where, personal)
                else:
                    fixed.append({"where": where, "value": va})

    for item in inputs.values():
        item["type"] = _type_of(item["examples"])
        if item["personal"]:
            item["examples"] = [MASK]

    # The request that did the job: a successful write near the end of the newer recording.
    candidates = []
    for step in b["steps"]:
        for r in step["requests"]:
            status = (r.get("response") or {}).get("status")
            if r.get("method", "GET") != "GET" and not is_tracker(str(r.get("url", ""))) and (status is None or status < 400):
                candidates.append({"step": step["n"], "method": r["method"], "url": r["url"], "status": status})
    likely = candidates[-1] if candidates else None
    if not candidates:
        warnings.append("No request that saves data was captured; a tool for this flow will have to replay the clicks in a browser.")

    return {
        "inputs": list(inputs.values()),
        "fixed": fixed[:100],
        "candidates": candidates,
        "likely_request": likely,
        "warnings": warnings,
    }
