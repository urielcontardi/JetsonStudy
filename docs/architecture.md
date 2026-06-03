# Arquitetura — Orwell

Documento de arquitetura detalhada. Para o "porquê" de cada decisão, ver `docs/decisions/`.
Para definições de termos, ver [`glossary.md`](glossary.md).

## 1. Princípios

1. **Capturar uma vez, consumir muitos.** O vídeo é capturado e codificado uma única vez; vários
   consumidores (disco, IA, recorte) se penduram no mesmo fluxo sem se atrapalhar.
2. **Performance na camada nativa.** Python só orquestra e trata eventos. Pixels nunca sobem para
   o Python.
3. **Fronteiras de serviço claras.** Cada serviço tem uma responsabilidade e um contrato. Pode ser
   entendido, testado e atualizado isolado.
4. **Formatos e protocolos abertos.** MP4 padrão, SQLite, HTTP — sem lock-in de fornecedor.
5. **12-factor.** Config externa, logs no stdout, sem estado escondido → migração para K3s indolor.

## 2. Camadas

```
┌─────────────────────────────────────────────────────────────────────┐
│ HOST (Jetson Orin NX) — fora do Docker                              │
│   JetPack/L4T · Driver GMSL Stereolabs (kernel) · Tailscale · NTP   │
├─────────────────────────────────────────────────────────────────────┤
│ CONTAINERS (docker-compose → futuramente K3s)                       │
│                                                                     │
│   recorder (DeepStream/pyds)   clip-api (FastAPI)                   │
│                                                                     │
│   Volume compartilhado: NVMe (segmentos + índice SQLite)            │
└─────────────────────────────────────────────────────────────────────┘
```

O **driver GMSL é kernel** e fica **no host**; os containers acessam a câmera via
`/dev/video*` + socket do Argus, com o **NVIDIA Container Runtime**.

## 3. O pipeline de mídia (`recorder`)

Aplicação DeepStream (pyds). Esqueleto conceitual do pipeline (por câmera, batched):

```
nvarguscamerasrc(cam0) ┐
                       ├─ nvstreammux (batch=2) ─ nvinfer (TensorRT)* ─ nvtracker* ─ tee ┐
nvarguscamerasrc(cam1) ┘                                                                  │
                                                                                          ├─ [A] encode ─ splitmuxsink ─→ NVMe (segmentos)
                                                                                          └─ [B] preview (RTSP/WebRTC, dev only)
* nvinfer/nvtracker: stub/desligado na Fase 1; modelo real na Fase 2.
```

- **[A] Gravação contínua:** encoder **configurável** (NVENC HW na Orin NX: `nvv4l2h265enc`;
  `x264enc` SW como fallback na Nano — ver `recorder/pipeline.py` e
  [ADR-0014](decisions/0014-encoder-configuravel-hw-sw.md)), **key-int ~1 s** → um **`tee`** após o
  parser distribui o stream codificado para o `splitmuxsink` (muxer fragmentado) gerando
  **segmentos fMP4/CMAF de ~4s** (configurável) + **playlist `.m3u8`** por câmera. A seção de
  inferência (`inference_stage`) fica cabeada porém **desligada** (`ai.enabled: false`) até a
  Fase 2. Cada segmento fechado é registrado no índice. Ver
  [ADR-0006](decisions/0006-mp4-padrao-splitmuxsink.md).
- **[B] Preview (dev):** branch RTSP/WebRTC opcional via MediaMTX (`preview.enabled: true`).
  Off por padrão; não afeta a gravação.

## 4. Armazenamento e índice

- **Segmentos:** **fMP4/CMAF de ~4s** (configurável) no NVMe + **playlist `.m3u8`** por câmera.
  Layout hierárquico para evitar diretórios gigantes:
  `data/{camera}/{AAAA}/{MM}/{DD}/{HH}/seg-<epoch>.m4s` (+ `init.mp4` por câmera/parâmetros).
- **GOP ~1 s:** keyframe a cada ~segundo permite **corte por cópia de stream** (sem recomprimir)
  com granularidade de ~1 s — barato em CPU.
- **Índice (SQLite):** tabela `segments(camera_id, t_inicio, t_fim, path, size, created_at)`.
  - Escrito pelo `recorder` ao fechar cada segmento.
  - Lido pela `clip-api` para mapear `[start,end]` → conjunto de segmentos.
  - A playlist `.m3u8` é uma redundância útil para players (streaming via Tailscale).
- **Rotação por espaço:** rotina verifica uso do disco; acima de ~85% apaga segmentos mais antigos
  (e remove do índice). Retenção = "o máximo que couber".
- **Clipes:** `ffmpeg -c copy` concatena os segmentos que cobrem a janela →
  **MP4 *faststart* standalone** (fácil de tocar/baixar).

## 5. Plano de controle

### 5.1 `clip-api` (FastAPI)
- `GET /clips?camera={id}&start={iso8601}&end={iso8601}`
  1. Consulta o índice → segmentos que cobrem a janela.
  2. `ffmpeg -c copy` concatena/recorta nas bordas de keyframe → MP4 temporário.
  3. Responde `video/mp4` (stream/download). `404` se fora da janela retida.
- `GET /healthz`, `GET /cameras`, `GET /segments?...` (introspecção/debug).
- Exposta na interface do **Tailscale**.

## 6. Configuração (12-factor)

`config/` (montado nos containers) define identidade/limites do device:
- câmeras (IDs, modos de sensor), perfil de captura (res/fps/codec/GOP/segmento),
- retenção (limite de disco), caminhos no NVMe,
- nome/identidade do device (para Tailscale e, futuramente, frota).

## 7. Empacotamento e deploy

- **POC:** `docker-compose.yml` com `clip-api` + `recorder` (perfil `jetson`) + `preview` (perfil
  `dev`); imagens **buildadas localmente** no Jetson. Base do `recorder`: imagem L4T/DeepStream da
  NVIDIA (`nvcr.io`). NVIDIA Container Runtime + device mounts para a câmera.
- **Frota (futuro):** Helm chart equivalente; **K3s**; **Rancher Fleet** (GitOps); **registry**
  de imagens. Ver [`operations.md`](operations.md).

## 8. Observabilidade (mínimo viável)

- Logs estruturados no **stdout** de cada serviço (coletáveis por journald/loki depois).
- `clip-api /healthz` e métricas básicas (segmentos gravados, uso de disco, FPS real, drops).
- Telemetria de frota fica para a fase Rancher.
