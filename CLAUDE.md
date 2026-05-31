# CLAUDE.md — Projeto Orwell

> Contexto de projeto para o Claude Code. Carregado automaticamente a cada sessão.
> Mantenha curto e atual; detalhes ficam em `docs/`.

## O que é

**Orwell** é um **DVR de borda com IA**: grava câmeras continuamente em buffer circular numa
**NVIDIA Jetson Orin Nano**, permite **recortar/baixar intervalos** de vídeo remotamente e
(em fase seguinte) roda **IA local** que dispara o **envio de ~10 s de vídeo** de cada evento
para a nuvem. Acesso remoto via **Tailscale**; futura gestão de frota via **Rancher**.

- **Hardware:** Jetson Orin Nano + carrier/ZED Box (GMSL2) + **2× ZED X One S** (monoculares) + NVMe.
- **Estado:** projeto novo. Design aprovado em `docs/superpowers/specs/2026-05-31-orwell-dvr-borda-design.md`.

## Stack (decidida)

- **Tudo em Python.**
- **Plano de mídia/IA:** **DeepStream** (NVIDIA) via `pyds`. Captura por **Argus**
  (`nvarguscamerasrc`), inferência por **TensorRT**.
- **Plano de controle:** **FastAPI** (Clip API) + worker Python (Uploader).
- **Da Stereolabs usamos APENAS o driver GMSL** (kernel, no host). **Nada de ZED SDK pesado**
  (só entraria se um dia precisarmos de profundidade/3D).
- **Containers** orquestrados por **docker-compose** (POC) → **K3s + Rancher Fleet** (frota).
- **MQTT** (Mosquitto) como barramento de eventos. **SQLite** como índice de segmentos.

## Restrições que NÃO podem ser esquecidas

- ⚠️ **Orin Nano NÃO tem NVENC** (encoder de hardware). **Encode é por software (CPU, H.264).**
  H.265 software em tempo real para 2 streams é inviável. Perfil POC reduzido: **1080p@15fps, 2 cams**.
- ⚠️ **Câmeras ZED X One S são GMSL2, não USB.** Dependem do **driver GMSL no host**, casado com a
  versão do **JetPack/L4T**. O driver **não** é conteinerizável (é kernel).
- ⚠️ **Performance vem da camada nativa** (GStreamer/DeepStream/TensorRT). Python só orquestra e
  trata eventos. **Nunca** processar cada pixel de cada frame em Python (numpy por frame = mata a
  performance).
- **Caminho de escala:** módulo **Orin NX** (pino-compatível, tem NVENC) destrava H.265 por HW.

## Componentes (alvo)

| Serviço | Papel | Tech |
|---|---|---|
| `recorder` | Captura + encode + gravação contínua + Smart Record + eventos | DeepStream/pyds |
| `clip-api` | `GET /clips?camera&start&end` → MP4 (ffmpeg copy) | FastAPI |
| `uploader` | Evento MQTT → recorta 10 s → nuvem (backend plugável, S3 default) | Python worker |
| `broker` | Barramento de eventos | Mosquitto/MQTT |

Gravação: segmentos **fMP4/CMAF de ~4 s** (configurável) + **playlist HLS** por câmera, **GOP ~1 s**,
rotação por espaço em disco. Clipes por cópia de stream (`ffmpeg -c copy`). Ver ADR-0006.

## Estrutura

```
config/      services/{recorder,clip-api,uploader}/   shared/   models/   deploy/   docs/   tests/
```

## Convenções

- **12-factor:** config por env/arquivo montado, logs no stdout, sem caminhos hardcoded
  (facilita migração compose → Helm/K3s).
- Recortes de vídeo por **cópia de stream** (sem recomprimir) sempre que possível.
- Timestamps em **UTC**; NTP no host.
- Documentar toda decisão arquitetural relevante como **ADR** em `docs/decisions/`.
- **Provisionamento como código (regra de ouro):** **nada** toca o host de forma manual/ad-hoc.
  Todo comando que instala/modifica o ambiente Linux (apt, Docker, drivers, mounts, NTP,
  Tailscale…) **deve** virar um script idempotente em `deploy/`. Esses scripts **são** o registro
  reproduzível ("placa zerada → bootstrap → no ar"). Se precisou rodar algo no host, ou adicione
  ao script certo, ou registre em `deploy/provisioning-log.md`. Pré-requisito fora dos scripts:
  flashar o JetPack/L4T (SDK Manager). Ver [ADR-0013](docs/decisions/0013-provisionamento-como-codigo.md).

## Mapa de documentação

- `docs/superpowers/specs/2026-05-31-orwell-dvr-borda-design.md` — **spec/design** (fonte de verdade).
- `docs/architecture.md` — arquitetura detalhada, interfaces, fluxos.
- `docs/glossary.md` — glossário didático (GStreamer, DeepStream, TensorRT, Argus, Smart Record, MQTT, Tailscale, K3s, Rancher, registry…).
- `docs/hardware.md` — hardware, ZED X One S, driver GMSL, Orin Nano vs Orin NX.
- `docs/operations.md` — acesso remoto (Tailscale), atualização (compose → Rancher), provisionamento.
- `deploy/` — **provisionamento como código**: scripts idempotentes (`99-bootstrap.sh`) + runbook
  (`deploy/README.md`) para preparar uma placa zerada (JetPack já flashado).
- `docs/roadmap.md` — faseamento POC → escala.
- `docs/decisions/` — ADRs (decisões + porquês).
