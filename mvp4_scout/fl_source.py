"""
Источник заказов: FL.ru.

parse_orders(html) — ЧИСТАЯ функция (без сети), парсит HTML списка проектов.
                     Используется в офлайн-тестах.
fetch_fl_orders(...) — боевая: ходит в сеть через requests и зовёт parse_orders.

Разметка FL.ru (проверено на живой странице):
  - Заголовок проекта — якорь со спец-именем:
      <a ... name="prj5510341" href="/projects/5510341/<slug>.html">НАЗВАНИЕ</a>
    (брать именно его, а не первый <a> в карточке — там кнопка «Откликнуться»).
  - Бюджет — число с разделителем &nbsp; прямо перед span.fl-rub:
      4&nbsp;000&nbsp;<span class="fl-rub">...руб...</span>
  - «по договорённости» — блока fl-rub нет, бюджет = None.
"""
from __future__ import annotations
import re
import urllib.parse
import xml.etree.ElementTree as ET

from mvp4_scout.rank import parse_age_hours

try:
    import requests
except ImportError:  # офлайн-тест с parse_orders сети не требует
    requests = None

# Официальный RSS-фид FL.ru: чистый список свежих проектов с категорией,
# описанием и бюджетом. Работает без авторизации (в отличие от ?keyword=,
# который для гостя игнорируется и отдаёт общую ленту).
RSS_URL = "https://www.fl.ru/rss/all.xml"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Якорь-заголовок проекта: name="prj<id>" + href на .html
_TITLE_RE = re.compile(
    r'name="prj\d+"\s+href="/projects/(\d+)/[^"]+\.html"[^>]*>([^<]{3,160})</a>'
)
# Число (с &nbsp; и пробелами) непосредственно перед маркером валюты fl-rub
_NUM_BEFORE_RUB = re.compile(r'((?:\d|&nbsp;|\s){1,24})<span class="fl-rub"')
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITIES = {
    "&nbsp;": " ", "&laquo;": "«", "&raquo;": "»", "&mdash;": "—",
    "&ndash;": "–", "&amp;": "&", "&quot;": '"', "&#39;": "'", "&hellip;": "…",
}


def _clean_text(s: str) -> str:
    """HTML-фрагмент -> чистый текст (теги долой, сущности раскрыть, пробелы свернуть)."""
    s = _TAG_RE.sub(" ", s)
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def parse_orders(html: str) -> list[dict]:
    """HTML списка проектов FL.ru -> [{"title","budget"(int|None),"url"}]. Без сети."""
    if not html:
        return []
    matches = list(_TITLE_RE.finditer(html))
    orders: list[dict] = []
    for idx, m in enumerate(matches):
        pid = m.group(1)
        title = re.sub(r"\s+", " ", m.group(2)).strip()

        # тело карточки — от конца заголовка до начала следующего (или окно 3000)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(html), start + 3000)
        body = html[start:end]

        budget = None
        nm = _NUM_BEFORE_RUB.search(body)
        if nm:
            digits = re.sub(r"\D", "", nm.group(1).replace("&nbsp;", ""))
            if digits:
                budget = int(digits)

        # Описание заказа: чистый текст тела карточки (для смысловой оценки).
        desc = _clean_text(body)[:400]

        orders.append(
            {
                "title": title,
                "budget": budget,
                "url": f"https://www.fl.ru/projects/{pid}/",
                "desc": desc,
            }
        )
    return orders


_RSS_BUDGET_RE = re.compile(r"\(Бюджет:\s*([\d\s ]+)")


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """RSS FL.ru -> [{"title","budget"(int|None),"url","desc","category"}]. Без сети.

    Заголовок в RSS вида: «НАЗВАНИЕ (Бюджет: 15 000  ₽, для всех)».
    Бюджет вытаскиваем из этого суффикса, сам суффикс из title убираем.
    """
    root = ET.fromstring(xml_bytes)
    orders: list[dict] = []
    for it in root.findall(".//item"):
        def g(tag: str) -> str:
            e = it.find(tag)
            return (e.text or "").strip() if e is not None else ""

        raw_title = g("title")
        budget = None
        m = _RSS_BUDGET_RE.search(raw_title)
        if m:
            digits = re.sub(r"\D", "", m.group(1))
            if digits:
                budget = int(digits)
        title = re.sub(r"\s*\(Бюджет:.*$", "", raw_title).strip() or raw_title

        orders.append(
            {
                "title": title,
                "budget": budget,
                "url": g("link"),
                "desc": _clean_text(g("description"))[:500],
                "category": g("category"),
            }
        )
    return orders


