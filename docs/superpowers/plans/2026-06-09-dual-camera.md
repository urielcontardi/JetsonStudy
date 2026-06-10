# Dual-Camera Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expandir o sistema para suportar duas câmeras com IA independente por câmera, volume de modelos por câmera, e dashboard com split view sincronizado.

**Architecture:** `AIConfig` migra do nível raiz de `OrwellConfig` para campo de `CameraConfig`; recorder passa `camera.ai` para o pipeline de cada câmera; dashboard exibe dois painéis lado a lado com controles de clipe sincronizáveis.

**Tech Stack:** Pydantic v2, GStreamer/DeepStream, FastAPI, HTML/JS vanilla, Docker Compose

---

## Mapa de arquivos

| Arquivo | Mudança |
|---|---|
| `shared/orwell_shared/config.py` | `CameraConfig` ganha `ai: AIConfig`; `OrwellConfig` perde `ai` |
| `shared/tests/test_config.py` | Atualizar/adicionar testes para AI por câmera |
| `config/orwell.yaml` | Mover `ai:` global para dentro de cada câmera |
| `services/recorder/recorder/main.py` | `config.ai` → `camera.ai`; `_wire_ai_probe` recebe `camera.ai` |
| `docker-compose.yml` | `/dev/video1`, volume `/models`, healthcheck cam1 |
| `services/dashboard/dashboard/page.html` | Split view, iframes dinâmicos, clip bars sync/unlock |

---

## Task 1: Config — AIConfig por câmera

**Files:**
- Modify: `shared/orwell_shared/config.py`
- Modify: `shared/tests/test_config.py`

- [ ] **Step 1: Escrever testes que falham**

Em `shared/tests/test_config.py`, substituir `test_ai_and_preview_default_disabled` e adicionar os testes abaixo:

```python
def test_camera_ai_default_disabled():
    from orwell_shared.config import CameraConfig
    cam = CameraConfig(id="0", argus_sensor_id=0)
    assert cam.ai.enabled is False
    assert cam.ai.model_path == "/models/detector.engine"


def test_preview_default_disabled():
    cfg = OrwellConfig()
    assert cfg.preview.enabled is False


def test_camera_ai_parsed_from_yaml(tmp_path):
    from orwell_shared.config import load_config
    p = tmp_path / "orwell.yaml"
    p.write_text("""
cameras:
  - id: "0"
    argus_sensor_id: 0
    ai:
      enabled: true
      model_path: /models/cam0/detector.engine
      confidence_threshold: 0.8
  - id: "1"
    argus_sensor_id: 1
    ai:
      enabled: false
      model_path: /models/cam1/classifier.engine
""")
    cfg = load_config(p)
    assert cfg.cameras[0].ai.enabled is True
    assert cfg.cameras[0].ai.model_path == "/models/cam0/detector.engine"
    assert cfg.cameras[0].ai.confidence_threshold == 0.8
    assert cfg.cameras[1].ai.enabled is False


def test_orwell_config_has_no_global_ai():
    cfg = OrwellConfig()
    assert not hasattr(cfg, "ai")
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd /Users/urielabecontardi/Documents/tractian-orwell
python -m pytest shared/tests/test_config.py::test_camera_ai_default_disabled shared/tests/test_config.py::test_camera_ai_parsed_from_yaml shared/tests/test_config.py::test_orwell_config_has_no_global_ai -v
```

Esperado: FAIL — `CameraConfig has no field 'ai'`

- [ ] **Step 3: Implementar**

Em `shared/orwell_shared/config.py`:

1. Adicionar `ai: AIConfig = Field(default_factory=AIConfig)` em `CameraConfig`:

```python
class CameraConfig(BaseModel):
    id: str
    argus_sensor_id: int
    name: str | None = None
    ai: AIConfig = Field(default_factory=AIConfig)
```

2. Remover `ai: AIConfig = Field(default_factory=AIConfig)` de `OrwellConfig`:

