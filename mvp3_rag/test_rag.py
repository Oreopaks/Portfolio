"""
Офлайн-тесты MVP3 (без сети, без ключей: LLM=mock, эмбеддинги локальные).
Запуск: cd /home/oleg/freelance-mvp && .venv/bin/python mvp3_rag/test_rag.py
"""
import os
import sys
sys.path.insert(0, "/home/oleg/freelance-mvp")

# Ядро тестов гоняем на детерминированном TF-IDF (без сети/модели). Dense-путь
# проверяется отдельным guarded-тестом ниже. ВАЖНО: задать ДО импорта rag —
# rag._DENSE вычисляется на импорте.
os.environ["RAG_BACKEND"] = "tfidf"

from pathlib import Path

from mvp3_rag import rag
from mvp3_rag.embedder import LocalEmbedder, cosine


def test_embedder_basics():
    emb = LocalEmbedder().fit(["возврат товара 14 дней", "доставка по москве"])
    v = emb.embed("возврат")
    assert isinstance(v, dict) and v, "embed должен вернуть непустой dict"
    a = emb.embed("сколько дней на возврат")
    b = emb.embed("возврат товара в течение 14 дней")
    c = emb.embed("способы оплаты картой")
    assert cosine(a, b) > cosine(a, c), "близкий по теме текст должен быть ближе"
    assert cosine(a, a) > 0.99, "cosine с самим собой ~ 1.0"
    print("OK embedder")


def test_chunking():
    text = "слово " * 400  # ~2400 символов
    chunks = rag.chunk_text(text, size=500, overlap=80)
    assert len(chunks) > 1, "длинный текст должен дать несколько чанков"
    assert all(len(c) <= 600 for c in chunks), "чанки не должны сильно превышать size"
    print(f"OK chunking ({len(chunks)} чанков)")


def test_retrieval_and_answer():
    kb = Path(__file__).resolve().parent / "sample_docs" / "company_kb.md"
    text = kb.read_text(encoding="utf-8")
    rag.build_index([(kb.name, text)])

    # факт: возврат — 14 дней
    hits = rag.search("сколько дней на возврат товара?", k=3)
    assert hits, "search должен вернуть результаты"
    top = hits[0]
    assert "возврат" in top["chunk"].lower(), f"топ-чанк должен быть про возврат: {top['chunk'][:80]}"
    assert top["score"] > 0, "score должен быть положительным"

    res = rag.answer("сколько дней на возврат товара?", k=3)
    assert isinstance(res, dict)
    assert res["sources"], "sources не должны быть пустыми"
    assert isinstance(res["answer"], str) and res["answer"].strip(), "answer — непустая строка"
    print("OK retrieval+answer")

    # ещё один факт: гарантия 12 месяцев
    g = rag.search("какой гарантийный срок?", k=3)
    assert "гаранти" in g[0]["chunk"].lower(), f"топ про гарантию: {g[0]['chunk'][:80]}"
    print("OK second fact (гарантия)")


def test_persistence():
    # индекс должен был сохраниться на диск предыдущим тестом
    assert rag.INDEX_PATH.exists(), "rag_index.json должен быть создан"
    rag._INDEX = None  # сбрасываем кэш, форсим загрузку с диска
    loaded = rag.load_index()
    assert loaded and loaded.get("chunks"), "индекс должен загрузиться с диска"
    print("OK persistence")


def test_dense_embedder_optional():
    """Семантика dense-эмбеддера: близкий по смыслу, но без общих слов, ближе
    нерелевантного. Пропускается, если fastembed/модель недоступны (офлайн/CI)."""
    try:
        from mvp3_rag.embedder import DenseEmbedder, dense_cosine
        emb = DenseEmbedder()
        q = emb.embed("сколько суток на отказ от покупки")
        rel = emb.embed("возврат товара возможен в течение 14 дней")
        irr = emb.embed("доставка курьером по городу завтра")
    except Exception as e:  # нет fastembed или модель не качается — не блокируем оффлайн-прогон
        print(f"SKIP dense (нет fastembed/модели): {type(e).__name__}")
        return
    assert dense_cosine(q, rel) > dense_cosine(q, irr), "семантически близкий должен быть ближе"
    assert len(q) == DenseEmbedder.DIM
    print("OK dense embedder (семантика без общих слов)")


if __name__ == "__main__":
    test_embedder_basics()
    test_chunking()
    test_retrieval_and_answer()
    test_persistence()
    test_dense_embedder_optional()
    print("MVP3 TESTS OK")
