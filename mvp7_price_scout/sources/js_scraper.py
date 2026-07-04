"""
Отказоустойчивый Playwright-скрапер JS-каталога конкурента (production).

Для сайтов, где каталог/цены живут за JavaScript: бесконечный скролл, кнопка
«Показать ещё», SKU-конфигуратор (клик по цвету/памяти/SIM меняет цену). Для
статичных витрин проекта хватает requests+bs4 (sr57/iprice/ispace/mobilax/
kingstore); этот модуль — дополнение к repremium для тяжёлых JS-витрин.

Гарантии спеки:
  1. Filter Extraction — боковое меню фильтров -> JSON-схема (для валидации).
  2. Total Scraping (100%) — счётчик товаров сайта СВЕРЯЕТСЯ с числом собранных;
     обход идёт пока «Далее»/«Показать ещё» жив ИЛИ скролл добавляет элементы;
     недобор -> исключение (не молчим, страница не теряется).
  3. Resiliency — retry(3) с экспоненциальным backoff+джиттер, ротация User-Agent,
     таймауты 10-15с, человекоподобные задержки/скролл.
  + каждый SKU -> atomize() -> атомарный JSON (базовая модель/RAM/ROM/SIM/цвет/
    регион/цена) для сравнения с каталогом di-park.

Архитектура: чистые парсеры (parse_count / build_filter_schema / parse_cards)
тестируются офлайн; браузерные async-функции — боевые. Playwright импортируется
лениво (модуль грузится без него — для юнит-тестов чистых функций).

CLI:
    python -m mvp7_price_scout.sources.js_scraper \
        --category https://shop.example/smartphones/ --cards ".product-card" \
        --out /tmp/example
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from mvp7_price_scout.atomize import atomize
from mvp7_price_scout.normalize import clean_title, parse_price

log = logging.getLogger("js_scraper")

# Ротация User-Agent — против простого anti-bot по одному UA.
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass
class ScrapeConfig:
    """Настройки скрапера под конкретный сайт (селекторы + пороги устойчивости)."""
    category_url: str
    shop: str = "js_shop"
    # --- селекторы каталога ---
    card_sel: str = ".product-card, .catalog-item, [class*=product-item]"
    name_sel: str = "[class*=name], [class*=title], h3, h2"
    price_sel: str = "[itemprop=price], [class*=price-new], [class*=price]:not([class*=old])"
    old_price_sel: str = "del, s, [class*=old-price], [class*=price-old]"
    link_sel: str = "a[href]"
    count_sel: str = "[class*=found], [class*=catalog-count], [class*=items-count]"
    # --- фильтры ---
    filter_group_sel: str = ".filter-group, [class*=filter__group], .facet, fieldset"
    filter_name_sel: str = "legend, [class*=title], h3, h4, .facet__title"
    filter_value_sel: str = "label, a[href], [class*=filter-value], [data-value]"
    # --- SKU-конфигуратор (переключатели на карточке товара) ---
    sku_option_sels: tuple[str, ...] = (
        "[data-color]:not([disabled])", "[data-storage]:not([disabled])",
        "[data-sim]:not([disabled])",
    )
    sku_name_sel: str = "h1, [itemprop=name]"
    sku_price_sel: str = "[itemprop=price], [class*=price-new], [class*=price]"
    # --- устойчивость ---
    tries: int = 3
    nav_timeout_ms: int = 15000       # 10-15с на тяжёлую JS-страницу
    sel_timeout_ms: int = 12000
    idle_timeout_ms: int = 12000
    scroll_rounds: int = 40           # предел раундов скролла (страховка от вечного цикла)
    max_skus_per_product: int = 60    # страховка от комбинаторного взрыва конфигуратора
    headless: bool = True


# ─────────────────────────── ЧИСТЫЕ ПАРСЕРЫ (офлайн-тест) ───────────────────────────

def parse_count(text: str | None) -> int | None:
    """«Найдено 342 товара» / «Показано 24 из 1 240» -> итоговое число (МАКСИМУМ).

    Берём максимальное число в строке: у «24 из 1240» тотал — большее (1240).
    """
    if not text:
        return None
    nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d\s ]*", text)]
    return max(nums) if nums else None


def build_filter_schema(html: str, cfg: ScrapeConfig) -> dict[str, list[str]]:
    """Боковое меню фильтров -> {название группы: [значения]} (JSON-схема)."""
    soup = BeautifulSoup(html or "", "html.parser")
    schema: dict[str, list[str]] = {}
    for grp in soup.select(cfg.filter_group_sel):
        name_el = grp.select_one(cfg.filter_name_sel)
        name = clean_title(name_el.get_text()) if name_el else ""
        if not name:
            continue
        values: list[str] = []
        for opt in grp.select(cfg.filter_value_sel):
            v = clean_title(opt.get_text()) or (opt.get("data-value") or "").strip()
            # отбрасываем счётчики-обёртки («Синий (12)») до чистого значения
            v = re.sub(r"\s*\(\d+\)\s*$", "", v)
            if v and v.lower() != name.lower():
                values.append(v)
        if values:
            schema[name] = sorted(dict.fromkeys(values))   # уникальные, порядок стабилен
    return schema


def parse_cards(html: str, cfg: ScrapeConfig, base_url: str = "") -> list[dict]:
    """HTML листинга -> [{title, price, old_price, url}] (чистая, без браузера)."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    for card in soup.select(cfg.card_sel):
        name_el = card.select_one(cfg.name_sel)
        title = clean_title(name_el.get_text()) if name_el else ""
        if not title:
            continue
        old_el = card.select_one(cfg.old_price_sel)
        old_price = parse_price(old_el.get_text()) if old_el else None
        if old_el:                                   # чтобы old не попал в текущую цену
            old_el.extract()
        price_el = card.select_one(cfg.price_sel)
        price = None
        if price_el:
            price = parse_price(price_el.get("content") or price_el.get_text())
        a = card.select_one(cfg.link_sel)
        url = (a.get("href") if a else "") or ""
        if url.startswith("/"):
            url = base_url.rstrip("/") + url
        out.append({"title": title, "price": price, "old_price": old_price, "url": url})
    return out


