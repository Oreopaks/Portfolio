"""
Источник sr57.ru («Smart Room») — WooCommerce, статичный HTML.

Карточка листинга: <li class="product">, заголовок .woocommerce-loop-product__title,
цена .price .woocommerce-Price-amount (при скидке берём .price ins = цену со
скидкой, что платит покупатель). Нет в наличии -> класс li.outofstock.
Каталог: категории из product_cat-sitemap.xml, пагинация /page/N/ (rel="next").

parse_sr57(html)  — чистая. fetch_sr57(...) — боевая.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http

BASE = "https://sr57.ru"
SHOP = "sr57"


def parse_sr57(html: str) -> list[Product]:
    """HTML категории WooCommerce -> [Product]. Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[Product] = []
    for li in soup.select("li.product"):
        a = li.select_one("a.woocommerce-LoopProduct-link") or li.select_one("a[href]")
        title_el = li.select_one(".woocommerce-loop-product__title") or li.select_one("h2, h3")
        if not title_el:
            continue
        title = clean_title(title_el.get_text())
        url = a["href"] if a and a.has_attr("href") else ""
        # цена со скидкой (ins) приоритетнее старой (del)
        price_el = (li.select_one(".price ins .woocommerce-Price-amount")
                    or li.select_one(".price .woocommerce-Price-amount")
                    or li.select_one(".price"))
        price = parse_price(price_el.get_text()) if price_el else None
        classes = li.get("class") or []
        in_stock = "outofstock" not in classes
        out.append(Product(shop=SHOP, title=title, price=price, url=url, in_stock=in_stock))
    return out


def _categories() -> list[str]:
    """Топ-категории из product_cat-sitemap.xml (архив включает подкатегории)."""
    try:
        xml = http.get(f"{BASE}/product_cat-sitemap.xml", timeout=30).text
    except Exception as e:
        print(f"[sr57] sitemap категорий недоступен: {e}")
        return [f"{BASE}/product-category/apple-iphone/"]  # хотя бы телефоны
    cats = re.findall(r"<loc>(https://sr57\.ru/product-category/[^<]+)</loc>", xml)
    # только верхний уровень: один сегмент после product-category/
    top = [c for c in cats
           if len([s for s in c.split("/product-category/")[1].split("/") if s]) == 1]
    return sorted(set(top)) or sorted(set(cats))


def fetch_sr57(max_pages: int = 60, throttle: float = 0.5) -> list[Product]:
    """Боевая: обойти категории sr57 с пагинацией -> [Product]. Дедуп по url."""
    seen: set[str] = set()
    out: list[Product] = []
    for cat in _categories():
        for p in range(1, max_pages + 1):
            url = cat if p == 1 else f"{cat.rstrip('/')}/page/{p}/"
            try:
                r = http.get(url, timeout=40)
            except Exception as e:
                print(f"[sr57] {url}: {e}")
                break
            if r.status_code != 200:
                break
            html = r.text
            cards = parse_sr57(html)
            fresh = [c for c in cards if c.url and c.url not in seen]
            for c in fresh:
                seen.add(c.url)
            out.extend(fresh)
            time.sleep(throttle)
            if not cards or not fresh or 'rel="next"' not in html:
                break
    print(f"[sr57] собрано {len(out)} товаров")
    return out
