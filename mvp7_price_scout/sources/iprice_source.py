"""
Источник iprice.store — Webasyst Shop-Script. Статичный HTML.

Карточка: .js-product-item, имя .product-list__name, цена .price, ссылка a[href].
Категории из sitemap-shop.xml (телефонные разделы). Пагинация ?page=N (если есть).
Публичного 1С-фида нет (/upload/1c_exchange.xml -> 404).

parse_iprice(html) — чистая. fetch_iprice(...) — боевая.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http

BASE = "https://iprice.store"
SHOP = "iprice"

_TARGET = re.compile(r"smart|iphone|apple|samsung|xiaomi|redmi|poco|honor|realme|"
                     r"telefon|smartfon|huawei|vivo|oppo|tecno|nothing|googl|pixel", re.I)


def parse_iprice(html: str) -> list[Product]:
    """HTML категории Webasyst -> [Product]. Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[Product] = []
    for it in soup.select(".js-product-item"):
        name_el = it.select_one(".product-list__name") or it.select_one(".product-list__title")
        if not name_el:
            continue
        title = clean_title(name_el.get_text())
        if not title:
            continue
        a = it.select_one("a[href]")
        url = a["href"] if a else ""
        if url.startswith("/"):
            url = BASE + url
        price_el = it.select_one(".price") or it.select_one("[class*=price]")
        price = parse_price(price_el.get_text()) if price_el else None
        text = it.get_text(" ", strip=True).lower()
        in_stock = "нет в наличии" not in text
        out.append(Product(shop=SHOP, title=title, price=price, url=url, in_stock=in_stock))
    return out


def _phone_categories() -> list[str]:
    """Телефонные /category/ URL из sitemap-shop.xml."""
    try:
        xml = http.get(f"{BASE}/sitemap-shop.xml", timeout=30).text
    except Exception as e:
        print(f"[iprice] sitemap недоступен: {e}")
        return []
    locs = re.findall(r"<loc>(https://iprice\.store/category/[^<]+)</loc>", xml)
    return sorted({u for u in locs if _TARGET.search(u)})


def fetch_iprice(max_pages: int = 20, throttle: float = 0.6) -> list[Product]:
    """Боевая: обойти телефонные категории iprice -> [Product]. Дедуп по url."""
    cats = _phone_categories()
    if not cats:
        return []
    seen: set[str] = set()
    out: list[Product] = []
    for cat in cats:
        for p in range(1, max_pages + 1):
            sep = "&" if "?" in cat else "?"
            url = cat if p == 1 else f"{cat}{sep}page={p}"
            try:
                r = http.get(url, timeout=40)
            except Exception as e:
                print(f"[iprice] {url}: {e}")
                break
            if r.status_code != 200:
                break
            cards = parse_iprice(r.text)
            fresh = [c for c in cards if c.url and c.url not in seen]
            for c in fresh:
                seen.add(c.url)
            out.extend(fresh)
            time.sleep(throttle)
            if not fresh:                       # нет новых — конец категории
                break
    print(f"[iprice] собрано {len(out)} товаров из {len(cats)} категорий")
    return out
