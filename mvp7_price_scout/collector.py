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
from mvp7_price_scout.normalize import Product, collapse_variants, is_special_edition, is_used
from mvp7_price_scout.sources.dipark_source import fetch_dipark_catalog
from mvp7_price_scout.sources.iprice_source import fetch_iprice
from mvp7_price_scout.sources.ispace_source import fetch_ispace
from mvp7_price_scout.sources.kingstore_source import fetch_kingstore
from mvp7_price_scout.sources.mobilax_source import fetch_mobilax
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
    ("mobilax", fetch_mobilax),     # Webasyst (зеркало мобилакс.рф, mobileax.ru за Cloudflare)
]
# Тяжёлые (Playwright/instagrapi+OCR) — только --heavy, реже / по /refresh.
# Яндекс-профили исключены: отдают услуги/витрину, не каталог телефонов (см. README).
HEAVY_SOURCES: list[tuple[str, callable]] = [
    ("repremium", fetch_repremium),          # Bitrix aspro, грид через Playwright
    ("smart_room_57", _fetch_instagram),     # Instagram, нужна сессия (IG_SETTINGS)
]


# Пороги health-проверки «источник протух»: cron ходит каждые RUN_EVERY_HOURS,
# алертим при возрасте цен > STALE_HOURS (двух пропущенных прогонов достаточно).
RUN_EVERY_HOURS = 3
STALE_HOURS = 8

# Тихие часы: ценовые алерты ночью не шлём (владельца не будим). Health (источник
# отвалился) шлём всегда — это уже поломка. ponytail: ночное изменение цены при
# следующем дневном прогоне может не всплыть (сравнение идёт с ночным срезом) —
# приемлемый потолок для MVP; апгрейд — буфер отложенной доставки до утра.
QUIET_START, QUIET_END = 23, 8

# Флаг-дедуп «сбор di-park подозрительно мал»: пока сайт лежит, не долбить одним
# и тем же алертом каждые 3 часа. Сбрасывается при первом же удачном сборе.
_DIPARK_LOW_MARKER = Path(__file__).resolve().parent / ".dipark_low"


def _quiet_now() -> bool:
    h = datetime.now().hour
    return h >= QUIET_START or h < QUIET_END


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stamp(products: list[Product]) -> list[Product]:
    t = _now()
    for p in products:
        p.fetched_at = t
    return products


def _new_only(products: list[Product]) -> list[Product]:
    """Отсечь Б/У/уценку и спец/эксклюзив-издания — сравниваем сопоставимое.

    Спец-издания (Iron Man Edition, эксклюзив-цвета) стоят сильно дороже, а
    model_key их не различает -> кросс-матч со стандартом даёт ложные сигналы.
    """
    return [p for p in products
            if not is_used(p.title) and not is_special_edition(p.title)]


