# Roadmap — Orwell

Faseamento pensado para **sair rápido com uma POC** e **escalar sem retrabalho**.

## Fase 1 — POC: DVR contínuo + acesso remoto  ⬅️ foco atual

**Meta:** 2 câmeras gravando continuamente em buffer circular, com recorte de intervalos
acessível remotamente.

- [x] **Provisionamento como código** (`deploy/`): scripts idempotentes `99-bootstrap.sh`
      (base + storage + Docker + NVIDIA runtime + Tailscale + NTP + driver GMSL) + `host-verify.sh`
      + runbook. Pré-requisito: JetPack flashado (passo 0). Ver `deploy/README.md`.
- [x] `recorder` (Plano 1B): captura 2 câmeras (Argus) → encode H.264 SW (GOP ~1 s) →
      `splitmuxsink` (segmentos fMP4 ~4 s) no NVMe. `nvinfer` **stub/ausente**. *(código pronto;
      runtime GStreamer a validar no Jetson)*
- [x] Índice **SQLite** + **playlist HLS** preenchidos pelo indexer a cada segmento.
- [x] **Rotação por espaço** (limpa segmentos antigos acima de ~85% do disco).
- [x] `clip-api` (FastAPI): `GET /clips?camera&start&end` → ffmpeg copy → MP4.
- [x] `broker` (Mosquitto) e `uploader` **no esqueleto** (sem modelo ainda).
- [x] `docker-compose.yml` subindo os serviços; **build local**; auto-start via `orwell.service`.
- [ ] **Validar on-device** (Jetson): pipeline GStreamer, tag DeepStream, concat fMP4, câmeras.
- [ ] Acesso via **Tailscale** (provisionado por `deploy/60-tailscale.sh`).

**Critério de pronto:** gravo 2 câmeras por horas, o disco rotaciona sozinho, e consigo baixar
um intervalo arbitrário de vídeo de fora pela Clip API via Tailscale.

## Fase 2 — IA local + eventos para a nuvem

**Meta:** detectar eventos no vídeo ao vivo e enviar ~10 s de cada evento para a nuvem.

- [ ] Treinar/obter modelo de detecção; converter para **engine TensorRT**.
- [ ] Ligar `nvinfer` (+ `nvtracker` se necessário) no pipeline do `recorder`.
- [ ] Publicar eventos em **MQTT** (`orwell/events`).
- [ ] `uploader`: assinar eventos → obter clipe de ~10 s (Smart Record ou extração dos segmentos)
      → enviar via backend de storage.
- [ ] Backend **S3** funcional; interface plugável validada.
- [ ] Validar **orçamento de CPU** (encode SW + inferência) on-device; tunar perfil.

**Critério de pronto:** um evento real gera automaticamente um clipe de ~10 s na nuvem, sem
derrubar a gravação contínua.

## Fase 3 — Escala e frota

**Meta:** operar muitos devices com atualização e gestão centralizadas.

- [ ] Migrar de docker-compose para **K3s** (single-node primeiro) + **Helm chart**.
- [ ] Introduzir **registry** de imagens (GHCR/Harbor); CI buildando arm64.
- [ ] **Rancher + Fleet (GitOps)** para deploy/atualização da frota.
- [ ] NVIDIA device plugin + pod `recorder` privilegiado (câmera/GPU no K8s).
- [ ] Avaliar módulo **Orin NX** (NVENC/H.265) onde encode/IA apertar.
- [ ] Avaliar **Yocto / Rancher Elemental** para imagem de SO + OTA de host/driver.
- [ ] Telemetria/observabilidade de frota.

## Itens deliberadamente adiados (YAGNI por enquanto)

- Profundidade/3D (ZED SDK pesado) — só se um caso de uso exigir.
- H.265 — depende de NVENC (Orin NX).
- ZED Hub (nuvem da Stereolabs) — preferimos Tailscale + nuvem própria (sem lock-in).
- Áudio, multi-tenant, autenticação avançada da API — quando houver necessidade real.
