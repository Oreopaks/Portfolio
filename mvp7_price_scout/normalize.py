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
    sim_type: str | None = None     # "esim"/"sim_esim"/"dual_sim"/None — guard матчинга (см. sim_type_of)
    color: str | None = None        # канон цвета (см. color_of) — для per-color цены нашего каталога
    fetched_at: str = ""            # ISO-время сбора (ставит collector)
    dipark_id: int | None = None    # id товара-эталона, к которому привязан

    def __post_init__(self) -> None:
        if not self.model_key:
            self.model_key = model_key(self.title)
        if self.storage is None:
            self.storage = storage_of(self.title)
        if self.sim_type is None:
            self.sim_type = sim_type_of(self.title)
        if self.color is None:
            self.color = color_of(self.title)


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
    # материал корпуса (часы) — не различает товар, а названия магазинов разнятся
    "aluminium", "aluminum", "алюминий", "алюминиевый",
    # описательный шум витрин у аксессуаров («Беспроводные наушники AirPods Pro
    # (3-го поколения)») — цифру поколения оставляем, слова-обвязку режем
    "наушники", "беспроводные", "проводные", "поколения", "поколение", "го",
    # кириллические варианты SIM (запрос «17 256 две симки» / «сим+есим»)
    "сим", "есим", "симка", "симки", "симкарта", "две",
    # ремешки часов: вариант ремешка не различаем (цены те же, а лексика
    # у магазинов вразнобой — фрагментирует семью до «не нашёл»)
    "band", "loop", "case", "with", "milanese", "alpine", "ocean", "trail",
    "sport", "braided", "solo", "link", "ремешок", "ремешком",
    # маркеры поколения: цифру оставляем (обработка в model_key), слово режем
    "gen", "generation",
}
# Цвета (RU+EN). НЕ включаем pro/max/plus/air/ultra/mini — это модель, не цвет!
_COLORS = {
    "black", "white", "blue", "red", "green", "yellow", "purple", "pink",
    "gold", "silver", "gray", "grey", "graphite", "titanium", "midnight",
    "starlight", "space", "orange", "teal", "lavender", "cream", "mint",
    "sierra", "pacific", "desert", "natural", "ultramarine", "coral",
    "rose", "jet", "slate", "navy",       # Rose Gold / Jet Black / Slate / Navy
    "чёрный", "черный", "белый", "синий", "красный", "зелёный", "зеленый",
    "жёлтый", "желтый", "фиолетовый", "розовый", "золотой", "золото",
    "серебристый", "серебро", "серый", "графит", "графитовый", "титан",
    "титановый", "полночный", "космический", "оранжевый", "бирюзовый",
    "лавандовый", "бежевый", "голубой",
    "черные", "белые",                    # мн.ч. у аксессуаров («наушники белые»)
    # женский род (колонки, станции: «Яндекс Станция оранжевая»)
    "черная", "белая", "синяя", "красная", "зеленая", "серая", "розовая",
    "фиолетовая", "желтая", "голубая", "бежевая", "серебристая", "золотая",
    "бирюзовая", "лавандовая", "оранжевая",
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


# Тип SIM — ЖЁСТКОЕ разделение SKU на три несовместимые группы (разные рынки/цены):
# eSIM-only (глобал/импорт), физическая+eSIM («Sim+E-Sim», ЕАС) и две физические
# SIM (Китай/ГК «2 nano-SIM»). Сравнивать цены МОЖНО только внутри одной группы
# (guard в match.py/store.py). Из model_key sim по-прежнему выкинут — отдельный признак.
# \b обязателен: без него «Blue Sim+eSIM» терял «e Sim» из хвоста цвета и
# давал ложный esim-only для физической симки.
_ESIM_RE = re.compile(r"\be[\s\-_]?sim|\bесим\b|\bе[\s\-_]?сим\b", re.I)
# Физическая nano-SIM. Голое "dual"/"двойн" НЕ считаем физикой: «Dual eSIM» (US,
# 2×eSIM) — это eSIM-группа. Требуем именно sim/nano/сим-токен (eSIM уже вычтен).
_PHYS_SIM_RE = re.compile(
    r"\bsim\b|nano[\s\-]?sim|две\s*sim|2\s*sim|физическ|\bсим\w*|две\s*сим", re.I)
# Две ФИЗИЧЕСКИЕ SIM без eSIM (китайская/гонконгская версия): «2 nano-SIM»,
# «Dual SIM», «две симки» — отдельный SKU, не путать с «Sim+eSIM».
_DUAL_SIM_RE = re.compile(
    r"\bdual\s*sim\b|dual\s*nano|две\s*sim|две\s*сим|\b2\s*(?:nano[\s\-]?)?sim\b|"
    r"\b2\s*сим\b|двойн\w*\s*sim", re.I)


def sim_type_of(title: str) -> str | None:
    """Тип SIM из названия: "esim" / "sim_esim" / "dual_sim" / None (не указан).

      • "esim"     — только eSIM (вкл. «Dual eSIM»), без физической симки;
      • "sim_esim" — физическая nano-SIM + eSIM («Sim+E-Sim», «Nano-SIM + eSIM»);
      • "dual_sim" — две физические SIM без eSIM («2 nano-SIM», Китай/ГК).

    eSIM-вхождения вычитаем ПЕРЕД поиском физической/двойной симки, иначе
    «Sim+E-Sim» дал бы ложный esim-only, а «Dual eSIM» — ложный dual_sim.
    """
    s = unicodedata.normalize("NFKC", title or "").lower().replace("ё", "е")
    has_esim = bool(_ESIM_RE.search(s))
    phys_s = _ESIM_RE.sub(" ", s)                     # убрать eSIM, остаток = физика
    has_dual = bool(_DUAL_SIM_RE.search(phys_s))
    has_phys = has_dual or bool(_PHYS_SIM_RE.search(phys_s))
    if has_dual and not has_esim:
        return "dual_sim"                             # 2 физ. SIM без eSIM (Китай)
    if has_phys:
        return "sim_esim"                             # физ. SIM (+ обычно eSIM)
    return "esim" if has_esim else None


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
    "series": "s", "серия": "s",          # Watch Series 10 == Watch S10
    "2nd": "2", "3rd": "3", "4th": "4", "5th": "5", "1st": "1",  # 2nd gen == 2
}