def card_id(card: dict) -> str:
    """Стабильный ключ карточки для подсчёта уникальных (url или title+price)."""
    return card.get("url") or f"{card['title']}|{card.get('price')}"


# ─────────────────────────── БРАУЗЕРНЫЕ ФУНКЦИИ (боевые) ───────────────────────────

async def _retry(action, what: str, cfg: ScrapeConfig):
    """Выполнить async-действие с retry(cfg.tries) и экспоненциальным backoff+джиттер."""
    last: Exception | None = None
    for attempt in range(1, cfg.tries + 1):
        try:
            return await action()
        except Exception as e:                       # таймаут селектора/навигации/сети
            last = e
            delay = 2 ** (attempt - 1) + random.random()      # 1s, 2s, 4s (+джиттер)
            log.warning("  ↻ [%s] попытка %d/%d упала: %s — жду %.1fс",
                        what, attempt, cfg.tries, str(e)[:120], delay)
            await asyncio.sleep(delay)
    raise RuntimeError(f"[{what}] исчерпаны {cfg.tries} попытки: {last}")


async def _human_pause(a: float = 0.3, b: float = 1.1) -> None:
    await asyncio.sleep(random.uniform(a, b))


async def _human_scroll(page) -> None:
    """Человекоподобный скролл: несколько рывков колеса с паузами, не один прыжок."""
    for _ in range(random.randint(2, 4)):
        await page.mouse.wheel(0, random.randint(600, 1400))
        await _human_pause(0.15, 0.5)


async def extract_filters(page, cfg: ScrapeConfig) -> dict[str, list[str]]:
    """Обойти категорию и распарсить боковое меню фильтров -> JSON-схема."""
    async def _open():
        return await page.wait_for_selector(cfg.filter_group_sel, timeout=cfg.sel_timeout_ms)
    try:
        await _retry(_open, "filters:wait", cfg)
    except RuntimeError:
        log.warning("  фильтры не найдены (%s) — пропускаю сбор фильтров", cfg.filter_group_sel)
        return {}
    schema = build_filter_schema(await page.content(), cfg)
    log.info("  фильтров: %d групп (%s)", len(schema), ", ".join(schema) or "—")
    return schema


