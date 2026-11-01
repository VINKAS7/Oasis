"""business_id resolution: exact ids, clear misspellings, and refusing to guess between look-alikes
or to turn an invented id into some other business."""

from app.gateway import directory


def test_exact_id():
    assert directory.resolve("biz_trattoria_basilico_01") == "biz_trattoria_basilico_01"


def test_misspelled_name():
    assert directory.resolve("Trattoria Basilco") == "biz_trattoria_basilico_01"


def test_exact_name_of_one_of_two_lookalikes():
    assert directory.resolve("Café Central") == "biz_cafe_central_01"
    assert directory.resolve("Café Centrale") == "biz_cafe_centrale_01"


def test_ambiguous_name_is_not_guessed():
    assert directory.resolve("Cafe Centr") is None
    r = directory.resolve_ref("Cafe Centr")
    assert r["status"] == "ambiguous"
    assert {c["business_id"] for c in r["candidates"]} == {"biz_cafe_central_01", "biz_cafe_centrale_01"}


def test_invented_id_is_not_fuzzy_matched():
    assert directory.resolve("biz_trattoria_basilico") is None
    assert directory.resolve("biz_trattoria_basilico_02") is None
    assert directory.resolve_ref("biz_trattoria")["status"] == "not_found"


def test_unrelated_name_not_found():
    assert directory.resolve("Pizza place") is None


def test_draft_never_resolves():
    assert directory.resolve("biz_draft_pizza_01") is None
    assert directory.resolve("Pizza Draft House") is None


def test_resolved_name_is_reported():
    r = directory.resolve_ref("Trattoria Basilco")
    assert r == {"status": "ok", "business_id": "biz_trattoria_basilico_01", "resolved_from": "Trattoria Basilco",
                 "name": "Trattoria Basilico"}