def collect_base(conn) -> list[dict]:
    """Собрать каталог эталона di-park -> база. Вернуть base_catalog для матчинга.

    Guard: подозрительно малый сбор (сайт лёг, sitemap недоступен) НЕ затирает
    каталог — иначе один сбой di-park опустошает базу и отвязывает всех
    конкурентов до следующего удачного прогона, а бот отвечает «не нашёл» на всё.

    upsert_base (не replace_shop!): id эталона стабильны между прогонами — на
    них ссылаются price_log (алерты), dipark_id конкурентов и callback-кнопки.
    """
    prods = collapse_variants(_new_only(fetch_dipark_catalog()))
    old_n = conn.execute(
        "SELECT COUNT(*) FROM products WHERE source_type = 'base'").fetchone()[0]
    if old_n >= 50 and len(prods) < old_n * 0.5:
        if not _DIPARK_LOW_MARKER.exists():         # дедуп: один алерт на затяжную поломку
            notify.send_admins(
                f"🚨 <b>Сбор di-park подозрительно мал</b>: {len(prods)} товаров "
                f"(было {old_n}). Каталог не тронут, прогон отменён — см. collector.log.")
            _DIPARK_LOW_MARKER.touch()
        exc = RuntimeError(f"di-park вернул {len(prods)} < 50% от {old_n} — эталон не обновляю")
        exc.notified = True                         # run() не шлёт второй алерт про этот отказ
        raise exc
    _DIPARK_LOW_MARKER.unlink(missing_ok=True)      # сбор восстановился — сброс дедупа
    for p in prods:
        p.source_type = "base"
    _stamp(prods)
    n = store.upsert_base(conn, prods)
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
    sources = STATIC_SOURCES + (HEAVY_SOURCES if heavy else [])
    # трек прогресса для статус-бара бота (/status): di-park + все источники прогона
    store.progress_start(conn, ["di-park"] + [s for s, _ in sources], run_ts, heavy)
    try:
        store.progress_mark(conn, "di-park", "running")
        base_rows = collect_base(conn)
        store.progress_mark(conn, "di-park", "done", len(base_rows))
    except Exception as e:      # эталон не собрался — работаем на старых данных
        store.progress_mark(conn, "di-park", "fail")
        store.progress_finish(conn, _now())
        if not getattr(e, "notified", False):   # полный отказ (сайт лёг) — не немо в лог
            notify.send_admins(f"🚨 <b>di-park (эталон) не собрался</b>: {e}\n"
                               "Работаю на старых ценах — конкуренты не пересчитаны.")
        print(f"[collector] эталон di-park упал, прогон отменён: {e}")
        conn.close()
        return
    all_comp: list[Product] = []
    for shop, fn in sources:
        store.progress_mark(conn, shop, "running")
        try:
            kept = collect_competitor(conn, shop, fn, base_rows)
            all_comp += kept
            store.progress_mark(conn, shop, "done", len(kept))
        except Exception as e:  # источник может упасть — не валим весь прогон
            store.progress_mark(conn, shop, "fail")
            print(f"[collector] {shop} упал: {e}")

    # Алерты: сравнить с прошлым прогоном ДО записи текущего среза в историю.
    try:
        msgs = alerts.compute_alerts(conn, run_ts)
        store.append_price_log(conn, all_comp, run_ts)
        if msgs and not _quiet_now():
            notify.send_admins("⚠️ <b>Изменения у конкурентов</b>\n\n" + "\n\n".join(msgs))
            print(f"[collector] алертов: {len(msgs)}")
        elif msgs:
            print(f"[collector] {len(msgs)} ценовых алертов подавлены (тихие часы)")
    except Exception as e:
        print(f"[collector] алерты упали: {e}")

    # Health: упал ли источник против прошлого прогона (иначе выпадение источника
    # немо — владелец думает, что сравнил со всеми, а iprice/ispace отвалились).
    try:
        cur_counts = {r["shop"]: (r["n"], r["with_price"])
                      for r in store.stats(conn) if r["source_type"] != "base"}
        for shop, _fn in sources:
            # источник, не давший НИ строки ни разу (IG без сессии), отсутствует
            # и в stats, и в прошлых прогонах — фиксируем нулём, чтобы история
            # была честной и переход 0 -> >0 -> 0 ловился
            cur_counts.setdefault(shop, (0, 0))
        prev = store.previous_source_counts(conn, run_ts)
        # union: источник, вернувший 0, вычищается из products и пропадает из stats —
        # именно его (iprice=0) и надо поймать, поэтому идём и по прошлым магазинам.
        drops = []
        for shop in set(cur_counts) | set(prev):
            n, wp = cur_counts.get(shop, (0, 0))
            pn, pwp = prev.get(shop, (0, 0))
            if pn and (n == 0 or n < pn * 0.5):
                drops.append(f"⚠️ <b>{shop}</b>: {n} товаров (было {pn}) — источник отвалился или сломался.")
            elif pwp and n and wp == 0:
                drops.append(f"⚠️ <b>{shop}</b>: товары есть, но ни одной цены "
                             f"(было {pwp} с ценой) — вёрстка цен уехала.")
        # источник, падающий ИСКЛЮЧЕНИЕМ, оставляет в базе старые строки — счётчик
        # не меняется и верхние проверки молчат хоть неделю. Ловим по возрасту
        # последнего сбора; окно = один интервал cron, чтобы не спамить каждый прогон.
        for r in store.stats(conn):
            if r["source_type"] == "base" or not r["last"]:
                continue
            try:
                age_h = (datetime.now() - datetime.fromisoformat(r["last"])).total_seconds() / 3600
            except ValueError:
                continue
            if STALE_HOURS < age_h <= STALE_HOURS + RUN_EVERY_HOURS:
                drops.append(f"⚠️ <b>{r['shop']}</b>: цены не обновлялись {int(age_h)}ч — "
                             f"источник падает (см. collector.log).")
        if drops:
            notify.send_admins("🚨 <b>Проблема сбора цен</b>\n\n" + "\n".join(drops))
            print(f"[collector] health-алертов: {len(drops)}")
        store.record_source_counts(conn, run_ts, cur_counts)
    except Exception as e:
        print(f"[collector] health-проверка упала: {e}")

    store.progress_finish(conn, _now())     # статус-бар: сбор завершён

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
