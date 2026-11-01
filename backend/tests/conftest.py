"""A throwaway database seeded with businesses that are easy to confuse: near-identical names,
the same word as a dish and as a kind of business, catalogs in German, French and Italian, a shop
with sizes and colours, an online-only shop and a draft that must never show up.

No AI provider is configured, so search runs on words alone (as during an embedding outage);
tests that need meaning pass fake similarities through `fake_similar`."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="oasis-tests-"))
os.environ["DATABASE_PATH"] = str(_TMP / "test.sqlite")
os.environ.setdefault("SECRETS_KEY", "")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402

BASEL = (47.5596, 7.5886)
DAY = {"closed": False, "open": "11:30", "close": "23:00"}


def _hours(**override):
    return json.dumps({d: override.get(d, DAY) for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


BUSINESSES = [
    # id, type, name, (lat, lng) or None, description, extra columns
    ("biz_trattoria_basilico_01", "restaurant", "Trattoria Basilico", (47.5604, 7.5931),
     "Neapolitan pizza and fresh pasta in Kleinbasel. Order ahead and pick up warm.", {"accepts_orders": 1}),
    ("biz_cafe_central_01", "cafe", "Café Central", (47.5580, 7.5880),
     "Espresso, croissants and fast Wi-Fi next to the Marktplatz.",
     {"hours": _hours(**{d: {"closed": False, "open": "7:00", "close": "18:00"} for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})}),
    ("biz_cafe_centrale_01", "cafe", "Café Centrale", (47.3769, 8.5417), "Kaffee und Kuchen am Zürichsee.", {}),
    ("biz_barbershop_01", "beauty", "Kleinbasel Barbershop", (47.5620, 7.5950), "Haarschnitt und Bartpflege für Herren.",
     {"category_label": "barbershop"}),
    ("biz_rhein_bar_01", "bar", "Rhein Bar", (47.5610, 7.5900), "Cocktails and craft beer by the river.",
     {"hours": _hours(**{d: {"closed": False, "open": "18:00", "close": "02:00"} for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})}),
    ("biz_rhein_threads_01", "shop", "Rhein Threads", (47.5590, 7.5870), "Organic cotton basics made in Basel.",
     {"shop_template": "clothing", "accepts_orders": 1}),
    ("biz_pixel_prints_01", "online", "Pixel Prints", None, "Custom posters and t-shirt printing, shipped across Switzerland.",
     {"online_only": 1}),
    ("biz_boulangerie_du_lac_01", "cafe", "Boulangerie du Lac", (46.2044, 6.1432), "Pain, croissants et pâtisseries maison.", {}),
    ("biz_gelateria_ticino_01", "cafe", "Gelateria Ticino", (46.0037, 8.9511), "Gelato artigianale e caffè.", {}),
    ("biz_velo_strasse_01", "rental", "Velo Straße", (47.5570, 7.5900), "Fahrräder und E-Bikes mieten in Basel.", {}),
    ("biz_draft_pizza_01", "restaurant", "Pizza Draft House", (47.5597, 7.5887), "Pizza, not published yet.", {"status": "draft"}),
]

# Catalogs read from the businesses' websites (item_snapshots), as catalog.normalize returns them.
SNAPSHOTS = {
    "biz_trattoria_basilico_01": [
        ("Pizza Margherita", "Pizza", 18.0), ("Pizza Diavola", "Pizza", 22.0), ("Pizza Funghi", "Pizza", 21.0),
        ("Spaghetti Carbonara", "Pasta", 24.0), ("Tiramisù", "Dolci", 9.0)],
    "biz_cafe_central_01": [("Cappuccino", "Drinks", 5.2), ("Croissant", "Bakery", 3.5)],
    "biz_cafe_centrale_01": [("Kaffee Crème", "Getränke", 4.8), ("Apfelkuchen", "Kuchen", 6.5)],
    "biz_barbershop_01": [("Haarschnitt", "Herren", 35.0), ("Bart trimmen", "Herren", 20.0)],
    "biz_rhein_bar_01": [("Negroni", "Cocktails", 16.0), ("Lager", "Bier", 7.0)],
    "biz_pixel_prints_01": [("Poster A2", "Prints", 29.0), ("Custom T-Shirt", "Apparel", 35.0)],
    "biz_boulangerie_du_lac_01": [("Croissant au beurre", "Viennoiseries", 2.2), ("Pain au chocolat", "Viennoiseries", 2.5),
                                  ("Baguette tradition", "Pains", 3.4)],
    "biz_gelateria_ticino_01": [("Gelato al pistacchio", "Gelati", 4.5), ("Caffè espresso", "Caffetteria", 2.8)],
    "biz_velo_strasse_01": [("E-Bike Tagesmiete", "Miete", 45.0), ("Stadtvelo Tagesmiete", "Miete", 25.0)],
}

# Rhein Threads is an Oasis shop: products with sizes, colours and stock.
PRODUCTS = [
    ("prd_tee_classic", "T-Shirt Classic", "Tops", 29.0, {"size": ["S", "M", "L"], "colour": ["Black", "White"]},
     {"S/Black": 3, "M/Black": 2, "L/Black": 0, "S/White": 5, "M/White": 5, "L/White": 5}),
    ("prd_hoodie", "Hoodie Rhein", "Tops", 79.0, {"size": ["M", "L"]}, {"M": 4, "L": 1}),
    ("prd_linen_shirt", "Linen Shirt", "Shirts", 69.0, {"size": ["M", "L"]}, {"M": 3, "L": 3}),
]


def _item(bid: str, name: str, section: str, amount: float) -> dict:
    from app import catalog

    return {"id": catalog.item_id(name), "name": name, "description": "", "section": section, "price": f"CHF {amount:.2f}",
            "amount": amount, "currency": "CHF", "image_url": "", "url": ""}


def _seed() -> None:
    db.init_db()
    stamp = db.now()
    with db.session() as conn:
        for bid, kind, name, where, desc, extra in BUSINESSES:
            cols = {"id": bid, "owner_id": "usr_test", "type": kind, "name": name, "address": "" if where is None else f"{name} street 1, Basel",
                    "lat": None if where is None else where[0], "lng": None if where is None else where[1], "description": desc,
                    "status": "live", "hours": _hours(), "created_at": stamp, "updated_at": stamp, **extra}
            conn.execute(f"INSERT INTO businesses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
        for bid, items in SNAPSHOTS.items():
            conn.execute("INSERT INTO item_snapshots (tool_id, business_id, items, fetched_at) VALUES (?, ?, ?, ?)",
                         (f"tool_{bid}", bid, json.dumps([_item(bid, *i) for i in items], ensure_ascii=False), stamp))
        for n, (pid, name, cat, amount, options, stock) in enumerate(PRODUCTS):
            conn.execute(
                "INSERT INTO products (id, business_id, name, category, price_amount, currency, options, stock, sort, created_at, updated_at)"
                " VALUES (?, 'biz_rhein_threads_01', ?, ?, ?, 'CHF', ?, ?, ?, ?, ?)",
                (pid, name, cat, amount, json.dumps(options), json.dumps(stock), n, stamp, stamp))


_seed()


@pytest.fixture(autouse=True)
def _fresh_index():
    from app.gateway import search_index

    search_index.forget_lexical()
    yield
    search_index.forget_lexical()


@pytest.fixture
def fake_similar(monkeypatch):
    """Replace search by meaning with fixed similarities: fake_similar({"business:biz_x": 0.6, ...})."""
    from app.gateway import search_index

    def install(table: dict[str, float] | None):
        async def similar(_query: str):
            return table

        monkeypatch.setattr(search_index, "similar", similar)

    return install
