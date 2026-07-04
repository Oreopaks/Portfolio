"""Тесты хранилища: снимок магазина, линковка к эталону, сравнение, /top."""
from mvp7_price_scout import store
from mvp7_price_scout.normalize import Product


def _base(conn):
    """Залить каталог эталона (наш di-park) и вернуть id товара iPhone 17 256."""
    p = Product(shop="di-park", title="Apple iPhone 17 256Gb White",
                price=149990, source_type="base", url="https://di-park.ru/x")
    store.replace_shop(conn, "di-park", [p])
    store.link_base_self(conn)
    return store.base_catalog(conn)[0]["id"]


def test_replace_shop_is_snapshot(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    _base(conn)
    # повторный сбор магазина с другим набором -> старое затёрто, не накоплено
    store.replace_shop(conn, "sr57", [
        Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990),
    ])
    store.replace_shop(conn, "sr57", [
        Product(shop="sr57", title="Apple iPhone 17 256Gb", price=143000),
    ])
    rows = conn.execute("SELECT COUNT(*) c FROM products WHERE shop='sr57'").fetchone()
    assert rows["c"] == 1


def test_comparison_links_competitor_to_base(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    bid = _base(conn)
    comp = Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990)
    comp.dipark_id = bid                      # матч проставит collector; тут вручную
    store.replace_shop(conn, "sr57", [comp])
    got = store.competitors_for(conn, store.base_by_id(conn, bid))   # по семье модель+объём+SIM
    assert len(got) == 1 and got[0]["shop"] == "sr57" and got[0]["price"] == 144990


def test_competitors_visible_across_sim_family(tmp_path):
    """Конкурент без пометки SIM (привязан к дешёвой eSIM-строке) виден и на physical-карточке."""
    conn = store.connect(tmp_path / "p.db")
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)",
                price=100990, source_type="base"),
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Deep Blue eSIM",
                price=91990, source_type="base"),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    rows = store.base_catalog(conn)
    esim = min(rows, key=lambda r: r["price"])          # к дешёвой eSIM привяжется конкурент
    phys = max(rows, key=lambda r: r["price"])          # physical (Sim+E-Sim)
    comp = Product(shop="sr57", title="Apple iPhone 17 Pro 256Gb", price=95000)   # SIM не указан
    comp.dipark_id = esim["id"]
    store.replace_shop(conn, "sr57", [comp])
    got = store.competitors_for(conn, store.base_by_id(conn, phys["id"]))
    assert len(got) == 1 and got[0]["shop"] == "sr57"


def test_marked_sim_shop_unmarked_rows_hidden(tmp_path):
    """Магазин явно метит eSIM -> его НЕпомеченные (physical) строки не лезут на eSIM-карточку.

    Магазин целиком без пометок SIM (iprice) виден по-прежнему — мягкий guard.
    """
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Cosmic Orange (E-Sim)",
                   price=89490, source_type="base")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    rp = [Product(shop="repremium", title="Смартфон Apple iPhone 17 Pro 256 ГБ оранжевый eSIM", price=91390),
          Product(shop="repremium", title="Смартфон Apple iPhone 17 Pro 256 ГБ оранжевый", price=100890)]
    ip = [Product(shop="iprice", title="Apple iPhone 17 Pro 256Gb Orange", price=91990)]
    for c in rp + ip:
        c.dipark_id = bid
    store.replace_shop(conn, "repremium", rp)
    store.replace_shop(conn, "iprice", ip)
    got = {(g["shop"], g["price"]) for g in store.competitors_for(conn, store.base_by_id(conn, bid))}
    assert ("repremium", 91390) in got
    assert ("repremium", 100890) not in got       # непомеченная строка метящего магазина скрыта
    assert ("iprice", 91990) in got


def test_physical_card_excludes_esim_priced_competitor(tmp_path):
    """Корень бага: немаркированный конкурент с ценой уровня eSIM НЕ занижает
    Sim+eSIM-карточку. sim_ok=False у eSIM-цены, min валидных = physical-цена."""
    conn = store.connect(tmp_path / "p.db")
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Orange (E-Sim)",
                price=96490, source_type="base"),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Silver (E-Sim)",
                price=99990, source_type="base"),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Orange (Sim+E-Sim)",
                price=109990, source_type="base"),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Blue (Sim+E-Sim)",
                price=111990, source_type="base"),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    rows = store.base_catalog(conn)
    esim_id = min(rows, key=lambda r: r["price"])["id"]       # к дешёвой eSIM привяжется матчер
    phys = max(rows, key=lambda r: r["price"])                # Sim+eSIM карточка
    comps = [
        Product(shop="iprice", title="Apple iPhone 17 Pro Max 256Gb Orange (NEW)", price=94990),  # eSIM-версия
        Product(shop="sr57", title="iPhone 17 Pro Max 256GB Orange Sim+eSIM", price=109990),      # явная physical
        Product(shop="repremium", title="Смартфон Apple iPhone 17 Pro Max 256 ГБ оранжевый", price=111890),  # physical без пометки
    ]
    for c in comps:
        c.dipark_id = esim_id
    for shop in ("iprice", "sr57", "repremium"):
        store.replace_shop(conn, shop, [c for c in comps if c.shop == shop])

    got = {c["shop"]: c for c in store.competitors_for(conn, store.base_by_id(conn, phys["id"]))}
    assert got["iprice"]["sim_ok"] is False        # 94990 — цена eSIM-версии, вне расчёта
    assert got["sr57"]["sim_ok"] is True and got["repremium"]["sim_ok"] is True
    valid_min = min(c["price"] for c in got.values() if c["sim_ok"])
    assert valid_min == 109990                     # не 94990 — floor из physical-цен


