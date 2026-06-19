# DEPLOY — как выгрузить всё в сеть (24/7, бесплатно)

Код написан и протестирован. Здесь — только то, что **должен сделать ты** (аккаунты,
ключи, кнопки), потому что без твоих учёток это сделать нельзя.

Порядок: получить ключи → запушить на GitHub → поднять бесплатный сервер →
запустить 4 MVP → опубликовать сайт.

---

## 0. Что понадобится (чек-лист аккаунтов)

- [ ] **GitHub** аккаунт (бесплатно, без карты) — для кода, скаута (Actions) и сайта (Pages).
- [ ] **LLM-ключ**: GigaChat (Сбер, по паспорту РФ, без карты/VPN) **или** YandexGPT.
- [ ] **Telegram**: аккаунт + бот от @BotFather (для MVP1 и уведомлений скаута).
- [ ] **Бесплатный сервер 24/7** для MVP1/2/3: Oracle Cloud Always Free **или** GCP free
      (нужна загранкарта для регистрации — карту не списывают). План Б без карты — в конце.
- [ ] *(опц.)* Cloudflare аккаунт — если хочешь сайт на Cloudflare Pages.

---

## 1. LLM-ключ

### Вариант А — GigaChat (рекомендую для РФ)
1. Зайти на https://developers.sber.ru/studio → войти → создать проект **GigaChat API**.
2. Раздел «Авторизационные данные» → скопировать **Authorization key** (это base64 от
   `client_id:client_secret`).
3. В `.env`:
   ```
   LLM_PROVIDER=gigachat
   GIGACHAT_AUTH_KEY=<вставить authorization key>
   GIGACHAT_SCOPE=GIGACHAT_API_PERS
   ```
4. **Сертификат Минцифры** (иначе TLS-ошибка при запросе к Сберу):
   ```bash
   # на сервере, разово
   curl -k https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer \
     -o russian_trusted_root_ca.cer
   ```
   и в `.env`: `GIGACHAT_CA=russian_trusted_root_ca.cer`
   (на время локального теста можно `GIGACHAT_CA=False` — небезопасно, только для проверки).

### Вариант Б — YandexGPT
1. https://console.yandex.cloud → создать сервисный аккаунт + API-ключ, узнать folder id.
2. В `.env`:
   ```
   LLM_PROVIDER=yandex
   YANDEX_API_KEY=<api-key>
   YANDEX_FOLDER_ID=<folder-id>
   ```

Проверка ключа:
```bash
.venv/bin/python -c "import shared.config; from shared import llm; print(llm.available()); print(llm.chat('Ты ассистент.','Скажи привет одним словом'))"
```

---

## 2. Запушить проект на GitHub

Локальный git уже инициализирован и закоммичен. `gh` не установлен, поэтому репозиторий
создаём через сайт:

1. https://github.com/new → имя `freelance-mvp` → **Private** → Create (без README).
2. На сервере:
   ```bash
   cd /home/oleg/freelance-mvp
   git remote add origin https://github.com/<ТВОЙ_ЛОГИН>/freelance-mvp.git
   git branch -M main
   git push -u origin main
   ```
   (логин/пароль → используй Personal Access Token вместо пароля:
   GitHub → Settings → Developer settings → Tokens → Fine-grained, scope repo.)

`.env` в репозиторий **не попадёт** (он в `.gitignore`). Это правильно — ключи в гит не кладём.

---

## 3. Бесплатный сервер 24/7 (для MVP1, MVP2, MVP3)

### Oracle Cloud Always Free (навсегда бесплатно)
1. https://www.oracle.com/cloud/free → Start for free → регистрация (загранкарта, не списывают).
2. Create VM Instance → Shape: **Ampere A1 (ARM, до 4 ядер/24 ГБ)** или **VM.Standard.E2.1.Micro (AMD, x2 навсегда free)**.
   Если ARM «out of capacity» — бери AMD micro.
