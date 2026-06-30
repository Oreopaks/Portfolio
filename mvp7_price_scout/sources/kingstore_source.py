"""
Источник oryol.kingstore.link («KingStore» Орёл) — Bitrix, статичный HTML.

Apple-магазин. Каждая карточка листинга несёт чистые data-атрибуты:
  <div class="index-products-body-item product-card"
       data-product-name="Смартфон Apple iPhone 17e 256 ГБ Белый"
       data-product-price="62990" data-category="iphone" data-id="4971">
Парсим их напрямую — надёжнее текста (цена уже целое, без «от/руб»).
Категории-хабы /catalog/<раздел>/ берём со страницы /catalog/. Пагинация
?PAGEN_1=N; стоп при отсутствии новых data-id (дедуп).

parse_kingstore(html) — чистая. fetch_kingstore(...) — боевая.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from mvp7_price_scout.normalize import Product, clean_title
from mvp7_price_scout.sources import http

BASE = "https://oryol.kingstore.link"
SHOP = "kingstore"

# Разделы-хабы, где есть пересечение с каталогом di-park (телефоны/Apple-техника).
_TARGET = re.compile(r"iphone|ipad|mac|watch|airpods|samsung|sony|smartfon|telefon", re.I)
# Б/У и аксессуары не сравниваем с новыми телефонами.
_SKIP_HUB = re.compile(r"used|accessories", re.I)


def parse_kingstore(html: str) -> list[Product]:
    """HTML листинга KingStore -> [Product] из data-атрибутов карточек. Без сети."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[Product] = []
    for card in soup.select(".index-products-body-item.product-card"):
        name = clean_title(card.get("data-product-name") or "")
        if not name:
            continue
        raw_price = (card.get("data-product-price") or "").strip()
        # data-product-price="1" — плейсхолдер «цена скрыта/под заказ», не реальная цена
        price = int(raw_price) if raw_price.isdigit() and int(raw_price) >= 100 else None
        a = card.select_one("a.index-products-body-item__title") or card.select_one("a[href]")
        url = a["href"] if a and a.has_attr("href") else ""
        if url.startswith("/"):
            url = BASE + url
        text = card.get_text(" ", strip=True).lower()
        in_stock = not any(s in text for s in ("нет в наличии", "под заказ", "уведомить"))
        out.append(Product(shop=SHOP, title=name, price=price, url=url, in_stock=in_stock))
    return out


def _phone_hubs() -> list[str]:
    """Телефонные/Apple хабы /catalog/<раздел>/ со страницы каталога (минус Б/У, аксессуары)."""
    try:
        html = http.get(f"{BASE}/catalog/", timeout=30).text
    except Exception as e:
        print(f"[kingstore] каталог недоступен: {e}")
        return []
    hubs = {m for m in re.findall(r'href="(/catalog/[^"/]+/)"', html)}
    return sorted(h for h in hubs if _TARGET.search(h) and not _SKIP_HUB.search(h))


def fetch_kingstore(max_pages: int = 30, throttle: float = 0.4) -> list[Product]:
    """Боевая: обойти телефонные хабы KingStore с пагинацией -> [Product]. Дедуп по url."""
    hubs = _phone_hubs()
    if not hubs:
        return []
    seen: set[str] = set()
    out: list[Product] = []
    for hub in hubs:
        for p in range(1, max_pages + 1):
            url = f"{BASE}{hub}" + (f"?PAGEN_1={p}" if p > 1 else "")
            try:
                r = http.get(url, timeout=40)
            except Exception as e:
                print(f"[kingstore] {url}: {e}")
                break
            if r.status_code != 200:
                break
            cards = parse_kingstore(r.text)
            fresh = [c for c in cards if c.url and c.url not in seen]
            for c in fresh:
                seen.add(c.url)
            out.extend(fresh)
            time.sleep(throttle)
            if not fresh:                       # нет новых карточек -> конец раздела
                break
    print(f"[kingstore] собрано {len(out)} товаров из {len(hubs)} разделов")
    return out
