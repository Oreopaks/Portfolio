"""
Одноразовый вход в Instagram -> сохранение сессии в файл IG_SETTINGS.

Запускает ЗАКАЗЧИК один раз (логин + код 2FA). Пароль НЕ хранится — только
файл сессии. Рекомендация: отдельный (не основной) аккаунт, риск временного бана.

Запуск:
    export IG_USERNAME=...; export IG_SETTINGS=mvp7_price_scout/ig_session.json
    python -m mvp7_price_scout.ig_login
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень репо (freelance-mvp)
import shared.config  # noqa: F401


def main() -> None:
    from instagrapi import Client

    user = os.environ.get("IG_USERNAME") or input("Instagram логин: ").strip()
    settings = os.environ.get("IG_SETTINGS", "mvp7_price_scout/ig_session.json")
    password = getpass.getpass("Пароль (не сохраняется): ")

    cl = Client()
    cl.delay_range = [1, 3]

    def code_handler(_username) -> str:
        return input("Код 2FA из приложения/SMS: ").strip()

    cl.challenge_code_handler = code_handler
    cl.login(user, password, verification_code="")
    cl.dump_settings(settings)
    print(f"Сессия сохранена: {settings}")
    print("Впиши в .env: IG_USERNAME=" + user + f"  и  IG_SETTINGS={settings}")


if __name__ == "__main__":
    main()
