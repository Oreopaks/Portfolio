"""
Офлайн-тесты MVP4 (без сети). Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp4_scout/test_scout.py
"""
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from mvp4_scout.fl_source import parse_orders, parse_listing
from mvp4_scout.scout import filter_orders, _is_blacklisted
from mvp4_scout.draft import make_draft, PROFILE
from mvp4_scout import rank

# --- Фикстура: разметка как у живого FL.ru (name="prj..", span.fl-rub) ------
# Кнопка «Откликнуться» специально добавлена первым <a> в карточке, чтобы тест
# ловил регресс «парсер взял кнопку вместо заголовка».
FIXTURE_HTML = """
<html><body>
<div class="header"><a href="/projects/000/otklik.html">Откликнуться</a> мусор</div>

<div class="b-post">
  <a href="/projects/111111/x.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj111111" href="/projects/111111/razrabotka-bota.html">Разработка Telegram-бота на GPT</a></h2>
  <div class="b-post__price"><span class="text-4 text-dark">30&nbsp;000&nbsp;<span class="fl-rub"><span class="d-none">руб</span></span></span></div>
</div>

<div class="b-post">
  <a href="/projects/222222/y.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj222222" href="/projects/222222/parsing-kataloga.html">Парсинг каталога интернет-магазина</a></h2>
  <div class="b-post__price"><span class="text-4 text-dark">5&nbsp;000&nbsp;<span class="fl-rub"><span class="d-none">руб</span></span></span></div>
</div>

<div class="b-post">
  <a href="/projects/333333/z.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj333333" href="/projects/333333/avtomatizaciya-n8n.html">Автоматизация отчётов в n8n</a></h2>
  <div class="b-post__price"><span class="text-4 text-muted">по договоренности</span></div>
</div>

</body></html>
"""


def test_parse_orders():
    orders = parse_orders(FIXTURE_HTML)
    assert len(orders) == 3, f"ожидалось 3 заказа, получено {len(orders)}"

    by_url = {o["url"]: o for o in orders}
    o1 = by_url["https://www.fl.ru/projects/111111/"]
    o2 = by_url["https://www.fl.ru/projects/222222/"]
    o3 = by_url["https://www.fl.ru/projects/333333/"]

    assert o1["budget"] == 30000, f"budget1={o1['budget']}"
    assert o2["budget"] == 5000, f"budget2={o2['budget']}"
    assert o3["budget"] is None, f"budget3={o3['budget']}"

    assert "Telegram" in o1["title"], o1["title"]
    # регресс-гард: парсер не должен подхватывать кнопку «Откликнуться» как заголовок
    assert all(o["title"] != "Откликнуться" for o in orders), [o["title"] for o in orders]
    print("ok parse_orders: 3 заказа, бюджеты 30000 / 5000 / None, кнопки отсеяны")


def test_filter_orders():
    orders = parse_orders(FIXTURE_HTML)
    keywords = ["бот", "парсинг", "автоматизация", "n8n"]
    kept = filter_orders(orders, min_budget=10000, keywords=keywords)
    titles = [o["title"] for o in kept]

    # >=10000 с ключом — остаётся; 5000 — отсеивается; None-бюджет с ключом — остаётся.
    assert any("Telegram-бота" in t for t in titles), titles  # 30000, ключ "бот"
    assert not any("Парсинг каталога" in t for t in titles), titles  # 5000 — дроп
    assert any("n8n" in t for t in titles), titles  # None + ключ "n8n"/"автоматизация"

    budgets = [o["budget"] for o in kept]
    assert 5000 not in budgets, budgets
    print(f"ok filter_orders: оставлено {len(kept)} (5000-й отсеян)")


# --- Фикстура: карточки страницы списка fl.ru/projects/ (с откликами/возрастом) -
# Структура повторяет живую: иконка #message-empty -> «N ответов», #eye-open ->
# просмотры, «Заказ X назад» -> возраст, число перед «руб» -> бюджет.
LISTING_FIXTURE = """
<div class="b-post">
  <a href="/projects/111111/x.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj111111" href="/projects/111111/bot-na-gpt.html">Разработка Telegram-бота на GPT</a></h2>
  <div class="b-post__price">30&nbsp;000&nbsp;<span class="fl-rub">руб</span></div>
  <div class="b-post__body">Нужен чат-бот для записи клиентов и автоответов.</div>
  <div class="mt-6">Заказ 2 часа 10 минут назад</div>
  <span title="Количество просмотров"><svg><use xlink:href="#eye-open"></use></svg><span class="text-7">больше 300</span></span>
  <span><svg><use xlink:href="#message-empty"></use></svg> 3 ответа</span>
</div>

<div class="b-post">
  <a href="/projects/222222/y.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj222222" href="/projects/222222/parsing-cen.html">Парсинг цен маркетплейса в Excel</a></h2>
  <div class="b-post__price">8&nbsp;000&nbsp;<span class="fl-rub">руб</span></div>
  <div class="b-post__body">Собрать цены конкурентов и выгрузить в таблицу.</div>
  <div class="mt-6">Заказ 35 минут назад</div>
  <span title="Количество просмотров"><svg><use xlink:href="#eye-open"></use></svg><span class="text-7">42</span></span>
  <span><svg><use xlink:href="#message-empty"></use></svg> 1 ответ</span>
</div>

<div class="b-post">
  <a href="/projects/333333/z.html" class="b-post__link-apply">Откликнуться</a>
  <h2><a class="b-post__link" name="prj333333" href="/projects/333333/avtomatizaciya.html">Автоматизация заявок в CRM на n8n</a></h2>
  <div class="b-post__price"><span class="text-muted">по договоренности</span></div>
  <div class="b-post__body">Заявки с сайта в CRM + уведомление в Telegram.</div>
  <div class="mt-6">Заказ 1 день назад</div>
  <span title="Количество просмотров"><svg><use xlink:href="#eye-open"></use></svg><span class="text-7">больше 300</span></span>
  <span><svg><use xlink:href="#message-empty"></use></svg> 18 ответов</span>
</div>
"""


