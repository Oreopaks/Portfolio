#!/usr/bin/env bash
# Запуск бота сравнения цен в фоне (переживает закрытие терминала через nohup).
# Идемпотентно: если уже запущен — не плодит второй.
cd /home/oleg/freelance-mvp || exit 1

if pgrep -f "mvp7_price_scout.bot" >/dev/null; then
    echo "Бот уже запущен (pid $(pgrep -f 'mvp7_price_scout.bot' | head -1))"
    exit 0
fi

nohup .venv/bin/python -m mvp7_price_scout.bot > mvp7_price_scout/bot_run.log 2>&1 &
disown
sleep 2
if pgrep -f "mvp7_price_scout.bot" >/dev/null; then
    echo "✅ Бот запущен → @Site_parssss_bot"
    echo "   лог: mvp7_price_scout/bot_run.log"
    echo "   стоп: pkill -f mvp7_price_scout.bot"
else
    echo "❌ Не стартовал. Лог:"; tail -n 20 mvp7_price_scout/bot_run.log
fi
