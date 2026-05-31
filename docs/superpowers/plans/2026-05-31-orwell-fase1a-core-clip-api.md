# Orwell — Fase 1A: Core + Clip API + Uploader (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o núcleo hardware-independente do Orwell — a lib `orwell_shared` (config, índice de segmentos, retenção, extração de clipe, storage plugável, schema de eventos), o serviço `clip-api` (FastAPI) e o esqueleto do `uploader` (MQTT → clipe → nuvem), orquestrados por docker-compose com um broker MQTT — tudo testável na máquina de dev com segmentos de vídeo de exemplo, sem Jetson.

**Architecture:** Monorepo Python. Um pacote compartilhado `orwell_shared` concentra a lógica pura (testável); os serviços (`clip-api`, `uploader`) são camadas finas em cima dele. O `recorder` (DeepStream, on-device) fica para o Plano 1B e consumirá o mesmo `orwell_shared` (índice SQLite + config). Segmentos são fMP4 individualmente tocáveis + playlist HLS; clipes são extraídos por cópia de stream (`ffmpeg -c copy`), com granularidade de segmento (~4s) na POC.

**Tech Stack:** Python 3.11, pydantic v2, PyYAML, FastAPI + Starlette TestClient, paho-mqtt, boto3 (S3), ffmpeg (CLI), SQLite (stdlib), pytest. Docker + docker-compose (eclipse-mosquitto para o broker).

**Referências:** spec `docs/superpowers/specs/2026-05-31-orwell-dvr-borda-design.md`; ADRs `docs/decisions/` (esp. 0004 Python, 0006 fMP4/CMAF+HLS, 0007 SQLite, 0010 storage plugável).

**Convenções fixas (não reinterpretar):**
- Tempos internos: **epoch float em UTC** (`segment.t_start`, `t_end`). A API aceita ISO-8601 e converte.
- Layout de segmento: `data/{camera_id}/{YYYY}/{MM}/{DD}/{HH}/seg-<epoch_ms>.m4s`; init: `data/{camera_id}/init.mp4`.
- Nada de placeholders: 12-factor (config via YAML + env `ORWELL_*`).

---

## File Structure

```
orwell/
  pyproject.toml                       # pacote orwell_shared + extras [dev,clip-api,uploader]
  config/orwell.yaml                   # config default (device, câmeras, perfil, retenção, broker, cloud)
  shared/orwell_shared/
    __init__.py
    config.py                          # modelos pydantic + load_config(yaml+env)
    paths.py                           # layout/parse de caminhos de segmento
    index.py                           # SegmentIndex (SQLite): add/query/oldest/delete/total_size/cameras
    retention.py                       # plan_eviction (puro) + run_eviction (I/O)
    clips.py                           # select_segments, build_ffmpeg_cmd, extract_clip
    events.py                          # DetectionEvent (pydantic) + janela do clipe
    storage/__init__.py                # get_backend(cloud_config)
    storage/base.py                    # StorageBackend (Protocol)
    storage/local.py                   # LocalStorageBackend
    storage/s3.py                      # S3StorageBackend (client injetável)
  shared/tests/                        # testes unitários do orwell_shared
  services/clip-api/
    app/__init__.py  app/main.py       # FastAPI: /healthz /cameras /segments /clips
    app/settings.py                    # carrega config + abre índice
    Dockerfile
    tests/test_clip_api.py
  services/uploader/
    app/__init__.py  app/main.py       # loop MQTT (fino)
    app/handler.py                     # handle_event(...) puro-ish (TDD)
    Dockerfile
    tests/test_uploader.py
  broker/mosquitto.conf
  docker-compose.yml
  tests/conftest.py                    # fixtures: segmentos fMP4 de exemplo, índice temp
  tests/test_integration_clip.py       # ffmpeg real sobre amostras (skip se ffmpeg ausente)
```

---

## Task 0: Scaffolding do projeto e pytest

**Files:**
- Create: `pyproject.toml`
- Create: `shared/orwell_shared/__init__.py`
- Create: `shared/tests/__init__.py`
- Create: `shared/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_smoke.py`:
```python
def test_package_importable():
    import orwell_shared
    assert orwell_shared.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orwell_shared'`

- [ ] **Step 3: Create the package and pyproject**

`shared/orwell_shared/__init__.py`:
```python
__version__ = "0.1.0"
```

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "orwell-shared"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
clip-api = ["fastapi>=0.110", "uvicorn>=0.29"]
uploader = ["paho-mqtt>=2.0", "boto3>=1.34"]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "paho-mqtt>=2.0",
    "boto3>=1.34",
]

[tool.setuptools.packages.find]
where = ["shared"]
include = ["orwell_shared*"]

[tool.pytest.ini_options]
testpaths = ["shared/tests", "services", "tests"]
```

`shared/tests/__init__.py`: (empty file)

- [ ] **Step 4: Install editable and run the test**

Run:
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest shared/tests/test_smoke.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml shared/orwell_shared/__init__.py shared/tests/
git commit -m "chore: scaffold orwell_shared package + pytest"
```

---

## Task 1: Config (pydantic + YAML + env)

