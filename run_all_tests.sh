#!/usr/bin/env bash
# Прогон всех офлайн-тестов (provider=mock, без сети/ключей).
set -u
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

fail=0
for t in mvp1_gpt_bot/test_bot.py \
         mvp2_n8n_automation/test_reference.py \
         mvp3_rag/test_rag.py \
         mvp4_scout/test_scout.py; do
  echo "── $t ──"
  if ! "$PY" "$t"; then
    echo "FAIL: $t"; fail=1
  fi
  echo
done

if [ "$fail" = 0 ]; then
  echo "ВСЕ ТЕСТЫ ПРОШЛИ ✅"
else
  echo "ЕСТЬ ПАДЕНИЯ ❌"; exit 1
fi
