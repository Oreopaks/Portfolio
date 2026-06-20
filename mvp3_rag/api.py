"""
Flask-приложение для RAG-ассистента.

  POST /ingest  — json {"name","text"} ИЛИ загрузка файла .txt/.md/.pdf
  POST /ask     — json {"query"} -> {"answer","sources"}
  GET  /        — одностраничный UI (вставить документ -> задать вопрос)

Запуск: python mvp3_rag/api.py  (слушает 0.0.0.0:8080)
PDF поддерживается, если установлен pypdf (не обязателен).
"""
from __future__ import annotations

import os
import sys
import io
from pathlib import Path

sys.path.insert(0, "/home/oleg/freelance-mvp")

from flask import Flask, request, jsonify, Response

import shared.config  # noqa: F401  .env
from shared.llm import available
from mvp3_rag import rag

app = Flask(__name__)

# опциональная поддержка PDF — не падаем, если pypdf нет
try:  # pragma: no cover
    import pypdf  # type: ignore

    _HAS_PDF = True
except Exception:  # noqa: BLE001
    pypdf = None  # type: ignore
    _HAS_PDF = False


def _pdf_to_text(data: bytes) -> str:  # pragma: no cover
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAG-ассистент по документам</title>
<style>
  :root { --bg:#0f1117; --card:#1a1d27; --acc:#4f8cff; --txt:#e6e8ee; --mut:#8b90a0; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background:var(--bg); color:var(--txt); }
  .wrap { max-width: 860px; margin: 0 auto; padding: 28px 18px 60px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--mut); margin: 0 0 24px; font-size: 14px; }
  .card { background:var(--card); border:1px solid #262a36; border-radius:14px;
          padding:18px; margin-bottom:18px; }
  label { display:block; font-size:13px; color:var(--mut); margin-bottom:6px; }
  textarea, input[type=text] { width:100%; background:#11131b; color:var(--txt);
          border:1px solid #2c3140; border-radius:10px; padding:10px 12px;
          font-size:14px; font-family:inherit; }
  textarea { min-height:140px; resize:vertical; }
  .row { display:flex; gap:10px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  button { background:var(--acc); color:#fff; border:0; border-radius:10px;
           padding:10px 18px; font-size:14px; cursor:pointer; font-weight:600; }
  button.sec { background:#2a2f3d; }
  button:disabled { opacity:.5; cursor:default; }
  .ask { display:flex; gap:10px; }
  .ask input { flex:1; }
  .answer { white-space:pre-wrap; line-height:1.5; }
  .src { border-left:3px solid var(--acc); padding:8px 12px; margin-top:10px;
         background:#11131b; border-radius:0 8px 8px 0; font-size:13px; }
  .src .meta { color:var(--acc); font-weight:600; margin-bottom:4px; }
  .src .txt { color:var(--mut); }
  .note { font-size:12px; color:var(--mut); }
  .ok { color:#46c98b; } .err { color:#ff6b6b; }
</style>
</head>
<body>
<div class="wrap">
  <h1>RAG-ассистент по документам</h1>
  <p class="sub">Загрузите документ -> задайте вопрос -> получите ответ со ссылками на источники.
     LLM: <b>__PROVIDER__</b></p>

  <div class="card">
    <label>1. Документ (вставьте текст или загрузите файл .txt / .md__PDF__)</label>
    <input type="text" id="docname" placeholder="Название документа, напр. company_kb.md"
           style="margin-bottom:10px">
    <textarea id="doctext" placeholder="Вставьте сюда текст базы знаний..."></textarea>
    <div class="row">
      <button id="ingestBtn">Загрузить в индекс</button>
      <input type="file" id="docfile" accept=".txt,.md,.pdf">
      <span id="ingestMsg" class="note"></span>
    </div>
  </div>

  <div class="card">
    <label>2. Вопрос</label>
    <div class="ask">
      <input type="text" id="query" placeholder="Например: сколько дней на возврат?">
      <button id="askBtn">Спросить</button>
    </div>
    <div id="result" style="margin-top:16px"></div>
  </div>
</div>

<script>
async function postJSON(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify(body)});
  return r.json();
}
const $ = id => document.getElementById(id);

$('ingestBtn').onclick = async () => {
  const file = $('docfile').files[0];
  const msg = $('ingestMsg');
  msg.textContent = 'Индексирую...'; msg.className = 'note';
  try {
    let res;
    if (file) {
      const fd = new FormData(); fd.append('file', file);
      res = await (await fetch('/ingest', {method:'POST', body: fd})).json();
    } else {
      const name = $('docname').value.trim() || 'document.txt';
      const text = $('doctext').value.trim();
      if (!text) { msg.textContent = 'Пусто: вставьте текст или выберите файл'; msg.className='note err'; return; }
      res = await postJSON('/ingest', {name, text});
    }
    if (res.error) { msg.textContent = 'Ошибка: ' + res.error; msg.className='note err'; }
    else { msg.textContent = `Готово: «${res.name}», чанков в индексе: ${res.chunks}`; msg.className='note ok'; }
  } catch (e) { msg.textContent = 'Ошибка: ' + e; msg.className='note err'; }
};

$('askBtn').onclick = async () => {
  const query = $('query').value.trim();
  const box = $('result');
  if (!query) { box.innerHTML = '<span class="note err">Введите вопрос</span>'; return; }
  box.innerHTML = '<span class="note">Думаю...</span>';
  try {
    const res = await postJSON('/ask', {query});
    if (res.error) { box.innerHTML = '<span class="note err">Ошибка: '+res.error+'</span>'; return; }
    let html = '<div class="answer">'+ escapeHtml(res.answer) +'</div>';
    if (res.sources && res.sources.length) {
      html += '<div class="note" style="margin-top:14px">Источники:</div>';
      res.sources.forEach((s,i) => {
        html += `<div class="src"><div class="meta">[${i+1}] ${escapeHtml(s.doc)} · score ${s.score.toFixed(3)}</div>`
              + `<div class="txt">${escapeHtml(s.chunk.slice(0,260))}${s.chunk.length>260?'…':''}</div></div>`;
      });
    }
    box.innerHTML = html;
  } catch (e) { box.innerHTML = '<span class="note err">Ошибка: '+e+'</span>'; }
};
$('query').addEventListener('keydown', e => { if (e.key==='Enter') $('askBtn').click(); });

function escapeHtml(s){return (s||'').replace(/[&<>"']/g, c=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
</body>
</html>
"""


@app.get("/")
def index():
    provider = "реальный" if available() and __import__("os").environ.get(
        "LLM_PROVIDER", "mock"
    ) != "mock" else "mock (офлайн)"
    html = (
        INDEX_HTML.replace("__PROVIDER__", provider)
        .replace("__PDF__", " / .pdf" if _HAS_PDF else "")
    )
    return Response(html, mimetype="text/html")


@app.post("/ingest")
def ingest():
    try:
        # вариант 1: загрузка файла
        if "file" in request.files:
            f = request.files["file"]
            name = f.filename or "upload.txt"
            data = f.read()
            if name.lower().endswith(".pdf"):
                if not _HAS_PDF:
                    return jsonify({"error": "PDF не поддержан: pypdf не установлен"}), 400
                text = _pdf_to_text(data)
            else:
                text = data.decode("utf-8", errors="replace")
        else:
            # вариант 2: json {name, text}
            body = request.get_json(silent=True) or {}
            name = (body.get("name") or "document.txt").strip()
            text = body.get("text") or ""

        text = text.strip()
        if not text:
            return jsonify({"error": "пустой текст"}), 400

        index = rag.extend_index([(name, text)])
        return jsonify({"name": name, "chunks": len(index.get("chunks", []))})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@app.post("/ask")
def ask():
    try:
        body = request.get_json(silent=True) or {}
        query = (body.get("query") or "").strip()
        if not query:
            return jsonify({"error": "пустой запрос"}), 400
        return jsonify(rag.answer(query))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    _port = int(os.environ.get("RAG_PORT", "8080"))
    print(f"RAG API -> http://0.0.0.0:{_port}  (LLM available:", available(), ")")
    app.run(host="0.0.0.0", port=_port, debug=False)
