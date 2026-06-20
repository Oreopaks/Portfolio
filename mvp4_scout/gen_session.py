"""
Одноразовый генератор TG_SESSION (StringSession) для скаута (MVP4).

Запусти в терминале (нужен интерактивный ввод телефона + кода из Telegram):
    .venv/bin/python mvp4_scout/gen_session.py

Введёшь номер (+7XXXXXXXXXX) и код, что придёт в Telegram (если есть 2FA-пароль — тоже).
Скрипт напечатает длинную строку — впиши её в .env как:
    TG_SESSION=<строка>
api_id / api_hash берутся из .env (TG_API_ID / TG_API_HASH).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import shared.config  # noqa: F401 — подхватывает .env
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(os.environ["TG_API_ID"])
api_hash = os.environ["TG_API_HASH"]

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_str = client.session.save()
    me = client.get_me()
    print(f"\nВошёл как: {me.first_name} (@{me.username}, id={me.id})")
    print("\n==== TG_SESSION (впиши в .env) ====")
    print(session_str)
    print("===================================")
