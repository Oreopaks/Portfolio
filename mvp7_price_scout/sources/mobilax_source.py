"""
Источник МобилАкс (Орёл) — Webasyst Shop-Script, статичный HTML.

Основной домен mobileax.ru закрыт Cloudflare (JS-challenge «Just a moment…»,
статикой не берётся), поэтому ходим на зеркало каталога мобилакс.рф
(xn--80abvjddo3a.xn--p1ai) — тот же магазин, без Cloudflare.

Карточка листинга — <div class="products__item"> с микроразметкой schema.org:
имя .products__item-info-name[itemprop=name], цена [itemprop=price] (целое) с
фолбэком на .products__price-new, ссылка первым <a href>, наличие «Доступно».
Категории берём из sitemap-shop.xml (телефонные разделы), пагинация ?page=N.

parse_mobilax(html) — чистая. fetch_mobilax(...) — боевая.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title, parse_price
from mvp7_price_scout.sources import http

# Пунякод мобилакс.рф — зеркало без Cloudflare (requests сам обходит IDNA).
BASE = "https://xn--80abvjddo3a.xn--p1ai"
SHOP = "mobilax"

# Разделы каталога с пересечением с di-park (телефоны/Apple-техника).
_TARGET = re.compile(r"iphone|samsung|smartfon|telefon|apple|ipad|macbook|watch|"
                     r"airpods|xiaomi|redmi|poco|honor|realme|vivo|oppo|huawei", re.I)
# Аксессуары/Б-У не сравниваем с новыми телефонами.
_SKIP = re.compile(r"aksessuar|chekhl|steklo|remeshok|used|b-u|bu-", re.I)


def parse_mobilax(html: str) -> list[Product]:
    """HTML листинга категории мобилакс.рф -> [Product]. Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    # зачёркнутые/старые цены — вон до извлечения (акционная разметка)
    for bad in soup.select("del, s, [class*=price-old], [class*=old-price], [class*=oldprice]"):
        bad.decompose()
    out: list[Product] = []
    for card in soup.select(".products__item"):
        name_el = card.select_one(".products__item-info-name") or card.select_one("[itemprop=name]")
        if not name_el:
            continue
        title = clean_title(name_el.get_text())
        if not title:
            continue
        a = card.select_one("a[href]")
        url = a["href"] if a and a.has_attr("href") else ""
        if url.startswith("/"):
            url = BASE + url
        # цена: schema.org [itemprop=price] (уже целое) приоритетнее текста витрины
        price = None
        meta = card.select_one("[itemprop=price]")
        if meta:
            price = parse_price(meta.get("content") or meta.get_text())
        if price is None:
            pe = card.select_one(".products__price-new") or card.select_one("[class*=price-new]")
            price = parse_price(pe.get_text()) if pe else None
        text = card.get_text(" ", strip=True).lower()
        in_stock = not any(s in text for s in ("нет в наличии", "под заказ", "ожидается"))
        out.append(Product(shop=SHOP, title=title, price=price, url=url, in_stock=in_stock))
    return out


def _phone_categories() -> list[str]:
    """Телефонные /category/ URL из sitemap-shop.xml (минус аксессуары/Б-У)."""
    try:
        xml = http.get(f"{BASE}/sitemap-shop.xml", timeout=30).text
    except Exception as e:
        print(f"[mobilax] sitemap недоступен: {e}")
        return [f"{BASE}/category/iphone/"]                # хотя бы iPhone
    locs = re.findall(r"<loc>([^<]+/category/[^<]+)</loc>", xml)
    cats = {u for u in locs if _TARGET.search(u) and not _SKIP.search(u)}
    return sorted(cats)


def fetch_mobilax(max_pages: int = 30, throttle: float = 0.5) -> list[Product]:
    """Боевая: обойти телефонные категории мобилакс.рф с пагинацией -> [Product]. Дедуп по url."""
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
                print(f"[mobilax] {url}: {e}")
                break
            if r.status_code != 200:
                break
            cards = parse_mobilax(r.text)
            fresh = [c for c in cards if c.url and c.url not in seen]
            for c in fresh:
                seen.add(c.url)
            out.extend(fresh)
            time.sleep(throttle)
            if not fresh:                       # нет новых карточек — конец раздела
                break
    print(f"[mobilax] собрано {len(out)} товаров из {len(cats)} категорий")
    return out