# Серия+номер, написанные раздельно («SE 2», «Series 10» -> se2/s10) — сливаем,
# иначе «Watch SE 2» и «Watch SE2» дают разные ключи.
_SERIES = {"se", "s", "a", "m", "mi"}
# ...но не в названиях фототехники: у объективов «AF-S 24-120mm» цифра — фокусное,
# слияние в «s24» дало бы ложное попадание в телефоны.
_NO_SERIES_MERGE = {"lens", "kit", "фотоаппарат", "объектив", "macro"}


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
    # размер часов: «42 mm»/«42 мм» -> «42mm» (иначе id-guard матчинга рвёт
    # ВСЮ категорию Watch между магазинами)
    s = re.sub(r"\b(\d{2})\s*(?:mm|мм)\b", r"\1mm", s)
    # PS5/PS4 -> «playstation 5»: у di-park консоль зовётся «PlayStation 5», а игры
    # и часть магазинов — «PS5». Без унификации приставка/игры не матчатся между
    # магазинами (ps5 != playstation). За приставками охотится клиент.
    s = re.sub(r"\bps\s*([345])\b", r"playstation \1", s)
    anchor: int | None = None
    for rx in (_RAM_ROM_RE, _TB_RE, _GB_RE):
        m = rx.search(s)
        if m:
            anchor = m.start() if anchor is None else min(anchor, m.start())
    if anchor is not None:
        s = s[:anchor]                     # всё после объёма (цвет/sim) — долой
    # «Pro+» != «Pro» (разные модели!): плюс перед пробелом/концом -> слово plus.
    # «Sim+E-Sim» не трогаем (за «+» идёт буква).
    s = re.sub(r"\+(?=\s|$)", " plus ", s)
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)   # пунктуация -> пробел

    raw = [_ALIAS.get(w, w) for w in s.split()]       # айфон -> iphone
    # мусор — до слияния серий: «SE (Gen.2)» должен стать [se, 2] -> se2
    raw = [w for w in raw
           if w not in _STOP and w not in _COLORS
           and not (w.isdigit() and len(w) >= 5)              # артикулы/штрихкоды
           and not (w.isdigit() and len(w) == 4 and w[:2] in ("19", "20"))]  # год «2025»
    merged: list[str] = []
    can_merge = not (_NO_SERIES_MERGE & set(raw))
    i = 0
    while i < len(raw):                   # se|s|a|m|mi + 1-2 цифры -> se2/s10/a54
        if (can_merge and raw[i] in _SERIES and i + 1 < len(raw)
                and raw[i + 1].isdigit() and len(raw[i + 1]) <= 2):
            merged.append(raw[i] + raw[i + 1])
            i += 2
        else:
            merged.append(raw[i])
            i += 1

    tokens: list[str] = []
    for w in merged:
        if len(w) <= 1 and not w.isdigit():   # одиночные буквы ("e" из "E-Sim") — шум,
            continue                          # но цифра = номер модели (AirPods 4, Ultra 2)
        tokens.append(w)

    tokens = sorted(set(tokens))
    low_full = unicodedata.normalize("NFKC", title).lower()
    if re.search(r"\blte\b|cellular|\bсотов", low_full):
        # LTE/Cellular-версия планшета — другой товар (разница 10-15 тыс.);
        # токен в _VARIANT матчинга, чтобы Wi-Fi не матчился к LTE
        tokens.append("cellular")
    m = _RAM_ROM_RE.search(low_full)
    if m:
        # RAM различает SKU (8/256 и 12/256 — разные товары с разной ценой),
        # иначе collapse_variants схлопнет их в цену дешёвого. В match.py этот
        # токен ИСКЛЮЧЁН из жёсткого guard'а (конкурент может RAM не писать).
        tokens.append(f"ram{int(m.group(1))}")
    if st:
        tokens.append(st)                  # объём всегда в хвосте ключа
    return " ".join(tokens)


