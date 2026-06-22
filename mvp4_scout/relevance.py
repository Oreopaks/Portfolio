"""
Оценка релевантности заказа под ОБЛАСТИ компетенций фрилансера (LLM, по одному).

Почему по одному, а не батчем: батч в GigaChat нестабилен (один вход -> то 3
матча, то 0). Одиночный запрос при temperature=0 стабилен по главному решению —
к какой области относится заказ (demo). Само число fit может колебаться ±15,
поэтому ГЕЙТ строится на demo (мусор стабильно получает demo=-1), а fit идёт
на ранжирование/показ.

Фрейм важен: спрашиваем не «тот же ли это продукт», а «заказ из той же ОБЛАСТИ,
где у разработчика опыт» — иначе LLM рубит даже явные бот-заказы как «надо
делать с нуля».

score_orders(orders, profile) -> те же заказы с полями fit/demo/why,
отсортированные по fit убыв. demo=-1 => fit принудительно 0 (в гейт не пройдёт).
"""
from __future__ import annotations
import sys
import json

sys.path.insert(0, "/home/oleg/freelance-mvp")

from shared.llm import chat


# Чёткие границы областей (индексы совпадают с PROFILE["projects"] в draft.py).
# Примеры внутри каждой области критично важны для верного роутинга пограничных
# заказов (напр. «спарсить цены конкурентов» -> 3 парсинг, а не 1 автоматизация).
AREA_GUIDE = (
    "0 = GPT-боты / чат-боты: диалоговый бот на GPT/нейросети в Telegram или на сайте — "
    "поддержка, ответы на вопросы, запись клиентов, FAQ-бот, AI-консультант.\n"
    "1 = AI-автоматизация и интеграции: связать сервисы С УЧАСТИЕМ LLM/нейросети — "
    "n8n/zapier/make + GPT, авто-обработка заявок/звонков/документов, умные рассылки, AI-webhook.\n"
    "2 = RAG / поиск-ответы по документам: вопросы-ответы по базе знаний, PDF, регламентам, "
    "ИИ-ассистент по внутренним документам компании, умный поиск, эмбеддинги, векторный поиск.\n"
    "3 = Парсинг и сбор данных: спарсить сайты/каталоги/маркетплейсы, собрать базу товаров/"
    "цен/объявлений, мониторинг конкурентов и цен, выгрузка в Excel/Google Sheets "
    "(часто как вход к AI-обработке данных)."
)


def _score_one(order: dict, profile: dict) -> dict:
    title = (order.get("title") or "").strip()
    desc = (order.get("desc") or "").strip()[:280]
    category = (order.get("category") or "").strip()

    system = (
        "Ты подбираешь заказы фрилансеру — Python/AI-разработчику. Он берёт ТОЛЬКО AI-задачи: "
        "GPT/нейросети, чат-боты, RAG, AI-автоматизация процессов, парсинг-под-AI. Реши, "
        "относится ли заказ к одной из его ОБЛАСТЕЙ и к какой ИМЕННО (по сути задачи, не по словам). "
        'Ответ — ТОЛЬКО JSON: {"fit":0-100,"demo":<индекс области или -1>,"why":"<кратко>"}. '
        "fit>=70 — явно его область; 40-69 — смежно; <=20 — не его. "
        "НЕ его (fit<=20, demo=-1): копирайт/тексты/SEO, SMM/посты/ведение соцсетей, "
        "лендинги/сайты/вёрстка, графдизайн/логотипы, видео/монтаж, настройка 1С/Битрикс, "
        "мобильная разработка с нуля, инженерия/чертежи, поиск/пробив людей/OSINT/накрутка. "
        "ГЛАВНОЕ правило: если в заказе нет AI / нейросети / бота / данных-под-обработку — "
        "это НЕ его (fit<=20, demo=-1). Выбирай demo строго по описанию ниже."
    )
    user = (
        f"Области (индекс = область):\n{AREA_GUIDE}\n\n"
        f"Заказ: «{title}»" + (f" [категория: {category}]" if category else "")
        + (f"\nОписание: {desc}" if desc else "")
    )
    raw = chat(system, user, temperature=0.0)
    s, e = raw.find("{"), raw.rfind("}")
    obj = {}
    if s != -1 and e > s:
        try:
            obj = json.loads(raw[s : e + 1])
        except Exception:
            obj = {}
    return obj


def score_orders(orders: list[dict], profile: dict, max_items: int = 40) -> list[dict]:
    """LLM-оценка каждого заказа (с лимитом max_items). Поля fit/demo/why; demo=-1
    => fit=0 (не пройдёт гейт). Отсортировано по fit убыв."""
    nprod = len(profile.get("projects", []))
    out: list[dict] = []
    for o in orders[:max_items]:
        try:
            obj = _score_one(o, profile)
        except Exception as ex:
            print(f"[relevance] ошибка оценки: {ex}")
            obj = {}
        try:
            demo = int(obj.get("demo", -1))
        except Exception:
            demo = -1
        try:
            fit = max(0, min(100, int(obj.get("fit", 0))))
        except Exception:
            fit = 0
        if not (0 <= demo < nprod):
            demo, fit = -1, 0  # нет валидной области -> в гейт не пройдёт
        o = dict(o)
        o["fit"] = fit
        o["demo"] = demo
        o["why"] = str(obj.get("why", "")).strip()[:200]
        out.append(o)
    out.sort(key=lambda x: x.get("fit", 0), reverse=True)
    return out
