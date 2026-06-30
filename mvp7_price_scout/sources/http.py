"""Общий HTTP-хелпер источников: единый User-Agent + ретраи на сетевых сбоях."""
from __future__ import annotations

import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru,en;q=0.9"}


def get(url: str, timeout: int = 40, tries: int = 2, **kw) -> requests.Response:
    """GET с UA и ретраями. Кидает последнее исключение, если все попытки упали."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout, **kw)
        except Exception as e:  # сеть может моргать — пробуем ещё раз
            last = e
            time.sleep(1.0 * (i + 1))
    raise last  # type: ignore[misc]
