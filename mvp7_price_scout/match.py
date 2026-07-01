"""
Сопоставление товара конкурента к каталогу эталона (наш di-park).

di-park = канонический список. Для записи конкурента ищем эталонный товар:
  1) точное равенство model_key (объём уже внутри ключа) -> 100;
  2) иначе fuzzy ТОЛЬКО среди эталонов с тем же объёмом И тем же набором
     вариант-токенов (pro/max/ultra/plus...), по token_sort_ratio >= порога.

Почему не token_set_ratio: он даёт 100 для подмножества — «Galaxy S24» совпал
бы с «Galaxy S24 Ultra». token_sort_ratio штрафует лишний токен, а guard по
вариант-токенам и объёму режет ложные склейки (256 vs 512, base vs Pro).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from mvp7_price_scout.normalize import Product, sim_type_of

# Нижний порог token_sort_ratio среди уже прошедших guard-ы кандидатов (страховка).
MIN_RATIO = 55

# Токены, различающие модель внутри линейки. Должны совпадать у пары точно.
_VARIANT = {"pro", "max", "plus", "ultra", "mini", "air", "se", "fe", "lite", "neo"}


def _variants(model_key: str) -> frozenset[str]:
    return frozenset(t for t in model_key.split() if t in _VARIANT)


def _id_tokens(model_key: str, storage: str | None) -> frozenset[str]:
    """Цифросодержащие модель-токены (17, s24, 14t) без токена объёма.

    Критичны: token_sort_ratio считает «16» и «17» почти одинаковыми (1 символ),
    поэтому iPhone 16 ложно матчился к 17, Galaxy S24 к S25. Требуем точного
    совпадения этого набора.
    """
    return frozenset(t for t in model_key.split()
                     if any(c.isdigit() for c in t) and t != storage)


def _core_alpha(model_key: str) -> frozenset[str]:
    """Буквенные токены бренда/линейки (iphone, galaxy, macbook) без вариант-слов."""
    return frozenset(t for t in model_key.split()
                     if not any(c.isdigit() for c in t) and t not in _VARIANT)


def build_index(base_rows: list[dict]) -> dict:
    """Индекс каталога эталона: точный по ключу + бакеты по объёму.

    Обогащаем строки sim_type (из title) — нужен для мягкого SIM-guard'а. Один
    model_key может иметь несколько строк (eSIM-only и Sim+E-Sim), поэтому by_key
    держит список, а не одну строку.
    """
    by_key: dict[str, list[dict]] = {}
    by_storage: dict[str | None, list[dict]] = {}
    for r in base_rows:
        r["sim_type"] = sim_type_of(r.get("title", ""))
        by_key.setdefault(r["model_key"], []).append(r)
        by_storage.setdefault(r.get("storage"), []).append(r)
    return {"by_key": by_key, "by_storage": by_storage}


def _sim_ok(a: str | None, b: str | None) -> bool:
    """Мягкий SIM-guard: конфликт ТОЛЬКО когда оба типа известны и различны.

    Если конкурент (или эталон) тип SIM не указал — матчим как раньше, чтобы не
    терять match-rate на витринах без пометки SIM.
    """
    return a is None or b is None or a == b


def _cheapest(rows: list[dict]) -> dict:
    priced = [r for r in rows if r.get("price") is not None]
    return min(priced, key=lambda r: r["price"]) if priced else rows[0]


def match_one(prod: Product, index: dict, min_ratio: int = MIN_RATIO) -> tuple[int | None, int]:
    """Вернуть (dipark_id, score) лучшего эталона для товара конкурента или (None, score).

    Кандидат валиден ТОЛЬКО при совпадении: объём + вариант-токены (pro/max/...) +
    числовые модель-токены (17/s24/...) + хотя бы один общий бренд/линейка-токен +
    совместимый тип SIM (мягко: eSIM-only не матчится к Sim+E-Sim, см. _sim_ok).
    Среди валидных берём лучший token_sort_ratio (страховочный порог MIN_RATIO).
    """
    psim = prod.sim_type
    exacts = index["by_key"].get(prod.model_key)
    if exacts:
        ok = [r for r in exacts if _sim_ok(psim, r["sim_type"])]
        if ok:                                               # совместимый по SIM эталон
            return _cheapest(ok)["id"], 100
    pk = prod.model_key
    pv, pids, pca = _variants(pk), _id_tokens(pk, prod.storage), _core_alpha(pk)
    best: dict | None = None
    best_score = 0
    for row in index["by_storage"].get(prod.storage, []):
        if not _sim_ok(psim, row["sim_type"]):               # eSIM-only vs Sim+E-Sim
            continue
        rk = row["model_key"]
        if _variants(rk) != pv:                              # pro/max/ultra/plus...
            continue
        if _id_tokens(rk, row.get("storage")) != pids:       # 16 vs 17, s24 vs s25
            continue
        if not (_core_alpha(rk) & pca):                      # общий бренд/линейка
            continue
        score = int(fuzz.token_sort_ratio(pk, rk))
        if score > best_score:
            best_score, best = score, row
    if best and best_score >= min_ratio:
        return best["id"], best_score
    return None, best_score


def match_all(products: list[Product], base_rows: list[dict]) -> int:
    """Проставить dipark_id всем товарам конкурента. Вернуть число матчей."""
    index = build_index(base_rows)
    matched = 0
    for p in products:
        pid, _ = match_one(p, index)
        p.dipark_id = pid
        if pid is not None:
            matched += 1
    return matched
