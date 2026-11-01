"""Live evaluation of the customer chat (/api/chat) against the running API and its database.

Each case is a short conversation in English, German, French or Italian with what a good answer
must contain: the right business, the right item, a confirm card for orders. Prints one row per
case and a summary (correct business %, correct item %, orders reaching confirmation, errors,
LLM calls and latency per turn), so runs before and after a change can be compared.

    uv --directory backend run python scripts/eval_chat.py [--api http://127.0.0.1:8000] [--only de,fr] [--json out.json]

LLM calls are counted from the ai_calls table (task client_chat), so run it against an API that
uses the same database and nothing else is chatting at the time."""

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATABASE_PATH  # noqa: E402

BASEL = "47.5596, 7.5886"

# turns: the visitor's messages (later turns see the assistant's earlier replies).
# expect: business (name substring), item (substring of a shown item or the reply), confirm (an order/booking card).
CASES: list[dict[str, Any]] = [
    {"id": "en-pizza-near", "lang": "en", "turns": ["What's the nearest pizza place?"], "expect": {"business": "Trattoria Basilico"}},
    {"id": "en-menu", "lang": "en", "turns": ["Show me the menu of Trattoria Basilico"], "expect": {"business": "Trattoria Basilico", "item": "Margherita"}},
    {"id": "en-item-price", "lang": "en", "turns": ["How much is the pizza diavola at Trattoria Basilico?"], "expect": {"business": "Trattoria Basilico", "item": "Diavola"}},
    {"id": "en-typo-name", "lang": "en", "turns": ["Trattoria Basilco opening hours"], "expect": {"business": "Trattoria Basilico"}},
    {"id": "en-black-hoodie", "lang": "en", "turns": ["I need a black hoodie in size L"], "expect": {"business": "Rhein Threads", "item": "Hoodie"}},
    {"id": "en-merino", "lang": "en", "turns": ["merino wool sweater"], "expect": {"business": "Alpine Knit", "item": "Merino"}},
    {"id": "en-haircut", "lang": "en", "turns": ["Where can I get a haircut?"], "expect": {"business": "Studio Lina"}},
    {"id": "en-trainer", "lang": "en", "turns": ["I'm looking for a personal trainer"], "expect": {"business": "FitFlow"}},
    {"id": "en-bowl", "lang": "en", "turns": ["vegan bowl for lunch"], "expect": {"business": "Green Bowl"}},
    {"id": "en-bike", "lang": "en", "turns": ["bike accessories shop"], "expect": {"business": "Velo Gear"}},
    {"id": "en-order-pizza", "lang": "en",
     "turns": ["Order 2 Pizza Margherita from Trattoria Basilico for pickup at 19:00. My name is Anna, phone 079 123 45 67."],
     "expect": {"business": "Trattoria Basilico", "confirm": True}},
    {"id": "en-order-variant", "lang": "en",
     "turns": ["Order one Linen Shirt in size M, colour White from Rhein Threads. I'm Tom, tom@example.com"],
     "expect": {"business": "Rhein Threads", "confirm": True}},
    {"id": "en-follow-up-order", "lang": "en",
     "turns": ["Show me the t-shirts from Rhein Threads", "I'll take the graphic tee in black, size M. Name Ana, ana@example.com"],
     "expect": {"business": "Rhein Threads", "confirm": True}},
    {"id": "en-follow-up-menu", "lang": "en",
     "turns": ["Which pizzeria is near me?", "What's on their menu?"], "expect": {"business": "Trattoria Basilico", "item": "Pizza"}},
    {"id": "de-pizza", "lang": "de", "turns": ["Wo gibt es in der Nähe Pizza?"], "expect": {"business": "Trattoria Basilico"}},
    {"id": "de-hoodie", "lang": "de", "turns": ["Ich suche einen schwarzen Kapuzenpullover in Grösse L"], "expect": {"business": "Rhein Threads", "item": "Hoodie"}},
    {"id": "de-haircut", "lang": "de", "turns": ["Wo kann ich mir die Haare schneiden lassen?"], "expect": {"business": "Studio Lina"}},
    {"id": "de-menu", "lang": "de", "turns": ["Zeig mir die Speisekarte von Trattoria Basilico"], "expect": {"business": "Trattoria Basilico", "item": "Margherita"}},
    {"id": "de-order", "lang": "de",
     "turns": ["Ich möchte eine Pizza Funghi bei Trattoria Basilico bestellen, Abholung 18:30, Name Lukas, Telefon 076 555 12 12"],
     "expect": {"business": "Trattoria Basilico", "confirm": True}},
    {"id": "fr-pizza", "lang": "fr", "turns": ["Où puis-je manger une pizza près d'ici ?"], "expect": {"business": "Trattoria Basilico"}},
    {"id": "fr-linen", "lang": "fr", "turns": ["Je cherche une chemise en lin"], "expect": {"business": "Rhein Threads", "item": "Linen"}},
    {"id": "fr-haircut", "lang": "fr", "turns": ["Où me faire couper les cheveux ?"], "expect": {"business": "Studio Lina"}},
    {"id": "fr-merino", "lang": "fr", "turns": ["un pull en laine mérinos"], "expect": {"business": "Alpine Knit", "item": "Merino"}},
    {"id": "fr-order", "lang": "fr",
     "turns": ["Je voudrais commander un bonnet côtelé rouge chez Alpine Knit. Je m'appelle Claire, claire@example.com"],
     "expect": {"business": "Alpine Knit", "confirm": True}},
    {"id": "it-pizza", "lang": "it", "turns": ["Dove posso mangiare una pizza qui vicino?"], "expect": {"business": "Trattoria Basilico"}},
    {"id": "it-hoodie", "lang": "it", "turns": ["Cerco una felpa con cappuccio nera"], "expect": {"business": "Rhein Threads", "item": "Hoodie"}},
    {"id": "it-haircut", "lang": "it", "turns": ["Dove posso fare un taglio di capelli?"], "expect": {"business": "Studio Lina"}},
    {"id": "it-menu", "lang": "it", "turns": ["Voglio vedere il menu della Trattoria Basilico"], "expect": {"business": "Trattoria Basilico", "item": "Margherita"}},
    {"id": "it-order", "lang": "it",
     "turns": ["Vorrei ordinare un tiramisù da Trattoria Basilico per le 20:00, sono Marco, 078 999 88 77"],
     "expect": {"business": "Trattoria Basilico", "confirm": True}},
]


