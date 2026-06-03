# Orwell — Reescrita para Orin NX (Design / Spec)

- **Data:** 2026-06-01
- **Status:** Aprovado (brainstorming) — pronto para plano de implementação
- **Autores:** Uriel + Claude (consultoria de arquitetura)
- **Substitui (parcialmente):** [`2026-05-31-orwell-dvr-borda-design.md`](2026-05-31-orwell-dvr-borda-design.md)
  na parte de **hardware-alvo e encode**. A arquitetura macro (índice, HLS, Tailscale) permanece.

---

## 1. Resumo executivo e motivação

O projeto Orwell foi desenhado em 2026-05-31 assumindo **Jetson Orin Nano**, cuja **ausência de
NVENC** (encoder de hardware) era a **restrição central**: todo encode tinha de ser por software
(`x264enc`), com perfil reduzido (1080p@15fps) e H.265 considerado inviável.

**O hardware real do projeto é a Jetson Orin NX**, que **possui NVENC**. Isso muda a restrição
central e justifica uma reescrita que:

1. Torna o **encoder selecionável por configuração**: **NVENC por hardware (H.265/H.264) como
   padrão na NX**, com **`x264enc` por software como fallback** (Nano / sem NVENC). O software fica
   **agnóstico ao módulo**, como o [ADR-0012](../../decisions/0012-orin-nx-caminho-de-escala.md)
   já exigia.
2. **Reescreve o código do zero** seguindo este spec, mantendo a arquitetura macro validada e
   guiando as partes puras por **TDD**.
3. Mantém o **DeepStream desde a Fase 1** (com `nvinfer` desligado por config), porque a **IA vem
   logo em seguida** — pagar a integração do DeepStream uma vez agora evita reestruturar o pipeline
   e revalidar o framework no device pouco depois.
4. Resolve o **fluxo de desenvolvimento remoto Mac → Jetson** (headless), incluindo **preview de
   câmera ao vivo** via serviço opcional.

## 2. Objetivos e não-objetivos

