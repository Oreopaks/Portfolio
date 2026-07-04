"""Офлайн-тесты чистых парсеров Playwright-скрапера (без браузера)."""
from mvp7_price_scout.sources.js_scraper import (
    ScrapeConfig, build_filter_schema, card_id, parse_cards, parse_count,
)

CFG = ScrapeConfig(category_url="https://shop.x/cat/")


def test_parse_count_takes_total():
    assert parse_count("Найдено 342 товара") == 342
    assert parse_count("Показано 24 из 1 240") == 1240        # тотал = большее число
    assert parse_count("нет товаров") is None
    assert parse_count(None) is None


FILTERS_HTML = """
<aside>
  <div class="filter-group"><div class="filter-group__title">Объём памяти</div>
    <label>128 ГБ (12)</label><label>256 ГБ (8)</label><label>512 ГБ</label></div>
  <div class="filter-group"><div class="filter-group__title">Тип SIM</div>
    <label>nanoSIM + eSIM</label><label>Dual SIM</label><label>2 eSIM</label></div>
  <div class="filter-group"><div class="filter-group__title">Регион</div>
    <label>РСТ</label><label>LL/A</label></div>
</aside>
"""


def test_build_filter_schema():
    s = build_filter_schema(FILTERS_HTML, CFG)
    assert set(s) == {"Объём памяти", "Тип SIM", "Регион"}
    assert s["Объём памяти"] == ["128 ГБ", "256 ГБ", "512 ГБ"]   # счётчик «(12)» срезан
    assert "nanoSIM + eSIM" in s["Тип SIM"] and "Dual SIM" in s["Тип SIM"]
    assert s["Регион"] == ["LL/A", "РСТ"]


CARDS_HTML = """
<div class="product-card">
  <a href="/p/iphone-15-256"><div class="product-card__name">iPhone 15 256GB Black</div></a>
  <div class="price-new">75 890 ₽</div>
  <del class="price-old">85 000 ₽</del>
</div>
<div class="catalog-item">
  <h3>Galaxy S24 256GB</h3>
  <a href="https://shop.x/p/s24">l</a>
  <span class="price">99 990 ₽</span>
</div>
"""


def test_parse_cards_price_oldprice_url():
    cards = parse_cards(CARDS_HTML, CFG, base_url="https://shop.x")
    assert len(cards) == 2
    c = {x["title"]: x for x in cards}

    a = c["iPhone 15 256GB Black"]
    assert a["price"] == 75890 and a["old_price"] == 85000      # старая не подменила текущую
    assert a["url"] == "https://shop.x/p/iphone-15-256"         # относительный -> абсолютный

    b = c["Galaxy S24 256GB"]
    assert b["price"] == 99990 and b["old_price"] is None
    assert b["url"] == "https://shop.x/p/s24"


def test_parse_cards_empty():
    assert parse_cards("", CFG) == []


def test_card_id_prefers_url():
    assert card_id({"title": "X", "price": 1, "url": "/p/x"}) == "/p/x"
    assert card_id({"title": "X", "price": 1, "url": ""}) == "X|1"


# ─── Async-оркестрация: fake-page эмулирует ленивую подгрузку/скролл/счётчик ───
import asyncio  # noqa: E402

from mvp7_price_scout.sources import js_scraper as J  # noqa: E402


async def _noop(*a, **k):
    pass


class _FakeEl:
    def __init__(self, text="", on_click=None):
        self._t, self._cb = text, on_click

    async def inner_text(self):
        return self._t

    async def get_attribute(self, k):
        return None

    async def is_enabled(self):
        return True

    async def is_visible(self):
        return True

    async def scroll_into_view_if_needed(self, **k):
        pass

    async def click(self, **k):
        if self._cb:
            self._cb()


class _FakeMouse:
    def __init__(self, page):
        self.page = page

    async def wheel(self, dx, dy):
        self.page.reveal()


class _FakePage:
    """Эмулирует каталог: показывает page_size карточек, скролл/клик подгружает ещё."""
    def __init__(self, total, page_size=10, count_text=None, load_more=False):
        self._all = [
            f'<div class="product-card"><a href="/p/{i}">'
            f'<div class="product-card__name">Phone {i} 128GB</div></a>'
            f'<div class="price-new">{10000 + i} ₽</div></div>'
            for i in range(total)
        ]
        self._shown = min(page_size, total)
        self._size = page_size
        self._count_text = count_text
        self._load_more = load_more
        self.mouse = _FakeMouse(self)
        self.url = "https://shop.x/cat/"

    def reveal(self):
        self._shown = min(len(self._all), self._shown + self._size)

    async def content(self):
        cnt = f'<div class="catalog-count">{self._count_text}</div>' if self._count_text else ""
        return f"<html><body>{cnt}{''.join(self._all[:self._shown])}</body></html>"

    async def query_selector(self, sel):
        s = sel.lower()
        if "count" in s or "found" in s:
            return _FakeEl(self._count_text) if self._count_text else None
        if self._load_more and ("ещё" in s or "more" in s or "next" in s):
            return _FakeEl("Показать ещё", on_click=self.reveal) if self._shown < len(self._all) else None
        return None

    async def query_selector_all(self, sel):
        return []

    async def wait_for_selector(self, sel, **k):
        return _FakeEl("x")

    async def wait_for_load_state(self, *a, **k):
        pass

    async def wait_for_timeout(self, *a, **k):
        pass


def test_collect_listing_infinite_scroll_reaches_total(monkeypatch):
    monkeypatch.setattr(J.asyncio, "sleep", _noop)
    page = _FakePage(total=35, page_size=10, count_text="Найдено 35 товаров")
    cards = asyncio.run(J.collect_listing(page, CFG, "https://shop.x"))
    assert len(cards) == 35                                    # 100% собрано скроллом


def test_collect_listing_load_more_button(monkeypatch):
    monkeypatch.setattr(J.asyncio, "sleep", _noop)
    page = _FakePage(total=25, page_size=10, count_text="Найдено 25", load_more=True)
    cards = asyncio.run(J.collect_listing(page, CFG, "https://shop.x"))
    assert len(cards) == 25                                    # «Показать ещё» дожали


def test_collect_listing_incomplete_raises(monkeypatch):
    """Сайт заявляет 100, отдал 10 -> 100%-гард поднимает исключение (не молчим)."""
    monkeypatch.setattr(J.asyncio, "sleep", _noop)
    page = _FakePage(total=10, page_size=10, count_text="Найдено 100 товаров")
    import pytest
    with pytest.raises(RuntimeError, match="НЕПОЛНЫЙ"):
        asyncio.run(J.collect_listing(page, CFG, "https://shop.x"))


def test_retry_backoff(monkeypatch):
    monkeypatch.setattr(J.asyncio, "sleep", _noop)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("селектор не дождался")
        return "ok"

    assert asyncio.run(J._retry(flaky, "test", CFG)) == "ok" and calls["n"] == 3

    async def dead():
        raise TimeoutError("всегда падает")

    import pytest
    with pytest.raises(RuntimeError, match="исчерпаны"):
        asyncio.run(J._retry(dead, "test", CFG))


def test_extract_filters_builds_schema(monkeypatch):
    monkeypatch.setattr(J.asyncio, "sleep", _noop)

    class _FiltersPage(_FakePage):
        async def content(self):
            return FILTERS_HTML

    schema = asyncio.run(J.extract_filters(_FiltersPage(total=0), CFG))
    assert set(schema) == {"Объём памяти", "Тип SIM", "Регион"}
