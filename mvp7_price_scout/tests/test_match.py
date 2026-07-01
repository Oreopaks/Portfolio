"""Тесты сопоставления: точный матч, guard по объёму и по вариант-токенам."""
from mvp7_price_scout.match import build_index, match_one, match_all
from mvp7_price_scout.normalize import Product, model_key


def _base():
    rows = [
        {"id": 1, "title": "iPhone 17 256", "model_key": model_key("Apple iPhone 17 256Gb"),
         "storage": "256gb", "price": 149990},
        {"id": 2, "title": "iPhone 17 512", "model_key": model_key("Apple iPhone 17 512Gb"),
         "storage": "512gb", "price": 169990},
        {"id": 3, "title": "iPhone 17 Pro Max 256", "model_key": model_key("Apple iPhone 17 Pro Max 256Gb"),
         "storage": "256gb", "price": 199990},
        {"id": 4, "title": "Galaxy S24 256", "model_key": model_key("Samsung Galaxy S24 256Gb"),
         "storage": "256gb", "price": 99990},
        {"id": 5, "title": "Galaxy S24 Ultra 256", "model_key": model_key("Samsung Galaxy S24 Ultra 256Gb"),
         "storage": "256gb", "price": 139990},
    ]
    return rows


def test_exact_match():
    idx = build_index(_base())
    p = Product(shop="x", title="Apple iPhone 17 256 ГБ White", price=144990)
    pid, score = match_one(p, idx)
    assert pid == 1 and score == 100


def test_storage_guard_rejects_wrong_capacity():
    idx = build_index(_base())
    p = Product(shop="x", title="iPhone 17 1TB", price=200000)  # 1tb нет в базе
    pid, _ = match_one(p, idx)
    assert pid is None


def test_variant_guard_base_vs_promax():
    """Обычный iPhone 17 НЕ должен матчиться к Pro Max (вариант-токены разные)."""
    idx = build_index(_base())
    p = Product(shop="x", title="iPhone 17 256GB", price=145000)
    pid, _ = match_one(p, idx)
    assert pid == 1  # именно базовый, не Pro Max (id=3)


def test_variant_guard_s24_not_ultra():
    """Galaxy S24 не должен схлопнуться с S24 Ultra (классическая ловушка subset)."""
    idx = build_index(_base())
    p = Product(shop="x", title="Samsung Galaxy S24 256GB", price=95000)
    pid, _ = match_one(p, idx)
    assert pid == 4
    p2 = Product(shop="x", title="Samsung Galaxy S24 Ultra 256GB", price=130000)
    assert match_one(p2, idx)[0] == 5


def test_model_number_guard_16_vs_17():
    """iPhone 16 НЕ должен матчиться к iPhone 17 (token_sort_ratio их путает)."""
    rows = [{"id": 9, "title": "iPhone 16 256", "model_key": model_key("Apple iPhone 16 256Gb"),
             "storage": "256gb", "price": 70000}]
    idx = build_index(rows)
    p = Product(shop="x", title="Apple iPhone 17 256Gb", price=80000)
    assert match_one(p, idx)[0] is None


def test_fuzzy_match_extra_brand_token():
    """Лишний бренд-токен у конкурента не мешает (poco x7 256 == poco x7 xiaomi 256)."""
    rows = [{"id": 7, "title": "POCO X7 256", "model_key": model_key("POCO X7 256Gb"),
             "storage": "256gb", "price": 25000}]
    idx = build_index(rows)
    p = Product(shop="x", title="Xiaomi POCO X7 256GB", price=24000)
    assert match_one(p, idx)[0] == 7


def test_no_match_unknown_product():
    idx = build_index(_base())
    p = Product(shop="x", title="Xiaomi Redmi Note 13 128GB", price=20000)
    assert match_one(p, idx)[0] is None


def test_sim_guard_separates_esim_from_physical():
    """eSIM-only конкурента НЕ матчится к Sim+E-Sim эталону (разные SKU/цены)."""
    rows = [{"id": 10, "title": "Apple iPhone 17 256Gb (Sim+E-Sim)",
             "model_key": model_key("Apple iPhone 17 256Gb (Sim+E-Sim)"),
             "storage": "256gb", "price": 150000}]
    idx = build_index(rows)
    p = Product(shop="x", title="iPhone 17 256Gb eSIM", price=130000)
    assert match_one(p, idx)[0] is None


def test_sim_guard_soft_when_competitor_unknown():
    """Конкурент без пометки SIM матчится как раньше (мягкий guard)."""
    rows = [{"id": 11, "title": "Apple iPhone 17 256Gb (Sim+E-Sim)",
             "model_key": model_key("Apple iPhone 17 256Gb (Sim+E-Sim)"),
             "storage": "256gb", "price": 150000}]
    idx = build_index(rows)
    p = Product(shop="x", title="iPhone 17 256GB", price=145000)   # SIM не указан
    assert match_one(p, idx)[0] == 11


def test_sim_guard_picks_matching_base_variant():
    """В эталоне обе версии (один model_key) — eSIM-конкурент идёт к eSIM-эталону."""
    rows = [
        {"id": 12, "title": "Apple iPhone 17 256Gb (Sim+E-Sim)",
         "model_key": model_key("Apple iPhone 17 256Gb (Sim+E-Sim)"),
         "storage": "256gb", "price": 150000},
        {"id": 13, "title": "Apple iPhone 17 256Gb eSIM",
         "model_key": model_key("Apple iPhone 17 256Gb eSIM"),
         "storage": "256gb", "price": 135000},
    ]
    idx = build_index(rows)
    p = Product(shop="x", title="iPhone 17 256Gb eSIM", price=130000)
    assert match_one(p, idx)[0] == 13


def test_match_all_sets_dipark_id():
    rows = _base()
    prods = [
        Product(shop="x", title="Apple iPhone 17 256Gb Black", price=144990),
        Product(shop="x", title="Nokia 3310", price=2000),
    ]
    n = match_all(prods, rows)
    assert n == 1
    assert prods[0].dipark_id == 1 and prods[1].dipark_id is None
