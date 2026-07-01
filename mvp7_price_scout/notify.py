"""Отправка сообщений админам бота (для алертов collector'а). Без токена — в консоль."""
from __future__ import annotations

import os

import requests

API = "https://api.telegram.org"


def admin_ids() -> list[str]:
    return [a.strip() for a in os.environ.get("PRICE_BOT_ADMINS", "").split(",") if a.strip()]


def _chunks(text: str, limit: int = 4000) -> list[str]:
    """Нарезать текст на части <= limit ПО границам строк.

    Наивный text[:4000] рвёт HTML-тег на границе -> Telegram 400 «can't parse
    entities» -> вся пачка алертов не доходит. Режем по '\\n' (алерты разделены
    пустыми строками), сохраняя теги целыми.
    """
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    cur = ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return [c[:limit] for c in out]      # страховка на сверхдлинную одиночную строку


def send_admins(text: str) -> None:
    """Разослать текст всем админам. Если нет токена/админов — печать в консоль."""
    token = os.environ.get("PRICE_BOT_TOKEN")
    admins = admin_ids()
    if not token or not admins:
        print("[notify] нет PRICE_BOT_TOKEN/PRICE_BOT_ADMINS — алерт в консоль:\n" + text + "\n")
        return
    for chat in admins:
        for part in _chunks(text):
            try:
                r = requests.post(
                    f"{API}/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": part,
                          "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=20,
                )
                if not r.ok:   # Telegram 4xx не кидает исключение — иначе сбой был бы немым
                    print(f"[notify] {chat} не дошло: {r.status_code} {r.text[:200]}")
            except Exception as e:
                print(f"[notify] ошибка отправки {chat}: {e}")
