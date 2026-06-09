# Dual-Camera Support — Design

**Data:** 2026-06-09
**Status:** Aprovado

## Contexto

O Orwell já grava e indexa múltiplas câmeras no recorder e na clip-api. O que faltava era:
- Config de IA por câmera (modelo, threshold, etc.)
- Suporte ao segundo device GMSL no Docker
- Dashboard com split view e controles sincronizados

## Decisões

| Decisão | Escolha | Motivo |
|---|---|---|
| Estrutura de config de IA | Embutida em cada câmera | Câmera autocontida, sem herança implícita |
| Containers de inference | Único recorder, modelos como volumes | Sem overhead GPU duplo; DeepStream isolou por pipeline |
| Dashboard | Split view 50/50 fixo | Supervisão simultânea das duas câmeras |
| Controles de clipe | Sync por padrão, desacoplável | Correlacionar eventos é o caso principal |

---

## 1. Config (`config/orwell.yaml` + `shared/orwell_shared/config.py`)

### orwell.yaml

O bloco `ai:` global é **removido**. Cada entrada em `cameras:` ganha um sub-bloco `ai:` opcional:

```yaml
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
      confidence_threshold: 0.7
      input_width: 640
      input_height: 360
```

### config.py

- `AIConfig` mantém os mesmos campos.
- `CameraConfig` ganha campo `ai: AIConfig = AIConfig()` (default: `enabled=False`).
- `OrwellConfig` perde o campo `ai: AIConfig` de nível raiz.
- Testes existentes de `AIConfig` migram para dentro de `CameraConfig`.

---

## 2. Docker (`docker-compose.yml`)

### Devices do recorder

```yaml
devices:
  - /dev/video0:/dev/video0
  - /dev/video1:/dev/video1
```

### Volume de modelos

```yaml
recorder:
  volumes:
    - ...existentes...
    - ${ORWELL_MODELS_DIR:-./models}:/models:ro
```

Estrutura esperada em disco:
```
models/
  cam0/
    detector.engine        # gerado com trtexec no Jetson
  cam1/
    classifier.engine
```

O arquivo `.engine` é gerado uma vez no Jetson (amarrado à GPU/JetPack) e nunca entra no repositório.

### Gateway healthcheck

```yaml
test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/healthz >/dev/null && wget -qO- http://preview:8888/cam0/index.m3u8 >/dev/null && wget -qO- http://preview:8888/cam1/index.m3u8 >/dev/null"]
```

---

## 3. Recorder (`services/recorder/`)

### main.py

- Substituir `config.ai` por `camera.ai` na chamada de `_build_camera_bin`.
- Remover referência ao campo `config.ai` global (não existe mais).

### pipeline.py

- Nenhuma mudança de assinatura — `ai_scale_chain`, `inference_stage` e `_wire_ai_probe` já recebem `AIConfig` por parâmetro.
- Cada pipeline de câmera instancia seu próprio `nvinfer` com o `model_path` do `camera.ai`.

---

## 4. Dashboard (`services/dashboard/dashboard/page.html`)

### Layout

```
┌──────────────────────────────────────────────────────┐
│ status bar              [⛓ sync]  [live][config][docs] │
├─────────────────────────┬────────────────────────────┤
│  cam0 — front           │  cam1 — rear               │
│  [iframe :8888/cam0]    │  [iframe :8888/cam1]       │
│                         │                            │
├─────────────────────────┴────────────────────────────┤
│  início [___] fim [___]  Δt  ↓ baixar (cam0 + cam1)  │  ← modo sync
│  ou                                                  │
│  [cam0: início fim ↓]  |  [cam1: início fim ↓]       │  ← modo unlock
└──────────────────────────────────────────────────────┘
```

### Comportamento

- **Modo sync (padrão):** barra de clipe única. Botão "↓ baixar clipe" dispara dois downloads sequenciais (`/api/clips?camera=0&...` e `/api/clips?camera=1&...`) com o mesmo intervalo.
- **Modo unlock:** botão `⛓` vira `🔓`. Cada painel exibe sua própria barra de clipe; downloads independentes.
- Status bar: o item `s-cam` exibe os IDs das câmeras (`cam0 | cam1`) buscados de `GET /api/cameras` na inicialização da página. `GET /api/cameras` retorna os IDs das câmeras que têm segmentos gravados no SQLite — sem nomes. Suficiente para o MVP.
- `const CAM = '0'` e `${PREVIEW_BASE}/cam0` hardcoded são substituídos por iteração sobre o array de câmeras retornado pela API.

### config.html

- Mesma busca a `/api/cameras` para popular o `s-cam` na status bar.
- Nenhuma mudança funcional além disso.

---

## 5. Fluxo de dados completo

```
nvarguscamerasrc(sensor=0) ─→ encode ─→ DVR(cam0/) ─→ shmsink ─→ rtspclientsink ─→ MediaMTX/cam0
                            └→ nvinfer(cam0.engine) ─→ events/(cam0)

nvarguscamerasrc(sensor=1) ─→ encode ─→ DVR(cam1/) ─→ shmsink ─→ rtspclientsink ─→ MediaMTX/cam1
                            └→ nvinfer(cam1.engine) ─→ events/(cam1)

uploader ─→ lê EventIndex ─→ VSTP ─→ Conveyor (cam0 e cam1 como eventos distintos)
```

---

## Fora do escopo desta iteração

- UI de gerenciamento de modelos (upload de `.engine` via dashboard)
- Config de `inference_fps` e `confidence_threshold` ajustável em runtime via config page
- Gravação de metadados de detecção por câmera no SQLite
