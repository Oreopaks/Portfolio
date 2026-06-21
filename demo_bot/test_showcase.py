"""
Офлайн-тесты витрины (mock-LLM, без сети). Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python demo_bot/test_showcase.py
"""
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from demo_bot.showcase import handle_demo, MENU, _text_to_lead


def test_menu():
    for t in ("/demo", "демо", "меню"):
        r = handle_demo(t, {})
        assert r is not None and r[0] == MENU, t
    print("ok menu: /demo, демо, меню -> меню витрины")


def test_inline_copy_and_smm():
    reply, st = handle_demo("/copy кофейня, акция на раф", {})
    assert "копирайтер" in reply.lower() and ("кофейня" in reply or "раф" in reply), reply[:120]
    assert st == {}, st  # инлайн-команда не оставляет состояния

    reply, st = handle_demo("/smm доставка еды", {})
    assert "Контент-план" in reply and "День 1" in reply, reply[:120]
    print("ok inline: /copy и /smm с аргументом отрабатывают сразу")


def test_two_step_flow():
    # /rag без аргумента -> запрос + состояние demo:rag
    reply, st = handle_demo("/rag", {})
    assert st.get("demo") == "rag", st
    # следующий простой текст обрабатывается как аргумент rag
    reply2, st2 = handle_demo("какой срок гарантии?", st)
    assert reply2 is not None and "документ" in reply2.lower(), reply2[:120]
    assert st2 == {}, st2
    print("ok flow: /rag -> запрос -> ответ по следующему сообщению")


def test_lead_scoring():
    reply, _ = handle_demo("/lead Нужен лендинг срочно, бюджет 120000, тел +79991234567, a@b.ru", {})
    # бюджет>=50000(+50) + срочно(+30) + телефон(+10) + email(+10) = 100 -> hot
    assert "HOT" in reply, reply[:160]
    lead = _text_to_lead("бюджет 120000 +79991234567 a@b.ru")
    assert lead["budget"] == 120000 and lead["phone"] and lead["email"], lead
    print("ok lead: горячая заявка -> HOT, парсинг бюджета/контактов")


def test_passthrough():
    # не-demo текст без demo-состояния -> None (пусть решает основной бот)
    assert handle_demo("во сколько открываетесь?", {}) is None
    assert handle_demo("/start", {}) is None              # /start = кофейня, не витрина
    assert handle_demo("привет", {"flow": "booking"}) is None  # бронь не перехватывается
    print("ok passthrough: посторонний текст и /start -> None")


if __name__ == "__main__":
    test_menu()
    test_inline_copy_and_smm()
    test_two_step_flow()
    test_lead_scoring()
    test_passthrough()
    print("DEMO_BOT TESTS OK")
