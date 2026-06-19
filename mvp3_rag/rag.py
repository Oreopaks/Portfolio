"""
RAG-ядро: чанкинг, индекс (chunks + vectors + doc names), поиск по cosine
и генерация ответа с цитированием источников через shared.llm.chat.

Работает полностью офлайн: эмбеддинги локальные (LocalEmbedder), LLM по
умолчанию mock. Боевой LLM включается через LLM_PROVIDER в .env.
"""
from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

# гарантируем, что shared.* импортируется при любом cwd
sys.path.insert(0, "/home/oleg/freelance-mvp")

import shared.config  # noqa: F401  подхватывает .env при импорте
from shared.llm import chat

from mvp3_rag.embedder import LocalEmbedder, cosine

INDEX_PATH = Path(__file__).resolve().parent / "rag_index.json"

SYSTEM_PROMPT = "Отвечай ТОЛЬКО по контексту, добавляй ссылку на источник"

# индекс в памяти процесса
_INDEX: Dict | None = None


# ---------------------------------------------------------------------------
# Чанкинг
# ---------------------------------------------------------------------------
def chunk_text(text: str, size: int = 500, overlap: int = 80) -> List[str]:
    """
    Режет текст на перекрывающиеся куски ~size символов с overlap.
    Старается не рвать слова: ищет ближайший пробел/перенос к границе.
    """
    text = (text or "").strip()
    if not text:
        return []
    if size <= 0:
        return [text]
    if overlap >= size:
        overlap = size // 4

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # отступаем к ближайшему пробелу, чтобы не резать слово
            window = text.rfind(" ", start, end)
            nl = text.rfind("\n", start, end)
            cut = max(window, nl)
            if cut > start + size // 2:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# ---------------------------------------------------------------------------
# Построение / загрузка индекса
# ---------------------------------------------------------------------------
def _serialize_vec(vec: Dict[str, float]) -> Dict[str, float]:
    # round для компактности json
    return {k: round(v, 6) for k, v in vec.items()}


def build_index(docs: List[Tuple[str, str]]) -> Dict:
    """
    docs: список (doc_name, text). Строит чанки, эмбеддинги и сохраняет
    индекс в rag_index.json. Возвращает индекс (dict).
    """
    all_chunks: List[Dict] = []
    for doc_name, text in docs:
        for ch in chunk_text(text):
            all_chunks.append({"doc": doc_name, "chunk": ch})

    embedder = LocalEmbedder().fit([c["chunk"] for c in all_chunks])
    for c in all_chunks:
        c["vector"] = _serialize_vec(embedder.embed(c["chunk"]))

    index = {
        "version": 1,
        "idf": {k: round(v, 6) for k, v in embedder.idf.items()},
        "n_docs": embedder.n_docs,
        "chunks": all_chunks,
    }
    _save_index(index)
    global _INDEX
    _INDEX = index
    return index


def extend_index(docs: List[Tuple[str, str]]) -> Dict:
    """
    Добавляет документы к существующему индексу и пересчитывает IDF/векторы
    по объединённому корпусу (для маленьких FAQ это дёшево и корректно).
    """
    existing = load_index()
    pairs: Dict[str, str] = {}
    order: List[str] = []
    if existing and existing.get("chunks"):
        # восстанавливаем тексты документов из чанков (для пересчёта IDF)
        for c in existing["chunks"]:
            if c["doc"] not in pairs:
                pairs[c["doc"]] = ""
                order.append(c["doc"])
            pairs[c["doc"]] += c["chunk"] + "\n"
    for doc_name, text in docs:
        if doc_name not in pairs:
            order.append(doc_name)
            pairs[doc_name] = ""
        pairs[doc_name] += text + "\n"
    return build_index([(name, pairs[name]) for name in order])


def _save_index(index: Dict) -> None:
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8"
    )


def load_index() -> Dict | None:
    """Загружает индекс из памяти, иначе с диска."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    if INDEX_PATH.exists():
        _INDEX = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return _INDEX


def _embedder_from_index(index: Dict) -> LocalEmbedder:
    emb = LocalEmbedder()
    emb.idf = {k: float(v) for k, v in index.get("idf", {}).items()}
    emb.n_docs = int(index.get("n_docs", 0))
    return emb


# ---------------------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------------------
def search(query: str, k: int = 3) -> List[Dict]:
    """Top-k чанков по cosine. -> [{"doc","chunk","score"}]."""
    index = load_index()
    if not index or not index.get("chunks"):
        return []
    emb = _embedder_from_index(index)
    qvec = emb.embed(query)
    scored: List[Dict] = []
    for c in index["chunks"]:
        score = cosine(qvec, c["vector"])
        scored.append({"doc": c["doc"], "chunk": c["chunk"], "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


# ---------------------------------------------------------------------------
# Ответ с цитированием
# ---------------------------------------------------------------------------
def answer(query: str, k: int = 3) -> Dict:
    """
    Собирает контекст из top-k чанков, зовёт LLM с инструкцией отвечать
    только по контексту и ссылаться на источник. Возвращает
    {"answer": str, "sources": [{"doc","chunk","score"}]}.
    """
    hits = search(query, k=k)
    if not hits:
        return {
            "answer": "В базе знаний нет документов. Сначала загрузите документ.",
            "sources": [],
        }

    context_blocks = []
    for i, h in enumerate(hits, 1):
        context_blocks.append(f"[Источник {i}: {h['doc']}]\n{h['chunk']}")
    context = "\n\n".join(context_blocks)

    user = f"Контекст:\n{context}\n\nВопрос: {query}"
    reply = chat(SYSTEM_PROMPT, user)

    return {"answer": reply, "sources": hits}


if __name__ == "__main__":  # быстрая ручная проверка
    kb = Path(__file__).resolve().parent / "sample_docs" / "company_kb.md"
    build_index([(kb.name, kb.read_text(encoding="utf-8"))])
    q = "сколько дней на возврат?"
    res = answer(q)
    print("Q:", q)
    print("A:", res["answer"])
    for s in res["sources"]:
        print(f"  - {s['doc']} (score={s['score']:.3f})")
