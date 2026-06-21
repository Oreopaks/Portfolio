"""
Офлайн-тесты MVP6 (mock-LLM, без сети). Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp6_smm/test_smm.py
"""
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from mvp6_smm.smm import content_plan, make_post, RUBRICS, PLATFORMS


def test_content_plan_deterministic():
    plan = content_plan("доставка здоровой еды", 7)
    assert len(plan) == 7, len(plan)
    assert plan[0]["rubric"] == RUBRICS[0][0], plan[0]
    assert plan[0]["day"] == 1 and plan[6]["day"] == 7
    # ротация рубрик: день 8 (если бы был) вернулся бы к первой; проверим цикл на 8
    plan8 = content_plan("x", 8)
    assert plan8[7]["rubric"] == RUBRICS[0][0], plan8[7]
    # тема попадает в идею
    assert "доставка здоровой еды" in plan[0]["idea"], plan[0]["idea"]
    print("ok content_plan: 7 дней, рубрики ротуются, тема в идее")


def test_days_clamp_and_empty():
    assert len(content_plan("x", 99)) == 14, "days клампится в 14"
    assert len(content_plan("x", 0)) == 1, "days < 1 -> 1"
    try:
        content_plan("   ")
        assert False, "ожидался ValueError на пустую тему"
    except ValueError:
        pass
    print("ok clamp: days [1..14], пустая тема -> ValueError")


def test_make_post():
    idea = content_plan("автосервис", 1)[0]["idea"]
    out = make_post(idea, "telegram", "автосервис")
    assert isinstance(out, str) and out.strip(), "пустой пост"
    assert "автосервис" in out, out[:160]  # тема эхо-ится mock-ом
    # неизвестная платформа не падает (фоллбэк на telegram)
    assert make_post(idea, "tiktok", "автосервис").strip()
    assert set(PLATFORMS) == {"telegram", "vk", "instagram"}, list(PLATFORMS)
    print("ok make_post: непустой пост, фоллбэк платформы работает")


if __name__ == "__main__":
    test_content_plan_deterministic()
    test_days_clamp_and_empty()
    test_make_post()
    print("MVP6 TESTS OK")
