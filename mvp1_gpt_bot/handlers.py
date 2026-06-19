"""
Чистая, тестируемая логика бота-консультанта кофейни.

Точка входа — handle_message(text, state, kb) -> (reply, new_state).
Без сети и без Telegram: всё детерминировано настолько, насколько детерминирован
выбранный LLM-провайдер (по умолчанию mock).
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime

# Корень проекта в sys.path, чтобы работал `import shared.*` при запуске из любой папки.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import shared.config  # noqa: F401  — побочный эффект: подхватывает .env
from shared.llm import chat

# Куда писать брони. Можно переопределить через переменную окружения (удобно в тестах).
BOOKINGS_CSV = os.environ.get(
    "BOOKINGS_CSV", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.csv")
)

_GREETING_TRIGGERS = ("/start", "привет", "здравств", "добрый", "hi", "hello", "хай")
_BOOKING_TRIGGERS = ("запис", "брон", "столик", "забронир")


def _is_greeting(text: str) -> bool:
    t = text.strip().lower()
    return any(t.startswith(g) or g in t for g in _GREETING_TRIGGERS)


def _is_booking(text: str) -> bool:
    t = text.lower()
    return any(g in t for g in _BOOKING_TRIGGERS)


def save_booking(name: str, when: str) -> str:
    """
    Дописывает строку брони в CSV (создаёт файл с заголовком при первом вызове).
    Возвращает путь к файлу — чтобы тесты могли его проверить.
    """
    path = BOOKINGS_CSV
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["created_at", "name", "when"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), name, when])
    return path


def _greeting_reply(kb: dict) -> str:
    name = kb.get("name", "наша кофейня")
    return (
        f"Привет! Это бот-консультант кофейни «{name}» ☕\n"
        "Я подскажу меню, часы работы и адрес, отвечу на вопросы — "
        "а ещё могу записать вас на столик. Просто напишите, что нужно!\n"
        "Например: «во сколько открываетесь?», «сколько стоит латте?» "
        "или «хочу забронировать столик»."
    )


def _build_system_prompt(kb: dict) -> str:
    name = kb.get("name", "кофейня")
    address = kb.get("address", "")
    hours = kb.get("hours", "")
    phone = kb.get("phone", "")
    menu = kb.get("menu", [])
    faq = kb.get("faq", [])

    menu_lines = "\n".join(f"- {m.get('item')}: {m.get('price')}" for m in menu)
    faq_lines = "\n".join(f"Q: {p.get('q')}\nA: {p.get('a')}" for p in faq)

    return (
        f"Ты — дружелюбный бот-консультант кофейни «{name}». "
        "Отвечай кратко, тепло и по делу, на русском языке. "
        "Используй только сведения ниже; если ответа нет в данных — честно скажи, "
        "что уточнишь у бариста, и предложи позвонить.\n\n"
        f"Адрес: {address}\n"
        f"Телефон: {phone}\n"
        f"Часы работы: {hours}\n\n"
        f"Меню:\n{menu_lines}\n\n"
        f"Частые вопросы:\n{faq_lines}"
    )


def _faq_reply(text: str, kb: dict) -> str:
    system = _build_system_prompt(kb)
    return chat(system, text)


def handle_message(text: str, state: dict, kb: dict) -> tuple[str, dict]:
    """
    Главный обработчик. Возвращает (ответ, новое_состояние).

    state — словарь на чат. Для брони: {"flow": "booking", "step": "name"|"datetime", "name": "..."}.
    Пустой/None state означает отсутствие активного диалога.
    """
    state = dict(state or {})
    text = (text or "").strip()

    # --- 1. Незавершённая бронь имеет приоритет (мы внутри многошагового флоу) ---
    if state.get("flow") == "booking":
        if state.get("step") == "name":
            if not text:
                return ("Подскажите, пожалуйста, ваше имя для брони.", state)
            state["name"] = text
            state["step"] = "datetime"
            return (
                f"Приятно, {text}! На какую дату и время записать столик? "
                "Например: «завтра в 19:00» или «25 июня, 14:30».",
                state,
            )
        if state.get("step") == "datetime":
            if not text:
                return ("На какую дату и время вас записать?", state)
            name = state.get("name", "гость")
            when = text
            save_booking(name, when)
            new_state: dict = {}  # флоу завершён, сбрасываем состояние
            return (
                f"Готово! ✅ Столик забронирован на имя {name}, {when}.\n"
                f"Будем рады видеть вас в «{kb.get('name', 'кофейне')}». "
                "Если планы изменятся — просто напишите.",
                new_state,
            )

    # --- 2. Приветствие / /start ---
    if _is_greeting(text):
        return (_greeting_reply(kb), {})

    # --- 3. Старт брони ---
    if _is_booking(text):
        state = {"flow": "booking", "step": "name"}
        return ("С удовольствием забронирую столик! Как вас зовут?", state)

    # --- 4. Общий вопрос / FAQ через LLM ---
    return (_faq_reply(text, kb), {})
