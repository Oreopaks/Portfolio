# mvp7_price_scout — мониторинг цен конкурентов + Telegram-бот

Сравнивает цены магазина **di-park.ru** (эталон) с конкурентами Орла. Сбор по
расписанию в SQLite; Telegram-бот по запросу товара отдаёт компактную таблицу
«наша цена vs конкуренты», шлёт проактивные алерты и даёт сводку по рынку.

## Что умеет

- 📊 **Сравнение по запросу** — напиши товар, бот пришлёт таблицу цен с разницей,
  кто дешевле, и подсказкой «чтобы быть дешевле всех: N ₽».
- 🔔 **Проактивные алерты** — collector сам пишет админу, когда конкурент
  подрезал нас по цене или заметно снизил цену (сравнение прогонов).
- 📉 **/top** — товары, где мы дороже всех (теряем продажи).
- 📈 **/stats** — позиция на рынке: где дешевле/дороже/наравне, средний проигрыш.
- 📤 **/export** — вся таблица сравнения в Excel/CSV одним файлом.

## Архитектура

```
collector (cron) di-park ─┐
                 sr57 ─────┼ collapse цветов ─ match к каталогу di-park ─ SQLite ─ алерты админу
                 iprice ───┤
                 ispace ───┤   (--heavy:)  repremium (Playwright), Instagram (сессия+OCR)
bot (long-poll)  запрос ─ fuzzy-поиск по каталогу di-park ─ таблица из SQLite
```

Бот не парсит в реальном времени — отвечает мгновенно из базы (у каждой цены
есть время сбора, «обновлено Nч назад»).

## Установка

```bash
cd /home/oleg/freelance-mvp
.venv/bin/pip install -r requirements-optional.txt
.venv/bin/python -m playwright install chromium      # для repremium
```

`.env` (секция MVP7 в `.env.example`):
```
PRICE_BOT_TOKEN=...      # ОТДЕЛЬНЫЙ бот @BotFather (не слитый токен!)
PRICE_BOT_ADMINS=...     # chat_id админов (узнать /id), через запятую
PRICESCOUT_DB=mvp7_price_scout/prices.db
IG_USERNAME=...          # для Instagram (после ig_login.py)
IG_SETTINGS=mvp7_price_scout/ig_session.json
```

## Запуск

```bash
.venv/bin/python -m mvp7_price_scout.collector            # быстрый сбор (sr57, iprice, ispace)
.venv/bin/python -m mvp7_price_scout.collector --heavy    # + repremium (Playwright) + Instagram
.venv/bin/python -m mvp7_price_scout.bot                  # бот (foreground)
bash mvp7_price_scout/run_bot.sh                          # бот в фоне (nohup, переживает терминал)
.venv/bin/python -m mvp7_price_scout.ig_login             # одноразовый вход в Instagram (заказчик)
```

Бот в фоне (постоянно): `bash mvp7_price_scout/run_bot.sh` — идемпотентно, лог в
`bot_run.log`, стоп `pkill -f mvp7_price_scout.bot`. Для автозапуска после
перезагрузки — добавить watchdog в cron (см. ниже).

Команды бота: `<товар>`, `/top`, `/stats`, `/export`, `/refresh` (админ, запускает
тяжёлый сбор), `/id`, `/help`.

### Расписание (cron)

Открыть `crontab -e` и добавить:
```cron
# бот всегда живой (поднимет после краша/перезагрузки)
* * * * *    pgrep -f mvp7_price_scout.bot >/dev/null || bash /home/oleg/freelance-mvp/mvp7_price_scout/run_bot.sh
# сбор цен
0 */3 * * *  cd /home/oleg/freelance-mvp && .venv/bin/python -m mvp7_price_scout.collector
30 6 * * *   cd /home/oleg/freelance-mvp && .venv/bin/python -m mvp7_price_scout.collector --heavy
```

## Статус источников

| Источник | Тип | Метод | Статус |
|---|---|---|---|
| **di-park.ru** | эталон | Laravel SSR, requests+bs4, sitemap (~2900 товаров) | ✅ |
| **sr57.ru** | конкурент | WooCommerce, requests+bs4 | ✅ |
| **iprice.store** | конкурент | Webasyst, requests+bs4 | ✅ |
| **orel.ispace-shop.ru** | конкурент | Bitrix, цены на страницах товаров (в листингах скрыты) | ✅ частично* |
| **repremium.ru** | конкурент | Bitrix/aspro, грид через **Playwright** (--heavy) | ✅ |
| **Instagram @smart_room_57** | конкурент | instagrapi сессия + OCR (--heavy) | ✅ нужна сессия** |
| Яндекс ×2 (Kingstore, Rem-gsm) | — | — | ❌ исключены*** |

\* ispace прячет цены в листингах («Цена при оплате наличными») — тянем страницы
товаров из блока «популярное» (частичное покрытие популярных позиций).
\*\* Instagram режет анонимов (429). Нужен один раз `ig_login.py` (сессия заказчика).
Цены из подписей парсятся надёжно; цены на фото/в stories — через OCR (~20-40%
требуют ручной сверки, помечены `~` и source_type `ig_ocr`).
\*\*\* Проверены оба Яндекс-профиля: отдают услуги/витрину (Kingstore —
«установка приложений», Rem-gsm — ремонт), не каталог телефонов. Сравнивать нечего.

## Как устроено сравнение (ядро корректности)

- `normalize.model_key(title)` — канон: режем всё после объёма памяти
  (цвет/sim/комплектация — открытый список), бренд-шум долой, RU→EN алиасы.
  `Apple iPhone 17 256Gb Mist Blue` → `17 iphone 256gb`.
- `collapse_variants` — цвета схлопываются в одну цену за объём (минимум).
- `is_used` — Б/У/уценка/демо исключаются (сравниваем новое с новым).
- `match.match_one` — конкурент к эталону: точный ключ ИЛИ fuzzy с guard'ами:
  **объём + вариант-токены (pro/max/ultra) + числовые модель-токены (16≠17, s24≠s25)
  + общий бренд**. Без guard'ов token_sort_ratio путает 16/17 (1 символ) — в тестах.

## Тесты

```bash
.venv/bin/python -m pytest mvp7_price_scout/tests -q     # 57 тестов
```

## Безопасность

- Токен `8654917998:AAGJ...` был в открытом чате — **отозвать** (@BotFather `/revoke`),
  завести отдельного бота. Токены только в `.env` (вне git).
- Instagram: отдельный аккаунт, пароль не хранить — только файл сессии.
- repremium robots `crawl-delay 20с` — берём только телефонные разделы, умеренно.
