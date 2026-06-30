"""
Playwright-хелпер для JS-источников (repremium, ispace, Яндекс).

Один браузер на сессию (Browser as context manager) + render(url) со скроллом —
подгружает ленивые/AJAX-карточки каталога. Запуск headless с --no-sandbox.
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class Browser:
    """with Browser() as br: html = br.render(url)."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None

    def __enter__(self) -> "Browser":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        self._ctx = self._browser.new_context(user_agent=UA, locale="ru-RU")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def render(self, url: str, wait_selector: str | None = None,
               scroll: bool = True, timeout: int = 45000) -> str:
        """Открыть URL, подождать селектор, проскроллить до конца -> HTML."""
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass
            if scroll:
                prev = 0
                for _ in range(25):                 # докручиваем ленивую подгрузку
                    page.mouse.wheel(0, 9000)
                    page.wait_for_timeout(500)
                    h = page.evaluate("document.body.scrollHeight")
                    if h == prev:
                        break
                    prev = h
            return page.content()
        finally:
            page.close()

    def goto_page(self, url: str, timeout: int = 45000):
        """Вернуть live-страницу (для источников, где нужен клик по вкладке — Яндекс)."""
        page = self._ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return page
