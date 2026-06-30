"""
Источник Instagram @smart_room_57 (соцсеть магазина Smart Room).

Цены в подписях постов (текст) и НА фото/в stories (OCR). Анонимный доступ
Instagram режет (429/login_required) -> нужна авторизованная сессия заказчика
(ig_login.py создаёт файл IG_SETTINGS). Без сессии fetch возвращает [].

parse_listing_text(text, source_type) — ЧИСТАЯ: текст подписи/OCR -> [Product].
fetch_instagram(...) — боевая (instagrapi + OCR).
"""
from __future__ import annotations

import os
import re

from mvp7_price_scout.normalize import Product, clean_title, parse_price

SHOP = "smart_room_57"
TARGET = "smart_room_57"

# Число с разделителями тысяч (47 990 / 47.990) или сплошной прогон 4-6 цифр.
_PRICE = re.compile(r"(\d{1,3}(?:[.\s ]\d{3})+|\d{4,6})\s*(?:₽|руб|р\b|rub)?", re.I)
_BRAND = re.compile(r"iphone|samsung|galaxy|xiaomi|redmi|poco|honor|realme|airpods|"
                    r"ipad|macbook|watch|айфон|самсунг|ксиоми|редми", re.I)


def parse_listing_text(text: str, source_type: str = "ig") -> list[Product]:
    """Текст подписи/OCR -> [Product]. Заголовок-бренд переносится на строки-цены.

    IG-посты часто: «iPhone 15 🔥» затем «128GB — 47990 / 256GB — 54990».
    Строке-цене без бренда подставляем последний заголовок с брендом.
    """
    out: list[Product] = []
    context = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        prices = []
        for m in _PRICE.finditer(line):
            v = parse_price(m.group(1))
            if v and 1500 <= v <= 900000:
                prices.append((m.start(), v))
        if not prices:
            if _BRAND.search(line):            # строка-заголовок (бренд, без цены)
                context = clean_title(re.sub(r"[^\w\s().+/-]", "", line)).strip(" -—:•·")
            continue
        pos, val = prices[-1]
        name = clean_title(re.sub(r"[^\w\s().+/-]", "", line[:pos])).strip(" -—:•·")
        # если в строке нет бренда — подставим контекст-заголовок
        if not _BRAND.search(name) and context:
            name = f"{context} {name}".strip()
        if len(re.sub(r"\W", "", name)) < 3:
            continue
        if not _BRAND.search(name):             # совсем не товар — пропускаем
            continue
        out.append(Product(shop=SHOP, title=name, price=val, source_type=source_type))
    return out


def fetch_instagram(amount: int = 30, do_ocr: bool = True, stories: bool = True) -> list[Product]:
    """Боевая: посты (подписи + OCR фото) + stories/highlights (OCR) -> [Product].

    Требует файл сессии IG_SETTINGS (ig_login.py). Без него — [].
    """
    settings = os.environ.get("IG_SETTINGS")
    if not settings or not os.path.exists(settings):
        print("[instagram] нет сессии (IG_SETTINGS). Запусти: python -m mvp7_price_scout.ig_login")
        return []
    try:
        import requests
        from instagrapi import Client
        from mvp7_price_scout import ocr
    except Exception as e:
        print(f"[instagram] зависимости не готовы: {e}")
        return []

    cl = Client()
    cl.delay_range = [1, 3]
    cl.load_settings(settings)
    user = os.environ.get("IG_USERNAME")
    pwd = os.environ.get("IG_PASSWORD", "")
    if user and pwd:
        try:
            cl.login(user, pwd)               # переиспользует сессию, освежает при нужде
        except Exception as e:
            print(f"[instagram] login предупреждение: {e}")

    try:
        uid = cl.user_id_from_username(TARGET)
    except Exception as e:
        print(f"[instagram] профиль недоступен (сессия протухла?): {e}")
        return []

    def _ocr_url(url) -> list[Product]:
        if not (do_ocr and url):
            return []
        try:
            data = requests.get(str(url), timeout=20).content
            return parse_listing_text(ocr.ocr_image_bytes(data), "ig_ocr")
        except Exception:
            return []

    out: list[Product] = []
    try:
        for m in cl.user_medias(uid, amount=amount):
            out += parse_listing_text(m.caption_text or "", "ig")
            out += _ocr_url(getattr(m, "thumbnail_url", None))
    except Exception as e:
        print(f"[instagram] посты: {e}")

    if stories:
        try:
            for s in cl.user_stories(uid):
                out += _ocr_url(getattr(s, "thumbnail_url", None))
        except Exception as e:
            print(f"[instagram] stories: {e}")
        try:
            for hl in cl.user_highlights(uid):
                for item in cl.highlight_info(hl.pk).items:
                    out += _ocr_url(getattr(item, "thumbnail_url", None))
        except Exception as e:
            print(f"[instagram] highlights: {e}")

    print(f"[instagram] извлечено {len(out)} ценовых строк")
    return out
