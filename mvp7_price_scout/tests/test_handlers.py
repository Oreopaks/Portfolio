"""Тесты рендера ответа бота: компактная таблица, поиск, /top."""
from mvp7_price_scout import store, handlers
from mvp7_price_scout.normalize import Product


def _seed(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb",
                   price=149990, source_type="base", url="u", fetched_at="2026-06-29T16:00:00")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    comps = [
        Product(shop="sr57", title="Apple iPhone 17 Pro Max 256Gb", price=144990,
                fetched_at="2026-06-29T14:00:00"),
        Product(shop="iprice", title="Apple iPhone 17 Pro Max 256Gb", price=151000,
                fetched_at="2026-06-29T14:00:00"),
    ]
    for c in comps:
        c.dipark_id = bid
    store.replace_shop(conn, "sr57", [comps[0]])
    store.replace_shop(conn, "iprice", [comps[1]])
    return conn, bid


def test_render_comparison_format(tmp_path):
    conn, bid = _seed(tmp_path)
    row = store.base_by_id(conn, bid)
    out = handlers.render_comparison(conn, row)
    assert "💰 Твоя цена: 149 990 ₽" in out
    assert "🔴 Дешевле тебя (1):" in out
    assert "sr57.ru — 144 990 ₽  (−5 000 ₽)" in out
    assert "🟢 Дороже тебя (1):" in out
    assert "iprice — 151 000 ₽  (+1 010 ₽)" in out
    assert "🎯 Поставь 144 890 ₽ → станешь дешевле всех" in out
    assert "🟡 Тебя обходят по цене: 1 из 2" in out


def test_find_product_fuzzy(tmp_path):
    conn, bid = _seed(tmp_path)
    assert handlers.find_product(conn, "iphone 17 pro max 256")["id"] == bid
    assert handlers.find_product(conn, "айфон 17 про макс 256")["id"] == bid   # RU alias
    assert handlers.find_product(conn, "ноутбук asus") is None


def test_handle_text_routes(tmp_path):
    conn, _ = _seed(tmp_path)
    assert "сравниваю цены" in handlers.handle_text(conn, "/help", False)
    assert "только администратору" in handlers.handle_text(conn, "/refresh", False)
    assert "Твоя цена" in handlers.handle_text(conn, "iphone 17 pro max 256", False)


def test_top(tmp_path):
    conn, _ = _seed(tmp_path)
    out = handlers.render_top(conn)
    assert "дороже" in out and "iPhone 17 Pro Max" in out


def test_html_escape_in_rendered_title(tmp_path):
    """Скрапленный title с <>& не должен ломать parse_mode=HTML (иначе Telegram 400)."""
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Apple iPhone 17 <Pro> & Max 256Gb",
                   price=149990, source_type="base", url="u", fetched_at="2026-06-29T16:00:00")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    out = handlers.render_comparison(conn, store.base_by_id(conn, bid))
    assert "&lt;Pro&gt;" in out and "&amp;" in out
    assert "<Pro>" not in out


def test_html_escape_user_query_echo(tmp_path):
    """Юзер-ввод в эхо «не нашёл» тоже экранируется."""
    conn, _ = _seed(tmp_path)
    out = handlers.handle_text(conn, "<b>zzz несуществующий", False)
    assert "&lt;b&gt;" in out and "<b>" not in out