### Objetivos (esta reescrita = Fase 1 na NX)
- Gravar **2 câmeras** ZED X One S continuamente em buffer circular (retenção = "o máximo que o
  disco aguentar").
- **Encode por hardware (NVENC)** na Orin NX, **selecionável por config** (codec + hw/sw), com
  fallback por software documentado.
- Expor a **Clip API**: `GET` de um intervalo `[t_início, t_fim]` por câmera → MP4
  (`ffmpeg -c copy`).
- **Pipeline DeepStream** com a **seção de inferência cabeada porém desligada** (`ai.enabled:
  false`) — costura limpa para a Fase 2.
- Acesso remoto seguro via **Tailscale**; **fluxo de dev Mac → Jetson** documentado.
- **Preview de câmera ao vivo** (RTSP/WebRTC) como ferramenta de dev opcional.
- **Tudo containerizado** (docker-compose): subir/matar/reiniciar serviço a serviço.

### Não-objetivos (agora)
- **IA real** (modelo TensorRT, eventos, upload de evento) — Fase 2 (a costura fica pronta).
- **Profundidade / 3D / estéreo** (ZED SDK pesado).
- **Yocto / OTA de host** — só ao industrializar ([ADR-0011](../../decisions/0011-sem-yocto-na-poc.md)).
- **Registry de imagens / K3s / Rancher** — Fase 3 (POC builda local).
- **WebRTC no caminho de produção** — na Fase 1 é só ferramenta de dev/bring-up.

## 3. Hardware e plataforma

| Item | Escolha | Observação |
|---|---|---|
| Compute | **Jetson Orin NX** (primário) | ✅ **Possui NVENC** (encode HW) + NVDEC. |
| Compute (fallback) | Jetson Orin Nano | ⚠️ **Sem NVENC** → encode por software. Pino-compatível. |
| Carrier | Mini Carrier / ZED Box (Stereolabs) | GMSL2 via ZED Link capture card. |
| Câmeras | **2× ZED X One S** | Monoculares, global shutter. GMSL2, **não USB**. |
| Storage | **NVMe** | Define a retenção (rotação por espaço). |
| SO | **JetPack** (L4T) | Driver GMSL casado com a versão do L4T. **No host (kernel).** |
| Rede remota | **Tailscale** | Acesso seguro sem abrir portas. |

A Orin NX é **pino-compatível** com o carrier do Orin Nano. A NX tem CPU/RAM/GPU folgados para
rodar DeepStream + encode HW + (futuramente) inferência sem o aperto que existia na Nano.

## 4. Stack de software

- **Tudo em Python** (orquestração) sobre a camada nativa (GStreamer/DeepStream/TensorRT).
- **Plano de mídia:** aplicação **DeepStream** via GStreamer/`gi` (e `pyds` na Fase 2 para ler
  metadados de inferência). Captura por **Argus** (`nvarguscamerasrc`).
- **Plano de controle:** **FastAPI** (Clip API).
- **Da Stereolabs, apenas o driver GMSL** (kernel, no host).
- **Containers:** docker-compose (POC) → K3s + Rancher (frota, Fase 3).

## 5. Restrição central (revisada): encode na Orin NX

A Orin NX **possui NVENC**. Portanto:

- **Padrão:** **encode por hardware** (`nvv4l2h265enc` / `nvv4l2h264enc`). H.265 vira viável e
  recomendado (arquivos ~2× menores → mais dias de retenção). Os frames permanecem em memória
  **NVMM** (GPU) — sem a cópia NVMM→CPU que o caminho por software exige.
- **Fallback (Nano / sem NVENC):** **`x264enc` por software**, exigindo `nvvidconv` para baixar os
  frames para a CPU (I420). H.265 por software **não é suportado** (inviável em tempo real).
- A escolha é por **configuração**, não por código (ver §7). Decisão registrada em **ADR-0014**;
  o antigo [ADR-0005](../../decisions/0005-encode-h264-software-perfil-reduzido.md) é
  **superseded**.

## 6. Arquitetura

### 6.1 Componentes (containers via docker-compose)

1. **`recorder`** — aplicação **DeepStream/GStreamer** (perfil `jetson`). Pipeline modular por
   câmera com a seção de inferência **desligável** (ver §6.3).
2. **`clip-api`** — FastAPI. `GET /clips?camera&start&end` → consulta o índice → seleciona
   segmentos → **`ffmpeg -c copy`** → MP4. Exposta via Tailscale.
3. **`preview`** *(perfil `dev`, opcional)* — **MediaMTX** servindo **RTSP/WebRTC** para preview de
   câmera ao vivo durante o desenvolvimento. Alimentado por um branch do `tee` do recorder,
   **gated por `preview.enabled`** (off por padrão; não pesa na gravação quando desligado).

### 6.2 Armazenamento e índice (inalterado)
- **Segmentos fMP4/CMAF** de ~**4 s** (configurável) + **playlist `.m3u8`** por câmera, **GOP ~1 s**
  → recorte por cópia de stream com precisão de ~1 s, **sem recomprimir**. Layout
  `data/{cam}/{AAAA}/{MM}/{DD}/{HH}/seg-<epoch>.m4s`. Ver
  [ADR-0006](../../decisions/0006-mp4-padrao-splitmuxsink.md).
- **Índice em SQLite:** `(camera_id, t_inicio, t_fim, path, size, created_at)`. Fonte de verdade
  para a Clip API. Ver [ADR-0007](../../decisions/0007-indice-sqlite.md).
- **Rotação por espaço:** acima de ~85% de uso, apaga segmentos mais antigos (e remove do índice).

### 6.3 Pipeline do recorder (o núcleo da mudança)

**Montagem modular**, com costura de IA desligável por config.

**Fase 1 (`ai.enabled: false`)** — por câmera, sem inferência. **Encoda uma vez**; um `tee` após o
parser distribui o stream já codificado para gravação e (opcionalmente) preview:
```
nvarguscamerasrc(sensor-id=k) → caps(NVMM, W×H, fps) → <ENCODER> → <PARSER> → tee
   ├─ splitmuxsink(mp4mux fragmentado) → NVMe (seg-<epoch>.m4s)
   └─(opcional, preview.enabled) → <branch RTSP/WebRTC p/ MediaMTX>
```
Com `preview.enabled: false` o `tee` tem um único consumidor (gravação) — custo desprezível.

**`<ENCODER>` selecionável por config:**

| `capture.codec` | `capture.encoder` | Elementos GStreamer | Memória |
|---|---|---|---|
| `h265` | `hw` | `nvv4l2h265enc` | NVMM (sem cópia p/ CPU) — **padrão NX** |
| `h264` | `hw` | `nvv4l2h264enc` | NVMM |
| `h264` | `sw` | `nvvidconv → video/x-raw,I420 → x264enc` | CPU — **fallback Nano** |
| `h265` | `sw` | — | **rejeitado** com erro de validação claro |

`<PARSER>` = `h265parse` ou `h264parse` conforme o codec. **GOP** = `round(gop_seconds × fps)`
(`key-int-max`). `splitmuxsink` nomeia cada fragmento via callback `format-location-full`
(`seg-<epoch_ms>.m4s`), `max-size-time = segment_seconds`.

**Fase 2 (`ai.enabled: true`, fora do escopo agora; costura desenhada):**
```
[cam0,cam1] → nvstreammux(batch=N) → nvinfer → nvtracker → nvstreamdemux
            → [por câmera: <ENCODER> → <PARSER> → splitmuxsink]
   probe no src pad do nvinfer/nvtracker: lê NvDsObjectMeta → dispara evento (Fase 2)
```
Ligar a IA = `ai.enabled: true` + prover engine TensorRT e config do `nvinfer` + adicionar o probe.
**O caminho de gravação/encoder/sink não muda entre as fases.**

**Base image:** `nvcr.io/nvidia/deepstream:<tag>` (via `ARG`), casando com o JetPack/L4T instalado.

### 6.4 Fluxos de dados
1. **Gravação contínua (sempre on):** câmera → DeepStream → encode (HW) → segmentos + índice.
2. **GET sob demanda (humano via Tailscale):** clip-api → índice → `ffmpeg -c copy` → MP4.
3. **Preview ao vivo (dev, opcional):** tee do recorder → MediaMTX → RTSP/WebRTC no Mac (VLC/browser).
4. **Evento de IA (Fase 2):** `nvinfer` detecta → transporte a definir → serviço de upload → recorta ~10 s → nuvem.

### 6.5 Interfaces (contratos — inalterados)
- **Clip API:** `GET /clips?camera={id}&start={iso8601}&end={iso8601}` → `200` MP4
  (`Content-Type: video/mp4`); `404` se fora da janela retida. `GET /healthz`, `/cameras`,
  `/segments`.
- **Índice:** `add_segment(...)`, `query(camera, start, end)` em `shared`.
- Evento de IA (Fase 2): schema e transporte a definir.

## 7. Configuração (12-factor)

`config/orwell.yaml` — adições destacadas:

```yaml
capture:
  width: 1920
  height: 1080
  fps: 30
  codec: h265          # h264 | h265
  encoder: hw          # hw (NVENC, Orin NX) | sw (x264enc, fallback Nano)
  gop_seconds: 1.0
  segment_seconds: 4.0
  bitrate_kbps: 8000
ai:
  enabled: false       # Fase 1 = false; Fase 2 liga a seção nvinfer/nvtracker
  # (Fase 2) nvinfer_config / tracker_config
preview:
  enabled: false       # branch RTSP/WebRTC p/ MediaMTX (ferramenta de dev)
```

- `CaptureProfile` ganha `encoder: str = "hw"`. **Validação:** `codec == "h265" and encoder ==
  "sw"` → erro explícito na carga da config.
- Novos modelos `AIConfig(enabled=False, ...)` e `PreviewConfig(enabled=False, ...)` em
  `OrwellConfig`.
- **Defaults:** `h265 / hw / 1080p@30`. Tunável; **números finais validados on-device**.
- Overrides por env preservados (`ORWELL_CAPTURE__ENCODER=sw`, etc.).

## 8. Operação: acesso remoto e dev Mac → Jetson

Dois eixos (ver [`operations.md`](../../operations.md)):
- **Alcance de rede:** **Tailscale** (WireGuard mesh) — estado da arte para acesso a borda; zero
  portas abertas, MagicDNS, ACLs, Tailscale SSH.
- **Orquestração/frota:** **Rancher Fleet** na Fase 3 (ADR-0009); avaliar **NVIDIA Fleet Command**
  como alternativa NVIDIA-nativa.

**Fluxo de dev remoto (Mac → Jetson headless) — nova seção em `operations.md`:**
1. **Tailscale** nos dois → Jetson acessível por nome (`orwell-nx`).
2. **VS Code / Cursor Remote-SSH** sobre o tailnet = bancada principal: editar, terminal, rodar
   `docker compose`, ler logs, **port-forward automático** (8080 → `localhost:8080` no Mac).
3. **Ver gravado / quase-ao-vivo:** **VLC/Safari** abrindo a **HLS** (`.m3u8`) ou um clipe da
   **Clip API**, pelo tailnet.
4. **Ver câmera ao vivo (bring-up):** serviço **`preview` (MediaMTX)**, perfil `dev` → **RTSP**
   (`rtsp://orwell-nx:8554/cam0` no VLC) ou **WebRTC** (browser). Sub-segundo.
5. **Sanity-check rápido:** snapshot JPEG via GStreamer (`num-buffers=1 → jpegenc`) + `scp`.
6. **Evitar:** X11 forwarding / VNC para vídeo (renderizar na Jetson e espelhar a tela é ruim em
   rede; sempre mandar os dados de vídeo para o Mac).

**Regra de ouro reforçada:** **tudo em containers.** Iterar = `docker compose up -d <serviço>`,
`down`, `restart`, `logs -f <serviço>`. Nada roda no host além do que é kernel/driver. Perfis:
`jetson` (recorder), `dev` (preview/MediaMTX).

## 9. Estrutura do repositório (monorepo — mantida)

```
orwell/
  docker-compose.yml          # clip-api, recorder(jetson), preview(dev)
  config/                     # orwell.yaml (+ nvinfer/tracker na Fase 2; mediamtx.yml dev)
  services/
    recorder/                 # pipeline.py (puro/testável) · indexer.py · main.py (gi/Gst)
    clip-api/                 # FastAPI (main · settings)
  shared/orwell_shared/       # config · index · paths · clips · retention
  models/                     # engines TensorRT (Fase 2; gitignored)
  deploy/                     # provisionamento como código (host)
  docs/                       # documentação + ADRs
  tests/                      # testes de integração
```

## 10. Estratégia de testes (TDD nas partes puras)

- **`recorder/pipeline.py` (coração da mudança, 100% testável sem GStreamer):**
  - cada combinação `codec × encoder` gera a string de pipeline correta;
  - GOP = `round(gop_seconds × fps)`;
  - caminho HW mantém NVMM; caminho SW insere `nvvidconv`/I420;
  - `codec=h265 + encoder=sw` → erro de validação;
  - builder da costura de IA: `ai.enabled=false` → pipeline simples; `true` → cadeia com
    `nvstreammux/nvinfer/nvtracker` (montagem testável como string, runtime on-device).
- **`shared`:** `index`, `clips`, `retention`, `paths`, `config` (incl. validação encoder/codec) — testes unitários.
- **`clip-api`:** testes de rota (índice fake → seleção de segmentos → resposta).
- **On-device (Jetson):** runtime `gi`/Gst, elementos NVIDIA (`nvarguscamerasrc`, `nvv4l2*enc`),
  concat fMP4, câmeras Argus, MediaMTX. **Não testável no macOS.**

## 11. Refatoração de documentação e ADRs

| Arquivo | Mudança |
|---|---|
| **Este spec** | Fonte de verdade da reescrita NX |
| **ADR-0005** | *Superseded* (deixa de ser "encode H.264 SW" como restrição central) |
| **Novo ADR-0014** | "Encoder selecionável por config: NVENC HW (default) + x264 SW (fallback)" |
| **ADR-0003** | Nota: DeepStream desde a Fase 1; `nvinfer` desligado até a Fase 2 |
| **ADR-0012** | Status: Orin NX passa de "caminho de escala" a **alvo primário** |
| `docs/hardware.md` | BOM → Orin NX; §3 reescrita (NVENC presente); §4 (Nano = fallback) |
| `docs/architecture.md` | §3 pipeline: encoder HW config-driven, NVMM, costura de IA, preview |
| `docs/roadmap.md` | Fase 1 na NX (HW encode); IA iminente; itens WebRTC e Fleet Command |
| `CLAUDE.md` | Bloco "Restrições": NVENC disponível na NX (Nano = fallback) |
| `docs/operations.md` | Nova seção "dev remoto Mac → Jetson" + preview MediaMTX |
| `docs/glossary.md` | Entradas: NVENC, `nvv4l2h265enc`, HW vs SW encode, WebRTC, MediaMTX |

## 12. Faseamento (atualizado)

- **Fase 1 (esta reescrita):** DVR na **Orin NX** com **encode HW (H.265) config-driven**, Clip API
  via Tailscale, costura de IA pronta (desligada), preview ao vivo (dev). → **DVR funcional e
  acessível do Mac.**
- **Fase 2 (logo em seguida):** ligar `nvinfer` (modelo TensorRT) → eventos → upload de clipes de
  evento (transporte a definir na Fase 2). Avaliar **WebRTC** em produção.
- **Fase 3:** K3s + Rancher Fleet; registry; avaliar **NVIDIA Fleet Command**; OTA de host.

## 13. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Nomes/props exatos dos elementos NVENC variam por JetPack/L4T/DeepStream | Validar on-device; `pipeline.py` isola a montagem; `ARG` da imagem DeepStream |
| Peso do DeepStream na Fase 1 sem IA | NX tem folga; paga-se uma vez (evita reestruturar na Fase 2) |
| Reescrita "do zero" regredir o que já funcionava | Manter arquitetura macro validada; TDD nas partes puras; mesma cobertura de testes |
| Preview (tee) competir com a gravação | `preview.enabled=false` por padrão; branch só sobe no perfil `dev` |
| Compatibilidade driver GMSL × L4T | Casar `.deb` com o JetPack; fixar em `deploy/00-versions.env` |

## 14. Decisões (ADRs)

Ver `docs/decisions/`. Afetados por esta reescrita: **0003** (nota), **0005** (superseded),
**0012** (status → primário), **novo 0014** (encoder config-driven). Inalterados: 0001, 0002,
0004, 0006, 0007, 0008, 0009, 0010, 0011, 0013.

## 15. Referências

- Orin NX possui NVENC; Orin Nano não — NVIDIA Jetson Linux Developer Guide.
- ZED X One / driver GMSL — Stereolabs docs.
- DeepStream (`nvstreammux`, `nvinfer`, `nvtracker`, Smart Record) — NVIDIA DeepStream dev guide.
- Tailscale (WireGuard mesh), MediaMTX (RTSP/WebRTC), NVIDIA Fleet Command — docs dos fornecedores.
