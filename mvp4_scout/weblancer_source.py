"""
Источник заказов: Weblancer (weblancer.net).

Страница /freelance/ отрисована на сервере — карточки заказов лежат в HTML.
Из каждой берём заголовок, число откликов («N заявок») и бюджет.

Биржа мультивалютная (₽/$/грн). Для честного RUB-фильтра «чек 10k+» берём
бюджет ТОЛЬКО когда он в рублях (руб/₽); иначе budget=None («по договорённости»)
— такой заказ дойдёт до LLM лишь при совпадении по ключу.

Доступна из РФ, регистрация и отклик открыты.

parse_weblancer(html) — ЧИСТАЯ функция (без сети), для офлайн-тестов.
fetch_weblancer(pages) — боевая: ходит в сеть и зовёт parse_weblancer.
"""
from __future__ import annotations
import re

try:
    import requests
except ImportError:  # офлайн-тест с parse_weblancer сети не требует
    requests = None

LISTING_URL = "https://www.weblancer.net/freelance/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Ссылка-карточка заказа: /freelance/<категория>/<slug>-<id>/
_LINK_RE = re.compile(r'href="(/freelance/[a-z0-9-]+/[a-z0-9-]+-(\d+)/)"')
# Текст заголовка — сразу за href в том же <a>...</a>
_TITLE_RE = re.compile(r">([^<]{3,140})</a>")
# Бюджет ТОЛЬКО в рублях (руб/₽); $ и грн игнорируем -> None.
_BUDGET_RUB_RE = re.compile(r"(\d[\d\s ]{2,})\s*(?:руб|₽)")
_RESP_RE = re.compile(r"(\d+)\s*заявок")
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITIES = {"&nbsp;": " ", "&laquo;": "«", "&raquo;": "»", "&amp;": "&", "&mdash;": "—"}


def _clean(s: str) -> str:
    s = _TAG_RE.sub(" ", s or "")
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def parse_weblancer(html: str) -> list[dict]:
    """HTML страницы weblancer.net/freelance/ -> заказы. Без сети.

    Поля: title, budget(int|None — только руб), url, desc, responses(int|None),
    age_hours(None — на карточках нет), views(None), source.
    """
    if not html:
        return []
    cards = list(_LINK_RE.finditer(html))
    out: list[dict] = []
    for idx, m in enumerate(cards):
        href = m.group(1)
        start = m.start()
        end = cards[idx + 1].start() if idx + 1 < len(cards) else min(len(html), start + 1500)

        tm = _TITLE_RE.search(html[start : start + 400])
        title = tm.group(1).strip() if tm else ""
        if not title:
            continue

        text = _clean(html[start:end])

        budget = None
        bm = _BUDGET_RUB_RE.search(text)
        if bm:
            digits = re.sub(r"\D", "", bm.group(1))
            if digits:
                budget = int(digits)

        rm = _RESP_RE.search(text)
        responses = int(rm.group(1)) if rm else None

        desc = text.split(title, 1)[1].strip() if title in text else text

        out.append(
            {
                "title": title,
                "budget": budget,
                "url": f"https://www.weblancer.net{href}",
                "desc": desc[:400],
                "responses": responses,
                "age_hours": None,
                "views": None,
                "source": "weblancer",
            }
        )
    return out


def fetch_weblancer(pages: int = 1) -> list[dict]:
    """Боевая: тянет N страниц списка заказов Weblancer и парсит. Использует сеть."""
    if requests is None:
        raise RuntimeError("requests не установлен — fetch_weblancer недоступен")
    out: list[dict] = []
    for page in range(1, max(1, pages) + 1):
        url = LISTING_URL + (f"?page={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "ru"}, timeout=40)
            if r.status_code != 200:
                print(f"[weblancer] {url} -> HTTP {r.status_code}")
                continue
            out.extend(parse_weblancer(r.text))
        except Exception as e:  # сеть может падать — не валим весь цикл
            print(f"[weblancer] ошибка запроса {url}: {e}")
    return out
