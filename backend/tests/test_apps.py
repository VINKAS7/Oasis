"""The MCP App views (items, ask, business): registered, served whole, and the ask_user tool's
settings checked; get_business_info's open-now status."""

import asyncio
from datetime import datetime

from app.gateway import apps, mcp_server, service


def test_every_view_is_registered_and_served_whole():
    uris = {str(r.uri) for r in asyncio.run(mcp_server.mcp.list_resources())}
    for key, spec in apps.VIEWS.items():
        assert spec["uri"] in uris and set(spec["older"]) <= uris
        html = apps.page(key)
        assert "/* @theme */" not in html and "<!-- @bridge -->" not in html
        assert html.lstrip().startswith("<!doctype html>")
    assert "const Oasis" in apps.page("ask") and "const Oasis" in apps.page("business")
    tools = {t.name: (t.meta or {}).get("ui", {}).get("resourceUri") for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert tools["ask_user"] == apps.VIEWS["ask"]["uri"] and tools["get_business_info"] == apps.VIEWS["business"]["uri"]


def test_tools_point_at_their_views():
    assert apps.ui_meta("ask")["ui"]["resourceUri"] == apps.VIEWS["ask"]["uri"]
    assert apps.ui_meta()["openai/outputTemplate"] == apps.VIEWS["items"]["uri"]


def test_view_resource_reads_with_its_csp():
    view = apps.View(uri=apps.VIEWS["business"]["uri"], name="b", mime_type="text/html", view="business")
    html = asyncio.run(view.read())
    assert "Opening hours" in html
    assert view.meta["ui"]["csp"]["frameDomains"] == apps.MAP_FRAMES
    assert "permissions" not in view.meta["ui"]  # only the items view asks for location


def ask(**kw):
    base = dict(question="Pick up or delivery?", kind="single_choice", options=None, allow_other=False, max_choices=None, min=None, max=None,
                step=None, unit="", between=False, default=None, hint="", placeholder="")
    return mcp_server.ask_user(**{**base, **kw})


def test_ask_choice():
    r = ask(options=["Margherita", "Diavola", "Margherita", " "], allow_other=True)
    assert r["ok"] and r["options"] == ["Margherita", "Diavola"] and r["allow_other"] is True
    assert r["ask"]["question"] == "Pick up or delivery?"
    assert "Wait for their answer" in r["message"]


def test_ask_choice_needs_two_options():
    assert ask(options=["Only one"])["ok"] is False


def test_ask_multi_max_choices_capped():
    r = ask(kind="multi_choice", options=["a", "b", "c"], max_choices=9)
    assert r["max_choices"] == 3


def test_ask_range_between_with_unit():
    r = ask(question="Budget?", kind="range", min=10, max=80, step=5, unit="CHF", between=True)
    assert (r["min"], r["max"], r["step"], r["unit"], r["between"]) == (10.0, 80.0, 5.0, "CHF", True)
    assert "10-80 CHF, a range" in r["message"]


def test_ask_range_rejects_backwards_bounds():
    assert ask(kind="range", min=50, max=10)["ok"] is False


def test_ask_rating_defaults_to_five_stars():
    r = ask(question="How was it?", kind="rating")
    assert r["max"] == 5.0 and "1-5 stars" in r["message"]


def test_ask_unknown_kind_and_empty_question():
    assert ask(kind="slider")["ok"] is False
    assert ask(question="  ")["ok"] is False


HOURS = {d: {"closed": False, "open": "18:00", "close": "02:00"} for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def test_open_now_after_midnight():
    r = service._open_now(HOURS, False, now=datetime(2026, 11, 3, 1, 0))  # a Tuesday, 01:00
    assert r == {"today": "tue", "open_now": True, "closes_at": "02:00"}


def test_closed_now_opens_later():
    r = service._open_now(HOURS, False, now=datetime(2026, 11, 3, 15, 0))
    assert r["open_now"] is False and r["opens_at"] == "18:00"


def test_online_business_has_no_open_status():
    assert service._open_now(HOURS, True) == {}


def test_business_info_has_open_status():
    info = service.business_info("biz_trattoria_basilico_01")
    assert info["today"] in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") and info["open_now"] in (True, False)


def test_oauth_discovery_is_404_not_the_web_app():
    # MCP clients read these to decide whether to ask for sign-in; Oasis needs none.
    from fastapi.testclient import TestClient

    from app import main

    if not main.FRONTEND_DIST.is_dir():
        return  # no built UI: nothing catches these paths anyway
    client = TestClient(main.app)
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp"):
        r = client.get(path)
        assert r.status_code == 404 and "<html" not in r.text.lower(), path
