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

from mvp4_scout.fl_source import fetch_fl_rss, fetch_fl_listing
from mvp4_scout.kwork_source import fetch_kwork
from mvp4_scout.weblancer_source import fetch_weblancer
from mvp4_scout.tg_source import fetch_tg_orders
from mvp4_scout.draft import make_draft, PROFILE
from mvp4_scout.relevance import score_orders
from mvp4_scout.rank import (
    prescore,
    priority,
    win_probability,
    roi,
    verdict,
    keyword_strength,
)

SEEN_PATH = Path(__file__).resolve().parent / "seen.json"

# Настройки берутся из env (с дефолтами), чтобы конфиг жил в Secrets.
# Ключи покрывают ВСЕ 4 области профиля (боты / автоматизация-интеграции / RAG /
# парсинг) — широкая сеть на дешёвом префильтре; точный роутинг по области даёт
# LLM в relevance.py. Совпадение — по началу слова (см. _kw_hit/keyword_strength).
_DEFAULT_KEYWORDS = (
    "бот,чат-бот,GPT,чатгпт,gigachat,yandexgpt,нейросет,ии,llm,openai,ассистент,"  # боты / LLM
    "rag,база знаний,эмбеддинг,векторн,документ,"     # RAG / поиск по документам
    "автоматизаци,интеграци,n8n,zapier,make,webhook,парсинг,парсер,скрапинг,спарсить,"  # автоматизация
    "агент,langchain,голосов,распознаван,компьютерн,ocr,анализ звонк"  # AI-агенты / voice / CV
)
KEYWORDS = [k.strip() for k in os.environ.get("SCOUT_KEYWORDS", _DEFAULT_KEYWORDS).split(",") if k.strip()]
MIN_BUDGET = int(os.environ.get("SCOUT_MIN_BUDGET", "10000"))
# Какие биржи опрашивать (РФ-доступные, регистрация+отклик открыты): fl,kwork,weblancer.
SOURCES = {s.strip() for s in os.environ.get("SCOUT_SOURCES", "fl,kwork,weblancer").split(",") if s.strip()}
KWORK_PAGES = int(os.environ.get("SCOUT_KWORK_PAGES", "2"))           # ~12 заказов/стр
WEBLANCER_PAGES = int(os.environ.get("SCOUT_WEBLANCER_PAGES", "1"))   # ~20 заказов/стр
TG_CHANNELS = [c.strip() for c in os.environ.get("SCOUT_TG_CHANNELS", "").split(",") if c.strip()]

# Человекочитаемые имена бирж для уведомления.
_SOURCE_LABEL = {"fl": "FL.ru", "kwork": "Kwork", "weblancer": "Weblancer", "tg": "Telegram"}
# Порог LLM-релевантности (0-100): ниже — не шлём. Мусор стабильно получает
# demo=-1 -> fit=0. 60 режет слабые «смежно», оставляя уверенные матчи.
FIT_MIN = int(os.environ.get("SCOUT_SCORE_MIN", "60"))
# Объём парсинга: сколько страниц списка тянуть (~30 заказов на страницу).
SCOUT_PAGES = int(os.environ.get("SCOUT_PAGES", "3"))
# Cap на дорогую LLM-оценку: берём топ-K кандидатов по дешёвому pre-score.
SCOUT_TOP_K = int(os.environ.get("SCOUT_TOP_K", "12"))
# Жёсткий потолок откликов — режет только вакансий-спам (100+ откликов). Заказы
# с умеренной конкуренцией НЕ выкидываем: их шанс уходит в win_prob/priority и
# показывается в уведомлении — решает пользователь, а не молчаливый дроп.
MAX_RESPONSES = int(os.environ.get("SCOUT_MAX_RESPONSES", "60"))
# Сколько уведомлений слать за цикл (топ по приоритету) — чтобы не заспамить.
MAX_NOTIFY = int(os.environ.get("SCOUT_MAX_NOTIFY", "10"))