def test_parse_listing():
    orders = parse_listing(LISTING_FIXTURE)
    assert len(orders) == 3, f"ожидалось 3, получено {len(orders)}"
    by = {o["url"]: o for o in orders}
    bot = by["https://www.fl.ru/projects/111111/bot-na-gpt.html"]
    par = by["https://www.fl.ru/projects/222222/parsing-cen.html"]
    aut = by["https://www.fl.ru/projects/333333/avtomatizaciya.html"]

    assert bot["budget"] == 30000, bot["budget"]
    assert bot["responses"] == 3, bot["responses"]
    assert bot["views"] == 300, bot["views"]
    assert 2.0 < bot["age_hours"] < 2.3, bot["age_hours"]  # 2ч10м

    assert par["budget"] == 8000 and par["responses"] == 1, par
    assert par["age_hours"] is not None and par["age_hours"] < 1, par["age_hours"]  # 35 мин

    assert aut["budget"] is None, aut["budget"]            # по договорённости
    assert aut["responses"] == 18, aut["responses"]
    assert abs(aut["age_hours"] - 24.0) < 0.1, aut["age_hours"]  # 1 день
    print("ok parse_listing: 3 карточки, бюджет/отклики/возраст/просмотры распознаны")


def test_rank_model():
    # возраст
    assert rank.parse_age_hours(None) is None
    assert abs(rank.parse_age_hours("1 час назад") - 1.0) < 1e-6
    assert abs(rank.parse_age_hours("2 дня назад") - 48.0) < 1e-6
    assert abs(rank.parse_age_hours("19 часов 37 минут назад") - (19 + 37 / 60)) < 0.01

    # win_probability: больше откликов -> ниже; свежее -> выше
    assert rank.win_probability(0, 0) > rank.win_probability(10, 0) > rank.win_probability(30, 0)
    assert rank.win_probability(3, 0) > rank.win_probability(3, 48)
    assert 0 < rank.win_probability(50, 200) <= rank.win_probability(0, 0) <= 1.0

    # roi: ₽/день по области; None бюджет -> None
    assert rank.roi(30000, 0) == 10000.0     # 30000 / 3 дня
    assert rank.roi(None, 0) is None

    # priority монотонен по fit и по win_prob
    assert rank.priority(80, 0.8, 10000) > rank.priority(40, 0.8, 10000)
    assert rank.priority(80, 0.9, 10000) > rank.priority(80, 0.2, 10000)

    # prescore: заказ по теме обгоняет заказ вне темы
    kw = ["бот", "парсинг", "автоматизация"]
    in_topic = {"title": "Разработка бота", "desc": "телеграм бот", "responses": 1, "age_hours": 1, "budget": 30000}
    off_topic = {"title": "Монтаж видео", "desc": "склейка роликов", "responses": 1, "age_hours": 1, "budget": 30000}
    assert rank.prescore(in_topic, kw) > rank.prescore(off_topic, kw)
    assert rank.keyword_strength("монтаж видео", kw) == 0.0
    print("ok rank_model: age/win_prob/roi/priority/prescore монотонны и корректны")


def test_blacklist():
    # «такое не нужно»: OSINT/пробив/накрутка отсекаются ДО LLM
    assert _is_blacklisted({"title": "Ищу цифровой след человека", "desc": ""})
    assert _is_blacklisted({"title": "Накрутка голосов на сайте", "desc": ""})
    assert _is_blacklisted({"title": "Пробив по номеру телефона", "desc": ""})
    # нормальный заказ — проходит
    assert not _is_blacklisted({"title": "Разработка Telegram-бота на GPT", "desc": "запись клиентов"})
    print("ok blacklist: OSINT/накрутка отсеяны, нормальный заказ прошёл")


def test_make_draft():
    order = {"title": "Разработка Telegram-бота на GPT", "budget": 30000,
             "url": "https://www.fl.ru/projects/111111/"}
    draft = make_draft(order, PROFILE)
    assert isinstance(draft, str) and draft.strip(), "пустой черновик"
    # mock-LLM возвращает детерминированный текст, в котором эхо user-промпта,
    # содержащего заголовок заказа -> часть заголовка должна присутствовать.
    assert "Telegram" in draft or "бот" in draft.lower(), draft[:200]
    print(f"ok make_draft: непустой отклик ({len(draft)} симв.)")


if __name__ == "__main__":
    test_parse_orders()
    test_filter_orders()
    test_parse_listing()
    test_rank_model()
    test_blacklist()
    test_make_draft()
    print("MVP4 TESTS OK")
