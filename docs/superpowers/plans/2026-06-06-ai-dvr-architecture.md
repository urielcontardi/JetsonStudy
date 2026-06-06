# AI DVR Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expandir o recorder para um pipeline de 3 branches (DVR arquivo, IA tempo real, event buffer), adicionar EventIndex ao shared, novos endpoints na clip-api e calculador HTML de storage.

**Architecture:** Branch A grava diretamente em bitrate de arquivo (0,5 Mbps, ~20 dias de retenção). Branch B escala os frames para 640×360 e roda TensorRT. Branch C mantém um buffer circular em tmpfs (60s, 8 Mbps) para clips de alta qualidade quando a IA detecta evento.

**Tech Stack:** Python · GStreamer/DeepStream (nvarguscamerasrc, nvv4l2h265enc, nvinfer) · FastAPI · SQLite · pytest

---

## File Map

| Arquivo | Ação |
|---|---|
| `config/orwell.yaml` | Modificar — fps 25, bitrate 500, watermark 85, ai/event_buffer |
| `shared/orwell_shared/config.py` | Modificar — AIConfig novos campos, EventBufferConfig, RetentionConfig.events_dir |
| `shared/orwell_shared/events.py` | Criar — Event dataclass + EventIndex |
| `shared/orwell_shared/clips.py` | Modificar — adicionar extract_event_clip |
| `shared/tests/test_events.py` | Criar — testes EventIndex |
| `shared/tests/test_clips.py` | Modificar — adicionar teste extract_event_clip |
| `services/recorder/recorder/pipeline.py` | Modificar — build_raw_source, dvr_encoder_chain, event_buffer_encoder_chain, ai_scale_chain |
| `services/recorder/recorder/event_handler.py` | Criar — flush_event_buffer, handle_detection |
| `services/recorder/recorder/main.py` | Modificar — _build_camera_bin 3 branches |
| `services/recorder/tests/test_pipeline.py` | Modificar — fix framerate, testes novos builders |
| `services/recorder/tests/test_event_handler.py` | Criar — testes event_handler |
| `services/clip-api/clip_api/main.py` | Modificar — GET /events, GET /events/{id}/clip |
| `services/clip-api/clip_api/settings.py` | Modificar — adicionar events_dir() |
| `services/clip-api/tests/test_clip_api.py` | Modificar — testes novos endpoints |
| `shared/orwell_shared/uploader.py` | Criar — UploaderBackend Protocol |
| `docker-compose.yml` | Modificar — ORWELL_EVENTS_DIR nos serviços |
| `tools/storage-calculator.html` | Criar — calculador HTML interativo |

---

## Task 1: Corrigir bug pré-existente — framerate em build_source_chain

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Modify: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Confirmar o teste falhando**

```bash
pytest services/recorder/tests/test_pipeline.py::test_build_source_chain_hw_h265 -v
```
Expected: FAIL com `AssertionError: assert 'framerate=30/1'`

- [ ] **Step 2: Corrigir build_source_chain em pipeline.py**

Localizar `build_source_chain` (linha ~46) e adicionar `framerate={profile.fps}/1` à caps filter:

```python
def build_source_chain(camera: CameraConfig, profile: CaptureProfile) -> str:
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} sensor-mode=2 ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1 ! "
        f"{encoder_chain(profile)} ! "
        f"{parser_element(profile)}"
    )
```

- [ ] **Step 3: Rodar os testes e confirmar que passam**

```bash
pytest services/recorder/tests/test_pipeline.py -v
```
Expected: todos PASS

- [ ] **Step 4: Commit**

```bash
git add services/recorder/recorder/pipeline.py
git commit -m "fix(recorder): add framerate to nvarguscamerasrc caps filter"
```

---

## Task 2: Novos modelos de config (AIConfig, EventBufferConfig, RetentionConfig)

**Files:**
- Modify: `shared/orwell_shared/config.py`
- Test: `shared/tests/test_config.py`

- [ ] **Step 1: Escrever os testes que vão falhar**

Adicionar ao final de `shared/tests/test_config.py`:

```python
def test_event_buffer_config_defaults():
    from orwell_shared.config import EventBufferConfig
    c = EventBufferConfig()
    assert c.enabled is True
    assert c.buffer_seconds == 60
    assert c.bitrate_kbps == 8000
    assert c.tmpfs_dir == "/dev/shm/orwell"


def test_retention_config_has_events_dir():
    from orwell_shared.config import RetentionConfig
    c = RetentionConfig()
    assert c.events_dir == "/var/lib/orwell/events"


def test_ai_config_new_fields():
    from orwell_shared.config import AIConfig
    c = AIConfig()
    assert c.inference_fps == 8
    assert c.confidence_threshold == 0.6
    assert c.input_width == 640
    assert c.input_height == 360
    assert c.model_path == "/models/detector.engine"


def test_orwell_config_has_event_buffer():
    from orwell_shared.config import OrwellConfig
    c = OrwellConfig()
    assert hasattr(c, "event_buffer")
    assert c.event_buffer.buffer_seconds == 60
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest shared/tests/test_config.py -v -k "event_buffer or events_dir or ai_config_new"
```
Expected: FAIL (ImportError ou AttributeError)

- [ ] **Step 3: Implementar as mudanças em config.py**

Substituir o conteúdo de `shared/orwell_shared/config.py` por:

```python
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class CameraConfig(BaseModel):
    id: str
    argus_sensor_id: int
    name: str | None = None


class CaptureProfile(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "h265"
    encoder: str = "hw"
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


class RetentionConfig(BaseModel):
    data_dir: str = "/var/lib/orwell/data"
    events_dir: str = "/var/lib/orwell/events"
    disk_high_watermark_pct: int = 85


class AIConfig(BaseModel):
    enabled: bool = False
    inference_fps: int = 8
    confidence_threshold: float = 0.6
    input_width: int = 640
    input_height: int = 360
    model_path: str = "/models/detector.engine"


class EventBufferConfig(BaseModel):
    enabled: bool = True
    buffer_seconds: int = 60
    bitrate_kbps: int = 8000
    tmpfs_dir: str = "/dev/shm/orwell"


class PreviewConfig(BaseModel):
    enabled: bool = False
    rtsp_base_url: str = "rtsp://preview:8554"


class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    event_buffer: EventBufferConfig = Field(default_factory=EventBufferConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)


def _apply_env_overrides(data: dict) -> dict:
    for env_key, value in os.environ.items():
        if not env_key.startswith("ORWELL_"):
            continue
        path = env_key[len("ORWELL_"):].lower().split("__")
        cursor = data
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return data


def load_config(path: str | Path) -> OrwellConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    raw = _apply_env_overrides(raw)
    return OrwellConfig.model_validate(raw)
```

