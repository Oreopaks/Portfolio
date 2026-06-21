"""
MVP6 — AI-SMM-менеджер.

Две половины (как у скаута: дешёвая детерминированная + дорогая LLM):
  • content_plan() — недельный план ДЕТЕРМИНИРОВАННО (ротация рубрик), без LLM;
  • make_post()    — текст поста под платформу через LLM (shared.llm.chat).

Один вход — тема/ниша, на выходе — расписание публикаций + готовые посты с
хэштегами под Telegram / VK / Instagram.

CLI:  python mvp6_smm/smm.py "доставка здоровой еды" telegram
"""
from __future__ import annotations
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from shared.llm import chat

# Рубрики контента: (название, что это). Ротация по дням -> разнообразная лента,
# а не семь однотипных постов.
RUBRICS = [
    ("Польза", "практический совет по теме, который читатель применит сегодня"),
    ("Кейс", "история результата клиента или проекта с конкретными цифрами"),
    ("Закулисье", "как процесс устроен изнутри, по-человечески, без глянца"),
    ("Оффер", "прямое предложение услуги или товара с выгодой и призывом"),
    ("Вовлечение", "вопрос аудитории, который провоцирует комментарии"),
    ("Разбор мифа", "развенчание частого заблуждения по теме"),
    ("Подборка", "список инструментов, идей или ошибок по теме"),
]

# Платформы: правила формата поста.
PLATFORMS = {
    "telegram": "Telegram-канал: 1-3 абзаца, без кликбейта, эмодзи умеренно, ссылка/CTA в конце",
    "vk": "ВКонтакте: 1-2 абзаца, дружелюбный тон, 3-5 хэштегов в конце",
    "instagram": "Instagram: крючок в первой строке, короткие абзацы, 5-10 хэштегов, эмодзи",
}


def content_plan(topic: str, days: int = 7) -> list[dict]:
    """Недельный контент-план (детерминированно, без LLM): ротация рубрик по дням.

    -> [{"day","rubric","idea"}]. days клампится в [1..14].
    """
    if not topic or not topic.strip():
        raise ValueError("пустая тема")
    topic = topic.strip()
    days = max(1, min(14, days))
    out: list[dict] = []
    for i in range(days):
        name, brief = RUBRICS[i % len(RUBRICS)]
        out.append({"day": i + 1, "rubric": name, "idea": f"{name} по теме «{topic}»: {brief}"})
    return out


def make_post(idea: str, platform: str = "telegram", topic: str = "") -> str:
    """Сгенерировать текст поста под платформу через LLM. Неизвестная платформа -> telegram."""
    spec = PLATFORMS.get(platform, PLATFORMS["telegram"])
    system = (
        f"Ты SMM-специалист. Пишешь пост на русском строго под формат платформы: {spec}. "
        "Без воды и канцелярита, текст готов к публикации."
    )
    user = f"Тема канала: {topic}. Сделай пост по идее: {idea}"
    return chat(system, user, temperature=0.7).strip()


def week(topic: str, platform: str = "telegram") -> list[dict]:
    """Полный недельный план с готовыми постами: content_plan + make_post на каждый день."""
    plan = content_plan(topic, 7)
    for p in plan:
        p["post"] = make_post(p["idea"], platform, topic)
    return plan


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "доставка здоровой еды"
    platform = sys.argv[2] if len(sys.argv) > 2 else "telegram"
    for p in content_plan(topic, 7):
        print(f"День {p['day']} · {p['rubric']}: {p['idea']}")
    print("\n--- пример поста (день 1) ---")
    print(make_post(content_plan(topic, 1)[0]["idea"], platform, topic))
