#!/usr/bin/env bash
# Установка cron для price-бота: сбор цен по расписанию + автозапуск/перезапуск бота.
# Идемпотентно — повторный запуск не плодит дубли.
#   Запуск:  bash mvp7_price_scout/setup_cron.sh
set -euo pipefail
REPO=/home/oleg/freelance-mvp

{
  crontab -l 2>/dev/null | grep -vE "mvp7_price_scout|price_scout.collector" || true
  echo "# --- mvp7_price_scout (price bot) ---"
  echo "0 */3 * * * cd $REPO && .venv/bin/python -m mvp7_price_scout.collector --heavy >> mvp7_price_scout/collector.log 2>&1"
  echo "@reboot $REPO/mvp7_price_scout/run_bot.sh >/dev/null 2>&1"
  echo "*/5 * * * * $REPO/mvp7_price_scout/run_bot.sh >/dev/null 2>&1"
} | crontab -

echo "Cron установлен:"
crontab -l | grep -A4 "mvp7_price_scout (price"
echo
echo "Сбор цен: каждые 3 часа (--heavy)."
echo "Бот: автозапуск при ребуте + перезапуск если упал (проверка каждые 5 мин, run_bot.sh идемпотентен)."