- [ ] **Step 4: Rodar todos os testes de config**

```bash
pytest shared/tests/test_config.py -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/config.py shared/tests/test_config.py
git commit -m "feat(config): add EventBufferConfig, update AIConfig and RetentionConfig"
```

---

## Task 3: EventIndex no shared

**Files:**
- Create: `shared/orwell_shared/events.py`
- Create: `shared/tests/test_events.py`

- [ ] **Step 1: Escrever os testes**

Criar `shared/tests/test_events.py`:

```python
import time

import pytest

from orwell_shared.events import Event, EventIndex


@pytest.fixture
def idx(tmp_path):
    return EventIndex(tmp_path / "idx.sqlite")


def _event(**kwargs) -> Event:
    defaults = dict(
        id="evt-1", camera_id="0", t_evento=1000.0,
        label="smoke", confidence=0.85,
    )
    defaults.update(kwargs)
    return Event(**defaults)


def test_add_and_get(idx):
    ev = _event()
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result is not None
    assert result.label == "smoke"
    assert result.confidence == 0.85


def test_get_missing_returns_none(idx):
    assert idx.get("nope") is None


def test_query_by_camera_and_time(idx):
    idx.add_event(_event(id="e1", camera_id="0", t_evento=1000.0))
    idx.add_event(_event(id="e2", camera_id="0", t_evento=2000.0))
    idx.add_event(_event(id="e3", camera_id="1", t_evento=1000.0))

    result = idx.query("0", 900.0, 1500.0)
    assert len(result) == 1
    assert result[0].id == "e1"


def test_query_returns_ordered_by_time(idx):
    idx.add_event(_event(id="e2", t_evento=2000.0))
    idx.add_event(_event(id="e1", t_evento=1000.0))
    result = idx.query("0", 0.0, 9999.0)
    assert [e.id for e in result] == ["e1", "e2"]


def test_bbox_json_roundtrip(idx):
    ev = _event(bbox_json='{"x":0.1,"y":0.2,"w":0.3,"h":0.4}')
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.bbox_json == '{"x":0.1,"y":0.2,"w":0.3,"h":0.4}'


def test_clip_path_and_uploaded_at(idx):
    ev = _event(clip_path="/events/evt-1", uploaded_at=None)
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.clip_path == "/events/evt-1"
    assert result.uploaded_at is None
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest shared/tests/test_events.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar events.py**

Criar `shared/orwell_shared/events.py`:

```python
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Event:
    id: str
    camera_id: str
    t_evento: float
    label: str
    confidence: float
    bbox_json: str | None = None
    clip_path: str | None = None
    uploaded_at: float | None = None
    created_at: float = field(default_factory=time.time)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    camera_id   TEXT NOT NULL,
    t_evento    REAL NOT NULL,
    label       TEXT NOT NULL,
    confidence  REAL NOT NULL,
    bbox_json   TEXT,
    clip_path   TEXT,
    uploaded_at REAL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_cam_time ON events(camera_id, t_evento);
