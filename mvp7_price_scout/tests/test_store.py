"""Тесты хранилища: снимок магазина, линковка к эталону, сравнение, /top."""
from mvp7_price_scout import store
from mvp7_price_scout.normalize import Product


def _base(conn):
    """Залить каталог эталона (наш di-park) и вернуть id товара iPhone 17 256."""
    p = Product(shop="di-park", title="Apple iPhone 17 256Gb White",
                price=149990, source_type="base", url="https://di-park.ru/x")
    store.replace_shop(conn, "di-park", [p])
    store.link_base_self(conn)
    return store.base_catalog(conn)[0]["id"]


def test_replace_shop_is_snapshot(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    _base(conn)
    # повторный сбор магазина с другим набором -> старое затёрто, не накоплено
    store.replace_shop(conn, "sr57", [
        Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990),
    ])
    store.replace_shop(conn, "sr57", [
        Product(shop="sr57", title="Apple iPhone 17 256Gb", price=143000),
    ])
    rows = conn.execute("SELECT COUNT(*) c FROM products WHERE shop='sr57'").fetchone()
    assert rows["c"] == 1


def test_comparison_links_competitor_to_base(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    bid = _base(conn)
    comp = Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990)
    comp.dipark_id = bid                      # матч проставит collector; тут вручную
    store.replace_shop(conn, "sr57", [comp])
    got = store.competitors_for(conn, bid)
    assert len(got) == 1 and got[0]["shop"] == "sr57" and got[0]["price"] == 144990


def test_biggest_gaps(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    bid = _base(conn)                         # наша цена 149990
    cheap = Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990)
    cheap.dipark_id = bid
    store.replace_shop(conn, "sr57", [cheap])
    gaps = store.biggest_gaps(conn)
    assert gaps and gaps[0]["dipark_id"] == bid
    assert gaps[0]["gap"] == 5000 and gaps[0]["min_shop"] == "sr57"