def fetch_fl_rss() -> list[dict]:
    """Боевая: тянет RSS-фид FL.ru и парсит. Использует сеть."""
    if requests is None:
        raise RuntimeError("requests не установлен — fetch_fl_rss недоступен")
    r = requests.get(RSS_URL, headers={"User-Agent": _UA}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"FL.ru RSS -> HTTP {r.status_code}")
    return parse_rss(r.content)


# ---------------------------------------------------------------------------
# Страница списка проектов fl.ru/projects/ — БОГАЧЕ RSS: в каждой карточке
# отрисованы число откликов, возраст заказа и просмотры. Это и есть сигналы
# «стоит ли откликаться» (конкуренция + свежесть), которых нет ни в RSS, ни
# на странице самого заказа (там счётчик откликов догружается через JS).
# ---------------------------------------------------------------------------
LISTING_URL = "https://www.fl.ru/projects/"

# Заголовок-якорь карточки: name="prj<id>" + href на .html (как в parse_orders).
_CARD_RE = re.compile(
    r'name="prj(\d+)"\s+href="(/projects/\d+/[^"]+\.html)"[^>]*>([^<]{3,200})</a>'
)
_BUDGET_RUB_RE = re.compile(r"(\d[\d\s ]{1,12})\s*руб")
# Иконка #message-empty -> рядом «N ответов» (счётчик откликов карточки).
_RESP_RE = re.compile(r"#message-empty.{0,400}?(\d+)\s*ответ", re.S)
# Иконка #eye-open -> следующий <span> с числом просмотров («больше 300» / «42»).
_VIEWS_RE = re.compile(r"#eye-open.{0,400}?<span[^>]*>\s*(больше\s*\d+|\d+)", re.S)
# «Заказ 19 часов 37 минут назад» — возраст заказа.
_AGE_RE = re.compile(r"Заказ\s+(.+?)\s+назад", re.S)


def _parse_views(s: str) -> int | None:
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


def parse_listing(html: str) -> list[dict]:
    """HTML страницы списка fl.ru/projects/ -> заказы с деловыми сигналами. Без сети.

    Поля: title, budget(int|None), url, desc, responses(int|None),
    age_hours(float|None), views(int|None).
    """
    if not html:
        return []
    cards = list(_CARD_RE.finditer(html))
    out: list[dict] = []
    for idx, m in enumerate(cards):
        pid, href, title = m.group(1), m.group(2), re.sub(r"\s+", " ", m.group(3)).strip()
        start = m.start()
        end = cards[idx + 1].start() if idx + 1 < len(cards) else min(len(html), start + 4000)
        raw = html[start:end]
        text = _clean_text(raw)

        budget = None
        bm = _BUDGET_RUB_RE.search(text)
        if bm:
            digits = re.sub(r"\D", "", bm.group(1))
            if digits:
                budget = int(digits)

        rm = _RESP_RE.search(raw)
        responses = int(rm.group(1)) if rm else None

        vm = _VIEWS_RE.search(raw)
        views = _parse_views(vm.group(1)) if vm else None

        am = _AGE_RE.search(text)
        age_hours = parse_age_hours(am.group(1)) if am else None

        out.append(
            {
                "title": title,
                "budget": budget,
                "url": f"https://www.fl.ru{href}",
                "desc": text[:400],
                "responses": responses,
                "age_hours": age_hours,
                "views": views,
            }
        )
    return out


def fetch_fl_listing(pages: int = 3) -> list[dict]:
    """Боевая: тянет N страниц списка проектов FL.ru и парсит. Использует сеть."""
    if requests is None:
        raise RuntimeError("requests не установлен — fetch_fl_listing недоступен")
    out: list[dict] = []
    for page in range(1, max(1, pages) + 1):
        url = LISTING_URL + (f"?page={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "ru"}, timeout=40)
            if r.status_code != 200:
                print(f"[fl] {url} -> HTTP {r.status_code}")
                continue
            out.extend(parse_listing(r.text))
        except Exception as e:  # сеть может падать — не валим весь цикл
            print(f"[fl] ошибка запроса {url}: {e}")
    return out


def fetch_fl_orders(keywords: list[str], pages: int = 1) -> list[dict]:
    """Боевая: тянет FL.ru по каждому ключевому слову. Использует сеть."""
    if requests is None:
        raise RuntimeError("requests не установлен — fetch_fl_orders недоступен")
    out: list[dict] = []
    for kw in keywords:
        for page in range(1, pages + 1):
            params = {"kind": 1, "keyword": kw}
            if page > 1:
                params["page"] = page
            url = "https://www.fl.ru/projects/?" + urllib.parse.urlencode(params)
            try:
                r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
                if r.status_code != 200:
                    print(f"[fl] {url} -> HTTP {r.status_code}")
                    continue
                out.extend(parse_orders(r.text))
            except Exception as e:  # сеть может падать — не валим весь цикл
                print(f"[fl] ошибка запроса {url}: {e}")
    return out
