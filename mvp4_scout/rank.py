"""
Деловая модель ранжирования заказа — ДЕТЕРМИНИРОВАННАЯ, без сети и без LLM.

Релевантность («мой ли это профиль») даёт LLM в relevance.py. Здесь — вторая,
не менее важная половина: СТОИТ ЛИ вообще на заказ откликаться. На фрилансе
решает не только тема, но и:

  • сколько уже откликов  — чем больше конкурентов, тем ниже шанс взять заказ;
  • насколько заказ свежий — ранний отклик ловит заказчика, пока он выбирает;
  • цена ÷ время          — 30 000 ₽ за 5 дней хуже, чем 15 000 ₽ за 1 день.

Все функции чистые → гоняются офлайн-тестами без моков.
"""
from __future__ import annotations
import re
from datetime import datetime

# Оценка трудоёмкости по областям (индексы = PROFILE["projects"] в draft.py),
# в рабочих днях. Грубо, но честно: ROI = бюджет / дни → ₽ в день.
EFFORT_DAYS = {0: 3.0, 1: 2.0, 2: 5.0, 3: 2.0}
DEFAULT_EFFORT_DAYS = 3.0

# Опорная дневная ставка (₽/день) для нормировки ROI. ~8000 — крепкий день
# разработчика на РФ-бирже: ниже — ставка слабая, выше — хорошая.
ROI_REF = 8000.0


def parse_age_hours(s: str | None) -> float | None:
    """«19 часов 37 минут назад» / «2 дня назад» / «1 час назад» -> часы (float).

    None, если строки нет или ничего не распознали (возраст неизвестен).
    """
    if not s:
        return None
    h = 0.0
    for num, unit in re.findall(r"(\d+)\s*(минут\w*|мин|часов|часа|час|дн\w*|день|недел\w*)", s.lower()):
        n = int(num)
        if unit.startswith("мин"):
            h += n / 60.0
        elif unit.startswith("час"):
            h += n
        elif unit.startswith(("дн", "день")):
            h += n * 24.0
        elif unit.startswith("недел"):
            h += n * 168.0
    return round(h, 2) if h > 0 else None


_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def ru_date_age_hours(date_str: str | None, now: datetime | None = None) -> float | None:
    """«21 июня» / «3 июля» -> возраст в часах относительно now. None, если не распознали.

    Kwork отдаёт дату заказа днём, без времени -> берём начало того дня. Если
    дата оказалась в будущем (конец декабря при текущем январе) -> прошлый год.
    """
    if not date_str:
        return None
    m = re.search(r"(\d{1,2})\s+([а-яё]+)", date_str.lower())
    if not m:
        return None
    day = int(m.group(1))
    pref = m.group(2)[:3]
    mon = next((v for k, v in _RU_MONTHS.items() if pref.startswith(k)), None)
    if mon is None:
        return None
    now = now or datetime.now()
    try:
        dt = datetime(now.year, mon, day)
    except ValueError:
        return None
    if dt > now:
        try:
            dt = datetime(now.year - 1, mon, day)
        except ValueError:
            return None
    return round(max(0.0, (now - dt).total_seconds() / 3600.0), 2)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def win_probability(responses: int | None, age_hours: float | None) -> float:
    """Грубая вероятность взять заказ [0..1].

    Главный фактор — конкуренция (число откликов): заказчик выбирает из
    первых нескольких, поэтому шанс ~ 1/(1+откликов/6). Свежесть модулирует
    ±50%: свежий заказ с парой откликов — горячий, протухший — вялый.
    Неизвестный возраст -> нейтральная свежесть 0.5.
    """
    r = responses if responses is not None else 0
    comp = 1.0 / (1.0 + max(0, r) / 6.0)          # 0->1.0, 6->0.5, 18->0.25, 30->0.17
    if age_hours is None:
        fresh = 0.5
    else:
        fresh = _clamp(1.0 - age_hours / 72.0, 0.2, 1.0)  # 0ч->1.0, 36ч->0.5, >=72ч->0.2
    return round(comp * (0.5 + 0.5 * fresh), 3)


