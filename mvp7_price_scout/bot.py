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
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень репо (freelance-mvp)
import shared.config  # noqa: F401 — подхватывает .env

import requests

from mvp7_price_scout import handlers, notify, store

API = "https://api.telegram.org"
_OFFSET_FILE = Path(__file__).resolve().parent / ".bot_offset"


def _load_offset() -> int | None:
    """offset getUpdates из файла — переживает рестарт (cron перезапускает бота).

    Без персиста рестарт зовёт getUpdates(None) и Telegram переотдаёт последнюю
    неподтверждённую пачку -> дубли ответов на старые сообщения.
    """
    try:
        return int(_OFFSET_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_FILE.write_text(str(offset))
    except OSError:
        pass


def _post(token: str, method: str, tries: int = 2, timeout: int = 30, **kwargs):
    """POST к Telegram с ретраем на сетевой сбой и паузой на 429 flood-control.

    Возвращает Response или None (сеть недоступна после ретраев). 4xx отдаём как
    есть — вызывающий решает (битый HTML -> повтор без parse_mode).
    """
    for attempt in range(tries):
        try:
            r = requests.post(f"{API}/bot{token}/{method}", timeout=timeout, **kwargs)
        except Exception as e:
            print(f"[bot] {method} сеть, попытка {attempt + 1}/{tries}: {e}")
            time.sleep(1)
            continue
        if r.status_code == 429:                # flood control — подождать retry_after и повторить
            try:
                retry = r.json().get("parameters", {}).get("retry_after", 1)
            except Exception:
                retry = 1
            print(f"[bot] {method} 429, пауза {retry}s")
            time.sleep(min(retry, 30))
            continue
        return r
    return None


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


def _markup(buttons: list) -> dict:
    return {"inline_keyboard": [[{"text": b[0], "callback_data": b[1]}] for b in buttons]}


def send_message(token: str, chat_id: int, text: str, buttons: list | None = None) -> None:
    # длинный ответ -> несколько сообщений по границам строк (не режем хвост молча)
    parts = notify._chunks(text)
    for i, part in enumerate(parts):
        payload = {"chat_id": chat_id, "text": part,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons and i == len(parts) - 1:   # кнопки — на последней части
            payload["reply_markup"] = _markup(buttons)
        r = _post(token, "sendMessage", json=payload)
        if r is None:
            continue
        if r.status_code == 400 and ("parse" in r.text.lower() or "entities" in r.text.lower()):
            payload.pop("parse_mode", None)    # битый HTML — доставить хоть текстом
            r = _post(token, "sendMessage", json=payload)
        if r is not None and not r.ok:   # 403 (бот заблокан) и пр. — иначе ответ молча терялся
            print(f"[bot] sendMessage -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")


def edit_message(token: str, chat_id: int, message_id: int, text: str,
                 buttons: list | None = None) -> None:
    """Отредактировать текст сообщения (живой статус-бар — не плодим новые)."""
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = _markup(buttons)
    r = _post(token, "editMessageText", json=payload)
    if r is None:
        return
    # «message is not modified» (прогресс не изменился между тапами) — это не ошибка
    if not r.ok and "not modified" not in r.text.lower():
        print(f"[bot] editMessageText -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")


def answer_callback(token: str, cb_id: str) -> None:
    """Погасить «часики» на нажатой inline-кнопке (иначе клиент висит ~15с)."""
    _post(token, "answerCallbackQuery", tries=1, timeout=15,
          json={"callback_query_id": cb_id})


def set_commands(token: str) -> None:
    """Меню команд (кнопка «/» в клиенте) — иначе команды надо помнить наизусть."""
    cmds = [
        {"command": "start", "description": "Как пользоваться ботом"},
        {"command": "help", "description": "Команды и примеры запросов"},
        {"command": "top", "description": "Где мы дороже конкурентов"},
        {"command": "stats", "description": "Наша позиция на рынке"},
        {"command": "status", "description": "Прогресс обновления цен"},
        {"command": "export", "description": "Выгрузка сравнения в Excel (админ)"},
    ]
    _post(token, "setMyCommands", tries=1, json={"commands": cmds})


def send_document(token: str, chat_id: int, path: str, caption: str = "",
                  filename: str = "Сравнение_цен.xlsx",
                  mime: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") -> None:
    # tries=1: файл открыт один раз, ретрай на исчерпанном потоке отправил бы пустое
    try:
        with open(path, "rb") as f:
            r = _post(token, "sendDocument", tries=1, timeout=60,
                      data={"chat_id": chat_id, "caption": caption},
                      files={"document": (filename, f, mime)})
    except Exception as e:
        print(f"[bot] sendDocument -> {chat_id} ошибка: {e}")
        return
    if r is not None and not r.ok:
        print(f"[bot] sendDocument -> {chat_id} не дошло: {r.status_code} {r.text[:200]}")


def _export_async(token: str, chat_id: int) -> None:
    """Сборка xlsx в отдельном потоке (своё соединение) — не блокирует остальных клиентов.

    build_export_xlsx только читает; WAL допускает параллельное чтение с главным
    соединением бота. sqlite-connection не шарится между потоками -> открываем своё.
    """
    conn = store.connect()
    path = None
    try:
        path = handlers.build_export_xlsx(conn)
        send_document(token, chat_id, path, "Сравнение цен Di-Park vs конкуренты")
    except Exception as e:
        print(f"[bot] /export: {e}")
        send_message(token, chat_id, "Не удалось сформировать выгрузку.")
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        conn.close()


def _handle_update(token: str, conn, admins: set, upd: dict) -> None:
    """Обработать один апдейт. Вынесено, чтобы главный цикл обернул это в try/except
    и один битый апдейт (неожиданная структура и т.п.) не ронял весь бот."""
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
        return

    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = msg.get("text") or msg.get("caption")   # подпись к фото — тоже запрос
    if not text:                                   # стикер/voice — не молчим
        send_message(token, chat_id,
                     "Пришли название товара текстом, например: "
                     "<code>iphone 17 pro 256</code>")
        return
    is_admin = str(chat_id) in admins
    if text.strip().lower() == "/id":            # помощь в настройке админов
        send_message(token, chat_id, f"Твой chat_id: <code>{chat_id}</code>")
        return
    if text.strip().lower().startswith("/export"):
        if not is_admin:   # полная ценовая аналитика — не для чужих глаз
            send_message(token, chat_id, "Команда /export доступна только администратору.")
            return
        # сборка xlsx медленная -> в отдельный поток, иначе блокирует всех клиентов
        send_message(token, chat_id, "Готовлю выгрузку, пришлю файлом через минуту…")
        threading.Thread(target=_export_async, args=(token, chat_id), daemon=True).start()
        return
    try:
        reply = handlers.handle_text(conn, text, is_admin)
    except Exception as e:
        print("Ошибка обработки:", e)
        reply = handlers.Reply("Упс, что-то пошло не так. Попробуй ещё раз.")
    send_message(token, chat_id, reply.text, reply.buttons)


def main() -> None:
    token = os.environ.get("PRICE_BOT_TOKEN")
    if not token:
        print("PRICE_BOT_TOKEN не задан. Получи токен у @BotFather и впиши в .env "
              "(PRICE_BOT_TOKEN=...). Не используй ранее слитый токен — отзови его /revoke.")
        sys.exit(1)

    admins = _admins()
    conn = store.connect()
    set_commands(token)                 # меню «/» в клиенте
    offset = _load_offset()             # переживает рестарт (cron перезапускает бота)
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
            try:
                _handle_update(token, conn, admins, upd)
            except Exception as e:      # один битый апдейт не должен ронять весь бот
                print("Ошибка обработки апдейта:", e)
            _save_offset(offset)        # без дублей после падения/рестарта


if __name__ == "__main__":
    main()
