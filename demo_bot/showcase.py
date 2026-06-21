"""
Портфолио-витрина для Telegram — одна точка, где клиент пробует ЖИВЬЁМ
продукты, у которых иначе только CLI/референс:
  /copy — AI-копирайтер (MVP5)   /smm  — AI-SMM (MVP6)
  /rag  — поиск по документам (MVP3)   /lead — квалификация заявки (MVP2)

handle_demo(text, state) -> (reply, new_state) | None
    None  => текст не относится к витрине -> обработает основной бот.

Чистый диспетчер: Telegram-сети нет, тестируется офлайн (mock-LLM).
"""
from __future__ import annotations
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (
    _ROOT,
    f"{_ROOT}/mvp5_copywriter",
    f"{_ROOT}/mvp6_smm",
    f"{_ROOT}/mvp3_rag",
    f"{_ROOT}/mvp2_n8n_automation",
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shared.config  # noqa: F401  — подхватывает .env
from copywriter import generate            # MVP5
from smm import content_plan, make_post    # MVP6
from rag import answer as rag_answer        # MVP3
from reference import process_lead          # MVP2

_CMDS = ("copy", "smm", "rag", "lead")

MENU = (
    "🧪 Витрина решений — потыкай живьём:\n\n"
    "✍️ /copy — AI-копирайтер (тема → продающий текст)\n"
    "📣 /smm — AI-SMM (тема → контент-план + пост)\n"
    "📚 /rag — поиск по документам (вопрос → ответ с цитатой)\n"
    "🎯 /lead — квалификация заявки (текст → горячность лида)\n\n"
    "Можно сразу с аргументом: «/copy кофейня, акция на раф»."
)
_PROMPTS = {
    "copy": "✍️ Пришли тему/бриф — напишу продающий пост.\nНапр.: кофейня в центре, акция на раф-кофе",
    "smm": "📣 Пришли тему канала — соберу контент-план на неделю + пример поста.\nНапр.: доставка здоровой еды",
    "rag": "📚 Задай вопрос по демо-базе — отвечу с цитатой источника.\nНапр.: какой срок гарантии?",
    "lead": "🎯 Пришли текст заявки клиента — оценю горячность и маршрут.\nНапр.: Нужен лендинг срочно, бюджет 120000, тел +79991234567",
}


def _text_to_lead(text: str) -> dict:
    """Свободный текст заявки -> dict под reference.process_lead."""
    m = re.search(r"(\d[\d\s]{3,}\d)", text)
    budget = int(re.sub(r"\D", "", m.group(1))) if m else 0
    phone = "+x" if re.search(r"\+?\d[\d\s\-]{7,}", text) else ""
    email = "x@x" if re.search(r"\S+@\S+\.\S+", text) else ""
    return {"name": text[:40], "message": text, "budget": budget, "phone": phone, "email": email}


def _run(cmd: str, arg: str) -> str:
    arg = arg.strip()
    if cmd == "copy":
        return "✍️ AI-копирайтер:\n\n" + generate("post", arg)
    if cmd == "smm":
        plan = content_plan(arg, 7)
        lines = "\n".join(f"День {p['day']} · {p['rubric']}" for p in plan)
        post = make_post(plan[0]["idea"], "telegram", arg)
        return f"📣 Контент-план «{arg}»:\n{lines}\n\n— Пример поста (день 1):\n{post}"
    if cmd == "rag":
        res = rag_answer(arg)
        src = res.get("sources") or []
        cite = f"\n\n📎 Источник: {src[0].get('doc', '?')}" if src else ""
        return "📚 Ответ по документам:\n\n" + str(res.get("answer", "")) + cite
    if cmd == "lead":
        r = process_lead(_text_to_lead(arg))
        emoji = {"hot": "🔥", "warm": "🌤", "cold": "🥶"}.get(r["category"], "")
        return (
            f"🎯 Квалификация заявки:\n\n{emoji} {r['category'].upper()} "
            f"(score {r['score']}/100)\nМаршрут: {r['routed_to']}\n"
            f"Рекомендация: {r['note']}"
        )
    return "Не понял команду."


def _safe_run(cmd: str, arg: str) -> str:
    try:
        return _run(cmd, arg)
    except Exception as e:  # одно упавшее демо не должно ронять бота
        return f"⚠️ Демо «{cmd}» не отработало: {e}"


def handle_demo(text: str, state: dict) -> tuple[str, dict] | None:
    """Роутер витрины. None => не наша команда (пусть решает основной бот)."""
    state = dict(state or {})
    t = (text or "").strip()
    low = t.lower()

    if low in ("/demo", "демо", "/menu", "меню", "витрина"):
        return MENU, {}

    if t.startswith("/"):
        parts = t[1:].split(None, 1)
        cmd = parts[0].lower()
        if cmd in _CMDS:
            arg = parts[1].strip() if len(parts) > 1 else ""
            if not arg:
                return _PROMPTS[cmd], {"demo": cmd}
            return _safe_run(cmd, arg), {}
        return None  # другая /команда — не витрина

    # продолжение флоу витрины: ждём аргумент простым текстом
    if state.get("demo") in _CMDS and t:
        return _safe_run(state["demo"], t), {}

    return None