def roi(budget: int | None, area: int) -> float | None:
    """Ставка в ₽/день = бюджет / оценка трудоёмкости области. None, если бюджета нет."""
    if not budget:
        return None
    days = EFFORT_DAYS.get(area, DEFAULT_EFFORT_DAYS)
    return round(budget / days, 0)


def _budget_signal(budget: int | None) -> float:
    """Бюджет -> [0..1] для пре-скоринга. None (по договорённости) = нейтрально 0.5."""
    if not budget:
        return 0.5
    return _clamp(budget / 50000.0, 0.1, 1.0)


def keyword_strength(text: str, keywords: list[str]) -> float:
    """Сила темы по числу попавших ключей профиля (по началу слова) -> [0..1].

    Нормировка по АБСОЛЮТНОМУ числу совпадений, а не по размеру словаря:
    1 ключ -> 0.5, 2+ -> 1.0. Иначе расширение списка ключей под все области
    профиля разбавляло бы сигнал и роняло пре-скор тематичных заказов.
    0 -> заказ вне профиля (в кандидаты под дорогую LLM не берём).
    """
    if not keywords:
        return 0.0
    words = re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9]+", text.lower())
    kws = [k.lower() for k in keywords]
    hit = sum(1 for k in kws if any(w.startswith(k) for w in words))
    return _clamp(hit / 2.0, 0.0, 1.0)


def prescore(order: dict, keywords: list[str]) -> float:
    """Дешёвый пре-LLM скор [0..100]: тема(ключи) + winnability + бюджет.

    По нему отбираем топ-K кандидатов под дорогую LLM-оценку — чтобы не жечь
    модель на каждом из ~90 собранных заказов (соотношение цены и времени
    самого скаута).
    """
    kw = keyword_strength(f"{order.get('title','')} {order.get('desc','')}", keywords)
    wp = win_probability(order.get("responses"), order.get("age_hours"))
    bs = _budget_signal(order.get("budget"))
    return round(100.0 * (0.55 * kw + 0.30 * wp + 0.15 * bs), 1)


def priority(fit: int, win_prob: float, roi_value: float | None) -> float:
    """Итоговый приоритет [0..100] = LLM-fit, промодулированный winnability и ROI.

    fit задаёт потолок (нерелевантное не всплывёт), winnability и ставка
    решают порядок среди релевантных.
    """
    base = fit * (0.45 + 0.55 * win_prob)
    if roi_value is None:
        rf = 0.9                                   # бюджет неизвестен — лёгкий дисконт
    else:
        rf = _clamp(roi_value / ROI_REF, 0.6, 1.15)
    return round(min(100.0, base * rf), 1)


def verdict(order: dict) -> str:
    """Короткий человекочитаемый вердикт по деловым сигналам (для уведомления)."""
    parts: list[str] = []
    wp = order.get("win_prob", 0.0)
    r = order.get("responses")
    age = order.get("age_hours")

    if wp >= 0.6:
        parts.append("🔥 горячий")
    elif wp < 0.3:
        parts.append("🥶 шанс низкий")

    if r is not None:
        if r >= 20:
            parts.append(f"много откликов ({r})")
        elif r <= 3:
            parts.append(f"мало откликов ({r})")
        else:
            parts.append(f"откликов: {r}")

    if age is not None and age <= 3:
        parts.append("свежий")

    rv = order.get("roi")
    if rv is not None:
        if rv >= ROI_REF * 1.1:
            parts.append(f"💰 ставка ~{int(rv):,} ₽/день".replace(",", " "))
        elif rv < ROI_REF * 0.6:
            parts.append(f"⚠️ слабая ставка ~{int(rv):,} ₽/день".replace(",", " "))
    return " · ".join(parts)
