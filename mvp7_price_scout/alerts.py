"""
Проактивные алерты для владельца: что изменилось у конкурентов с прошлого сбора.

Два события (самые ценные для торговли):
  🔻 конкурент ВПЕРВЫЕ стал дешевле нас по товару (подрезал);
  📉 конкурент заметно снизил цену (>= DROP_PCT) на товар, что есть у нас.

На первом прогоне (нет истории) молчим — алертим только изменения.
"""
from __future__ import annotations

from mvp7_price_scout import handlers, store

DROP_PCT = 0.03      # порог «заметного» снижения цены конкурента
MIN_ABS = 300        # минимум в рублях, чтобы не шуметь на копейках
MAX_ALERTS = 20


def compute_alerts(conn, run_ts: str) -> list[str]:
    """Сравнить текущий срез с предыдущим прогоном -> список текстов алертов."""
    prev = store.previous_run_prices(conn, run_ts)
    if not prev:                      # первый прогон / нет истории — не шумим
        return []

    cur = conn.execute(
        """
        SELECT b.id AS pid, b.title AS title, b.price AS our,
               c.shop AS shop, MIN(c.price) AS cp, c.source_type AS st
        FROM products b
        JOIN products c ON c.dipark_id = b.id AND c.source_type != 'base'
                       AND c.in_stock = 1
        WHERE b.source_type = 'base' AND c.price IS NOT NULL
        GROUP BY b.id, c.shop
        """
    ).fetchall()   # GROUP BY (pid, shop): одна строка на пару, без дублей алертов
    # (при MIN(price) SQLite берёт c.source_type из строки-минимума)

    scored: list[tuple[int, str]] = []
    for r in cur:
        pid, title, our, shop, cp, st = (
            r["pid"], r["title"], r["our"], r["shop"], r["cp"], r["st"])
        title = handlers._esc(title)         # scraped title -> безопасно в HTML
        p0 = prev.get((pid, shop))
        label = handlers._label(shop, st)
        # конкурент ВПЕРВЫЕ подрезал: был >= нашей цены, стал ниже.
        # p0 is None (нет истории пары) НЕ считаем «впервые дешевле» — иначе смена
        # url/каталога конкурента (все пары новые) даёт лавину ложных алертов.
        if our is not None and cp < our and p0 is not None and p0 >= our and (our - cp) >= MIN_ABS:
            scored.append((
                our - cp,
                f"🔻 <b>{title}</b>\n{label} {handlers.fmt_int(cp)} ₽ — теперь дешевле нас "
                f"на {handlers.fmt_int(our - cp)} ₽ (у нас {handlers.fmt_int(our)} ₽)",
            ))
        # конкурент заметно снизил цену
        elif p0 is not None and cp <= p0 * (1 - DROP_PCT) and (p0 - cp) >= MIN_ABS:
            scored.append((
                p0 - cp,
                f"📉 <b>{title}</b>\n{label}: {handlers.fmt_int(p0)} → {handlers.fmt_int(cp)} ₽ "
                f"(−{handlers.fmt_int(p0 - cp)})",
            ))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:MAX_ALERTS]]
