"""
Генерация персонализированного отклика на заказ через LLM.

make_draft(order, profile) -> str — питч под конкретный заказ. Из списка
готовых проектов фрилансера выбирает самый близкий к заказу и ссылается на
него как на уже работающее решение (с живой ссылкой на демо), а не «с нуля».
"""
from __future__ import annotations
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from shared.llm import chat

PORTFOLIO_URL = "https://oreopaks.github.io/Portfolio/"
BOT_DEMO_URL = "https://t.me/sdfghjklmvds_bot"

# Профиль фрилансера: реальные ГОТОВЫЕ проекты с живыми демо.
# Под каждый заказ make_draft выберет самый релевантный и сошлётся на него.
PROFILE = {
    "name": "Олег Крючков",
    "role": "Python-разработчик и AI-инженер",
    "portfolio": PORTFOLIO_URL,
    "skills": ["GPT-боты", "n8n-автоматизация", "RAG (поиск по документам с цитатами)", "парсинг/скаут заказов"],
    # name — короткое имя; desc — что делает; ready — что уже готово; link — живое демо.
    "projects": [
        {
            "name": "GPT-бот для бизнеса",
            "desc": "Telegram-бот на GPT отвечает по базе знаний компании 24/7, ведёт запись клиентов",
            "ready": "рабочий бот, можно потыкать прямо сейчас",
            "link": BOT_DEMO_URL,
        },
        {
            "name": "AI-автоматизация на n8n",
            "desc": "заявка с сайта/формы → авто-квалификация лида → CRM + уведомление менеджеру в Telegram",
            "ready": "готовый workflow",
            "link": PORTFOLIO_URL,
        },
        {
            "name": "RAG-ассистент по документам",
            "desc": "отвечает на вопросы по вашим PDF/регламентам со ссылкой на источник-цитату",
            "ready": "рабочий прототип с цитированием",
            "link": PORTFOLIO_URL,
        },
        {
            "name": "Скаут заказов / парсинг",
            "desc": "автомониторинг площадок и сбор данных, выгрузка в Excel/Google Sheets/Telegram",
            "ready": "рабочий скрипт",
            "link": PORTFOLIO_URL,
        },
    ],
}


def _projects_block(profile: dict) -> str:
    return "\n".join(
        f"- {p['name']}: {p['desc']} (готово: {p['ready']}; демо: {p['link']})"
        for p in profile.get("projects", [])
    )


def make_draft(order: dict, profile: dict = PROFILE, focus: int = -1) -> str:
    """Сгенерировать отклик на заказ. Возвращает текст питча.

    focus — индекс продукта в profile["projects"], который оценщик счёл самым
    близким; если задан, отклик ссылается именно на него.
    """
    title = order.get("title", "").strip()
    budget = order.get("budget")
    budget_str = f"{budget} руб" if budget else "по договорённости"

    projects = profile.get("projects", [])
    focus_hint = ""
    if 0 <= focus < len(projects):
        fp = projects[focus]
        focus_hint = (
            f"\nСамый близкий мой готовый продукт под этот заказ: "
            f"«{fp['name']}» (демо: {fp['link']}). Сошлись именно на него."
        )

    system = (
        f"Ты — {profile['name']}, {profile['role']}. "
        "Пишешь короткий цепляющий отклик на заказ фриланс-биржи на русском. "
        "Тон деловой и живой, без воды и канцелярита. 3-5 предложений. "
        "Правила: (1) сошлись на суть заказа; (2) выбери из моих ГОТОВЫХ проектов "
        "самый близкий к этому заказу и упомяни его конкретно как уже работающее "
        "решение, дай ссылку на его демо; (3) в конце предложи следующий шаг. "
        "НЕ выдумывай проектов, которых нет в списке. Если ничего близко не подходит — "
        "честно предложи сделать под задачу, опираясь на близкий опыт."
    )
    user = (
        f"Заказ: «{title}» (бюджет: {budget_str}).\n"
        f"Мои навыки: {', '.join(profile['skills'])}.\n"
        f"Мои готовые проекты с живыми демо:\n{_projects_block(profile)}\n"
        f"Портфолио целиком: {profile['portfolio']}"
        f"{focus_hint}\n"
        "Напиши отклик: покажи заказчику, что у меня уже есть подходящее рабочее "
        "решение со ссылкой, а не начинаю с нуля."
    )
    return chat(system, user, temperature=0.4).strip()