**Files:**
- Create: `shared/orwell_shared/config.py`
- Create: `config/orwell.yaml`
- Test: `shared/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_config.py`:
```python
from pathlib import Path
from orwell_shared.config import load_config, OrwellConfig

YAML = """
device_name: orwell-01
cameras:
  - id: "0"
    argus_sensor_id: 0
    name: front
  - id: "1"
    argus_sensor_id: 1
capture:
  width: 1920
  height: 1080
  fps: 15
  segment_seconds: 4.0
  gop_seconds: 1.0
retention:
  data_dir: /var/lib/orwell/data
  disk_high_watermark_pct: 85
broker:
  host: broker
  events_topic: orwell/events
cloud:
  backend: s3
  bucket: my-bucket
"""

def test_load_config_parses_yaml(tmp_path: Path):
    p = tmp_path / "orwell.yaml"
    p.write_text(YAML)
    cfg = load_config(p)
    assert isinstance(cfg, OrwellConfig)
    assert cfg.device_name == "orwell-01"
    assert len(cfg.cameras) == 2
    assert cfg.cameras[0].id == "0"
    assert cfg.capture.segment_seconds == 4.0
    assert cfg.retention.disk_high_watermark_pct == 85
    assert cfg.cloud.bucket == "my-bucket"

def test_env_overrides_scalar(tmp_path: Path, monkeypatch):
    p = tmp_path / "orwell.yaml"
    p.write_text(YAML)
    monkeypatch.setenv("ORWELL_RETENTION__DISK_HIGH_WATERMARK_PCT", "70")
    monkeypatch.setenv("ORWELL_DEVICE_NAME", "orwell-99")
    cfg = load_config(p)
    assert cfg.retention.disk_high_watermark_pct == 70
    assert cfg.device_name == "orwell-99"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orwell_shared.config'`

- [ ] **Step 3: Implement config**

`shared/orwell_shared/config.py`:
```python
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    id: str
    argus_sensor_id: int
    name: str | None = None


class CaptureProfile(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 15
    codec: str = "h264"
    gop_seconds: float = 1.0
    segment_seconds: float = 4.0
    bitrate_kbps: int = 6000


class RetentionConfig(BaseModel):
    data_dir: str = "/var/lib/orwell/data"
    disk_high_watermark_pct: int = 85


class BrokerConfig(BaseModel):
    host: str = "broker"
    port: int = 1883
    events_topic: str = "orwell/events"


class CloudConfig(BaseModel):
    backend: str = "s3"           # s3 | local
    bucket: str | None = None
    prefix: str = "orwell/"
    local_dir: str = "/var/lib/orwell/uploads"


class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)


def _apply_env_overrides(data: dict) -> dict:
    """ORWELL_FOO=bar -> data['foo']; ORWELL_SECTION__KEY=val -> data['section']['key']."""
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_config.py -v`
Expected: PASS (2 passed). pydantic coage `"70"` → `int` automaticamente.

- [ ] **Step 5: Create default config and commit**

`config/orwell.yaml`:
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
  fps: 15
  codec: h264
  gop_seconds: 1.0
  segment_seconds: 4.0      # fácil de mudar (ADR-0006)
  bitrate_kbps: 6000
retention:
  data_dir: /var/lib/orwell/data
  disk_high_watermark_pct: 85
broker:
  host: broker
  port: 1883
  events_topic: orwell/events
cloud:
  backend: s3
  bucket: ""                # preencher quando definir a nuvem (ADR-0010)
  prefix: orwell/
```

```bash
git add shared/orwell_shared/config.py shared/tests/test_config.py config/orwell.yaml
git commit -m "feat(shared): config (pydantic + yaml + env overrides)"
```

---

## Task 2: Paths (layout/parse de segmentos)

**Files:**
- Create: `shared/orwell_shared/paths.py`
- Test: `shared/tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_paths.py`:
```python
from pathlib import Path
from orwell_shared.paths import segment_path, parse_segment_epoch_ms, init_path

def test_segment_path_layout():
    # 2026-05-31T14:00:00Z = 1780236000 s = 1780236000000 ms
    p = segment_path("/data", "0", 1780236000000)
    assert p == Path("/data/0/2026/05/31/14/seg-1780236000000.m4s")

def test_parse_segment_epoch_ms_roundtrip():
    p = segment_path("/data", "1", 1780236004500)
    assert parse_segment_epoch_ms(p) == 1780236004500

def test_init_path():
    assert init_path("/data", "0") == Path("/data/0/init.mp4")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_paths.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement paths**

`shared/orwell_shared/paths.py`:
```python
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_SEG_RE = re.compile(r"seg-(\d+)\.m4s$")


def segment_dir(data_dir: str | Path, camera_id: str, epoch_ms: int) -> Path:
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return Path(data_dir) / camera_id / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}" / f"{dt:%H}"


def segment_path(data_dir: str | Path, camera_id: str, epoch_ms: int) -> Path:
    return segment_dir(data_dir, camera_id, epoch_ms) / f"seg-{epoch_ms}.m4s"


def parse_segment_epoch_ms(path: str | Path) -> int:
    m = _SEG_RE.search(str(path))
    if not m:
        raise ValueError(f"not a segment path: {path}")
    return int(m.group(1))


def init_path(data_dir: str | Path, camera_id: str) -> Path:
    return Path(data_dir) / camera_id / "init.mp4"


def playlist_path(data_dir: str | Path, camera_id: str) -> Path:
    return Path(data_dir) / camera_id / "live.m3u8"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_paths.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/paths.py shared/tests/test_paths.py
git commit -m "feat(shared): segment path layout + parsing"
```

---

## Task 3: SegmentIndex (SQLite)

