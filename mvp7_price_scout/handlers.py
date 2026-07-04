"""
Логика бота: поиск товара в каталоге эталона + рендер компактной таблицы цен.

Чистые функции рендера (тестируемы офлайн) + handle_text() как роутер команд.
Бот никогда не парсит в реальном времени — только читает срез из SQLite.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from mvp7_price_scout import store
from mvp7_price_scout.normalize import _STOP, model_key, color_of, family_title, sim_type_of

ROOT = str(Path(__file__).resolve().parents[1])   # корень репо (freelance-mvp)


@dataclass
class Reply:
    """Ответ бота: текст + опциональные inline-кнопки [(подпись, callback_data)].

    callback_data всегда «p:{id}» — тап по любой кнопке открывает карточку товара
    с этим id (подсказка-семья ИЛИ другой цвет). bot.py строит reply_markup.
    """
    text: str
    buttons: list | None = None

SHOP_LABEL = {
    "sr57": "sr57.ru", "repremium": "repremium", "iprice": "iprice",
    "ispace": "ispace", "kingstore": "KingStore", "mobilax": "Мобилакс",
    "smart_room_57": "Instagram", "di-park": "Di-Park",
}
# Метка типа SIM в карточке/выгрузке (жёсткое разделение SKU, см. sim_type_of).
_SIM_TAG = {"esim": " · eSIM", "sim_esim": " · Sim+eSIM", "dual_sim": " · 2 SIM"}
HELP = (
    "Я сравниваю цены Di-Park с конкурентами Орла.\n\n"
    "• Напиши товар — пришлю таблицу цен.\n"
    "  Примеры: <code>iphone 17 pro max 256</code>, <code>galaxy s24 256</code>, "
    "<code>airpods pro 2</code>\n"
    "• /top — где мы дороже всех (теряем продажи)\n"
    "• /stats — наша позиция на рынке одним взглядом\n"
    "• /export — выгрузить всё сравнение в Excel/CSV\n"
    "• /refresh — обновить цены конкурентов (только админ)\n"
    "• /status — прогресс обновления цен"
)


def fmt_int(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}".replace(",", " ")


def _esc(s: str) -> str:
    """Экранировать скрапленный/юзерский текст для parse_mode=HTML (&, <, >).

    Цены/лейблы статичны, экранируем только динамику — иначе title с «<»/«&»
    (или юзер-ввод вроде «<b») роняет сообщение в Telegram (400), и ответ молча
    теряется. quote=False — кавычки в тексте экранировать не нужно.
    """
    return html.escape(s or "", quote=False)


def fmt_ago(iso: str | None) -> str:
    """ISO-время сбора -> «2ч назад» / «5м назад» / «3дн назад»."""
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return "?"
    sec = (datetime.now() - dt).total_seconds()
    if sec < 3600:
        return f"{int(sec // 60)}м назад"
    if sec < 86400:
        return f"{int(sec // 3600)}ч назад"
    return f"{int(sec // 86400)}дн назад"


def _label(shop: str, source_type: str) -> str:
    base = SHOP_LABEL.get(shop, shop)
    if source_type == "yandex":
        return base + "🅈"
    if source_type in ("ig", "ig_ocr"):
        return base + "📷"
    return base


def _short_title(title: str) -> str:
    """Убрать шум для показа: (Sim+E-Sim), лишние пробелы, префикс Apple.

    Цвет ОСТАВЛЯЕМ: каталог хранится per-color и цена за цвет точная — показать
    «iPhone 17 Pro 256Gb Deep Blue» корректно (см. find_product / color_of).
    """
    t = re.sub(r"\([^)]*\)", "", title or "")
    t = re.sub(r"^\s*Apple\s+", "", t, flags=re.I)     # «Apple iPhone» -> «iPhone»
    return re.sub(r"\s+", " ", t).strip()


# Аксессуар-слова: в подсказках сам товар ранжируем выше аксессуара к нему
# («s24» — сначала телефон Galaxy, потом чехлы PITAKA S24).
_ACCESSORY = {"чехол", "чехлы", "накладка", "стекло", "пленка", "ремешок",
              "кабель", "зарядка", "зарядное", "адаптер", "защитное"}


# Цвет в запросе RU -> EN (каталог di-park называет цвета по-английски).
_COLOR_RU = {
    "чёрный": "black", "черный": "black", "белый": "white", "синий": "blue",
    "голубой": "blue", "красный": "red", "зелёный": "green", "зеленый": "green",
    "жёлтый": "yellow", "желтый": "yellow", "серый": "gray", "серебристый": "silver",
    "серебро": "silver", "золотой": "gold", "золото": "gold", "фиолетовый": "purple",
    "розовый": "pink", "оранжевый": "orange", "титановый": "titanium", "титан": "titanium",
    "бирюзовый": "teal", "графит": "graphite", "графитовый": "graphite",
}


def _query_colors(query: str, vocab: set) -> set:
    """Цвет(а) из запроса -> EN-токены для сопоставления с цветом каталога.

    Цвет = буквенный токен, которого нет ни в модель-словаре каталога (vocab),
    ни в стоп-словах (_STOP: sim/esim/новый/... — это НЕ цвет, иначе «sim+esim»
    из запроса уплывал бы в цвет-фильтр). RU переводим в EN (синий->blue).
    """
    out: set = set()
    for w in re.sub(r"[^\w]+", " ", query.lower().replace("ё", "е"), flags=re.UNICODE).split():
        w = _COLOR_RU.get(w, w)
        if len(w) > 1 and not any(c.isdigit() for c in w) and w not in vocab and w not in _STOP:
            out.add(w)
    return out


def _qtokens(qk: str, vocab: set) -> set:
    """Значимые токены запроса для сопоставления с каталогом.

    Голое число объёма приводим к каталожной форме: «256» -> «256gb» (иначе
    покрытие не различало бы 256 и 512 — они не пинили семью). Прочее держим,
    если это токен каталога или цифросодержащее (модель). Буквенный шум (цвет)
    отсекается — он не в vocab.
    """
    out: set = set()
    for t in qk.split():
        if t.isdigit() and (t + "gb") in vocab:
            out.add(t + "gb")                          # 256 -> 256gb (объём)
        elif t in vocab or any(c.isdigit() for c in t):
            out.add(t)
    return out or set(qk.split())                      # запрос — только цвет/шум: не теряем


def find_product(conn, query: str, min_score: int = 55) -> dict | None:
    """Найти товар эталона под запрос: лучшая семья модель+объём, затем нужный цвет.

    Ранжируем по доле токенов запроса в товаре, потом token_sort_ratio — иначе
    короткий «galaxy s24» цепляет чехол «Pitaka S24». Цвет/шум (буквенные токены
    вне словаря каталога) на поиск семьи не влияют. Затем внутри семьи выбираем
    строку запрошенного типа SIM («sim+esim» -> Sim+E-Sim, не дешёвый eSIM-only)
    и запрошенного цвета (каталог per-color, цена за цвет точная); если SIM/цвет
    не указан или не найден — берём самый дешёвый вариант.
    """
    qk = model_key(query)
    if not qk:
        return None
    cands = store.search_base(conn, qk)
    if not cands:
        return None
    vocab = set().union(*(set(r["model_key"].split()) for r in cands))
    qtok = _qtokens(qk, vocab)
    ekey = " ".join(sorted(qtok))

    def coverage(r: dict) -> float:
        return len(qtok & set(r["model_key"].split())) / len(qtok) if qtok else 0.0

    best = max(cands, key=lambda r: (coverage(r), fuzz.token_sort_ratio(ekey, r["model_key"])))
    cov = coverage(best)
    # fuzz-порог только при неполном покрытии: короткий запрос («ipad», «17»)
    # против длинного ключа даёт низкий fuzz даже при cov=1.0 — не тупик
    if cov < 0.5 or (cov < 1.0 and fuzz.token_sort_ratio(ekey, best["model_key"]) < min_score):
        return None

    fam = [r for r in cands
           if r["model_key"] == best["model_key"] and r["storage"] == best["storage"]]
    qsim = sim_type_of(query)
    if qsim:                              # запрошен тип SIM — сужаем семью на него
        fam = [r for r in fam if sim_type_of(r["title"]) == qsim] or fam
    want = _query_colors(query, vocab)
    if want:
        picked = [r for r in fam if want & set((color_of(r["title"]) or "").split())]
        if picked:
            fam = picked
    return min(fam, key=lambda r: (r["price"] is None, r["price"] or 0))


def _cheapest_row(rows: list[dict]) -> dict:
    return min(rows, key=lambda r: (r["price"] is None, r["price"] or 0))


def _fam_label(title: str) -> str:
    """Подпись кнопки-семьи: без цвета, без (Sim+E-Sim), без Apple-префикса."""
    t = re.sub(r"\([^)]*\)", "", family_title(title))
    t = re.sub(r"^\s*Apple\s+", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def search_suggestions(conn, query: str, limit: int = 8, min_score: int = 45) -> list[dict]:
    """Ранжированные подсказки-СЕМЬИ (модель+объём) под свободный запрос.

    Пользователь пишет названия по-разному — вместо тупика «не нашёл» отдаём
    список ближайших товаров. Группируем по (model_key, storage): одна кнопка на
    семью, представитель — запрошенный цвет (если указан) либо самый дешёвый.
    Возвращаем [{id, label, price, score}] отсортированно по релевантности.
    """
    qk = model_key(query)
    if not qk:
        return []
    cands = store.search_base(conn, qk)
    if not cands:
        return []
    qsim = sim_type_of(query)
    if qsim:                              # запрошен тип SIM — семьи/цены только его
        cands = [r for r in cands if sim_type_of(r["title"]) == qsim] or cands
    vocab = set().union(*(set(r["model_key"].split()) for r in cands))
    qtok = _qtokens(qk, vocab)
    ekey = " ".join(sorted(qtok))
    want = _query_colors(query, vocab)

    def score(r: dict) -> tuple:
        cov = len(qtok & set(r["model_key"].split())) / len(qtok) if qtok else 0.0
        return (cov, fuzz.token_sort_ratio(ekey, r["model_key"]))

    fams: dict[tuple, list[dict]] = {}
    for r in cands:
        fams.setdefault((r["model_key"], r["storage"]), []).append(r)

    out: list[dict] = []
    for rows in fams.values():
        sc = max(score(r) for r in rows)
        # fuzz-порог только при неполном покрытии (см. find_product): иначе
        # «ipad» терял все 25 семей iPad и бот отвечал «Не нашёл»
        if sc[0] < 0.5 or (sc[0] < 1.0 and sc[1] < min_score):
            continue
        colored = [r for r in rows if want & set((color_of(r["title"]) or "").split())] if want else []
        rep = _cheapest_row(colored or rows)
        if colored:                                    # запрошенный цвет найден — подпись с цветом
            label = f"{_short_title(rep['title'])} — {fmt_int(rep['price'])} ₽"
        else:
            prices = [r["price"] for r in rows if r["price"] is not None]
            tail = f" — от {fmt_int(min(prices))} ₽" if prices else ""
            label = _fam_label(rep["title"]) + tail
        acc = int(bool(_ACCESSORY & set(rep["model_key"].split())))
        out.append({"id": rep["id"], "label": label, "price": rep["price"],
                    "score": sc, "accessory": acc})

    if not out:
        return []
    # сначала по покрытию, затем товары раньше аксессуаров, затем fuzz, затем дешёвые
    out.sort(key=lambda x: (-x["score"][0],
                            x["accessory"],
                            -x["score"][1],
                            x["price"] if x["price"] is not None else 10 ** 9))
    topcov = out[0]["score"][0]
    out = [s for s in out if s["score"][0] == topcov]   # только верхний слой покрытия (без 16/14 под «17»)
    return out[:limit]


def _variant_buttons(conn, base_row: dict) -> list:
    """Кнопки других цветов той же семьи (у каждого своя цена) — per-color выбор.

    Только цвета С ценой (None-цена как кнопка бесполезна), по одному на цвет.
    """
    btns = []
    seen: set = set()
    for r in store.family_colors(conn, base_row):
        col = (color_of(r["title"]) or "вариант").title()
        if r["id"] == base_row["id"] or r["price"] is None or col in seen:
            continue
        seen.add(col)
        btns.append((f"{col} — {fmt_int(r['price'])} ₽", f"p:{r['id']}"))
    return btns[:6]


def _dedup_comps(comps: list[dict]) -> list[dict]:
    """Одна строка на (магазин, тип источника) — его ЛУЧШАЯ цена.

    Матчер цвет-агностичен, поэтому один магазин даёт несколько строк семьи
    (цвета/варианты) с разными ценами — как «5 конкурентов» это шум и раздувает
    счётчик «Дороже тебя». Вход отсортирован по цене (competitors_for: NULL в
    хвосте), значит первая строка магазина = его минимальная цена; остальные
    отбрасываем. Строка без цены выживает только у магазина, где цен нет вовсе.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in comps:
        key = (c["shop"], c["source_type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def render_comparison(conn, base_row: dict) -> str:
    """Понятная карточка владельцу: вердикт + кто дешевле/дороже тебя + что сделать."""
    our = base_row["price"]
    comps = _dedup_comps(store.competitors_for(conn, base_row))
    sim_tag = _SIM_TAG.get(sim_type_of(base_row["title"]), "")
    lines = [f"📱 {_esc(_short_title(base_row['title']))}{sim_tag}"]
    lines.append(f"💰 Твоя цена: {fmt_int(our)} ₽" if our else "💰 Твоя цена: под заказ")

    # Валидные (тип SIM совпал) vs флагнутые (немаркированный конкурент с ценой
    # уровня eSIM-версии) — в вердикт/«Поставь» идут ТОЛЬКО валидные, sim_ok=True.
    priced = sorted([c for c in comps if c["price"] is not None and c.get("sim_ok", True)],
                    key=lambda c: c["price"])
    flagged = sorted([c for c in comps if c["price"] is not None and not c.get("sim_ok", True)],
                     key=lambda c: c["price"])
    missing = [c for c in comps if c["price"] is None]

    def flagged_lines() -> list[str]:
        if not flagged:
            return []
        out = ["\n⚠️ Не учитываю (цена уровня eSIM-версии, тип SIM у конкурента "
               "не указан — сверь вручную):"]
        out += [f" • {_label(c['shop'], c['source_type'])} — {fmt_int(c['price'])} ₽"
                for c in flagged]
        return out

    if not priced:
        lines.append("\nКонкурентов с этим товаром не нашёл.")
        lines += flagged_lines()
        if missing:
            lines.append("◽ есть, но без цены: " + ", ".join(
                sorted({_label(c["shop"], c["source_type"]) for c in missing})))
        lines.append(f"🕒 {fmt_ago(base_row.get('fetched_at'))}")
        return "\n".join(lines)

    def row(c: dict, sign: str) -> str:
        ap = "~" if c["source_type"] == "ig_ocr" else ""        # OCR — нужна сверка
        tail = f"  ({sign}{fmt_int(abs(c['price'] - our))} ₽)" if our else ""
        return f" • {_label(c['shop'], c['source_type'])} — {ap}{fmt_int(c['price'])} ₽{tail}"

    if our:
        cheaper = [c for c in priced if c["price"] < our]
        equal = [c for c in priced if c["price"] == our]
        pricier = [c for c in priced if c["price"] > our]
        lines.append("")
        if not cheaper:
            lines.append("🟢 Дешевле тебя никого нет — ты в топе 👍")
        elif len(cheaper) == len(priced):
            lines.append("🔴 Ты дороже ВСЕХ — здесь теряешь покупателей")
        else:
            lines.append(f"🟡 Тебя обходят по цене: {len(cheaper)} из {len(priced)}")
        if cheaper:
            lines.append(f"\n🔴 Дешевле тебя ({len(cheaper)}):")
            lines += [row(c, "−") for c in cheaper]
        if equal:
            lines.append("\n⚪ Такая же цена: " + ", ".join(
                _label(c["shop"], c["source_type"]) for c in equal))
        if pricier:
            lines.append(f"\n🟢 Дороже тебя ({len(pricier)}):")
            lines += [row(c, "+") for c in pricier]
        if cheaper:
            # ориентир «Поставь» — только по ВАЛИДНЫМ (тип SIM совпал) и без OCR-цен
            # (нужна сверка). Немаркированный eSIM-конкурент сюда уже не попадёт: он
            # отфильтрован в priced (sim_ok=False) — корень бага «поставь 94 890 ₽».
            floor = next((c for c in priced if c["source_type"] != "ig_ocr"), None)
            if floor:
                lines.append(f"\n🎯 Поставь {fmt_int(floor['price'] - 100)} ₽ → станешь дешевле всех")
    else:
        lines.append("\nЦены конкурентов:")
        lines += [row(c, "") for c in priced]

    lines += flagged_lines()
    if missing:
        lines.append("◽ без цены: " + ", ".join(
            sorted({_label(c["shop"], c["source_type"]) for c in missing})))
    newest = max((c.get("fetched_at") or "" for c in comps), default="")
    lines.append(f"🕒 обновлено {fmt_ago(newest)}")
    return "\n".join(lines)


def render_stats(conn) -> str:
    """Сводка позиции Di-Park на рынке (для команды /stats)."""
    mp = store.market_position(conn)
    if not mp["total"]:
        return "Пока нет сопоставленных товаров — запусти сбор (collector)."
    t = mp["total"]
    pct = lambda n: f"{round(n / t * 100)}%"
    # свежесть по источникам — владелец видит сам, если какой-то магазин протух
    fresh = "\n".join(
        f" • {_label(r['shop'], r['source_type'])} — {r['n']} тов., {fmt_ago(r['last'])}"
        for r in store.stats(conn) if r["source_type"] != "base")
    return (
        "📊 Твоя позиция на рынке\n"
        f"Сравнил {t} твоих товаров с конкурентами:\n\n"
        f"🟢 Ты дешевле всех:  {mp['cheaper']} ({pct(mp['cheaper'])})\n"
        f"🔴 Ты дороже всех:   {mp['pricier']} ({pct(mp['pricier'])})  ← тут теряешь\n"
        f"⚪ Наравне:           {mp['equal']}\n\n"
        f"Где дороже — в среднем на {mp['avg_loss_pct']}% выше конкурента.\n"
        "Список где теряешь → /top\n\n"
        f"🕒 Свежесть цен:\n{fresh}"
    )


def _comparison_rows(conn) -> tuple[list[str], list[dict]]:
    """Собрать данные сравнения: (список магазинов, строки с вычисленными полями).

    Через ту же семейную выборку, что карточка бота (competitors_for: семья +
    SIM-guard + in_stock) — иначе Excel противоречил боту (в боте «дороже всех»,
    в Excel «дешевле всех») и содержал неотличимые дубли одного названия с
    разными ценами (eSIM и Sim+eSIM без пометки).
    """
    shops = [r["shop"] for r in conn.execute(
        "SELECT DISTINCT shop FROM products WHERE source_type!='base' ORDER BY shop")]

    items: list[dict] = []
    for rows in store._base_families(conn):
        rep = min(rows, key=lambda r: (r["price"] is None, r["price"] or 0))
        comps = _dedup_comps(store.competitors_for(conn, rep))
        pv: dict[str, int] = {}
        for c in comps:
            if (c["price"] is not None and c.get("sim_ok", True)
                    and (c["shop"] not in pv or c["price"] < pv[c["shop"]])):
                pv[c["shop"]] = c["price"]
        if not pv:
            continue                        # без конкурентов в выгрузке делать нечего
        prices = {s: pv.get(s) for s in shops}
        mn = min(pv.values())
        mn_shop = SHOP_LABEL.get(min(pv, key=pv.get), min(pv, key=pv.get))
        our = rep["price"]
        if our is None:
            status, gap = "под заказ", None
        elif our > mn:
            status, gap = "🔴 дороже всех", our - mn
        elif our < mn:
            status, gap = "🟢 дешевле всех", our - mn
        else:
            status, gap = "⚪ наравне", 0
        sim_tag = _SIM_TAG.get(sim_type_of(rep["title"]), "")
        items.append({"title": _short_title(rep["title"]) + sim_tag, "our": our,
                      "prices": prices, "mn": mn, "mn_shop": mn_shop,
                      "gap": gap, "status": status})
    # сначала где сильнее проигрываем (положительный gap), потом остальное
    items.sort(key=lambda x: (x["gap"] if x["gap"] is not None else -10**9), reverse=True)
    return shops, items


def build_export_xlsx(conn) -> str:
    """Красивый .xlsx сравнения: цветовой статус, формат ₽, сортировка по потерям."""
    import tempfile

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    shops, items = _comparison_rows(conn)
    money = '# ##0" ₽";-# ##0" ₽";0'      # отрицательная наценка видима (мы дешевле)
    red = PatternFill("solid", fgColor="FFC7CE")
    green = PatternFill("solid", fgColor="C6EFCE")
    yellow = PatternFill("solid", fgColor="FFEB9C")

    wb = Workbook()
    ws = wb.active
    ws.title = "Сравнение цен"
    headers = ["Товар", "Наша цена", *[SHOP_LABEL.get(s, s) for s in shops],
               "Мин у конкур.", "Где дешевле", "Наценка к мин", "Статус"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for it in items:
        ws.append([it["title"], it["our"], *[it["prices"][s] for s in shops],
                   it["mn"], it["mn_shop"], it["gap"], it["status"]])
        r = ws.max_row
        for cell in ws[r]:
            if isinstance(cell.value, (int, float)):
                cell.number_format = money
        fill = {"🔴 дороже всех": red, "🟢 дешевле всех": green, "⚪ наравне": yellow}.get(it["status"])
        if fill:
            ws.cell(row=r, column=2).fill = fill           # наша цена
            ws.cell(row=r, column=len(headers)).fill = fill  # статус

    ws.column_dimensions["A"].width = 46
    for i in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    mp = store.market_position(conn)
    s2 = wb.create_sheet("Сводка")
    for row in [["Показатель", "Значение"],
                ["Товаров с конкурентами", mp["total"]],
                ["Мы дешевле всех", mp["cheaper"]],
                ["Мы дороже всех", mp["pricier"]],
                ["Наравне", mp["equal"]],
                ["Средний проигрыш где дороже, %", mp["avg_loss_pct"]]]:
        s2.append(row)
    for c in s2[1]:
        c.font = Font(bold=True)
    s2.column_dimensions["A"].width = 34
    s2.column_dimensions["B"].width = 12

    fd = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    path = fd.name
    fd.close()
    wb.save(path)
    return path


def render_top(conn, limit: int = 15) -> str:
    """Где ты дороже конкурентов — тут теряешь продажи (для /top)."""
    gaps = store.biggest_gaps(conn, limit)
    if not gaps:
        return "👍 Нет товаров, где ты дороже конкурентов (или база пуста)."
    lines = ["📉 Где ты дороже конкурентов — тут теряешь продажи:", ""]
    for i, g in enumerate(gaps, 1):
        shop = SHOP_LABEL.get(g["min_shop"], g["min_shop"])
        lines.append(f"{i}. {_esc(_short_title(g['title']))}")
        lines.append(f"    ты {fmt_int(g['our_price'])} ₽  →  у {shop} "
                     f"{fmt_int(g['min_comp'])} ₽  (дешевле на {fmt_int(g['gap'])} ₽)")
    return "\n".join(lines)


def _bar(done: int, total: int, width: int = 10) -> str:
    """Текстовый прогресс-бар: [██████░░░░]."""
    filled = round(width * done / total) if total else 0
    return "[" + "█" * filled + "░" * (width - filled) + "]"


# Кнопка ручного обновления статус-бара (callback edit'ит то же сообщение).
_STATUS_BTN = [("🔄 Обновить статус", "status")]
_STEP_ICON = {"pending": "⬜", "running": "⏳", "done": "✅", "fail": "⚠️"}


def render_progress(conn) -> str:
    """Статус-бар текущего сбора цен (для /status и кнопки под /refresh)."""
    p = store.progress_read(conn)
    if not p:
        return ("Сбор цен ещё не запускался в этой сессии.\n"
                "Он идёт по расписанию каждые ~3 часа; запустить вручную — /refresh (админ).")
    steps = p["steps"]
    total = len(steps)
    done = sum(1 for s in steps if s["status"] in ("done", "fail"))
    running = not p["finished_at"]
    if running:
        head = f"🔄 Обновление цен идёт (запущено {fmt_ago(p['started_at'])})"
    else:
        head = f"✅ Обновление завершено {fmt_ago(p['finished_at'])}"
    lines = [head, f"{_bar(done, total)} {done}/{total} источников", ""]
    for s in steps:
        label = SHOP_LABEL.get(s["shop"], s["shop"])
        if s["status"] == "done":
            tail = f" — {fmt_int(s['n'])} тов." if s["n"] is not None else " — готово"
        elif s["status"] == "fail":
            tail = " — не собрался"
        elif s["status"] == "running":
            tail = " — собираю…"
        else:
            tail = ""
        lines.append(f"{_STEP_ICON.get(s['status'], '⬜')} {label}{tail}")
    if not running:
        lines.append("\nЦены обновлены — просто спроси товар.")
    return "\n".join(lines)


def trigger_heavy_refresh() -> bool:
    """Запустить тяжёлый сбор отдельным процессом — бот не виснет. False = уже идёт.

    Guard от параллельных прогонов (двойной тап /refresh или наложение на cron):
    два collector'а interleaved-заменяют магазины и рвут привязки dipark_id.
    Вывод — в общий collector.log (DEVNULL делал ручные прогоны неотлаживаемыми).
    """
    if subprocess.run(["pgrep", "-f", "mvp7_price_scout.collector"],
                      capture_output=True).returncode == 0:
        return False
    log = open(Path(ROOT) / "mvp7_price_scout" / "collector.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "mvp7_price_scout.collector", "--heavy"],
        cwd=ROOT, stdout=log, stderr=log,
    )
    return True


def _product_reply(conn, base_row: dict) -> Reply:
    """Карточка товара + кнопки других цветов семьи (per-color выбор в один тап)."""
    return Reply(render_comparison(conn, base_row), _variant_buttons(conn, base_row))


def _query_has_storage(conn, query: str) -> bool:
    """Указан ли в запросе объём («256»/«1tb») ПЛЮС модель — семья однозначна.

    Голый объём («256») без модель-токена карточку не открывает: под 256gb
    подходят десятки семей, «уверенный» ответ был бы случайным товаром.
    """
    qk = model_key(query)
    if not qk:
        return False
    cands = store.search_base(conn, qk)
    if not cands:
        return False
    vocab = set().union(*(set(r["model_key"].split()) for r in cands))
    toks = _qtokens(qk, vocab)
    return (any(t.endswith(("gb", "tb")) for t in toks)
            and any(not t.endswith(("gb", "tb")) for t in toks))


def handle_text(conn, text: str, is_admin: bool) -> Reply:
    """Роутер: команда или запрос товара -> Reply (текст + опц. кнопки).

    Запрос товара: если одна семья доминирует (выше по покрытию токенов) —
    сразу карточка нужного цвета + кнопки других цветов. Если несколько семей
    равнозначны (свободный/короткий запрос) — список подсказок-кнопок, чтобы не
    гадать за пользователя (он пишет названия по-разному).
    """
    text = (text or "").strip()
    low = text.lower()

    if low in ("/start", "/help", "start", "help", "помощь"):
        return Reply(HELP)
    if re.match(r"/top(@|\s|$)", low):       # не ловить «/topsecret»
        return Reply(render_top(conn))
    if re.match(r"/stats(@|\s|$)", low):
        return Reply(render_stats(conn))
    if re.match(r"/status(@|\s|$)", low):
        return Reply(render_progress(conn), _STATUS_BTN)
    if re.match(r"/refresh(@|\s|$)", low):
        if not is_admin:
            return Reply("Команда /refresh доступна только администратору.")
        if not trigger_heavy_refresh():
            return Reply(render_progress(conn), _STATUS_BTN)      # уже идёт — покажи прогресс
        return Reply("🔄 Запустил обновление цен конкурентов.\n"
                     "Жми кнопку — покажу прогресс по источникам.", _STATUS_BTN)
    if text.startswith("/"):
        return Reply("Неизвестная команда. /help — список.")

    if len(low) < 2:
        return Reply("Напиши название товара, например: <code>iphone 17 256</code>")

    sugg = search_suggestions(conn, text)
    if not sugg:
        return Reply(f"Не нашёл «{_esc(text)}» в каталоге Di-Park.\n"
                     "Попробуй короче: модель + объём, напр. <code>iphone 16 pro 256</code>.")
    # объём указан (или семья одна) -> сразу карточка нужного цвета; иначе список подсказок
    # (объём — ось, которую чаще всего недописывают: «17 pro» -> выбор 128/256/512)
    if len(sugg) == 1 or _query_has_storage(conn, text):
        product = find_product(conn, text) or store.base_by_id(conn, sugg[0]["id"])
        if product:
            return _product_reply(conn, product)
    buttons = [(s["label"], f"p:{s['id']}") for s in sugg]
    return Reply(f"Уточни, что именно (нашёл {len(sugg)} под «{_esc(text)}»):", buttons)


def handle_callback(conn, data: str) -> Reply | None:
    """Тап по inline-кнопке «p:{id}» -> карточка выбранного товара (+ цвета семьи).

    id меняются при каждом пересборе каталога (replace_shop = DELETE+INSERT), так
    что кнопки в старых сообщениях протухают. На неизвестный id — не молчим, а
    просим переспросить (иначе мёртвый тап без реакции).
    """
    if data == "status":                     # кнопка «Обновить статус» под /refresh
        return Reply(render_progress(conn), _STATUS_BTN)
    if not data or not data.startswith("p:"):
        return None
    try:
        pid = int(data[2:])
    except ValueError:
        return None
    row = store.base_by_id(conn, pid)
    if not row:
        return Reply("Этот список устарел — цены с тех пор обновились. "
                     "Напиши товар ещё раз, пришлю свежие цены.")
    return _product_reply(conn, row)