def test_upsert_base_keeps_ids_stable(tmp_path):
    """Пересбор каталога НЕ ротирует id эталона — на них смотрят price_log и кнопки."""
    conn = store.connect(tmp_path / "p.db")

    def snap(price):
        return [Product(shop="di-park", title="Apple iPhone 17 256Gb White",
                        price=price, source_type="base", url="https://di-park.ru/x",
                        fetched_at="2026-07-01T10:00:00")]

    store.upsert_base(conn, snap(149990))
    id1 = store.base_catalog(conn)[0]["id"]
    store.upsert_base(conn, snap(148990))          # тот же товар, новая цена
    rows = store.base_catalog(conn)
    assert len(rows) == 1 and rows[0]["id"] == id1 and rows[0]["price"] == 148990
    store.upsert_base(conn, [])                    # товар исчез с сайта — удалён
    assert store.base_catalog(conn) == []


def test_alerts_fire_across_recollections(tmp_path):
    """Снижение цены конкурента даёт алерт, даже когда каталог пересобран между прогонами."""
    from mvp7_price_scout import alerts

    conn = store.connect(tmp_path / "p.db")

    def base(ts):
        p = Product(shop="di-park", title="Apple iPhone 17 256Gb White", price=68000,
                    source_type="base", url="https://di-park.ru/x", fetched_at=ts)
        store.upsert_base(conn, [p])
        return store.base_catalog(conn)[0]["id"]

    def comp(price, bid):
        c = Product(shop="sr57", title="Apple iPhone 17 256Gb", price=price)
        c.dipark_id = bid
        store.replace_shop(conn, "sr57", [c])
        return c

    ts1, ts2 = "2026-07-01T10:00:00", "2026-07-01T13:00:00"
    bid = base(ts1)
    store.append_price_log(conn, [comp(69000, bid)], ts1)     # прогон 1: дороже нас
    bid2 = base(ts2)                                          # пересбор: id стабилен
    assert bid2 == bid
    comp(66000, bid2)                                         # прогон 2: подрезал
    msgs = alerts.compute_alerts(conn, ts2)
    assert msgs and "дешевле нас" in msgs[0]


def test_source_counts_roundtrip(tmp_path):
    """Счётчики источников: последний прогон до ts; пусто если истории нет."""
    conn = store.connect(tmp_path / "p.db")
    store.record_source_counts(conn, "2026-06-30T10:00:00", {"sr57": (50, 48), "iprice": (30, 30)})
    store.record_source_counts(conn, "2026-06-30T13:00:00", {"sr57": (52, 50)})
    assert store.previous_source_counts(conn, "2026-06-30T13:00:00") == {"sr57": (50, 48), "iprice": (30, 30)}
    assert store.previous_source_counts(conn, "2026-06-30T09:00:00") == {}


def test_progress_roundtrip(tmp_path):
    """Прогресс сбора: старт со списком, отметки шагов, финиш; новый прогон затирает."""
    conn = store.connect(tmp_path / "p.db")
    assert store.progress_read(conn) is None                 # ещё не запускался
    store.progress_start(conn, ["di-park", "sr57", "mobilax"], "2026-07-04T09:00:00", heavy=True)
    p = store.progress_read(conn)
    assert p and p["heavy"] is True and len(p["steps"]) == 3 and p["finished_at"] is None
    assert all(s["status"] == "pending" for s in p["steps"])
    store.progress_mark(conn, "di-park", "done", 2900)
    store.progress_mark(conn, "sr57", "fail")
    steps = {s["shop"]: s for s in store.progress_read(conn)["steps"]}
    assert steps["di-park"]["status"] == "done" and steps["di-park"]["n"] == 2900
    assert steps["sr57"]["status"] == "fail"
    store.progress_finish(conn, "2026-07-04T09:05:00")
    assert store.progress_read(conn)["finished_at"] == "2026-07-04T09:05:00"
    store.progress_start(conn, ["di-park"], "2026-07-04T12:00:00")   # новый прогон затирает
    p2 = store.progress_read(conn)
    assert len(p2["steps"]) == 1 and p2["finished_at"] is None


def test_biggest_gaps(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    bid = _base(conn)                         # наша цена 149990
    cheap = Product(shop="sr57", title="Apple iPhone 17 256Gb", price=144990)
    cheap.dipark_id = bid
    store.replace_shop(conn, "sr57", [cheap])
    gaps = store.biggest_gaps(conn)
    assert gaps and gaps[0]["dipark_id"] == bid
    assert gaps[0]["gap"] == 5000 and gaps[0]["min_shop"] == "sr57"
