"""Тесты парсера подписей/OCR Instagram (parse_listing_text) — чистая логика."""
from mvp7_price_scout.sources.instagram_source import parse_listing_text


def test_single_line_caption():
    ps = parse_listing_text("Apple iPhone 15 128GB — 47 990₽", "ig")
    assert len(ps) == 1
    assert ps[0].price == 47990 and ps[0].model_key == "15 iphone 128gb"
    assert ps[0].source_type == "ig" and ps[0].shop == "smart_room_57"


def test_multiline_context_carry():
    """Заголовок-бренд переносится на строки-цены без бренда."""
    cap = "🔥 iPhone 15 в наличии 🔥\n128GB — 47 990\n256GB — 54 990 руб"
    keys = {p.model_key: p.price for p in parse_listing_text(cap, "ig")}
    assert keys.get("15 iphone 128gb") == 47990
    assert keys.get("15 iphone 256gb") == 54990


def test_skip_non_product_lines():
    assert parse_listing_text("Работаем с 10 до 20, доставка по городу", "ig") == []
    assert parse_listing_text("Скидка 5000 на всё!", "ig") == []        # нет бренда
    assert parse_listing_text("Акция -300₽", "ig") == []                # < порога цены


def test_ocr_source_type():
    ps = parse_listing_text("Samsung Galaxy S24 256GB 79990", "ig_ocr")
    assert ps and ps[0].source_type == "ig_ocr"
