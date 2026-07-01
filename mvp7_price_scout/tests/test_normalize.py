"""Офлайн-тесты нормализации: model_key / storage_of / parse_price."""
from mvp7_price_scout.normalize import (
    model_key, storage_of, sim_type_of, color_of, parse_price,
    collapse_variants, is_used, Product,
)


def test_is_used_detects_secondhand():
    assert is_used("iPhone 13 128Gb Starlight 76% Б/У")
    assert is_used("Apple iPhone 15 128Gb Blue 83% б/у")
    assert is_used("Смартфон уценка витринный")
    assert not is_used("Apple iPhone 17 256Gb White (Sim+E-Sim)")
    assert not is_used("Samsung Galaxy S24 256GB")


def test_same_phone_across_shops_same_key():
    """Один телефон, три разных названия -> один model_key."""
    a = model_key("Apple iPhone 17 256Gb White (Sim+E-Sim)")   # di-park
    b = model_key("Смартфон Apple iPhone 17 256 ГБ")            # конкурент A
    c = model_key("iPhone 17 256GB")                            # конкурент B
    assert a == b == c
    assert "256gb" in a and "iphone" in a and "17" in a


def test_storage_distinguishes_variants():
    """256 и 512 — разные товары, ключи не совпадают."""
    assert model_key("iPhone 17 256GB") != model_key("iPhone 17 512GB")


def test_model_line_distinguishes():
    """17 и 17 Pro Max — разные модели."""
    assert model_key("iPhone 17 256GB") != model_key("iPhone 17 Pro Max 256GB")
    assert "pro" in model_key("iPhone 17 Pro Max 256GB")
    assert "max" in model_key("iPhone 17 Pro Max 256GB")


def test_storage_of():
    assert storage_of("Apple iPhone 17 256Gb White") == "256gb"
    assert storage_of("Redmi Note 13 8/256GB") == "256gb"      # RAM/ROM -> ROM
    assert storage_of("iPad Pro 1 ТБ") == "1tb"
    assert storage_of("Samsung Galaxy S24 512 Гб") == "512gb"
    assert storage_of("AirPods Pro 2") is None


def test_color_and_sim_noise_dropped():
    k = model_key("Apple iPhone 17 256Gb White (Sim+E-Sim)")
    for noise in ("white", "sim", "esim", "apple", "e"):
        assert noise not in k.split()


def test_compound_color_after_storage_dropped():
    """Составной цвет ПОСЛЕ объёма ('256Gb Mist Blue') не должен течь в ключ."""
    plain = model_key("Apple iPhone 17 256Gb White (Sim+E-Sim)")
    mist = model_key("Apple iPhone 17 256Gb Mist Blue (Sim+E-Sim)")
    cosmic = model_key("Apple iPhone 17 256Gb Cosmic Orange")
    assert plain == mist == cosmic == "17 iphone 256gb"


def test_ram_rom_not_leaked():
    """RAM перед объёмом не должен попадать в ключ (12/512 -> 512gb, без 12)."""
    a = model_key("POCO M8 Pro 5G 12/512Gb Black")
    b = model_key("POCO M8 Pro 5G 512GB")
    assert a == b
    assert "12" not in a.split()


def test_sim_type_detection():
    assert sim_type_of("Apple iPhone 17 256Gb White (Sim+E-Sim)") == "physical"
    assert sim_type_of("iPhone 17 256Gb (Nano-SIM + eSIM)") == "physical"
    assert sim_type_of("iPhone 17 256Gb eSIM") == "esim"
    assert sim_type_of("iPhone 17 256Gb e-sim only") == "esim"
    assert sim_type_of("Apple iPhone 17 256Gb White") is None       # SIM не указан
    assert sim_type_of("iPhone 17 256Gb Starlight") is None          # цвет не ловится как sim


def test_collapse_splits_by_sim_type():
    """eSIM-only и Sim+E-Sim одного цвета — разные SKU, не схлопывать в одну цену."""
    items = [
        Product(shop="x", title="iPhone 17 256Gb Black (Sim+E-Sim)", price=150000),
        Product(shop="x", title="iPhone 17 256Gb Black (Sim+E-Sim)", price=151000),
        Product(shop="x", title="iPhone 17 256Gb Black eSIM", price=130000),
    ]
    out = collapse_variants(items)
    assert len(out) == 2                                    # physical (мин 150000) + esim
    assert sorted(p.price for p in out) == [130000, 150000]


def test_color_of():
    assert color_of("Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)") == "deep blue"
    assert color_of("Apple iPhone 17 Pro 256Gb Cosmic Orange (E-Sim)") == "cosmic orange"
    assert color_of("Samsung Galaxy S25 12/256Gb Navy") == "navy"
    assert color_of("AirPods Pro 2") is None          # без объёма цвет не выделяем


def test_collapse_keeps_one_row_per_color():
    """Цвета больше НЕ схлопываются — цена за цвет различается (~33% каталога)."""
    items = [
        Product(shop="di-park", title="iPhone 13 128Gb Midnight", price=41990),
        Product(shop="di-park", title="iPhone 13 128Gb Starlight", price=None, in_stock=False),
        Product(shop="di-park", title="iPhone 13 128Gb Pink", price=42990),
    ]
    out = collapse_variants(items)
    assert len(out) == 3
    assert {p.color for p in out} == {"midnight", "starlight", "pink"}


def test_collapse_dedups_same_color_keeps_min():
    """Истинные дубли (один цвет, разные SKU/наличие) — схлопнуть в мин. цену."""
    items = [
        Product(shop="di-park", title="iPhone 13 128Gb Midnight", price=42990, in_stock=False),
        Product(shop="di-park", title="iPhone 13 128Gb Midnight", price=41990),
    ]
    out = collapse_variants(items)
    assert len(out) == 1
    assert out[0].price == 41990 and out[0].in_stock is True


def test_parse_price():
    assert parse_price("47 990 руб") == 47990
    assert parse_price("от 99 990 ₽") == 99990
    assert parse_price("1 199 000") == 1199000
    assert parse_price("149990.00") == 149990          # копейки отбрасываем
    assert parse_price("по запросу") is None
    assert parse_price("") is None
    assert parse_price(None) is None


def test_product_autofills_key_and_storage():
    p = Product(shop="sr57", title="Apple iPhone 17 256Gb Black", price=144990)
    assert p.model_key == model_key("Apple iPhone 17 256Gb Black")
    assert p.storage == "256gb"
