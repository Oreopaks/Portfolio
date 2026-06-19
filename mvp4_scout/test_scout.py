"""
Офлайн-тесты MVP4 (без сети). Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp4_scout/test_scout.py
"""
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from mvp4_scout.fl_source import parse_orders
from mvp4_scout.scout import filter_orders
from mvp4_scout.draft import make_draft, PROFILE

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
    test_make_draft()
    print("MVP4 TESTS OK")
