"""
Проактивные алерты для владельца: что изменилось у конкурентов с прошлого сбора.

Два события (самые ценные для торговли):
  🔻 конкурент дешевле нас по товару (впервые подрезал ИЛИ новый и сразу дешевле);
  📉 конкурент заметно снизил цену (>= DROP_PCT) на товар, что есть у нас.

Считаем через store.competitors_for (семья + SIM-guard) — та же выборка, что
карточка бота, иначе eSIM-конкурент давал ложный «подрезал» по чужому SKU.
Агрегируем ПО ТОВАРУ (не по паре товар×магазин): один блок на товар, магазины
списком — иначе один популярный товар с 5 конкурентами выжирал MAX_ALERTS.

На первом прогоне (нет истории) молчим — алертим только изменения.
"""
from __future__ import annotations

from mvp7_price_scout import handlers, store
from mvp7_price_scout.normalize import sim_type_of

DROP_PCT = 0.03      # порог «заметного» снижения цены конкурента
MIN_ABS = 300        # минимум в рублях, чтобы не шуметь на копейках
MAX_ALERTS = 20


def compute_alerts(conn, run_ts: str) -> list[str]:
    """Сравнить текущий срез с предыдущим прогоном -> список текстов алертов."""
    prev_raw = store.previous_run_prices(conn, run_ts)
    if not prev_raw:                  # первый прогон / нет истории — не шумим
        return []

    # previous_run_prices отдаёт цены по КОНКРЕТНОЙ base-строке (цвету), а
    # competitors_for агрегирует всю семью цветов -> переагрегируем prev по семье
    # (ключ модель+объём+SIM), иначе новый цвет или ротация id ломали бы сравнение.
    families = store._base_families(conn)
    fam_of: dict[int, tuple] = {}
    for rows in families:
        key = (rows[0]["model_key"], rows[0]["storage"], sim_type_of(rows[0]["title"]))
        for r in rows:
            fam_of[r["id"]] = key
    prev: dict[tuple, int] = {}
    for (pid, shop), price in prev_raw.items():
        key = fam_of.get(pid)
        if key is None:
            continue
        k = (key, shop)
        if k not in prev or price < prev[k]:      # мин. цена магазина по семье
            prev[k] = price

    scored: list[tuple[int, str]] = []
    for rows in families:
        priced_base = [r for r in rows if r["price"] is not None]
        rep = min(priced_base, key=lambda r: r["price"]) if priced_base else rows[0]
        our = rep["price"]
        fam_key = (rep["model_key"], rep["storage"], sim_type_of(rep["title"]))
        title = handlers._esc(handlers._short_title(rep["title"]))

        # лучшая (мин) ВАЛИДНАЯ цена каждого магазина по семье (SIM-guard sim_ok)
        best: dict[str, tuple[int, str]] = {}
        for c in store.competitors_for(conn, rep):
            if c["price"] is None or not c.get("sim_ok", True):
                continue
            if c["shop"] not in best or c["price"] < best[c["shop"]][0]:
                best[c["shop"]] = (c["price"], c["source_type"])

        undercut: list[tuple[str, int, str]] = []    # (shop, price, source_type) — дешевле нас
        drops: list[tuple[str, int, int, str]] = []  # (shop, p0, cp, source_type) — снизил цену
        for shop, (cp, st) in best.items():
            p0 = prev.get((fam_key, shop))
            # ВПЕРВЫЕ/сразу дешевле нас: был >= нашей цены ЛИБО новый магазин по этому
            # товару (p0 None, но история в целом есть) и сразу подрезал. Смена
            # url/каталога больше не даёт лавину: prev агрегирован по семье, не по id.
            if (our is not None and cp < our and (our - cp) >= MIN_ABS
                    and (p0 is None or p0 >= our)):
                undercut.append((shop, cp, st))
            # заметно снизил цену — но НЕ дублируем, если он уже в «дешевле нас»
            # (подрез важнее снижения: elif как в исходной логике)
            elif p0 is not None and cp <= p0 * (1 - DROP_PCT) and (p0 - cp) >= MIN_ABS:
                drops.append((shop, p0, cp, st))

        if undercut:
            undercut.sort(key=lambda x: x[1])
            shops_txt = ", ".join(f"{handlers._label(s, st)} {handlers.fmt_int(p)} ₽"
                                  for s, p, st in undercut)
            our_txt = f" (у нас {handlers.fmt_int(our)} ₽)" if our is not None else ""
            head = ("теперь дешевле нас" if len(undercut) == 1
                    else f"{len(undercut)} магазина(ов) теперь дешевле нас")
            weight = max(our - p for _, p, _ in undercut)
            scored.append((weight, f"🔻 <b>{title}</b>\n{head}: {shops_txt}{our_txt}"))
        if drops:
            drops.sort(key=lambda x: x[1] - x[2], reverse=True)
            shops_txt = "\n".join(
                f"{handlers._label(s, st)}: {handlers.fmt_int(p0)} → {handlers.fmt_int(cp)} ₽ "
                f"(−{handlers.fmt_int(p0 - cp)})"
                for s, p0, cp, st in drops)
            weight = max(p0 - cp for _, p0, cp, _ in drops)
            scored.append((weight, f"📉 <b>{title}</b>\n{shops_txt}"))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = [m for _, m in scored[:MAX_ALERTS]]
    if len(scored) > MAX_ALERTS:                  # не терять хвост молча
        out.append(f"➕ ещё {len(scored) - MAX_ALERTS} изменений (показаны крупнейшие).")
    return out