**Files:**
- Create: `shared/orwell_shared/index.py`
- Test: `shared/tests/test_index.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_index.py`:
```python
from orwell_shared.index import SegmentIndex, Segment

def make(cam, start, end, path, size=1000):
    return Segment(camera_id=cam, t_start=start, t_end=end, path=path, size=size, created_at=end)

def test_add_and_query_overlap(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/seg-100000.m4s"))
    idx.add_segment(make("0", 104.0, 108.0, "/d/0/seg-104000.m4s"))
    idx.add_segment(make("0", 108.0, 112.0, "/d/0/seg-108000.m4s"))
    idx.add_segment(make("1", 100.0, 104.0, "/d/1/seg-100000.m4s"))
    # janela [105,109] cobre os segmentos 104-108 e 108-112 da câmera 0
    res = idx.query("0", 105.0, 109.0)
    assert [s.path for s in res] == ["/d/0/seg-104000.m4s", "/d/0/seg-108000.m4s"]

def test_cameras_and_total_size(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=10))
    idx.add_segment(make("1", 100.0, 104.0, "/d/1/a.m4s", size=20))
    assert sorted(idx.cameras()) == ["0", "1"]
    assert idx.total_size() == 30

def test_oldest_and_delete(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/old.m4s"))
    idx.add_segment(make("0", 200.0, 204.0, "/d/0/new.m4s"))
    assert idx.oldest().path == "/d/0/old.m4s"
    idx.delete("/d/0/old.m4s")
    assert idx.oldest().path == "/d/0/new.m4s"

def test_add_is_idempotent_on_path(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=10))
    idx.add_segment(make("0", 100.0, 104.0, "/d/0/a.m4s", size=99))  # mesmo path
    assert idx.total_size() == 99  # upsert
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_index.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement index**

`shared/orwell_shared/index.py`:
```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    camera_id: str
    t_start: float
    t_end: float
    path: str
    size: int
    created_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    path       TEXT PRIMARY KEY,
    camera_id  TEXT NOT NULL,
    t_start    REAL NOT NULL,
    t_end      REAL NOT NULL,
    size       INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cam_time ON segments(camera_id, t_start);