3. Image: Ubuntu 22.04. Скачать приватный SSH-ключ.
4. Networking → открыть порты, которые будешь использовать (напр. 8080 для RAG) в Security List.
5. Подключиться и развернуть:
   ```bash
   ssh -i <ключ> ubuntu@<IP_сервера>
   sudo apt update && sudo apt install -y python3-venv git
   git clone https://github.com/<ТВОЙ_ЛОГИН>/freelance-mvp.git
   cd freelance-mvp
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env && nano .env     # вставить ключи из шагов 1 и 4/5
   bash run_all_tests.sh                 # должно быть «ВСЕ ТЕСТЫ ПРОШЛИ ✅»
   ```

Альтернатива: **GCP e2-micro** (always free в ряде регионов US) — те же шаги.

---

## 4. Запуск MVP

### MVP1 — Telegram-бот (на сервере, 24/7)
1. @BotFather → `/newbot` → получить токен → в `.env`: `TELEGRAM_BOT_TOKEN=...`
2. Поднять как systemd-сервис (перезапуск при падении/ребуте):
   ```bash
   sudo tee /etc/systemd/system/mvp1-bot.service >/dev/null <<'EOF'
   [Unit]
   Description=MVP1 GPT bot
   After=network.target
   [Service]
   WorkingDirectory=/home/ubuntu/freelance-mvp
   ExecStart=/home/ubuntu/freelance-mvp/.venv/bin/python mvp1_gpt_bot/bot.py
   Restart=always
   User=ubuntu
   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl enable --now mvp1-bot
   sudo systemctl status mvp1-bot   # проверить, что running
   ```
3. Демо-ссылка для портфолио: `https://t.me/<имя_бота>` → это `{{LIVE_URL_1}}`.

### MVP3 — RAG API (на сервере, 24/7)
1. Запуск через gunicorn (стабильнее, чем `app.run`):
   ```bash
   .venv/bin/pip install gunicorn
   sudo tee /etc/systemd/system/mvp3-rag.service >/dev/null <<'EOF'
   [Unit]
   Description=MVP3 RAG API
   After=network.target
   [Service]
   WorkingDirectory=/home/ubuntu/freelance-mvp
   ExecStart=/home/ubuntu/freelance-mvp/.venv/bin/gunicorn -b 0.0.0.0:8080 mvp3_rag.api:app
   Restart=always
   User=ubuntu
   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl enable --now mvp3-rag
   ```
