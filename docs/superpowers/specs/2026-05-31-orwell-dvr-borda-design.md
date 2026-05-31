# Orwell — DVR de borda com IA (Design / Spec)

- **Data:** 2026-05-31
- **Status:** Aprovado (brainstorming) — pronto para plano de implementação
- **Autores:** Uriel + Claude (consultoria de arquitetura)

---

## 1. Resumo executivo

Orwell é um **gravador contínuo de vídeo na borda (estilo DVR)** rodando em **NVIDIA Jetson
Orin Nano** com câmeras **Stereolabs ZED X One S** (GMSL2). O produto grava todas as câmeras
continuamente em um **buffer circular** (segmentos rotativos em NVMe), expõe uma **API para
recortar e baixar intervalos arbitrários** de vídeo (acessível remotamente via **Tailscale**) e,
em uma fase seguinte, roda **IA local** sobre o vídeo para detectar eventos. Cada evento dispara
o **envio de ~10 s de vídeo daquele momento para a nuvem**.

O objetivo imediato é uma **POC rápida** que já nasça com **fronteiras de serviço desenhadas
para escalar** (futuramente gerenciada por **Rancher**).

## 2. Objetivos e não-objetivos

### Objetivos (POC)
- Gravar **2 câmeras** ZED X One S continuamente em buffer circular (retenção = "o máximo que o
  disco aguentar").
- Expor uma **Clip API**: `GET` de um intervalo `[t_início, t_fim]` por câmera → arquivo MP4.
- Acesso remoto seguro via **Tailscale**.
- Estrutura de repositório e serviços **pronta para escalar** (containers, 12-factor, fases
  claras para IA, nuvem e frota).

### Objetivos (fases seguintes)
- **IA local** (TensorRT) gerando eventos sobre o vídeo ao vivo.
- **Evento → recorte de ~10 s → upload para nuvem** (backend plugável, S3 por padrão).
- **Gestão de frota** via **Rancher** (K3s + Fleet/GitOps) e provisionamento de SO.

### Não-objetivos (agora)
- **Profundidade / 3D / estéreo** (ZED SDK pesado) — reservado para o futuro, se necessário.
- **Yocto / imagem de SO customizada** — só quando industrializar.
- **Registry de imagens** — entra junto com o Rancher (POC builda local).
- **H.265 por hardware** — depende de NVENC, ausente no Orin Nano (ver §6).

## 3. Hardware e plataforma

| Item | Escolha | Observação |
|---|---|---|
| Compute | **Jetson Orin Nano** | ⚠️ **Sem NVENC** (encoder de hardware). Só **NVDEC** (decode). |
| Carrier | Mini Carrier / ZED Box (Stereolabs) | GMSL2 via ZED Link capture card. |
| Câmeras | **2× ZED X One S** | **Monoculares** (lente única, global shutter). GMSL2, **não USB**. |
| Storage | **NVMe** | Define a retenção (rotação por espaço). |
| SO | **JetPack** (L4T padrão) | Sem Yocto na POC. |
| Driver câmera | **Driver GMSL da Stereolabs** | Kernel, **no host**, casado com a versão do L4T. **Obrigatório.** |
| Rede remota | **Tailscale** | Acesso seguro sem abrir portas. |

**Caminho de escala de hardware:** o módulo **Orin NX é pino-compatível** com o mesmo carrier do
Orin Nano e **possui NVENC** → trocar o módulo destrava **H.265 por hardware** e libera CPU,
**sem reprojetar a placa**. Ver [ADR-0012](../../decisions/0012-orin-nx-caminho-de-escala.md).

## 4. Stack de software

- **Tudo em Python.**
  - **Plano de mídia/IA:** aplicação **DeepStream** via **`pyds`** (bindings Python).
  - **Plano de controle:** **FastAPI**/Python (Clip API), worker Python (Uploader).
- **Da Stereolabs, apenas o driver GMSL.** Captura, IA e gravação são **NVIDIA**:
  **Argus** (captura) + **DeepStream** (pipeline) + **TensorRT** (inferência).
- **Por que Python não custa performance:** os frames vivem em memória nativa/GPU e fluem entre
  blocos C/CUDA do GStreamer/DeepStream/TensorRT; o Python só **orquestra o pipeline** e **reage a
  eventos** (metadados leves). Ver [glossário](../../glossary.md) e [ADR-0004](../../decisions/0004-stack-tudo-python.md).

## 5. Arquitetura

### 5.1 Componentes (containers via docker-compose)

1. **`recorder`** — aplicação DeepStream (pyds). Pipeline por câmera:
   `nvarguscamerasrc → nvstreammux (batch 2) → nvinfer (TensorRT, *stub* na POC) → tee`
   - **Ramo A (gravação):** `x264enc` (software) → mux → **`splitmuxsink`** → segmentos no NVMe;
     atualiza o índice.
   - **Ramo B (evento):** **Smart Record** (NvDsSR) mantendo cache de vídeo codificado para
     recortes pré/pós evento.
   - Publica eventos de detecção em **MQTT** (via `nvmsgbroker` ou cliente MQTT).
2. **`clip-api`** — FastAPI. `GET /clips?camera&start&end` → consulta o índice → seleciona
   segmentos → **ffmpeg copy** (sem recomprimir) → MP4. Exposta via Tailscale.
3. **`uploader`** — worker. Assina MQTT → obtém clipe de ~10 s → envia via **backend de storage
   plugável** (S3 por padrão; interface para Azure/GCP).
4. **`broker`** — **Mosquitto** (MQTT) local; barramento de eventos desacoplando recorder ↔ uploader.

### 5.2 Armazenamento e índice
- **Segmentos fMP4/CMAF** de ~**4 s** (configurável) + **playlist `.m3u8`** por câmera, **GOP ~1 s**
  (keyframe a cada segundo) → recorte por cópia de stream com precisão de ~1 s, **sem recomprimir**
  (essencial sem NVENC). Layout `data/{cam}/{AAAA}/{MM}/{DD}/{HH}/`. Ver
  [ADR-0006](../../decisions/0006-mp4-padrao-splitmuxsink.md).
- **Índice em SQLite:** `(camera_id, t_inicio, t_fim, caminho_arquivo, ...)`. Fonte de verdade
  para a Clip API.
- **Rotação por espaço:** ao ultrapassar um limite de disco (ex.: **85%**), apaga os segmentos
  mais antigos. Retenção efetiva = função do tamanho do NVMe.

### 5.3 Fluxos de dados
1. **Gravação contínua (sempre on):** câmera → DeepStream → encode → segmentos + índice.
2. **GET sob demanda (humano via Tailscale):** clip-api → índice → ffmpeg copy → MP4.
3. **Evento de IA (automático):** `nvinfer` detecta → MQTT → uploader → recorta ~10 s → nuvem.

### 5.4 Interfaces (contratos)
- **Clip API:** `GET /clips?camera={id}&start={iso8601}&end={iso8601}` → `200` MP4
  (`Content-Type: video/mp4`); `404` se fora da janela retida.
- **Evento MQTT** (tópico `orwell/events`): JSON
  `{ "camera_id", "ts_event", "label", "score", "pre_s", "post_s" }`.
- **Backend de storage (uploader):** interface `put(clip_path, metadata) -> uri`
  (implementação padrão: S3).
- **Índice:** módulo `shared` com funções `add_segment(...)`, `query(camera, start, end)`.

## 6. Restrição central: ausência de NVENC no Orin Nano

A NVIDIA confirma que o **Orin Nano não possui encoder de hardware (NVENC)** — apenas decoder
(NVDEC). Consequências:
- **Encode é por software (CPU)** via `x264enc`/libx264. **H.265 software em tempo real para 2
  streams é inviável**; o caminho é **H.264 software** com preset rápido.
- Para liberar CPU para a inferência futura, a POC usa um **perfil reduzido** (ver §7).
- O **caminho de escala** para encode pesado/H.265 é o módulo **Orin NX** (NVENC).

## 7. Perfil de captura (POC)
- **Resolução/FPS:** 1080p @ 15 fps por câmera (tunável; sensor nativo é 1920×1200@30).
- **Câmeras:** 2 simultâneas.
- **Codec:** H.264 software, preset rápido, **GOP ~1 s**.
- **Segmento:** fMP4/CMAF de ~**4 s** (configurável) + playlist HLS por câmera.
- Todos os valores são **configuráveis** (`config/`), para ajuste empírico no device.

## 8. Operação: acesso remoto e atualização

- **Acesso remoto = Tailscale** (eixo de *alcance de rede*): MagicDNS (nome por device), ACLs,
  Tailscale SSH. Clip API alcançável em `http://{device}:8080/clips?...` sem porta aberta.
- **Atualização dos serviços = orquestração** (eixo de *gestão*):
  - **POC:** `docker-compose` + **build local** no Jetson; update = `docker compose pull/up -d`
    (ou rebuild local) via Tailscale SSH.
  - **Frota (futuro):** **K3s** (Kubernetes leve, arm64) + **Helm** + **Rancher Fleet (GitOps)**;
    **registry** de imagens (GHCR ou Harbor) entra nesta fase.
- **Separação de camadas:** Rancher/K3s atualizam **containers**; **driver GMSL + JetPack +
  Tailscale** vivem no **host** (provisionamento de SO é outra camada — Yocto/Rancher Elemental
  no futuro).
- **GPU + câmera no K8s (futuro):** NVIDIA device plugin + pod `recorder` privilegiado com
  `/dev/video*` e socket do Argus montados.

## 9. Estrutura do repositório (monorepo)

```
orwell/
  docker-compose.yml          # orquestra recorder, clip-api, uploader, broker
  config/                     # câmeras, perfil de captura, retenção, nuvem (env / yaml)
  services/
    recorder/                 # app DeepStream (pyds) + configs (nvinfer, smart record)
    clip-api/                 # FastAPI
    uploader/                 # consumidor MQTT + backends de storage (s3, base)
  shared/                     # lib Python: índice (SQLite), schemas (evento, clip), paths
  models/                     # engines TensorRT / ONNX (grandes → gitignored; pointers)
  deploy/                     # host-setup (driver GMSL, tailscale, NTP), notas de provisionamento
  docs/                       # esta documentação
  tests/
```

## 10. Faseamento

- **Fase 1 — POC (foco):** 2 câmeras gravando continuamente + rotação + índice + **Clip API via
  Tailscale**. `nvinfer` como *stub*; `broker`/`uploader` já no esqueleto. → **DVR funcional e
  acessível remotamente.**
- **Fase 2 — IA + nuvem:** modelo TensorRT real no `nvinfer` → eventos MQTT → `uploader` →
  upload de clipes de evento para a nuvem.
- **Fase 3 — Escala/frota:** migrar para **K3s + Rancher Fleet**; **registry**; considerar
  **Orin NX** (NVENC/H.265); avaliar **Yocto/OTA** e provisionamento de frota.

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Orçamento de CPU (2×1080p15 SW + inferência) | Perfil reduzido/tunável; validar on-device; caminho Orin NX. |
| Câmera dentro de container | NVIDIA Container Runtime + mapear `/dev/video*` e socket do Argus; driver no host. |
| Relógio do índice ("GET intervalo") | NTP no Jetson; timestamps em UTC. |
| Compatibilidade driver GMSL × L4T | Casar versão do `.deb` com o JetPack instalado; fixar versões em `deploy/`. |
| Lock-in | MP4 padrão (não SVO), backend de nuvem plugável, Tailscale + stack aberta. |

## 12. Decisões (ADRs)

Ver `docs/decisions/`:
- 0001 — Gravar DVR de borda no Jetson (contexto/projeto)
- 0002 — Stereolabs: só o driver GMSL (sem ZED SDK pesado)
- 0003 — DeepStream como plano de mídia/IA
- 0004 — Stack tudo em Python
- 0005 — Encode H.264 por software + perfil reduzido (Orin Nano sem NVENC)
- 0006 — MP4 padrão via splitmuxsink (não SVO)
- 0007 — Índice de segmentos em SQLite
- 0008 — Acesso remoto via Tailscale
- 0009 — docker-compose agora → K3s + Rancher Fleet depois
- 0010 — Storage de nuvem plugável (S3 por padrão)
- 0011 — Sem Yocto na POC
- 0012 — Orin NX como caminho de escala (NVENC/H.265)

## 13. Referências

- Orin Nano sem NVENC — NVIDIA Jetson Linux Developer Guide, "Software Encode in Orin Nano".
- ZED X One / driver GMSL — Stereolabs docs (ZED X One, GMSL2 Drivers, ZED Link).
- DeepStream Smart Record / `nvmsgbroker` — NVIDIA DeepStream dev guide.
