"""
Нормализация товаров — ядро сравнения цен между магазинами.

Главная функция model_key(title): из «грязного» названия товара делает
канонический ключ для сравнения. Один и тот же телефон в разных магазинах
назван по-разному:

    "Apple iPhone 17 256Gb White (Sim+E-Sim)"   (di-park)
    "Смартфон Apple iPhone 17 256 ГБ"            (конкурент A)
    "iPhone 17 256GB"                            (конкурент B)

Все три -> model_key "17 256gb iphone" (бренд+модель+объём, отсортировано,
цвет/sim/мусор отброшены). Точное равенство ключей = быстрый матч; неточные
случаи добивает rapidfuzz в match.py с guard'ом по объёму памяти.

Чистые функции, без сети — тестируются офлайн.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Product:
    """Нормализованная запись о товаре от любого источника."""
    shop: str                       # "di-park", "sr57", "repremium", "Kingstore"...
    title: str                      # как на сайте (для показа)
    price: int | None               # рубли, целое; None — нет цены/«под заказ»
    url: str = ""
    in_stock: bool = True
    source_type: str = "site"       # base | site | yandex | ig | ig_ocr
    model_key: str = ""             # канон для сравнения (см. model_key())
    storage: str | None = None      # "256gb"/"1tb" — признак для guard'а матчинга
    fetched_at: str = ""            # ISO-время сбора (ставит collector)
    dipark_id: int | None = None    # id товара-эталона, к которому привязан

    def __post_init__(self) -> None:
        if not self.model_key:
            self.model_key = model_key(self.title)
        if self.storage is None:
            self.storage = storage_of(self.title)


# --- словарь мусора: слова, которые НЕ различают товар и только мешают матчу ---
# Бренд "apple" дропаем (модель "iphone" уникальна), а вот "samsung"/"xiaomi"
# оставляем — у них модельная линейка (galaxy/redmi) без бренда неоднозначна.
_STOP = {
    "apple", "смартфон", "smartphone", "phone", "тел", "сотовый",
    "sim", "esim", "nano", "nanosim", "dual", "ru", "рст", "eac", "global",
    "версия", "новый", "new", "оригинал", "original", "гарантия",
    "цвет", "color", "шт", "gb", "гб", "tb", "тб",  # объём учитываем отдельно
    # шумовые слова витрин/соцсетей (часто в подписях IG/заголовках)
    "наличии", "наличие", "налич", "акция", "скидка", "хит", "новинка",
    "заказ", "доставка", "рассрочка", "кредит", "топ", "распродажа",
}
# Цвета (RU+EN). НЕ включаем pro/max/plus/air/ultra/mini — это модель, не цвет!
_COLORS = {
    "black", "white", "blue", "red", "green", "yellow", "purple", "pink",
    "gold", "silver", "gray", "grey", "graphite", "titanium", "midnight",
    "starlight", "space", "orange", "teal", "lavender", "cream", "mint",
    "sierra", "pacific", "desert", "natural", "ultramarine", "coral",
    "чёрный", "черный", "белый", "синий", "красный", "зелёный", "зеленый",
    "жёлтый", "желтый", "фиолетовый", "розовый", "золотой", "золото",
    "серебристый", "серебро", "серый", "графит", "графитовый", "титан",
    "титановый", "полночный", "космический", "оранжевый", "бирюзовый",
    "лавандовый", "бежевый", "голубой",
}

# Объём памяти: "256gb", "256 гб", "1tb", "8/256gb" (RAM/ROM — берём ROM=второе).
# TB допускает 1 цифру (1/2/4 ТБ); GB требует >=2 цифр (16..512), иначе ловил бы
# "iPhone 1". При нескольких GB (RAM+ROM без слэша) берём максимум = ROM.
_RAM_ROM_RE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{2,4})\s*(?:gb|гб|g|г)\b", re.I)
_TB_RE = re.compile(r"\b(\d{1,2})\s*(tb|тб)\b", re.I)
_GB_RE = re.compile(r"\b(\d{2,4})\s*(gb|гб)\b", re.I)


def storage_of(title: str) -> str | None:
    """Объём накопителя из названия -> "256gb"/"1tb" (норм.), иначе None.

    "8/256GB" -> "256gb" (ROM=второе число); "1 ТБ" -> "1tb"; "256 Гб" -> "256gb".
    """
    s = unicodedata.normalize("NFKC", title).lower().replace("ё", "е")
    m = _RAM_ROM_RE.search(s)
    if m:
        return f"{int(m.group(2))}gb"
    m = _TB_RE.search(s)
    if m:
        return f"{int(m.group(1))}tb"
    gbs = [int(g[0]) for g in _GB_RE.findall(s)]
    if gbs:
        return f"{max(gbs)}gb"            # несколько GB (RAM+ROM) -> ROM = максимум
    return None


# Кириллица брендов -> латиница (чтобы RU-запрос «айфон 17» нашёл «iPhone 17»).
_ALIAS = {
    "айфон": "iphone", "афон": "iphone", "эпл": "apple", "эппл": "apple",
    "самсунг": "samsung", "галакси": "galaxy", "ксиаоми": "xiaomi",
    "ксиоми": "xiaomi", "сяоми": "xiaomi", "редми": "redmi", "поко": "poco",
    "хуавей": "huawei", "хонор": "honor", "реалми": "realme", "виво": "vivo",
    "оппо": "oppo", "техно": "tecno", "макбук": "macbook", "айпад": "ipad",
    "аэрподс": "airpods", "эирподс": "airpods", "вотч": "watch",
    "плейстейшн": "playstation", "дайсон": "dyson",
    # модель-слова (для RU-запросов «про макс», «ультра»)
    "про": "pro", "макс": "max", "плюс": "plus", "мини": "mini",
    "ультра": "ultra", "эйр": "air", "эир": "air", "лайт": "lite",
}


def model_key(title: str) -> str:
    """Канонический ключ товара для сравнения между магазинами.

    Ключевой приём: цвет/комплектация — открытый список («Mist Blue», «Cosmic
    Orange», «Desert Titanium»...), перечислить нельзя. Но у ритейла они идут
    ПОСЛЕ объёма памяти, а бренд+модель — ДО. Поэтому режем строку по первому
    «якорю объёма» и берём только то, что слева. Объём добавляем в хвост ключа.
    Оставшиеся токены сортируем (инвариант к порядку слов).
    """
    st = storage_of(title)
    # slash-сохраняющая строка, чтобы поймать конструкцию RAM/ROM ("8/256")
    s = unicodedata.normalize("NFKC", title).lower().replace("ё", "е")
    anchor: int | None = None
    for rx in (_RAM_ROM_RE, _TB_RE, _GB_RE):
        m = rx.search(s)
        if m:
            anchor = m.start() if anchor is None else min(anchor, m.start())
    if anchor is not None:
        s = s[:anchor]                     # всё после объёма (цвет/sim) — долой
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)   # пунктуация -> пробел

    tokens: list[str] = []
    for w in s.split():
        w = _ALIAS.get(w, w)              # айфон -> iphone
        if len(w) <= 1:                   # одиночные буквы ("e" из "E-Sim") — шум
            continue
        if w in _STOP or w in _COLORS:    # ловит цвет, если он попал ДО объёма
            continue
        if w.isdigit() and len(w) >= 5:   # артикулы/штрихкоды — мусор
            continue
        tokens.append(w)

    tokens = sorted(set(tokens))
    if st:
        tokens.append(st)                  # объём всегда в хвосте ключа
    return " ".join(tokens)


def collapse_variants(products: list[Product]) -> list[Product]:
    """Схлопнуть цвет-варианты одного товара (один model_key) в одну запись.

    Магазины дробят товар на цвета с одной ценой за объём (часть «под заказ»
    без цены). Берём представителя с минимальной известной ценой; in_stock —
    True, если в наличии хоть один вариант. Так на сравнение идёт одна цена за
    (модель+объём), а не 6 одинаковых строк.
    """
    groups: dict[str, list[Product]] = {}
    for p in products:
        groups.setdefault(p.model_key, []).append(p)
    out: list[Product] = []
    for items in groups.values():
        priced = [p for p in items if p.price is not None]
        rep = min(priced, key=lambda p: p.price) if priced else items[0]
        rep.in_stock = any(p.in_stock for p in items)
        out.append(rep)
    return out


# --- общий парсер цены (рубли) — переиспользуется всеми источниками ---
_PRICE_RE = re.compile(r"(\d[\d   .,]{2,})")


def parse_price(text: str | None) -> int | None:
    """Текст с ценой -> целое число рублей. "47 990 руб" -> 47990; мусор -> None.

    Берёт первую длинную числовую группу, чистит пробелы/неразрывные пробелы и
    разделители тысяч. Дробную часть (",00"/".00") отбрасывает.
    """
    if not text:
        return None
    m = _PRICE_RE.search(text.replace("&nbsp;", " "))
    if not m:
        return None
    raw = m.group(1)
    raw = re.sub(r"[   ]", "", raw)        # убрать разделители тысяч
    raw = re.sub(r"[.,]\d{1,2}$", "", raw)           # убрать копейки
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    val = int(digits)
    return val if val > 0 else None


def clean_title(title: str) -> str:
    """Свернуть пробелы/переносы для аккуратного показа."""
    return re.sub(r"\s+", " ", (title or "").replace("&nbsp;", " ")).strip()


# Б/У, уценка, восстановленные, % заряда батареи — НЕ сравниваем с новыми.
_USED_RE = re.compile(r"б\s*/?\s*у\b|\bбу\b|уцен|восстановл|refurb|trade.?in|\d{1,3}\s*%", re.I)


def is_used(title: str) -> bool:
    """True для Б/У/уценённых/восстановленных товаров (исключаем из сравнения новых)."""
    return bool(_USED_RE.search(title or ""))
