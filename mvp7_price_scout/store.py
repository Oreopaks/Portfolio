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
"""


def connect(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Открыть БД (env PRICESCOUT_DB > аргумент > дефолт) и накатить схему."""
    path = db_path or os.environ.get("PRICESCOUT_DB") or DEFAULT_DB
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


def base_catalog(conn: sqlite3.Connection) -> list[dict]:
    """Каталог эталона (наш di-park) — id+ключ+объём+цена для матчинга/поиска."""
    cur = conn.execute(
        "SELECT id, title, model_key, storage, price, url "
        "FROM products WHERE source_type = 'base'"
    )
    return [dict(r) for r in cur.fetchall()]


def search_base(conn: sqlite3.Connection, query_key: str, limit: int = 40) -> list[dict]:
    """Кандидаты из каталога эталона по словам ключа (LIKE) — добивает fuzzy в caller.

    Возвращает строки base, у которых model_key/title содержит хотя бы одно
    значимое слово запроса. Узкий префильтр перед дорогим rapidfuzz.
    """
    words = [w for w in query_key.split() if len(w) >= 2]
    if not words:
        cur = conn.execute(
            "SELECT id, title, model_key, storage, price, url "
            "FROM products WHERE source_type='base' LIMIT ?", (limit * 4,)
        )
        return [dict(r) for r in cur.fetchall()]
    clause = " OR ".join(["model_key LIKE ? OR title LIKE ?"] * len(words))
    params: list[str] = []
    for w in words:
        params += [f"%{w}%", f"%{w}%"]
    cur = conn.execute(
        f"SELECT id, title, model_key, storage, price, url "
        f"FROM products WHERE source_type='base' AND ({clause}) LIMIT ?",
        (*params, limit * 4),
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
        "SELECT id, title FROM products "
        "WHERE source_type = 'base' AND model_key = ? AND storage IS ?",
        (base_row["model_key"], base_row["storage"]),
    ).fetchall()
    bsim = sim_type_of(base_row["title"])
    ids = [r["id"] for r in fam
           if bsim is None or sim_type_of(r["title"]) is None or sim_type_of(r["title"]) == bsim]
    if not ids:
        ids = [base_row["id"]]
    placeholders = ",".join("?" * len(ids))
    cur = conn.execute(
        f"SELECT shop, title, price, url, in_stock, source_type, fetched_at "
        f"FROM products WHERE source_type != 'base' AND dipark_id IN ({placeholders}) "
        f"ORDER BY (price IS NULL), price",
        ids,
    )
    return [dict(r) for r in cur.fetchall()]


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


def base_by_id(conn: sqlite3.Connection, dipark_id: int) -> dict | None:
    cur = conn.execute(
        "SELECT id, title, model_key, storage, price, url, fetched_at "
        "FROM products WHERE id = ? AND source_type = 'base'",
        (dipark_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def biggest_gaps(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
    """Товары, где мы дороже самого дешёвого конкурента — сильнее всего (для /top).

    Возвращает [{dipark_id, title, our_price, min_comp, min_shop, gap}], gap>0.
    """
    cur = conn.execute(
        """
        SELECT b.id AS dipark_id, b.title AS title, b.price AS our_price,
               MIN(c.price) AS min_comp
        FROM products b
        JOIN products c ON c.dipark_id = b.id AND c.source_type != 'base'
        WHERE b.source_type = 'base' AND b.price IS NOT NULL AND c.price IS NOT NULL
        GROUP BY b.id
        HAVING b.price > MIN(c.price)
        ORDER BY (b.price - MIN(c.price)) DESC
        LIMIT ?
        """,
        (limit,),
    )
    out: list[dict] = []
    for r in cur.fetchall():
        d = dict(r)
        d["gap"] = d["our_price"] - d["min_comp"]
        # какой магазин дал минимум
        sub = conn.execute(
            "SELECT shop FROM products WHERE dipark_id=? AND source_type!='base' "
            "AND price=? LIMIT 1", (d["dipark_id"], d["min_comp"]),
        ).fetchone()
        d["min_shop"] = sub["shop"] if sub else "?"
        out.append(d)
    return out


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
    cur = conn.execute(
        "SELECT dipark_id, shop, price FROM price_log WHERE run_ts = ?", (prev_ts,)
    )
    return {(r["dipark_id"], r["shop"]): r["price"] for r in cur.fetchall() if r["price"] is not None}


def market_position(conn: sqlite3.Connection) -> dict:
    """Позиция на рынке: где мы дешевле/дороже/наравне + средний проигрыш.

    Считаем по товарам, где есть И наша цена, И цена хоть одного конкурента.
    """
    cur = conn.execute(
        """
        SELECT b.id, b.price AS our, MIN(c.price) AS mn
        FROM products b
        JOIN products c ON c.dipark_id = b.id AND c.source_type != 'base'
        WHERE b.source_type = 'base' AND b.price IS NOT NULL AND c.price IS NOT NULL
        GROUP BY b.id
        """
    )
    cheaper = pricier = equal = 0
    loss_pcts: list[float] = []
    for r in cur.fetchall():
        if r["our"] < r["mn"]:
            cheaper += 1
        elif r["our"] > r["mn"]:
            pricier += 1
            loss_pcts.append((r["our"] - r["mn"]) / r["our"] * 100)
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
