#!/usr/bin/env bash
# Обёртка для cron: запуск скаута 24/7 каждые 30 минут.
# flock -n не даёт двум прогонам пересечься, если цикл затянулся (GigaChat медлит).
set -euo pipefail

REPO="/home/oleg/freelance-mvp"
LOG="$REPO/mvp4_scout/scout.log"
LOCK="$REPO/mvp4_scout/scout.lock"

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date '+%F %T') предыдущий прогон ещё идёт — пропуск" >> "$LOG"
    exit 0
fi

cd "$REPO"
echo "===== $(date '+%F %T') старт цикла =====" >> "$LOG"
"$REPO/.venv/bin/python" mvp4_scout/scout.py >> "$LOG" 2>&1 || echo "$(date '+%F %T') цикл завершился с ошибкой" >> "$LOG"
echo "===== $(date '+%F %T') конец =====" >> "$LOG"

# Держим лог в узде — последние 2000 строк.
tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" || true
