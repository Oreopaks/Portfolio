# Портфолио AI-разработчика — деплой и настройка

Статический сайт без шага сборки. Достаточно выложить папку `site/` — всё готово.

---

## Плейсхолдеры для замены

Перед публикацией найди и замени следующие строки в `site/index.html`:

| Плейсхолдер      | Что подставить                                     |
|------------------|----------------------------------------------------|
| `{{ИМЯ}}`        | Ваше имя или псевдоним, напр. `Олег Иванов`       |
| `{{TELEGRAM}}`   | Username в Telegram без `@`, напр. `oleg_ai_dev`  |
| `{{EMAIL}}`      | Ваш email, напр. `hello@example.com`               |
| `{{LIVE_URL_1}}` | URL живого демо GPT-бота                           |
| `{{LIVE_URL_2}}` | URL живого демо n8n-автоматизации                  |
| `{{LIVE_URL_3}}` | URL живого демо RAG-ассистента                     |
| `{{LIVE_URL_4}}` | URL живого демо парсинга                           |
| `{{VIDEO_URL_1}}`| Ссылка на видео-обзор GPT-бота (YouTube / Loom)   |
| `{{VIDEO_URL_2}}`| Ссылка на видео-обзор n8n-автоматизации            |
| `{{VIDEO_URL_3}}`| Ссылка на видео-обзор RAG-ассистента               |
| `{{VIDEO_URL_4}}`| Ссылка на видео-обзор парсинга                     |

Быстрая замена через `sed` (Linux / macOS):
```bash
sed -i 's/{{ИМЯ}}/Олег Иванов/g' site/index.html
sed -i 's/{{TELEGRAM}}/oleg_ai_dev/g' site/index.html
sed -i 's/{{EMAIL}}/hello@example.com/g' site/index.html
# и так далее для каждого плейсхолдера
```

---

## Деплой на GitHub Pages

1. Создай репозиторий на GitHub (публичный или приватный с Pages).
2. Помести файлы `index.html` и `style.css` в корень ветки `main`
   (или в папку `site/`, если удобно — тогда укажи её в настройках Pages).
3. Перейди в **Settings → Pages**.
4. В разделе **Source** выбери:
   - Branch: `main`
   - Folder: `/ (root)` — если файлы в корне, или `/site` — если в подпапке.
5. Нажми **Save**. Через ~1–2 минуты сайт будет доступен по адресу:
   `https://<username>.github.io/<repo>/`

Больше никаких настроек не нужно — нет npm, нет билда.

---

## Деплой на Cloudflare Pages

1. Зайди в [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create application** → **Pages**.
2. Подключи GitHub-репозиторий.
3. Настройки сборки:
   - **Framework preset:** `None`
   - **Build command:** *(оставь пустым)*
   - **Output directory:** `site` (или `.` если файлы в корне)
4. Нажми **Save and Deploy**.

Cloudflare автоматически выдаёт домен вида `<project>.pages.dev` и поднимает HTTPS.
При каждом пуше в `main` сайт обновляется автоматически.

---

## Структура файлов

```
site/
├── index.html   # Единственная страница
└── style.css    # Все стили (без внешних зависимостей)
```

Никаких node_modules, package.json, webpack и т.п. — чистый HTML + CSS.
