# MVP4 — Order Scout (разведчик заказов на фрилансе)

Бот, который **круглосуточно ищет за тебя подходящие заказы** на FL.ru
(и опционально в Telegram-каналах), фильтрует их по бюджету и ключевым словам,
**сразу пишет персональный черновик отклика через LLM** и присылает всё
готовым сообщением в твой Telegram. Работает бесплатно 24/7 на GitHub Actions
по расписанию (cron каждые 30 минут).

Ты открываешь телефон — а там уже: заказ + бюджет + ссылка + готовый текст
отклика, который остаётся скопировать и отправить.

## Что внутри

```
mvp4_scout/
├── fl_source.py     # FL.ru: parse_orders(html) [чистая] + fetch_fl_orders() [сеть]
├── tg_source.py     # Telegram-каналы через Telethon (опционально; без него -> [])
├── draft.py         # make_draft(order, profile) -> отклик через shared.llm.chat + PROFILE
├── scout.py         # filter_orders / notify / run_cycle (главный цикл) + CLI
├── test_scout.py    # офлайн-тесты (фикстура HTML + mock-LLM, без сети)
├── seen.json        # память о уже отправленных заказах (создаётся на 1-м прогоне)
└── .github/workflows/scout.yml   # cron каждые 30 мин на GitHub Actions
```

## Архитектура (поток данных)

```
            FL.ru (requests)            Telegram (Telethon, опц.)
                  │                              │
            parse_orders                   fetch_tg_orders
                  └──────────────┬───────────────┘
                                 ▼
                   filter_orders(min_budget, keywords)   # бюджет + ключи + дедуп
                                 ▼
                   дедуп против seen.json                # не слать повторно
                                 ▼
                   make_draft(order, PROFILE)            # shared.llm.chat -> питч
                                 ▼
                   notify(text)                          # Telegram sendMessage
```

- **`parse_orders` — чистая функция** (без сети): её и гоняют тесты. Боевой
  `fetch_fl_orders` лишь добавляет HTTP-запрос и зовёт `parse_orders`.
- LLM абстрагирован через `shared/llm.py`: провайдер задаётся `LLM_PROVIDER`
  (`mock` для тестов/CI без ключей, `gigachat` / `yandex` — боевые, РФ, без VPN).
- Telethon — **опциональная** зависимость. Не установлен / нет кредов ->
  Telegram-источник тихо пропускается, FL.ru продолжает работать.
- Профиль фрилансера в `draft.PROFILE` (навыки + кейсы) — под него LLM пишет
  отклик. Меняешь профиль -> меняются тексты.

## Настройки (env / GitHub Secrets)

| Переменная | Обяз. | Назначение |
|---|---|---|
| `LLM_PROVIDER` | да | `gigachat` (рекоменд., РФ) или `yandex`; `mock` — без LLM |
| `GIGACHAT_AUTH_KEY` | для gigachat | ключ авторизации GigaChat |
| `SCOUT_NOTIFY_TOKEN` | да | токен Telegram-бота, который шлёт тебе уведомления (от @BotFather) |
| `SCOUT_NOTIFY_CHAT_ID` | да | твой chat_id (узнать у @userinfobot) |
| `SCOUT_KEYWORDS` | нет | ключи через запятую (деф.: `бот,парсинг,автоматизация,GPT,Telegram`) |
| `SCOUT_MIN_BUDGET` | нет | мин. бюджет в рублях (деф.: `10000`) |
| `SCOUT_TG_CHANNELS` | нет | каналы через запятую (напр. `@freelance_orders`) |
| `TG_API_ID` / `TG_API_HASH` | для TG | с https://my.telegram.org |
| `TG_SESSION` | для TG | StringSession Telethon (чтобы не хранить .session-файл в CI) |

Если `SCOUT_NOTIFY_TOKEN`/`SCOUT_NOTIFY_CHAT_ID` не заданы — `notify()` просто
печатает в лог (удобно для отладки), ничего не падает.

## Локальный запуск

```bash
cd /home/oleg/freelance-mvp
.venv/bin/python mvp4_scout/test_scout.py   # офлайн-тесты -> "MVP4 TESTS OK"
.venv/bin/python mvp4_scout/scout.py        # один боевой цикл (нужны креды/сеть)
```

## Деплой на GitHub Actions (бесплатно, 24/7)

1. Залей проект в GitHub-репозиторий.
2. **Settings → Secrets and variables → Actions → New repository secret** —
   добавь нужные секреты из таблицы выше (минимум: `LLM_PROVIDER`,
   `GIGACHAT_AUTH_KEY`, `SCOUT_NOTIFY_TOKEN`, `SCOUT_NOTIFY_CHAT_ID`).
3. Workflow `.github/workflows/scout.yml` запустится сам по cron
   (`*/30 * * * *`). Можно дёрнуть вручную: **Actions → Order Scout → Run workflow**.
4. `seen.json` коммитится обратно в репозиторий после каждого прогона
   (нужно `permissions: contents: write` — уже прописано), чтобы заказы не
   повторялись между запусками.

> Лимиты бесплатных GitHub Actions с запасом покрывают запуск раз в 30 минут.

## Почему это само по себе продукт

- **Экономит часы в день**: вместо ручного мониторинга бирж — готовые
  отклики прилетают в Telegram. Кто откликнулся первым и по делу — тот и взял заказ.
- **Продаётся как услуга/SaaS**: «персональный AI-разведчик заказов» под нишу
  клиента (свои ключевые слова, свой профиль, свои источники). Настройка —
  это правка нескольких Secrets.
- **Расширяемо**: источники (`*_source.py`) подключаются по одному интерфейсу
  `-> list[{"title","budget","url"}]` — Kwork, Хабр Фриланс, Upwork, чаты —
  добавляются без переписывания ядра.
- **Ноль инфраструктуры и затрат**: хостинг = GitHub Actions, LLM = российские
  провайдеры без VPN. Запускается у любого клиента форком репозитория.
