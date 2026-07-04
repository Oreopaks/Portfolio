"""
Data Cleaner — раскладывает карточку товара конкурента на АТОМАРНЫЕ поля для
точного сравнения с каталогом di-park.

atomize(title, price, old_price) -> dict:
    base_model, ram, rom, storage, sim_type, sim_label, color,
    region, region_raw, price, old_price, discount, model_key

Чистые функции (без сети/DOM) — тестируются офлайн. Построено НА normalize.py
(единый источник правды: model_key / storage / sim_type / color / parse_price),
добавляет то, чего там нет отдельным полем:
  • регион/спецификацию (CN / LL-A / EU / РСТ-ЕАС) — в model_key намеренно срезана
    как шум, но для карточки/цены критична (гарантия, серый импорт);
  • явное разделение RAM и ROM (8 / 256GB);
  • человеко-читаемую базовую модель и метку SIM.

Почему не Playwright «кликай каждую комбинацию»: конкуренты (sr57, iprice, ispace,
kingstore, mobilax, repremium) отдают КАЖДЫЙ SKU отдельной строкой листинга — цвет,
объём и тип SIM уже разнесены по карточкам. Комбо-селекторы нужны только сайту-
конфигуратору на JS; для таких см. reference-хелпер в README/скрейпере, здесь не нужен.
"""
from __future__ import annotations

import re
import unicodedata

from mvp7_price_scout.normalize import (  # единый источник правды
    _RAM_ROM_RE,
    clean_title,
    color_of,
    family_title,
    model_key,
    parse_price,
    sim_type_of,
    storage_of,
)


# --- Регион / спецификация поставки. Порядок важен: специфичные коды раньше. ---
# Латиница И кириллица (в объявлениях «СN» часто набрана русской «С»).
_REGION = [
    ("us",     re.compile(r"\bll\s*/?\s*a\b|\busa?\b|\bсша\b|америк", re.I)),
    ("cn",     re.compile(r"\b[cс]h?\s*/?\s*a\b|\b[cс]n\b|\bzp\s*/?\s*a\b|китай|гонконг|\bhk\b", re.I)),
    ("eu",     re.compile(r"\beu\b|\beur\b|европ|\bfa\s*/?\s*a\b|\bip\s*/?\s*a\b", re.I)),
    ("jp",     re.compile(r"\bj\s*/?\s*a\b|\bjp\b|япон", re.I)),
    ("ae",     re.compile(r"\bae\b|\baa\s*/?\s*a\b|оаэ|дубай|эмират", re.I)),
    ("ru",     re.compile(r"\bрст\b|\bеас\b|\beac\b|\bросте?ст\b|\bru\s*/?\s*a\b|официал", re.I)),
    ("global", re.compile(r"\bglobal\b|\bглобал", re.I)),
]


def region_of(title: str) -> tuple[str | None, str | None]:
    """Регион/спецификация из названия -> (код, исходный маркер) или (None, None).

    Код: us|cn|eu|jp|ae|ru|global. «iPhone 15 Pro LL/A» -> ("us", "LL/A").
    """
    s = unicodedata.normalize("NFKC", title or "")
    for code, rx in _REGION:
        m = rx.search(s)
        if m:
            return code, m.group(0).strip()
    return None, None


_BRAND_NOISE = re.compile(r"^\s*(?:смартфон|телефон|apple)\s+", re.I)


def base_model_of(title: str) -> str | None:
    """Человеко-читаемая базовая модель без объёма/цвета/скобок/бренд-шума.

    «Смартфон Apple iPhone 15 Pro Max 8/256GB Black (LL/A)» -> «iPhone 15 Pro Max».
    Бренд Apple срезаем (модель iphone уникальна), Samsung/Xiaomi оставляем.
    """
    s = family_title(title)                              # до объёма включительно, без цвета
    s = re.sub(r"\([^)]*\)", " ", s)                     # (LL/A), (Sim+E-Sim)
    s = _RAM_ROM_RE.sub(" ", s)                          # 8/256GB
    s = re.sub(r"\b\d{2,4}\s*(?:гб|gb)\b", " ", s, flags=re.I)   # 256Gb
    s = re.sub(r"\b\d{1,2}\s*(?:тб|tb)\b", " ", s, flags=re.I)   # 1TB
    while _BRAND_NOISE.search(s):
        s = _BRAND_NOISE.sub("", s)
    s = re.sub(r"\bapple\b", " ", s, flags=re.I)         # «Apple» в середине
    return re.sub(r"\s+", " ", s).strip() or None


