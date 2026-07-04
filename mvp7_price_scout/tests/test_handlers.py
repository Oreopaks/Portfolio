"""Тесты рендера ответа бота: компактная таблица, поиск, /top."""
from mvp7_price_scout import store, handlers
from mvp7_price_scout.normalize import Product


def _seed(tmp_path):
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb",
                   price=149990, source_type="base", url="u", fetched_at="2026-06-29T16:00:00")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    comps = [
        Product(shop="sr57", title="Apple iPhone 17 Pro Max 256Gb", price=144990,
                fetched_at="2026-06-29T14:00:00"),
        Product(shop="iprice", title="Apple iPhone 17 Pro Max 256Gb", price=151000,
                fetched_at="2026-06-29T14:00:00"),
    ]
    for c in comps:
        c.dipark_id = bid
    store.replace_shop(conn, "sr57", [comps[0]])
    store.replace_shop(conn, "iprice", [comps[1]])
    return conn, bid


def test_render_comparison_format(tmp_path):
    conn, bid = _seed(tmp_path)
    row = store.base_by_id(conn, bid)
    out = handlers.render_comparison(conn, row)
    assert "💰 Твоя цена: 149 990 ₽" in out
    assert "🔴 Дешевле тебя (1):" in out
    assert "sr57.ru — 144 990 ₽  (−5 000 ₽)" in out
    assert "🟢 Дороже тебя (1):" in out
    assert "iprice — 151 000 ₽  (+1 010 ₽)" in out
    assert "🎯 Поставь 144 890 ₽ → станешь дешевле всех" in out
    assert "🟡 Тебя обходят по цене: 1 из 2" in out


def test_find_product_fuzzy(tmp_path):
    conn, bid = _seed(tmp_path)
    assert handlers.find_product(conn, "iphone 17 pro max 256")["id"] == bid
    assert handlers.find_product(conn, "айфон 17 про макс 256")["id"] == bid   # RU alias
    assert handlers.find_product(conn, "ноутбук asus") is None


def test_find_product_ignores_color(tmp_path):
    """Поиск с цветом (в т.ч. вне закрытого списка) находит товар по модель+объём."""
    conn, bid = _seed(tmp_path)
    assert handlers.find_product(conn, "iphone 17 pro max 256 cosmic orange")["id"] == bid
    assert handlers.find_product(conn, "айфон 17 про макс 256 чёрный")["id"] == bid


def test_find_product_per_color_price(tmp_path):
    """Запрос с цветом отдаёт цену ИМЕННО этого цвета; без цвета — самый дешёвый."""
    conn = store.connect(tmp_path / "p.db")
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Cosmic Orange (Sim+E-Sim)",
                price=99990, source_type="base", url="u", fetched_at="2026-06-30T16:00:00"),
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)",
                price=100990, source_type="base", url="u", fetched_at="2026-06-30T16:00:00"),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    assert handlers.find_product(conn, "17 pro 256 blue")["price"] == 100990
    assert handlers.find_product(conn, "17 pro 256 синий")["price"] == 100990     # RU цвет
    assert handlers.find_product(conn, "17 pro 256")["price"] == 99990            # без цвета


def _seed_multi(tmp_path):
    """Каталог с несколькими семьями и цветами для проверки подсказок."""
    conn = store.connect(tmp_path / "p.db")
    t = "2026-06-30T16:00:00"
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Cosmic Orange (Sim+E-Sim)",
                price=99990, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Deep Blue (Sim+E-Sim)",
                price=100990, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro 512Gb Silver (Sim+E-Sim)",
                price=120990, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Cosmic Orange (Sim+E-Sim)",
                price=129990, source_type="base", url="u", fetched_at=t),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    return conn


def test_suggestions_list_when_ambiguous(tmp_path):
    """Неоднозначный запрос («17 pro») -> список кнопок-подсказок, не одна карточка."""
    conn = _seed_multi(tmp_path)
    r = handlers.handle_text(conn, "17 pro", False)
    assert r.buttons and len(r.buttons) >= 2
    assert all(cb.startswith("p:") for _, cb in r.buttons)


def test_dominant_family_card_with_color_buttons(tmp_path):
    """Точный запрос с цветом -> карточка нужного цвета + кнопки других цветов семьи."""
    conn = _seed_multi(tmp_path)
    r = handlers.handle_text(conn, "17 pro 256 blue", False)
    assert "Deep Blue" in r.text and "100 990" in r.text
    assert r.buttons and any("Orange" in lbl for lbl, _ in r.buttons)
    # кнопка ведёт на другой цвет ТОЙ ЖЕ семьи (256Gb), не на 512/Pro Max
    assert all(cb.startswith("p:") for _, cb in r.buttons)


def test_callback_opens_product_card(tmp_path):
    """Тап по кнопке «p:{id}» открывает карточку товара; мусор -> None."""
    conn = _seed_multi(tmp_path)
    blue = handlers.find_product(conn, "17 pro 256 blue")
    r = handlers.handle_callback(conn, f"p:{blue['id']}")
    assert r and "Deep Blue" in r.text
    assert handlers.handle_callback(conn, "garbage") is None      # не наша кнопка
    stale = handlers.handle_callback(conn, "p:999999")            # протухший id
    assert stale and "устарел" in stale.text


