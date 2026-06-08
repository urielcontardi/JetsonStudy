# Hardware e plataforma — Orwell

## 1. Bill of materials (POC)

| Componente | Modelo | Papel |
|---|---|---|
| Compute | NVIDIA **Jetson Orin NX** (primário) | Captura, **encode por HW (NVENC)**, IA |
| Compute (fallback) | NVIDIA Jetson Orin Nano (pino-compatível) | Mesmo papel, mas **encode por software** (sem NVENC) |
| Carrier | Mini Carrier / **ZED Box** (Stereolabs) + **ZED Link** GMSL2 | Conecta as câmeras GMSL2 |
| Câmeras | **2× Stereolabs ZED X One S** | Captura de vídeo (monocular, global shutter) |
| Storage | **NVMe** (M.2) | Buffer circular de vídeo + índice |
| Rede | Ethernet/Wi-Fi/4G + **Tailscale** | Acesso remoto |

## 2. Câmeras ZED X One S — fatos importantes

- **Monoculares** (lente única, global shutter). **Sozinhas não geram profundidade.** Profundidade
  só pareando **duas** unidades como rig estéreo (via ZED SDK) — fora do escopo atual.
- Sensor nativo até **1920×1200** (1200p). POC usa **1080p@15fps** (perfil reduzido, tunável).
- Interface **GMSL2** (coaxial), **não USB**. Precisam de placa de captura **ZED Link** + driver.
- Para nosso uso (RGB + IA 2D), são lidas pelo **Argus (NVIDIA)**; o **ZED SDK pesado não é
  necessário**. Ver [ADR-0002](decisions/0002-stereolabs-so-driver-gmsl.md).

## 3. Encode: NVENC na Orin NX (HW); software como fallback (Nano)

O **alvo primário é a Orin NX, que possui NVENC** (encoder de hardware). Implicações:

- **Encode por hardware** via `nvv4l2h265enc`/`nvv4l2h264enc` — **H.265 viável e recomendado**
  (arquivos ~2× menores → mais dias de retenção); os frames seguem em **NVMM** (GPU), sem a cópia
  NVMM→CPU que o caminho por software exige.
- **CPU livre** para a inferência (Fase 2) — não há mais o aperto de encode SW disputando CPU.
- **Encoder selecionável por config** (`capture.codec` + `capture.encoder`) — ver
  [ADR-0014](decisions/0014-encoder-configuravel-hw-sw.md).

### Fallback: Orin Nano (sem NVENC)
A NVIDIA confirma ("Software Encode in Orin Nano") que o **Orin Nano não possui NVENC** — só
**NVDEC** (decode). Quando rodando na Nano:
- **Encode por software** via `libx264`/`x264enc` (`encoder: sw`, `codec: h264`).
- Benchmark de referência (RidgeRun, 1080p, 10 Mbps): `ultrafast` ~71 fps, `medium` ~24 fps em um
  único stream — **2 streams** consomem boa parte da CPU, exigindo perfil reduzido (ex. 1080p@15).
- **H.265 por software em tempo real é inviável** → na Nano, apenas H.264 software.

### Mitigações (ambos os caminhos)
- **Recorte por cópia de stream** (sem recomprimir) → não gasta CPU para gerar clipes.
- Perfil **configurável** por device (res/fps/codec/encoder/bitrate) — validar on-device.

## 4. Caminho de escala: módulo Orin NX

- O **Orin NX** é **pino-compatível** com o carrier do Orin Nano (o devkit do Orin Nano aceita o
  módulo Orin NX).
- O Orin NX **possui NVENC** → destrava **H.265 por hardware**, encode com CPU livre e mais câmeras
  por device.
- **Trocar o módulo** é o upgrade natural quando o encode/IA apertar — **sem reprojetar a placa**.
  Ver [ADR-0012](decisions/0012-orin-nx-caminho-de-escala.md).

## 5. Driver GMSL — instalação (host)

- Baixar o `.deb` correto na página de drivers da Stereolabs, **casando**: placa (ZED Box / ZED
  Link Duo/Mono), deserializer e **versão do L4T** (ex.: L4T 36.x ↔ JetPack 6.x).
- Exemplo de pacote: `stereolabs-zedlink-duo_<ver>-LI-MAX96712-all-L4T36.4.0_arm64.deb`.
- Instalar com `dpkg -i ...`; se faltar dependência, instalar `libqt5core5a`. **Reiniciar** após.
- **É kernel → fica no host**, não no container. Fixar a versão usada em `deploy/`.
- Detalhes de provisionamento em [`operations.md`](operations.md).

## 6. Storage e retenção

- Vídeo gravado e índice ficam no **NVMe**.
- **Retenção por espaço:** quando o uso passa de ~85%, apaga segmentos mais antigos.
- **Estimativa de ordem de grandeza** (H.264 SW, 1080p@15fps, ~6–8 Mbps por câmera, 2 câmeras):
  ~5–7 GB/h no total → ~120–170 GB/dia. Em NVMe de 1 TB ≈ vários dias; 2 TB ≈ ~1–2 semanas.
  **Validar empíricamente** (bitrate real depende de preset e cena).

## 7. Ambiente validado (device em uso — 2026-06-08)

| Item | Valor |
|---|---|
| Hostname (Tailscale) | `omnitrac-4cbb47c1331a` |
| IP Tailscale | `100.109.171.54` |
| MAC Ethernet (`enP8p1s0`) | `4c:bb:47:c1:33:1a` |
| sensor_ext_id (Conveyor) | `4cbb47c1331a` |
| OS | Ubuntu 22.04.5 LTS (Jammy Jellyfish) |
| Kernel | `5.15.148-tegra` |
| JetPack / L4T | **R36.4.7** |
| Arquitetura | `aarch64` |

## 8. Rede e tempo

- **Tailscale** no host para acesso remoto (ver [`operations.md`](operations.md)).
- **NTP** habilitado no host — o índice e os recortes dependem de **tempo confiável (UTC)**.
