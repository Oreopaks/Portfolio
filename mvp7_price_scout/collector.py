"""
COLLECTOR — агрегатор сбора цен (аналог mvp4_scout/scout.run_cycle).

Поток: di-park (эталон) -> collapse цвет-вариантов -> SQLite (база).
Затем каждый конкурент: fetch -> collapse -> match к каталогу эталона ->
сохраняем ТОЛЬКО сматченные строки (несматченные не нужны боту).

Снимочная семантика store.replace_shop: каждый прогон затирает данные магазина.
Падение одного источника не валит остальные (try/except на источник).

CLI:
    python -m mvp7_price_scout.collector            # статичные сайты (быстро)
    python -m mvp7_price_scout.collector --heavy    # + Яндекс/Instagram (медленно)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень репо (freelance-mvp)
import shared.config  # noqa: F401  — подхватывает .env

from mvp7_price_scout import alerts, notify, store
from mvp7_price_scout.match import match_all
from mvp7_price_scout.normalize import Product, collapse_variants, is_used
from mvp7_price_scout.sources.dipark_source import fetch_dipark_catalog
from mvp7_price_scout.sources.iprice_source import fetch_iprice
from mvp7_price_scout.sources.ispace_source import fetch_ispace
from mvp7_price_scout.sources.kingstore_source import fetch_kingstore
from mvp7_price_scout.sources.repremium_source import fetch_repremium
from mvp7_price_scout.sources.sr57_source import fetch_sr57

def _fetch_instagram(*a, **kw):
    """Ленивый импорт Instagram (тянет instagrapi/torch) — только при --heavy."""
    from mvp7_price_scout.sources.instagram_source import fetch_instagram
    return fetch_instagram(*a, **kw)


# Статичные/быстрые сайты-конкуренты (cron каждые ~3ч).
STATIC_SOURCES: list[tuple[str, callable]] = [
    ("sr57", fetch_sr57),           # WooCommerce
    ("iprice", fetch_iprice),       # Webasyst
    ("ispace", fetch_ispace),       # Bitrix (страницы товаров, цены скрыты в листингах)
    ("kingstore", fetch_kingstore), # Bitrix (цены в data-атрибутах карточек листинга)
]
# Тяжёлые (Playwright/instagrapi+OCR) — только --heavy, реже / по /refresh.
# Яндекс-профили исключены: отдают услуги/витрину, не каталог телефонов (см. README).
HEAVY_SOURCES: list[tuple[str, callable]] = [
    ("repremium", fetch_repremium),          # Bitrix aspro, грид через Playwright
    ("smart_room_57", _fetch_instagram),     # Instagram, нужна сессия (IG_SETTINGS)
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stamp(products: list[Product]) -> list[Product]:
    t = _now()
    for p in products:
        p.fetched_at = t
    return products


def _new_only(products: list[Product]) -> list[Product]:
    """Отсечь Б/У/уценку — сравниваем только новые товары."""
    return [p for p in products if not is_used(p.title)]


def collect_base(conn) -> list[dict]:
    """Собрать каталог эталона di-park -> база. Вернуть base_catalog для матчинга."""
    prods = collapse_variants(_new_only(fetch_dipark_catalog()))
    for p in prods:
        p.source_type = "base"
    _stamp(prods)
    n = store.replace_shop(conn, "di-park", prods)
    store.link_base_self(conn)
    print(f"[collector] di-park (эталон): {n} товаров")
    return store.base_catalog(conn)


def collect_competitor(conn, shop: str, fetch_fn: callable, base_rows: list[dict]) -> list[Product]:
    """Собрать конкурента, сматчить к эталону, сохранить только сматченное. Вернуть сохранённое."""
    prods = collapse_variants(_new_only(fetch_fn()))
    matched = match_all(prods, base_rows)
    keep = [p for p in prods if p.dipark_id is not None]
    _stamp(keep)
    n = store.replace_shop(conn, shop, keep)
    print(f"[collector] {shop}: собрано {len(prods)}, сматчено {matched}, сохранено {n}")
    return keep


def run(heavy: bool = False, db: str | None = None) -> None:
    conn = store.connect(db)
    run_ts = _now()
    base_rows = collect_base(conn)
    all_comp: list[Product] = []
    sources = STATIC_SOURCES + (HEAVY_SOURCES if heavy else [])
    for shop, fn in sources:
        try:
            all_comp += collect_competitor(conn, shop, fn, base_rows)
        except Exception as e:  # источник может упасть — не валим весь прогон
            print(f"[collector] {shop} упал: {e}")

    # Алерты: сравнить с прошлым прогоном ДО записи текущего среза в историю.
    try:
        msgs = alerts.compute_alerts(conn, run_ts)
        store.append_price_log(conn, all_comp, run_ts)
        if msgs:
            notify.send_admins("⚠️ <b>Изменения у конкурентов</b>\n\n" + "\n\n".join(msgs))
            print(f"[collector] алертов: {len(msgs)}")
    except Exception as e:
        print(f"[collector] алерты упали: {e}")

    print("\n=== срез базы (магазин / тип / товаров / с ценой / обновлено) ===")
    for r in store.stats(conn):
        print(f"  {r['shop']:<14} {r['source_type']:<6} n={r['n']:<5} "
              f"price={r['with_price']:<5} {r['last']}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Сбор цен di-park + конкуренты")
    ap.add_argument("--heavy", action="store_true", help="включить Яндекс/Instagram")
    ap.add_argument("--db", default=os.environ.get("PRICESCOUT_DB"))
    args = ap.parse_args()
    run(heavy=args.heavy, db=args.db)
