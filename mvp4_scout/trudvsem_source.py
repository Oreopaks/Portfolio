"""
Источник ЦЕЛЕЙ ДЛЯ ИСХОДА (не заказов!) — гос-API «Работа России» (Trudvsem).

Логика разворота: вакансия «оператор обработки заявок / колл-центр / поддержка» =
компания, которая ПЛАТИТ ЗАРПЛАТУ за ручной процесс, который закрывает AI-автоматизация.
Это тёплый лид под холодный питч, а не фриланс-заказ.

Почему Trudvsem, а не hh.ru: hh геоблокирует наш DE-VPS (451/403). Trudvsem —
открытое гос-API (opendata.trudvsem.ru), без авторизации, пускает с сервера, и
отдаёт КОНТАКТ работодателя (email/телефон/сайт) прямо в ответе.

fetch_targets(queries) -> [{title, company, email, phone, site, salary_min/max,
                            region, duty, url, id, source}]
parse_vacancies(payload) — чистый парсер JSON, тестируется офлайн.
"""
from __future__ import annotations

import requests

_API = "https://opendata.trudvsem.ru/api/v1/vacancies"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; oreo-outbound/1.0)"}


def _phone(v: dict) -> str:
    for c in v.get("contact_list") or []:
        if "елефон" in (c.get("contact_type") or ""):
            return c.get("contact_value") or ""
    return ""


def _region_name(v: dict) -> str:
    reg = v.get("region")
    if isinstance(reg, dict):
        return reg.get("name") or ""
    return reg or ""


def parse_vacancies(payload: dict) -> list[dict]:
    """JSON Trudvsem -> список целей. Без сети — для офлайн-тестов."""
    out: list[dict] = []
    vacs = ((payload or {}).get("results") or {}).get("vacancies") or []
    for w in vacs:
        v = w.get("vacancy", {}) or {}
        comp = v.get("company", {}) or {}
        out.append({
            "title": v.get("job-name", "") or "",
            "company": comp.get("name", "") or "",
            "inn": comp.get("inn", "") or "",
            "email": comp.get("email", "") or "",
            "phone": _phone(v),
            "site": comp.get("url", "") or "",
            "salary_min": v.get("salary_min"),
            "salary_max": v.get("salary_max"),
            "region": _region_name(v),
            "duty": (v.get("duty") or "").strip()[:300],
            "url": v.get("vac_url", "") or "",
            "id": v.get("id", "") or "",
            "source": "trudvsem",
        })
    return out


def fetch_targets(queries: list[str], per_query: int = 20) -> list[dict]:
    """Тянет вакансии-цели по каждому запросу, дедуп по id заказа."""
    seen: set[str] = set()
    res: list[dict] = []
    for q in queries:
        try:
            r = requests.get(_API, headers=_UA,
                             params={"text": q, "limit": per_query, "offset": 0}, timeout=25)
            r.raise_for_status()
            for t in parse_vacancies(r.json()):
                if t["id"] and t["id"] not in seen:
                    seen.add(t["id"])
                    t["query"] = q
                    res.append(t)
        except Exception as e:
            print(f"[trudvsem] '{q}' ошибка: {e}")
    return res
