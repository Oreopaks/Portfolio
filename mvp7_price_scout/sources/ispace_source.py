"""
Источник orel.ispace-shop.ru — Bitrix. Цены СКРЫТЫ в листингах
(«Цена указана при оплате наличными»), но есть на странице товара (.price).

Поэтому: собираем ссылки товаров /offers/<slug>/ из sitemap -> тянем страницы
товаров (модель-URL /offers/apple_iphone_15/ редиректит на конкретный SKU
/offers/apple_iphone_15_512gb_black_esim/ — идём ЗА редиректом) -> имя
(h1/og:title/slug) + цена (.good__total-price / itemprop=price). Playwright не нужен.

parse_offer(html, url) — чистая. fetch_ispace(...) — боевая.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http

BASE = "https://orel.ispace-shop.ru"
SHOP = "ispace"

_TARGET = re.compile(r"apple|samsung|xiaomi|honor|realme|poco|smartfon|telefon|"
                     r"iphone|galaxy|redmi|vivo|oppo|huawei|googl|pixel|ipad|macbook|watch", re.I)
# Приоритет в выборке: телефоны (1) -> планшеты/ноуты (2) -> прочее (3).
_PHONES = re.compile(r"iphone|samsung|galaxy|xiaomi|redmi|poco|honor|realme|vivo|"
                     r"oppo|huawei|tecno|pixel|nothing|smartfon", re.I)
_TABLETS = re.compile(r"ipad|macbook|watch", re.I)


def _priority(url: str) -> int:
    if _PHONES.search(url):
        return 0
    if _TABLETS.search(url):
        return 1
    return 2


def parse_offer(html: str, url: str = "") -> Product | None:
    """Страница товара ispace -> Product (имя h1 + цена .price). Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    h1 = soup.select_one("h1")
    if h1 and h1.get_text(strip=True):
        title = clean_title(h1.get_text())
    if not title:                                    # h1 часто пустой -> og:title
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            title = clean_title(og["content"])
    if not title and url:                            # фоллбэк: имя из slug
        title = clean_title(url.strip("/").split("/")[-1].replace("_", " "))
    if not title:
        return None
    # зачёркнутые/старые цены и рассрочка «от N ₽/мес» — вон до извлечения
    for bad in soup.select("del, s, [class*=old-price], [class*=price-old], [class*=oldprice], [class*=discount]"):
        bad.decompose()
    price = None
    # итоговая цена товара строго из карточки, НЕ из блока «популярное»
    # (.populars__item-price — сопутствующие товары) и не из рассрочки:
    # good__total-price / schema.org itemprop=price / .price — по приоритету.
    for sel in (".good__total-price", "[itemprop=price]", ".price"):
        el = soup.select_one(sel)
        if el:
            price = parse_price(el.get("content") or el.get_text())
            if price:
                break
    text = soup.get_text(" ", strip=True).lower()
    in_stock = "нет в наличии" not in text
    return Product(shop=SHOP, title=title, price=price, url=url, in_stock=in_stock)


def _phone_offer_urls() -> list[str]:
    """Все телефонные страницы товаров /offers/<slug>/ из дочерних sitemap."""
    try:
        idx = http.get(f"{BASE}/sitemap.xml", timeout=30).text
    except Exception as e:
        print(f"[ispace] sitemap недоступен: {e}")
        return []
    childs = re.findall(r"<loc>([^<]+\.xml)</loc>", idx)
    urls: set[str] = set()
    for c in childs:
        try:
            t = http.get(c, timeout=30).text
        except Exception:
            continue
        for u in re.findall(r"<loc>(https://orel\.ispace-shop\.ru/offers/[a-z0-9_]+/)</loc>", t):
            if _TARGET.search(u):
                urls.add(u)
    # телефоны вперёд, потом планшеты/ноуты, потом прочее (важно при cap)
    return sorted(urls, key=lambda u: (_priority(u), u))


def fetch_ispace(max_products: int = 300, throttle: float = 0.3) -> list[Product]:
    """Боевая: телефонные страницы товаров из sitemap -> имя+цена -> [Product].

    ВНИМАНИЕ: ispace отдаёт 503 на параллельные запросы (жёсткий rate-limit),
    поэтому строго последовательно с throttle — иначе теряем страницы.
    """
    urls = _phone_offer_urls()
    if not urls:
        return []
    if len(urls) > max_products:
        print(f"[ispace] телефонных страниц {len(urls)}, беру первые {max_products}")
        urls = urls[:max_products]
    out: list[Product] = []
    for url in urls:
        try:
            r = http.get(url, timeout=25)
        except Exception as e:
            print(f"[ispace] {url}: {e}")
            continue
        # модель-URL (/offers/apple_iphone_15/) редиректит на конкретный SKU
        # (…_512gb_black_esim) — это ЖИВОЙ товар с ценой, оставляем. Снятый товар
        # редиректит на ЛИСТИНГ (/catalog/…) — его отсекаем: если после редиректа
        # ушли НЕ на /offers/, пропускаем (иначе цена тайла листинга липнет к
        # неверному товару). Раньше резались ВСЕ редиректы -> терялись новые
        # модели, в базе оставалось ~6 товаров.
        if r.status_code != 200 or "/offers/" not in r.url:
            continue
        p = parse_offer(r.text, r.url)          # r.url — итоговый SKU-URL (для slug-имени)
        if p and p.price:
            out.append(p)
        time.sleep(throttle)
    print(f"[ispace] собрано {len(out)} товаров (из {len(urls)} страниц)")
    return out
