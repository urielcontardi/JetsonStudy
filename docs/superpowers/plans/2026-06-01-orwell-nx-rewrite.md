# Orwell — Reescrita para Orin NX (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adaptar o Orwell para a Jetson Orin NX com encode por hardware (NVENC) selecionável por configuração, mantendo fallback por software, DeepStream desde a Fase 1 com a costura de IA desligável, e preview de câmera ao vivo para dev — tudo validado por TDD nas partes puras.

**Architecture:** O coração da mudança é o `recorder/pipeline.py` (construção de string de pipeline GStreamer, 100% testável sem GStreamer) e o `shared/orwell_shared/config.py` (schema + validação). A arquitetura macro (4 serviços, índice SQLite, HLS, recorte por `ffmpeg copy`, MQTT, Tailscale, storage plugável) é preservada. Módulos sem mudança de comportamento (`index`, `paths`, `clips`, `retention`, `events`, `storage`, `clip-api`, `uploader`, `indexer`) ficam como estão, com seus testes existentes como rede de segurança.

**Tech Stack:** Python 3, pydantic v2, pytest, GStreamer/DeepStream (`gi`/`pyds`, runtime só no Jetson), docker-compose, MediaMTX (preview), ffmpeg.

**Fonte de verdade:** `docs/superpowers/specs/2026-06-01-orwell-nx-rewrite-design.md`.

**Convenção de bitrate (CRÍTICA — fonte comum de bug):**
- Encoders HW NVIDIA (`nvv4l2h264enc`/`nvv4l2h265enc`): propriedade `bitrate` em **bits/segundo** → `bitrate_kbps * 1000`. GOP via `iframeinterval` (em frames).
- Encoder SW (`x264enc`): propriedade `bitrate` em **kbit/segundo** → `bitrate_kbps`. GOP via `key-int-max` (em frames).

**Como rodar os testes:** a partir da raiz do repo, `python -m pytest <caminho> -v`. (`pyproject.toml` define os pacotes; rode no venv do projeto.)

---

## Task 1: Config — campo `encoder`, modelos `AIConfig`/`PreviewConfig` e validação

**Files:**
- Modify: `shared/orwell_shared/config.py`
- Test: `shared/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Adicione ao final de `shared/tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from orwell_shared.config import CaptureProfile, OrwellConfig


def test_capture_defaults_to_h265_hw():
    prof = CaptureProfile()
    assert prof.codec == "h265"
    assert prof.encoder == "hw"
    assert prof.fps == 30


def test_h265_software_is_rejected():
    with pytest.raises(ValidationError):
        CaptureProfile(codec="h265", encoder="sw")


def test_h264_software_is_allowed():
    prof = CaptureProfile(codec="h264", encoder="sw")
    assert prof.encoder == "sw"


