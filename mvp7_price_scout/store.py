"""
Хранилище цен — SQLite (stdlib sqlite3, синхронно, как весь стек проекта).

Снимочная семантика: каждый прогон сбора ПОЛНОСТЬЮ заменяет строки магазина
(replace_shop) — никаких накапливающихся дублей, всегда «последний срез цен».

Таблица products:
  base-строки  (наш di-park):   source_type='base', dipark_id = свой же id
  конкуренты:                   dipark_id = id эталонного товара (или NULL, нет матча)

Сравнение товара X = все строки с dipark_id = X (включая нашу base-строку).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from mvp7_price_scout.normalize import Product, sim_type_of

DEFAULT_DB = Path(__file__).resolve().parent / "prices.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop        TEXT NOT NULL,
    title       TEXT NOT NULL,
    model_key   TEXT NOT NULL,
    storage     TEXT,
    price       INTEGER,
    in_stock    INTEGER NOT NULL DEFAULT 1,
    url         TEXT,
    source_type TEXT NOT NULL DEFAULT 'site',
    fetched_at  TEXT,
    dipark_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_products_model_key ON products(model_key);
CREATE INDEX IF NOT EXISTS idx_products_dipark_id ON products(dipark_id);
CREATE INDEX IF NOT EXISTS idx_products_shop ON products(shop);

-- История цен конкурентов (append-only) — для алертов «снизил цену / подрезал нас».
CREATE TABLE IF NOT EXISTS price_log (
    run_ts     TEXT NOT NULL,
    dipark_id  INTEGER NOT NULL,
    shop       TEXT NOT NULL,
    price      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pricelog_ts ON price_log(run_ts);
CREATE INDEX IF NOT EXISTS idx_pricelog_key ON price_log(dipark_id, shop);

-- Счётчики товаров по источнику за прогон — для health-алерта «источник отвалился».
CREATE TABLE IF NOT EXISTS run_counts (
    run_ts     TEXT NOT NULL,
    shop       TEXT NOT NULL,
    n          INTEGER NOT NULL,
    with_price INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runcounts_ts ON run_counts(run_ts);

-- Прогресс ТЕКУЩЕГО сбора (одна строка) — collector пишет по шагам, бот читает
-- (WAL: чтение боту не блокируется) и рисует статус-бар в /status. steps = JSON
-- [{shop, status: pending|running|done|fail, n}].
CREATE TABLE IF NOT EXISTS run_progress (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    started_at  TEXT,
    finished_at TEXT,
    heavy       INTEGER NOT NULL DEFAULT 0,
    steps       TEXT NOT NULL DEFAULT '[]'
);
"""