def collapse_variants(products: list[Product]) -> list[Product]:
    """Схлопнуть цвет-варианты одного товара (один model_key) в одну запись.

    Схлопываем только ИСТИННЫЕ дубли — одинаковые (модель+объём+SIM+цвет),
    дублирующиеся по SKU/наличию. Берём представителя с минимальной известной
    ценой; in_stock — True, если в наличии хоть один вариант.

    Группа = (model_key, sim_type, color). Цвет и SIM не схлопываем: у этого
    каталога цена по цвету различается (~33% товаров), а eSIM-only ≠ Sim+E-Sim —
    схлопывание дало бы ложное «дешевле» и неверную цену для запрошенного цвета.
    """
    groups: dict[tuple[str, str | None, str | None], list[Product]] = {}
    for p in products:
        groups.setdefault((p.model_key, p.sim_type, p.color), []).append(p)
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


def family_title(title: str) -> str:
    """Название ДО объёма включительно (без цвета) — для подписей/группировки семьи.

    «Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)» -> «Apple iPhone 17 Pro 256Gb».
    Без объёма (наушники, часы) — возвращаем как есть.
    """
    s = clean_title(title)
    low = s.lower()
    end: int | None = None
    for rx in (_RAM_ROM_RE, _TB_RE, _GB_RE):
        m = rx.search(low)
        if m:
            end = m.end() if end is None else max(end, m.end())
    return s[:end].strip() if end is not None else s


