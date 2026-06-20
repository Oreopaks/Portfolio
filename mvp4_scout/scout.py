"""
ORDER SCOUT — главный цикл.

Собирает заказы (FL.ru + опц. Telegram) -> фильтрует по бюджету+ключам ->
отсеивает уже виденные (seen.json) -> генерит отклик на каждый ->
шлёт уведомление в Telegram.

CLI: python mvp4_scout/scout.py
"""
from __future__ import annotations
import os
import re
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, "/home/oleg/freelance-mvp")

import shared.config  # noqa: F401  — подхватывает .env

try:
    import requests
except ImportError:
    requests = None

from mvp4_scout.fl_source import fetch_fl_rss, fetch_fl_orders
from mvp4_scout.tg_source import fetch_tg_orders
from mvp4_scout.draft import make_draft, PROFILE
from mvp4_scout.relevance import score_orders

SEEN_PATH = Path(__file__).resolve().parent / "seen.json"

# Настройки берутся из env (с дефолтами), чтобы конфиг жил в Secrets.
KEYWORDS = [k.strip() for k in os.environ.get("SCOUT_KEYWORDS", "бот,парсинг,автоматизация,GPT,Telegram").split(",") if k.strip()]
MIN_BUDGET = int(os.environ.get("SCOUT_MIN_BUDGET", "10000"))
TG_CHANNELS = [c.strip() for c in os.environ.get("SCOUT_TG_CHANNELS", "").split(",") if c.strip()]
# Порог умной оценки релевантности (0-100): ниже — не шлём.
SCORE_MIN = int(os.environ.get("SCOUT_SCORE_MIN", "70"))

# Whitelist категорий FL.ru под демо (бот/AI/автоматизация/парсинг/данные/разработка).
# Детерминированно отсекает видео/дизайн/инженерию/фото до дорогой LLM-оценки.
_CAT_OK = re.compile(
    r"бот|ai|искусственн|нейросет|gpt|чат|telegram|автоматизац|парс|скрейп|scrap"
    r"|crm|интеграц|данн|data|python|api|скрипт|программир|разработк",
    re.IGNORECASE,
)


def _category_ok(cat: str) -> bool:
    """True, если категория пустая (источник без категории) или попадает в whitelist."""
    cat = (cat or "").strip()
    return not cat or bool(_CAT_OK.search(cat))


def _kw_hit(title: str, kws: list[str]) -> bool:
    """Совпадение ключа по НАЧАЛУ слова, не подстрокой.

    Иначе короткий ключ «бот» ловит «разрабоТКА»/«дораБОТка»/«раБОТа»
    (внутри «работ» сидит «бот») и фильтр тонет в мусоре.
    Токен считается хитом, если начинается с ключа: «бот»→«бота»,«ботом»;
    «автоматизаци»→«автоматизация». «работа» уже НЕ матчит «бот».
    """
    if not kws:
        return False
    words = re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9]+", title.lower())
    return any(w.startswith(k) for w in words for k in kws)


def filter_orders(orders: list[dict], min_budget: int, keywords: list[str]) -> list[dict]:
    """Оставляем релевантные заказы.

    - budget >= min_budget И совпадение по ключу -> оставляем;
    - budget None -> оставляем ТОЛЬКО при совпадении по ключу (по началу слова);
    - дедуп по заголовку.
    """
    kws = [k.lower() for k in keywords]
    seen_titles: set[str] = set()
    result: list[dict] = []
    for o in orders:
        title = (o.get("title") or "").strip()
        if not title:
            continue
        if title in seen_titles:
            continue

        kw_hit = _kw_hit(title, kws)
        budget = o.get("budget")

        if budget is None:
            keep = kw_hit  # без бюджета — только при сильном совпадении по ключу
        else:
            keep = budget >= min_budget and (kw_hit or not kws)

        if keep:
            seen_titles.add(title)
            result.append(o)
    return result


def _load_seen() -> set[str]:
    if SEEN_PATH.exists():
        try:
            return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=0), encoding="utf-8")


def notify(text: str) -> None:
    """Отправка уведомления в Telegram. No-op (печать), если токен/чат не заданы."""
    token = os.environ.get("SCOUT_NOTIFY_TOKEN")
    chat_id = os.environ.get("SCOUT_NOTIFY_CHAT_ID")
    if not token or not chat_id:
        print("[notify] токен/чат не заданы — печатаю локально:\n" + text + "\n")
        return
    if requests is None:
        print("[notify] requests не установлен — печатаю локально:\n" + text + "\n")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": False},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[notify] Telegram {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[notify] ошибка отправки: {e}")


def run_cycle() -> int:
    """Полный цикл скаута. Возвращает число новых уведомлений."""
    orders: list[dict] = []

    # FL.ru — основной источник через RSS-фид (чистый, с категорией и описанием)
    try:
        orders.extend(fetch_fl_rss())
    except Exception as e:
        print(f"[scout] FL.ru RSS недоступен: {e}")

    # Telegram (только если заданы каналы; иначе пропустит само)
    if TG_CHANNELS:
        try:
            orders.extend(fetch_tg_orders(TG_CHANNELS))
        except Exception as e:
            print(f"[scout] Telegram недоступен: {e}")

    # дедуп по url/заголовку
    uniq: list[dict] = []
    seen_keys: set[str] = set()
    for o in orders:
        k = o.get("url") or o.get("title")
        if k and k not in seen_keys:
            seen_keys.add(k)
            uniq.append(o)

    # whitelist категорий: отсекаем явно не-IT (видео/дизайн/инженерия) до LLM
    in_cat = [o for o in uniq if _category_ok(o.get("category", ""))]

    # бюджет-префильтр: режем числовые ниже порога (None оставляем — решит оценщик)
    pre = [o for o in in_cat if o.get("budget") is None or o["budget"] >= MIN_BUDGET]
    print(f"[scout] собрано {len(orders)} -> уник {len(uniq)} -> по категории {len(in_cat)} -> по бюджету {len(pre)}")

    # умная LLM-оценка релевантности под готовые продукты
    scored = score_orders(pre, PROFILE)
    relevant = [o for o in scored if o.get("fit", 0) >= SCORE_MIN]
    print(f"[scout] релевантных (fit>={SCORE_MIN}): {len(relevant)}")

    seen = _load_seen()
    new = [o for o in relevant if (o.get("url") or o.get("title")) not in seen]
    print(f"[scout] новых (не виденных ранее): {len(new)}")

    sent = 0
    for o in new:
        demo = o.get("demo", -1)
        try:
            draft = make_draft(o, PROFILE, focus=demo)
        except Exception as e:
            draft = f"(не удалось сгенерировать отклик: {e})"
        budget = o.get("budget")
        budget_str = f"{budget} руб" if budget else "по договорённости"
        demo_name = PROFILE["projects"][demo]["name"] if 0 <= demo < len(PROFILE["projects"]) else "—"
        text = (
            f"🆕 Заказ под «{demo_name}» (релевантность {o.get('fit')}%)\n"
            f"{o.get('title')}\n"
            f"Бюджет: {budget_str}\n"
            f"{o.get('url')}\n"
            f"💡 {o.get('why', '')}\n\n"
            f"✍️ Черновик отклика:\n{draft}"
        )
        notify(text)
        seen.add(o.get("url") or o.get("title"))
        sent += 1
        time.sleep(0.2)  # лёгкий троттлинг telegram-api

    _save_seen(seen)
    print(f"[scout] отправлено уведомлений: {sent}")
    return sent


if __name__ == "__main__":
    run_cycle()
