#!/usr/bin/env bash
# Watchdog для MVP1-бота (кофейня + портфолио-витрина /demo).
# Cron зовёт каждые 5 мин: если бот не жив — поднимает. Переживает краш и ребут.
set -u
REPO="/home/oleg/freelance-mvp"

# Уже работает — выходим (один инстанс, иначе конфликт getUpdates в Telegram).
if pgrep -f 'mvp1_gpt_bot/bot.py' >/dev/null; then
    exit 0
fi

cd "$REPO"
echo "$(date '+%F %T') старт бота" >> "$REPO/mvp1_gpt_bot/bot.log"
PYTHONUNBUFFERED=1 setsid "$REPO/.venv/bin/python" mvp1_gpt_bot/bot.py \
    >> "$REPO/mvp1_gpt_bot/bot.log" 2>&1 < /dev/null &
