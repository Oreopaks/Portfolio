#!/usr/bin/env bash
# Watchdog для супервизора витрины (5 продуктовых ботов в одном процессе).
# Cron зовёт каждые 5 мин: если процесс не жив — поднимает. Переживает краш и ребут.
set -u
REPO="/home/oleg/freelance-mvp"

# Уже работает — выходим (один инстанс, иначе конфликт getUpdates в Telegram).
if pgrep -f 'demo_bot/supervisor.py' >/dev/null; then
    exit 0
fi

cd "$REPO"
echo "$(date '+%F %T') старт супервизора витрины" >> "$REPO/demo_bot/supervisor.log"
PYTHONUNBUFFERED=1 setsid "$REPO/.venv/bin/python" demo_bot/supervisor.py \
    >> "$REPO/demo_bot/supervisor.log" 2>&1 < /dev/null &