2. Открыть порт 8080 в Security List Oracle + `sudo ufw allow 8080` (если ufw вкл).
3. Демо-ссылка: `http://<IP>:8080/` → `{{LIVE_URL_3}}`.
   *(Для красивого домена/HTTPS — позже nginx + Let's Encrypt, не обязательно для демо.)*
4. *(опц.)* PDF-загрузка: `.venv/bin/pip install pypdf` — включится сама.

### MVP2 — n8n (на сервере, 24/7)
n8n нужен живой процесс. Проще всего через Docker:
```bash
# поставить docker (если нет)
curl -fsSL https://get.docker.com | sudo sh
sudo docker run -d --restart=always --name n8n -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n docker.n8n.io/n8nio/n8n
```
1. Открыть порт 5678, зайти на `http://<IP>:5678`, создать локального пользователя.
2. **Import from File** → загрузить `mvp2_n8n_automation/workflow.json`.
3. Завести credentials (вместо плейсхолдеров `REPLACE_WITH_*`):
   - **GigaChat**: HTTP Header Auth → `Authorization: Bearer <token>` (или OAuth-шаг перед HTTP-нодой).
   - **Telegram**: токен бота + chat_id (env `SALES_TELEGRAM_CHAT_ID`).
   - **Google Sheets**: OAuth2 + id таблицы с листом `Leads`.
4. Activate workflow. Демо-ссылка для портфолио — короткое видео/Loom прогона → `{{LIVE_URL_2}}` или `{{VIDEO_URL_2}}`.
   `reference.py` доказывает ту же логику без n8n (можно показать прогон в терминале).

### MVP4 — Скаут заказов (БЕЗ сервера, на GitHub Actions, $0)
1. Telegram-уведомления: создать ещё одного бота (или тот же), узнать свой `chat_id`
   (напиши боту, потом @userinfobot или getUpdates).
2. *(опц.)* Источник TG-каналов: https://my.telegram.org → API development tools →
   получить `api_id` / `api_hash`; локально сгенерировать `TG_SESSION` (StringSession Telethon).
   Без них скаут просто пропускает Telegram и парсит только FL.ru.
3. GitHub → репозиторий → **Settings → Secrets and variables → Actions → New secret**, добавить:
   | Secret | Значение |
   |---|---|
   | `LLM_PROVIDER` | `gigachat` |
   | `GIGACHAT_AUTH_KEY` | ключ из шага 1 |
   | `SCOUT_NOTIFY_TOKEN` | токен бота-уведомителя |
   | `SCOUT_NOTIFY_CHAT_ID` | твой chat_id |
   | `SCOUT_MIN_BUDGET` | `10000` |
   | `SCOUT_KEYWORDS` | `бот,gpt,gigachat,нейросеть,n8n,парсинг,автоматизация,python,api` |
   | *(опц.)* `SCOUT_TG_CHANNELS` | `ipomogator,digitaltender` |
   | *(опц.)* `TG_API_ID`,`TG_API_HASH`,`TG_SESSION` | для чтения TG-каналов |
4. Actions → workflow **Order Scout** → Run workflow (проверить вручную). Дальше крутится по cron каждые 30 мин.
   Воркфлоу коммитит `seen.json` обратно — дубли не приходят.

---

## 5. Сайт-портфолио

### Вариант А — GitHub Pages
1. Положи содержимое `site/` в отдельный репозиторий **или** включи Pages на этом:
   Settings → Pages → Source: Deploy from branch → `main` / папка `/site` (если поддерживается)
   либо перенеси файлы `site/*` в корень отдельного репо `<логин>.github.io`.
2. Адрес: `https://<логин>.github.io/...`

### Вариант Б — Cloudflare Pages (без карты)
1. https://pages.cloudflare.com → Connect to Git → выбрать репо.
2. Build command: пусто. Output directory: `site`. Deploy.

### Заполнить плейсхолдеры в `site/index.html` (11 штук)
`{{ИМЯ}}`, `{{TELEGRAM}}`, `{{EMAIL}}`, `{{LIVE_URL_1..4}}`, `{{VIDEO_URL_1..4}}` —
подставить реальные значения (ссылки на бота, RAG-демо, видео-обзоры).

---

## 6. Финальный чек-лист «всё в сети»

- [ ] `bash run_all_tests.sh` на сервере → «ВСЕ ТЕСТЫ ПРОШЛИ ✅»
- [ ] `llm.chat(...)` с реальным провайдером возвращает ответ (не `[mock:...]`)
- [ ] Бот отвечает в Telegram (`systemctl status mvp1-bot` = running)
- [ ] RAG отвечает на `http://<IP>:8080/` и цитирует источник
- [ ] n8n workflow активен, тестовый лид доходит до Telegram/Sheets
- [ ] Скаут (Actions) прислал тебе хотя бы один заказ с черновиком
- [ ] Сайт открывается, плейсхолдеры заменены, ссылки на живые демо работают

---

## План Б — если нет загранкарты (Oracle/GCP недоступны)

Бесплатно без карты остаётся:
- **Скаут (MVP4)** — GitHub Actions ✅ (карта не нужна)
- **Сайт** — GitHub/Cloudflare Pages ✅
- **Бот (MVP1) + RAG (MVP3)** — запусти на машине, к которой уже есть доступ
  (этот сервер), под systemd/tmux; для постоянного публичного доступа к RAG —
  туннель Cloudflare (`cloudflared tunnel`, бесплатно, без карты).
- **n8n (MVP2)** — крути локально/в Docker и показывай записью экрана (для демо в портфолио
  живой публичный n8n не обязателен; `reference.py` доказывает логику).

Либо дешёвый РФ-VPS (Timeweb/Beget, ~150–200 ₽/мес) — не бесплатно, но снимает все вопросы
с картами и доступностью.
