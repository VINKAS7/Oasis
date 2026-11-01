"""Reading catalogs from websites: prices, the same name in two sections, stable ids."""

from app import catalog


def test_parse_price_formats():
    assert catalog.parse_price("CHF 18.50")[0] == 18.5
    assert catalog.parse_price("18,50 €")[0] == 18.5
    assert catalog.parse_price("CHF 1'299.00")[0] == 1299.0
    assert catalog.parse_price("$1,299.00")[0] == 1299.0


def test_jsonld_price_with_thousands():
    data = '{"@type": "Product", "name": "Road bike", "offers": {"@type": "Offer", "price": "1,299.00", "priceCurrency": "CHF"}}'
    [item] = catalog.jsonld_items([data])
    assert item["amount"] == 1299.0


def test_same_name_in_two_sections_is_kept():
    raw = [{"name": "Margherita", "section": "Pizza", "price": "CHF 18"}, {"name": "Margherita", "section": "Kids", "price": "CHF 12"}]
    items = catalog.normalize(raw, "https://example.ch/")
    assert len(items) == 2
    assert {i["amount"] for i in items} == {18.0, 12.0}
    assert len({i["id"] for i in items}) == 2


def test_first_id_stays_name_based():
    # ids already saved in snapshots and orders must not change
    raw = [{"name": "Margherita", "section": "Pizza", "price": "CHF 18"}, {"name": "Margherita", "section": "Kids", "price": "CHF 12"}]
    assert catalog.normalize(raw, "https://example.ch/")[0]["id"] == catalog.item_id("Margherita")


def test_exact_duplicate_dropped():
    raw = [{"name": "Margherita", "section": "Pizza", "price": "CHF 18"}, {"name": "Margherita", "section": "Pizza", "price": "CHF 18"}]
    assert len(catalog.normalize(raw, "https://example.ch/")) == 1