def test_not_found_has_no_buttons(tmp_path):
    conn = _seed_multi(tmp_path)
    r = handlers.handle_text(conn, "nokia 3310", False)
    assert r.buttons is None and "Не нашёл" in r.text


def test_handle_text_routes(tmp_path):
    conn, _ = _seed(tmp_path)
    assert "сравниваю цены" in handlers.handle_text(conn, "/help", False).text
    assert "только администратору" in handlers.handle_text(conn, "/refresh", False).text
    assert "Твоя цена" in handlers.handle_text(conn, "iphone 17 pro max 256", False).text


def test_top(tmp_path):
    conn, _ = _seed(tmp_path)
    out = handlers.render_top(conn)
    assert "дороже" in out and "iPhone 17 Pro Max" in out


def test_html_escape_in_rendered_title(tmp_path):
    """Скрапленный title с <>& не должен ломать parse_mode=HTML (иначе Telegram 400)."""
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Apple iPhone 17 <Pro> & Max 256Gb",
                   price=149990, source_type="base", url="u", fetched_at="2026-06-29T16:00:00")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    out = handlers.render_comparison(conn, store.base_by_id(conn, bid))
    assert "&lt;Pro&gt;" in out and "&amp;" in out
    assert "<Pro>" not in out


def test_html_escape_user_query_echo(tmp_path):
    """Юзер-ввод в эхо «не нашёл» тоже экранируется."""
    conn, _ = _seed(tmp_path)
    out = handlers.handle_text(conn, "<b>zzz несуществующий", False).text
    assert "&lt;b&gt;" in out and "<b>" not in out


def test_render_one_best_row_per_shop(tmp_path):
    """Варианты одного магазина (цвета) не раздувают список: одна строка = его мин. цена."""
    conn = store.connect(tmp_path / "p.db")
    base = Product(shop="di-park", title="Наушники Marshall Major V", price=7790,
                   source_type="base", url="u", fetched_at="2026-06-29T16:00:00")
    store.replace_shop(conn, "di-park", [base])
    store.link_base_self(conn)
    bid = store.base_catalog(conn)[0]["id"]
    dups = [Product(shop="sr57", title="Marshall Major V Black", price=7490),
            Product(shop="sr57", title="Marshall Major V Brown", price=7490),
            Product(shop="sr57", title="Marshall Major V Cream", price=8490)]
    for c in dups:
        c.dipark_id = bid
    store.replace_shop(conn, "sr57", dups)
    out = handlers.render_comparison(conn, store.base_by_id(conn, bid))
    assert out.count("7 490 ₽") == 1           # магазин показан один раз, лучшей ценой
    assert "8 490 ₽" not in out                # дорогой цвет-вариант того же магазина скрыт
    assert "Дешевле тебя (1)" in out           # счётчик = число магазинов, не строк


def _seed_sim_variants(tmp_path):
    """Одна семья, один цвет, два SKU по типу SIM: eSIM-only дешевле Sim+E-Sim."""
    conn = store.connect(tmp_path / "p.db")
    t = "2026-07-01T16:00:00"
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Cosmic Orange (E-Sim)",
                price=89490, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro 256Gb Cosmic Orange (Sim+E-Sim)",
                price=99990, source_type="base", url="u", fetched_at=t),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    return conn


def test_find_product_respects_sim_type(tmp_path):
    """«sim+esim» в запросе -> Sim+E-Sim SKU, а не дешёвый eSIM-only (и наоборот)."""
    conn = _seed_sim_variants(tmp_path)
    assert handlers.find_product(conn, "17 pro 256 sim+esim")["price"] == 99990
    assert handlers.find_product(conn, "17 pro 256 esim")["price"] == 89490
    assert handlers.find_product(conn, "17 pro 256")["price"] == 89490   # SIM не указан — дешёвый


def test_handle_text_sim_query_full_path(tmp_path):
    """Сквозной путь бага: запрос «17 pro 256 sim+esim» -> карточка Sim+eSIM, не eSIM."""
    conn = _seed_sim_variants(tmp_path)
    r = handlers.handle_text(conn, "17 pro 256 sim+esim", False)
    assert "99 990" in r.text and "Sim+eSIM" in r.text


def test_short_query_full_coverage_not_dropped(tmp_path):
    """«17» покрывает все семьи целиком — fuzz-порог не должен давать «Не нашёл»."""
    conn = _seed_multi(tmp_path)
    r = handlers.handle_text(conn, "17", False)
    assert "Не нашёл" not in r.text


def test_bare_storage_asks_instead_of_random_card(tmp_path):
    """Голое «256» не открывает уверенную карточку случайного товара."""
    conn = _seed_multi(tmp_path)
    r = handlers.handle_text(conn, "256", False)
    assert "Твоя цена" not in r.text          # не карточка, а уточнение/не нашёл


def test_cyrillic_sim_query(tmp_path):
    """«сим+есим» кириллицей выбирает Sim+E-Sim SKU."""
    conn = _seed_sim_variants(tmp_path)
    assert handlers.find_product(conn, "17 pro 256 сим+есим")["price"] == 99990
    assert handlers.find_product(conn, "17 pro 256 есим")["price"] == 89490