```python
class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    event_buffer: EventBufferConfig = Field(default_factory=EventBufferConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
    conveyor: ConveyorConfig = Field(default_factory=ConveyorConfig)
```

- [ ] **Step 4: Rodar todos os testes de config**

```bash
python -m pytest shared/tests/test_config.py -v
```

Esperado: todos PASS. Se `test_ai_and_preview_default_disabled` ainda existir no arquivo, remova-o (foi substituído pelos dois novos).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/config.py shared/tests/test_config.py
git commit -m "refactor(config): AIConfig por câmera, remove ai global de OrwellConfig"
```

---

## Task 2: config/orwell.yaml — mover ai para câmeras

**Files:**
- Modify: `config/orwell.yaml`

- [ ] **Step 1: Atualizar o yaml**

Substituir o conteúdo de `config/orwell.yaml`. Remover o bloco `ai:` global e adicionar `ai:` em cada câmera:

```yaml
device_name: orwell-01

cameras:
  - id: "0"
    argus_sensor_id: 0
    name: front
    ai:
      enabled: false
      model_path: /models/cam0/detector.engine
      inference_fps: 8
      confidence_threshold: 0.6
      input_width: 640
      input_height: 360

  - id: "1"
    argus_sensor_id: 1
    name: rear
    ai:
      enabled: false
      model_path: /models/cam1/classifier.engine
      inference_fps: 8
      confidence_threshold: 0.6
      input_width: 640
      input_height: 360

capture:
  width: 1920
  height: 1080
  fps: 25
  codec: h264
  encoder: hw
  gop_seconds: 1.0
  segment_seconds: 4.0
  bitrate_kbps: 500

event_buffer:
  enabled: true
  buffer_seconds: 60
  bitrate_kbps: 8000
  tmpfs_dir: /dev/shm/orwell

retention:
  data_dir: /var/lib/orwell/data
  events_dir: /var/lib/orwell/events
  disk_high_watermark_pct: 85

preview:
  enabled: true
  rtsp_base_url: rtsp://preview:8554

conveyor:
  enabled: true
  host: conveyor.tractian.com
  port: 8080
  gateway_ext_id: "000011113333"
  upload_interval_s: 30
  status_interval_s: 300
```

- [ ] **Step 2: Verificar que o yaml carrega sem erro**

```bash
python -c "
from orwell_shared.config import load_config
cfg = load_config('config/orwell.yaml')
print('cameras:', [c.id for c in cfg.cameras])
print('cam0 ai.enabled:', cfg.cameras[0].ai.enabled)
print('cam1 model:', cfg.cameras[1].ai.model_path)
"
```

Esperado:
```
cameras: ['0', '1']
cam0 ai.enabled: False
cam1 model: /models/cam1/classifier.engine
```

- [ ] **Step 3: Commit**

```bash
git add config/orwell.yaml
git commit -m "config: move ai por câmera, remove bloco ai global"
```

---

## Task 3: Recorder — usar camera.ai

**Files:**
- Modify: `services/recorder/recorder/main.py`

Não há testes unitários para `main.py` (depende de GStreamer/Jetson). A validação é por leitura.

- [ ] **Step 1: Atualizar `_wire_ai_probe` — apenas trocar `config.ai.confidence_threshold` por `camera.ai.confidence_threshold`**

`_wire_ai_probe` mantém `config` na assinatura porque ainda usa `config.capture.width`, `config.event_buffer.tmpfs_dir` e `config.retention.events_dir` dentro do closure. Só a linha de threshold muda.

Localizar a linha com `config.ai.confidence_threshold` em `_wire_ai_probe` e substituir:

```python
                    if obj.confidence >= camera.ai.confidence_threshold:
