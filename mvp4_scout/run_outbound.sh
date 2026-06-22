#!/usr/bin/env bash
# Ежедневный исход: находит вакансии-цели (Trudvsem), генерит питчи и шлёт
# готовые пакеты владельцу в ЛС (@kryu_scout_bot). Человек жмёт отправить сам.
# Cron: раз в день. LLM/токены берутся из .env.
set -u
REPO="/home/oleg/freelance-mvp"
cd "$REPO"
echo "$(date '+%F %T') outbound старт" >> "$REPO/mvp4_scout/outbound.log"
OUTBOUND_MAX="${OUTBOUND_MAX:-8}" PYTHONUNBUFFERED=1 "$REPO/.venv/bin/python" \
    mvp4_scout/outbound.py --send >> "$REPO/mvp4_scout/outbound.log" 2>&1
echo "$(date '+%F %T') outbound конец" >> "$REPO/mvp4_scout/outbound.log"