def test_out_of_stock_competitor_excluded(tmp_path):
    """Цена «нет в наличии» не участвует в сравнении (купить нельзя)."""
    conn, bid = _seed(tmp_path)
    dead = Product(shop="kingstore", title="Apple iPhone 17 Pro Max 256Gb",
                   price=100000, in_stock=False)
    dead.dipark_id = bid
    store.replace_shop(conn, "kingstore", [dead])
    out = handlers.render_comparison(conn, store.base_by_id(conn, bid))
    assert "KingStore" not in out


def test_physical_card_floor_ignores_esim_price(tmp_path):
    """Сквозной баг-репро: на Sim+eSIM-карточке «Поставь» считается по physical-ценам,
    немаркированная eSIM-цена (iprice 94 990) отправлена во флаг, а не в floor."""
    conn = store.connect(tmp_path / "p.db")
    t = "2026-07-04T09:00:00"
    bases = [
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Orange (E-Sim)",
                price=96490, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Silver (E-Sim)",
                price=99990, source_type="base", url="u", fetched_at=t),
        Product(shop="di-park", title="Apple iPhone 17 Pro Max 256Gb Blue (Sim+E-Sim)",
                price=111990, source_type="base", url="u", fetched_at=t),
    ]
    store.replace_shop(conn, "di-park", bases)
    store.link_base_self(conn)
    rows = store.base_catalog(conn)
    esim_id = min(rows, key=lambda r: r["price"])["id"]
    phys = next(r for r in rows if "Sim+E-Sim" in r["title"])
    comps = [
        Product(shop="iprice", title="Apple iPhone 17 Pro Max 256Gb Blue (NEW)", price=94990, fetched_at=t),
        Product(shop="sr57", title="iPhone 17 Pro Max 256GB Blue Sim+eSIM", price=109990, fetched_at=t),
        Product(shop="repremium", title="Смартфон Apple iPhone 17 Pro Max 256 ГБ синий", price=111890, fetched_at=t),
    ]
    for c in comps:
        c.dipark_id = esim_id
    for shop in ("iprice", "sr57", "repremium"):
        store.replace_shop(conn, shop, [c for c in comps if c.shop == shop])

    out = handlers.render_comparison(conn, store.base_by_id(conn, phys["id"]))
    assert "🎯 Поставь 109 890 ₽ → станешь дешевле всех" in out   # sr57 109 990 − 100
    assert "94 890" not in out                                    # НЕ демпинг до eSIM-цены
    assert "Не учитываю" in out and "iprice" in out.split("Не учитываю")[1]  # iprice во флаге


def test_render_progress_states(tmp_path):
    """Статус-бар: нет прогона / идёт (частично) / завершено."""
    conn = store.connect(tmp_path / "p.db")
    assert "ещё не запускался" in handlers.render_progress(conn)
    store.progress_start(conn, ["di-park", "sr57", "mobilax"], "2026-07-04T09:00:00")
    store.progress_mark(conn, "di-park", "done", 2900)
    store.progress_mark(conn, "sr57", "running")
    out = handlers.render_progress(conn)
    assert "идёт" in out and "1/3 источников" in out      # завершён 1 (di-park)
    assert "✅ Di-Park — 2 900 тов." in out
    assert "⏳ sr57.ru" in out and "⬜ Мобилакс" in out
    store.progress_mark(conn, "sr57", "done", 200)
    store.progress_mark(conn, "mobilax", "done", 150)
    store.progress_finish(conn, "2026-07-04T09:05:00")
    done = handlers.render_progress(conn)
    assert "завершено" in done and "3/3 источников" in done


def test_status_command_and_callback(tmp_path):
    """/status и кнопка «status» отдают статус-бар с кнопкой обновления."""
    conn = store.connect(tmp_path / "p.db")
    r = handlers.handle_text(conn, "/status", False)
    assert r.buttons == [("🔄 Обновить статус", "status")]
    cb = handlers.handle_callback(conn, "status")
    assert cb and cb.buttons == [("🔄 Обновить статус", "status")]


def test_refresh_shows_progress_when_running(tmp_path, monkeypatch):
    """/refresh, когда сбор уже идёт, отдаёт статус-бар, а не общий текст."""
    conn = store.connect(tmp_path / "p.db")
    store.progress_start(conn, ["di-park", "sr57"], "2026-07-04T09:00:00")
    monkeypatch.setattr(handlers, "trigger_heavy_refresh", lambda: False)   # «уже идёт»
    r = handlers.handle_text(conn, "/refresh", True)
    assert "источников" in r.text and r.buttons == [("🔄 Обновить статус", "status")]


def test_sim_tokens_are_not_colors():
    """sim/esim/шум из запроса не должны попадать в цвет-фильтр."""
    vocab = {"17", "pro", "iphone", "256gb"}
    assert handlers._query_colors("17 pro 256 sim+esim новый", vocab) == set()
    assert handlers._query_colors("17 pro 256 синий esim", vocab) == {"blue"}