```

- [ ] **Step 2: Atualizar a chamada de `_build_camera_bin` — `config.ai` → `cam.ai`**

Localizar (linha ~251) e substituir:

```python
pipelines = [
    _build_camera_bin(
        Gst, cam, config.capture,
        cam.ai, config.event_buffer, config.preview,
        config.retention.data_dir,
    )
    for cam in available
]
```

- [ ] **Step 3: Atualizar o bloco de `_wire_ai_probe` — por câmera, não global**

Localizar (linha ~260) e substituir:

```python
for cam, pipeline in zip(available, pipelines):
    if cam.ai.enabled:
        _wire_ai_probe(Gst, pipeline, cam, event_index)
```

- [ ] **Step 4: Verificar que não há mais referência a `config.ai` nas chamadas de build/wire**

```bash
grep -n "config\.ai" services/recorder/recorder/main.py
```

Esperado: nenhuma linha retornada. (referências a `config.capture`, `config.event_buffer` etc. são esperadas e corretas).

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/main.py
git commit -m "refactor(recorder): usa camera.ai por câmera em vez de config.ai global"
```

---

## Task 4: Docker — video1, models volume, healthcheck

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Adicionar `/dev/video1` nos devices do recorder**

Localizar o bloco `devices:` do serviço `recorder` e substituir:

```yaml
    devices:
      - /dev/video0:/dev/video0
      - /dev/video1:/dev/video1
```

- [ ] **Step 2: Adicionar volume de modelos no recorder**

Localizar o bloco `volumes:` do serviço `recorder` e adicionar a última linha:

```yaml
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
      - ${ORWELL_EVENTS_DIR:-./events}:/events
      - ./config:/app/config:ro
      - /tmp/argus_socket:/tmp/argus_socket
      - /dev/shm:/dev/shm
      - ${ORWELL_MODELS_DIR:-./models}:/models:ro
```

- [ ] **Step 3: Atualizar gateway healthcheck para verificar cam1**

Localizar o `healthcheck` do serviço `gateway` e substituir o `test`:

```yaml
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/healthz >/dev/null && wget -qO- http://preview:8888/cam0/index.m3u8 >/dev/null && wget -qO- http://preview:8888/cam1/index.m3u8 >/dev/null"]
```

- [ ] **Step 4: Criar diretório de modelos local (para dev)**

```bash
mkdir -p models/cam0 models/cam1
echo "# engine files gerados no Jetson com trtexec — não commitar" > models/.gitkeep
echo "models/*.engine" >> .gitignore
```

- [ ] **Step 5: Validar compose**

```bash
docker compose config --quiet && echo "compose ok"
```

