"""Matching what a customer (or their assistant) asks to order against the catalog: ids, names as
typed, sizes and colours, stock, and helpful errors instead of guesses."""

import pytest

from app.gateway import orders
from app.shop import catalog as shop_catalog

TRATTORIA = [
    {"id": "pizza-margherita-abc123", "name": "Pizza Margherita", "amount": 18.0, "currency": "CHF"},
    {"id": "pizza-diavola-def456", "name": "Pizza Diavola", "amount": 22.0, "currency": "CHF"},
    {"id": "tiramisu-0a1b2c", "name": "Tiramisù", "amount": 9.0, "currency": "CHF"},
]


def lines(requested, catalog=TRATTORIA):
    return orders._lines(requested, catalog)


def test_by_id():
    [l] = lines([{"id": "pizza-diavola-def456", "quantity": 2}])
    assert (l["name"], l["quantity"], l["amount"]) == ("Pizza Diavola", 2, 22.0)


def test_by_exact_name_any_case():
    assert lines([{"id": "pizza margherita", "quantity": 1}])[0]["id"] == "pizza-margherita-abc123"


def test_by_name_without_accent():
    assert lines([{"id": "Tiramisu", "quantity": 1}])[0]["id"] == "tiramisu-0a1b2c"


def test_by_clear_misspelling():
    assert lines([{"id": "Pizza Margarita", "quantity": 1}])[0]["id"] == "pizza-margherita-abc123"


def test_by_unique_short_name():
    assert lines([{"id": "Diavola", "quantity": 1}])[0]["id"] == "pizza-diavola-def456"


def test_ambiguous_name_lists_candidates():
    with pytest.raises(orders.OrderError) as e:
        lines([{"id": "Pizza", "quantity": 1}])
    assert e.value.outcome == "bad_input"
    assert {c["id"] for c in e.value.extra["candidates"]} >= {"pizza-margherita-abc123", "pizza-diavola-def456"}


def test_unknown_item_lists_candidates():
    with pytest.raises(orders.OrderError) as e:
        lines([{"id": "Calzone", "quantity": 1}])
    assert e.value.outcome == "bad_input"
    assert "candidates" in e.value.extra


def shop():
    return shop_catalog.items_for("biz_rhein_threads_01")


def test_variant_by_options_any_case():
    [l] = lines([{"id": "prd_tee_classic", "quantity": 1, "options": {"size": "m", "colour": "black"}}], shop())
    assert l["variant"] == "M/Black"


def test_variant_options_with_other_axis_names():
    # assistants often say "color"; the shop says "colour"
    [l] = lines([{"id": "prd_tee_classic", "quantity": 1, "options": {"Size": "S", "color": "White"}}], shop())
    assert l["variant"] == "S/White"


def test_variant_missing_choice_says_which():
    with pytest.raises(orders.OrderError) as e:
        lines([{"id": "prd_tee_classic", "quantity": 1, "options": {"size": "M"}}], shop())
    assert "colour" in e.value.message


def test_variant_sold_out():
    with pytest.raises(orders.OrderError) as e:
        lines([{"id": "prd_tee_classic", "quantity": 1, "options": {"size": "L", "colour": "Black"}}], shop())
    assert "sold out" in e.value.message


def test_variant_only_n_left():
    with pytest.raises(orders.OrderError) as e:
        lines([{"id": "prd_tee_classic", "quantity": 3, "options": {"size": "M", "colour": "Black"}}], shop())
    assert "Only 2 left" in e.value.message
