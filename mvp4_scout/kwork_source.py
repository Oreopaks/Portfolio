"""
Источник заказов: Kwork (kwork.ru) — крупнейшая РФ-биржа.

Страница /projects отдаёт список заказов («wants») прямо в HTML встроенным
JSON-состоянием. Парсим этот JSON — надёжнее и богаче, чем скрести вёрстку:
есть бюджет, число откликов и дата создания.

Регистрация и отклик доступны из РФ (сервис российский). Все бюджеты в рублях.

parse_kwork(html, now) — ЧИСТАЯ функция (без сети), для офлайн-тестов.
fetch_kwork(pages)    — боевая: ходит в сеть и зовёт parse_kwork.
"""
from __future__ import annotations
import re
import json
from datetime import datetime

from mvp4_scout.rank import ru_date_age_hours

try:
    import requests
except ImportError:  # офлайн-тест с parse_kwork сети не требует
    requests = None

LISTING_URL = "https://kwork.ru/projects"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_ENTITIES = {
    "&laquo;": "«", "&raquo;": "»", "&nbsp;": " ", "&mdash;": "—",
    "&ndash;": "–", "&amp;": "&", "&quot;": '"', "&#39;": "'", "&hellip;": "…",
}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    s = _TAG_RE.sub(" ", s or "")
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def _extract_wants(html: str) -> list[dict]:
    """Вырезать массив "wants":[...] из встроенного JSON и распарсить. [] если нет.

    Сканер уважает строки (скобки внутри "..." не считает), иначе «[» в описании
    заказа сломал бы подсчёт глубины.
    """
    i = html.find('"wants":[')
    if i < 0:
        return []
    start = html.find("[", i)
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : j + 1])
                except Exception:
                    return []
    return []


def parse_kwork(html: str, now: datetime | None = None) -> list[dict]:
    """HTML страницы kwork.ru/projects -> заказы. Без сети.

    budget = верхняя граница (possiblePriceLimit), в рублях; fallback на priceLimit.
    responses = kwork_count (число откликов); age из wantDates.dateCreate.
    """
    out: list[dict] = []
    for w in _extract_wants(html):
        try:
            pid = w.get("id")
            title = _clean(str(w.get("name", "")))
            if not pid or not title:
                continue

            budget = w.get("possiblePriceLimit")
            if budget:
                budget = int(budget)
            else:
                pl = w.get("priceLimit")
                try:
                    budget = int(float(pl)) if pl else None
                except (TypeError, ValueError):
                    budget = None

            resp = w.get("kwork_count")
            resp = int(resp) if resp is not None else None
            date_create = (w.get("wantDates") or {}).get("dateCreate")

            out.append(
                {
                    "title": title,
                    "budget": budget,
                    "url": f"https://kwork.ru/projects/{pid}/view",
                    "desc": _clean(str(w.get("description", "")))[:400],
                    "responses": resp,
                    "age_hours": ru_date_age_hours(date_create, now),
                    "views": None,
                    "source": "kwork",
                }
            )
        except Exception:  # один битый want не валит весь разбор
            continue
    return out


def fetch_kwork(pages: int = 2) -> list[dict]:
    """Боевая: тянет N страниц списка заказов Kwork и парсит. Использует сеть."""
    if requests is None:
        raise RuntimeError("requests не установлен — fetch_kwork недоступен")
    out: list[dict] = []
    for page in range(1, max(1, pages) + 1):
        url = LISTING_URL + (f"?page={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "ru"}, timeout=40)
            if r.status_code != 200:
                print(f"[kwork] {url} -> HTTP {r.status_code}")
                continue
            out.extend(parse_kwork(r.text))
        except Exception as e:  # сеть может падать — не валим весь цикл
            print(f"[kwork] ошибка запроса {url}: {e}")
    return out
