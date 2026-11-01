"""The right business for a query, in English, German, French and Italian, with typos, plurals,
accents and type words. Runs on words alone (no embedding model), the mode search falls back to
during an outage, so these must hold without meaning."""

import asyncio

import pytest

from app.gateway import directory

from conftest import BASEL


def search(query: str, type_: str | None = None):
    return asyncio.run(directory.search(query, type_))


def ids(results):
    return [r["business_id"] for r in results]


# query -> the business that must come first
TOP = [
    ("pizza", "biz_trattoria_basilico_01"),
    ("pizzas", "biz_trattoria_basilico_01"),
    ("margherita", "biz_trattoria_basilico_01"),
    ("Trattoria Basilico", "biz_trattoria_basilico_01"),
    ("trattoria basilco", "biz_trattoria_basilico_01"),        # typo in the name
    ("Café Central", "biz_cafe_central_01"),
    ("cafe central", "biz_cafe_central_01"),                    # no accent
    ("Café Centrale", "biz_cafe_centrale_01"),                  # the near-identical other one
    ("Haarschnitt", "biz_barbershop_01"),                       # German catalog, German query
    ("haircut", "biz_barbershop_01"),                           # German catalog, English query
    ("coupe de cheveux", "biz_barbershop_01"),                  # French query
    ("taglio di capelli", "biz_barbershop_01"),                 # Italian query
    ("negroni", "biz_rhein_bar_01"),
    ("hoodie", "biz_rhein_threads_01"),
    ("Hemd", "biz_rhein_threads_01"),                           # German for shirt
    ("chemise", "biz_rhein_threads_01"),                        # French for shirt
    ("camicia", "biz_rhein_threads_01"),                        # Italian for shirt
    ("pain au chocolat", "biz_boulangerie_du_lac_01"),
    ("baguette", "biz_boulangerie_du_lac_01"),
    ("gelato", "biz_gelateria_ticino_01"),
    ("glace", "biz_gelateria_ticino_01"),                       # French for ice cream
    ("Eis", "biz_gelateria_ticino_01"),                         # German for ice cream
    ("Velo Strasse", "biz_velo_strasse_01"),                    # ß written as ss
    ("e-bike mieten", "biz_velo_strasse_01"),
    ("Fahrrad", "biz_velo_strasse_01"),
    ("poster", "biz_pixel_prints_01"),
]


@pytest.mark.parametrize("query,expected", TOP)
def test_top_business(query, expected):
    found = ids(search(query))
    assert found, f"nothing found for {query!r}"
    assert found[0] == expected, f"{query!r}: got {found[:3]}"


# query -> businesses that must not appear at all
NOT = [
    ("pizza", {"biz_draft_pizza_01", "biz_barbershop_01", "biz_rhein_threads_01"}),
    ("croissant", {"biz_barbershop_01", "biz_rhein_bar_01", "biz_trattoria_basilico_01"}),
    ("haircut", {"biz_trattoria_basilico_01", "biz_cafe_central_01"}),
    ("Kaffee in der Nähe", {"biz_barbershop_01", "biz_rhein_threads_01", "biz_velo_strasse_01"}),
]


@pytest.mark.parametrize("query,banned", NOT)
def test_no_wrong_business(query, banned):
    assert not banned & set(ids(search(query))), f"{query!r} brought up {banned & set(ids(search(query)))}"


def test_croissant_finds_both_bakeries():
    found = set(ids(search("croissant")))
    assert {"biz_cafe_central_01", "biz_boulangerie_du_lac_01"} <= found


def test_coffee_in_any_language_finds_cafes():
    for q in ("coffee", "Kaffee", "café", "caffè"):
        found = set(ids(search(q)))
        assert "biz_cafe_central_01" in found or "biz_cafe_centrale_01" in found, f"{q!r}: {found}"


def test_matching_items_name_the_dish():
    hit = search("margherita")[0]
    assert [i["name"] for i in hit["matching_items"]] == ["Pizza Margherita"]


def test_type_bar_is_not_barbershop():
    found = ids(asyncio.run(directory.find("", "bar", BASEL, 5, [], None, None))["businesses"])
    assert "biz_rhein_bar_01" in found
    assert "biz_barbershop_01" not in found


def test_type_shop_is_not_workshop_like_substring():
    # "spa" must not pull in every "Hair, beauty or spa" business when it is only part of a word
    kind, extra = directory._kind_filter("spaghetti")
    assert kind is None and extra == "spaghetti"


def test_find_nearby_pizza_in_basel():
    r = asyncio.run(directory.find("pizza", None, BASEL, 5, [], None, None))
    assert ids(r["businesses"])[0] == "biz_trattoria_basilico_01"
    assert r["widened"] is False


def test_find_nearby_exact_before_nearer_similar(fake_similar):
    # Café Central is nearer but only similar in meaning; the Trattoria actually lists pizza.
    fake_similar({"business:biz_cafe_central_01": 0.58, "business:biz_trattoria_basilico_01": 0.55})
    r = asyncio.run(directory.find("pizza", None, BASEL, 5, [], None, None))
    found = ids(r["businesses"])
    assert found[0] == "biz_trattoria_basilico_01", found


def test_partial_index_keeps_keyword_hits(fake_similar):
    # Only one business has vectors (indexing stopped half way): the others must not vanish.
    fake_similar({"business:biz_cafe_central_01": 0.30})
    assert "biz_boulangerie_du_lac_01" in ids(search("croissant"))
    assert ids(search("pizza"))[0] == "biz_trattoria_basilico_01"


def test_search_reports_mode():
    r = asyncio.run(directory.find("pizza", None, BASEL, 5, [], None, None))
    assert r.get("search_mode") == "keywords"


def test_find_nearby_names_farther_exact_matches():
    # Nothing in Basel sells gelato; the Ticino gelateria (200+ km) is still worth naming.
    r = asyncio.run(directory.find("gelato", None, BASEL, 5, [], None, None))
    assert "biz_gelateria_ticino_01" in ids(r.get("farther", []))
    assert r["farther"][0]["distance_km"] > directory.WIDEST_KM


def test_no_farther_when_nearby_matches():
    r = asyncio.run(directory.find("pizza", None, BASEL, 5, [], None, None))
    assert "farther" not in r


@pytest.mark.parametrize("query", ["bonnet", "Mütze", "berretto"])
def test_beanie_words(query):
    from app.gateway import matching

    assert matching.terms(query) == ["beanie"]
