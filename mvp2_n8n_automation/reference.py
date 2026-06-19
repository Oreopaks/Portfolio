"""
MVP2 — AI lead-automation: эталонная Python-реализация пайплайна.

Тот же конвейер, что и в workflow.json (n8n), но запускается и тестируется
без n8n. Логика квалификации ДЕТЕРМИНИРОВАНА (rule-based) — стабильно для тестов.
LLM используется ТОЛЬКО для человекочитаемой заметки/next-action.

Пайплайн: входящий лид -> score_lead (правила) -> categorize (hot/warm/cold)
        -> routed_to (маршрут) -> note (через shared.llm.chat).

Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp2_n8n_automation/reference.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Чтобы reference.py работал и при прямом запуске (python reference.py),
# и как модуль (python -m ...): добавляем корень проекта в sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared.config  # noqa: E402,F401  — подхватывает .env при импорте
from shared.llm import chat  # noqa: E402

# Ключевые слова срочности (lowercase). Совпадение -> +баллы.
URGENCY_KEYWORDS = ("срочно", "сегодня", "asap", "немедленно", "сейчас")

SYSTEM_PROMPT = (
    "Ты ассистент отдела продаж. По краткой сводке лида напиши ОДНО короткое "
    "предложение на русском: как лучше всего связаться и что предложить. "
    "Без воды, по делу."
)

ROUTES = {
    "hot": "sales_call",
    "warm": "email_nurture",
    "cold": "newsletter",
}


def score_lead(lead: dict) -> int:
    """Rule-based скоринг 0..100.

    Баллы:
      - бюджет: >=50000 -> +50; >=10000 -> +25; иначе 0
      - срочность: любое ключевое слово в name/message -> +30
      - контакты: телефон -> +10, email -> +10
    """
    score = 0

    budget = lead.get("budget", 0) or 0
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        budget = 0
    if budget >= 50000:
        score += 50
    elif budget >= 10000:
        score += 25

    text = " ".join(
        str(lead.get(k, "")) for k in ("name", "message", "subject")
    ).lower()
    if any(kw in text for kw in URGENCY_KEYWORDS):
        score += 30

    if str(lead.get("phone", "")).strip():
        score += 10
    if str(lead.get("email", "")).strip():
        score += 10

    return min(score, 100)


def categorize(score: int) -> str:
    """Порог: >=70 hot, >=40 warm, иначе cold."""
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"


def _lead_summary(lead: dict) -> str:
    """Краткая сводка лида для LLM."""
    return (
        f"Имя: {lead.get('name', '—')}. "
        f"Бюджет: {lead.get('budget', '—')}. "
        f"Контакты: {lead.get('phone', '—')} / {lead.get('email', '—')}. "
        f"Сообщение: {lead.get('message', '—')}"
    )


def process_lead(lead: dict) -> dict:
    """Полный прогон одного лида через пайплайн."""
    score = score_lead(lead)
    category = categorize(score)
    routed_to = ROUTES[category]
    note = chat(SYSTEM_PROMPT, _lead_summary(lead))
    return {
        "lead": lead,
        "score": score,
        "category": category,
        "routed_to": routed_to,
        "note": note,
    }


if __name__ == "__main__":
    demo_leads = [
        {
            "name": "ООО Ромашка (срочно)",
            "budget": 120000,
            "phone": "+7 999 123-45-67",
            "email": "ceo@romashka.ru",
            "message": "Нужен лендинг СРОЧНО, бюджет есть, готовы стартовать сегодня",
        },
        {
            "name": "Иван Петров",
            "budget": 15000,
            "phone": "",
            "email": "ivan@example.com",
            "message": "Думаю над сайтом-визиткой, присматриваюсь",
        },
        {
            "name": "Аноним",
            "budget": 0,
            "phone": "",
            "email": "",
            "message": "А сколько у вас стоит логотип?",
        },
    ]

    print("=== MVP2 lead-automation (reference.py) ===\n")
    for lead in demo_leads:
        result = process_lead(lead)
        print(f"Лид:       {result['lead']['name']}")
        print(f"Score:     {result['score']}")
        print(f"Category:  {result['category']}")
        print(f"Routed to: {result['routed_to']}")
        print(f"Note:      {result['note']}")
        print("-" * 60)
