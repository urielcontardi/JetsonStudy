# Orwell

**DVR de borda com IA** para NVIDIA Jetson Orin Nano + câmeras Stereolabs ZED X One S.

Orwell grava câmeras continuamente em um **buffer circular** (estilo DVR), permite **recortar e
baixar intervalos** de vídeo remotamente (via **Tailscale**) e, em fase seguinte, roda **IA local**
que dispara o **envio de ~10 s de vídeo** de cada evento detectado para a nuvem.

> 📐 Projeto em fase de design. Veja a especificação completa em
> [`docs/superpowers/specs/2026-05-31-orwell-dvr-borda-design.md`](docs/superpowers/specs/2026-05-31-orwell-dvr-borda-design.md).

## Visão geral

```
ZED X One S ×2  →  [recorder: DeepStream]  →  NVMe (segmentos + índice SQLite)
   (GMSL2)            │  encode H.264 (SW)        │
                      │  Smart Record             ├─→ [clip-api: FastAPI] ──(Tailscale)──→ você
                      └─→ evento (MQTT) ─→ [uploader] ─→ ☁️ nuvem (S3 plugável)
```

- **Plataforma:** Jetson Orin Nano (⚠️ sem NVENC → encode por software), JetPack + driver GMSL Stereolabs.
- **Stack:** tudo em **Python** — DeepStream (`pyds`) no plano de mídia/IA; FastAPI no plano de controle.
- **Deploy:** docker-compose (POC) → K3s + Rancher Fleet (frota).

## Componentes

| Serviço | **Função** |
|---|---|
| `recorder` | Captura, encode, gravação contínua, Smart Record, eventos |
| `clip-api` | `GET /clips?camera&start&end` → MP4 |
| `uploader` | Evento → recorta ~10 s → nuvem |
| `broker` | MQTT (Mosquitto) |

## Status / Roadmap

- [ ] **Fase 1 (POC):** gravação contínua 2 câmeras + rotação + índice + Clip API via Tailscale.
- [ ] **Fase 2:** modelo TensorRT real → eventos → upload de clipes.
- [ ] **Fase 3:** K3s + Rancher Fleet, registry, avaliar Orin NX / Yocto.

Detalhes em [`docs/roadmap.md`](docs/roadmap.md).

## Documentação

- [Arquitetura](docs/architecture.md) · [Glossário](docs/glossary.md) ·
  [Hardware](docs/hardware.md) · [Operação](docs/operations.md) ·
  [Decisões (ADRs)](docs/decisions/)
