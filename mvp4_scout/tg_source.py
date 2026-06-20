"""
Источник заказов: Telegram-каналы (биржи фриланса, чаты с заказами).

Использует Telethon. Зависимость ОПЦИОНАЛЬНА: если telethon не установлен,
fetch_tg_orders() логирует предупреждение и возвращает [] — код продолжает жить.

Нужны TG_API_ID / TG_API_HASH из env (https://my.telegram.org).
"""
from __future__ import annotations
import os

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    _HAS_TELETHON = True
except ImportError:
    TelegramClient = None
    StringSession = None
    _HAS_TELETHON = False


def fetch_tg_orders(channels, limit: int = 30) -> list[dict]:
    """Читает последние сообщения каналов -> [{"title","budget"(None),"url"}].

    Бюджет из свободного текста не вычисляем (оставляем None — пусть решает
    фильтр по ключевым словам). Если telethon/креды отсутствуют — возвращаем [].
    """
    if not _HAS_TELETHON:
        print("[tg] telethon не установлен — пропускаю Telegram-источник")
        return []

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        print("[tg] TG_API_ID / TG_API_HASH не заданы — пропускаю Telegram-источник")
        return []

    session_str = os.environ.get("TG_SESSION", "")
    if not session_str:
        # Без сохранённой сессии Telethon ушёл бы в интерактивный логин (запрос телефона).
        # В CI/без сессии просто пропускаем — заказы берутся из FL.ru.
        print("[tg] TG_SESSION пуст — пропускаю Telegram-источник (нужен gen_session.py)")
        return []

    # StringSession в env, чтобы не таскать .session-файл в CI.
    session = StringSession(session_str)
    orders: list[dict] = []

    with TelegramClient(session, int(api_id), api_hash) as client:
        for ch in channels:
            try:
                entity = client.get_entity(ch)
                for msg in client.iter_messages(entity, limit=limit):
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    title = text.replace("\n", " ")[:90].strip()
                    uname = getattr(entity, "username", None)
                    url = (
                        f"https://t.me/{uname}/{msg.id}"
                        if uname
                        else f"tg://msg?id={msg.id}"
                    )
                    orders.append({"title": title, "budget": None, "url": url})
            except Exception as e:
                print(f"[tg] ошибка чтения канала {ch}: {e}")
    return orders