"""


class SegmentIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_segment(self, seg: Segment) -> None:
        self._conn.execute(
            "INSERT INTO segments(path,camera_id,t_start,t_end,size,created_at) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "camera_id=excluded.camera_id, t_start=excluded.t_start, "
            "t_end=excluded.t_end, size=excluded.size, created_at=excluded.created_at",
            (seg.path, seg.camera_id, seg.t_start, seg.t_end, seg.size, seg.created_at),
        )
        self._conn.commit()

    def query(self, camera_id: str, start: float, end: float) -> list[Segment]:
        rows = self._conn.execute(
            "SELECT * FROM segments WHERE camera_id=? AND t_end>=? AND t_start<=? "
            "ORDER BY t_start",
            (camera_id, start, end),
        ).fetchall()
        return [self._row(r) for r in rows]

    def oldest(self, camera_id: str | None = None) -> Segment | None:
        if camera_id is None:
            row = self._conn.execute(
                "SELECT * FROM segments ORDER BY t_start LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM segments WHERE camera_id=? ORDER BY t_start LIMIT 1",
                (camera_id,),
            ).fetchone()
        return self._row(row) if row else None

    def delete(self, path: str) -> None:
        self._conn.execute("DELETE FROM segments WHERE path=?", (path,))
        self._conn.commit()

    def total_size(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(size),0) AS s FROM segments").fetchone()
        return int(row["s"])

    def cameras(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT camera_id FROM segments").fetchall()
        return [r["camera_id"] for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> Segment:
        return Segment(
            camera_id=r["camera_id"], t_start=r["t_start"], t_end=r["t_end"],
            path=r["path"], size=r["size"], created_at=r["created_at"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_index.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/index.py shared/tests/test_index.py
git commit -m "feat(shared): SQLite segment index"
```

---

## Task 4: Retenção (rotação por espaço)

**Files:**
- Create: `shared/orwell_shared/retention.py`
- Test: `shared/tests/test_retention.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_retention.py`:
```python
from orwell_shared.index import SegmentIndex, Segment
from orwell_shared.retention import plan_eviction, run_eviction

def make(cam, start, path, size):
    return Segment(camera_id=cam, t_start=start, t_end=start + 4, path=path, size=size, created_at=start)

def test_plan_eviction_returns_oldest_until_under_watermark():
    # capacidade 1000, uso atual 900 (90%), watermark 85% -> alvo <=850
    # precisa liberar >=50; remove os mais antigos primeiro
    oldest_first = [
        ("a.m4s", 30),
        ("b.m4s", 30),
        ("c.m4s", 30),
    ]
    to_delete = plan_eviction(used_bytes=900, capacity_bytes=1000,
                              high_watermark_pct=85, oldest_first=oldest_first)
    # remove a (870) e b (840 <=850) -> para
    assert to_delete == ["a.m4s", "b.m4s"]

def test_plan_eviction_noop_when_under_watermark():
    assert plan_eviction(800, 1000, 85, [("a.m4s", 30)]) == []

def test_run_eviction_deletes_files_and_index(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    paths = []
    for i in range(3):
        f = data / f"seg-{i}.m4s"
        f.write_bytes(b"x" * 100)
        idx.add_segment(make("0", float(i), str(f), 100))
        paths.append(str(f))
    # força "uso" alto via função injetada
    deleted = run_eviction(idx, used_bytes=300, capacity_bytes=300,
                           high_watermark_pct=50)
    # alvo <=150 -> remove seg-0 (200) e seg-1 (100<=150)
    assert deleted == [paths[0], paths[1]]
    assert idx.oldest().path == paths[2]
    assert not (data / "seg-0.m4s").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_retention.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement retention**

`shared/orwell_shared/retention.py`:
```python
from __future__ import annotations

import os
import shutil

from .index import SegmentIndex


def disk_usage(path: str) -> tuple[int, int]:
    """Retorna (used_bytes, total_bytes) do filesystem que contém `path`."""
    u = shutil.disk_usage(path)
    return (u.used, u.total)


def plan_eviction(used_bytes: int, capacity_bytes: int, high_watermark_pct: int,
                  oldest_first: list[tuple[str, int]]) -> list[str]:
    """Decide quais paths apagar (mais antigos primeiro) até cair abaixo do watermark.

    `oldest_first`: lista de (path, size) ordenada do mais antigo ao mais novo.
    Função pura — não toca disco.
    """
    target = capacity_bytes * high_watermark_pct / 100.0
    if used_bytes <= target:
        return []
    to_delete: list[str] = []
    remaining = used_bytes
    for path, size in oldest_first:
        if remaining <= target:
            break
        to_delete.append(path)
        remaining -= size
    return to_delete


def _oldest_first(index: SegmentIndex) -> list[tuple[str, int]]:
    rows = index._conn.execute(
        "SELECT path, size FROM segments ORDER BY t_start"
    ).fetchall()
    return [(r["path"], r["size"]) for r in rows]


def run_eviction(index: SegmentIndex, used_bytes: int, capacity_bytes: int,
                 high_watermark_pct: int) -> list[str]:
    """Aplica plan_eviction: apaga arquivos do disco e remove do índice."""
    victims = plan_eviction(used_bytes, capacity_bytes, high_watermark_pct,
                            _oldest_first(index))
    for path in victims:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        index.delete(path)
    return victims
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_retention.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/retention.py shared/tests/test_retention.py
git commit -m "feat(shared): disk-watermark retention (pure planner + runner)"
```

---

## Task 5: Eventos (schema + janela de clipe)

**Files:**
- Create: `shared/orwell_shared/events.py`
- Test: `shared/tests/test_events.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_events.py`:
```python
from orwell_shared.events import DetectionEvent

def test_parse_event_json():
    payload = '{"camera_id":"0","ts_event":1780236005.0,"label":"person","score":0.9}'
    ev = DetectionEvent.model_validate_json(payload)
    assert ev.camera_id == "0"
    assert ev.label == "person"
    assert ev.pre_s == 5.0 and ev.post_s == 5.0

def test_clip_window():
    ev = DetectionEvent(camera_id="0", ts_event=1000.0, label="x", score=0.5,
                        pre_s=3, post_s=7)
    assert ev.clip_window() == (997.0, 1007.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_events.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement events**

`shared/orwell_shared/events.py`:
```python
from __future__ import annotations

from pydantic import BaseModel


class DetectionEvent(BaseModel):
    camera_id: str
    ts_event: float          # epoch seconds (UTC)
    label: str
    score: float
    pre_s: float = 5.0
    post_s: float = 5.0

    def clip_window(self) -> tuple[float, float]:
        return (self.ts_event - self.pre_s, self.ts_event + self.post_s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_events.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/events.py shared/tests/test_events.py
git commit -m "feat(shared): DetectionEvent schema + clip window"
```

---

## Task 6: Extração de clipe (select + ffmpeg copy)

**Files:**
- Create: `shared/orwell_shared/clips.py`
- Test: `shared/tests/test_clips.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_clips.py`:
```python
from pathlib import Path
from orwell_shared.index import SegmentIndex, Segment
from orwell_shared.clips import build_ffmpeg_cmd, extract_clip, NoSegments
import pytest

def make(cam, start, path):
    return Segment(camera_id=cam, t_start=start, t_end=start + 4, path=path, size=10, created_at=start)

def test_build_ffmpeg_cmd_uses_concat_copy_faststart(tmp_path):
    listfile = tmp_path / "list.txt"
    out = tmp_path / "out.mp4"
    cmd = build_ffmpeg_cmd(listfile, out)
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert "-safe" in cmd and "0" in cmd
    assert "-c" in cmd and "copy" in cmd
    assert "+faststart" in " ".join(cmd)
    assert str(out) == cmd[-1]

def test_extract_clip_selects_segments_and_invokes_runner(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    init = tmp_path / "init.mp4"; init.write_bytes(b"init")
    for i, start in enumerate([100.0, 104.0, 108.0]):
        f = tmp_path / f"seg-{i}.m4s"; f.write_bytes(b"seg")
        idx.add_segment(make("0", start, str(f)))
    calls = {}
    def fake_runner(cmd, **kw):
        calls["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"clip")  # simula saída do ffmpeg
        class R: returncode = 0
        return R()
    out = tmp_path / "clip.mp4"
    result = extract_clip(idx, "0", 105.0, 109.0, out, init_path=init, runner=fake_runner)
    assert result == out and out.read_bytes() == b"clip"
    # a listfile passada ao ffmpeg deve referenciar init + 2 segmentos cobertos
    assert calls["cmd"][0] == "ffmpeg"

def test_extract_clip_raises_when_no_segments(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    with pytest.raises(NoSegments):
        extract_clip(idx, "0", 1.0, 2.0, tmp_path / "x.mp4",
                     init_path=tmp_path / "init.mp4", runner=lambda *a, **k: None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_clips.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement clips**

`shared/orwell_shared/clips.py`:
```python
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .index import Segment, SegmentIndex


class NoSegments(Exception):
    """Nenhum segmento cobre a janela pedida."""


def select_segments(index: SegmentIndex, camera_id: str, start: float, end: float) -> list[Segment]:
    return index.query(camera_id, start, end)


def _write_concat_list(segments: list[Segment], init: Path, listfile: Path) -> None:
    # Demuxer concat do ffmpeg: cada segmento fMP4 é precedido pelo init segment.
    lines = []
    for seg in segments:
        lines.append(f"file '{init}'")
        lines.append(f"file '{seg.path}'")
    listfile.write_text("\n".join(lines) + "\n")


def build_ffmpeg_cmd(listfile: Path, out_path: Path) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(listfile),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]


def extract_clip(index: SegmentIndex, camera_id: str, start: float, end: float,
                 out_path: str | Path, init_path: str | Path,
                 runner: Callable = subprocess.run) -> Path:
    segments = select_segments(index, camera_id, start, end)
    if not segments:
        raise NoSegments(f"camera={camera_id} window=[{start},{end}]")
    out_path = Path(out_path)
    init_path = Path(init_path)
    with tempfile.TemporaryDirectory() as td:
        listfile = Path(td) / "concat.txt"
        _write_concat_list(segments, init_path, listfile)
        cmd = build_ffmpeg_cmd(listfile, out_path)
        result = runner(cmd, capture_output=True)
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', b'')!r}")
    return out_path
```

> Nota (POC): a extração é por **granularidade de segmento** (~4s) — pode cobrir alguns segundos
> a mais nas bordas. Refinamento futuro (corte por segundo via `-ss/-to`) fica para o Plano 1B/2.
> A duplicação do init por segmento no concat é tolerada por `-c copy`; se o muxer escolhido
> gerar segmentos auto-contidos (com moov próprio), o init pode ser omitido — validar no Plano 1B.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_clips.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/clips.py shared/tests/test_clips.py
git commit -m "feat(shared): clip extraction (segment select + ffmpeg concat copy)"
```

---

## Task 7: Storage plugável (base + local + s3)

**Files:**
- Create: `shared/orwell_shared/storage/__init__.py`
- Create: `shared/orwell_shared/storage/base.py`
- Create: `shared/orwell_shared/storage/local.py`
- Create: `shared/orwell_shared/storage/s3.py`
- Test: `shared/tests/test_storage.py`

- [ ] **Step 1: Write the failing test**

`shared/tests/test_storage.py`:
```python
from pathlib import Path
from orwell_shared.config import CloudConfig
from orwell_shared.storage import get_backend
from orwell_shared.storage.local import LocalStorageBackend
from orwell_shared.storage.s3 import S3StorageBackend

def test_local_backend_copies_and_returns_uri(tmp_path):
    src = tmp_path / "clip.mp4"; src.write_bytes(b"data")
    dest_dir = tmp_path / "uploads"
    backend = LocalStorageBackend(str(dest_dir))
    uri = backend.put(str(src), "events/clip.mp4", {"camera": "0"})
    assert uri == f"file://{dest_dir}/events/clip.mp4"
    assert (dest_dir / "events" / "clip.mp4").read_bytes() == b"data"

def test_s3_backend_calls_client(tmp_path):
    src = tmp_path / "clip.mp4"; src.write_bytes(b"data")
    calls = {}
    class FakeClient:
        def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
            calls.update(Filename=Filename, Bucket=Bucket, Key=Key, ExtraArgs=ExtraArgs)
    backend = S3StorageBackend(bucket="my-bucket", prefix="orwell/", client=FakeClient())
    uri = backend.put(str(src), "events/clip.mp4", {"camera": "0"})
    assert calls["Bucket"] == "my-bucket"
    assert calls["Key"] == "orwell/events/clip.mp4"
    assert uri == "s3://my-bucket/orwell/events/clip.mp4"

def test_get_backend_factory_local():
    cfg = CloudConfig(backend="local", local_dir="/tmp/up")
    assert isinstance(get_backend(cfg), LocalStorageBackend)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest shared/tests/test_storage.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement storage**

`shared/orwell_shared/storage/base.py`:
```python
from __future__ import annotations

from typing import Protocol


class StorageBackend(Protocol):
    def put(self, local_path: str, key: str, metadata: dict) -> str:
        """Envia `local_path` para `key`; retorna a URI resultante."""
        ...
```

`shared/orwell_shared/storage/local.py`:
```python
from __future__ import annotations

import shutil
from pathlib import Path


class LocalStorageBackend:
    def __init__(self, dest_dir: str):
        self.dest_dir = Path(dest_dir)

    def put(self, local_path: str, key: str, metadata: dict) -> str:
        target = self.dest_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        return f"file://{target}"
```

`shared/orwell_shared/storage/s3.py`:
```python
from __future__ import annotations


class S3StorageBackend:
    def __init__(self, bucket: str, prefix: str = "", client=None):
        self.bucket = bucket
        self.prefix = prefix
        if client is None:
            import boto3  # import tardio: só quando realmente usar S3
            client = boto3.client("s3")
        self.client = client

    def put(self, local_path: str, key: str, metadata: dict) -> str:
        full_key = f"{self.prefix}{key}"
        self.client.upload_file(
            Filename=local_path, Bucket=self.bucket, Key=full_key,
            ExtraArgs={"Metadata": {k: str(v) for k, v in metadata.items()}},
        )
        return f"s3://{self.bucket}/{full_key}"
```

`shared/orwell_shared/storage/__init__.py`:
```python
from __future__ import annotations

from ..config import CloudConfig
from .base import StorageBackend
from .local import LocalStorageBackend
from .s3 import S3StorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend", "S3StorageBackend", "get_backend"]


def get_backend(cfg: CloudConfig) -> StorageBackend:
    if cfg.backend == "local":
        return LocalStorageBackend(cfg.local_dir)
    if cfg.backend == "s3":
        if not cfg.bucket:
            raise ValueError("cloud.bucket é obrigatório para backend=s3")
        return S3StorageBackend(bucket=cfg.bucket, prefix=cfg.prefix)
    raise ValueError(f"backend de storage desconhecido: {cfg.backend}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest shared/tests/test_storage.py -v`
Expected: PASS (3 passed). O teste S3 injeta um client fake (boto3 não é chamado).

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/storage/ shared/tests/test_storage.py
git commit -m "feat(shared): pluggable storage (base + local + s3)"
```

---

## Task 8: clip-api (FastAPI)

**Files:**
- Create: `services/clip-api/app/__init__.py` (empty)
- Create: `services/clip-api/app/settings.py`
- Create: `services/clip-api/app/main.py`
- Test: `services/clip-api/tests/test_clip_api.py`

- [ ] **Step 1: Write the failing test**

`services/clip-api/tests/test_clip_api.py`:
```python
from pathlib import Path
import os
from fastapi.testclient import TestClient
from orwell_shared.index import SegmentIndex, Segment

def _build_client(tmp_path, monkeypatch):
    # índice com 2 segmentos da câmera "0" cobrindo [100,108]
    idx_path = tmp_path / "idx.sqlite"
    idx = SegmentIndex(idx_path)
    init = tmp_path / "0" / "init.mp4"; init.parent.mkdir(parents=True); init.write_bytes(b"i")
    for i, start in enumerate([100.0, 104.0]):
        f = tmp_path / "0" / f"seg-{i}.m4s"; f.write_bytes(b"s")
        idx.add_segment(Segment("0", start, start + 4, str(f), 10, start))
    monkeypatch.setenv("ORWELL_INDEX_DB", str(idx_path))
    monkeypatch.setenv("ORWELL_DATA_DIR", str(tmp_path))
    from app.main import create_app
    # injeta um extrator fake p/ não depender de ffmpeg neste teste
    def fake_extract(index, camera, start, end, out_path, init_path, runner=None):
        Path(out_path).write_bytes(b"CLIP"); return Path(out_path)
    app = create_app(extract_fn=fake_extract)
    return TestClient(app)

def test_healthz(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    assert c.get("/healthz").json() == {"status": "ok"}

def test_cameras(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    assert c.get("/cameras").json() == ["0"]

def test_get_clip_returns_mp4(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/clips", params={"camera": "0",
                                "start": "1970-01-01T00:01:45Z",   # 105s
                                "end": "1970-01-01T00:01:47Z"})    # 107s
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.content == b"CLIP"

def test_get_clip_404_when_empty(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    r = c.get("/clips", params={"camera": "0",
                                "start": "2000-01-01T00:00:00Z",
                                "end": "2000-01-01T00:00:05Z"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest services/clip-api/tests/test_clip_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement settings + app**

`services/clip-api/app/__init__.py`: (empty file)

`services/clip-api/app/settings.py`:
```python
from __future__ import annotations

import os


def index_db_path() -> str:
    return os.environ.get("ORWELL_INDEX_DB", "/var/lib/orwell/data/index.sqlite")


def data_dir() -> str:
    return os.environ.get("ORWELL_DATA_DIR", "/var/lib/orwell/data")
```

`services/clip-api/app/main.py`:
```python
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from orwell_shared.clips import extract_clip, NoSegments
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import init_path

from .settings import index_db_path, data_dir


def _to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def create_app(extract_fn=extract_clip) -> FastAPI:
    app = FastAPI(title="Orwell Clip API")
    index = SegmentIndex(index_db_path())
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

    @app.get("/clips")
    def clips(camera: str = Query(...), start: str = Query(...), end: str = Query(...)):
        s, e = _to_epoch(start), _to_epoch(end)
        out = Path(tempfile.gettempdir()) / f"clip-{camera}-{int(s)}-{int(e)}.mp4"
        try:
            extract_fn(index, camera, s, e, out, init_path=init_path(ddir, camera))
        except NoSegments:
            raise HTTPException(status_code=404, detail="no segments for window")
        return FileResponse(str(out), media_type="video/mp4", filename=out.name)

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/clip-api/tests/test_clip_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/clip-api/app services/clip-api/tests
git commit -m "feat(clip-api): FastAPI service (healthz, cameras, segments, clips)"
```

---

## Task 9: clip-api Dockerfile

**Files:**
- Create: `services/clip-api/Dockerfile`
- Create: `services/clip-api/.dockerignore`

- [ ] **Step 1: Write the Dockerfile**

`services/clip-api/Dockerfile`:
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# instala a lib compartilhada
COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src[clip-api]"

COPY services/clip-api/app /app/app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`services/clip-api/.dockerignore`:
```
**/__pycache__
**/*.pyc
.venv
```

- [ ] **Step 2: Build the image (context = repo root)**

Run: `docker build -f services/clip-api/Dockerfile -t orwell-clip-api:dev .`
Expected: build conclui sem erro (imagem `orwell-clip-api:dev` criada).

- [ ] **Step 3: Smoke-run healthz**

Run:
```bash
docker run --rm -d --name clipapi -p 8080:8080 orwell-clip-api:dev
sleep 2 && curl -s localhost:8080/healthz
docker stop clipapi
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add services/clip-api/Dockerfile services/clip-api/.dockerignore
git commit -m "build(clip-api): Dockerfile (python-slim + ffmpeg)"
```

---

## Task 10: uploader (handler TDD + loop MQTT fino)

**Files:**
- Create: `services/uploader/app/__init__.py` (empty)
- Create: `services/uploader/app/handler.py`
- Create: `services/uploader/app/main.py`
- Test: `services/uploader/tests/test_uploader.py`

- [ ] **Step 1: Write the failing test**

`services/uploader/tests/test_uploader.py`:
```python
from pathlib import Path
from orwell_shared.index import SegmentIndex, Segment
from app.handler import handle_event_payload

class FakeStorage:
    def __init__(self): self.calls = []
    def put(self, local_path, key, metadata):
        self.calls.append((local_path, key, metadata)); return f"s3://b/{key}"

def test_handle_event_extracts_window_and_uploads(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    init = tmp_path / "0" / "init.mp4"; init.parent.mkdir(parents=True); init.write_bytes(b"i")
    for i, start in enumerate([996.0, 1000.0, 1004.0]):
        f = tmp_path / "0" / f"seg-{i}.m4s"; f.write_bytes(b"s")
        idx.add_segment(Segment("0", start, start + 4, str(f), 10, start))
    storage = FakeStorage()
    def fake_extract(index, camera, start, end, out_path, init_path, runner=None):
        Path(out_path).write_bytes(b"CLIP"); return Path(out_path)
    payload = '{"camera_id":"0","ts_event":1000.0,"label":"person","score":0.9,"pre_s":3,"post_s":3}'
    uri = handle_event_payload(payload, idx, storage, data_dir=str(tmp_path),
                               extract_fn=fake_extract)
    assert uri.startswith("s3://b/")
    assert storage.calls[0][2]["camera"] == "0"   # metadata
    assert storage.calls[0][2]["label"] == "person"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest services/uploader/tests/test_uploader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement handler + main**

`services/uploader/app/__init__.py`: (empty file)

`services/uploader/app/handler.py`:
```python
from __future__ import annotations

import tempfile
from pathlib import Path

from orwell_shared.clips import extract_clip
from orwell_shared.events import DetectionEvent
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import init_path


def handle_event_payload(payload: str, index: SegmentIndex, storage,
                         data_dir: str, extract_fn=extract_clip) -> str:
    ev = DetectionEvent.model_validate_json(payload)
    start, end = ev.clip_window()
    out = Path(tempfile.gettempdir()) / f"event-{ev.camera_id}-{int(ev.ts_event)}.mp4"
    extract_fn(index, ev.camera_id, start, end, out,
               init_path=init_path(data_dir, ev.camera_id))
    key = f"events/{ev.camera_id}/{int(ev.ts_event)}.mp4"
    metadata = {"camera": ev.camera_id, "label": ev.label, "score": str(ev.score),
                "ts_event": str(ev.ts_event)}
    return storage.put(str(out), key, metadata)
```

`services/uploader/app/main.py`:
```python
from __future__ import annotations

import os

import paho.mqtt.client as mqtt

from orwell_shared.config import load_config
from orwell_shared.index import SegmentIndex
from orwell_shared.storage import get_backend

from .handler import handle_event_payload


def main() -> None:
    cfg = load_config(os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml"))
    index = SegmentIndex(os.environ.get("ORWELL_INDEX_DB",
                                        f"{cfg.retention.data_dir}/index.sqlite"))
    storage = get_backend(cfg.cloud)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(cfg.broker.events_topic)

    def on_message(client, userdata, msg):
        try:
            uri = handle_event_payload(msg.payload.decode(), index, storage,
                                       data_dir=cfg.retention.data_dir)
            print(f"uploaded: {uri}", flush=True)
        except Exception as exc:  # noqa: BLE001 - loop não pode morrer por 1 evento
            print(f"event error: {exc}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cfg.broker.host, cfg.broker.port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest services/uploader/tests/test_uploader.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add services/uploader/app services/uploader/tests
git commit -m "feat(uploader): MQTT event handler -> clip -> storage (skeleton)"
```

---

## Task 11: uploader Dockerfile

**Files:**
- Create: `services/uploader/Dockerfile`
- Create: `services/uploader/.dockerignore`

- [ ] **Step 1: Write the Dockerfile**

`services/uploader/Dockerfile`:
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src[uploader]"

COPY services/uploader/app /app/app
COPY config /app/config

CMD ["python", "-m", "app.main"]
```

`services/uploader/.dockerignore`:
```
**/__pycache__
**/*.pyc
.venv
```

- [ ] **Step 2: Build the image**

Run: `docker build -f services/uploader/Dockerfile -t orwell-uploader:dev .`
Expected: build conclui sem erro.

- [ ] **Step 3: Commit**

```bash
git add services/uploader/Dockerfile services/uploader/.dockerignore
git commit -m "build(uploader): Dockerfile (python-slim + ffmpeg)"
```

---

## Task 12: Broker (Mosquitto) + docker-compose

**Files:**
- Create: `broker/mosquitto.conf`
- Create: `docker-compose.yml`

- [ ] **Step 1: Write broker config and compose**

`broker/mosquitto.conf`:
```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
```

`docker-compose.yml`:
```yaml
services:
  broker:
    image: eclipse-mosquitto:2
    volumes:
      - ./broker/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto-data:/mosquitto/data
    ports:
      - "1883:1883"

  clip-api:
    build:
      context: .
      dockerfile: services/clip-api/Dockerfile
    environment:
      ORWELL_INDEX_DB: /data/index.sqlite
      ORWELL_DATA_DIR: /data
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
    ports:
      - "8080:8080"
    depends_on: [broker]

  uploader:
    build:
      context: .
      dockerfile: services/uploader/Dockerfile
    environment:
      ORWELL_CONFIG: /app/config/orwell.yaml
      ORWELL_INDEX_DB: /data/index.sqlite
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
      - ./config:/app/config:ro
    depends_on: [broker]

  # recorder: definido no Plano 1B (DeepStream, base L4T, on-device).

volumes:
  mosquitto-data:
```

- [ ] **Step 2: Validate compose config**

Run: `docker compose config`
Expected: imprime a config resolvida sem erro de sintaxe.

- [ ] **Step 3: Bring up broker + clip-api and check health**

Run:
```bash
mkdir -p data
docker compose up -d broker clip-api
sleep 3 && curl -s localhost:8080/healthz
docker compose logs --no-color clip-api | tail -5
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Tear down and commit**

```bash
docker compose down
git add broker/mosquitto.conf docker-compose.yml
git commit -m "build: docker-compose (broker + clip-api + uploader)"
```

---

## Task 13: Teste de integração com ffmpeg real

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_integration_clip.py`

- [ ] **Step 1: Write the fixture + failing integration test**

`tests/__init__.py`: (empty file)

`tests/conftest.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG = shutil.which("ffmpeg")


@pytest.fixture
def sample_segments(tmp_path):
    """Gera init.mp4 + 3 segmentos fMP4 de 2s (cor sólida) para a câmera '0'."""
    if not FFMPEG:
        pytest.skip("ffmpeg não disponível")
    cam_dir = tmp_path / "0"
    cam_dir.mkdir(parents=True)
    # gera 3 arquivos mp4 fragmentados auto-contidos de 2s cada
    starts = [100.0, 102.0, 104.0]
    paths = []
    for i, _ in enumerate(starts):
        out = cam_dir / f"seg-{i}.m4s"
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c=blue:s=320x240:d=2:r=15",
             "-c:v", "libx264", "-g", "15", "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
             str(out)],
            check=True, capture_output=True,
        )
        paths.append((str(out), starts[i]))
    init = cam_dir / "init.mp4"
    init.write_bytes(b"")  # segmentos são auto-contidos; init vazio é tolerado no concat
    return tmp_path, paths
```

`tests/test_integration_clip.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

from orwell_shared.index import SegmentIndex, Segment
from orwell_shared.clips import extract_clip

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe ausentes")
def test_extract_real_clip_produces_playable_mp4(sample_segments, tmp_path):
    data_dir, paths = sample_segments
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    for p, start in paths:
        idx.add_segment(Segment("0", start, start + 2, p, Path(p).stat().st_size, start))
    out = tmp_path / "clip.mp4"
    init = data_dir / "0" / "init.mp4"
    extract_clip(idx, "0", 101.0, 105.0, out, init_path=init)
    assert out.exists() and out.stat().st_size > 0
    # ffprobe confirma que é um vídeo legível
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0
    assert float(probe.stdout.strip()) > 0
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest tests/test_integration_clip.py -v`
Expected: PASS (1 passed) — ou SKIP se ffmpeg/ffprobe ausentes na máquina.

> Se o concat com `init` vazio falhar no seu ffmpeg, ajuste `_write_concat_list` para omitir o
> init quando os segmentos forem auto-contidos. Esse é o ponto a validar contra o muxer real no
> Plano 1B; documente o resultado em `docs/decisions/0006-mp4-padrao-splitmuxsink.md`.

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: integração de extração de clipe com ffmpeg real"
```

---

## Task 14: README de desenvolvimento

**Files:**
- Create: `services/README.md`

- [ ] **Step 1: Write the dev runbook**

`services/README.md`:
```markdown
# Serviços Orwell — desenvolvimento

## Setup
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Testes
```bash
python -m pytest            # todos
python -m pytest shared     # só a lib
```

## Subir localmente (sem Jetson)
```bash
mkdir -p data
docker compose up -d broker clip-api uploader
curl localhost:8080/healthz
```

## Estrutura
- `shared/orwell_shared/` — lógica pura (config, índice, retenção, clipes, storage, eventos).
- `services/clip-api/` — FastAPI: GET /clips.
- `services/uploader/` — MQTT → clipe → nuvem (esqueleto; IA no Plano 2).
- `recorder/` — DeepStream on-device (Plano 1B).
```

- [ ] **Step 2: Commit**

```bash
git add services/README.md
git commit -m "docs(services): dev runbook"
```

---

## Self-Review (preenchido)

**Cobertura do spec (Fase 1, parte hardware-independente):**
- Buffer/segmentos + índice → Tasks 2, 3 (índice); gravação real fica no Plano 1B (recorder).
- Rotação por espaço → Task 4.
- Clip API (GET intervalo) → Tasks 6, 8.
- Extração por cópia de stream (fMP4) → Task 6 (+ integração Task 13).
- Evento → clipe → nuvem (uploader, storage plugável S3) → Tasks 5, 7, 10.
- Broker MQTT + compose → Task 12.
- 12-factor (config YAML + env) → Task 1.
- Lacuna intencional: **recorder/DeepStream/Argus/HLS-write** → Plano 1B (on-device). `nvinfer`/IA → Plano 2.

**Placeholders:** nenhum — todos os steps têm código/comandos reais.

**Consistência de tipos:** `Segment(camera_id,t_start,t_end,path,size,created_at)` usado igual em
index/retention/clips/api/uploader; `extract_clip(index,camera,start,end,out_path,init_path,runner)`
e `extract_fn` com a mesma assinatura em clip-api e uploader; `get_backend(CloudConfig)` consistente
com `CloudConfig` da Task 1.
