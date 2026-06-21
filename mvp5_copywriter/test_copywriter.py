"""
Офлайн-тесты MVP5 (mock-LLM, без сети). Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp5_copywriter/test_copywriter.py
"""
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from mvp5_copywriter.copywriter import generate, formats, FORMATS


def test_formats():
    fs = formats()
    assert len(fs) == 4, fs
    assert set(FORMATS) == {"seo", "product", "post", "email"}, list(FORMATS)
    print(f"ok formats: 4 формата {sorted(FORMATS)}")


def test_generate_echoes_brief():
    # mock-LLM эхо-ит user-промпт -> часть брифа должна оказаться в выводе.
    brief = "кофейня в центре, акция на раф-кофе"
    out = generate("post", brief)
    assert isinstance(out, str) and out.strip(), "пустой текст"
    assert "кофейня" in out or "раф" in out, out[:160]
    print(f"ok generate: непустой пост ({len(out)} симв.)")


def test_keywords_in_prompt():
    # ключи попадают в user-промпт -> через mock-эхо видны в выводе.
    out = generate("seo", "ремонт квартир под ключ", keywords=["ремонт под ключ", "смета"])
    assert "ремонт под ключ" in out or "смета" in out, out[:200]
    print("ok keywords: ключевые слова уходят в запрос")


def test_unknown_format_and_empty():
    for bad in [("xxx", "тест"), ("post", "  ")]:
        try:
            generate(*bad)
            assert False, f"ожидался ValueError на {bad}"
        except ValueError:
            pass
    print("ok validation: неизвестный формат и пустой бриф -> ValueError")


if __name__ == "__main__":
    test_formats()
    test_generate_echoes_brief()
    test_keywords_in_prompt()
    test_unknown_format_and_empty()
    print("MVP5 TESTS OK")
