# MVP2 — AI Lead Automation

Автоматизация входящих лидов: лид приходит по вебхуку, ИИ-конвейер квалифицирует
его (**hot / warm / cold**), маршрутизирует и логирует.

Два артефакта делают **один и тот же** пайплайн:

| Файл | Что это |
|------|---------|
| `workflow.json` | Импортируемый workflow для **n8n** (продакшен-исполнение). |
| `reference.py` | Эталонная Python-реализация той же логики — запускается и тестируется **без n8n**. |
| `test_reference.py` | Офлайн-тесты (mock LLM, без сети/ключей). |

## Пайплайн

```
Входящий лид (Webhook)
   -> Score & Qualify (правила, JS/Python)   # детерминированно
   -> Note (LLM / GigaChat HTTP)             # человекочитаемая заметка
   -> IF по категории
        ├─ hot  -> Telegram-уведомление + лог
        └─ остальные -> лог (Google Sheets)
```

### Логика квалификации (детерминирована — стабильна для тестов)

- `score_lead(lead) -> 0..100`:
  - бюджет: `>=50000` -> +50, `>=10000` -> +25;
  - срочность (ключевые слова `срочно/сегодня/asap/...`) -> +30;
  - контакты: телефон -> +10, email -> +10.
- `categorize(score)`: `>=70` hot, `>=40` warm, иначе cold.
- маршрут: hot -> `sales_call`, warm -> `email_nurture`, cold -> `newsletter`.

LLM (`shared.llm.chat`) используется **только** для текстовой заметки/next-action,
не для скоринга — поэтому тесты воспроизводимы.

## Запуск reference.py (доказывает логику без n8n)

```bash
cd /home/oleg/freelance-mvp
.venv/bin/python mvp2_n8n_automation/reference.py     # демо на 3 лидах
.venv/bin/python mvp2_n8n_automation/test_reference.py # -> MVP2 TESTS OK
```

По умолчанию провайдер LLM — `mock` (детерминированный, без сети). Для реального
LLM выставьте `LLM_PROVIDER=gigachat` (или `yandex`) и ключи в `/home/oleg/freelance-mvp/.env`.

## Импорт workflow.json в n8n

1. n8n -> **Workflows** -> **Import from File** -> выберите `workflow.json`.
2. Откройте импортированный workflow и задайте креденшелы (см. ниже).
3. Активируйте workflow. URL вебхука: `POST {N8N_HOST}/webhook/lead`.
4. Тест:
   ```bash
   curl -X POST {N8N_HOST}/webhook/lead \
     -H 'Content-Type: application/json' \
     -d '{"name":"ООО Ромашка","budget":120000,"phone":"+79991234567","email":"a@b.ru","message":"нужно срочно"}'
   ```

## Креденшелы (human-only, задаются в n8n UI)

В JSON стоят плейсхолдеры `REPLACE_WITH_*` — замените на реальные ID после создания креденшелов:

| Нода | Тип креденшела | Что нужно |
|------|----------------|-----------|
| **GigaChat note (HTTP)** | HTTP Header Auth | Header `Authorization` со значением `Bearer <access_token>` GigaChat. Токен получают по OAuth (см. `shared/llm.py` `_gigachat_token`). Проще: добавить шаг получения токена или хранить долгоживущий. |
| **Telegram notify (hot)** | Telegram API | Token бота от @BotFather. Также задайте env-переменную `SALES_TELEGRAM_CHAT_ID` (chat_id отдела продаж). |
| **Append to CRM Sheet** | Google Sheets OAuth2 | OAuth2-доступ к Google. Замените `documentId` на ID вашей таблицы, лист `Leads` с колонками: name, phone, email, budget, score, category, routed_to, note. |

## Что делает человек (не автоматизируется этим артефактом)

- Хостинг/запуск самого n8n (self-hosted или n8n.cloud).
- Создание креденшелов GigaChat / Telegram / Google Sheets в n8n UI и подстановка их ID.
- Создание Google-таблицы с листом `Leads` и заголовками колонок.
- (Опционально) шаг OAuth-получения токена GigaChat перед HTTP-нодой, если не используете долгоживущий токен.

## Связь артефактов

`reference.py` и Code-нода в `workflow.json` реализуют **одинаковые** правила
(`score_lead` / `categorize` / маршруты). Поэтому `test_reference.py` доказывает
корректность бизнес-логики офлайн, а n8n-граф исполняет её в продакшене.
