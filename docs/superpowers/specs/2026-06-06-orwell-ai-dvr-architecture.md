# Orwell — Arquitetura DVR + IA Industrial

**Data:** 2026-06-06
**Status:** Aprovado
**Contexto:** Jetson Orin NX · 256 GB NVMe · 2× ZED X One S (GMSL2)

---

## Objetivo

Gravar vídeo continuamente com máxima retenção, rodar IA em tempo real para detecção de falhas industriais (fumaça, anomalias mecânicas) e enviar clips de alta qualidade para a nuvem quando um evento é detectado.

---

## Restrições

- Hardware fixo: Jetson Orin NX com NVENC/NVDEC/GPU como blocos independentes.
- 256 GB NVMe como único storage persistente.
- Câmeras GMSL2 — driver no host, captura via Argus.
- Tudo em Python + DeepStream/GStreamer.
- Upload para nuvem: protocolo próprio a definir (Fase 2). Esta spec define apenas a interface.

---

## Decisão de Arquitetura

Pipeline GStreamer com **três branches (`tee`)** saindo do mesmo fluxo de frames:

```
Camera (Argus)
    └─→ nvarguscamerasrc → nvvideoconvert → tee
                                              ├─ [A] DVR Stream    (arquivo, longa retenção)
                                              ├─ [B] AI Stream     (inferência em tempo real)
                                              └─ [C] Event Buffer  (alta qualidade, RAM)
```

Os três blocos de hardware operam em paralelo independente:
- **NVENC** → encode branch A (DVR) + encode branch C (event buffer)
- **GPU / DLA** → TensorRT branch B (inferência)
- **NVDEC** → não utilizado nesta fase (sem recompressão)

**Não há recompressor.** O DVR grava direto em bitrate de arquivo desde o início, eliminando um serviço e aumentando a retenção.

---

## Branches do Pipeline

### Branch A — DVR (storage longo)

| Parâmetro | Valor |
|---|---|
| Resolução | 1920×1080 |
| FPS | 25 |
| Codec | H.265 (NVENC HW) |
| Bitrate | 0,5 Mbps por câmera |
| Formato | fMP4/CMAF (`.m4s`) |
| Duração segmento | 4 s |
| Destino | `/var/lib/orwell/data/{cam}/{AAAA}/{MM}/{DD}/{HH}/seg-<epoch>.m4s` |

Qualidade suficiente para identificar que um evento ocorreu e localizar no tempo. Detalhes do evento são capturados pelo Branch C.

Cada segmento fechado é registrado na tabela `segments` do SQLite com `(camera_id, t_inicio, t_fim, path, size)`.

### Branch B — IA (inferência em tempo real)

| Parâmetro | Valor |
|---|---|
| Resolução | 640×360 |
| FPS efetivo | ~8 fps (skip de frames) |
| Processamento | `nvvideoconvert` → `nvinfer` (TensorRT) |
| Modelos suportados | detecção de objetos (YOLO-family), anomalia |
| Output | evento com `{camera_id, timestamp, label, confidence, bbox}` |

Quando `confidence >= threshold`, dispara o handler de evento que:
1. Persiste o evento na tabela `events` do SQLite.
2. Aciona o flush do branch C.
3. Notifica a clip-api via callback interno.

### Branch C — Event Buffer (clip de alta qualidade)

| Parâmetro | Valor |
|---|---|
| Resolução | 1920×1080 |
| FPS | 25 |
| Codec | H.265 (NVENC HW) |
| Bitrate | 8 Mbps por câmera |
| Destino | `tmpfs` (`/dev/shm/orwell/`) |
| Tamanho do buffer | configurável (default: 60 s) |
| RAM consumida | ~120 MB (60 s, 2 câmeras a 8 Mbps) |

Implementado como **arquivo circular em tmpfs**: escreve em `cam0-buf.m4s` e `cam1-buf.m4s` com rotação via `splitmuxsink` de tamanho fixo (metade do `buffer_seconds`). Em regime, há sempre 60–120 s de histórico disponíveis.

Ao detectar evento, copia os arquivos para `/var/lib/orwell/events/<event_id>/` antes do próximo ciclo sobrescrever. O clip inclui aproximadamente `buffer_seconds / 2` de pré-evento.

---

## Storage

### Única camada (arquivo desde o início)

| Parâmetro | Valor |
|---|---|
| Bitrate total (2 cams) | 1 Mbps = 0,45 GB/h |
| Usável (256 GB × 85%) | 217 GB |
| **Retenção estimada** | **~20 dias** |

### Watermark e Rotação

- `disk_high_watermark_pct: 85` — ao ultrapassar, deleta segmentos mais antigos.
- Rotação: segmentos DVR mais antigos primeiro. Clips de evento **nunca** são rotacionados automaticamente — apenas pelo operador.

### Event Clips

- Armazenados em `/var/lib/orwell/events/<event_id>/` fora da rotação automática.
- Ocupam `buffer_seconds × 8 Mbps × 2 cams / 8` ≈ 120 MB por evento.
- Após upload (Fase 2), podem ser deletados pelo operador ou automaticamente.

