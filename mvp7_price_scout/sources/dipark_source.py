"""
Источник di-park.ru — НАШ магазин-эталон (база цен). source_type='base'.

Платформа — Laravel SSR: цены в статичном HTML (Playwright не нужен). Каталог =
страницы-листинги категорий с сеткой карточек <article class="offer-card">, по 24
на страницу, пагинация ?page=N до исчезновения rel="next". Категории берём из
sitemap.xml (первый сегмент пути) — устойчиво к изменениям дерева каталога.

parse_dipark(html)        — ЧИСТАЯ: HTML листинга -> [Product]. Офлайн-тест.
fetch_dipark_catalog(...) — боевая: обходит все категории с пагинацией.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http

BASE = "https://di-park.ru"
SHOP = "di-park"

# Разделы sitemap, которые НЕ являются товарными категориями.
_NON_CATALOG = {
    "blog", "about", "promotions", "delivery-payment", "return-exchange",
    "warranty", "contacts", "privacy", "cart", "search", "offers", "products",
    "trade-in", "forms", "orders", "sitemap.xml", "reviews", "vacancies",
    "podarochnye-sertifikaty",
}


def parse_dipark(html: str) -> list[Product]:
    """HTML листинга категории -> список товаров (source_type='base'). Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    # зачёркнутые/старые цены — вон ДО извлечения, иначе parse_price возьмёт
    # первое число (= старую цену) при появлении акционной разметки
    for bad in soup.select("del, s, [class*=old-price], [class*=price-old], [class*=oldprice], [class*=discount]"):
        bad.decompose()
    out: list[Product] = []
    for art in soup.select("article.offer-card"):
        a = art.select_one("a.offer-card__title")
        if not a:
            continue
        title = clean_title(a.get_text())
        if not title:
            continue
        url = a.get("href", "") or ""
        price_el = art.select_one(".offer-card__price")
        price = parse_price(price_el.get_text()) if price_el else None
        text = art.get_text(" ", strip=True).lower()
        # «под заказ» / «уточнить стоимость» = не в наличии, цена под запрос (None)
        in_stock = not any(s in text for s in
                           ("нет в наличии", "под заказ", "уточнить стоимост"))
        out.append(Product(
            shop=SHOP, title=title, price=price, url=url,
            in_stock=in_stock, source_type="base",
        ))
    return out


def _top_categories() -> list[str]:
    """Первые сегменты товарных URL из sitemap.xml (без сервисных разделов)."""
    try:
        xml = http.get(f"{BASE}/sitemap.xml", timeout=30).text
    except Exception as e:
        print(f"[dipark] sitemap недоступен: {e}")
        return []
    counts: dict[str, int] = {}
    for loc in re.findall(r"<loc>https://di-park\.ru/([^<]*)</loc>", xml):
        first = loc.split("/")[0].split("?")[0].strip()
        if first:
            counts[first] = counts.get(first, 0) + 1
    # категория = сегмент с детьми (>=3 URL) и не из сервисного списка
    return [s for s, n in counts.items() if n >= 3 and s not in _NON_CATALOG]


def _fetch_category(cat: str, max_pages: int, throttle: float) -> list[Product]:
    """Обойти пагинацию одной категории -> [Product] (локальный дедуп по url)."""
    local_seen: set[str] = set()
    items: list[Product] = []
    for p in range(1, max_pages + 1):
        url = f"{BASE}/{cat}" + (f"?page={p}" if p > 1 else "")
        try:
            r = http.get(url, timeout=40)
        except Exception as e:
            print(f"[dipark] {url}: {e}")
            break
        if r.status_code != 200:
            break
        html = r.text
        cards = parse_dipark(html)
        fresh = [c for c in cards if c.url and c.url not in local_seen]
        for c in fresh:
            local_seen.add(c.url)
        items.extend(fresh)
        time.sleep(throttle)
        if not cards or not fresh or not re.search(r'rel=["\']?next', html):
            break
    return items


def fetch_dipark_catalog(max_pages: int = 100, throttle: float = 0.4,
                         categories: list[str] | None = None,
                         workers: int = 8) -> list[Product]:
    """Боевая: обойти все категории di-park с пагинацией -> каталог [Product].

    Категории независимы -> тянем их параллельно (пагинация внутри категории
    остаётся последовательной). Дедуп по url. Категория останавливается при:
    пустой странице / отсутствии rel="next" / странице без новых карточек / HTTP!=200.
    """
    cats = categories or _top_categories()
    if not cats:
        print("[dipark] категории не определены — каталог пуст")
        return []
    seen: set[str] = set()
    out: list[Product] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for items in ex.map(lambda c: _fetch_category(c, max_pages, throttle), cats):
            for c in items:                       # глобальный дедуп при слиянии
                if c.url and c.url not in seen:
                    seen.add(c.url)
                    out.append(c)
    print(f"[dipark] каталог: {len(out)} товаров из {len(cats)} категорий")
    return out
