# Orwell Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar um container `dashboard` (FastAPI + HTML/JS inline) na porta 3000 com docs de rotas, preview ao vivo (HLS embed) e timeline interativa para baixar clipes.

**Architecture:** Novo serviço `services/dashboard/` com um único arquivo FastAPI que serve uma página HTML estática. A página usa JS puro para consultar a clip-api (`/cameras`, `/range`) e montar a timeline. Adicionar `GET /range?camera=X` na clip-api para expor o período gravado.

**Tech Stack:** Python 3.11, FastAPI, Jinja2 (template HTML inline), JS puro, sem npm/node.

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `services/clip-api/clip_api/main.py` | Modificar | Adicionar `GET /range` |
| `services/clip-api/tests/test_clip_api.py` | Modificar | Testes do novo endpoint |
| `services/dashboard/dashboard/main.py` | Criar | FastAPI servindo o HTML |
| `services/dashboard/dashboard/__init__.py` | Criar | Pacote Python |
| `services/dashboard/dashboard/page.html` | Criar | UI completa (docs + preview + timeline) |
| `services/dashboard/Dockerfile` | Criar | Container dashboard |
| `docker-compose.yml` | Modificar | Adicionar serviço dashboard |

---

## Task 1: Adicionar `GET /range` na clip-api

**Files:**
- Modify: `services/clip-api/clip_api/main.py`
- Modify: `services/clip-api/tests/test_clip_api.py`

- [ ] **Step 1: Escrever o teste falhando**

Em `services/clip-api/tests/test_clip_api.py`, adicionar após os imports existentes:

```python
def test_range_empty(client):
    r = client.get("/range?camera=99")
    assert r.status_code == 200
    assert r.json() == {"camera": "99", "first": None, "last": None}


def test_range_with_segments(client, tmp_path):
    from orwell_shared.index import Segment, SegmentIndex
    from orwell_shared.clips import extract_clip
    import os

    db = str(tmp_path / "idx.sqlite")
    idx = SegmentIndex(db)
    idx.add_segment(Segment("0", 1000.0, 1004.0, "/data/seg1.m4s", 100, 1000.0))
    idx.add_segment(Segment("0", 1004.0, 1008.0, "/data/seg2.m4s", 100, 1004.0))

    from fastapi.testclient import TestClient
    from clip_api.main import create_app
    app2 = create_app()
    app2.state.index = idx
    # patch index diretamente
    import clip_api.main as m
    orig = m.SegmentIndex
    m.SegmentIndex = lambda *a, **kw: idx
    c2 = TestClient(create_app())
    m.SegmentIndex = orig

    r = c2.get("/range?camera=0")
    assert r.status_code == 200
    data = r.json()
    assert data["first"] is not None
    assert data["last"] is not None
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
python -m pytest services/clip-api/tests/test_clip_api.py::test_range_empty -v
```
Expected: `FAILED` — `AttributeError: 'TestClient' object has no attribute...` ou `404`

- [ ] **Step 3: Implementar `GET /range` em `services/clip-api/clip_api/main.py`**

Adicionar dentro de `create_app()`, após o endpoint `/segments`:

```python
    @app.get("/range")
    def range_endpoint(camera: str = Query(...)):
        oldest = index.oldest(camera)
        newest_rows = index._conn.execute(
            "SELECT * FROM segments WHERE camera_id=? ORDER BY t_end DESC LIMIT 1",
            (camera,)
        ).fetchone()
        newest = index._row(newest_rows) if newest_rows else None

        def fmt(ts: float | None) -> str | None:
            if ts is None:
                return None
            from datetime import datetime, timezone
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "camera": camera,
            "first": fmt(oldest.t_start) if oldest else None,
            "last":  fmt(newest.t_end)   if newest else None,
        }
```

- [ ] **Step 4: Rodar os testes**

```bash
python -m pytest services/clip-api/tests/test_clip_api.py -v
```
Expected: todos passando, incluindo `test_range_empty`.

- [ ] **Step 5: Commit**

```bash
git add services/clip-api/clip_api/main.py services/clip-api/tests/test_clip_api.py
git commit -m "feat(clip-api): GET /range returns first/last timestamp for camera"
```

---

## Task 2: Criar o serviço dashboard

**Files:**
- Create: `services/dashboard/dashboard/__init__.py`
- Create: `services/dashboard/dashboard/main.py`
- Create: `services/dashboard/dashboard/page.html`

- [ ] **Step 1: Criar o pacote**

`services/dashboard/dashboard/__init__.py` — arquivo vazio.

- [ ] **Step 2: Criar `services/dashboard/dashboard/main.py`**

