"""
Telegram-бот кофейни «Кофе Капля» на long-polling (без вебхуков, без библиотек-обёрток).

Запуск:
    export TELEGRAM_BOT_TOKEN=...   # токен от @BotFather
    export LLM_PROVIDER=mock        # или gigachat / yandex (с ключами в .env)
    python mvp1_gpt_bot/bot.py
"""
from __future__ import annotations

import json
import os
import sys

# Корень проекта в sys.path — для `import shared.*` при запуске из любой папки.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import shared.config  # noqa: F401 — подхватывает .env при импорте
import requests

from handlers import handle_message

_HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.telegram.org"


def load_kb() -> dict:
    with open(os.path.join(_HERE, "knowledge.json"), encoding="utf-8") as f:
        return json.load(f)


def get_updates(token: str, offset: int | None) -> list[dict]:
    """Один цикл long-polling getUpdates."""
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"{API}/bot{token}/getUpdates", params=params, timeout=40)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates error: {data}")
    return data.get("result", [])


def send_message(token: str, chat_id: int, text: str) -> None:
    requests.post(
        f"{API}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print(
            "TELEGRAM_BOT_TOKEN не задан.\n"
            "Получите токен у @BotFather в Telegram и задайте переменную окружения:\n"
            "  export TELEGRAM_BOT_TOKEN=123456:ABC...\n"
            "(или впишите её в файл .env в корне проекта)."
        )
        sys.exit(1)

    kb = load_kb()
    states: dict[int, dict] = {}  # state на каждый chat_id (в памяти)
    offset: int | None = None

    print(f"Бот «{kb.get('name')}» запущен. LLM-провайдер:", os.environ.get("LLM_PROVIDER", "mock"))
    print("Ожидаю сообщения... (Ctrl+C для остановки)")

    while True:
        try:
            updates = get_updates(token, offset)
        except KeyboardInterrupt:
            print("\nОстановлено.")
            return
        except Exception as e:  # сетевые сбои не должны ронять бота
            print("Ошибка getUpdates, повтор:", e)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg or "text" not in msg:
                continue
            chat_id = msg["chat"]["id"]
            text = msg["text"]
            try:
                reply, states[chat_id] = handle_message(text, states.get(chat_id, {}), kb)
            except Exception as e:
                print("Ошибка обработки сообщения:", e)
                reply = "Упс, что-то пошло не так. Попробуйте ещё раз или позвоните нам."
            send_message(token, chat_id, reply)


if __name__ == "__main__":
    main()
