"""Общий HTTP-хелпер источников: единый User-Agent + ретраи на сетевых сбоях."""
from __future__ import annotations

import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru,en;q=0.9"}


_RETRY_STATUS = {429, 500, 502, 503, 504}   # временные — есть смысл повторить


def get(url: str, timeout: int = 40, tries: int = 2, **kw) -> requests.Response:
    """GET с UA и ретраями. Повторяет на сетевых сбоях И на 429/5xx.

    На не-200 не бросает (совместимость: вызыватели читают .text), но ГРОМКО
    логирует — иначе блок сайта (403/503) неотличим от «пусто» и целый источник
    молча выпадает из сравнения.
    """
    last: Exception | None = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
        except Exception as e:  # сеть может моргать — пробуем ещё раз
            last = e
            time.sleep(1.0 * (i + 1))
            continue
        if r.status_code in _RETRY_STATUS and i < tries - 1:
            time.sleep(1.5 * (i + 1))
            continue
        if r.status_code >= 400:      # 403 (анти-бот), 404, 5xx — источник отдаёт не данные
            print(f"[http] {r.status_code} {url}")
        return r
    raise last  # type: ignore[misc]