def color_of(title: str) -> str | None:
    """Цвет/комплектация товара = нормализованный хвост ПОСЛЕ объёма памяти.

    У ритейла бренд+модель идут ДО объёма, цвет — ПОСЛЕ ("256Gb Deep Blue").
    Берём всё после объёма, выкидываем SIM-скобки и шум -> канон цвета для
    группировки нашего каталога (di-park) по цвету. Без объёма (наушники, часы,
    стилус) якоря нет — берём известные цвет-слова (_COLORS) из названия:
    «Watch S10 46mm Rose Gold» -> "rose gold" (иначе Watch не дробятся по цвету,
    а цвет-слова утекали бы в model_key и рвали семью).

    Цвета между магазинами называются по-разному (Midnight/Black/Чёрный), поэтому
    этот ключ применяем ТОЛЬКО к нашему каталогу для показа per-color цены, а не
    для матчинга конкурентов (те матчатся по модель+объём+SIM, цвет-агностично).
    """
    s = clean_title(title)
    low = s.lower()
    end: int | None = None
    for rx in (_RAM_ROM_RE, _TB_RE, _GB_RE):
        m = rx.search(low)
        if m:
            end = m.end() if end is None else max(end, m.end())
    if end is None:
        tail = re.sub(r"[^\w]+", " ", low, flags=re.UNICODE).replace("ё", "е")
        words = [w for w in tail.split() if w in _COLORS]
        return " ".join(words) or None
    tail = re.sub(r"\([^)]*\)", " ", s[end:])             # выкинуть (Sim+E-Sim)
    tail = re.sub(r"[^\w]+", " ", tail, flags=re.UNICODE).lower().replace("ё", "е")
    words = [w for w in tail.split()
             if len(w) > 1 and not w.isdigit() and w not in _STOP]
    return " ".join(words) or None


# Б/У, уценка, восстановленные, % заряда батареи — НЕ сравниваем с новыми.
# RFB = refurbished, «Актив»/«активированный», «копия», витринные экземпляры.
_USED_RE = re.compile(
    r"б\s*/?\s*у\b|\bбу\b|уцен|восстановл|refurb|trade.?in|"
    # процент — только В КОНТЕКСТЕ БАТАРЕИ (Б/У «АКБ 89%»), не голый «100% Arabica»
    r"(?:батар|акб|аккум|заряд)\w*\s*\d{1,3}\s*%|\d{1,3}\s*%\s*(?:батар|акб|аккум|заряд)|"
    # «актив»/«активирован» = активированный экземпляр, намеренно вне сравнения с
    # запечатанным новым (цены несопоставимы) — см. test_used_detects_rfb_copy_showcase
    r"\brfb\b|актив|копия|витрин", re.I)


def is_used(title: str) -> bool:
    """True для Б/У/уценённых/восстановленных товаров (исключаем из сравнения новых)."""
    return bool(_USED_RE.search(title or ""))


# Спец/лимитированные/эксклюзивные издания: цена сильно выше стандарта, а model_key
# их не различает (цвет/эдишн срезаются) -> кросс-матч со стандартом даёт ложные
# сигналы «дешевле/дороже». Исключаем из сравнения, как Б/У (сравниваем сопоставимое).
_SPECIAL_RE = re.compile(
    r"эксклюзив|лимитир|\blimited\b|iron\s*man|marvel|мстител|"
    r"кастом|\bcustom\b|\bбайки\b|коллекц|\bcollector",
    re.I,
)
# ВАЖНО: голого слова «Edition» здесь НЕТ намеренно. Оно — часть официального имени
# массы штатных SKU (Deluxe/Gold/Ultimate/Digital/Comfort/Black Edition игр, мышей,
# роутеров) с обычной ценой, а не признак редкости. Флагаем спец-издание только по
# реальным маркерам редкости выше — иначе теряли 44 товара/прогон из базы di-park.


def is_special_edition(title: str) -> bool:
    """True для спец/эксклюзив/лимитированных изданий (несопоставимы со стандартом)."""
    return bool(_SPECIAL_RE.search(title or ""))
