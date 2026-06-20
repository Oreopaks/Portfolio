"""
ДЕТЕРМИНИРОВАННАЯ оценка релевантности заказа под готовые продукты.

Почему не LLM-оценка: GigaChat на батче нестабилен (один и тот же вход даёт
то 3 матча, то 0) — поток получается рваный. Здесь — чистые правила:
категория уже отфильтрована в scout, а тут считаем совпадения ключей каждого
демо в заголовке+описании. Один вход -> один выход. LLM используется только
для текста отклика (make_draft), не для решения «слать/не слать».

score_orders(orders, profile) -> те же заказы с полями:
  fit  — 0..100 (по силе совпадения ключей),
  demo — индекс самого близкого продукта (0..N-1) или -1,
  why  — какие ключи сработали.
"""
from __future__ import annotations
import re

# Ключи под каждый продукт. Индекс == индексу в PROFILE["projects"] (draft.py):
#   0 GPT-бот, 1 n8n-автоматизация, 2 RAG, 3 Скаут/парсинг.
DEMO_KEYWORDS = {
    0: ["бот", "чат-бот", "чатбот", "gpt", "ассистент", "автоответ", "автоответчик",
        "диалог", "нейросотрудник", "нейроассистент", "саппорт", "поддержк", "faq",
        "telegram-бот", "телеграм-бот", "консультант", "запись клиент", "записи клиент"],
    1: ["автоматизац", "автоматизировать", "n8n", "zapier", "make.com", "integromat",
        "интеграц", "webhook", "вебхук", "crm", "amocrm", "битрикс", "bitrix",
        "заявк", "лид", "воронк", "сценари", "пайплайн", "рассылк", "уведомлен"],
    2: ["rag", "retrieval", "база знаний", "базе знаний", "документ", "pdf", "docx",
        "регламент", "инструкци", "поиск по", "ответы по", "векторн", "эмбеддинг",
        "knowledge base"],
    3: ["парс", "парсер", "парсинг", "scrap", "скрейп", "скрапинг", "сбор данных",
        "собрать данны", "собрать информаци", "мониторинг", "выгрузк", "спарсить",
        "граббер", "crawler", "краулер", "агрегат"],
}


def _hits(text: str, keywords: list[str]) -> list[str]:
    """Какие ключи сработали. Однословные — по началу слова (чтобы «бот» не ловил
    «работа»); фразы со пробелом/дефисом-словом — по подстроке."""
    hit = []
    words = re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9]+", text.lower())
    wordset_starts = words  # для проверки startswith
    low = text.lower()
    for kw in keywords:
        if " " in kw or "." in kw:  # фраза — подстрокой
            if kw in low:
                hit.append(kw)
        else:
            if any(w.startswith(kw) for w in wordset_starts):
                hit.append(kw)
    return hit


def score_orders(orders: list[dict], profile: dict, max_items: int = 200) -> list[dict]:
    """Детерминированно оценить заказы. Возвращает с полями fit/demo/why,
    отсортированные по fit убыв."""
    nprod = len(profile.get("projects", []))
    out: list[dict] = []
    for o in orders[:max_items]:
        title = (o.get("title") or "")
        desc = (o.get("desc") or "")
        best_demo, best_fit, best_why = -1, 0, ""
        for demo, kws in DEMO_KEYWORDS.items():
            if demo >= nprod:
                continue
            th = _hits(title, kws)
            dh = _hits(desc, kws)
            uniq = set(th) | set(dh)
            if not uniq:
                continue
            # релевантно, если ключ в ЗАГОЛОВКЕ, либо >=2 разных ключа в описании
            if not th and len(uniq) < 2:
                continue
            fit = min(100, 55 + 25 * len(th) + 10 * (len(uniq) - len(set(th))))
            if fit > best_fit:
                best_demo, best_fit, best_why = demo, fit, ", ".join(sorted(uniq))
        o = dict(o)
        o["fit"] = best_fit
        o["demo"] = best_demo
        o["why"] = (f"ключи: {best_why}" if best_why else "нет совпадений")
        out.append(o)
    out.sort(key=lambda x: x.get("fit", 0), reverse=True)
    return out
