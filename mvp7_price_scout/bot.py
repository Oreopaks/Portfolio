"""
Telegram-бот сравнения цен (long-poll на голом requests, как mvp1_gpt_bot/bot.py).

Отвечает мгновенно из SQLite (сбор делает collector по расписанию). Запуск:
    export PRICE_BOT_TOKEN=...        # отдельный бот @BotFather (НЕ слитый токен!)
    export PRICE_BOT_ADMINS=12345     # chat_id админов (узнать командой /id)
    python -m mvp7_price_scout.bot
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень репо (freelance-mvp)
import shared.config  # noqa: F401 — подхватывает .env

import requests

from mvp7_price_scout import handlers, store

API = "https://api.telegram.org"


def _admins() -> set[str]:
    return {a.strip() for a in os.environ.get("PRICE_BOT_ADMINS", "").split(",") if a.strip()}


def get_updates(token: str, offset: int | None) -> list[dict]:
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"{API}/bot{token}/getUpdates", params=params, timeout=40)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates: {data}")
    return data.get("result", [])


def send_message(token: str, chat_id: int, text: str, buttons: list | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:   # [(подпись, callback_data)] -> по кнопке на строку (названия длинные)
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": b[0], "callback_data": b[1]}] for b in buttons]
        }
    try:
        r = requests.post(f"{API}/bot{token}/sendMessage", json=payload, timeout=30)
        if r.status_code == 400 and "parse" in r.text.lower():
            # битый HTML (обрезка text[:4000] могла порвать тег) — доставить хоть текстом
            payload.pop("parse_mode", None)
            r = requests.post(f"{API}/bot{token}/sendMessage", json=payload, timeout=30)
        if not r.ok:   # 400 (битый HTML), 403 (бот заблокан) — иначе ответ молча терялся
            print(f"[bot] sendMessage -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[bot] sendMessage -> {chat_id} ошибка сети: {e}")


def edit_message(token: str, chat_id: int, message_id: int, text: str,
                 buttons: list | None = None) -> None:
    """Отредактировать текст сообщения (живой статус-бар — не плодим новые)."""
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": b[0], "callback_data": b[1]}] for b in buttons]
        }
    try:
        r = requests.post(f"{API}/bot{token}/editMessageText", json=payload, timeout=30)
        # «message is not modified» (прогресс не изменился между тапами) — это не ошибка
        if not r.ok and "not modified" not in r.text.lower():
            print(f"[bot] editMessageText -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[bot] editMessageText -> {chat_id} ошибка сети: {e}")


def answer_callback(token: str, cb_id: str) -> None:
    """Погасить «часики» на нажатой inline-кнопке (иначе клиент висит ~15с)."""
    try:
        requests.post(f"{API}/bot{token}/answerCallbackQuery",
                      json={"callback_query_id": cb_id}, timeout=15)
    except Exception as e:
        print(f"[bot] answerCallbackQuery ошибка: {e}")


def send_document(token: str, chat_id: int, path: str, caption: str = "",
                  filename: str = "Сравнение_цен.xlsx",
                  mime: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") -> None:
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{API}/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (filename, f, mime)},
                timeout=60,
            )
        if not r.ok:
            print(f"[bot] sendDocument -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[bot] sendDocument -> {chat_id} ошибка сети: {e}")


def main() -> None:
    token = os.environ.get("PRICE_BOT_TOKEN")
    if not token:
        print("PRICE_BOT_TOKEN не задан. Получи токен у @BotFather и впиши в .env "
              "(PRICE_BOT_TOKEN=...). Не используй ранее слитый токен — отзови его /revoke.")
        sys.exit(1)

    admins = _admins()
    conn = store.connect()
    offset: int | None = None
    print("Бот сравнения цен запущен. Админы:", admins or "(не заданы — /id покажет chat_id)")

    while True:
        try:
            updates = get_updates(token, offset)
        except KeyboardInterrupt:
            print("\nОстановлено.")
            return
        except Exception as e:  # сетевые сбои не должны ронять бота
            print("Ошибка getUpdates, повтор:", e)
            time.sleep(3)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1

            cb = upd.get("callback_query")               # тап по inline-кнопке (подсказка/цвет/статус)
            if cb:
                answer_callback(token, cb["id"])
                data = cb.get("data", "")
                try:
                    reply = handlers.handle_callback(conn, data)
                except Exception as e:
                    print("Ошибка callback:", e)
                    reply = None
                if reply and cb.get("message"):
                    m = cb["message"]
                    if data == "status":     # статус-бар: обновляем ТО ЖЕ сообщение, не плодим новые
                        edit_message(token, m["chat"]["id"], m["message_id"], reply.text, reply.buttons)
                    else:
                        send_message(token, m["chat"]["id"], reply.text, reply.buttons)
                continue

            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]
            text = msg.get("text") or msg.get("caption")   # подпись к фото — тоже запрос
            if not text:                                   # стикер/voice — не молчим
                send_message(token, chat_id,
                             "Пришли название товара текстом, например: "
                             "<code>iphone 17 pro 256</code>")
                continue
            is_admin = str(chat_id) in admins
            if text.strip().lower() == "/id":            # помощь в настройке админов
                send_message(token, chat_id, f"Твой chat_id: <code>{chat_id}</code>")
                continue
            if text.strip().lower().startswith("/export"):
                if not is_admin:   # полная ценовая аналитика — не для чужих глаз
                    send_message(token, chat_id, "Команда /export доступна только администратору.")
                    continue
                path = None
                try:
                    path = handlers.build_export_xlsx(conn)
                    send_document(token, chat_id, path, "Сравнение цен Di-Park vs конкуренты")
                except Exception as e:
                    print("Ошибка /export:", e)
                    send_message(token, chat_id, "Не удалось сформировать выгрузку.")
                finally:
                    if path:
                        try:
                            os.unlink(path)              # не копить xlsx в /tmp
                        except OSError:
                            pass
                continue
            try:
                reply = handlers.handle_text(conn, text, is_admin)
            except Exception as e:
                print("Ошибка обработки:", e)
                reply = handlers.Reply("Упс, что-то пошло не так. Попробуй ещё раз.")
            send_message(token, chat_id, reply.text, reply.buttons)


if __name__ == "__main__":
    main()