async def collect_listing(page, cfg: ScrapeConfig, base_url: str) -> list[dict]:
    """Собрать ВСЕ карточки категории: скролл/«Показать ещё»/«Далее» + сверка счётчика.

    100%-гарант: если сайт показывает общий счётчик и собрано меньше — RuntimeError.
    """
    expected = parse_count(await _safe_text(page, cfg.count_sel))
    log.info("  счётчик сайта: %s товаров", expected if expected is not None else "нет")

    seen: dict[str, dict] = {}
    stagnant = 0
    for rnd in range(1, cfg.scroll_rounds + 1):
        for c in parse_cards(await page.content(), cfg, base_url):
            seen[card_id(c)] = c
        before = len(seen)

        moved = await _load_more(page, cfg)          # «Показать ещё»/«Далее» если есть
        if not moved:
            await _human_scroll(page)                # иначе infinite scroll
            await _wait_idle(page, cfg)

        for c in parse_cards(await page.content(), cfg, base_url):
            seen.setdefault(card_id(c), c)
        after = len(seen)
        log.info("  раунд %d: карточек %d (+%d)%s", rnd, after, after - before,
                 " [клик подгрузки]" if moved else " [скролл]")

        if after == before:
            stagnant += 1
            if stagnant >= 2 and not moved:          # два раунда без роста и кликать нечего
                break
        else:
            stagnant = 0

    products = list(seen.values())
    if expected is not None and len(products) < expected:
        raise RuntimeError(
            f"НЕПОЛНЫЙ сбор {cfg.shop}: {len(products)}/{expected} — страница/скролл "
            f"потеряны, 100% не достигнуто")
    log.info("  собрано карточек: %d (счётчик сайта: %s) ✅", len(products), expected)
    return products


async def _load_more(page, cfg: ScrapeConfig) -> bool:
    """Кликнуть «Показать ещё»/активную «Далее», если есть. True — если кликнули."""
    for sel in ("text=/Показать ещё|Загрузить ещё|Show more/i",
                "[class*=show-more]", "[class*=load-more]",
                "a[rel=next]", "[class*=pagination] [class*=next]:not([disabled])"):
        try:
            btn = await page.query_selector(sel)
        except Exception:
            btn = None
        if btn and await btn.is_enabled() and await btn.is_visible():
            try:
                await btn.scroll_into_view_if_needed(timeout=cfg.sel_timeout_ms)
                await _human_pause()
                await btn.click(timeout=cfg.sel_timeout_ms)
                await _wait_idle(page, cfg)
                return True
            except Exception as e:
                log.warning("  клик подгрузки (%s) не удался: %s", sel, str(e)[:80])
    return False


async def expand_skus(page, url: str, cfg: ScrapeConfig) -> list[dict]:
    """Открыть карточку товара и кликнуть КАЖДОЕ сочетание цвет×память×SIM -> [SKU].

    Каждая комбинация -> atomize(title, price, old_price). Если переключателей нет —
    один SKU (страница как есть). Дедуп по (model_key, sim, color, region).
    """
    from itertools import product as iproduct

    async def _goto():
        await page.goto(url, wait_until="domcontentloaded", timeout=cfg.nav_timeout_ms)
        await page.wait_for_selector(cfg.sku_name_sel, timeout=cfg.sel_timeout_ms)
    await _retry(_goto, f"sku:goto {url[-40:]}", cfg)

    groups: list[list] = []
    for sel in cfg.sku_option_sels:
        opts = await page.query_selector_all(sel)
        if opts:
            groups.append(opts)
    combos = 1
    for g in groups:
        combos *= len(g)
    if combos > cfg.max_skus_per_product:
        log.warning("  %s: %d комбинаций > предел %d — беру как есть (без клика)",
                    url[-40:], combos, cfg.max_skus_per_product)
        groups = []

    out: dict[tuple, dict] = {}
    dims = groups or [[None]]
    for combo in iproduct(*dims):
        for opt in combo:
            if opt is None:
                continue
            try:
                await opt.click(timeout=cfg.sel_timeout_ms)
                await _wait_idle(page, cfg)          # ждём пересчёт цены (network idle)
                await _human_pause(0.2, 0.6)
            except Exception as e:
                log.warning("  клик опции не удался: %s", str(e)[:80])
        title = await _safe_text(page, cfg.sku_name_sel)
        price = await _safe_text(page, cfg.sku_price_sel)
        old = await _safe_text(page, cfg.old_price_sel)
        if not title:
            continue
        sku = atomize(title, price, old)
        sku["url"] = page.url
        out[(sku["model_key"], sku["sim_type"], sku["color"], sku["region"])] = sku
    log.info("  %s: SKU-комбинаций собрано %d", url[-40:], len(out))
    return list(out.values())