---

## Serviços

### `recorder` (existente — expandido)

**Responsabilidade:** pipeline DeepStream com branches A, B, C; indexação de segmentos; detecção de eventos; flush do event buffer.

**Mudanças vs spec anterior:**
- Adiciona branches B e C ao pipeline GStreamer.
- Adiciona tabela `events` ao índice SQLite.
- Altera config: fps 25, bitrate 0,5 Mbps, watermark 85%.

**Interface de saída:**
- Segmentos em `/var/lib/orwell/data/`
- Event clips em `/var/lib/orwell/events/<event_id>/`
- SQLite em `/var/lib/orwell/index.db`

### `clip-api` (existente — expandido)

**Endpoints adicionados:**
- `GET /events?camera=&start=&end=` → lista eventos detectados pela IA.
- `GET /events/{event_id}/clip` → retorna o clip de alta qualidade do evento.

**Endpoints existentes sem mudança:**
- `GET /clips?camera=&start=&end=` → MP4 por cópia de stream do DVR.
- `GET /cameras`, `GET /healthz`, `GET /segments`.

### `uploader` (Fase 2 — interface apenas)

**Interface definida (não implementar agora):**
```python
class UploaderBackend(Protocol):
    async def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        """Retorna URI do clip na nuvem."""
```

O `recorder` chama essa interface quando disponível via injeção de dependência. Se não configurado, persiste localmente e loga.

---

## Esquema SQLite

### Tabela `segments` (existente — sem alteração estrutural)

```sql
CREATE TABLE segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id  TEXT NOT NULL,
    t_inicio   REAL NOT NULL,
    t_fim      REAL NOT NULL,
    path       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX segments_camera_tempo ON segments(camera_id, t_inicio);
```

### Tabela `events` (nova)

```sql
CREATE TABLE events (
    id          TEXT PRIMARY KEY,   -- UUID
    camera_id   TEXT NOT NULL,
    t_evento    REAL NOT NULL,       -- epoch UTC
    label       TEXT NOT NULL,       -- 'smoke', 'mechanical_fault', etc.
    confidence  REAL NOT NULL,
    bbox_json   TEXT,                -- JSON: {x,y,w,h} normalizado (0–1)
    clip_path   TEXT,                -- path do clip de alta qualidade (NULL até flush)
    uploaded_at REAL,                -- epoch UTC, NULL até upload
    created_at  REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX events_camera_tempo ON events(camera_id, t_evento);
```

---

## Configuração (`orwell.yaml` — estado final)

```yaml
device_name: orwell-01

cameras:
  - id: "0"
    argus_sensor_id: 0
    name: front
  - id: "1"
    argus_sensor_id: 1
    name: rear

capture:
  width: 1920
  height: 1080
  fps: 25                  # padrão comercial (era 60)
  codec: h265
  encoder: hw              # NVENC
  gop_seconds: 1.0
  segment_seconds: 4.0
  bitrate_kbps: 500        # arquivo desde o início (era 8000)

ai:
  enabled: false           # true quando modelo TRT disponível
  inference_fps: 8
  confidence_threshold: 0.6
  input_width: 640
  input_height: 360
  model_path: /models/detector.engine

event_buffer:
  enabled: true
  buffer_seconds: 60
  bitrate_kbps: 8000       # alta qualidade para o clip de evento
  tmpfs_dir: /dev/shm/orwell

retention:
  data_dir: /var/lib/orwell/data
  events_dir: /var/lib/orwell/events
  disk_high_watermark_pct: 85   # era 50
```

---

## Diagrama de Fluxo de Evento

```
Camera
  │
  ├─[A]──→ encode 0,5 Mbps ──→ NVMe seg-*.m4s ──→ SQLite segments
  │                                (rotação por disco)
  │
  ├─[B]──→ scale 640×360 ──→ TensorRT ──→ confidence >= threshold?
  │                                              │ SIM
  │                                              ▼
  │                                        flush event buffer
  │                                              │
  └─[C]──→ encode 8 Mbps ──→ tmpfs (60s) ──→ copy → /events/<id>/
                                                      │
                                               SQLite events
                                                      │
                                               clip-api GET /events/{id}/clip
                                                      │
                                               uploader (Fase 2) ──→ nuvem
```

---

## Comparação: antes vs depois

| | Config original | **Esta spec** |
|---|---|---|
| FPS | 60 | **25** |
| Bitrate DVR | 8 Mbps/cam | **0,5 Mbps/cam** |
| Watermark | 50% | **85%** |
| Retenção | ~18 horas | **~20 dias** |
| IA | não | **sim (branch B)** |
| Clip de evento | não | **sim (branch C, 8 Mbps)** |
| Serviços extras | — | **nenhum** |

---

## Fora do Escopo desta Spec

- Protocolo de upload para nuvem (Fase 2).
- Treinamento/fine-tuning de modelos.
- Mais de 2 câmeras.
- Streaming ao vivo (MediaMTX — já previsto separadamente).
- Dashboard UI de eventos.
