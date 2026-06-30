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
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from mvp7_price_scout import store
from mvp7_price_scout.normalize import model_key

ROOT = str(Path(__file__).resolve().parents[1])   # корень репо (freelance-mvp)

SHOP_LABEL = {
    "sr57": "sr57.ru", "repremium": "repremium", "iprice": "iprice",
    "ispace": "ispace", "kingstore": "KingStore", "di-park": "Di-Park",
}
HELP = (
    "Я сравниваю цены Di-Park с конкурентами Орла.\n\n"
    "• Напиши товар — пришлю таблицу цен.\n"
    "  Примеры: <code>iphone 17 pro max 256</code>, <code>galaxy s24 256</code>, "
    "<code>airpods pro 2</code>\n"
    "• /top — где мы дороже всех (теряем продажи)\n"
    "• /stats — наша позиция на рынке одним взглядом\n"
    "• /export — выгрузить всё сравнение в Excel/CSV\n"
    "• /refresh — обновить цены конкурентов (только админ)"
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
    """Убрать шум для показа: (Sim+E-Sim), лишние пробелы, префикс Apple."""
    t = re.sub(r"\([^)]*\)", "", title or "")
    t = re.sub(r"^\s*Apple\s+", "", t, flags=re.I)     # «Apple iPhone» -> «iPhone»
    return re.sub(r"\s+", " ", t).strip()


def find_product(conn, query: str, min_score: int = 55) -> dict | None:
    """Найти лучший товар эталона под запрос (покрытие токенов запроса, затем fuzzy).

    Ранжируем по доле токенов запроса, найденных в товаре, потом по
    token_sort_ratio — иначе короткий «galaxy s24» цепляет чехол «Pitaka S24».
    """
    qk = model_key(query)
    if not qk:
        return None
    cands = store.search_base(conn, qk)
    if not cands:
        return None
    qtok = set(qk.split())

    def coverage(r: dict) -> float:
        return len(qtok & set(r["model_key"].split())) / len(qtok) if qtok else 0.0

    best = max(cands, key=lambda r: (coverage(r), fuzz.token_sort_ratio(qk, r["model_key"])))
    if coverage(best) < 0.5 or fuzz.token_sort_ratio(qk, best["model_key"]) < min_score:
        return None
    return best


def render_comparison(conn, base_row: dict) -> str:
    """Понятная карточка владельцу: вердикт + кто дешевле/дороже тебя + что сделать."""
    our = base_row["price"]
    comps = store.competitors_for(conn, base_row["id"])
    lines = [f"📱 {_esc(_short_title(base_row['title']))}"]
    lines.append(f"💰 Твоя цена: {fmt_int(our)} ₽" if our else "💰 Твоя цена: под заказ")

    priced = sorted([c for c in comps if c["price"] is not None], key=lambda c: c["price"])
    missing = [c for c in comps if c["price"] is None]

    if not priced:
        lines.append("\nКонкурентов с этим товаром не нашёл.")
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
            lines.append(f"\n🎯 Поставь {fmt_int(priced[0]['price'] - 100)} ₽ → станешь дешевле всех")
    else:
        lines.append("\nЦены конкурентов:")
        lines += [row(c, "") for c in priced]

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
    return (
        "📊 Твоя позиция на рынке\n"
        f"Сравнил {t} твоих товаров с конкурентами:\n\n"
        f"🟢 Ты дешевле всех:  {mp['cheaper']} ({pct(mp['cheaper'])})\n"
        f"🔴 Ты дороже всех:   {mp['pricier']} ({pct(mp['pricier'])})  ← тут теряешь\n"
        f"⚪ Наравне:           {mp['equal']}\n\n"
        f"Где дороже — в среднем на {mp['avg_loss_pct']}% выше конкурента.\n"
        "Список где теряешь → /top"
    )


def _comparison_rows(conn) -> tuple[list[str], list[dict]]:
    """Собрать данные сравнения: (список магазинов, строки с вычисленными полями)."""
    shops = [r["shop"] for r in conn.execute(
        "SELECT DISTINCT shop FROM products WHERE source_type!='base' ORDER BY shop")]
    cur = conn.execute(
        """
        SELECT b.id AS pid, b.title AS title, b.price AS our, c.shop AS shop, c.price AS cp
        FROM products b
        JOIN products c ON c.dipark_id = b.id AND c.source_type != 'base'
        WHERE b.source_type = 'base'
        """
    )
    prods: dict[int, dict] = {}
    for r in cur.fetchall():
        d = prods.setdefault(r["pid"], {"title": r["title"], "our": r["our"], "shops": {}})
        d["shops"][r["shop"]] = r["cp"]

    items: list[dict] = []
    for d in prods.values():
        prices = {s: d["shops"].get(s) for s in shops}
        pv = {s: p for s, p in prices.items() if p is not None}
        mn = min(pv.values()) if pv else None
        mn_shop = SHOP_LABEL.get(min(pv, key=pv.get), min(pv, key=pv.get)) if pv else ""
        our = d["our"]
        if our is None:
            status, gap = "под заказ", None
        elif mn is None:
            status, gap = "нет данных", None
        elif our > mn:
            status, gap = "🔴 дороже всех", our - mn
        elif our < mn:
            status, gap = "🟢 дешевле всех", our - mn
        else:
            status, gap = "⚪ наравне", 0
        items.append({"title": _short_title(d["title"]), "our": our, "prices": prices,
                      "mn": mn, "mn_shop": mn_shop, "gap": gap, "status": status})
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
    money = '# ##0" ₽";;0'
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


def trigger_heavy_refresh() -> None:
    """Запустить тяжёлый сбор (Яндекс/Instagram) отдельным процессом — бот не виснет."""
    subprocess.Popen(
        [sys.executable, "-m", "mvp7_price_scout.collector", "--heavy"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def handle_text(conn, text: str, is_admin: bool) -> str:
    """Роутер: команда или запрос товара -> текст ответа (HTML parse_mode)."""
    text = (text or "").strip()
    low = text.lower()

    if low in ("/start", "/help", "start", "help", "помощь"):
        return HELP
    if low.startswith("/top"):
        return render_top(conn)
    if low.startswith("/stats"):
        return render_stats(conn)
    if low.startswith("/refresh"):
        if not is_admin:
            return "Команда /refresh доступна только администратору."
        trigger_heavy_refresh()
        return "🔄 Запустил обновление цен конкурентов. Минуту-другую — потом просто спроси товар."
    if text.startswith("/"):
        return "Неизвестная команда. /help — список."

    if len(low) < 2:
        return "Напиши название товара, например: <code>iphone 17 256</code>"
    product = find_product(conn, text)
    if not product:
        return (f"Не нашёл «{_esc(text)}» в каталоге Di-Park.\n"
                "Попробуй точнее: модель + объём, напр. <code>iphone 16 pro 256</code>.")
    return render_comparison(conn, product)
