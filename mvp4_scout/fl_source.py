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

try:
    import requests
except ImportError:  # офлайн-тест с parse_orders сети не требует
    requests = None

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

        orders.append(
            {
                "title": title,
                "budget": budget,
                "url": f"https://www.fl.ru/projects/{pid}/",
            }
        )
    return orders


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
