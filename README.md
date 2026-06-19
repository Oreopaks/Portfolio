# freelance-mvp — 4 рабочих демо + сайт-портфолио

Боевые MVP для портфолио фрилансера (код + AI). Каждый — самостоятельный
продаваемый кейс. Всё на Python, минимум зависимостей (`requests`, `flask`),
LLM абстрагирован за провайдером (`mock` для тестов без ключей; `gigachat` /
`yandex` в бою — РФ, без VPN).

## Состав

| Папка | Что это | Чек | Хостинг 24/7 $0 |
|---|---|---|---|
| `mvp1_gpt_bot/` | Telegram GPT-бот бизнеса (FAQ + запись) | от 15к | VM / любой always-on |
| `mvp2_n8n_automation/` | AI-квалификация лидов (n8n workflow + python-эквивалент) | от 30к | n8n на VM |
| `mvp3_rag/` | RAG-ассистент по документам (ответ с цитатой) | от 65к | VM (Flask/gunicorn) |
| `mvp4_scout/` | Скаут заказов: парс FL.ru/TG → AI-черновик → Telegram | от 10к | GitHub Actions (cron) |
| `site/` | Одностраничный сайт-портфолио (статика) | — | GitHub/Cloudflare Pages |
| `shared/` | `llm.py` (провайдеры LLM) + `config.py` (.env) | — | — |

## Быстрый старт (локально)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # заполнить ключи (для боя)
.venv/bin/python run_all_tests.sh  # см. ниже
```

## Тесты

Все MVP тестируются офлайн (provider `mock`, без сети и ключей):

```bash
bash run_all_tests.sh
```

MVP4 дополнительно умеет живой парсинг FL.ru (сеть) — это проверяется отдельно,
запуском `python mvp4_scout/scout.py` с заданными ключами.

## Деплой в сеть

См. **[DEPLOY.md](DEPLOY.md)** — пошаговый runbook: какие ключи получить,
где бесплатно поднять 24/7, как запушить на GitHub и опубликовать сайт.

## Принцип LLM-провайдера

`shared/llm.py` → `chat(system, user)`. Провайдер из env `LLM_PROVIDER`:
- `mock` — детерминированный, без ключей (тесты/демо вхолостую);
- `gigachat` — Сбер, РФ, без VPN (нужен `GIGACHAT_AUTH_KEY`);
- `yandex` — YandexGPT (нужны `YANDEX_API_KEY` + `YANDEX_FOLDER_ID`).

Код MVP не меняется при смене провайдера — только `.env`.
