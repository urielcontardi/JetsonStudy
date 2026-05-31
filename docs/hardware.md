# Hardware e plataforma — Orwell

## 1. Bill of materials (POC)

| Componente | Modelo | Papel |
|---|---|---|
| Compute | NVIDIA **Jetson Orin Nano** | Processa captura, encode (SW), IA |
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

## 3. ⚠️ Restrição crítica: Orin Nano não tem NVENC

A NVIDIA confirma na documentação oficial ("Software Encode in Orin Nano") que o **Orin Nano não
possui o engine NVENC** — apenas **NVDEC** (decode). Implicações:

- **Todo encode é por software (CPU)** via `libx264`/`x264enc`.
- Benchmark de referência (RidgeRun, 1080p, 10 Mbps): `ultrafast` ~71 fps, `medium` ~24 fps,
  `veryslow` ~5 fps em um único stream. **2 streams** consomem boa parte da CPU.
- **H.265 por software em tempo real para 2 streams é inviável** → usamos **H.264 software**,
  preset rápido, GOP ~1 s.
- Tentativas de usar `nvv4l2h264enc`/`/dev/v4l2-nvenc` **falham** (não existe o device).

### Mitigações
- **Perfil reduzido** na POC (1080p@15fps) para deixar CPU para a inferência.
- **Recorte por cópia de stream** (sem recomprimir) → não gasta CPU para gerar clipes.
- **Caminho de escala: Orin NX** (ver §4).

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

## 7. Rede e tempo

- **Tailscale** no host para acesso remoto (ver [`operations.md`](operations.md)).
- **NTP** habilitado no host — o índice e os recortes dependem de **tempo confiável (UTC)**.
