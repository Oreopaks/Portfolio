"""
Единый интерфейс к LLM. Провайдеры: mock (для тестов, без сети/ключей),
gigachat (Сбер, РФ, без VPN), yandex (YandexGPT).

Выбор провайдера через переменную окружения LLM_PROVIDER (default: mock).
Все боевые провайдеры вызываются по REST через requests — без тяжёлых SDK.

Пример:
    from shared.llm import chat
    answer = chat("Ты бот кофейни.", "Во сколько вы открываетесь?")
"""
from __future__ import annotations
import os
import json
import hashlib
import time

try:
    import requests
except ImportError:  # тесты с mock не требуют requests
    requests = None


class LLMError(RuntimeError):
    pass


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "mock").lower().strip()


# ---------------------------------------------------------------------------
# MOCK — детерминированный, без сети. Нужен для CI/тестов без ключей.
# ---------------------------------------------------------------------------
def _mock_chat(system: str, user: str, **_) -> str:
    """
    Возвращает воспроизводимый осмысленный ответ. Детерминирован по входу,
    чтобы тесты были стабильны. НЕ для продакшена.
    """
    digest = hashlib.sha256((system + "|" + user).encode("utf-8")).hexdigest()[:8]
    return f"[mock:{digest}] Ответ на запрос: {user.strip()[:160]}"


# ---------------------------------------------------------------------------
# GigaChat (Сбер). Auth: OAuth2 по Authorization key -> access_token (30 мин).
# Docs: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat
# env: GIGACHAT_AUTH_KEY (base64 client_id:secret), GIGACHAT_SCOPE
# ---------------------------------------------------------------------------
_giga_token = {"value": None, "exp": 0.0}


def _gigachat_token() -> str:
    if requests is None:
        raise LLMError("requests не установлен")
    if _giga_token["value"] and time.time() < _giga_token["exp"] - 60:
        return _giga_token["value"]
    auth = os.environ.get("GIGACHAT_AUTH_KEY")
    if not auth:
        raise LLMError("GIGACHAT_AUTH_KEY не задан в .env")
    scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    rquid = hashlib.md5(auth.encode()).hexdigest()
    r = requests.post(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        headers={
            "Authorization": f"Basic {auth}",
            "RqUID": rquid,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"scope": scope},
        verify=os.environ.get("GIGACHAT_CA", True),  # см. DEPLOY.md про сертификат Минцифры
        timeout=30,
    )
    if r.status_code != 200:
        raise LLMError(f"GigaChat oauth {r.status_code}: {r.text[:200]}")
    j = r.json()
    _giga_token["value"] = j["access_token"]
    _giga_token["exp"] = j.get("expires_at", time.time() * 1000 + 1800_000) / 1000.0
    return _giga_token["value"]


def _gigachat_chat(system: str, user: str, temperature: float = 0.3, **_) -> str:
    token = _gigachat_token()
    r = requests.post(
        "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("GIGACHAT_MODEL", "GigaChat"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        },
        verify=os.environ.get("GIGACHAT_CA", True),
        timeout=60,
    )
    if r.status_code != 200:
        raise LLMError(f"GigaChat chat {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# YandexGPT. Auth: Api-Key (folder). env: YANDEX_API_KEY, YANDEX_FOLDER_ID
# Docs: https://yandex.cloud/ru/docs/foundation-models/text-generation/api-ref/
# ---------------------------------------------------------------------------
def _yandex_chat(system: str, user: str, temperature: float = 0.3, **_) -> str:
    if requests is None:
        raise LLMError("requests не установлен")
    key = os.environ.get("YANDEX_API_KEY")
    folder = os.environ.get("YANDEX_FOLDER_ID")
    if not key or not folder:
        raise LLMError("YANDEX_API_KEY / YANDEX_FOLDER_ID не заданы в .env")
    model = os.environ.get("YANDEX_MODEL", "yandexgpt-lite")
    r = requests.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        headers={"Authorization": f"Api-Key {key}", "Content-Type": "application/json"},
        json={
            "modelUri": f"gpt://{folder}/{model}/latest",
            "completionOptions": {"temperature": temperature, "maxTokens": 1000},
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": user},
            ],
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise LLMError(f"YandexGPT {r.status_code}: {r.text[:200]}")
    return r.json()["result"]["alternatives"][0]["message"]["text"].strip()


_PROVIDERS = {
    "mock": _mock_chat,
    "gigachat": _gigachat_chat,
    "yandex": _yandex_chat,
}


def chat(system: str, user: str, temperature: float = 0.3) -> str:
    """Главная точка входа. Провайдер берётся из LLM_PROVIDER."""
    fn = _PROVIDERS.get(_provider())
    if fn is None:
        raise LLMError(f"Неизвестный LLM_PROVIDER={_provider()}. Доступно: {list(_PROVIDERS)}")
    return fn(system, user, temperature=temperature)


def available() -> bool:
    """Можно ли реально звать LLM (mock — всегда да)."""
    p = _provider()
    if p == "mock":
        return True
    if p == "gigachat":
        return bool(os.environ.get("GIGACHAT_AUTH_KEY"))
    if p == "yandex":
        return bool(os.environ.get("YANDEX_API_KEY") and os.environ.get("YANDEX_FOLDER_ID"))
    return False


if __name__ == "__main__":
    print("provider:", _provider(), "available:", available())
    print(chat("Ты помощник.", "Привет, кто ты?"))
