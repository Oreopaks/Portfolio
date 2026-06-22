"""
SEMI-AUTO ИСХОД: бот находит компании с ручным процессом (вакансии Trudvsem),
пишет персональный питч и КОНТАКТ -> шлёт владельцу готовый пакет в ЛС.
Владелец жмёт «отправить» сам (человек в петле = нет бана/спама, верный фрейм).

Запуск:
    python mvp4_scout/outbound.py            # dry-run: печатает пакеты, НЕ шлёт
    python mvp4_scout/outbound.py --send     # шлёт пакеты в ЛС (SCOUT_NOTIFY_*), метит seen

Цель = вакансия «оператор/обработка заявок/колл-центр/поддержка»: компания платит
зарплату за рутину, которую закрывает AI-автоматизация -> тёплый лид под холодный питч.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/oleg/freelance-mvp")

import shared.config  # noqa: F401 — .env
import requests

from shared.llm import chat
from mvp4_scout.trudvsem_source import fetch_targets

# Роли-сигналы ручного процесса под АВТОМАТИЗАЦИЮ (ниша владельца).
DEFAULT_QUERIES = [
    "оператор обработки заявок",
    "оператор колл-центра",
    "оператор технической поддержки",
    "диспетчер приём заявок",
    "специалист по обработке обращений",
]
# Пускаем дальше только если роль реально про автоматизируемую рутину.
_RELEVANT = ("заявк", "обращен", "звонк", "колл", "call", "оператор", "диспетчер",
            "поддержк", "обработ", "приём", "прием", "чат", "клиент")

SEEN_PATH = Path(__file__).resolve().parent / "seen_outbound.json"
MAX_PACKAGES = int(os.environ.get("OUTBOUND_MAX", "8"))


def _relevant(t: dict) -> bool:
    blob = f"{t.get('title','')} {t.get('duty','')}".lower()
    if not any(k in blob for k in _RELEVANT):
        return False
    return bool(t.get("email") or t.get("phone"))  # без контакта пакет бесполезен


def _load_seen() -> set[str]:
    if SEEN_PATH.exists():
        try:
            return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def make_pitch(t: dict) -> str:
    system = (
        "Ты — Python/AI-разработчик. Напиши КОРОТКОЕ холодное сообщение руководителю компании "
        "(4-5 предложений, по-деловому, на «вы»). Контекст: компания наняла человека на рутину "
        "из вакансии. Предложи автоматизировать это на AI (n8n + GPT / бот): заявки сами "
        "квалифицируются и падают в CRM, обращения/звонки разбирает ИИ, менеджер видит только "
        "важное. Подчеркни: окупается за 1-2 месяца против зарплаты сотрудника. Крючок — живое "
        "демо @kryu_lead_bot. ВАЖНО: рамка «предлагаю автоматизацию», НЕ «ищу работу». Без воды, "
        "без воды-приветствий на абзац. Начни с сути."
    )
    user = (f"Компания: {t.get('company')}. Вакансия: {t.get('title')}. "
            f"Обязанности: {t.get('duty')}. Зарплата: {t.get('salary_min')}-{t.get('salary_max')}.")
    return chat(system, user, temperature=0.4)


def _fmt_salary(t: dict) -> str:
    lo, hi = t.get("salary_min"), t.get("salary_max")
    if not lo and not hi:
        return "не указана"
    if lo and hi and lo != hi:
        return f"{lo}-{hi} ₽"
    return f"{lo or hi} ₽"


def build_package(t: dict, pitch: str) -> str:
    contacts = "  ".join(filter(None, [
        f"✉️ {t['email']}" if t.get("email") else "",
        f"📞 {t['phone']}" if t.get("phone") else "",
        f"🔗 {t['site']}" if t.get("site") else "",
    ]))
    return (
        f"🎯 ЦЕЛЬ ИСХОДА [Работа России]\n"
        f"🏢 {t.get('company')} (ИНН {t.get('inn') or '—'})\n"
        f"💼 {t.get('title')} · ЗП {_fmt_salary(t)} · {t.get('region')}\n"
        f"{contacts}\n"
        f"📄 вакансия: {t.get('url')}\n\n"
        f"✍️ Питч (копируй и отправь ЛПР):\n{pitch}"
    )


def _send_tg(text: str) -> bool:
    tok = os.environ.get("SCOUT_NOTIFY_TOKEN")
    chat_id = os.environ.get("SCOUT_NOTIFY_CHAT_ID")
    if not tok or not chat_id:
        print("[outbound] SCOUT_NOTIFY_TOKEN/CHAT_ID не заданы — не шлю")
        return False
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=30)
    return r.ok


def cycle(send: bool = False, queries: list[str] | None = None, limit: int = MAX_PACKAGES) -> list[dict]:
    queries = queries or DEFAULT_QUERIES
    targets = fetch_targets(queries)
    seen = _load_seen()
    fresh = [t for t in targets if _relevant(t) and t["id"] not in seen]
    # одна компания — один пакет за цикл (не дёргаем тот же бизнес дважды)
    picked: list[dict] = []
    used_companies: set[str] = set()
    for t in fresh:
        key = (t.get("inn") or t.get("company") or "").strip().lower()
        if key and key in used_companies:
            continue
        used_companies.add(key)
        picked.append(t)
        if len(picked) >= limit:
            break
    print(f"[outbound] цели: {len(targets)} -> релевантных новых: {len(fresh)} -> уник компаний, берём {len(picked)}")
    out: list[dict] = []
    for t in picked:
        try:
            pitch = make_pitch(t)
        except Exception as e:
            pitch = f"(питч не сгенерился: {e})"
        pkg = build_package(t, pitch)
        if send:
            if _send_tg(pkg):
                seen.add(t["id"])
        else:
            print("\n" + "=" * 60 + "\n" + pkg)
        out.append({**t, "package": pkg})
    if send:
        _save_seen(seen)
        print(f"[outbound] отправлено и помечено seen: {len(out)}")
    return out


if __name__ == "__main__":
    cycle(send="--send" in sys.argv)