def connect(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Открыть БД (env PRICESCOUT_DB > аргумент > дефолт) и накатить схему.

    Относительный путь (PRICESCOUT_DB=mvp7_price_scout/prices.db) резолвим от
    корня репо, не от cwd — иначе запуск не из корня молча создаёт вторую
    пустую базу, и бот отвечает «каталог пуст».
    """
    path = Path(db_path or os.environ.get("PRICESCOUT_DB") or DEFAULT_DB)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # чтение боту не блокируется записью collector
    conn.executescript(_SCHEMA)
    return conn


def replace_shop(conn: sqlite3.Connection, shop: str, products: list[Product]) -> int:
    """Заменить ВСЕ строки магазина свежим срезом. Возвращает число вставленных."""
    rows = [
        (p.shop, p.title, p.model_key, p.storage,
         p.price, int(p.in_stock), p.url, p.source_type, p.fetched_at, p.dipark_id)
        for p in products
    ]
    with conn:  # транзакция: либо весь срез заменился, либо ничего
        conn.execute("DELETE FROM products WHERE shop = ?", (shop,))
        conn.executemany(
            "INSERT INTO products "
            "(shop, title, model_key, storage, price, in_stock, url, source_type, fetched_at, dipark_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def link_base_self(conn: sqlite3.Connection) -> None:
    """base-строкам проставить dipark_id = собственный id (для единых выборок)."""
    with conn:
        conn.execute("UPDATE products SET dipark_id = id WHERE source_type = 'base'")


def upsert_base(conn: sqlite3.Connection, products: list[Product]) -> int:
    """Обновить каталог эталона БЕЗ ротации id: UPDATE по (url, title), INSERT
    новых, DELETE исчезнувших. Вернуть число строк каталога.

    replace_shop (DELETE+INSERT) для эталона не годится: id ротируются каждый
    прогон, а на них ссылаются price_log (без стабильных id алерты «конкурент
    снизил цену» никогда не срабатывают — прошлый прогон весь по мёртвым id),
    dipark_id конкурентов (окно отвязки между пересборками магазинов) и
    callback-кнопки «p:{id}» в уже отправленных сообщениях.
    """
    with conn:
        old: dict[tuple, list[int]] = {}
        for r in conn.execute(
                "SELECT id, url, title FROM products WHERE source_type = 'base'"):
            old.setdefault((r["url"], r["title"]), []).append(r["id"])
        seen: set[int] = set()
        for p in products:
            pid = next((i for i in old.get((p.url, p.title), []) if i not in seen), None)
            if pid is not None:
                seen.add(pid)
                conn.execute(
                    "UPDATE products SET model_key=?, storage=?, price=?, in_stock=?, "
                    "fetched_at=? WHERE id=?",
                    (p.model_key, p.storage, p.price, int(p.in_stock), p.fetched_at, pid))
            else:
                conn.execute(
                    "INSERT INTO products (shop, title, model_key, storage, price, "
                    "in_stock, url, source_type, fetched_at, dipark_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                    (p.shop, p.title, p.model_key, p.storage, p.price,
                     int(p.in_stock), p.url, p.source_type, p.fetched_at))
        gone = [i for ids in old.values() for i in ids if i not in seen]
        if gone:
            conn.executemany("DELETE FROM products WHERE id = ?", [(i,) for i in gone])
        conn.execute("UPDATE products SET dipark_id = id WHERE source_type = 'base'")
    return len(products)


def base_catalog(conn: sqlite3.Connection) -> list[dict]:
    """Каталог эталона (наш di-park) — id+ключ+объём+цена для матчинга/поиска."""
    cur = conn.execute(
        "SELECT id, title, model_key, storage, price, url "
        "FROM products WHERE source_type = 'base'"
    )
    return [dict(r) for r in cur.fetchall()]


def tracked_shop_count(conn: sqlite3.Connection) -> int:
    """Сколько магазинов-конкурентов сейчас в базе — для карточки «сравнил с N из M»."""
    return conn.execute(
        "SELECT COUNT(DISTINCT shop) FROM products WHERE source_type != 'base'"
    ).fetchone()[0]


def search_base(conn: sqlite3.Connection, query_key: str, limit: int = 40) -> list[dict]:
    """Кандидаты из каталога эталона по словам ключа (LIKE) — добивает fuzzy в caller.

    Возвращает строки base, у которых model_key/title содержит хотя бы одно
    значимое слово запроса. Узкий префильтр перед дорогим rapidfuzz.
    """
    # ponytail: кап 24 значимых слова — очень длинный запрос иначе строит LIKE на
    # сотни термов, и SQLite падает «Expression tree too large (max depth 1000)».
    words = [w for w in query_key.split() if len(w) >= 2][:24]
    if not words:
        cur = conn.execute(
            "SELECT id, title, model_key, storage, price, url, fetched_at "
            "FROM products WHERE source_type='base' "
            "ORDER BY (price IS NULL), price LIMIT ?", (limit * 4,)
        )
        return [dict(r) for r in cur.fetchall()]
    # Сортировка: сначала по числу совпавших слов (иначе LIMIT забивается
    # тысячами дешёвых аксессуаров с одним общим словом «pro», и сам телефон
    # не попадает в кандидаты), затем приценённые строки (представитель семьи
    # в подсказках должен иметь цену).
    hit_expr = " + ".join(["(model_key LIKE ? OR title LIKE ?)"] * len(words))
    clause = " OR ".join(["model_key LIKE ? OR title LIKE ?"] * len(words))
    params: list[str] = []
    for w in words:
        params += [f"%{w}%", f"%{w}%"]
    # tie-break по числу токенов model_key ASC (короче = ядро товара: «13 iphone
    # 128gb», а не «стекло iphone 15 16 remax»). Без него одно-словный бренд-запрос
    # («iphone»/«samsung») забивал пул сотнями дешёвых аксессуаров (одинаковый hits,
    # price ASC), а реальные телефоны отсекались до fuzzy -> в подсказках 0 телефонов.
    cur = conn.execute(
        f"SELECT id, title, model_key, storage, price, url, fetched_at, "
        f"({hit_expr}) AS hits "
        f"FROM products WHERE source_type='base' AND ({clause}) "
        f"ORDER BY hits DESC, "
        f"(LENGTH(model_key) - LENGTH(REPLACE(model_key, ' ', ''))), "
        f"(price IS NULL), price LIMIT ?",
        (*params, *params, limit * 4),
    )
    return [dict(r) for r in cur.fetchall()]


def competitors_for(conn: sqlite3.Connection, base_row: dict) -> list[dict]:
    """Конкуренты товара — по СЕМЬЕ цветов (модель+объём+совместимый SIM).

    Наш каталог хранится per-color (цена по цвету различается), а у конкурентов
    цвета названы вразнобой (Midnight/Black/Чёрный) — построчно по цвету не
    сматчить. Поэтому: берём все цветовые строки эталона этой семьи (тот же
    model_key+storage, совместимый SIM) и собираем конкурентов, привязанных
    матчером (dipark_id) к ЛЮБОЙ из них. Так для любого запрошенного цвета видны
    все конкуренты семьи, и сохраняется фаззи-привязка матчера (аксессуары и т.п.).
    """
    fam = conn.execute(
        "SELECT id FROM products "
        "WHERE source_type = 'base' AND model_key = ? AND storage IS ?",
        (base_row["model_key"], base_row["storage"]),
    ).fetchall()
    ids = [r["id"] for r in fam] or [base_row["id"]]     # все цвета+SIM семьи
    placeholders = ",".join("?" * len(ids))
    cur = conn.execute(
        f"SELECT shop, title, price, url, in_stock, source_type, fetched_at "
        f"FROM products WHERE source_type != 'base' AND dipark_id IN ({placeholders}) "
        f"AND in_stock = 1 "        # «нет в наличии» — не конкурент: купить нельзя
        f"ORDER BY (price IS NULL), price",
        ids,
    )
    # Строгий SIM-guard по SIM самого КОНКУРЕНТА (а не по строке, к которой он
    # случайно привязался матчером). Каждой строке ставим флаг sim_ok — учитывать
    # ли её в расчёте «дешевле всех» (см. handlers/market_position/biggest_gaps):
    #   • base без типа SIM (Samsung/аксессуары) — все конкуренты валидны;
    #   • явный ДРУГОЙ тип SIM — не конкурент, отбраковываем (eSIM не лезет на
    #     Sim+eSIM-карточку и наоборот, «2 nano-SIM» не путаем с «Sim+eSIM»);
    #   • магазин, ЯВНО метящий нужный тип, свои НЕпомеченные строки метит другим
    #     (repremium метит eSIM, physical — без пометки) — их выкидываем;
    #   • немаркированный конкурент дешевле «зазора» между нашими eSIM и physical
    #     ценами почти наверняка продаёт eSIM-версию: показываем, но sim_ok=False
    #     (не занижаем рекомендацию по Sim+eSIM ценой eSIM-SKU — корень бага).
    bsim = sim_type_of(base_row["title"])
    rows = [(dict(r), sim_type_of(r["title"])) for r in cur.fetchall()]
    if bsim is None:
        for r, _ in rows:
            r["sim_ok"] = True
        return [r for r, _ in rows]
    compat = [(r, csim) for r, csim in rows if csim is None or csim == bsim]
    marked_shops = {r["shop"] for r, csim in compat if csim == bsim}
    kept = [(r, csim) for r, csim in compat if csim == bsim or r["shop"] not in marked_shops]
    leak = (family_sim_leak_threshold(conn, base_row)
            if bsim in ("sim_esim", "dual_sim") else None)
    out: list[dict] = []
    for r, csim in kept:
        r["sim_ok"] = not (csim is None and leak is not None
                           and r["price"] is not None and r["price"] < leak)
        out.append(r)
    return out


def family_colors(conn: sqlite3.Connection, base_row: dict) -> list[dict]:
    """Цветовые варианты эталона той же семьи (модель+объём, тот же тип SIM).

    Каталог per-color: у каждого цвета своя цена. Для кнопок «другие цвета» на
    карточке. SIM берём строго тот же (eSIM и Sim+E-Sim — разные семьи по цене).
    """
    cur = conn.execute(
        "SELECT id, title, price FROM products "
        "WHERE source_type = 'base' AND model_key = ? AND storage IS ? "
        "ORDER BY (price IS NULL), price",
        (base_row["model_key"], base_row["storage"]),
    )
    bsim = sim_type_of(base_row["title"])
    return [dict(r) for r in cur.fetchall() if sim_type_of(r["title"]) == bsim]


def family_sim_leak_threshold(conn: sqlite3.Connection, base_row: dict) -> int | None:
    """Ценовой порог «немаркированный конкурент — это eSIM-версия» для physical-карточки.

    Немаркированный конкурент дешевле порога почти наверняка продаёт eSIM-SKU и
    не должен занижать рекомендацию по Sim+eSIM/Dual-SIM (корень бага «поставь
    94 890 ₽»). Порог = СЕРЕДИНА зазора между нашей самой дорогой eSIM-ценой и
    самой дешёвой physical-ценой той же семьи (так отсекаются и eSIM-цены выше
    минимума, и физику-undercutter не задеваем). Зазора нет — потолок eSIM.
    None, если eSIM-варианта в каталоге нет (сравнивать не с чем).
    """
    cur = conn.execute(
        "SELECT title, price FROM products "
        "WHERE source_type = 'base' AND model_key = ? AND storage IS ? "
        "AND price IS NOT NULL",
        (base_row["model_key"], base_row["storage"]),
    )
    esim: list[int] = []
    phys: list[int] = []
    for r in cur.fetchall():
        st = sim_type_of(r["title"])
        if st == "esim":
            esim.append(r["price"])
        elif st in ("sim_esim", "dual_sim"):
            phys.append(r["price"])
    if not esim:
        return None
    hi = max(esim)
    if phys and min(phys) > hi:            # чистый зазор eSIM|physical — режем посередине
        return (hi + min(phys)) // 2
    return hi


def _base_families(conn: sqlite3.Connection) -> list[list[dict]]:
    """Строки эталона, сгруппированные в семьи (model_key, storage, sim) — как
    их видит карточка бота. Для /stats и /top, чтобы числа сходились с карточками."""
    fams: dict[tuple, list[dict]] = {}
    for r in conn.execute(
            "SELECT id, title, model_key, storage, price, url, fetched_at "
            "FROM products WHERE source_type = 'base'"):
        d = dict(r)
        fams.setdefault((d["model_key"], d["storage"], sim_type_of(d["title"])), []).append(d)
    return list(fams.values())


def base_by_id(conn: sqlite3.Connection, dipark_id: int) -> dict | None:
    cur = conn.execute(
        "SELECT id, title, model_key, storage, price, url, fetched_at "
        "FROM products WHERE id = ? AND source_type = 'base'",
        (dipark_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def biggest_gaps(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
    """Семьи, где мы дороже самого дешёвого конкурента — сильнее всего (для /top).

    Считаем ПО СЕМЬЯМ и через ту же выборку конкурентов, что карточка
    (competitors_for: семья+SIM-guard) — иначе /top говорил «дороже всех» там,
    где карточка того же товара говорила обратное, и дублировал проигрыш по
    цветам одного товара.

    Возвращает [{dipark_id, title, our_price, min_comp, min_shop, gap}], gap>0.
    """
    out: list[dict] = []
    for rows in _base_families(conn):
        priced = [r for r in rows if r["price"] is not None]
        if not priced:
            continue
        rep = min(priced, key=lambda r: r["price"])
        comps = [c for c in competitors_for(conn, rep)
                 if c["price"] is not None and c.get("sim_ok", True)]
        if not comps:
            continue
        best = min(comps, key=lambda c: c["price"])
        if rep["price"] > best["price"]:
            out.append({"dipark_id": rep["id"], "title": rep["title"],
                        "our_price": rep["price"], "min_comp": best["price"],
                        "min_shop": best["shop"], "gap": rep["price"] - best["price"]})
    out.sort(key=lambda d: d["gap"], reverse=True)
    return out[:limit]


def append_price_log(conn: sqlite3.Connection, products: list[Product], run_ts: str) -> None:
    """Дописать в историю цены конкурентов с привязкой к эталону (для алертов)."""
    rows = [(run_ts, p.dipark_id, p.shop, p.price)
            for p in products if p.dipark_id is not None]
    if rows:
        with conn:
            conn.executemany(
                "INSERT INTO price_log (run_ts, dipark_id, shop, price) VALUES (?,?,?,?)",
                rows,
            )


def previous_run_prices(conn: sqlite3.Connection, before_ts: str) -> dict[tuple[int, str], int]:
    """Цены конкурентов из последнего прогона СТРОГО до before_ts -> {(dipark_id,shop):price}."""
    row = conn.execute(
        "SELECT MAX(run_ts) AS t FROM price_log WHERE run_ts < ?", (before_ts,)
    ).fetchone()
    prev_ts = row["t"] if row else None
    if not prev_ts:
        return {}
    # MIN по (dipark_id, shop): у магазина в прогоне несколько строк (цвета/варианты),
    # а competitors_for/алерты сравнивают по МИНИМАЛЬНОЙ цене магазина. Без GROUP BY
    # dict-comprehension брал произвольную (last-wins) цену -> асимметрия prev(любая)
    # vs cur(min) фабриковала ложные «подрезы» на неизменных ценах.
    cur = conn.execute(
        "SELECT dipark_id, shop, MIN(price) AS price FROM price_log "
        "WHERE run_ts = ? AND price IS NOT NULL GROUP BY dipark_id, shop", (prev_ts,)
    )
    return {(r["dipark_id"], r["shop"]): r["price"] for r in cur.fetchall()}


def record_source_counts(conn: sqlite3.Connection, run_ts: str,
                         counts: dict[str, tuple[int, int]]) -> None:
    """Запомнить {shop: (n, with_price)} за прогон — для сравнения со следующим."""
    rows = [(run_ts, shop, n, wp) for shop, (n, wp) in counts.items()]
    if rows:
        with conn:
            conn.executemany(
                "INSERT INTO run_counts (run_ts, shop, n, with_price) VALUES (?,?,?,?)", rows)


def previous_source_counts(conn: sqlite3.Connection, before_ts: str) -> dict[str, tuple[int, int]]:
    """Счётчики источников из последнего прогона СТРОГО до before_ts -> {shop:(n,with_price)}."""
    row = conn.execute(
        "SELECT MAX(run_ts) AS t FROM run_counts WHERE run_ts < ?", (before_ts,)).fetchone()
    if not row or not row["t"]:
        return {}
    cur = conn.execute(
        "SELECT shop, n, with_price FROM run_counts WHERE run_ts = ?", (row["t"],))
    return {r["shop"]: (r["n"], r["with_price"]) for r in cur.fetchall()}


def progress_start(conn: sqlite3.Connection, shops: list[str], ts: str,
                   heavy: bool = False) -> None:
    """Начать трек прогресса: одна строка, все шаги в статусе pending."""
    steps = json.dumps([{"shop": s, "status": "pending", "n": None} for s in shops])
    with conn:
        conn.execute("DELETE FROM run_progress")
        conn.execute(
            "INSERT INTO run_progress (id, started_at, finished_at, heavy, steps) "
            "VALUES (1, ?, NULL, ?, ?)", (ts, int(heavy), steps))


def progress_mark(conn: sqlite3.Connection, shop: str, status: str,
                  n: int | None = None) -> None:
    """Отметить шаг источника: status = running | done | fail (+ число товаров)."""
    row = conn.execute("SELECT steps FROM run_progress WHERE id = 1").fetchone()
    if not row:
        return
    steps = json.loads(row["steps"])
    for st in steps:
        if st["shop"] == shop:
            st["status"] = status
            if n is not None:
                st["n"] = n
            break
    with conn:
        conn.execute("UPDATE run_progress SET steps = ? WHERE id = 1", (json.dumps(steps),))


def progress_finish(conn: sqlite3.Connection, ts: str) -> None:
    """Пометить сбор завершённым (проставить finished_at)."""
    with conn:
        conn.execute("UPDATE run_progress SET finished_at = ? WHERE id = 1", (ts,))


def progress_read(conn: sqlite3.Connection) -> dict | None:
    """Текущий прогресс сбора или None, если сбор ещё ни разу не запускался."""
    row = conn.execute(
        "SELECT started_at, finished_at, heavy, steps FROM run_progress WHERE id = 1"
    ).fetchone()
    if not row or not row["started_at"]:
        return None
    return {"started_at": row["started_at"], "finished_at": row["finished_at"],
            "heavy": bool(row["heavy"]), "steps": json.loads(row["steps"])}


def market_position(conn: sqlite3.Connection) -> dict:
    """Позиция на рынке: где мы дешевле/дороже/наравне + средний проигрыш.

    Считаем ПО СЕМЬЯМ через competitors_for — та же логика, что у карточки
    (семья+SIM-guard), иначе /stats расходился с карточками. Семья учитывается,
    если есть И наша цена, И цена хоть одного конкурента.
    """
    cheaper = pricier = equal = 0
    loss_pcts: list[float] = []
    for rows in _base_families(conn):
        priced = [r for r in rows if r["price"] is not None]
        if not priced:
            continue
        rep = min(priced, key=lambda r: r["price"])
        comps = [c["price"] for c in competitors_for(conn, rep)
                 if c["price"] is not None and c.get("sim_ok", True)]
        if not comps:
            continue
        mn = min(comps)
        if rep["price"] < mn:
            cheaper += 1
        elif rep["price"] > mn:
            pricier += 1
            loss_pcts.append((rep["price"] - mn) / rep["price"] * 100)
        else:
            equal += 1
    total = cheaper + pricier + equal
    avg_loss = round(sum(loss_pcts) / len(loss_pcts), 1) if loss_pcts else 0.0
    return {"total": total, "cheaper": cheaper, "pricier": pricier,
            "equal": equal, "avg_loss_pct": avg_loss}


def stats(conn: sqlite3.Connection) -> list[dict]:
    """Срез по магазинам: сколько товаров и когда обновлялось (для диагностики)."""
    cur = conn.execute(
        "SELECT shop, source_type, COUNT(*) AS n, "
        "SUM(price IS NOT NULL) AS with_price, MAX(fetched_at) AS last "
        "FROM products GROUP BY shop ORDER BY n DESC"
    )
    return [dict(r) for r in cur.fetchall()]
