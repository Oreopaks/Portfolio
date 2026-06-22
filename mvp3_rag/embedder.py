"""
Локальные эмбеддинги без внешних зависимостей (чистый Python).

LocalEmbedder — TF-IDF поверх мешка слов. Токенизация по русским и
английским словам, нижний регистр. Вектор — это dict {term: weight},
нормированный к единичной длине, поэтому cosine = просто скалярное
произведение пересекающихся ключей.

ApiEmbedder — заглушка под боевые эмбеддинги (OpenAI/Yandex/...).
Не обязана работать в офлайне; оставлена как точка расширения.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Tuple

# Слова: последовательности букв (рус./лат.) и цифр. Дефисы внутри слова
# режутся — для FAQ-доменов этого достаточно.
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> List[str]:
    """Нижний регистр + слова из русских/латинских букв и цифр."""
    return _TOKEN_RE.findall((text or "").lower())


class LocalEmbedder:
    """
    TF-IDF эмбеддер. Словарь IDF строится на корпусе через fit(); если
    корпус не передан — IDF считается единичным (получается чистый TF),
    что тоже работает для cosine, просто без взвешивания редких слов.
    """

    def __init__(self) -> None:
        self.idf: Dict[str, float] = {}
        self.n_docs: int = 0

    # -- обучение IDF на корпусе -------------------------------------------
    def fit(self, corpus: Iterable[str]) -> "LocalEmbedder":
        docs = [set(tokenize(t)) for t in corpus]
        self.n_docs = len(docs)
        df: Counter = Counter()
        for terms in docs:
            df.update(terms)
        # сглаженный IDF (никогда не ноль, чтобы термин из одного документа
        # всё равно имел вес)
        self.idf = {
            term: math.log((1 + self.n_docs) / (1 + cnt)) + 1.0
            for term, cnt in df.items()
        }
        return self

    # -- вектор одного текста ----------------------------------------------
    def embed(self, text: str) -> Dict[str, float]:
        """Возвращает нормированный разреженный вектор {term: weight}."""
        tokens = tokenize(text)
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = float(len(tokens))
        vec: Dict[str, float] = {}
        for term, cnt in tf.items():
            idf = self.idf.get(term, 1.0)  # незнакомый термин -> вес 1.0
            vec[term] = (cnt / total) * idf
        # L2-нормализация -> cosine сводится к скалярному произведению
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm > 0:
            for term in vec:
                vec[term] /= norm
        return vec


def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Косинусная близость двух разреженных векторов (dict term->weight)."""
    if not a or not b:
        return 0.0
    # итерируемся по меньшему словарю
    if len(a) > len(b):
        a, b = b, a
    dot = 0.0
    for term, wa in a.items():
        wb = b.get(term)
        if wb is not None:
            dot += wa * wb
    # векторы из embed() уже нормированы; для подстраховки нормируем здесь,
    # если кто-то подал ненормированные.
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dense_cosine(a: List[float], b: List[float]) -> float:
    """Косинус двух плотных векторов (list[float])."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class DenseEmbedder:
    """
    Плотные мультиязычные эмбеддинги через fastembed (ONNX, без torch).
    Модель paraphrase-multilingual-MiniLM-L12-v2 (dim=384) понимает русский ПО СМЫСЛУ:
    находит «возврат 14 дней» по запросу «сколько дней на отказ от покупки», чего
    TF-IDF (пересечение слов) не умеет. Скачивается один раз (~220 МБ), дальше офлайн.

    Модель — синглтон на класс: все боты в supervisor делят один инстанс в памяти.
    """

    MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    DIM = 384
    _model = None  # type: ignore[var-annotated]

    @classmethod
    def _get(cls):
        if cls._model is None:
            from fastembed import TextEmbedding  # тяжёлый импорт — только при первом вызове
            cls._model = TextEmbedding(model_name=cls.MODEL)
        return cls._model

    def fit(self, corpus: Iterable[str]) -> "DenseEmbedder":  # для совместимости интерфейса
        return self

    def embed(self, text: str) -> List[float]:
        return [float(x) for x in next(self._get().embed([text or ""]))]

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        return [[float(x) for x in v] for v in self._get().embed(list(texts))]
