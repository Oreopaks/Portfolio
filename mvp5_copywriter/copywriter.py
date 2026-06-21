"""
MVP5 — AI-копирайтер.

Генерит продающие тексты под бизнес-задачу через LLM (shared.llm.chat):
SEO-статья, описание товара, продающий пост, email-рассылка. Один вход —
короткий бриф (о чём и для кого), на выходе — готовый текст в нужном формате
и тоне, с естественными вхождениями ключевых слов.

CLI:  python mvp5_copywriter/copywriter.py seo "кофейня в центре, акция на раф"
"""
from __future__ import annotations
import sys

sys.path.insert(0, "/home/oleg/freelance-mvp")

from shared.llm import chat

# Форматы текста: system — роль/правила формата, ask — шаблон запроса.
FORMATS = {
    "seo": {
        "name": "SEO-статья",
        "system": (
            "Ты SEO-копирайтер. Пишешь структурированную статью на русском под "
            "поисковые запросы: цепляющий H1, 3-5 подзаголовков H2, абзацы по 2-4 "
            "предложения, естественные вхождения ключевых слов без переспама, вывод "
            "с призывом к действию. Без воды и канцелярита."
        ),
        "ask": "Напиши SEO-статью (600-900 слов) по теме: {brief}.{kw}",
    },
    "product": {
        "name": "Описание товара",
        "system": (
            "Ты копирайтер интернет-магазина. Пишешь продающее описание товара на "
            "русском: первый абзац про выгоду для покупателя, ключевые характеристики "
            "буллетами, закрытие частых возражений, мягкий призыв купить. По делу."
        ),
        "ask": "Опиши товар для карточки магазина: {brief}.{kw}",
    },
    "post": {
        "name": "Продающий пост",
        "system": (
            "Ты SMM-копирайтер. Пишешь продающий пост для соцсетей на русском: "
            "крючок в первой строке, польза или история, оффер, призыв к действию, "
            "3-5 уместных хэштегов в конце. Живой тон, эмодзи уместно."
        ),
        "ask": "Напиши продающий пост: {brief}.{kw}",
    },
    "email": {
        "name": "Email-рассылка",
        "system": (
            "Ты email-маркетолог. Пишешь письмо для рассылки на русском: тема письма "
            "(до 50 символов), прехедер, тело с одной чёткой мыслью и одной кнопкой-CTA. "
            "Без спам-слов и капса."
        ),
        "ask": "Напиши письмо для рассылки: {brief}.{kw}",
    },
}

TONES = ("деловой", "дружелюбный", "экспертный", "продающий")


def formats() -> list[str]:
    """Список доступных форматов «ключ — название» (для CLI/UI)."""
    return [f"{k} — {v['name']}" for k, v in FORMATS.items()]


def generate(kind: str, brief: str, keywords: list[str] | None = None, tone: str = "продающий") -> str:
    """Сгенерировать текст формата `kind` по брифу `brief`.

    keywords — ключи для естественного вхождения (SEO); tone — тон подачи.
    Бросает ValueError на неизвестный формат.
    """
    fmt = FORMATS.get(kind)
    if not fmt:
        raise ValueError(f"неизвестный формат {kind!r}; доступно: {sorted(FORMATS)}")
    if not brief or not brief.strip():
        raise ValueError("пустой бриф")
    kw = f" Ключевые слова для вхождения: {', '.join(keywords)}." if keywords else ""
    system = fmt["system"] + f" Тон: {tone}."
    user = fmt["ask"].format(brief=brief.strip(), kw=kw)
    return chat(system, user, temperature=0.6).strip()


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "post"
    brief = sys.argv[2] if len(sys.argv) > 2 else "кофейня в центре города, акция на раф-кофе"
    print(f"[{FORMATS.get(kind, {}).get('name', kind)}]\n")
    print(generate(kind, brief))