def _llm_calls_since(after_id: int) -> int:
    with sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT COUNT(*) FROM ai_calls WHERE id > ? AND task = 'client_chat'", (after_id,)).fetchone()[0]


def _last_call_id() -> int:
    with sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM ai_calls").fetchone()[0]


def _turn(client: httpx.Client, api: str, messages: list[dict[str, str]], lang: str, known: list[dict[str, str]],
          context: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    body = {"messages": messages, "location": BASEL, "language": lang, "businesses": known, **context}
    events: list[dict[str, Any]] = []
    started = time.monotonic()
    with client.stream("POST", f"{api}/api/chat", json=body, timeout=240) as r:
        if r.status_code != 200:
            return [{"type": "error", "message": f"HTTP {r.status_code}: {r.read().decode()[:200]}"}], time.monotonic() - started
        for line in r.iter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events, time.monotonic() - started


def run_case(client: httpx.Client, api: str, case: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    known: dict[str, str] = {}
    shown: list[dict[str, str]] = []
    all_events: list[dict[str, Any]] = []
    latencies, calls = [], 0
    for text in case["turns"]:
        messages.append({"role": "user", "content": text})
        before = _last_call_id()
        context = {"items_shown": shown[-40:]} if shown else {}
        events, took = _turn(client, api, messages, case["lang"], [{"business_id": k, "name": v} for k, v in known.items()], context)
        calls += _llm_calls_since(before)
        latencies.append(took)
        all_events += events
        reply = next((e["text"] for e in reversed(events) if e["type"] == "reply"), "")
        for e in events:
            for b in e.get("businesses") or []:
                known[b["business_id"]] = b["name"]
            if e["type"] in ("items", "confirm") and e.get("business_id"):
                known[e["business_id"]] = e.get("business_name") or known.get(e["business_id"], "")
            if e["type"] == "items":
                shown = [{"business_id": e["business_id"], "id": i.get("id", ""), "name": i.get("name", "")} for i in e.get("items", [])]
        if reply:
            messages.append({"role": "assistant", "content": reply})
    return _score(case, all_events, latencies, calls)


def _score(case: dict[str, Any], events: list[dict[str, Any]], latencies: list[float], calls: int) -> dict[str, Any]:
    expect = case["expect"]
    names = set()
    item_names: list[str] = []
    for e in events:
        for b in e.get("businesses") or []:
            names.add(b["name"])
            item_names += [i["name"] for i in b.get("matching_items") or []]
        if e["type"] in ("items", "confirm"):
            names.add(e.get("business_name", ""))
        if e["type"] == "items":
            item_names += [i.get("name", "") for i in e.get("items", [])]
        if e["type"] == "confirm":
            item_names += [str(x) for x in (e.get("would_send") or {}).get("items", [])]
    replies = " ".join(e["text"] for e in events if e["type"] == "reply")
    errors = [e["message"] for e in events if e["type"] == "error"]
    low = lambda s: s.lower()  # noqa: E731
    out: dict[str, Any] = {"id": case["id"], "lang": case["lang"], "errors": errors, "steps": sum(e["type"] == "step" for e in events),
                           "llm_calls": calls, "latency_s": round(sum(latencies), 1), "turns": len(latencies)}
    if "business" in expect:
        want = low(expect["business"])
        out["business_ok"] = any(want in low(n) for n in names) or want in low(replies)
    if "item" in expect:
        want = low(expect["item"])
        out["item_ok"] = any(want in low(n) for n in item_names) or want in low(replies)
    if expect.get("confirm"):
        out["confirm_ok"] = any(e["type"] == "confirm" for e in events)
    out["fallback"] = "couldn't put an answer together" in low(replies)
    return out


def _pct(rows: list[dict[str, Any]], key: str) -> str:
    vals = [r[key] for r in rows if key in r]
    return f"{100 * sum(vals) / len(vals):.0f}% ({sum(vals)}/{len(vals)})" if vals else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="", help="comma-separated languages or case ids")
    ap.add_argument("--json", default="", help="also write the rows here")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    cases = [c for c in CASES if not only or c["lang"] in only or c["id"] in only]
    rows = []
    with httpx.Client() as client:
        for case in cases:
            try:
                row = run_case(client, args.api, case)
            except httpx.HTTPError as exc:
                row = {"id": case["id"], "lang": case["lang"], "errors": [f"{exc.__class__.__name__}: {exc}"], "steps": 0, "llm_calls": 0,
                       "latency_s": 0.0, "turns": 0, "fallback": False}
            rows.append(row)
            marks = " ".join(f"{k[:-3]}={'ok' if row[k] else 'FAIL'}" for k in ("business_ok", "item_ok", "confirm_ok") if k in row)
            err = f" ERROR: {row['errors'][0][:80]}" if row["errors"] else ""
            print(f"{row['id']:<22} {marks:<40} steps={row['steps']:<2} llm={row['llm_calls']:<2} {row['latency_s']:>5}s{err}", flush=True)

    turns = sum(r["turns"] for r in rows) or 1
    lat = [r["latency_s"] / max(1, r["turns"]) for r in rows if r["turns"]]
    print("\nSummary")
    print(f"  correct business   {_pct(rows, 'business_ok')}")
    print(f"  correct item       {_pct(rows, 'item_ok')}")
    print(f"  order confirmation {_pct(rows, 'confirm_ok')}")
    print(f"  turns with errors  {sum(bool(r['errors']) for r in rows)}/{len(rows)}   fallback replies {sum(r['fallback'] for r in rows)}")
    print(f"  LLM calls per turn {sum(r['llm_calls'] for r in rows) / turns:.2f}   tool steps per turn {sum(r['steps'] for r in rows) / turns:.2f}")
    if lat:
        lat.sort()
        print(f"  latency per turn   p50 {statistics.median(lat):.1f}s   p95 {lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.1f}s")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