```python
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_HERE = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Orwell Dashboard")
    clip_api_url = os.environ.get("CLIP_API_URL", "http://clip-api:8080")
    preview_url = os.environ.get("PREVIEW_URL", "http://localhost:8888")
    html = (_HERE / "page.html").read_text()
    html = html.replace("__CLIP_API_URL__", clip_api_url)
    html = html.replace("__PREVIEW_URL__", preview_url)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 3: Criar `services/dashboard/dashboard/page.html`**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Orwell Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  header { padding: 1.5rem 2rem; border-bottom: 1px solid #1e2a3a; display: flex; align-items: center; gap: 1rem; }
  header h1 { font-size: 1.25rem; font-weight: 600; color: #38bdf8; }
  header span { font-size: 0.8rem; color: #64748b; }
  .container { max-width: 960px; margin: 0 auto; padding: 2rem; display: flex; flex-direction: column; gap: 2rem; }
  .card { background: #1a2030; border: 1px solid #1e2a3a; border-radius: 10px; overflow: hidden; }
  .card-header { padding: 1rem 1.5rem; border-bottom: 1px solid #1e2a3a; font-weight: 600; font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
  .card-body { padding: 1.5rem; }

  /* Docs */
  .route { display: grid; grid-template-columns: auto 1fr; gap: 0.5rem 1rem; align-items: start; padding: 0.75rem 0; border-bottom: 1px solid #1e2a3a; }
  .route:last-child { border-bottom: none; }
  .method { background: #0ea5e9; color: #fff; font-size: 0.7rem; font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px; font-family: monospace; align-self: center; }
  .method.get { background: #10b981; }
  .route-info { display: flex; flex-direction: column; gap: 0.2rem; }
  .route-path { font-family: monospace; font-size: 0.875rem; color: #e2e8f0; }
  .route-desc { font-size: 0.8rem; color: #64748b; }
  .route-params { font-family: monospace; font-size: 0.75rem; color: #38bdf8; }

  /* Preview */
  .preview-controls { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
  .btn { padding: 0.5rem 1.25rem; border-radius: 6px; border: none; font-size: 0.875rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-primary { background: #0ea5e9; color: #fff; }
  .btn-danger { background: #ef4444; color: #fff; }
  .btn-success { background: #10b981; color: #fff; }
  .camera-select { background: #0f1117; border: 1px solid #1e2a3a; color: #e2e8f0; padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.875rem; }
  #preview-container { display: none; }
  #preview-container iframe { width: 100%; aspect-ratio: 16/9; border: none; border-radius: 6px; background: #000; }
  #preview-status { font-size: 0.8rem; color: #64748b; }

  /* Timeline */
  .timeline-controls { display: flex; flex-direction: column; gap: 1rem; }
  .field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  label { font-size: 0.8rem; color: #94a3b8; display: block; margin-bottom: 0.35rem; }
  input[type="datetime-local"] {
    width: 100%; background: #0f1117; border: 1px solid #1e2a3a;
    color: #e2e8f0; padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.875rem;
  }
  input[type="datetime-local"]:focus { outline: none; border-color: #0ea5e9; }
  .timeline-bar-wrap { background: #0f1117; border: 1px solid #1e2a3a; border-radius: 6px; padding: 1rem; }
  .timeline-label { font-size: 0.75rem; color: #64748b; display: flex; justify-content: space-between; margin-bottom: 0.5rem; }
  .timeline-track { height: 10px; background: #1e2a3a; border-radius: 99px; position: relative; overflow: hidden; }
  .timeline-fill { height: 100%; background: #10b981; border-radius: 99px; width: 0%; transition: width 0.3s; }
  .timeline-selection { position: absolute; top: 0; height: 100%; background: #0ea5e9; opacity: 0.6; pointer-events: none; }
  .download-row { display: flex; gap: 1rem; align-items: center; }
  #range-info { font-size: 0.8rem; color: #64748b; }
  #download-status { font-size: 0.8rem; margin-top: 0.5rem; }
</style>
</head>
<body>
<header>
  <h1>Orwell DVR</h1>
  <span id="cam-badge">carregando câmeras...</span>
</header>

<div class="container">

  <!-- DOCS -->
  <div class="card">
    <div class="card-header">API Reference</div>
    <div class="card-body">
      <div class="route">
        <span class="method get">GET</span>
        <div class="route-info">
          <span class="route-path">/healthz</span>
          <span class="route-desc">Status do serviço</span>
        </div>
      </div>
      <div class="route">
        <span class="method get">GET</span>
        <div class="route-info">
          <span class="route-path">/cameras</span>
          <span class="route-desc">Lista câmeras com segmentos gravados</span>
        </div>
      </div>
      <div class="route">
        <span class="method get">GET</span>
        <div class="route-info">
          <span class="route-path">/range</span>
          <span class="route-desc">Período disponível de gravação para uma câmera</span>
          <span class="route-params">?camera=0</span>
        </div>
      </div>
      <div class="route">
        <span class="method get">GET</span>
        <div class="route-info">
          <span class="route-path">/segments</span>
          <span class="route-desc">Lista segmentos num intervalo</span>
          <span class="route-params">?camera=0&amp;start=2026-06-01T00:00:00Z&amp;end=2026-06-01T01:00:00Z</span>
        </div>
      </div>
      <div class="route">
        <span class="method get">GET</span>
        <div class="route-info">
          <span class="route-path">/clips</span>
          <span class="route-desc">Baixa MP4 do intervalo (ffmpeg copy)</span>
          <span class="route-params">?camera=0&amp;start=2026-06-01T00:00:00Z&amp;end=2026-06-01T00:00:30Z</span>
        </div>
      </div>
    </div>
  </div>

  <!-- PREVIEW -->
  <div class="card">
    <div class="card-header">Preview ao vivo</div>
    <div class="card-body">
      <div class="preview-controls">
        <select class="camera-select" id="preview-cam">
          <option value="0">Câmera 0</option>
        </select>
        <button class="btn btn-primary" id="btn-preview" onclick="togglePreview()">▶ Ver ao vivo</button>
        <span id="preview-status">HLS · ~5s latência</span>
      </div>
      <div id="preview-container">
        <iframe id="preview-iframe" src="" allowfullscreen></iframe>
      </div>
    </div>
  </div>

  <!-- TIMELINE -->
  <div class="card">
    <div class="card-header">Baixar Clipe</div>
    <div class="card-body">
      <div class="timeline-controls">
        <div style="display:flex; gap:1rem; align-items:center;">
          <select class="camera-select" id="clip-cam" onchange="loadRange()">
            <option value="0">Câmera 0</option>
          </select>
          <span id="range-info">Carregando...</span>
        </div>

        <div class="timeline-bar-wrap">
          <div class="timeline-label">
            <span id="range-first">—</span>
            <span id="range-last">—</span>
          </div>
          <div class="timeline-track">
            <div class="timeline-fill" id="timeline-fill"></div>
            <div class="timeline-selection" id="timeline-sel" style="left:0%;width:100%"></div>
          </div>
        </div>

        <div class="field-row">
          <div>
            <label>Início</label>
            <input type="datetime-local" id="clip-start" step="1" oninput="updateSelBar()">
          </div>
          <div>
            <label>Fim</label>
            <input type="datetime-local" id="clip-end" step="1" oninput="updateSelBar()">
          </div>
        </div>

        <div class="download-row">
          <button class="btn btn-success" onclick="downloadClip()">⬇ Baixar clipe</button>
          <button class="btn btn-primary" style="background:#6366f1" onclick="loadRange()">↺ Atualizar</button>
        </div>
        <div id="download-status"></div>
      </div>
    </div>
  </div>

</div>

<script>
const CLIP_API = "__CLIP_API_URL__";
const PREVIEW_BASE = "__PREVIEW_URL__";
let rangeFirst = null, rangeLast = null;

// ── init ──────────────────────────────────────────────────────────────
async function init() {
  try {
    const cams = await fetch(CLIP_API + "/cameras").then(r => r.json());
    document.getElementById("cam-badge").textContent =
      cams.length ? cams.map(c => "cam" + c).join(" · ") + " online" : "nenhuma câmera";
    ["preview-cam", "clip-cam"].forEach(id => {
      const sel = document.getElementById(id);
      sel.innerHTML = cams.map(c => `<option value="${c}">Câmera ${c}</option>`).join("");
    });
  } catch(e) {
    document.getElementById("cam-badge").textContent = "clip-api offline";
  }
  loadRange();
}

// ── preview ───────────────────────────────────────────────────────────
let previewOn = false;
function togglePreview() {
  const cam = document.getElementById("preview-cam").value;
  const iframe = document.getElementById("preview-iframe");
  const container = document.getElementById("preview-container");
  const btn = document.getElementById("btn-preview");
  if (!previewOn) {
    iframe.src = `${PREVIEW_BASE}/cam${cam}`;
    container.style.display = "block";
    btn.textContent = "⏹ Parar";
    btn.className = "btn btn-danger";
    previewOn = true;
  } else {
    iframe.src = "";
    container.style.display = "none";
    btn.textContent = "▶ Ver ao vivo";
    btn.className = "btn btn-primary";
    previewOn = false;
  }
}

// ── timeline / range ──────────────────────────────────────────────────
async function loadRange() {
  const cam = document.getElementById("clip-cam").value;
  const info = document.getElementById("range-info");
  const fill = document.getElementById("timeline-fill");
  info.textContent = "Carregando...";
  fill.style.width = "0%";
  try {
    const data = await fetch(`${CLIP_API}/range?camera=${cam}`).then(r => r.json());
    if (!data.first) {
      info.textContent = "Nenhum vídeo gravado ainda";
      document.getElementById("range-first").textContent = "—";
      document.getElementById("range-last").textContent = "—";
      rangeFirst = null; rangeLast = null;
      return;
    }
    rangeFirst = new Date(data.first);
    rangeLast  = new Date(data.last);
    const durH = ((rangeLast - rangeFirst) / 3600000).toFixed(1);
    info.textContent = `${durH}h disponíveis`;
    document.getElementById("range-first").textContent = fmtLocal(rangeFirst);
    document.getElementById("range-last").textContent  = fmtLocal(rangeLast);
    fill.style.width = "100%";

    // pré-preenche os pickers: últimos 30s
    const end = new Date(rangeLast);
    const start = new Date(Math.max(rangeFirst, end - 30000));
    document.getElementById("clip-start").value = toInputVal(start);
    document.getElementById("clip-end").value   = toInputVal(end);
    updateSelBar();
  } catch(e) {
    info.textContent = "Erro ao carregar range";
  }
}

function updateSelBar() {
  if (!rangeFirst || !rangeLast) return;
  const s = new Date(document.getElementById("clip-start").value);
  const e = new Date(document.getElementById("clip-end").value);
  const total = rangeLast - rangeFirst;
  const left  = Math.max(0, Math.min(100, (s - rangeFirst) / total * 100));
  const right = Math.max(0, Math.min(100, (e - rangeFirst) / total * 100));
  const sel = document.getElementById("timeline-sel");
  sel.style.left  = left + "%";
  sel.style.width = Math.max(0, right - left) + "%";
}

async function downloadClip() {
  const cam   = document.getElementById("clip-cam").value;
  const start = document.getElementById("clip-start").value;
  const end   = document.getElementById("clip-end").value;
  const status = document.getElementById("download-status");
  if (!start || !end) { status.textContent = "Preencha início e fim."; return; }
  const s = new Date(start).toISOString();
  const e = new Date(end).toISOString();
  const url = `${CLIP_API}/clips?camera=${cam}&start=${s}&end=${e}`;
  status.innerHTML = `<span style="color:#0ea5e9">⏳ Gerando clipe...</span>`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      status.innerHTML = `<span style="color:#ef4444">Erro: ${err.detail || resp.status}</span>`;
      return;
    }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `clip-cam${cam}-${start.replace(/[: ]/g,"-")}.mp4`;
    a.click();
    status.innerHTML = `<span style="color:#10b981">✓ Download iniciado</span>`;
  } catch(e) {
    status.innerHTML = `<span style="color:#ef4444">Erro de rede</span>`;
  }
}

// ── helpers ───────────────────────────────────────────────────────────
function fmtLocal(d) {
  return d.toLocaleString("pt-BR", {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit"});
}
function toInputVal(d) {
  // datetime-local espera "YYYY-MM-DDTHH:MM:SS" em hora local
  const pad = n => String(n).padStart(2,"0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

init();
</script>
</body>
</html>
```