Esperado: `compose ok` sem erros.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml models/.gitkeep .gitignore
git commit -m "feat(docker): /dev/video1, volume /models por câmera, healthcheck cam0+cam1"
```

---

## Task 5: Dashboard — split view

**Files:**
- Modify: `services/dashboard/dashboard/page.html`

- [ ] **Step 1: Substituir o conteúdo de `page.html`**

Substituir o arquivo inteiro pelo conteúdo abaixo:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>orwell</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: #0d0d0d; color: #b0b0b0; font-family: monospace; font-size: 13px; display: flex; flex-direction: column; }

#statusbar {
  display: flex; align-items: stretch; flex-shrink: 0;
  height: 34px; background: #111; border-bottom: 1px solid #1e1e1e;
  position: sticky; top: 0; z-index: 10;
}
.s-item { display: flex; align-items: center; padding: 0 12px; border-right: 1px solid #1e1e1e; white-space: nowrap; }
#s-host  { color: #555; }
#s-rec   { font-weight: bold; }
#s-rec.on  { color: #4caf50; }
#s-rec.off { color: #444; }
#s-disk  { color: #777; }
#s-event { color: #555; }
#s-cam   { color: #777; }
.s-gap   { flex: 1; }
nav { display: flex; }
nav a { display: flex; align-items: center; padding: 0 14px; color: #3a3a3a; text-decoration: none; border-left: 1px solid #1e1e1e; font-size: 12px; }
nav a:hover  { color: #888; background: #161616; }
nav a.active { color: #c8c8c8; border-bottom: 2px solid #4caf50; }

#preview-wrap {
  flex: 1; min-height: 0; display: flex; gap: 2px; background: #1a1a1a;
}
.cam-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.cam-label { background: #111; color: #444; font-size: 11px; padding: 3px 8px; border-bottom: 1px solid #1e1e1e; }
.cam-panel iframe { flex: 1; border: none; display: block; width: 100%; }

#clip-area { flex-shrink: 0; background: #111; border-top: 1px solid #1e1e1e; }
.clip-bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px; }
.clip-bar + .clip-bar { border-top: 1px solid #1a1a1a; }
.ts-wrap { display: flex; align-items: center; gap: 6px; }
.ts-lbl  { color: #444; }
.ts-in {
  background: #0d0d0d; border: 1px solid #252525; color: #999;
  padding: 3px 7px; font-family: monospace; font-size: 12px; width: 178px;
}
.ts-in:focus { outline: none; border-color: #4caf50; color: #c8c8c8; }
.dl-dur { color: #444; font-size: 12px; min-width: 44px; }
.btn-dl {
  padding: 4px 16px; background: #4caf50; color: #0a0a0a;
  border: none; font-family: monospace; font-size: 13px; font-weight: bold;
  cursor: pointer; text-decoration: none; display: inline-block;
}
.btn-dl:hover { background: #66bb6a; }
.btn-dl.off   { background: #1a1a1a; color: #333; pointer-events: none; }
.cam-tag { color: #555; font-size: 11px; min-width: 36px; }
#btn-sync {
  margin-left: auto; background: none; border: 1px solid #252525; color: #555;
  font-family: monospace; font-size: 12px; padding: 3px 10px; cursor: pointer;
}
#btn-sync:hover { border-color: #4caf50; color: #4caf50; }
#btn-sync.unlocked { color: #f59f00; border-color: #f59f00; }
</style>
</head>
<body>

<div id="statusbar">
  <span class="s-item" id="s-host">—</span>
  <span class="s-item" id="s-rec" class="off">○ idle</span>
  <span class="s-item" id="s-cam">—</span>
  <span class="s-item" id="s-disk">—</span>
  <span class="s-item" id="s-event">—</span>
  <span class="s-gap"></span>
  <nav>
    <a href="/" class="tab">live</a>
    <a href="/config" class="tab">config</a>
    <a href="/docs" class="tab">docs</a>
  </nav>
</div>

<div id="preview-wrap"></div>
<div id="clip-area"></div>

<script>
const CLIP_API    = "/api";
const PREVIEW_BASE = `http://${location.hostname}:8888`;

let cameras = [];
let synced  = true;
const state = {};  // { [camId]: { S: number|null, E: number|null } }

const iso   = ts => new Date(ts * 1000).toISOString().replace('.000', '');
const epoch = s  => Date.parse(s) / 1000;