def test_ai_and_preview_default_disabled():
    cfg = OrwellConfig()
    assert cfg.ai.enabled is False
    assert cfg.preview.enabled is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest shared/tests/test_config.py -v`
Expected: FAIL (`CaptureProfile` has no `encoder`; `AIConfig`/`PreviewConfig` not defined; no validation error raised). Note: `test_capture_defaults_to_h265_hw` will also fail because the current default fps is 15 and codec default exists but encoder doesn't.

- [ ] **Step 3: Implement the schema changes**

Em `shared/orwell_shared/config.py`, ajuste o import e os modelos. Troque o import do pydantic:

```python
from pydantic import BaseModel, Field, model_validator
```

Substitua a classe `CaptureProfile` por:

```python
class CaptureProfile(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "h265"          # h264 | h265
    encoder: str = "hw"          # hw (NVENC, Orin NX) | sw (x264enc, fallback Nano)
    gop_seconds: float = 1.0
    segment_seconds: float = 4.0
    bitrate_kbps: int = 8000

    @model_validator(mode="after")
    def _reject_h265_software(self) -> "CaptureProfile":
        if self.codec == "h265" and self.encoder == "sw":
            raise ValueError(
                "codec=h265 com encoder=sw é inviável em tempo real; "
                "use encoder=hw (NVENC) ou codec=h264 para software"
            )
        return self
```

Adicione, após `CloudConfig`:

```python
class AIConfig(BaseModel):
    enabled: bool = False        # Fase 1 = false; Fase 2 liga nvinfer/nvtracker
    nvinfer_config: str | None = None
    tracker_config: str | None = None


class PreviewConfig(BaseModel):
    enabled: bool = False        # branch RTSP/WebRTC p/ MediaMTX (ferramenta de dev)
    rtsp_base_url: str = "rtsp://preview:8554"
```

Em `OrwellConfig`, adicione os dois campos:

```python
    ai: AIConfig = Field(default_factory=AIConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_config.py -v`
Expected: PASS (todos, incluindo os pré-existentes `test_load_config_parses_yaml` e `test_env_overrides_scalar`).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/config.py shared/tests/test_config.py
git commit -m "feat(config): encoder selecionável (hw/sw) + AIConfig/PreviewConfig + validação h265/sw"
```

---

## Task 2: pipeline.py — `parser_element` e `encoder_chain` (HW/SW por codec)

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Test: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Adicione ao final de `services/recorder/tests/test_pipeline.py`:

```python
import pytest

from orwell_shared.config import CaptureProfile
from recorder.pipeline import encoder_chain, parser_element


def test_parser_element_by_codec():
    assert parser_element(CaptureProfile(codec="h264")) == "h264parse"
    assert parser_element(CaptureProfile(codec="h265", encoder="hw")) == "h265parse"


def test_encoder_chain_hw_h265_uses_nvenc_and_bps():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=30, gop_seconds=1.0,
                          bitrate_kbps=8000)
    chain = encoder_chain(prof)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=8000000" in chain      # kbps -> bps
    assert "iframeinterval=30" in chain     # gop_seconds * fps
    assert "nvvidconv" not in chain         # HW fica em NVMM, sem cópia p/ CPU


def test_encoder_chain_hw_h264_uses_nvenc():
    prof = CaptureProfile(codec="h264", encoder="hw", fps=15, gop_seconds=1.0,
                          bitrate_kbps=6000)
    chain = encoder_chain(prof)
    assert "nvv4l2h264enc" in chain
    assert "bitrate=6000000" in chain
    assert "iframeinterval=15" in chain


def test_encoder_chain_sw_h264_uses_x264_and_kbps_and_convert():
    prof = CaptureProfile(codec="h264", encoder="sw", fps=15, gop_seconds=1.0,
                          bitrate_kbps=6000)
    chain = encoder_chain(prof)
    assert "x264enc" in chain
    assert "bitrate=6000" in chain          # x264enc usa kbps
    assert "key-int-max=15" in chain
    assert "nvvidconv" in chain             # baixa NVMM -> CPU (I420)
    assert "I420" in chain
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -v`
Expected: FAIL (`encoder_chain` e `parser_element` não existem).

- [ ] **Step 3: Implement the functions**

Em `services/recorder/recorder/pipeline.py`, adicione após `keyframe_interval`:

```python
def parser_element(profile: CaptureProfile) -> str:
    """Parser GStreamer conforme o codec."""
    return "h265parse" if profile.codec == "h265" else "h264parse"


def encoder_chain(profile: CaptureProfile) -> str:
    """Cadeia de encode conforme codec/encoder.

    HW (NVENC, Orin NX): nvv4l2h26Xenc, bitrate em bits/s, GOP via iframeinterval,
    frames seguem em NVMM (sem cópia p/ CPU).
    SW (x264enc, fallback Nano): nvvidconv baixa NVMM->CPU (I420), bitrate em kbit/s,
    GOP via key-int-max.
    """
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return f"{elem} bitrate={profile.bitrate_kbps * 1000} iframeinterval={kf}"
    # software (somente h264; h265/sw é rejeitado na validação da config)
    return (
        "nvvidconv ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={profile.bitrate_kbps} key-int-max={kf}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -v`
Expected: PASS para os 4 novos testes. (O teste pré-existente `test_build_source_chain_has_expected_elements_and_params` ainda falha — será corrigido na Task 3.)

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/pipeline.py services/recorder/tests/test_pipeline.py
git commit -m "feat(recorder): encoder_chain HW/SW por codec + parser_element"
```

---

## Task 3: pipeline.py — `build_source_chain` usando encoder/parser configuráveis

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Test: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Update the failing test**

Substitua o teste `test_build_source_chain_has_expected_elements_and_params` em
`services/recorder/tests/test_pipeline.py` por dois testes (HW e SW):

```python
def test_build_source_chain_hw_h265():
    cam = CameraConfig(id="0", argus_sensor_id=2)
    chain = build_source_chain(cam, CaptureProfile(width=1920, height=1080, fps=30,
                                                   codec="h265", encoder="hw",
                                                   gop_seconds=1.0, bitrate_kbps=8000))
    assert "nvarguscamerasrc sensor-id=2" in chain
    assert "width=1920,height=1080" in chain
    assert "framerate=30/1" in chain
    assert "nvv4l2h265enc" in chain
    assert "iframeinterval=30" in chain
    assert chain.strip().endswith("h265parse")


def test_build_source_chain_sw_h264_fallback():
    cam = CameraConfig(id="1", argus_sensor_id=0)
    chain = build_source_chain(cam, CaptureProfile(width=1280, height=720, fps=15,
                                                   codec="h264", encoder="sw",
                                                   gop_seconds=1.0, bitrate_kbps=4000))
    assert "x264enc" in chain
    assert "key-int-max=15" in chain
    assert chain.strip().endswith("h264parse")
```

(Mantenha o import de `CameraConfig` no topo do arquivo — já existe.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -v`
Expected: FAIL (o `build_source_chain` atual fixa `x264enc` e `h264parse`, então `test_build_source_chain_hw_h265` falha).

- [ ] **Step 3: Rewrite `build_source_chain`**

Em `services/recorder/recorder/pipeline.py`, substitua a função `build_source_chain` por:

```python
def build_source_chain(camera: CameraConfig, profile: CaptureProfile) -> str:
    """Cadeia captura→encode→parser (até o parser). O sink é anexado em main.py.

    Encoder e parser são escolhidos por config (HW NVENC na Orin NX, x264enc SW como
    fallback). Ver encoder_chain()/parser_element().
    """
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1 ! "
        f"{encoder_chain(profile)} ! "
        f"{parser_element(profile)}"
    )
```

Atualize também a docstring do módulo (linha ~22) removendo a afirmação "Orin Nano não tem
NVENC → encode por software (x264enc)", substituindo por: "Encoder selecionável por config
(NVENC HW na Orin NX; x264enc SW como fallback) — ver encoder_chain()."

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/pipeline.py services/recorder/tests/test_pipeline.py
git commit -m "feat(recorder): build_source_chain usa encoder/parser configuráveis"
```

---

## Task 4: pipeline.py — `inference_stage` (costura de IA desligável)

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Test: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Adicione em `services/recorder/tests/test_pipeline.py`:

```python
from orwell_shared.config import AIConfig
from recorder.pipeline import inference_stage


def test_inference_stage_disabled_is_empty():
    assert inference_stage(AIConfig(enabled=False), num_cameras=2) == ""


def test_inference_stage_enabled_has_nvinfer_chain():
    chain = inference_stage(AIConfig(enabled=True), num_cameras=2)
    assert "nvstreammux" in chain
    assert "batch-size=2" in chain
    assert "nvinfer" in chain
    assert "nvtracker" in chain
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -k inference -v`
Expected: FAIL (`inference_stage` não existe).

- [ ] **Step 3: Implement the seam**

Em `services/recorder/recorder/pipeline.py`, adicione (e importe `AIConfig` no topo:
`from orwell_shared.config import AIConfig, CameraConfig, CaptureProfile`):

```python
def inference_stage(ai: AIConfig, num_cameras: int) -> str:
    """Costura de IA (Fase 2). Desligada (ai.enabled=False) → string vazia.

    Ligada → prefixo de inferência batched para inserir entre as fontes e os encoders.
    A montagem em runtime (probe NvDsObjectMeta → MQTT) fica em main.py; aqui só a
    descrição, validada on-device. Ver docs/superpowers/specs/2026-06-01-...
    """
    if not ai.enabled:
        return ""
    return (
        f"nvstreammux name=mux batch-size={num_cameras} ! "
        "nvinfer config-file-path=$NVINFER_CONFIG ! "
        "nvtracker ! nvstreamdemux name=demux"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -k inference -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/pipeline.py services/recorder/tests/test_pipeline.py
git commit -m "feat(recorder): inference_stage (costura de IA desligável p/ Fase 2)"
```

---

## Task 5: pipeline.py — `preview_branch` (tee → MediaMTX, desligável)

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Test: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Adicione em `services/recorder/tests/test_pipeline.py`:

```python
from orwell_shared.config import PreviewConfig
from recorder.pipeline import preview_branch


def test_preview_branch_disabled_is_empty():
    assert preview_branch(PreviewConfig(enabled=False), camera_id="0") == ""


def test_preview_branch_enabled_pushes_rtsp():
    branch = preview_branch(
        PreviewConfig(enabled=True, rtsp_base_url="rtsp://preview:8554"), camera_id="0")
    assert "rtspclientsink" in branch
    assert "rtsp://preview:8554/cam0" in branch
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -k preview -v`
Expected: FAIL (`preview_branch` não existe).

- [ ] **Step 3: Implement the branch**

Em `services/recorder/recorder/pipeline.py`, importe `PreviewConfig`
(`from orwell_shared.config import AIConfig, CameraConfig, CaptureProfile, PreviewConfig`)
e adicione:

```python
def preview_branch(preview: PreviewConfig, camera_id: str) -> str:
    """Branch opcional do tee enviando o stream JÁ CODIFICADO para o MediaMTX (RTSP).

    Desligado (preview.enabled=False) → string vazia (tee tem só o consumidor de
    gravação, custo desprezível). Ligado → empurra para rtsp://.../cam<id>.
    """
    if not preview.enabled:
        return ""
    url = f"{preview.rtsp_base_url.rstrip('/')}/cam{camera_id}"
    return f"rtspclientsink location={url}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/recorder/tests/test_pipeline.py -k preview -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/pipeline.py services/recorder/tests/test_pipeline.py
git commit -m "feat(recorder): preview_branch (tee->MediaMTX RTSP, desligável)"
```

---

## Task 6: recorder/main.py — fiar tee, preview e seam de IA (runtime, on-device)

**Files:**
- Modify: `services/recorder/recorder/main.py`

> Sem teste unitário: `main.py` usa `gi`/Gst, que só existe no Jetson. Validação é on-device
> (Step 4). Mantenha o código mínimo e legível.

- [ ] **Step 1: Atualizar a docstring e a montagem do bin por câmera**

Em `services/recorder/recorder/main.py`:

1. Troque o trecho da docstring "codifica em H.264 por software (Orin Nano não tem NVENC)"
   por "codifica via encoder configurável (NVENC HW na Orin NX; x264enc SW como fallback)".

2. Atualize os imports do pipeline:

```python
from .pipeline import build_source_chain, max_size_time_ns, preview_branch
```

3. Substitua `_build_camera_bin` para inserir um `tee` após o parser e anexar o branch de
   preview quando habilitado:

```python
def _build_camera_bin(Gst, camera, profile, preview, data_dir: str):
    """Pipeline de uma câmera: captura/encode → tee → splitmuxsink (+ preview opcional)."""
    record_sink = (
        "splitmuxsink name=sink "
        f"max-size-time={max_size_time_ns(profile)} "
        'muxer-factory=mp4mux '
        'muxer-properties="properties,fragment-duration=1000,faststart=true"'
    )
    preview_chain = preview_branch(preview, camera.id)
    desc = build_source_chain(camera, profile) + " ! tee name=t "
    desc += f"t. ! queue ! {record_sink} "
    if preview_chain:
        desc += f"t. ! queue ! {preview_chain} "
    pipeline = Gst.parse_launch(desc)
    sink = pipeline.get_by_name("sink")
    sink.connect("format-location-full", _make_format_location_cb(data_dir, camera.id))
    return pipeline
```

4. Atualize a chamada em `main()` para passar `config.preview`:

```python
    pipelines = [_build_camera_bin(Gst, cam, config.capture, config.preview,
                                   config.retention.data_dir)
                 for cam in config.cameras]
```

- [ ] **Step 2: Validação de import em máquina sem GStreamer (sanidade)**

Run: `python -c "import ast; ast.parse(open('services/recorder/recorder/main.py').read()); print('ok')"`
Expected: `ok` (sintaxe válida; não executa `gi`).

- [ ] **Step 3: Commit**

```bash
git add services/recorder/recorder/main.py
git commit -m "feat(recorder): main fia tee + preview opcional; encoder configurável"
```

- [ ] **Step 4: Validação on-device (registrar como pendência, NÃO bloqueia o plano)**

No Jetson: `docker compose --profile jetson up -d --build recorder` e conferir
`docker compose logs -f recorder` (pipeline em PLAYING, segmentos surgindo em `data/`).
Anotar resultado em `deploy/provisioning-log.md`.

---

## Task 7: config/orwell.yaml — defaults da Orin NX

**Files:**
- Modify: `config/orwell.yaml`

- [ ] **Step 1: Atualizar a seção `capture` e adicionar `ai`/`preview`**

Substitua a seção `capture:` e adicione as seções novas em `config/orwell.yaml`:

```yaml
capture:
  width: 1920
  height: 1080
  fps: 30
  codec: h265            # h264 | h265
  encoder: hw            # hw (NVENC, Orin NX) | sw (x264enc, fallback Nano)
  gop_seconds: 1.0
  segment_seconds: 4.0   # fácil de mudar (ADR-0006)
  bitrate_kbps: 8000
ai:
  enabled: false         # Fase 1 = false; Fase 2 liga nvinfer/nvtracker
preview:
  enabled: false         # ferramenta de dev (RTSP/WebRTC via MediaMTX)
  rtsp_base_url: rtsp://preview:8554
```

- [ ] **Step 2: Verificar que a config carrega e valida**

Run: `python -c "from orwell_shared.config import load_config; c=load_config('config/orwell.yaml'); print(c.capture.codec, c.capture.encoder, c.ai.enabled, c.preview.enabled)"`
Expected: `h265 hw False False`

- [ ] **Step 3: Commit**

```bash
git add config/orwell.yaml
git commit -m "config: defaults Orin NX (h265/hw, 1080p@30) + seções ai/preview"
```

---

## Task 8: docker-compose + config/mediamtx.yml — serviço `preview` (perfil `dev`)

**Files:**
- Modify: `docker-compose.yml`
- Create: `config/mediamtx.yml`

- [ ] **Step 1: Criar config mínima do MediaMTX**

Crie `config/mediamtx.yml`:

```yaml
# MediaMTX — preview ao vivo (RTSP/WebRTC) p/ dev. Recebe push do recorder e
# reexpõe via RTSP (8554) e WebRTC (8889). Não faz parte do caminho de produção.
rtsp: yes
rtspAddress: :8554
webrtc: yes
webrtcAddress: :8889
paths:
  all_others:
```

- [ ] **Step 2: Adicionar o serviço `preview` ao compose (perfil `dev`)**

Em `docker-compose.yml`, adicione antes da seção `volumes:`:

```yaml
  # ── preview: SÓ em dev. Live view (RTSP/WebRTC) das câmeras via MediaMTX. ──
  # Suba com:  docker compose --profile dev up -d preview
  # No Mac (via Tailscale):  VLC -> rtsp://orwell-nx:8554/cam0  |  WebRTC -> http://orwell-nx:8889/cam0
  preview:
    profiles: ["dev"]
    image: bluenviron/mediamtx:latest
    restart: unless-stopped
    volumes:
      - ./config/mediamtx.yml:/mediamtx.yml:ro
    ports:
      - "8554:8554"
      - "8889:8889"
```

- [ ] **Step 3: Validar a sintaxe do compose**

Run: `docker compose config -q && echo ok`
Expected: `ok` (sem erros de schema). Se `docker` não estiver disponível na máquina de dev,
pule e valide no Jetson.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml config/mediamtx.yml
git commit -m "feat(dev): serviço preview (MediaMTX RTSP/WebRTC) no perfil dev"
```

---

## Task 9: ADRs — novo 0014, supersede 0005, notas em 0003/0012

**Files:**
- Create: `docs/decisions/0014-encoder-configuravel-hw-sw.md`
- Modify: `docs/decisions/0005-encode-h264-software-perfil-reduzido.md`
- Modify: `docs/decisions/0012-orin-nx-caminho-de-escala.md`
- Modify: `docs/decisions/0003-deepstream-plano-de-midia.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: Criar ADR-0014**

Crie `docs/decisions/0014-encoder-configuravel-hw-sw.md`:

```markdown
# ADR-0014 — Encoder selecionável por config (NVENC HW default + x264 SW fallback)

**Status:** Aceito · 2026-06-01 · Supersede [ADR-0005](0005-encode-h264-software-perfil-reduzido.md)

## Contexto
O hardware-alvo do projeto passou a ser a **Jetson Orin NX**, que **possui NVENC** (encoder de
hardware), ao contrário da Orin Nano (ADR-0005). O software deve permanecer **agnóstico ao
módulo** (ADR-0012).

## Decisão
- **Encoder escolhido por configuração** (`capture.codec` + `capture.encoder`):
  - `hw` → `nvv4l2h265enc`/`nvv4l2h264enc` (NVENC); frames seguem em **NVMM** (sem cópia p/ CPU).
  - `sw` → `nvvidconv` + `x264enc` (libx264) como **fallback** (Nano / sem NVENC).
- **Default:** `h265`/`hw`, 1080p@30 (tunável; validar on-device).
- `h265` + `sw` é **rejeitado** na carga da config (inviável em tempo real).

## Consequências
- H.265 por HW vira viável → arquivos ~2× menores, mais retenção; CPU livre para a IA.
- A lógica de seleção vive em `recorder/pipeline.py` (`encoder_chain`), 100% testável.
- ⚠️ Bitrate: NVENC usa **bits/s** (`bitrate`), x264enc usa **kbit/s**. GOP: `iframeinterval`
  (HW) vs `key-int-max` (SW). Validar nomes/props exatos por JetPack/L4T on-device.
```

- [ ] **Step 2: Marcar ADR-0005 como superseded**

Em `docs/decisions/0005-encode-h264-software-perfil-reduzido.md`, troque a linha de status por:

```markdown
**Status:** Superseded por [ADR-0014](0014-encoder-configuravel-hw-sw.md) · 2026-06-01
(o alvo passou a ser a Orin NX, com NVENC). Mantido como histórico do raciocínio para a Orin Nano.
```

- [ ] **Step 3: Atualizar ADR-0012 (NX = alvo primário)**

Em `docs/decisions/0012-orin-nx-caminho-de-escala.md`, troque a linha de status por:

```markdown
**Status:** Aceito · 2026-06-01 — Orin NX é o **alvo primário** do projeto (não mais só "caminho
de escala futuro"). A Nano permanece como fallback de encode por software (ADR-0014).
```

- [ ] **Step 4: Nota no ADR-0003 (DeepStream desde a Fase 1)**

Em `docs/decisions/0003-deepstream-plano-de-midia.md`, adicione ao final do arquivo:

```markdown

## Atualização (2026-06-01)
DeepStream é usado **desde a Fase 1**, mas com `nvinfer`/`nvtracker` **desligados por config**
(`ai.enabled: false`). A costura de inferência fica cabeada (ver `recorder/pipeline.py:inference_stage`)
para a Fase 2 só ligar o modelo, sem reestruturar o pipeline. Ver
[spec 2026-06-01](../superpowers/specs/2026-06-01-orwell-nx-rewrite-design.md).
```

- [ ] **Step 5: Atualizar o índice de ADRs**

Em `docs/decisions/README.md`, adicione a linha do 0014 e marque 0005 como superseded
(siga o formato das demais linhas do arquivo — abra-o para ver o padrão exato e replique).

- [ ] **Step 6: Commit**

```bash
git add docs/decisions/
git commit -m "docs(adr): 0014 encoder configurável; 0005 superseded; 0012 NX primário; 0003 nota DeepStream Fase 1"
```

---

## Task 10: Refatorar docs — hardware, architecture, roadmap, glossary, CLAUDE

**Files:**
- Modify: `docs/hardware.md`
- Modify: `docs/architecture.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/glossary.md`
- Modify: `CLAUDE.md`

> Edições de prosa. Para cada arquivo, abra-o e ajuste os trechos indicados, preservando o tom.

- [ ] **Step 1: hardware.md**

- §1 (BOM): trocar "Compute | NVIDIA **Jetson Orin Nano**" por "Compute | NVIDIA **Jetson Orin NX**
  (primário) — possui NVENC". Adicionar linha de fallback "Orin Nano (pino-compatível) — encode SW".
- §3: trocar o título "⚠️ Restrição crítica: Orin Nano não tem NVENC" por "Encode: NVENC na Orin
  NX (HW); software como fallback (Nano)". Reescrever o corpo: a NX **tem** NVENC → encode HW
  (`nvv4l2h26Xenc`), H.265 viável; a Nano (fallback) usa `x264enc` SW. Manter o benchmark SW como
  referência só do fallback.

- [ ] **Step 2: architecture.md**

- §2 (diagrama de camadas): trocar "HOST (Jetson Orin Nano)" por "HOST (Jetson Orin NX)".
- §3, item **[A]**: trocar "`x264enc` (software, ...)" por "encoder configurável (NVENC HW na NX:
  `nvv4l2h265enc`; `x264enc` SW como fallback) — ver `recorder/pipeline.py`". Adicionar menção ao
  `tee` (gravação + preview opcional) e à costura `inference_stage` (Fase 2).
- §4: na nota sobre GOP/"essencial sem NVENC", ajustar para "essencial para corte barato; na NX o
  encode é HW".

- [ ] **Step 3: roadmap.md**

- Fase 1: trocar "encode H.264 SW (GOP ~1 s)" por "encode **HW H.265** (NVENC, config-driven; SW
  como fallback)". Acrescentar item "[x] preview ao vivo (MediaMTX, perfil dev)".
- "Itens adiados": remover "H.265 — depende de NVENC (Orin NX)" (agora é default). Adicionar à
  Fase 2/3 os itens **WebRTC em produção** e **avaliar NVIDIA Fleet Command vs Rancher**.

- [ ] **Step 4: glossary.md**

Adicionar entradas (no estilo das existentes): **NVENC** (encoder de HW; presente na Orin NX,
ausente na Nano), **`nvv4l2h265enc`/`nvv4l2h264enc`** (encoders HW GStreamer NVIDIA), **WebRTC**
(vídeo ao vivo de baixa latência), **MediaMTX** (servidor RTSP/WebRTC usado no preview de dev).

- [ ] **Step 5: CLAUDE.md**

No bloco "Restrições que NÃO podem ser esquecidas", trocar o primeiro item (⚠️ Orin Nano NÃO tem
NVENC) por: "⚠️ **Alvo é a Orin NX (tem NVENC)** → encode por **hardware** (`nvv4l2h26Xenc`),
H.265 viável. A **Orin Nano (sem NVENC) é fallback** por software (`x264enc`); o encoder é
**selecionável por config** (ver ADR-0014). H.265 software continua inviável."
Atualizar a tabela de componentes/linha do `recorder` se mencionar x264 fixo.

- [ ] **Step 6: Commit**

```bash
git add docs/hardware.md docs/architecture.md docs/roadmap.md docs/glossary.md CLAUDE.md
git commit -m "docs: refletir Orin NX (NVENC HW, encoder config-driven, preview) em hardware/arch/roadmap/glossary/CLAUDE"
```

---

## Task 11: operations.md — seção "dev remoto Mac → Jetson"

**Files:**
- Modify: `docs/operations.md`

- [ ] **Step 1: Adicionar a seção de fluxo de dev**

Em `docs/operations.md`, após a seção "## 1. Acesso remoto — Tailscale", adicione:

```markdown
## 1.1 Fluxo de dev remoto (Mac → Jetson headless)

A Jetson é headless; você a opera 100% do Mac pelo Tailscale. "Ver" tem três naturezas — a regra
de ouro é **nunca renderizar vídeo na Jetson e espelhar a tela (X11/VNC)**; mande os dados de
vídeo para o Mac e renderize lá.

1. **Tailscale** nos dois → Jetson acessível por nome (ex.: `orwell-nx`).
2. **Console/operar:** `ssh orwell@orwell-nx` (Tailscale SSH). Containers: `docker compose up -d
   <serviço>`, `down`, `restart`, `logs -f <serviço>`.
3. **Editar código:** **VS Code / Cursor Remote-SSH** sobre o tailnet — editar como se fosse local,
   terminal integrado, **port-forward automático** (8080 → `localhost:8080` no Mac).
4. **Ver gravado / quase-ao-vivo:** **VLC/Safari** abrindo a HLS (`.m3u8`) ou um clipe da Clip API
   (`http://orwell-nx:8080/clips?...`), pelo tailnet.
5. **Ver câmera ao vivo (bring-up):** subir o serviço de preview —
   `docker compose --profile dev up -d preview` (config `preview.enabled: true`) — e abrir
   **`rtsp://orwell-nx:8554/cam0`** no VLC ou **`http://orwell-nx:8889/cam0`** (WebRTC) no navegador.
6. **Sanity-check rápido:** snapshot JPEG via GStreamer (`num-buffers=1 ! jpegenc`) + `scp`.

Tudo em containers; nada roda no host além do que é kernel/driver (driver GMSL, JetPack, Tailscale).
```

- [ ] **Step 2: Commit**

```bash
git add docs/operations.md
git commit -m "docs(operations): fluxo de dev remoto Mac->Jetson (SSH, Remote-SSH, VLC/HLS, MediaMTX)"
```

---

## Task 12: Verificação final — suíte completa de testes

**Files:** nenhum (validação).

- [ ] **Step 1: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: PASS em todos os testes de `shared/tests`, `services/recorder/tests`,
`services/clip-api/tests`, `services/uploader/tests`, `tests/`. Nenhuma regressão nos módulos
preservados (index, paths, clips, retention, events, storage, clip-api, uploader, indexer).

- [ ] **Step 2: Conferir cobertura do spec (checklist)**

Confirmar manualmente que cada item do §11 (refatoração de docs/ADRs) do spec foi endereçado por
uma task acima e que o encoder config-driven (§5/§7), a costura de IA (§6.3) e o preview (§6.1/§8)
estão implementados.

- [ ] **Step 3: Commit final (se houver ajustes)**

```bash
git add -A && git commit -m "test: suíte completa verde após reescrita Orin NX" || echo "nada a commitar"
```

---

## Pendências on-device (fora do escopo automatizável no Mac)

Registrar em `deploy/provisioning-log.md` ao validar no Jetson:
- Nomes/props exatos de `nvv4l2h265enc`/`nvv4l2h264enc` conforme JetPack/L4T/DeepStream.
- `rtspclientsink` disponível na imagem DeepStream (senão, instalar `gstreamer1.0-plugins-*`).
- Concat fMP4 H.265 pela Clip API (`ffmpeg -c copy`) — validar playback do MP4 resultante.
- Tag correta da imagem DeepStream no `services/recorder/Dockerfile` (ARG `DEEPSTREAM_IMAGE`).
