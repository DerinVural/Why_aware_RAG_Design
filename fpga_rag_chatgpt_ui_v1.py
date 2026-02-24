#!/usr/bin/env python3
"""Local web UI for FPGA RAG + ChatGPT synthesis.

Usage:
  OPENAI_API_KEY=... python3 fpga_rag_chatgpt_ui_v1.py --port 8787
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from fpga_rag_query_v4 import DEFAULT_DB, DEFAULT_GRAPH, build_engine


HTML = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Why-Aware FPGA RAG UI</title>
  <style>
    :root {
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #1f2937;
      --muted: #4b5563;
      --accent: #0f766e;
      --accent-2: #b45309;
      --border: #d1d5db;
    }
    body {
      margin: 0;
      background: radial-gradient(circle at 10% 0%, #fff7e6 0%, var(--bg) 55%);
      color: var(--ink);
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    }
    .wrap { max-width: 1100px; margin: 20px auto; padding: 0 14px; }
    .hero {
      background: linear-gradient(135deg, #0f766e, #1d4ed8);
      color: #fff;
      padding: 18px;
      border-radius: 12px;
      box-shadow: 0 10px 24px rgba(0,0,0,0.13);
    }
    .hero h1 { margin: 0 0 6px 0; font-size: 24px; }
    .hero p { margin: 0; opacity: 0.95; }
    .panel {
      margin-top: 14px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
    }
    .row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    label { font-size: 13px; color: var(--muted); display: block; margin-bottom: 4px; }
    select, input, textarea, button {
      font: inherit;
      border-radius: 8px;
      border: 1px solid var(--border);
      padding: 10px;
    }
    textarea { width: 100%; min-height: 110px; resize: vertical; }
    .col { flex: 1 1 220px; }
    .btn {
      background: var(--accent);
      color: #fff;
      border: none;
      cursor: pointer;
      font-weight: 600;
    }
    .btn.secondary { background: var(--accent-2); }
    .btn:disabled { opacity: 0.7; cursor: wait; }
    pre {
      white-space: pre-wrap;
      background: #111827;
      color: #f9fafb;
      padding: 12px;
      border-radius: 8px;
      overflow: auto;
      margin: 0;
    }
    .grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
    @media (min-width: 960px) { .grid { grid-template-columns: 1fr 1fr; } }
    .hint { color: var(--muted); font-size: 13px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Why-Aware FPGA RAG Test Arayüzü</h1>
      <p>RAG sonucunu doğrudan gör, istersen aynı context ile ChatGPT yanıtı üret.</p>
    </div>

    <div class="panel">
      <div class="row">
        <div class="col">
          <label for="backend">Backend</label>
          <select id="backend">
            <option value="sqlite" selected>sqlite</option>
            <option value="json">json</option>
          </select>
        </div>
        <div class="col">
          <label for="model">ChatGPT Model</label>
          <input id="model" value="gpt-4.1-mini" />
        </div>
        <div class="col">
          <label for="use_llm">LLM Sentez</label>
          <select id="use_llm">
            <option value="1" selected>Açık</option>
            <option value="0">Kapalı (yalnızca RAG)</option>
          </select>
        </div>
      </div>

      <label for="query">Soru</label>
      <textarea id="query" placeholder="Örn: Neden DMA seçildi, alternatifler neydi?"></textarea>

      <div class="row">
        <button id="ask" class="btn">Sor</button>
        <button id="sample1" class="btn secondary">Örnek: WHY</button>
        <button id="sample2" class="btn secondary">Örnek: TRACE</button>
        <button id="sample3" class="btn secondary">Örnek: LED Pinleri</button>
      </div>
      <p class="hint">Not: OPENAI_API_KEY yoksa sadece RAG sonucu döner, LLM alanında uyarı görünür.</p>
    </div>

    <div class="grid">
      <div class="panel">
        <h3>RAG Kısa Cevap</h3>
        <pre id="rag_answer">Henüz sorgu yok.</pre>
      </div>
      <div class="panel">
        <h3>ChatGPT Yanıtı</h3>
        <pre id="llm">Henüz sorgu yok.</pre>
      </div>
      <div class="panel">
        <h3>Ham RAG JSON</h3>
        <pre id="rag">Henüz sorgu yok.</pre>
      </div>
    </div>
  </div>

  <script>
    const queryEl = document.getElementById("query");
    const ragEl = document.getElementById("rag");
    const ragAnswerEl = document.getElementById("rag_answer");
    const llmEl = document.getElementById("llm");
    const askBtn = document.getElementById("ask");

    document.getElementById("sample1").addEventListener("click", () => {
      queryEl.value = "Neden DMA seçildi, alternatifler neydi?";
    });
    document.getElementById("sample2").addEventListener("click", () => {
      queryEl.value = "DMA-REQ-L0-001'in alt gereksinimleri neler?";
    });
    document.getElementById("sample3").addEventListener("click", () => {
      queryEl.value = "Proje B'de AXI GPIO IP'si kaç kanallı konfigüre edilmiş, GPIO genişliği nedir ve LED çıkışları hangi FPGA pinlerine atanmıştır?";
    });

    async function ask() {
      const q = queryEl.value.trim();
      if (!q) return;
      askBtn.disabled = true;
      askBtn.textContent = "Sorgulanıyor...";
      ragEl.textContent = "Yükleniyor...";
      ragAnswerEl.textContent = "Yükleniyor...";
      llmEl.textContent = "Yükleniyor...";
      try {
        const resp = await fetch("/api/ask", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            query: q,
            backend: document.getElementById("backend").value,
            use_llm: document.getElementById("use_llm").value === "1",
            model: document.getElementById("model").value.trim() || "gpt-4.1-mini"
          })
        });
        const data = await resp.json();
        ragEl.textContent = JSON.stringify(data.rag_result, null, 2);
        ragAnswerEl.textContent = (data.rag_result && data.rag_result.answer) ? data.rag_result.answer : "(RAG answer yok)";
        llmEl.textContent = data.llm_answer || data.llm_error || "(LLM kapalı)";
      } catch (e) {
        ragEl.textContent = "İstek hatası: " + e;
        ragAnswerEl.textContent = "İstek hatası";
        llmEl.textContent = "İstek hatası";
      } finally {
        askBtn.disabled = false;
        askBtn.textContent = "Sor";
      }
    }

    askBtn.addEventListener("click", ask);
  </script>
</body>
</html>
"""


