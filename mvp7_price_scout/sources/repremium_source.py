"""
Источник repremium.ru (Орёл) — Bitrix (aspro). Листовые категории отдают грид в
статике (server-rendered), поэтому тянем их обычными параллельными requests;
Playwright оставлен ФОЛБЭКОМ для страниц, где грид не пришёл статикой (AJAX).

ВАЖНО: магазин города задаётся параметром shop_id=25285. Карточка: .catalog-card2,
заголовок .homepage2-products-slide__title, цена .homepage2-products-slide-price__value.
Берём телефонные разделы (где реально пересечение с di-park); demo/витрина — мимо.

parse_repremium(html) — чистая (по HTML). fetch_repremium(...) — боевая.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http
from mvp7_price_scout.sources.browser import Browser

BASE = "https://repremium.ru"
SHOP = "repremium"
SHOP_ID = "25285"

_TARGET = re.compile(r"apple|samsung|xiaomi|honor|realme|poco|smartfon|telefon|"
                     r"vivo|oppo|tecno|huawei|nothing|googl|pixel", re.I)
_SKIP_URL = re.compile(r"demo|vitrin|_b_u_|/bu_|ustal|obmen", re.I)  # витрина/Б-У/trade-in по slug


def parse_repremium(html: str) -> list[Product]:
    """Отрендеренный HTML категории repremium -> [Product]. Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[Product] = []
    for card in soup.select(".catalog-card2"):
        title_el = (card.select_one(".homepage2-products-slide__title")
                    or card.select_one("[class*=title]"))
        if not title_el:
            continue
        title = clean_title(title_el.get_text())
        if not title:
            continue
        a = card.select_one("a[href]")
        url = a["href"] if a else ""
        if url.startswith("/"):
            url = BASE + url
        if _SKIP_URL.search(url):                 # витринные/демо экземпляры — мимо
            continue
        price_el = (card.select_one(".homepage2-products-slide-price__value")
                    or card.select_one("[class*=price]"))
        price = parse_price(price_el.get_text()) if price_el else None
        text = card.get_text(" ", strip=True).lower()
        in_stock = "нет в наличии" not in text
        out.append(Product(shop=SHOP, title=title, price=price, url=url, in_stock=in_stock))
    return out


def _leaf_categories() -> list[str]:
    """Листовые телефонные категории /oryol/catalog/<бренд>/<модель>/ (ссылки в статике)."""
    try:
        root = http.get(f"{BASE}/oryol/catalog/?shop_id={SHOP_ID}", timeout=30).text
    except Exception as e:
        print(f"[repremium] каталог недоступен: {e}")
        return []
    hubs = sorted({s for s in re.findall(r'href="(/oryol/catalog/[^"/]+/)"', root)
                   if _TARGET.search(s)})
    leaves: set[str] = set()
    for hub in hubs:
        try:
            h = http.get(f"{BASE}{hub}?shop_id={SHOP_ID}", timeout=30).text
        except Exception:
            continue
        seg = hub.strip("/").split("/")[-1]
        for leaf in re.findall(rf'href="(/oryol/catalog/{seg}/[^"/]+/)"', h):
            leaves.add(leaf)
        leaves.add(hub)                            # сам хаб тоже может быть листом
    return sorted(leaves)


def _fetch_static(url: str) -> tuple[str, str | None]:
    """GET категории -> (url, html) или (url, None) при сбое/не-200."""
    try:
        r = http.get(url, timeout=30)
        return url, (r.text if r.status_code == 200 else None)
    except Exception as e:
        print(f"[repremium] {url}: {e}")
        return url, None


def fetch_repremium(max_cats: int = 60, workers: int = 10) -> list[Product]:
    """Боевая: телефонные категории repremium -> [Product]. Дедуп по url.

    Сначала параллельно статикой (грид server-rendered). Страницы без грида
    (html не пришёл / нет .catalog-card2) добиваем Playwright-рендером — редкость.
    """
    cats = _leaf_categories()[:max_cats]
    if not cats:
        return []
    urls = [f"{BASE}{cat}?shop_id={SHOP_ID}" for cat in cats]
    seen: set[str] = set()
    out: list[Product] = []
    need_render: list[str] = []

    def _take(html: str) -> None:
        for c in parse_repremium(html):
            if c.url and c.url not in seen:
                seen.add(c.url)
                out.append(c)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, html in ex.map(_fetch_static, urls):
            if html is None or "catalog-card2" not in html:   # грид не пришёл статикой
                need_render.append(url)
            else:
                _take(html)

    if need_render:                                            # фолбэк через браузер
        with Browser() as br:
            for url in need_render:
                try:
                    _take(br.render(url, wait_selector=".catalog-card2"))
                except Exception as e:
                    print(f"[repremium] render {url}: {e}")

    print(f"[repremium] собрано {len(out)} товаров из {len(cats)} категорий "
          f"(статикой {len(cats) - len(need_render)}, рендером {len(need_render)})")
    return out