# Чёрный список интентов, которые НЕ берём (пользователь: «такое не нужно»):
# накрутка, OSINT/пробив людей, слежка, гэмблинг, обнал. Дешёвый детерминированный
# отсев до LLM; LLM в relevance.py страхует тем же правилом.
_BLACKLIST = re.compile(
    r"накрут|голосован|цифровой\s+след|пробив|деанон|доксин|компромат|слежк"
    r"|казино|беттинг|ставки\s+на\s+спорт|обнал|отмыв",
    re.IGNORECASE,
)


# Не-AI домены, которые пользователь НЕ берёт (сайты/копирайт/дизайн/SMM/1С-Битрикс).
# Режем ТОЛЬКО если в заказе нет явного AI-сигнала — иначе «чат-бот для сайта» отсеялся бы.
_NONAI = re.compile(
    r"битрикс|\b1с\b|тильда|tilda|wordpress|вордпресс|лендинг|посадочн|верстк"
    r"|\bseo\b|\bsmm\b|копирайт|рерайт|логотип|\bдизайн|инфографик|photoshop|фотошоп|модерац",
    re.IGNORECASE,
)
_AICORE = re.compile(
    r"gpt|gigachat|yandexgpt|deepseek|нейросет|нейронк|\bии\b|\bllm\b|openai|чат-?бот|gpt-?бот"
    r"|\brag\b|база знаний|эмбеддинг|langchain|распознаван\w+ реч|компьютерн\w+ зрени"
    r"|голосов\w+ (?:бот|ассистент)",
    re.IGNORECASE,
)


def _is_blacklisted(o: dict) -> bool:
    text = f"{o.get('title','')} {o.get('desc','')}"
    if _BLACKLIST.search(text):
        return True
    # не-AI домен (сайт/копирайт/дизайн) без AI-сигнала -> не наша ниша
    if _NONAI.search(text) and not _AICORE.search(text):
        return True
    return False


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


def _fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def _fmt_age(h: float | None) -> str:
    if h is None:
        return "?"
    if h < 1:
        return f"{int(h * 60)} мин"
    if h < 48:
        return f"{int(h)} ч"
    return f"{int(h / 24)} дн"


def _dedup(orders: list[dict]) -> list[dict]:
    """Дедуп по url/заголовку, сохраняя порядок."""
    uniq: list[dict] = []
    keys: set[str] = set()
    for o in orders:
        k = o.get("url") or o.get("title")
        if k and k not in keys:
            keys.add(k)
            uniq.append(o)
    return uniq