function buildLayout(cams) {
  // Painéis de preview
  const wrap = document.getElementById('preview-wrap');
  wrap.innerHTML = '';
  cams.forEach(id => {
    const panel = document.createElement('div');
    panel.className = 'cam-panel';
    panel.innerHTML =
      `<div class="cam-label">cam${id}</div>` +
      `<iframe id="preview-${id}" allowfullscreen src="${PREVIEW_BASE}/cam${id}"></iframe>`;
    wrap.appendChild(panel);
  });

  // Barra sync (visível por padrão)
  const area = document.getElementById('clip-area');
  area.innerHTML = '';
  const syncBar = document.createElement('div');
  syncBar.id = 'clip-bar-sync';
  syncBar.className = 'clip-bar';
  syncBar.innerHTML =
    `<div class="ts-wrap"><span class="ts-lbl">início</span><input class="ts-in" id="sync-s" type="text" spellcheck="false"></div>` +
    `<div class="ts-wrap"><span class="ts-lbl">fim</span><input class="ts-in" id="sync-e" type="text" spellcheck="false"></div>` +
    `<span class="dl-dur" id="sync-dur"></span>` +
    cams.map(id => `<a class="btn-dl off" id="btn-dl-${id}" href="#" download>↓ cam${id}</a>`).join('') +
    `<button id="btn-sync">⛓ sync</button>`;
  area.appendChild(syncBar);

  // Barras independentes (ocultas por padrão)
  cams.forEach(id => {
    const bar = document.createElement('div');
    bar.id = `clip-bar-${id}`;
    bar.className = 'clip-bar';
    bar.style.display = 'none';
    bar.innerHTML =
      `<span class="cam-tag">cam${id}</span>` +
      `<div class="ts-wrap"><span class="ts-lbl">início</span><input class="ts-in" id="s-${id}" type="text" spellcheck="false"></div>` +
      `<div class="ts-wrap"><span class="ts-lbl">fim</span><input class="ts-in" id="e-${id}" type="text" spellcheck="false"></div>` +
      `<span class="dl-dur" id="dur-${id}"></span>` +
      `<a class="btn-dl off" id="indep-dl-${id}" href="#" download>↓ baixar</a>`;
    area.appendChild(bar);
  });

  wireEvents(cams);
}

function wireEvents(cams) {
  cams.forEach(id => { state[id] = { S: null, E: null }; });

  document.getElementById('sync-s').addEventListener('change', e => {
    const ts = epoch(e.target.value);
    if (!isNaN(ts)) { cams.forEach(id => { state[id].S = ts; }); updateSyncDl(); }
  });
  document.getElementById('sync-e').addEventListener('change', e => {
    const ts = epoch(e.target.value);
    if (!isNaN(ts)) { cams.forEach(id => { state[id].E = ts; }); updateSyncDl(); }
  });

  cams.forEach(id => {
    document.getElementById(`s-${id}`).addEventListener('change', e => {
      const ts = epoch(e.target.value); if (!isNaN(ts)) { state[id].S = ts; updateIndepDl(id); }
    });
    document.getElementById(`e-${id}`).addEventListener('change', e => {
      const ts = epoch(e.target.value); if (!isNaN(ts)) { state[id].E = ts; updateIndepDl(id); }
    });
  });

  document.getElementById('btn-sync').addEventListener('click', () => {
    synced = !synced;
    const btn = document.getElementById('btn-sync');
    btn.textContent = synced ? '⛓ sync' : '🔓 unlock';
    btn.classList.toggle('unlocked', !synced);
    document.getElementById('clip-bar-sync').style.display = synced ? '' : 'none';
    cams.forEach(id => {
      document.getElementById(`clip-bar-${id}`).style.display = synced ? 'none' : '';
    });
  });
}

function updateSyncDl() {
  const anyValid = cameras.some(id => state[id].S && state[id].E && state[id].E > state[id].S);
  const dur = document.getElementById('sync-dur');
  cameras.forEach(id => {
    const { S, E } = state[id];
    const btn = document.getElementById(`btn-dl-${id}`);
    if (!S || !E || E <= S) { btn.className = 'btn-dl off'; btn.href = '#'; dur.textContent = ''; return; }
    btn.className = 'btn-dl';
    btn.href = `${CLIP_API}/clips?camera=${id}&start=${iso(S)}&end=${iso(E)}`;
    const d = Math.round(E - S);
    dur.textContent = d >= 60 ? `${Math.floor(d/60)}m${d%60}s` : `${d}s`;
  });
}

function updateIndepDl(id) {
  const { S, E } = state[id];
  const btn = document.getElementById(`indep-dl-${id}`);
  const dur = document.getElementById(`dur-${id}`);
  if (!S || !E || E <= S) { btn.className = 'btn-dl off'; btn.href = '#'; dur.textContent = ''; return; }
  btn.className = 'btn-dl';
  btn.href = `${CLIP_API}/clips?camera=${id}&start=${iso(S)}&end=${iso(E)}`;
  const d = Math.round(E - S);
  dur.textContent = d >= 60 ? `${Math.floor(d/60)}m${d%60}s` : `${d}s`;
}

