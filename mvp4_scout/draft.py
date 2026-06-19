"""
Генерация персонализированного отклика на заказ через LLM.

make_draft(order, profile) -> str — питч под конкретный заказ, ссылается на
заголовок заказа и навыки/кейсы фрилансера из profile.
"""
from __future__ import annotations
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from shared.llm import chat

# Профиль фрилансера по умолчанию: код + AI.
PROFILE = {
    "name": "Олег",
    "role": "Python-разработчик и AI-инженер",
    "skills": ["GPT-боты", "n8n-автоматизация", "RAG (поиск по документам)", "парсинг сайтов"],
    "cases": [
        "Telegram-бот на GPT для поддержки клиентов (отвечает по базе знаний)",
        "n8n-сценарий: заявки с сайта -> CRM -> уведомления в Telegram",
        "RAG-система: вопросы по PDF-документам компании с ссылками на источник",
        "парсер бирж фриланса с авто-откликами",
    ],
    "demos": "Есть живые демо всех решений — могу показать в работе перед стартом.",
}


def make_draft(order: dict, profile: dict = PROFILE) -> str:
    """Сгенерировать отклик на заказ. Возвращает текст питча."""
    title = order.get("title", "").strip()
    budget = order.get("budget")
    budget_str = f"{budget} руб" if budget else "по договорённости"

    system = (
        f"Ты — {profile['name']}, {profile['role']}. "
        "Пишешь короткий цепляющий отклик на заказ фриланс-биржи на русском. "
        "Тон деловой, без воды и канцелярита. 3-5 предложений. "
        "Сошлись на суть заказа, покажи релевантный опыт и предложи следующий шаг."
    )
    user = (
        f"Заказ: «{title}» (бюджет: {budget_str}).\n"
        f"Мои навыки: {', '.join(profile['skills'])}.\n"
        f"Мои кейсы: {'; '.join(profile['cases'])}.\n"
        f"Важно: {profile['demos']}\n"
        "Напиши отклик заказчику."
    )
    return chat(system, user, temperature=0.4).strip()
