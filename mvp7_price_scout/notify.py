"""Отправка сообщений админам бота (для алертов collector'а). Без токена — в консоль."""
from __future__ import annotations

import os

import requests

API = "https://api.telegram.org"


def admin_ids() -> list[str]:
    return [a.strip() for a in os.environ.get("PRICE_BOT_ADMINS", "").split(",") if a.strip()]


def send_admins(text: str) -> None:
    """Разослать текст всем админам. Если нет токена/админов — печать в консоль."""
    token = os.environ.get("PRICE_BOT_TOKEN")
    admins = admin_ids()
    if not token or not admins:
        print("[notify] нет PRICE_BOT_TOKEN/PRICE_BOT_ADMINS — алерт в консоль:\n" + text + "\n")
        return
    for chat in admins:
        try:
            r = requests.post(
                f"{API}/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000],
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=20,
            )
            if not r.ok:   # Telegram 4xx не кидает исключение — иначе сбой был бы немым
                print(f"[notify] {chat} не дошло: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"[notify] ошибка отправки {chat}: {e}")