async function loadRange() {
  if (!cameras.length) return;
  try {
    const r = await fetch(`${CLIP_API}/range?camera=${cameras[0]}`);
    if (!r.ok) return;
    const d = await r.json();
    if (!d.first || !d.last) return;
    const t1 = epoch(d.last), t0 = epoch(d.first);
    const S = Math.max(t0, t1 - 60), E = t1;
    document.getElementById('sync-s').value = iso(S);
    document.getElementById('sync-e').value = iso(E);
    cameras.forEach(id => { state[id] = { S, E }; });
    updateSyncDl();
  } catch {}
}

async function init() {
  document.getElementById('s-host').textContent = location.hostname;
  document.querySelectorAll('.tab').forEach(t => {
    if (t.getAttribute('href') === location.pathname) t.classList.add('active');
  });
  try {
    const r = await fetch(`${CLIP_API}/cameras`);
    cameras = r.ok ? await r.json() : ['0', '1'];
  } catch { cameras = ['0', '1']; }
  document.getElementById('s-cam').textContent = cameras.map(id => `cam${id}`).join(' | ');
  buildLayout(cameras);
  await loadRange();
  setInterval(loadRange, 30000);
}
init();

async function pollMetrics() {
  try {
    const r = await fetch(`${CLIP_API}/metrics`); if (!r.ok) return;
    const m = await r.json();
    const el = document.getElementById('s-rec');
    el.textContent = m.recording ? '● REC' : '○ idle';
    el.className   = m.recording ? 'on' : 'off';
    const gb = n => (n / 1e9).toFixed(0);
    document.getElementById('s-disk').textContent = `${gb(m.disk_used_bytes)} GB / ${gb(m.disk_total_bytes)} GB`;
    if (m.last_event_ts) {
      const d = new Date(m.last_event_ts * 1000);
      const t = d.getUTCHours().toString().padStart(2,'0') + 'h' + d.getUTCMinutes().toString().padStart(2,'0');
      document.getElementById('s-event').textContent = `último: ${t}${m.last_event_label ? ' ' + m.last_event_label : ''}`;
    }
  } catch {}
}
pollMetrics(); setInterval(pollMetrics, 10000);
</script>
</body>
</html>
```

- [ ] **Step 2: Verificar que o HTML é válido**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
V().feed(open('services/dashboard/dashboard/page.html').read())
print('html ok')
"
```

Esperado: `html ok`

- [ ] **Step 3: Commit**

```bash
git add services/dashboard/dashboard/page.html
git commit -m "feat(dashboard): split view dual-camera com clip bars sync/unlock"
```

---

## Task 6: Deploy

- [ ] **Step 1: Push**

```bash
git push origin feat/ai-dvr-architecture
```

- [ ] **Step 2: Pull e rebuild na Jetson**

```bash
sshpass -p 'admin' ssh user@10.8.64.33 "cd orwell && git pull origin feat/ai-dvr-architecture && docker compose --profile jetson build recorder dashboard && docker compose --profile jetson up -d"
```

- [ ] **Step 3: Verificar containers healthy**

```bash
sshpass -p 'admin' ssh user@10.8.64.33 "cd orwell && docker compose ps"
```

Esperado: todos os containers `Up ... (healthy)` ou `Up`.

- [ ] **Step 4: Verificar dashboard no browser**

Abrir `http://10.8.64.33` e confirmar:
- Dois painéis de preview lado a lado
- Status bar mostra `cam0 | cam1`
- Botão `⛓ sync` presente
- Botão `↓ cam0` e `↓ cam1` ficam ativos quando há intervalo selecionado