def run_cycle() -> int:
    """Полный цикл скаута. Возвращает число новых уведомлений."""
    orders: list[dict] = []

    # --- FL.ru: страница списка (число откликов/возраст/просмотры). RSS — фоллбэк.
    if "fl" in SOURCES:
        fl_orders: list[dict] = []
        try:
            fl_orders = fetch_fl_listing(SCOUT_PAGES)
        except Exception as e:
            print(f"[scout] FL.ru listing недоступен: {e}")
        if not fl_orders:  # смена вёрстки/сеть -> RSS (без откликов/возраста)
            try:
                fl_orders = fetch_fl_rss()
                print("[scout] листинг пуст — фоллбэк на RSS")
            except Exception as e:
                print(f"[scout] FL.ru RSS недоступен: {e}")
        for o in fl_orders:
            o.setdefault("source", "fl")
        orders.extend(fl_orders)

    # --- Kwork: крупнейшая РФ-биржа, всё в рублях, встроенный JSON с откликами.
    if "kwork" in SOURCES:
        try:
            orders.extend(fetch_kwork(KWORK_PAGES))
        except Exception as e:
            print(f"[scout] Kwork недоступен: {e}")

    # --- Weblancer: SSR-карточки с числом заявок (бюджет берём только в рублях).
    if "weblancer" in SOURCES:
        try:
            orders.extend(fetch_weblancer(WEBLANCER_PAGES))
        except Exception as e:
            print(f"[scout] Weblancer недоступен: {e}")

    # Telegram (только если заданы каналы; иначе пропустит само)
    if TG_CHANNELS:
        try:
            tg_orders = fetch_tg_orders(TG_CHANNELS)
            for o in tg_orders:
                o.setdefault("source", "tg")
            orders.extend(tg_orders)
        except Exception as e:
            print(f"[scout] Telegram недоступен: {e}")

    uniq = _dedup(orders)

    # --- Дешёвые ДЕТЕРМИНИРОВАННЫЕ префильтры (без LLM) -----------------------
    step = [o for o in uniq if not _is_blacklisted(o)]                      # «такое не нужно»
    step = [o for o in step if o.get("budget") is None or o["budget"] >= MIN_BUDGET]
    step = [o for o in step if keyword_strength(f"{o.get('title','')} {o.get('desc','')}", KEYWORDS) > 0]
    step = [o for o in step if (o.get("responses") or 0) <= MAX_RESPONSES]  # не безнадёжно

    # Дедуп против уже отправленных ДО LLM (не жжём модель на старом).
    seen = _load_seen()
    step = [o for o in step if (o.get("url") or o.get("title")) not in seen]

    # Pre-score -> топ-K под дорогую LLM (цена/время самого скаута).
    for o in step:
        o["pre"] = prescore(o, KEYWORDS)
    step.sort(key=lambda o: o["pre"], reverse=True)
    candidates = step[:SCOUT_TOP_K]
    print(f"[scout] собрано {len(orders)} -> уник {len(uniq)} -> кандидатов {len(step)} -> в LLM {len(candidates)}")

    # --- LLM: тема + область компетенции -------------------------------------
    scored = score_orders(candidates, PROFILE)

    # --- Деловые сигналы + итоговый приоритет + гейт -------------------------
    final: list[dict] = []
    for o in scored:
        demo, fit = o.get("demo", -1), o.get("fit", 0)
        o["win_prob"] = win_probability(o.get("responses"), o.get("age_hours"))
        o["roi"] = roi(o.get("budget"), demo)
        o["priority"] = priority(fit, o["win_prob"], o["roi"])
        if demo >= 0 and fit >= FIT_MIN:
            final.append(o)
    final.sort(key=lambda o: o["priority"], reverse=True)
    final = final[:MAX_NOTIFY]
    print(f"[scout] прошли гейт (fit>={FIT_MIN}): {len(final)}")

    sent = 0
    for o in final:
        demo = o.get("demo", -1)
        try:
            draft = make_draft(o, PROFILE, focus=demo)
        except Exception as e:
            draft = f"(не удалось сгенерировать отклик: {e})"
        budget = o.get("budget")
        budget_str = f"{_fmt_int(budget)} ₽" if budget else "по договорённости"
        rv = o.get("roi")
        roi_str = f" (~{_fmt_int(rv)} ₽/день)" if rv else ""
        resp = o.get("responses")
        resp_str = str(resp) if resp is not None else "—"
        demo_name = PROFILE["projects"][demo]["name"] if 0 <= demo < len(PROFILE["projects"]) else "—"
        src = _SOURCE_LABEL.get(o.get("source"), o.get("source") or "—")
        text = (
            f"🆕 [{src}] «{demo_name}» · приоритет {int(o.get('priority', 0))}\n"
            f"{o.get('title')}\n"
            f"💰 Бюджет: {budget_str}{roi_str}\n"
            f"📊 Откликов: {resp_str} · возраст {_fmt_age(o.get('age_hours'))} · шанс ~{int(o['win_prob'] * 100)}%\n"
            f"{verdict(o)}\n"
            f"🔗 {o.get('url')}\n"
            f"💡 fit {o.get('fit')}% — {o.get('why', '')}\n\n"
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
