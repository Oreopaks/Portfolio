"""Офлайн-тесты нормализации: model_key / storage_of / parse_price."""
from mvp7_price_scout.normalize import (
    model_key, storage_of, sim_type_of, color_of, parse_price,
    collapse_variants, is_used, is_special_edition, Product,
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


def test_ps5_alias_expands_to_playstation():
    """«PS5» == «PlayStation 5» (di-park зовёт консоль полным именем, магазины — «PS5»)."""
    assert model_key("Sony PS5 Slim 1TB") == model_key("Sony PlayStation 5 Slim 1TB")
    assert "playstation" in model_key("PS5 Diablo 4")


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


def test_ram_in_key_as_soft_token():
    """RAM в ключе отдельным токеном ram12 (различает SKU), голое «12» не течёт."""
    a = model_key("POCO M8 Pro 5G 12/512Gb Black")
    b = model_key("POCO M8 Pro 5G 512GB")
    assert "12" not in a.split() and "ram12" in a.split()
    assert a != b                       # 12/512 и просто 512 — разные ключи
    # но конкурент, не указавший RAM, всё равно матчится (fuzzy, ram вне guard'а)
    from mvp7_price_scout.match import build_index, match_one
    idx = build_index([{"id": 1, "title": "POCO M8 Pro 5G 12/512Gb Black",
                        "model_key": a, "storage": "512gb", "price": 30000}])
    pid, _ = match_one(Product(shop="x", title="POCO M8 Pro 5G 512GB", price=29000), idx)
    assert pid == 1


def test_sim_type_detection():
    assert sim_type_of("Apple iPhone 17 256Gb White (Sim+E-Sim)") == "sim_esim"
    assert sim_type_of("iPhone 17 256Gb (Nano-SIM + eSIM)") == "sim_esim"
    assert sim_type_of("iPhone 17 256Gb eSIM") == "esim"
    assert sim_type_of("iPhone 17 256Gb e-sim only") == "esim"
    assert sim_type_of("Apple iPhone 17 256Gb White") is None       # SIM не указан
    assert sim_type_of("iPhone 17 256Gb Starlight") is None          # цвет не ловится как sim


def test_sim_type_three_groups():
    """Жёсткое разделение на 3 несовместимые группы + краевые случаи."""
    assert sim_type_of("iPhone 17 Pro 256Gb 2 nano-SIM") == "dual_sim"     # Китай: 2 физ. SIM
    assert sim_type_of("iPhone 17 Pro 256Gb Dual SIM") == "dual_sim"
    assert sim_type_of("iPhone 17 Pro 256Gb Dual eSIM") == "esim"          # 2×eSIM = eSIM-группа
    assert sim_type_of("iPhone 17 Pro 256Gb Nano-SIM + eSIM") == "sim_esim"
    # sim_esim и dual_sim — разные SKU, сравнивать их цены нельзя
    assert sim_type_of("iPhone 17 256Gb (Sim+E-Sim)") != sim_type_of("iPhone 17 256Gb 2 nano-SIM")


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


def test_is_special_edition():
    assert is_special_edition("POCO X8 Pro 12/512Gb Black Iron Man Edition")
    assert is_special_edition("Смартфон Apple iPhone 17 Pro 256 ГБ Coffee (эксклюзивный)")
    assert is_special_edition("Xiaomi 14 Ultra Limited")
    assert not is_special_edition("Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)")
    assert not is_special_edition("Samsung Galaxy S25 256Gb Navy")
    # «...Edition» — часть штатного имени SKU (игры, приставки), НЕ признак редкости:
    # флагаем только по реальным маркерам (Iron Man/Limited/...), иначе теряли ~44 тов./прогон
    assert not is_special_edition("Игровая консоль Sony PlayStation 5 Pro 2TB Digital Edition")
    assert not is_special_edition("PS5 Alan Wake 2 Deluxe Edition")
    assert not is_special_edition("GTA VI Ultimate Edition")
    assert not is_special_edition("Мышь Xiaomi Mouse Comfort Edition White")


def test_parse_price():
    assert parse_price("47 990 руб") == 47990
    assert parse_price("от 99 990 ₽") == 99990
    assert parse_price("1 199 000") == 1199000
    assert parse_price("149990.00") == 149990          # копейки отбрасываем
    assert parse_price("по запросу") is None
    assert parse_price("") is None
    assert parse_price(None) is None


def test_single_digit_model_number_kept():
    """AirPods Pro 2 и Pro 3 — разные товары: однозначная цифра модели не выпадает."""
    a = model_key("Apple AirPods Pro 2")
    b = model_key("Apple AirPods Pro 3")
    assert a != b and "2" in a.split() and "3" in b.split()
    assert "2" in model_key("Apple Watch Ultra 2 49mm").split()


def test_watch_colors_do_not_split_family():
    """Цвет и материал корпуса часов не текут в ключ — семья одна."""
    a = model_key("Apple Watch S10 46mm Rose Gold")
    b = model_key("Apple Watch S10 46mm Jet Black")
    c = model_key("Apple Watch S10 46mm Silver")
    assert a == b == c
    assert model_key("Apple Watch SE2 40mm Midnight Aluminium") == \
        model_key("Apple Watch SE2 40mm Midnight")


def test_color_of_fallback_without_storage():
    """Без якоря объёма (часы, наушники) цвет берётся из словаря цвет-слов."""
    assert color_of("Apple Watch S10 46mm Rose Gold") == "rose gold"
    assert color_of("Apple EarPods 3.5mm проводные белые") == "белые"
    assert color_of("Apple Pencil Pro") is None


def test_pro_plus_is_not_pro():
    """«Pro+» и «Pro» — разные модели: плюс не должен стираться пунктуацией."""
    plus = model_key("Xiaomi Redmi Note 15 Pro+ 5G 8/256Gb Mocha Brown")
    pro = model_key("Xiaomi Redmi Note 15 Pro 5G 8/256Gb Black")
    assert plus != pro and "plus" in plus.split()
    # а вот «Sim+E-Sim» плюсом модели не считается
    assert "plus" not in model_key("Apple iPhone 17 256Gb White (Sim+E-Sim)").split()


def test_ram_distinguishes_sku():
    """8/256 и 12/256 — разные товары с разной ценой, не схлопывать."""
    a = model_key("Realme 15 5G 8/256Gb Silk Pink")
    b = model_key("Realme 15 5G 12/256Gb Silk Pink")
    assert a != b and "ram8" in a.split() and "ram12" in b.split()
    out = collapse_variants([
        Product(shop="di-park", title="Realme 15 5G 8/256Gb Silk Pink", price=22490),
        Product(shop="di-park", title="Realme 15 5G 12/256Gb Silk Pink", price=25490),
    ])
    assert len(out) == 2


def test_watch_series_written_differently_same_key():
    """Series 11 / S11, SE (Gen.2) / SE2, «42 mm»/«42mm» — один товар у разных магазинов."""
    assert model_key("Apple Watch Series 11, 42 mm") == model_key("Apple Watch S11 42mm")
    assert model_key("Apple Watch SE (Gen.2) 40mm") == model_key("Apple Watch SE2 40mm")
    assert model_key("Apple Watch Series 11 42 мм") == model_key("Apple Watch S11 42mm")


def test_year_and_generation_words_dropped():
    assert model_key("MacBook Air M4 2025 256Gb") == model_key("MacBook Air M4 256Gb")
    assert model_key("AirPods Pro (2nd generation)") == model_key("Apple AirPods Pro 2")


def test_sim_type_cyrillic_and_color_boundary():
    assert sim_type_of("айфон 17 256 сим+есим") == "sim_esim"
    assert sim_type_of("17 256 две симки") == "dual_sim"          # две физ. SIM, без eSIM
    assert sim_type_of("17 256 есим") == "esim"
    # «Blue Sim+eSIM»: «e» из цвета не должна давать ложный esim-only
    assert sim_type_of("Apple iPhone 17 256GB Mist Blue Sim+eSIM") == "sim_esim"


def test_used_detects_rfb_copy_showcase():
    assert is_used("iPhone 15 Pro 512Gb Black (2 Sim) (RFB)")
    assert is_used("EarPods Type-C (Люкс копия)")
    assert is_used("Смартфон витринный экземпляр")
    assert is_used("iPhone 14 128Gb Новый Актив")
    assert is_used("iPhone 13 128Gb Б/У АКБ 89%")            # процент у батареи = Б/У
    assert not is_used("Кофе в зернах Mikale 100% Arabica 1кг")  # голый % — не Б/У
    assert not is_used("Коллекция 100% натуральных масел Антистресс")


def test_lte_is_separate_variant():
    wifi = model_key("iPad Air 11 M3 128Gb Wi-Fi")
    lte = model_key("iPad Air 11 M3 128Gb LTE")
    assert wifi != lte and "cellular" in lte.split()


def test_product_autofills_key_and_storage():
    p = Product(shop="sr57", title="Apple iPhone 17 256Gb Black", price=144990)
    assert p.model_key == model_key("Apple iPhone 17 256Gb Black")
    assert p.storage == "256gb"