def ram_rom(title: str) -> tuple[str | None, str | None]:
    """(RAM, ROM) раздельно. «8/256GB» -> ("8", "256GB"); «1TB» -> (None, "1TB").

    ROM берём каноничным storage_of (терпит «256 гб / 256gb / 256 GB / 8/256GB»)
    и приводим к верхнему регистру для показа.
    """
    m = _RAM_ROM_RE.search(unicodedata.normalize("NFKC", title or "").lower())
    ram = m.group(1) if m else None
    st = storage_of(title)                               # "256gb"/"1tb"/None
    rom = st.upper() if st else None
    return ram, rom


# eSIM-подтипы для метки. sim_type_of даёт каноничную ГРУППУ (esim/sim_esim/
# dual_sim) для матчинга; здесь добавляем «2×eSIM» (US-модели: две eSIM, без
# физической) и «слот для КП» (карта памяти) — на группу они не влияют.
_SIM_LABEL = {"esim": "eSIM only", "sim_esim": "nanoSIM + eSIM",
              "dual_sim": "Dual SIM (2×nanoSIM)"}
_TWO_ESIM = re.compile(r"\b2\s*e[\s\-_]?sim|dual\s*e[\s\-_]?sim|две\s*e[\s\-_]?sim", re.I)
_KP_SLOT = re.compile(r"слот\s+для\s+кп|карт[аы]\s+памяти|microsd|micro\s*sd|\btf\b", re.I)


def sim_of(title: str) -> tuple[str | None, str | None]:
    """(group, label). group = каноничная SIM-группа для матчинга (см. sim_type_of).

    «2 eSIM» / «Dual eSIM» -> esim + метка «2×eSIM». Наличие слота карты памяти
    дописываем в метку (не влияет на группу).
    """
    s = unicodedata.normalize("NFKC", title or "").lower().replace("ё", "е")
    if _TWO_ESIM.search(s):
        group, label = "esim", "2×eSIM"
    else:
        group = sim_type_of(title)
        label = _SIM_LABEL.get(group)
    if _KP_SLOT.search(s):
        label = f"{label} + слот КП" if label else "слот КП"
    return group, label


def _num(v) -> int | None:
    """Цену принимаем и числом, и строкой («119 990 ₽»)."""
    if isinstance(v, str):
        return parse_price(v)
    return v


def atomize(title: str, price=None, old_price=None) -> dict:
    """Карточка -> атомарный JSON-объект для сравнения с каталогом."""
    title = clean_title(title)
    ram, rom = ram_rom(title)
    group, label = sim_of(title)
    region, region_raw = region_of(title)
    # регион-маркер («LL/A», «CN») идёт в хвосте, где color_of ищет цвет — срезаем,
    # иначе «Natural Titanium LL/A» -> цвет «natural titanium ll»
    color_src = title
    for _code, _rx in _REGION:
        color_src = _rx.sub(" ", color_src)
    price = _num(price)
    old_price = _num(old_price)
    discount = old_price - price if (price and old_price and old_price > price) else None
    return {
        "base_model": base_model_of(title),
        "ram": ram,
        "rom": rom,
        "storage": storage_of(title),        # каноничная форма для группировки ("256gb")
        "sim_type": group,                   # esim | sim_esim | dual_sim | None
        "sim_label": label,
        "color": color_of(color_src),
        "region": region,                    # us|cn|eu|jp|ae|ru|global|None
        "region_raw": region_raw,
        "price": price,
        "old_price": old_price,
        "discount": discount,
        "model_key": model_key(title),       # канон для матчинга к di-park
    }