- [ ] **Step 4: Commit**

```bash
git add services/dashboard/
git commit -m "feat(dashboard): FastAPI + HTML dashboard (docs, preview, timeline)"
```

---

## Task 3: Dockerfile e docker-compose

**Files:**
- Create: `services/dashboard/Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Criar `services/dashboard/Dockerfile`**

```dockerfile
# Build context = repo root
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29"

COPY services/dashboard/dashboard /app/dashboard

EXPOSE 3000
CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "3000"]
```

- [ ] **Step 2: Adicionar serviço dashboard no `docker-compose.yml`**

Adicionar após o serviço `clip-api`:

```yaml
  dashboard:
    build:
      context: .
      dockerfile: services/dashboard/Dockerfile
    restart: unless-stopped
    environment:
      CLIP_API_URL: http://clip-api:8080
      PREVIEW_URL: http://10.8.64.33:8888
    ports:
      - "3000:3000"
    depends_on: [clip-api]
```

- [ ] **Step 3: Build e smoke test local**

```bash
docker compose build dashboard
docker compose up -d dashboard
curl localhost:3000/healthz
# expected: {"status":"ok"}
```

- [ ] **Step 4: Commit e push**

```bash
git add services/dashboard/Dockerfile docker-compose.yml
git commit -m "build(dashboard): Dockerfile + compose service porta 3000"
git push
```

---

## Task 4: Deploy na Jetson

- [ ] **Step 1: Pull e build na Jetson**

```bash
# na Jetson:
cd /home/user/orwell && git pull
docker compose build dashboard
docker compose up -d dashboard
```

- [ ] **Step 2: Verificar**

```bash
curl localhost:3000/healthz
# {"status":"ok"}
```

- [ ] **Step 3: Acessar no browser**

```
http://10.8.64.33:3000
```

---
