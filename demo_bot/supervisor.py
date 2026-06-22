"""
Супервизор витрины: один процесс держит несколько Telegram-ботов, по одному на продукт.

Каждый бот = свой токен от @BotFather и свой продукт:
    cafe (TELEGRAM_BOT_TOKEN) — MVP1 кофейня (полный диалог + бронь)
    lead (KRYU_LEAD_TOKEN)     — MVP2 квалификация заявки
    rag  (KRYU_RAG_TOKEN)      — MVP3 поиск по документам
    copy (KRYU_COPY_TOKEN)     — MVP5 копирайтер
    smm  (KRYU_SMM_TOKEN)      — MVP6 SMM-менеджер

Telegram разрешает только одного getUpdates-консьюмера на токен, поэтому
каждый бот крутит свой long-polling в отдельном потоке (свой offset + состояние).
Один процесс -> одна запись в cron-watchdog (run_bot.sh).

Сеть/KB переиспользуются из mvp1_gpt_bot/bot.py, форматирование демо — из showcase.py.

Запуск:
    python demo_bot/supervisor.py
Токены берутся из .env (см. .env.example).
"""
from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MVP1 = os.path.join(_ROOT, "mvp1_gpt_bot")
for _p in (_ROOT, _MVP1):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shared.config  # noqa: F401 — подхватывает .env при импорте

from bot import get_updates, send_message, load_kb  # mvp1_gpt_bot/bot.py — переиспользуем сеть+KB
from handlers import handle_message                  # MVP1 кофейня
from demo_bot.showcase import _safe_run, _PROMPTS    # MVP2/3/5/6 демо-логика

# (env-переменная токена, вид продукта). Вид cafe -> полный диалог кофейни,
# остальные -> любой текст прогоняется через соответствующее демо.
BOTS = [
    ("TELEGRAM_BOT_TOKEN", "cafe"),
    ("KRYU_LEAD_TOKEN", "lead"),
    ("KRYU_RAG_TOKEN", "rag"),
    ("KRYU_COPY_TOKEN", "copy"),
    ("KRYU_SMM_TOKEN", "smm"),
]

# Текст на /start, пустое сообщение или приветствие у продуктовых ботов.
_INTRO_TRIGGERS = ("/start", "start", "/help", "help", "/menu", "меню", "привет", "hi", "hello")


def make_cafe_handler(kb: dict):
    def handler(text: str, state: dict):
        return handle_message(text, state, kb)
    return handler


def make_product_handler(kind: str):
    """Весь бот = один продукт: любой текст -> демо, /start -> подсказка."""
    def handler(text: str, state: dict):
        t = (text or "").strip()
        if not t or t.lower() in _INTRO_TRIGGERS:
            return _PROMPTS[kind], {}
        return _safe_run(kind, t), {}
    return handler


def run_bot(name: str, token: str, handler) -> None:
    """Long-polling одного бота. Свой offset и состояние на чат."""
    offset: int | None = None
    states: dict[int, dict] = {}
    print(f"[{name}] запущен")
    while True:
        try:
            updates = get_updates(token, offset)
        except Exception as e:  # сетевой сбой не должен ронять поток
            print(f"[{name}] getUpdates ошибка, повтор:", e)
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg or "text" not in msg:
                continue
            chat_id = msg["chat"]["id"]
            text = msg["text"]
            try:
                reply, states[chat_id] = handler(text, states.get(chat_id, {}))
            except Exception as e:
                print(f"[{name}] ошибка обработки:", e)
                reply = "Упс, что-то пошло не так. Попробуйте ещё раз."
            send_message(token, chat_id, reply)


def main() -> None:
    kb = load_kb()
    cafe = make_cafe_handler(kb)

    started: list[str] = []
    for env, kind in BOTS:
        token = os.environ.get(env)
        if not token:
            print(f"[{kind}] {env} не задан — пропуск")
            continue
        handler = cafe if kind == "cafe" else make_product_handler(kind)
        threading.Thread(target=run_bot, args=(kind, token, handler), daemon=True).start()
        started.append(kind)

    if not started:
        print("Ни одного токена не задано — нечего запускать.")
        sys.exit(1)

    print("Супервизор витрины поднят. LLM:", os.environ.get("LLM_PROVIDER", "mock"),
          "| боты:", ", ".join(started))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
