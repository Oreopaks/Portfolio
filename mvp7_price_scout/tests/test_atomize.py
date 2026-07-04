"""Офлайн-тесты Data Cleaner: атомарные поля карточки товара."""
from mvp7_price_scout.atomize import atomize, base_model_of, ram_rom, region_of, sim_of


def test_atomize_full_iphone_ll_a():
    """iPhone 15 Pro, US-спека (LL/A), nanoSIM+eSIM, скидка."""
    a = atomize("Apple iPhone 15 Pro 256Gb Natural Titanium (Sim+E-Sim) LL/A",
                price="119 990 ₽", old_price="129 990 ₽")
    assert a["base_model"] == "iPhone 15 Pro"
    assert a["ram"] is None and a["rom"] == "256GB" and a["storage"] == "256gb"
    assert a["sim_type"] == "sim_esim" and a["sim_label"] == "nanoSIM + eSIM"
    assert a["color"] == "natural titanium"
    assert a["region"] == "us" and a["region_raw"].replace(" ", "").upper() == "LL/A"
    assert a["price"] == 119990 and a["old_price"] == 129990 and a["discount"] == 10000


def test_atomize_android_ram_rom_region_cn():
    """Android с RAM/ROM и китайской спекой."""
    a = atomize("Смартфон Samsung Galaxy S24 Ultra 12/512GB Titanium Black CN", price=94990)
    assert a["base_model"] == "Samsung Galaxy S24 Ultra"   # бренд не-Apple оставлен
    assert a["ram"] == "12" and a["rom"] == "512GB"
    assert a["region"] == "cn"
    assert a["discount"] is None


def test_sim_variants():
    assert sim_of("iPhone 15 Dual SIM")[0] == "dual_sim"
    assert sim_of("iPhone 15 nanoSIM + eSIM")[0] == "sim_esim"
    assert sim_of("iPhone 15 Pro 2 eSIM")[0] == "esim"        # две eSIM (US) — группа esim
    assert sim_of("iPhone 15 Pro 2eSIM")[1] == "2×eSIM"       # глитч без пробела тоже ловим
    assert sim_of("iPhone 15 Dual eSIM")[0] == "esim"
    # слот карты памяти дописывается в метку, группу не меняет
    g, lbl = sim_of("Xiaomi Redmi 13 8/256 nanoSIM + eSIM + слот для КП")
    assert g == "sim_esim" and "слот КП" in lbl


def test_ram_rom_and_memory_regex_tolerance():
    """RegEx с запасом: «128 гб» / «128gb» / «128 GB» / «8/256GB» / «1 ТБ»."""
    assert ram_rom("iPhone 14 128 гб")[1] == "128GB"
    assert ram_rom("iPhone 14 128gb")[1] == "128GB"
    assert ram_rom("iPhone 14 128 GB")[1] == "128GB"
    assert ram_rom("POCO X6 8/256GB") == ("8", "256GB")
    assert ram_rom("iPad Pro 1 ТБ")[1] == "1TB"
    assert ram_rom("AirPods Pro 2") == (None, None)


def test_region_markers():
    assert region_of("iPhone 15 Pro LL/A")[0] == "us"
    assert region_of("iPhone 15 Pro Max EU")[0] == "eu"
    assert region_of("iPhone 15 128Gb ZP/A")[0] == "cn"       # Гонконг
    assert region_of("iPhone 15 РСТ")[0] == "ru"
    assert region_of("iPhone 15 256Gb Black")[0] is None       # регион не указан


def test_base_model_strips_storage_color_brand():
    assert base_model_of("Apple iPhone 17 Pro Max 256Gb Cosmic Orange (E-Sim)") == "iPhone 17 Pro Max"
    assert base_model_of("Смартфон Apple iPhone 13 128 ГБ Синий") == "iPhone 13"
    assert base_model_of("Samsung Galaxy S24 256GB") == "Samsung Galaxy S24"


def test_atomize_keys_stable():
    """Контракт полей не должен молча меняться (валидируется JSON-схемой)."""
    a = atomize("Apple iPhone 16 256Gb Black")
    assert set(a) == {"base_model", "ram", "rom", "storage", "sim_type", "sim_label",
                      "color", "region", "region_raw", "price", "old_price",
                      "discount", "model_key"}