async def _safe_text(page, sel: str) -> str | None:
    try:
        el = await page.query_selector(sel)
        if not el:
            return None
        return (await el.get_attribute("content")) or (await el.inner_text())
    except Exception:
        return None


async def _wait_idle(page, cfg: ScrapeConfig) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=cfg.idle_timeout_ms)
    except Exception:
        pass                                         # networkidle может не наступить — не валимся


async def scrape(cfg: ScrapeConfig, expand: bool = False) -> dict:
    """Полный прогон: фильтры -> все карточки категории -> (опц.) SKU по комбинациям.

    Возвращает {"filters": {...}, "products": [atomized...], "count": N}. Логи —
    какая страница, сколько найдено, ошибки. Playwright импортируется здесь (лениво).
    """
    from playwright.async_api import async_playwright

    base = re.match(r"https?://[^/]+", cfg.category_url)
    base_url = base.group(0) if base else ""
    log.info("НАЧАЛО %s: %s", cfg.shop, cfg.category_url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=cfg.headless)
        context = await browser.new_context(
            user_agent=random.choice(UA_POOL),
            viewport={"width": random.choice([1366, 1440, 1536, 1920]),
                      "height": random.choice([768, 864, 900, 1080])},
            locale="ru-RU",
        )
        page = await context.new_page()
        page.set_default_timeout(cfg.sel_timeout_ms)
        try:
            async def _goto():
                await page.goto(cfg.category_url, wait_until="domcontentloaded",
                                timeout=cfg.nav_timeout_ms)
            await _retry(_goto, "category:goto", cfg)
            await _human_pause()

            filters = await extract_filters(page, cfg)
            cards = await collect_listing(page, cfg, base_url)

            if expand:
                products: list[dict] = []
                for i, c in enumerate(cards, 1):
                    if not c.get("url"):
                        products.append(atomize(c["title"], c["price"], c["old_price"]))
                        continue
                    log.info("товар %d/%d: %s", i, len(cards), c["title"][:50])
                    try:
                        products += await expand_skus(page, c["url"], cfg)
                    except Exception as e:
                        log.error("  SKU %s упал: %s", c["url"][-40:], str(e)[:120])
            else:
                products = [atomize(c["title"], c["price"], c["old_price"]) | {"url": c["url"]}
                           for c in cards]
        finally:
            await context.close()
            await browser.close()

    log.info("ГОТОВО %s: фильтров %d, товаров %d", cfg.shop, len(filters), len(products))
    return {"filters": filters, "products": products, "count": len(products)}


def _setup_logging(verbose: bool = True) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def main() -> None:
    ap = argparse.ArgumentParser(description="Playwright-скрапер JS-каталога конкурента")
    ap.add_argument("--category", required=True, help="URL категории")
    ap.add_argument("--shop", default="js_shop")
    ap.add_argument("--cards", dest="card_sel", help="CSS-селектор карточки товара")
    ap.add_argument("--expand", action="store_true", help="кликать SKU-комбинации на карточке")
    ap.add_argument("--out", help="префикс файлов вывода (<out>.filters.json / <out>.products.json)")
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    args = ap.parse_args()

    _setup_logging()
    cfg = ScrapeConfig(category_url=args.category, shop=args.shop, headless=args.headless)
    if args.card_sel:
        cfg.card_sel = args.card_sel
    result = asyncio.run(scrape(cfg, expand=args.expand))

    if args.out:
        with open(f"{args.out}.filters.json", "w", encoding="utf-8") as f:
            json.dump(result["filters"], f, ensure_ascii=False, indent=2)
        with open(f"{args.out}.products.json", "w", encoding="utf-8") as f:
            json.dump(result["products"], f, ensure_ascii=False, indent=2)
        log.info("записано: %s.filters.json, %s.products.json", args.out, args.out)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