"""


class EventIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_event(self, event: Event) -> None:
        self._conn.execute(
            "INSERT INTO events"
            "(id,camera_id,t_evento,label,confidence,bbox_json,clip_path,uploaded_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (event.id, event.camera_id, event.t_evento, event.label, event.confidence,
             event.bbox_json, event.clip_path, event.uploaded_at, event.created_at),
        )
        self._conn.commit()

    def query(self, camera_id: str, start: float, end: float) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE camera_id=? AND t_evento>=? AND t_evento<=?"
            " ORDER BY t_evento",
            (camera_id, start, end),
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, event_id: str) -> Event | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE id=?", (event_id,)
        ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(r: sqlite3.Row) -> Event:
        return Event(
            id=r["id"], camera_id=r["camera_id"], t_evento=r["t_evento"],
            label=r["label"], confidence=r["confidence"], bbox_json=r["bbox_json"],
            clip_path=r["clip_path"], uploaded_at=r["uploaded_at"],
            created_at=r["created_at"],
        )
```

- [ ] **Step 4: Rodar testes**

```bash
pytest shared/tests/test_events.py -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/events.py shared/tests/test_events.py
git commit -m "feat(shared): add Event dataclass and EventIndex"
```

---

## Task 4: extract_event_clip em clips.py

**Files:**
- Modify: `shared/orwell_shared/clips.py`
- Modify: `shared/tests/test_clips.py`

- [ ] **Step 1: Escrever o teste**

Adicionar ao final de `shared/tests/test_clips.py`:

```python
def test_extract_event_clip_concatenates_buf_files(tmp_path):
    from orwell_shared.clips import extract_event_clip

    clip_dir = tmp_path / "events" / "evt-1"
    clip_dir.mkdir(parents=True)
    # buf-1.m4s é mais recente (mtime maior)
    buf0 = clip_dir / "buf-0.m4s"; buf0.write_bytes(b"OLD")
    buf1 = clip_dir / "buf-1.m4s"; buf1.write_bytes(b"NEW")
    buf1.touch()  # garante mtime > buf0

    out = tmp_path / "event.mp4"
    called_with = []
    def fake_run(cmd, **_):
        called_with.extend(cmd)
        out.write_bytes(b"MP4")
        class R: returncode = 0
        return R()

    result = extract_event_clip(clip_dir, out, runner=fake_run)
    assert result == out
    assert out.read_bytes() == b"MP4"
    # os dois buf files devem aparecer no comando ffmpeg, ordenados por mtime
    concat_idx = called_with.index("-i") + 1
    concat_content = (tmp_path / called_with[concat_idx]).read_text()
    assert "buf-0.m4s" in concat_content
    assert "buf-1.m4s" in concat_content


def test_extract_event_clip_raises_when_no_files(tmp_path):
    from orwell_shared.clips import NoSegments, extract_event_clip
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(NoSegments):
        extract_event_clip(empty_dir, tmp_path / "out.mp4")
```

Adicionar `import pytest` no topo do arquivo se não existir.

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest shared/tests/test_clips.py -v -k "event_clip"
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Adicionar extract_event_clip em clips.py**

Adicionar ao final de `shared/orwell_shared/clips.py`:

```python
def extract_event_clip(
    clip_dir: Path,
    out_path: Path,
    runner: Callable = subprocess.run,
) -> Path:
    buf_files = sorted(Path(clip_dir).glob("buf-*.m4s"), key=lambda f: f.stat().st_mtime)
    if not buf_files:
        raise NoSegments(f"no buf files in {clip_dir}")
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as td:
        listfile = Path(td) / "concat.txt"
        listfile.write_text("\n".join(f"file '{f}'" for f in buf_files) + "\n")
        cmd = build_ffmpeg_cmd(listfile, out_path)
        result = runner(cmd, capture_output=True)
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', b'')!r}")
    return out_path
```

- [ ] **Step 4: Rodar testes**

```bash
pytest shared/tests/test_clips.py -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/clips.py shared/tests/test_clips.py
git commit -m "feat(shared): add extract_event_clip for high-quality event clips"
```

---

## Task 5: Novos builders de pipeline (3 branches)

**Files:**
- Modify: `services/recorder/recorder/pipeline.py`
- Modify: `services/recorder/tests/test_pipeline.py`

- [ ] **Step 1: Escrever os testes**

Adicionar ao final de `services/recorder/tests/test_pipeline.py`:

```python
from recorder.pipeline import (
    ai_scale_chain,
    build_raw_source,
    dvr_encoder_chain,
    event_buffer_encoder_chain,
)


def test_build_raw_source_no_encoder():
    cam = CameraConfig(id="0", argus_sensor_id=1)
    chain = build_raw_source(cam, CaptureProfile(width=1920, height=1080, fps=25))
    assert "nvarguscamerasrc sensor-id=1" in chain
    assert "width=1920,height=1080" in chain
    assert "framerate=25/1" in chain
    assert "nvv4l2h265enc" not in chain
    assert "nvv4l2h264enc" not in chain


def test_dvr_encoder_chain_hw_h265_low_bitrate():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=25, gop_seconds=1.0,
                          bitrate_kbps=500)
    chain = dvr_encoder_chain(prof)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=500000" in chain
    assert "iframeinterval=25" in chain
    assert "h265parse" in chain


def test_dvr_encoder_chain_sw_h264():
    prof = CaptureProfile(codec="h264", encoder="sw", fps=25, gop_seconds=1.0,
                          bitrate_kbps=500)
    chain = dvr_encoder_chain(prof)
    assert "x264enc" in chain
    assert "bitrate=500" in chain
    assert "key-int-max=25" in chain


def test_event_buffer_encoder_chain_uses_high_bitrate():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=25, gop_seconds=1.0,
                          bitrate_kbps=500)
    chain = event_buffer_encoder_chain(prof, buf_bitrate_kbps=8000)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=8000000" in chain
    assert "iframeinterval=25" in chain
    # deve ser independente do bitrate do DVR (500 kbps)
    assert "bitrate=500000" not in chain


def test_ai_scale_chain_sets_resolution_and_fps():
    chain = ai_scale_chain(input_width=640, input_height=360, inference_fps=8)
    assert "width=640" in chain
    assert "height=360" in chain
    assert "framerate=8/1" in chain
    assert "nvvideoconvert" in chain
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest services/recorder/tests/test_pipeline.py -v -k "raw_source or dvr_encoder or event_buffer_encoder or ai_scale"
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Adicionar as funções em pipeline.py**

Adicionar ao final de `services/recorder/recorder/pipeline.py`:

```python
def build_raw_source(camera: CameraConfig, profile: CaptureProfile) -> str:
    """Cadeia de captura bruta (pré-tee). Emite frames NVMM sem encode."""
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} sensor-mode=2 ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1"
    )


def dvr_encoder_chain(profile: CaptureProfile) -> str:
    """Branch A: nvvideoconvert + encoder + parser para o NVMe (bitrate de arquivo)."""
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return (
            f"nvvideoconvert ! "
            f"{elem} bitrate={profile.bitrate_kbps * 1000} iframeinterval={kf} ! "
            f"{parser_element(profile)}"
        )
    return (
        "nvvideoconvert ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={profile.bitrate_kbps} key-int-max={kf} ! h264parse"
    )


def event_buffer_encoder_chain(profile: CaptureProfile, buf_bitrate_kbps: int) -> str:
    """Branch C: nvvideoconvert + encoder de alta qualidade para o tmpfs."""
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return (
            f"nvvideoconvert ! "
            f"{elem} bitrate={buf_bitrate_kbps * 1000} iframeinterval={kf} ! "
            f"{parser_element(profile)}"
        )
    return (
        "nvvideoconvert ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={buf_bitrate_kbps} key-int-max={kf} ! h264parse"
    )


def ai_scale_chain(input_width: int, input_height: int, inference_fps: int) -> str:
    """Branch B: nvvideoconvert scale + videorate para inferência TensorRT."""
    return (
        f"nvvideoconvert ! "
        f"video/x-raw(memory:NVMM),width={input_width},height={input_height} ! "
        f"videorate ! video/x-raw,framerate={inference_fps}/1"
    )
```

- [ ] **Step 4: Rodar todos os testes do recorder**

```bash
pytest services/recorder/tests/ -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/pipeline.py services/recorder/tests/test_pipeline.py
git commit -m "feat(recorder/pipeline): add 3-branch builders — raw source, dvr, event buffer, ai scale"
```

---

## Task 6: Event handler (flush + persist)

**Files:**
- Create: `services/recorder/recorder/event_handler.py`
- Create: `services/recorder/tests/test_event_handler.py`

- [ ] **Step 1: Escrever os testes**

Criar `services/recorder/tests/test_event_handler.py`:

```python
import pytest
from orwell_shared.events import EventIndex
from recorder.event_handler import flush_event_buffer, handle_detection


@pytest.fixture
def setup(tmp_path):
    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)
    (buf_dir / "buf-0.m4s").write_bytes(b"DATA0")
    (buf_dir / "buf-1.m4s").write_bytes(b"DATA1")
    events_dir = tmp_path / "events"
    idx = EventIndex(tmp_path / "idx.sqlite")
    return tmpfs, events_dir, idx


def test_flush_copies_both_buf_files(setup):
    tmpfs, events_dir, _ = setup
    result = flush_event_buffer(str(tmpfs), str(events_dir), "evt-abc", "cam0")
    assert len(result) == 2
    assert all(f.exists() for f in result)
    assert all(f.parent.name == "evt-abc" for f in result)


def test_flush_skips_missing_files(tmp_path):
    tmpfs = tmp_path / "shm"
    buf_dir = tmpfs / "cam0"
    buf_dir.mkdir(parents=True)
    (buf_dir / "buf-0.m4s").write_bytes(b"x")
    # buf-1.m4s não existe

    result = flush_event_buffer(str(tmpfs), str(tmp_path / "events"), "evt-1", "cam0")
    assert len(result) == 1


def test_flush_empty_buf_returns_empty(tmp_path):
    tmpfs = tmp_path / "shm"
    (tmpfs / "cam0").mkdir(parents=True)
    result = flush_event_buffer(str(tmpfs), str(tmp_path / "events"), "evt-0", "cam0")
    assert result == []


def test_handle_detection_persists_event(setup):
    tmpfs, events_dir, idx = setup
    event_id = handle_detection(
        camera_id="cam0",
        t_evento=1000.0,
        label="smoke",
        confidence=0.9,
        bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
    )
    ev = idx.get(event_id)
    assert ev is not None
    assert ev.label == "smoke"
    assert ev.camera_id == "cam0"
    assert abs(ev.t_evento - 1000.0) < 0.001
    assert ev.confidence == 0.9
    assert ev.clip_path is not None
    import json
    bbox = json.loads(ev.bbox_json)
    assert bbox["x"] == pytest.approx(0.1)


def test_handle_detection_no_bbox(setup):
    tmpfs, events_dir, idx = setup
    event_id = handle_detection(
        camera_id="cam0", t_evento=2000.0, label="fault",
        confidence=0.7, bbox=None,
        tmpfs_dir=str(tmpfs), events_dir=str(events_dir),
        event_index=idx,
    )
    ev = idx.get(event_id)
    assert ev.bbox_json is None


def test_handle_detection_returns_unique_ids(setup):
    tmpfs, events_dir, idx = setup
    id1 = handle_detection("cam0", 1000.0, "smoke", 0.8, None,
                            str(tmpfs), str(events_dir), idx)
    id2 = handle_detection("cam0", 2000.0, "smoke", 0.8, None,
                            str(tmpfs), str(events_dir), idx)
    assert id1 != id2
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest services/recorder/tests/test_event_handler.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar event_handler.py**

Criar `services/recorder/recorder/event_handler.py`:

```python
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from orwell_shared.events import Event, EventIndex


def flush_event_buffer(
    tmpfs_dir: str,
    events_dir: str,
    event_id: str,
    camera_id: str,
) -> list[Path]:
    """Copia buf-0.m4s e buf-1.m4s do tmpfs para /events/<event_id>/."""
    buf_dir = Path(tmpfs_dir) / camera_id
    out_dir = Path(events_dir) / event_id
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for i in range(2):
        src = buf_dir / f"buf-{i}.m4s"
        if src.exists():
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)
    return copied


def handle_detection(
    camera_id: str,
    t_evento: float,
    label: str,
    confidence: float,
    bbox: dict | None,
    tmpfs_dir: str,
    events_dir: str,
    event_index: EventIndex,
) -> str:
    """Persiste evento no índice e faz flush do event buffer. Retorna o event_id."""
    event_id = str(uuid.uuid4())
    clip_files = flush_event_buffer(tmpfs_dir, events_dir, event_id, camera_id)
    clip_path = str(clip_files[0].parent) if clip_files else None
    event_index.add_event(Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=t_evento,
        label=label,
        confidence=confidence,
        bbox_json=json.dumps(bbox) if bbox is not None else None,
        clip_path=clip_path,
    ))
    return event_id
```

- [ ] **Step 4: Rodar testes**

```bash
pytest services/recorder/tests/test_event_handler.py -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/event_handler.py services/recorder/tests/test_event_handler.py
git commit -m "feat(recorder): add event_handler — flush_event_buffer + handle_detection"
```

---

## Task 7: Pipeline 3 branches em main.py

**Files:**
- Modify: `services/recorder/recorder/main.py`

> ⚠️ Este arquivo usa `gi`/GStreamer (só disponível no Jetson). Sem testes unitários — validar on-device. O objetivo é estruturar o código corretamente.

- [ ] **Step 1: Substituir `_build_camera_bin` pelo novo pipeline de 3 branches**

Substituir a função `_build_camera_bin` e adicionar o callback do buffer:

```python
def _make_buf_format_location_cb(tmpfs_dir: str, camera_id: str):
    """Callback do splitmuxsink do event buffer: alterna entre buf-0.m4s e buf-1.m4s."""
    from pathlib import Path
    buf_dir = Path(tmpfs_dir) / camera_id
    buf_dir.mkdir(parents=True, exist_ok=True)
    count = [0]

    def _cb(_splitmux, _fragment_id, *_args):
        idx = count[0] % 2
        count[0] += 1
        return str(buf_dir / f"buf-{idx}.m4s")
    return _cb


def _build_camera_bin(Gst, camera, profile, ai_cfg, event_buf_cfg, data_dir):
    """Pipeline de 3 branches para uma câmera.

    Branch A — DVR: encode baixo bitrate → NVMe.
    Branch B — IA: scale 640×360 → TensorRT (só se ai_cfg.enabled).
    Branch C — Event buffer: encode alto bitrate → tmpfs circular (só se event_buf_cfg.enabled).
    """
    from .pipeline import (
        ai_scale_chain,
        build_raw_source,
        dvr_encoder_chain,
        event_buffer_encoder_chain,
        max_size_time_ns,
    )

    dvr_sink = (
        "splitmuxsink name=dvr_sink "
        f"max-size-time={max_size_time_ns(profile)} "
        'muxer-factory=mp4mux '
        'muxer-properties="properties,fragment-duration=1000,faststart=true"'
    )

    desc = build_raw_source(camera, profile) + " ! tee name=t "
    desc += f"t. ! queue ! {dvr_encoder_chain(profile)} ! {dvr_sink} "

    if event_buf_cfg.enabled:
        buf_seg_ns = int((event_buf_cfg.buffer_seconds / 2) * 1_000_000_000)
        buf_sink = (
            "splitmuxsink name=buf_sink "
            f"max-size-time={buf_seg_ns} "
            'muxer-factory=mp4mux '
            'muxer-properties="properties,fragment-duration=1000,faststart=true"'
        )
        desc += (
            f"t. ! queue ! "
            f"{event_buffer_encoder_chain(profile, event_buf_cfg.bitrate_kbps)} ! "
            f"{buf_sink} "
        )

    if ai_cfg.enabled:
        desc += (
            f"t. ! queue ! "
            f"{ai_scale_chain(ai_cfg.input_width, ai_cfg.input_height, ai_cfg.inference_fps)} ! "
            f"nvinfer config-file-path={ai_cfg.model_path} name=ai_infer "
        )

    pipeline = Gst.parse_launch(desc)

    dvr = pipeline.get_by_name("dvr_sink")
    dvr.connect("format-location-full", _make_format_location_cb(data_dir, camera.id))

    if event_buf_cfg.enabled:
        buf = pipeline.get_by_name("buf_sink")
        buf.connect("format-location-full",
                    _make_buf_format_location_cb(event_buf_cfg.tmpfs_dir, camera.id))

    return pipeline
```

- [ ] **Step 2: Atualizar a chamada de `_build_camera_bin` em `main()`**

Localizar a linha onde `_build_camera_bin` é chamado (linha ~101) e substituir:

```python
    pipelines = [
        _build_camera_bin(
            Gst, cam, config.capture,
            config.ai, config.event_buffer,
            config.retention.data_dir,
        )
        for cam in available
    ]
```

- [ ] **Step 3: Adicionar `EventIndex` e wiring do event handler em `main()`**

Adicionar após a criação do `index` (linha ~89) e antes do loop de pipelines:

```python
    from orwell_shared.events import EventIndex
    from .event_handler import handle_detection

    event_index = EventIndex(os.environ.get(
        "ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite"))
```

Adicionar stub de probe para quando `ai.enabled = True` (após criar os pipelines):

```python
    # Probe de IA: conecta callback nvinfer → handle_detection por câmera
    # Ativado apenas quando ai.enabled = True e pyds disponível
    if config.ai.enabled:
        try:
            import pyds
            for cam, pipeline in zip(available, pipelines):
                ai_infer = pipeline.get_by_name("ai_infer")
                if ai_infer:
                    sink_pad = ai_infer.get_static_pad("sink")
                    def _make_probe(cam_id):
                        def _probe(pad, info):
                            batch = pyds.gst_buffer_get_nvds_batch_meta(
                                info.get_buffer().__hash__())
                            for frame in pyds.NvDsFrameMetaList(batch.frame_meta_list):
                                for obj in pyds.NvDsObjectMetaList(frame.obj_meta_list):
                                    if obj.confidence >= config.ai.confidence_threshold:
                                        import time
                                        handle_detection(
                                            camera_id=cam_id,
                                            t_evento=time.time(),
                                            label=obj.obj_label,
                                            confidence=float(obj.confidence),
                                            bbox={
                                                "x": obj.rect_params.left / config.capture.width,
                                                "y": obj.rect_params.top / config.capture.height,
                                                "w": obj.rect_params.width / config.capture.width,
                                                "h": obj.rect_params.height / config.capture.height,
                                            },
                                            tmpfs_dir=config.event_buffer.tmpfs_dir,
                                            events_dir=config.retention.events_dir,
                                            event_index=event_index,
                                        )
                            return Gst.PadProbeReturn.OK
                        return _probe
                    sink_pad.add_probe(Gst.PadProbeType.BUFFER, _make_probe(cam.id))
        except ImportError:
            print("recorder: pyds não disponível — probe de IA desativado", flush=True)
```

- [ ] **Step 4: Rodar todos os testes (pipeline, indexer, event_handler)**

```bash
pytest services/recorder/tests/ -v
```
Expected: todos PASS (main.py não tem testes — runtime only)

- [ ] **Step 5: Commit**

```bash
git add services/recorder/recorder/main.py
git commit -m "feat(recorder/main): 3-branch pipeline — DVR, event buffer, AI inference"
```

---

## Task 8: clip-api — endpoints /events

**Files:**
- Modify: `services/clip-api/clip_api/settings.py`
- Modify: `services/clip-api/clip_api/main.py`
- Modify: `services/clip-api/tests/test_clip_api.py`

- [ ] **Step 1: Escrever os testes**

Adicionar ao final de `services/clip-api/tests/test_clip_api.py`:

```python
def _build_client_with_events(tmp_path, monkeypatch):
    from orwell_shared.events import Event, EventIndex

    idx_path = tmp_path / "idx.sqlite"
    ev_idx = EventIndex(idx_path)
    event_id = "test-event-1"
    clip_dir = tmp_path / "events" / event_id
    clip_dir.mkdir(parents=True)
    (clip_dir / "buf-0.m4s").write_bytes(b"BUF0")
    (clip_dir / "buf-1.m4s").write_bytes(b"BUF1")
    ev_idx.add_event(Event(
        id=event_id, camera_id="0", t_evento=1000.0,
        label="smoke", confidence=0.9,
        clip_path=str(clip_dir),
    ))

    monkeypatch.setenv("ORWELL_INDEX_DB", str(idx_path))
    monkeypatch.setenv("ORWELL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORWELL_EVENTS_DIR", str(tmp_path / "events"))

    from orwell_shared.clips import NoSegments
    def fake_extract(index, camera, start, end, out_path, init_path=None, runner=None):
        if not index.query(camera, start, end):
            raise NoSegments(f"camera={camera}")
        Path(out_path).write_bytes(b"CLIP"); return Path(out_path)

    def fake_event_extract(clip_dir, out_path, runner=None):
        Path(out_path).write_bytes(b"EVENTCLIP"); return Path(out_path)

    from clip_api.main import create_app
    app = create_app(extract_fn=fake_extract, extract_event_fn=fake_event_extract)
    return TestClient(app)


def test_get_events_returns_list(tmp_path, monkeypatch):
    c = _build_client_with_events(tmp_path, monkeypatch)
    r = c.get("/events", params={
        "camera": "0",
        "start": "1970-01-01T00:16:39Z",   # 999s
        "end":   "1970-01-01T00:16:42Z",   # 1002s
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["label"] == "smoke"
    assert data[0]["confidence"] == pytest.approx(0.9)
    assert data[0]["clip_available"] is True


def test_get_events_empty_range(tmp_path, monkeypatch):
    c = _build_client_with_events(tmp_path, monkeypatch)
    r = c.get("/events", params={
        "camera": "0",
        "start": "2000-01-01T00:00:00Z",
        "end":   "2000-01-01T00:00:05Z",
    })
    assert r.status_code == 200
    assert r.json() == []


def test_get_event_clip_returns_video(tmp_path, monkeypatch):
    c = _build_client_with_events(tmp_path, monkeypatch)
    r = c.get("/events/test-event-1/clip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.content == b"EVENTCLIP"


def test_get_event_clip_not_found(tmp_path, monkeypatch):
    c = _build_client_with_events(tmp_path, monkeypatch)
    r = c.get("/events/nonexistent/clip")
    assert r.status_code == 404
```

Adicionar `import pytest` ao topo do arquivo `test_clip_api.py` se ainda não existir.

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest services/clip-api/tests/test_clip_api.py -v -k "events"
```
Expected: FAIL

- [ ] **Step 3: Adicionar events_dir() em settings.py**

```python
def events_dir() -> str:
    return os.environ.get("ORWELL_EVENTS_DIR", "/var/lib/orwell/events")
```

- [ ] **Step 4: Substituir o conteúdo completo de main.py**

```python
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from orwell_shared.clips import NoSegments, extract_clip, extract_event_clip
from orwell_shared.events import EventIndex
from orwell_shared.index import SegmentIndex

from .settings import data_dir, events_dir, index_db_path


def _to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def create_app(extract_fn=extract_clip, extract_event_fn=extract_event_clip) -> FastAPI:
    app = FastAPI(title="Orwell Clip API")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    index = SegmentIndex(index_db_path())
    event_index = EventIndex(index_db_path())
    ddir = data_dir()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/cameras")
    def cameras():
        return index.cameras()

    @app.get("/segments")
    def segments(camera: str, start: str, end: str):
        segs = index.query(camera, _to_epoch(start), _to_epoch(end))
        return [s.path for s in segs]

    @app.get("/range")
    def range_endpoint(camera: str = Query(...)):
        from datetime import datetime, timezone
        oldest = index.oldest(camera)
        newest_row = index._conn.execute(
            "SELECT * FROM segments WHERE camera_id=? ORDER BY t_end DESC LIMIT 1",
            (camera,)
        ).fetchone()
        newest = index._row(newest_row) if newest_row else None

        def fmt(ts: float | None) -> str | None:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "camera": camera,
            "first": fmt(oldest.t_start) if oldest else None,
            "last":  fmt(newest.t_end)   if newest else None,
        }

    @app.get("/clips")
    def clips(camera: str = Query(...), start: str = Query(...), end: str = Query(...)):
        s, e = _to_epoch(start), _to_epoch(end)
        out = Path(tempfile.gettempdir()) / f"clip-{camera}-{int(s)}-{int(e)}.mp4"
        try:
            extract_fn(index, camera, s, e, out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="no segments for window")
        return FileResponse(str(out), media_type="video/mp4", filename=out.name)

    @app.get("/events")
    def events_list(
        camera: str = Query(...),
        start: str = Query(...),
        end: str = Query(...),
    ):
        s, e = _to_epoch(start), _to_epoch(end)
        evts = event_index.query(camera, s, e)
        return [
            {
                "id": ev.id,
                "camera_id": ev.camera_id,
                "t_evento": ev.t_evento,
                "label": ev.label,
                "confidence": ev.confidence,
                "clip_available": ev.clip_path is not None,
            }
            for ev in evts
        ]

    @app.get("/events/{event_id}/clip")
    def event_clip(event_id: str):
        ev = event_index.get(event_id)
        if ev is None or ev.clip_path is None:
            raise HTTPException(status_code=404, detail="event clip not found")
        out = Path(tempfile.gettempdir()) / f"event-{event_id}.mp4"
        try:
            extract_event_fn(Path(ev.clip_path), out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="clip files not found")
        return FileResponse(str(out), media_type="video/mp4", filename=f"event-{event_id}.mp4")

    return app


app = create_app()
```

- [ ] **Step 5: Rodar todos os testes da clip-api**

```bash
pytest services/clip-api/tests/ -v
```
Expected: todos PASS

- [ ] **Step 6: Commit**

```bash
git add services/clip-api/clip_api/settings.py services/clip-api/clip_api/main.py \
        services/clip-api/tests/test_clip_api.py
git commit -m "feat(clip-api): add GET /events and GET /events/{id}/clip endpoints"
```

---

## Task 9: UploaderBackend Protocol + config/orwell.yaml + docker-compose

**Files:**
- Create: `shared/orwell_shared/uploader.py`
- Modify: `config/orwell.yaml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Criar uploader.py**

Criar `shared/orwell_shared/uploader.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class UploaderBackend(Protocol):
    async def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        """Envia o clip do evento para a nuvem. Retorna a URI do clip."""
        ...
```

- [ ] **Step 2: Atualizar config/orwell.yaml**

Substituir o conteúdo completo de `config/orwell.yaml`:

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
  fps: 25
  codec: h265
  encoder: hw
  gop_seconds: 1.0
  segment_seconds: 4.0
  bitrate_kbps: 500        # arquivo direto, ~20 dias de retenção

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
  bitrate_kbps: 8000
  tmpfs_dir: /dev/shm/orwell

retention:
  data_dir: /var/lib/orwell/data
  events_dir: /var/lib/orwell/events
  disk_high_watermark_pct: 85
```

- [ ] **Step 3: Atualizar docker-compose.yml**

Adicionar `ORWELL_EVENTS_DIR` e montar o volume de eventos nos serviços `clip-api` e `recorder`:

No serviço `clip-api`, adicionar ao `environment` e `volumes`:
```yaml
  clip-api:
    environment:
      ORWELL_INDEX_DB: /data/index.sqlite
      ORWELL_DATA_DIR: /data
      ORWELL_EVENTS_DIR: /events
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
      - ${ORWELL_EVENTS_DIR:-./events}:/events
```

No serviço `recorder`, adicionar ao `environment` e `volumes`:
```yaml
  recorder:
    environment:
      ORWELL_CONFIG: /app/config/orwell.yaml
      ORWELL_INDEX_DB: /data/index.sqlite
      ORWELL_RETENTION__DATA_DIR: /data
      ORWELL_RETENTION__EVENTS_DIR: /events
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
      - ${ORWELL_EVENTS_DIR:-./events}:/events
      - ./config:/app/config:ro
      - /tmp/argus_socket:/tmp/argus_socket
      - /dev/shm:/dev/shm          # tmpfs compartilhado host↔container
```

- [ ] **Step 4: Rodar todos os testes para confirmar que nada quebrou**

```bash
pytest -v
```
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/uploader.py config/orwell.yaml docker-compose.yml
git commit -m "feat: UploaderBackend Protocol, update orwell.yaml and docker-compose for events"
```

---

## Task 10: HTML Storage Calculator

**Files:**
- Create: `tools/storage-calculator.html`

- [ ] **Step 1: Criar o calculador**

Criar `tools/storage-calculator.html`:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Orwell — Storage Calculator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; padding: 32px 16px; }
  h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: #8b949e; font-size: 0.85rem; margin-bottom: 32px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; max-width: 900px; margin: 0 auto; }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px; }
  .card h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #8b949e; margin-bottom: 16px; }
  label { display: block; font-size: 0.82rem; color: #c9d1d9; margin-bottom: 12px; }
  .row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .row span { font-size: 0.82rem; color: #c9d1d9; }
  .val { font-weight: 600; color: #58a6ff; min-width: 64px; text-align: right; }
  input[type=range] { width: 100%; accent-color: #58a6ff; margin: 4px 0 8px; }
  input[type=number] { background: #21262d; border: 1px solid #30363d; border-radius: 6px; color: #e6edf3; padding: 4px 8px; width: 80px; font-size: 0.85rem; }
  .toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .toggle input { accent-color: #3fb950; width: 16px; height: 16px; }
  .results { max-width: 900px; margin: 24px auto 0; }
  .result-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px; }
  .result-card h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #8b949e; margin-bottom: 16px; }
  .big { font-size: 2.8rem; font-weight: 700; color: #3fb950; }
  .big-unit { font-size: 1rem; color: #8b949e; margin-left: 4px; }
  .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 0.85rem; }
  .stat-row:last-child { border: none; }
  .stat-label { color: #8b949e; }
  .stat-val { color: #e6edf3; font-weight: 500; }
  .warn { color: #f0883e; font-size: 0.8rem; margin-top: 8px; }
  .good { color: #3fb950; }
  .med  { color: #d29922; }
  .bad  { color: #f85149; }
  hr { border: none; border-top: 1px solid #21262d; margin: 20px 0; }
  .section-title { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #8b949e; margin-bottom: 8px; }
</style>
</head>
<body>
<div style="max-width:900px;margin:0 auto">
  <h1>Orwell Storage Calculator</h1>
  <p class="subtitle">Calcule o tempo de retenção de vídeo para diferentes configurações.</p>
</div>

<div class="grid">
  <!-- Hardware -->
  <div class="card">
    <h2>Hardware</h2>
    <div class="row"><span>NVMe (GB)</span><span class="val" id="v-nvme">256</span></div>
    <input type="range" id="nvme" min="64" max="2048" step="64" value="256">
    <div class="row"><span>Câmeras</span><span class="val" id="v-cams">2</span></div>
    <input type="range" id="cams" min="1" max="8" step="1" value="2">
    <div class="row"><span>Watermark disco (%)</span><span class="val" id="v-wm">85</span></div>
    <input type="range" id="wm" min="50" max="95" step="5" value="85">
  </div>

  <!-- DVR Stream (Branch A) -->
  <div class="card">
    <h2>DVR — Branch A</h2>
    <div class="row"><span>Bitrate por câmera (Mbps)</span><span class="val" id="v-dvr-br">0.5</span></div>
    <input type="range" id="dvr-br" min="0.25" max="8" step="0.25" value="0.5">
    <div class="row"><span>FPS</span><span class="val" id="v-dvr-fps">25</span></div>
    <input type="range" id="dvr-fps" min="5" max="60" step="5" value="25">
    <p class="warn" id="dvr-quality-note"></p>
  </div>

  <!-- Event Buffer (Branch C) -->
  <div class="card">
    <h2>Event Buffer — Branch C</h2>
    <label class="toggle">
      <input type="checkbox" id="buf-enabled" checked>
      Habilitado
    </label>
    <div class="row"><span>Buffer (segundos)</span><span class="val" id="v-buf-s">60</span></div>
    <input type="range" id="buf-s" min="10" max="300" step="10" value="60">
    <div class="row"><span>Bitrate por câmera (Mbps)</span><span class="val" id="v-buf-br">8</span></div>
    <input type="range" id="buf-br" min="2" max="20" step="1" value="8">
    <div class="row"><span>Eventos/dia estimados</span><span class="val" id="v-evts">5</span></div>
    <input type="range" id="evts" min="0" max="100" step="1" value="5">
  </div>

  <!-- AI Stream (Branch B) -->
  <div class="card">
    <h2>IA — Branch B</h2>
    <label class="toggle">
      <input type="checkbox" id="ai-enabled">
      Habilitado (apenas informativo — sem custo de storage)
    </label>
    <div class="row"><span>Resolução inferência</span>
      <select id="ai-res" style="background:#21262d;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:3px 6px;font-size:0.82rem">
        <option value="416x416">416×416</option>
        <option value="640x360" selected>640×360</option>
        <option value="640x640">640×640</option>
        <option value="1280x720">1280×720</option>
      </select>
    </div>
    <div class="row"><span>FPS inferência</span><span class="val" id="v-ai-fps">8</span></div>
    <input type="range" id="ai-fps" min="1" max="30" step="1" value="8">
    <p style="font-size:0.75rem;color:#8b949e;margin-top:8px">Branch B não grava em disco — sem custo de storage. RAM usada pelo event buffer apenas.</p>
  </div>
</div>

<!-- Results -->
<div class="results">
  <div class="result-card">
    <h2>Resultado</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px">
      <div>
        <div class="section-title">Retenção DVR</div>
        <div><span class="big" id="r-days">--</span><span class="big-unit" id="r-days-unit">dias</span></div>
        <div style="font-size:0.8rem;color:#8b949e;margin-top:4px" id="r-hours-also"></div>
      </div>
      <div>
        <div class="section-title">Consumo disco</div>
        <div><span class="big" id="r-gbh" style="font-size:1.8rem">--</span><span class="big-unit">GB/h</span></div>
        <div style="font-size:0.8rem;color:#8b949e;margin-top:4px" id="r-mbps-total"></div>
      </div>
      <div>
        <div class="section-title">RAM (event buffer)</div>
        <div><span class="big" id="r-ram" style="font-size:1.8rem">--</span><span class="big-unit">MB</span></div>
        <div style="font-size:0.8rem;color:#8b949e;margin-top:4px" id="r-ram-note"></div>
      </div>
    </div>

    <hr>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <div class="section-title">Breakdown de storage</div>
        <div class="stat-row"><span class="stat-label">NVMe utilizável</span><span class="stat-val" id="r-usable">--</span></div>
        <div class="stat-row"><span class="stat-label">DVR (GB/h)</span><span class="stat-val" id="r-dvr-rate">--</span></div>
        <div class="stat-row"><span class="stat-label">Event clips (GB/dia)</span><span class="stat-val" id="r-evts-rate">--</span></div>
        <div class="stat-row"><span class="stat-label">Disco p/ DVR efetivo</span><span class="stat-val" id="r-dvr-effective">--</span></div>
      </div>
      <div>
        <div class="section-title">Comparação</div>
        <div class="stat-row"><span class="stat-label">Config original (8 Mbps, 60fps, 50%)</span><span class="stat-val bad">~18h</span></div>
        <div class="stat-row"><span class="stat-label">Padrão comercial (4 Mbps, 25fps)</span><span class="stat-val med">~2,5 dias</span></div>
        <div class="stat-row"><span class="stat-label">Esta config</span><span class="stat-val" id="r-compare">--</span></div>
      </div>
    </div>
  </div>
</div>

<script>
function v(id) { return document.getElementById(id); }

function fmt(hours) {
  if (hours < 2) return { val: Math.round(hours * 60), unit: "min" };
  if (hours < 48) return { val: hours.toFixed(1), unit: "horas" };
  return { val: (hours / 24).toFixed(1), unit: "dias" };
}

function qualityNote(brMbps, fps) {
  const score = brMbps * (fps / 25);
  if (score < 0.3) return { cls: "bad", msg: "⚠️ Muito baixo — difícil identificar eventos no DVR" };
  if (score < 1.0) return { cls: "med", msg: "⚡ Baixo — suficiente para confirmar que algo ocorreu" };
  if (score < 4.0) return { cls: "good", msg: "✅ Padrão comercial — revisão adequada" };
  return { cls: "good", msg: "✅ Alta qualidade" };
}

function calc() {
  const nvme    = +v("nvme").value;
  const cams    = +v("cams").value;
  const wm      = +v("wm").value / 100;
  const dvrBr   = +v("dvr-br").value;
  const dvrFps  = +v("dvr-fps").value;
  const bufOn   = v("buf-enabled").checked;
  const bufS    = +v("buf-s").value;
  const bufBr   = +v("buf-br").value;
  const evtsDay = +v("evts").value;

  // Disco utilizável
  const usableGB = nvme * wm;

  // DVR rate
  const dvrTotalMbps = dvrBr * cams;
  const dvrGBH = dvrTotalMbps * 3600 / 8 / 1024;

  // Event clips storage (por dia)
  const clipSizeMB = bufOn ? (bufBr * cams * bufS / 8) : 0; // MB por evento
  const evtGBDay = (clipSizeMB * evtsDay) / 1024;

  // Disco efetivo para DVR (subtrai eventos)
  const dvrEffectiveGB = Math.max(0, usableGB - evtGBDay * 30); // reserva 30 dias de eventos

  // Retenção
  const retHours = dvrEffectiveGB / dvrGBH;

  // RAM event buffer
  const ramMB = bufOn ? (bufBr * cams * bufS / 8) : 0;

  // Render
  const r = fmt(retHours);
  v("r-days").textContent = r.val;
  v("r-days-unit").textContent = r.unit;
  if (r.unit === "dias") {
    v("r-hours-also").textContent = `≈ ${Math.round(retHours)}h`;
  } else {
    v("r-hours-also").textContent = "";
  }

  v("r-gbh").textContent = dvrGBH.toFixed(2);
  v("r-mbps-total").textContent = `${dvrTotalMbps.toFixed(2)} Mbps total`;

  v("r-ram").textContent = ramMB < 1 ? "0" : (ramMB > 1024 ? (ramMB/1024).toFixed(1) + " GB" : Math.round(ramMB));
  v("r-ram-note").textContent = bufOn ? `${bufS}s × ${cams} câm × ${bufBr} Mbps` : "desabilitado";

  v("r-usable").textContent = `${usableGB.toFixed(0)} GB (${Math.round(wm*100)}% de ${nvme} GB)`;
  v("r-dvr-rate").textContent = `${dvrGBH.toFixed(2)} GB/h`;
  v("r-evts-rate").textContent = bufOn
    ? `${evtGBDay.toFixed(2)} GB/dia (${evtsDay} × ${clipSizeMB.toFixed(0)} MB)`
    : "0 GB/dia (buffer desabilitado)";
  v("r-dvr-effective").textContent = `${dvrEffectiveGB.toFixed(0)} GB`;

  const retDays = retHours / 24;
  const compareEl = v("r-compare");
  compareEl.textContent = r.unit === "dias" ? `~${r.val} dias` : `~${r.val} ${r.unit}`;
  compareEl.className = "stat-val " + (retDays > 7 ? "good" : retDays > 2 ? "med" : "bad");

  // Quality note
  const q = qualityNote(dvrBr, dvrFps);
  const note = v("dvr-quality-note");
  note.textContent = q.msg;
  note.className = q.cls;

  // Update display values
  v("v-nvme").textContent = nvme;
  v("v-cams").textContent = cams;
  v("v-wm").textContent = Math.round(wm * 100);
  v("v-dvr-br").textContent = dvrBr;
  v("v-dvr-fps").textContent = dvrFps;
  v("v-buf-s").textContent = bufS;
  v("v-buf-br").textContent = bufBr;
  v("v-evts").textContent = evtsDay;
  v("v-ai-fps").textContent = v("ai-fps").value;
}

["nvme","cams","wm","dvr-br","dvr-fps","buf-s","buf-br","evts","ai-fps"].forEach(id => {
  v(id).addEventListener("input", calc);
});
["buf-enabled","ai-enabled"].forEach(id => {
  v(id).addEventListener("change", calc);
});

calc();
</script>
</body>
</html>
```

- [ ] **Step 2: Verificar no browser**

```bash
open tools/storage-calculator.html
```

Confirmar que os sliders respondem e os valores calculam corretamente.

- [ ] **Step 3: Commit**

```bash
git add tools/storage-calculator.html
git commit -m "feat(tools): interactive storage calculator HTML"
```

---

## Task 11: Suite completa + smoke test

- [ ] **Step 1: Rodar a suite completa**

```bash
pytest -v
```
Expected: todos PASS

- [ ] **Step 2: Confirmar cobertura mínima dos novos módulos**

```bash
pytest --tb=short -q
```
Expected: 0 failures

- [ ] **Step 3: Commit final se houver arquivos soltos**

```bash
git status
```

Se limpo, nenhuma ação necessária. Se houver arquivos modificados não comitados, revisar antes de comitar.