def call_openai_responses(model: str, question: str, rag_result: Dict[str, Any], api_key: str, timeout: int = 40) -> str:
    system = (
        "Sen FPGA RAG yardımcı asistanısın. Sadece verilen RAG kanıtlarına dayan. "
        "Kanıt olmayan bilgi uydurma. Eğer rag_result.answer içinde açık değerler varsa (pin, adres, sayı), "
        "bunları aynen koru ve çelişme üretme. Yanıtı Türkçe ve net ver."
    )
    user_payload = {
        "question": question,
        "rag_result": rag_result,
        "instructions": "Önce kısa cevap ver, sonra 2-4 maddede hangi kanıta dayandığını belirt.",
    }
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}],
            },
        ],
        "temperature": 0.2,
        "max_output_tokens": 600,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI bağlantı hatası: {exc}") from exc

    if isinstance(payload, dict):
        txt = payload.get("output_text")
        if txt:
            return txt
        out = payload.get("output", [])
        chunks = []
        for item in out:
            for c in item.get("content", []):
                t = c.get("text")
                if t:
                    chunks.append(t)
        if chunks:
            return "\n".join(chunks)
    raise RuntimeError("OpenAI yanıtı parse edilemedi.")


class AppServer(HTTPServer):
    def __init__(self, server_address, handler_cls, graph: Path, db: Path, default_model: str):
        super().__init__(server_address, handler_cls)
        self.graph = graph
        self.db = db
        self.default_model = default_model
        self.engine_cache: Dict[str, Any] = {}
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    def get_engine(self, backend: str):
        key = backend if backend in {"json", "sqlite"} else "sqlite"
        if key not in self.engine_cache:
            self.engine_cache[key] = build_engine(key, self.graph, self.db)
        return self.engine_cache[key]

    def close_all(self) -> None:
        for eng in self.engine_cache.values():
            close = getattr(eng, "close", None)
            if callable(close):
                close()


class Handler(BaseHTTPRequestHandler):
    server: AppServer  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[ui] " + (fmt % args) + "\n")

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "api_key_configured": bool(self.server.api_key),
                    "graph": str(self.server.graph),
                    "db": str(self.server.db),
                },
            )
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/ask":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n)
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        query = str(req.get("query", "")).strip()
        if not query:
            self._send_json(400, {"error": "query is required"})
            return
        backend = str(req.get("backend", "sqlite")).strip().lower()
        use_llm = bool(req.get("use_llm", True))
        model = str(req.get("model", self.server.default_model)).strip() or self.server.default_model

        try:
            engine = self.server.get_engine(backend)
            rag_result = engine.query(query)
        except Exception as exc:
            self._send_json(500, {"error": f"RAG query failed: {exc}"})
            return

        response: Dict[str, Any] = {
            "backend": backend,
            "query": query,
            "rag_result": rag_result,
        }
        if use_llm:
            if not self.server.api_key:
                response["llm_error"] = "OPENAI_API_KEY tanımlı değil. LLM sentez devre dışı."
            else:
                try:
                    response["llm_answer"] = call_openai_responses(model, query, rag_result, self.server.api_key)
                except Exception as exc:
                    response["llm_error"] = str(exc)
        self._send_json(200, response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Why-aware FPGA RAG web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--graph", default=str(DEFAULT_GRAPH))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    graph = Path(args.graph)
    db = Path(args.db)
    app = AppServer((args.host, args.port), Handler, graph=graph, db=db, default_model=args.model)
    print(f"UI running at http://{args.host}:{args.port}")
    print(f"Graph: {graph}")
    print(f"DB:    {db}")
    print(f"OPENAI_API_KEY configured: {bool(app.api_key)}")
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close_all()
        app.server_close()


if __name__ == "__main__":
    main()
