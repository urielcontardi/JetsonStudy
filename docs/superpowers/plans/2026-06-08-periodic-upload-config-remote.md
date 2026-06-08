# Periodic Upload + Config Remote + Uploader Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enviar o buffer circular de 60 s a cada 10 min (configurável), via serviço `uploader` independente, com `PATCH /config` na clip-api e painel de configuração no dashboard.

**Architecture:** O `recorder` adiciona um `PeriodicFlusher` (timer que copia o buffer circular para `/events/` e registra no SQLite) e um `ConfigWatcher` (hot-reload do `orwell.yaml`). O `UploadWorker` sai do `recorder` e passa para um novo serviço `uploader` (container leve, sem NVIDIA). A interface entre eles é SQLite + filesystem — zero acoplamento direto.

**Tech Stack:** Python 3.10+, SQLite (WAL), threading, shutil, pydantic, FastAPI, PyYAML, Protobuf, VSTP/Conveyor.

---

## File Map

| Arquivo | Ação |
|---|---|
| `shared/orwell_shared/events.py` | Modificar — `trigger_type` field + migration + `busy_timeout` |
| `shared/orwell_shared/index.py` | Modificar — `busy_timeout` |
| `shared/orwell_shared/config.py` | Modificar — `periodic_upload_enabled` + `periodic_upload_interval_s` |
| `shared/orwell_shared/upload_worker.py` | Modificar — passa `trigger_type` no metadata |
| `shared/orwell_shared/conveyor_uploader.py` | Modificar — lê `trigger_type` do metadata |
| `shared/orwell_shared/config_watcher.py` | Criar |
| `shared/proto/remote_config.proto` | Criar |
| `shared/orwell_shared/remote_config_pb2.py` | Gerar via protoc + commitar |
| `shared/tests/test_events.py` | Modificar — adicionar testes de `trigger_type` e `upload_stats` |
| `shared/tests/test_config.py` | Modificar — adicionar campos periódicos |
| `shared/tests/test_config_watcher.py` | Criar |
| `services/recorder/recorder/periodic_flusher.py` | Criar |
| `services/recorder/recorder/main.py` | Modificar — adicionar PeriodicFlusher + ConfigWatcher, remover UploadWorker |
| `services/recorder/tests/__init__.py` | Criar |
| `services/recorder/tests/test_periodic_flusher.py` | Criar |
| `services/uploader/Dockerfile` | Criar |
| `services/uploader/uploader/__init__.py` | Criar |
| `services/uploader/uploader/main.py` | Criar |
| `services/clip-api/clip_api/settings.py` | Modificar — adicionar `config_path()` |
| `services/clip-api/clip_api/main.py` | Modificar — `GET/PATCH /config` + `GET /upload-stats` |
| `services/clip-api/tests/test_config_api.py` | Criar |
| `services/dashboard/dashboard/page.html` | Modificar — painel de configuração |
| `docker-compose.yml` | Modificar — adicionar `uploader`, montar config na clip-api |

---

## Task 1: SQLite — busy_timeout + trigger_type

**Files:**
- Modify: `shared/orwell_shared/events.py`
- Modify: `shared/orwell_shared/index.py`
- Modify: `shared/tests/test_events.py`

- [ ] **Passo 1.1: Escrever os testes novos (devem falhar)**

Adicionar no final de `shared/tests/test_events.py`:

```python
def test_trigger_type_default_is_ai(idx):
    ev = _event()
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.trigger_type == "ai"


def test_trigger_type_periodic_persists(idx):
    ev = _event(id="p1", trigger_type="periodic")
    idx.add_event(ev)
    result = idx.get("p1")
    assert result.trigger_type == "periodic"


def test_trigger_type_migration_on_existing_db(tmp_path):
    """DB sem coluna trigger_type deve ser migrado automaticamente."""
    import sqlite3
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, t_evento REAL NOT NULL,
            label TEXT NOT NULL, confidence REAL NOT NULL, bbox_json TEXT,
            clip_path TEXT, uploaded_at REAL, created_at REAL NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO events VALUES('e1','cam0',1.0,'smoke',0.9,NULL,NULL,NULL,1.0)"
    )
    conn.commit()
    conn.close()

    idx = EventIndex(db)
    ev = idx.get("e1")
    assert ev is not None
    assert ev.trigger_type == "ai"


def test_upload_stats_empty(idx):
    stats = idx.upload_stats()
    assert stats["pending"] == 0
    assert stats["failed"] == 0
    assert stats["last_uploaded_at"] is None


def test_upload_stats_counts(idx):
    idx.add_event(_event(id="p1", clip_path="/events/p1"))          # pending
    idx.add_event(_event(id="p2", clip_path="/events/p2"))          # pending
    idx.add_event(_event(id="f1", clip_path="/events/f1"))          # failed
    idx.mark_upload_failed("f1")
    idx.add_event(_event(id="u1", clip_path="/events/u1"))          # uploaded
    idx.mark_uploaded("u1")

    stats = idx.upload_stats()
    assert stats["pending"] == 2
    assert stats["failed"] == 1
    assert stats["last_uploaded_at"] is not None
```

- [ ] **Passo 1.2: Rodar testes — verificar que falham**

```bash
cd /Users/urielabecontardi/Documents/tractian-orwell
python -m pytest shared/tests/test_events.py::test_trigger_type_default_is_ai -v
```
Esperado: `FAILED` — `Event.__init__() got an unexpected keyword argument 'trigger_type'`

- [ ] **Passo 1.3: Atualizar `shared/orwell_shared/events.py`**

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
    trigger_type: str = "ai"


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
    created_at  REAL NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'ai'
);
CREATE INDEX IF NOT EXISTS idx_events_cam_time ON events(camera_id, t_evento);
"""

_MIGRATION_ADD_TRIGGER_TYPE = (
    "ALTER TABLE events ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'ai'"
)


class EventIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.execute(_MIGRATION_ADD_TRIGGER_TYPE)
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # coluna já existe

    def add_event(self, event: Event) -> None:
        self._conn.execute(
            "INSERT INTO events"
            "(id,camera_id,t_evento,label,confidence,bbox_json,clip_path,uploaded_at,created_at,trigger_type)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event.id, event.camera_id, event.t_evento, event.label, event.confidence,
             event.bbox_json, event.clip_path, event.uploaded_at, event.created_at,
             event.trigger_type),
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

    def pending_uploads(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE uploaded_at IS NULL ORDER BY t_evento"
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_uploaded(self, event_id: str) -> None:
        import time as _time
        self._conn.execute(
            "UPDATE events SET uploaded_at=? WHERE id=?",
            (_time.time(), event_id),
        )
        self._conn.commit()

    def mark_upload_failed(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE events SET uploaded_at=? WHERE id=?",
            (-1.0, event_id),
        )
        self._conn.commit()

    def upload_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT "
            "  COUNT(CASE WHEN uploaded_at IS NULL THEN 1 END) AS pending, "
            "  COUNT(CASE WHEN uploaded_at = -1.0 THEN 1 END) AS failed, "
            "  MAX(CASE WHEN uploaded_at > 0 THEN uploaded_at END) AS last_uploaded_at "
            "FROM events"
        ).fetchone()
        return {
            "pending": row["pending"],
            "failed": row["failed"],
            "last_uploaded_at": row["last_uploaded_at"],
        }

    @staticmethod
    def _row(r: sqlite3.Row) -> Event:
        return Event(
            id=r["id"], camera_id=r["camera_id"], t_evento=r["t_evento"],
            label=r["label"], confidence=r["confidence"], bbox_json=r["bbox_json"],
            clip_path=r["clip_path"], uploaded_at=r["uploaded_at"],
            created_at=r["created_at"],
            trigger_type=r["trigger_type"] if "trigger_type" in r.keys() else "ai",
        )
```

- [ ] **Passo 1.4: Adicionar busy_timeout ao `shared/orwell_shared/index.py`**

Localizar em `SegmentIndex.__init__` a linha:
```python
        self._conn.execute("PRAGMA journal_mode=WAL")
```
E adicionar logo após:
```python
        self._conn.execute("PRAGMA busy_timeout=5000")
```

- [ ] **Passo 1.5: Rodar todos os testes de events — verificar que passam**

```bash
python -m pytest shared/tests/test_events.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 1.6: Commit**

```bash
git add shared/orwell_shared/events.py shared/orwell_shared/index.py shared/tests/test_events.py
git commit -m "feat(sqlite): trigger_type field + busy_timeout + upload_stats"
```

---

## Task 2: Config — campos de upload periódico

**Files:**
- Modify: `shared/orwell_shared/config.py`
- Modify: `shared/tests/test_config.py`

- [ ] **Passo 2.1: Escrever testes novos (devem falhar)**

Adicionar ao final de `shared/tests/test_config.py`:

```python
def test_conveyor_config_defaults_periodic():
    from orwell_shared.config import ConveyorConfig
    cfg = ConveyorConfig()
    assert cfg.periodic_upload_enabled is True
    assert cfg.periodic_upload_interval_s == 600


def test_conveyor_config_periodic_from_yaml(tmp_path):
    import yaml
    from orwell_shared.config import load_config
    cfg_file = tmp_path / "orwell.yaml"
    cfg_file.write_text(yaml.dump({
        "conveyor": {
            "enabled": True,
            "periodic_upload_enabled": False,
            "periodic_upload_interval_s": 300,
        }
    }))
    cfg = load_config(cfg_file)
    assert cfg.conveyor.periodic_upload_enabled is False
    assert cfg.conveyor.periodic_upload_interval_s == 300
```

- [ ] **Passo 2.2: Rodar — verificar que falham**

```bash
python -m pytest shared/tests/test_config.py::test_conveyor_config_defaults_periodic -v
```
Esperado: `FAILED` — `has no field 'periodic_upload_enabled'`

- [ ] **Passo 2.3: Atualizar `shared/orwell_shared/config.py`**

Localizar a classe `ConveyorConfig` e adicionar os dois novos campos:

```python
class ConveyorConfig(BaseModel):
    enabled: bool = False
    host: str = "conveyor.tractian.com"
    port: int = 8080
    gateway_ext_id: str = ""
    sensor_ext_id: str = ""
    upload_interval_s: int = 30
    status_interval_s: int = 300
    periodic_upload_enabled: bool = True
    periodic_upload_interval_s: int = 600
```

- [ ] **Passo 2.4: Rodar testes de config — verificar que passam**

```bash
python -m pytest shared/tests/test_config.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 2.5: Commit**

```bash
git add shared/orwell_shared/config.py shared/tests/test_config.py
git commit -m "feat(config): periodic_upload_enabled + periodic_upload_interval_s"
```

---

## Task 3: ConveyorUploader + UploadWorker — trigger_type no payload

**Files:**
- Modify: `shared/orwell_shared/conveyor_uploader.py`
- Modify: `shared/orwell_shared/upload_worker.py`
- Modify: `shared/tests/test_conveyor_uploader.py`

- [ ] **Passo 3.1: Verificar que o teste existente passa antes de mudar**

```bash
python -m pytest shared/tests/test_conveyor_uploader.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 3.2: Escrever teste para trigger_type periódico**

Adicionar ao final de `shared/tests/test_conveyor_uploader.py`:

```python
def test_upload_periodic_uses_trigger_type_periodic(tmp_path):
    from unittest.mock import MagicMock, patch
    from orwell_shared.conveyor_uploader import ConveyorUploader
    from orwell_shared.samples_pb2 import Package, TriggerType

    clip_dir = tmp_path / "events" / "evt-p"
    clip_dir.mkdir(parents=True)
    (clip_dir / "buf-0.m4s").write_bytes(b"A")
    (clip_dir / "buf-1.m4s").write_bytes(b"B")

    mock_client = MagicMock()
    uploader = ConveyorUploader(client=mock_client, sensor_ext_id="test-sensor")

    uploader.upload(
        event_id="evt-p-uuid-1234-5678-9012",
        clip_path=clip_dir,
        metadata={
            "camera_id": "cam0",
            "label": "periodic",
            "confidence": 1.0,
            "bbox": None,
            "t_evento": 1000.0,
            "trigger_type": "periodic",
        },
    )

    assert mock_client.send_dev_sample.called
    pkg = Package()
    pkg.ParseFromString(mock_client.send_dev_sample.call_args[0][0])
    assert pkg.trigger_type == TriggerType.Value("TRIGGER_TYPE_PERIODIC")
```

- [ ] **Passo 3.3: Rodar — verificar que falha**

```bash
python -m pytest shared/tests/test_conveyor_uploader.py::test_upload_periodic_uses_trigger_type_periodic -v
```
Esperado: `FAILED` — trigger_type ainda é `TRIGGER_TYPE_EVENT`

- [ ] **Passo 3.4: Atualizar `shared/orwell_shared/conveyor_uploader.py`**

Substituir o bloco de `trigger_type` no método `upload()`. Localizar:
```python
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_EVENT")
```
E substituir por:
```python
        raw_trigger = metadata.get("trigger_type", "ai")
        pkg.trigger_type = (
            TriggerType.Value("TRIGGER_TYPE_PERIODIC")
            if raw_trigger == "periodic"
            else TriggerType.Value("TRIGGER_TYPE_EVENT")
        )
```

- [ ] **Passo 3.5: Atualizar `shared/orwell_shared/upload_worker.py`**

No método `_process_pending`, adicionar `"trigger_type"` ao dict de metadata.
Localizar:
```python
                self._uploader.upload(
                    event_id=event.id,
                    clip_path=clip_path,
                    metadata={
                        "camera_id": event.camera_id,
                        "label": event.label,
                        "confidence": event.confidence,
                        "bbox": event.bbox_json,
                        "t_evento": event.t_evento,
                    },
                )
```
Substituir por:
```python
                self._uploader.upload(
                    event_id=event.id,
                    clip_path=clip_path,
                    metadata={
                        "camera_id": event.camera_id,
                        "label": event.label,
                        "confidence": event.confidence,
                        "bbox": event.bbox_json,
                        "t_evento": event.t_evento,
                        "trigger_type": event.trigger_type,
                    },
                )
```

- [ ] **Passo 3.6: Rodar todos os testes de uploader — verificar que passam**

```bash
python -m pytest shared/tests/test_conveyor_uploader.py shared/tests/test_upload_worker.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 3.7: Commit**

```bash
git add shared/orwell_shared/conveyor_uploader.py shared/orwell_shared/upload_worker.py shared/tests/test_conveyor_uploader.py
git commit -m "feat(uploader): propagate trigger_type to VSTP Package"
```

---

## Task 4: PeriodicFlusher

**Files:**
- Create: `services/recorder/recorder/periodic_flusher.py`
- Create: `services/recorder/tests/__init__.py`
- Create: `services/recorder/tests/test_periodic_flusher.py`

- [ ] **Passo 4.1: Criar `services/recorder/tests/__init__.py`**

Arquivo vazio:
```python
```

- [ ] **Passo 4.2: Escrever testes (devem falhar)**

Criar `services/recorder/tests/test_periodic_flusher.py`:

```python
import time
from pathlib import Path

import pytest

from orwell_shared.events import EventIndex
from recorder.periodic_flusher import PeriodicFlusher


@pytest.fixture
def setup(tmp_path):
    tmpfs = tmp_path / "shm"
    events_dir = tmp_path / "events"
    db = tmp_path / "idx.sqlite"

    # Simula buffer circular de 2 câmeras no tmpfs
    for cam in ("cam0", "cam1"):
        buf_dir = tmpfs / cam
        buf_dir.mkdir(parents=True)
        (buf_dir / "buf-0.m4s").write_bytes(b"SEGMENT0-" + cam.encode())
        (buf_dir / "buf-1.m4s").write_bytes(b"SEGMENT1-" + cam.encode())

    idx = EventIndex(db)
    return tmpfs, events_dir, idx


def test_flush_copies_buffer_files(setup, tmp_path):
    tmpfs, events_dir, idx = setup
    cameras = ["cam0", "cam1"]
    flusher = PeriodicFlusher(
        cameras=cameras,
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=True,
    )
    flusher._flush_all()

    pending = idx.pending_uploads()
    assert len(pending) == 2  # um evento por câmera
    for ev in pending:
        assert ev.trigger_type == "periodic"
        assert ev.label == "periodic"
        clip_dir = Path(ev.clip_path)
        assert (clip_dir / "buf-0.m4s").exists()


def test_flush_disabled_does_nothing(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=False,
    )
    flusher._flush_all()
    assert idx.pending_uploads() == []


def test_flusher_runs_on_timer(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=0.1,
        enabled=True,
    )
    flusher.start()
    time.sleep(0.35)
    flusher.stop()

    pending = idx.pending_uploads()
    # 0.35s / 0.1s interval => deve ter disparado ao menos 2 vezes
    assert len(pending) >= 2


def test_update_config_changes_interval(setup):
    tmpfs, events_dir, idx = setup
    flusher = PeriodicFlusher(
        cameras=["cam0"],
        tmpfs_dir=str(tmpfs),
        events_dir=str(events_dir),
        event_index=idx,
        interval_s=9999,
        enabled=False,
    )
    flusher.update_config(enabled=True, interval_s=0.1)
    flusher.start()
    time.sleep(0.35)
    flusher.stop()
    assert len(idx.pending_uploads()) >= 2
```

- [ ] **Passo 4.3: Rodar — verificar que falham**

```bash
python -m pytest services/recorder/tests/test_periodic_flusher.py -v
```
Esperado: `ModuleNotFoundError: No module named 'recorder.periodic_flusher'`

- [ ] **Passo 4.4: Criar `services/recorder/recorder/periodic_flusher.py`**

```python
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from orwell_shared.events import Event, EventIndex
from recorder.event_handler import flush_event_buffer


class PeriodicFlusher:
    def __init__(
        self,
        cameras: list[str],
        tmpfs_dir: str,
        events_dir: str,
        event_index: EventIndex,
        interval_s: float,
        enabled: bool,
    ) -> None:
        self._cameras = cameras
        self._tmpfs_dir = tmpfs_dir
        self._events_dir = events_dir
        self._index = event_index
        self._lock = threading.Lock()
        self._interval_s = interval_s
        self._enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PeriodicFlusher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def update_config(self, enabled: bool, interval_s: float) -> None:
        with self._lock:
            self._enabled = enabled
            self._interval_s = interval_s

    def _loop(self) -> None:
        last_flush = 0.0
        while not self._stop.wait(1.0):
            now = time.time()
            with self._lock:
                enabled = self._enabled
                interval = self._interval_s
            if enabled and (now - last_flush) >= interval:
                try:
                    self._flush_all()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("periodic flush error")
                last_flush = now

    def _flush_all(self) -> None:
        if not self._enabled:
            return
        t_now = time.time()
        for camera_id in self._cameras:
            event_id = str(uuid.uuid4())
            clip_files = flush_event_buffer(
                tmpfs_dir=self._tmpfs_dir,
                events_dir=self._events_dir,
                event_id=event_id,
                camera_id=camera_id,
            )
            if not clip_files:
                continue
            clip_path = str(clip_files[0].parent)
            self._index.add_event(Event(
                id=event_id,
                camera_id=camera_id,
                t_evento=t_now,
                label="periodic",
                confidence=1.0,
                clip_path=clip_path,
                trigger_type="periodic",
            ))
```

- [ ] **Passo 4.5: Rodar testes do PeriodicFlusher — verificar que passam**

```bash
python -m pytest services/recorder/tests/test_periodic_flusher.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 4.6: Commit**

```bash
git add services/recorder/recorder/periodic_flusher.py services/recorder/tests/
git commit -m "feat(recorder): PeriodicFlusher — timer-based circular buffer flush"
```

---

## Task 5: ConfigWatcher

**Files:**
- Create: `shared/orwell_shared/config_watcher.py`
- Create: `shared/tests/test_config_watcher.py`

- [ ] **Passo 5.1: Escrever testes (devem falhar)**

Criar `shared/tests/test_config_watcher.py`:

```python
import threading
import time

import pytest
import yaml

from orwell_shared.config_watcher import ConfigWatcher


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "orwell.yaml"
    path.write_text(yaml.dump({"conveyor": {"periodic_upload_interval_s": 600}}))
    return path


def test_watcher_calls_callback_on_file_change(config_file):
    calls = []

    def on_change(cfg):
        calls.append(cfg.conveyor.periodic_upload_interval_s)

    watcher = ConfigWatcher(config_file, on_change, poll_interval_s=0.05)
    watcher.start()
    time.sleep(0.1)

    # Modifica o arquivo
    config_file.write_text(yaml.dump({"conveyor": {"periodic_upload_interval_s": 120}}))
    time.sleep(0.15)
    watcher.stop()

    assert 120 in calls


def test_watcher_does_not_call_when_unchanged(config_file):
    calls = []

    def on_change(cfg):
        calls.append(cfg)

    watcher = ConfigWatcher(config_file, on_change, poll_interval_s=0.05)
    watcher.start()
    time.sleep(0.2)
    watcher.stop()

    assert calls == []
```

- [ ] **Passo 5.2: Rodar — verificar que falham**

```bash
python -m pytest shared/tests/test_config_watcher.py -v
```
Esperado: `ModuleNotFoundError: No module named 'orwell_shared.config_watcher'`

- [ ] **Passo 5.3: Criar `shared/orwell_shared/config_watcher.py`**

```python
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from orwell_shared.config import OrwellConfig, load_config

logger = logging.getLogger(__name__)


class ConfigWatcher:
    def __init__(
        self,
        config_path: str | Path,
        on_change: Callable[[OrwellConfig], None],
        poll_interval_s: float = 30.0,
    ) -> None:
        self._path = Path(config_path)
        self._on_change = on_change
        self._poll_interval = poll_interval_s
        self._last_mtime: float = self._path.stat().st_mtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ConfigWatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_interval):
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    cfg = load_config(self._path)
                    self._on_change(cfg)
            except Exception:
                logger.exception("config watcher error")
```

- [ ] **Passo 5.4: Rodar testes do ConfigWatcher — verificar que passam**

```bash
python -m pytest shared/tests/test_config_watcher.py -v
```
Esperado: todos `PASSED`

- [ ] **Passo 5.5: Commit**

```bash
git add shared/orwell_shared/config_watcher.py shared/tests/test_config_watcher.py
git commit -m "feat(shared): ConfigWatcher — hot-reload orwell.yaml sem restart"
```

---

## Task 6: Recorder main.py — PeriodicFlusher + ConfigWatcher, remove UploadWorker

**Files:**
- Modify: `services/recorder/recorder/main.py`

- [ ] **Passo 6.1: Atualizar `services/recorder/recorder/main.py`**

Substituir o conteúdo completo do arquivo pelo seguinte (as mudanças são: importar `PeriodicFlusher` e `ConfigWatcher`; remover o bloco `if config.conveyor.enabled` que instancia `UploadWorker`; adicionar `PeriodicFlusher` e `ConfigWatcher` na função `main()`):

```python
"""Recorder do Orwell — roda NO JETSON (JetPack/DeepStream).

Pipeline de 3 branches por câmera:
  A — DVR: encode baixo bitrate → NVMe (longa retenção)
  B — IA: scale 640×360 → TensorRT (só se ai.enabled)
  C — Event buffer: encode alto bitrate → tmpfs circular (só se event_buffer.enabled)

Quando nvinfer (branch B) detecta um evento com confiança >= threshold:
  - flush do buffer C → /events/<id>/
  - persiste no EventIndex (SQLite)

⚠️ Requer GStreamer + plugins NVIDIA (gi/Gst) — só executa no Jetson.
Os imports de `gi` e `pyds` são tardios para o pacote ser importável em máquinas sem GStreamer.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from orwell_shared.config import load_config
from orwell_shared.config_watcher import ConfigWatcher
from orwell_shared.events import EventIndex
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import segment_path

from .event_handler import handle_detection
from .indexer import run_once
from .periodic_flusher import PeriodicFlusher
from .pipeline import (
    ai_scale_chain,
    build_raw_source,
    dvr_encoder_chain,
    event_buffer_encoder_chain,
    max_size_time_ns,
    preview_branch,
)

INDEXER_PERIOD_S = 2.0


def _make_format_location_cb(data_dir: str, camera_id: str):
    """Callback do splitmuxsink DVR: nomeia cada fragmento como seg-<epoch_ms>.m4s."""
    def _cb(_splitmux, _fragment_id, *_args):
        epoch_ms = int(time.time() * 1000)
        path = segment_path(data_dir, camera_id, epoch_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return _cb


def _make_buf_format_location_cb(tmpfs_dir: str, camera_id: str):
    """Callback do splitmuxsink do event buffer: alterna entre buf-0.m4s e buf-1.m4s."""
    buf_dir = Path(tmpfs_dir) / camera_id
    buf_dir.mkdir(parents=True, exist_ok=True)
    count = [0]

    def _cb(_splitmux, _fragment_id, *_args):
        idx = count[0] % 2
        count[0] += 1
        return str(buf_dir / f"buf-{idx}.m4s")
    return _cb


def _build_camera_bin(Gst, camera, profile, ai_cfg, event_buf_cfg, preview_cfg, data_dir: str):
    """Pipeline de 3 branches para uma câmera."""
    dvr_sink_desc = (
        "splitmuxsink name=dvr_sink "
        f"max-size-time={max_size_time_ns(profile)} "
        'muxer-factory=mp4mux '
        'muxer-properties="properties,fragment-duration=1000,faststart=true"'
    )

    desc = build_raw_source(camera, profile) + " ! tee name=t "
    desc += f"t. ! queue ! {dvr_encoder_chain(profile)} ! {dvr_sink_desc} "

    if event_buf_cfg.enabled:
        buf_seg_ns = int((event_buf_cfg.buffer_seconds / 2) * 1_000_000_000)
        buf_sink_desc = (
            "splitmuxsink name=buf_sink "
            f"max-size-time={buf_seg_ns} "
            'muxer-factory=mp4mux '
            'muxer-properties="properties,fragment-duration=1000,faststart=true"'
        )
        desc += (
            f"t. ! queue ! "
            f"{event_buffer_encoder_chain(profile, event_buf_cfg.bitrate_kbps)} ! "
            f"{buf_sink_desc} "
        )

    if ai_cfg.enabled:
        desc += (
            f"t. ! queue ! "
            f"{ai_scale_chain(ai_cfg.input_width, ai_cfg.input_height, ai_cfg.inference_fps)} ! "
            f"nvinfer config-file-path={ai_cfg.model_path} name=ai_infer "
        )

    preview_chain = preview_branch(preview_cfg, camera.id)
    if preview_chain:
        desc += f"t. ! queue ! {preview_chain} "

    pipeline = Gst.parse_launch(desc)

    dvr = pipeline.get_by_name("dvr_sink")
    dvr.connect("format-location-full", _make_format_location_cb(data_dir, camera.id))

    if event_buf_cfg.enabled:
        buf = pipeline.get_by_name("buf_sink")
        buf.connect("format-location-full",
                    _make_buf_format_location_cb(event_buf_cfg.tmpfs_dir, camera.id))

    return pipeline


def _wire_ai_probe(Gst, pipeline, camera, config, event_index: EventIndex) -> None:
    """Conecta probe pyds no nvinfer para disparar handle_detection em cada detecção."""
    ai_infer = pipeline.get_by_name("ai_infer")
    if not ai_infer:
        return
    try:
        import pyds
    except ImportError:
        print("recorder: pyds não disponível — probe de IA desativado", flush=True)
        return

    sink_pad = ai_infer.get_static_pad("sink")

    def _make_probe(cam_id: str):
        def _probe(_pad, info):
            buf = info.get_buffer()
            batch = pyds.gst_buffer_get_nvds_batch_meta(buf.__hash__())
            l_frame = batch.frame_meta_list
            while l_frame:
                frame = pyds.NvDsFrameMeta.cast(l_frame.data)
                l_obj = frame.obj_meta_list
                while l_obj:
                    obj = pyds.NvDsObjectMeta.cast(l_obj.data)
                    if obj.confidence >= config.ai.confidence_threshold:
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
                    try:
                        l_obj = l_obj.next
                    except StopIteration:
                        break
                try:
                    l_frame = l_frame.next
                except StopIteration:
                    break
            return Gst.PadProbeReturn.OK
        return _probe

    sink_pad.add_probe(Gst.PadProbeType.BUFFER, _make_probe(camera.id))


def _indexer_loop(index: SegmentIndex, config, stop: threading.Event) -> None:
    known: dict[str, set[str]] = {}
    while not stop.is_set():
        try:
            run_once(index, config, known)
        except Exception as exc:  # noqa: BLE001
            print(f"indexer error: {exc}", flush=True)
        stop.wait(INDEXER_PERIOD_S)


def _available_sensor_ids() -> set[int]:
    import glob
    devices = glob.glob("/dev/video*")
    return set(range(len(devices)))


def main() -> None:
    import gi  # import tardio (só existe no Jetson)

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)

    config_path = os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
    config = load_config(config_path)
    db_path = os.environ.get("ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite")
    index = SegmentIndex(db_path)
    event_index = EventIndex(db_path)

    sensor_ids = _available_sensor_ids()
    available = [cam for cam in config.cameras if cam.argus_sensor_id in sensor_ids]
    skipped = [cam for cam in config.cameras if cam not in available]
    for cam in skipped:
        print(f"recorder: sensor-id={cam.argus_sensor_id} não disponível, ignorando", flush=True)

    if not available:
        print("recorder: nenhuma câmera disponível, saindo", flush=True)
        return

    pipelines = [
        _build_camera_bin(
            Gst, cam, config.capture,
            config.ai, config.event_buffer, config.preview,
            config.retention.data_dir,
        )
        for cam in available
    ]

    if config.ai.enabled:
        for cam, pipeline in zip(available, pipelines):
            _wire_ai_probe(Gst, pipeline, cam, config, event_index)

    for p in pipelines:
        p.set_state(Gst.State.PLAYING)
    print(f"recorder: {len(pipelines)} câmera(s) gravando em {config.retention.data_dir}",
          flush=True)

    camera_ids = [cam.id for cam in available]
    flusher = PeriodicFlusher(
        cameras=camera_ids,
        tmpfs_dir=config.event_buffer.tmpfs_dir,
        events_dir=config.retention.events_dir,
        event_index=event_index,
        interval_s=config.conveyor.periodic_upload_interval_s,
        enabled=config.conveyor.periodic_upload_enabled and config.conveyor.enabled,
    )
    flusher.start()
    print(
        f"recorder: PeriodicFlusher iniciado "
        f"(enabled={config.conveyor.periodic_upload_enabled}, "
        f"interval={config.conveyor.periodic_upload_interval_s}s)",
        flush=True,
    )

    def _on_config_change(new_cfg) -> None:
        flusher.update_config(
            enabled=new_cfg.conveyor.periodic_upload_enabled and new_cfg.conveyor.enabled,
            interval_s=new_cfg.conveyor.periodic_upload_interval_s,
        )
        print(
            f"recorder: config recarregada — periodic interval={new_cfg.conveyor.periodic_upload_interval_s}s",
            flush=True,
        )

    watcher = ConfigWatcher(config_path, _on_config_change)
    watcher.start()

    stop = threading.Event()
    threading.Thread(target=_indexer_loop, args=(index, config, stop), daemon=True).start()

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        flusher.stop()
        watcher.stop()
        for p in pipelines:
            p.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
```

- [ ] **Passo 6.2: Rodar suite de testes geral — verificar que nada quebrou**

```bash
python -m pytest shared/tests/ services/recorder/tests/ -v
```
Esperado: todos `PASSED`

- [ ] **Passo 6.3: Commit**

```bash
git add services/recorder/recorder/main.py
git commit -m "feat(recorder): PeriodicFlusher + ConfigWatcher; move UploadWorker to uploader service"
```

---

## Task 7: Serviço `uploader`

**Files:**
- Create: `services/uploader/Dockerfile`
- Create: `services/uploader/uploader/__init__.py`
- Create: `services/uploader/uploader/main.py`

- [ ] **Passo 7.1: Criar `services/uploader/uploader/__init__.py`**

Arquivo vazio:
```python
```

- [ ] **Passo 7.2: Criar `services/uploader/uploader/main.py`**

```python
"""Uploader service — lê EventIndex (SQLite), envia via VSTP, marca como uploaded.

Roda como container separado (sem NVIDIA runtime). Compartilha volumes /data e /events
com o recorder e o clip-api via HostPath no NVMe.
"""
from __future__ import annotations

import logging
import os
import time

from orwell_shared.config import load_config
from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.conveyor_uploader import ConveyorUploader
from orwell_shared.device_id import get_ext_id
from orwell_shared.events import EventIndex
from orwell_shared.upload_worker import UploadWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("uploader")


def main() -> None:
    config_path = os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
    config = load_config(config_path)
    db_path = os.environ.get("ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite")

    if not config.conveyor.enabled:
        logger.info("conveyor.enabled=false — uploader em modo idle (aguardando config)")
        while True:
            time.sleep(60)

    gateway_ext_id = config.conveyor.gateway_ext_id
    sensor_ext_id = config.conveyor.sensor_ext_id or get_ext_id()
    logger.info("gateway_ext_id=%s sensor_ext_id=%s", gateway_ext_id, sensor_ext_id)

    client = ConveyorClient(
        host=config.conveyor.host,
        port=config.conveyor.port,
        gateway_ext_id=gateway_ext_id,
        sensor_ext_id=sensor_ext_id,
    )
    uploader = ConveyorUploader(client=client, sensor_ext_id=sensor_ext_id)
    event_index = EventIndex(db_path)

    worker = UploadWorker(
        event_index=event_index,
        uploader=uploader,
        upload_interval_s=config.conveyor.upload_interval_s,
        status_interval_s=config.conveyor.status_interval_s,
    )
    worker.start()
    logger.info(
        "UploadWorker iniciado (host=%s:%s, poll=%ss)",
        config.conveyor.host, config.conveyor.port, config.conveyor.upload_interval_s,
    )

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        worker.stop()
        logger.info("uploader parado")


if __name__ == "__main__":
    main()
```

- [ ] **Passo 7.3: Criar `services/uploader/Dockerfile`**

```dockerfile
# Build context = repo root
FROM python:3.10-slim

WORKDIR /app

COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src"

COPY services/uploader/uploader /app/uploader

CMD ["python", "-m", "uploader.main"]
```

- [ ] **Passo 7.4: Verificar que o módulo importa sem erro**

```bash
cd /Users/urielabecontardi/Documents/tractian-orwell
PYTHONPATH=shared:services/uploader python -c "from uploader.main import main; print('ok')"
```
Esperado: `ok`

- [ ] **Passo 7.5: Commit**

```bash
git add services/uploader/
git commit -m "feat(uploader): novo serviço — container leve para envio VSTP"
```

---

## Task 8: docker-compose.yml — adicionar uploader + montar config na clip-api

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Passo 8.1: Atualizar `docker-compose.yml`**

Adicionar o serviço `uploader` e montar `./config` na `clip-api`:

No serviço `clip-api`, adicionar ao bloco `environment`:
```yaml
      ORWELL_CONFIG: /app/config/orwell.yaml
```
E ao bloco `volumes`:
```yaml
      - ./config:/app/config
```

Adicionar novo serviço `uploader` após o serviço `clip-api`:
```yaml
  uploader:
    build:
      context: .
      dockerfile: services/uploader/Dockerfile
    restart: unless-stopped
    environment:
      ORWELL_INDEX_DB: /data/index.sqlite
      ORWELL_EVENTS_DIR: /events
      ORWELL_CONFIG: /app/config/orwell.yaml
    volumes:
      - ${ORWELL_DATA_DIR:-./data}:/data
      - ${ORWELL_EVENTS_DIR:-./events}:/events
      - ./config:/app/config:ro
    depends_on: []
```

- [ ] **Passo 8.2: Verificar sintaxe do docker-compose**

```bash
docker compose config --quiet
```
Esperado: sem erros

- [ ] **Passo 8.3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): adicionar serviço uploader + montar config na clip-api"
```

---

## Task 9: clip-api — GET/PATCH /config + GET /upload-stats

**Files:**
- Modify: `services/clip-api/clip_api/settings.py`
- Modify: `services/clip-api/clip_api/main.py`
- Create: `services/clip-api/tests/test_config_api.py`

- [ ] **Passo 9.1: Escrever testes (devem falhar)**

Criar `services/clip-api/tests/test_config_api.py`:

```python
import yaml
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "conveyor": {
            "enabled": True,
            "periodic_upload_enabled": True,
            "periodic_upload_interval_s": 600,
        }
    }
    p = tmp_path / "orwell.yaml"
    p.write_text(yaml.dump(cfg))
    return p


@pytest.fixture
def client(config_file, monkeypatch):
    monkeypatch.setenv("ORWELL_INDEX_DB", str(config_file.parent / "idx.sqlite"))
    monkeypatch.setenv("ORWELL_CONFIG", str(config_file))
    from clip_api.main import create_app
    return TestClient(create_app())


def test_get_config_returns_periodic_fields(client):
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert data["periodic_upload_enabled"] is True
    assert data["periodic_upload_interval_s"] == 600


def test_patch_config_updates_interval(client, config_file):
    r = client.patch("/config", json={"periodic_upload_interval_s": 300})
    assert r.status_code == 200
    assert r.json()["periodic_upload_interval_s"] == 300

    raw = yaml.safe_load(config_file.read_text())
    assert raw["conveyor"]["periodic_upload_interval_s"] == 300


def test_patch_config_rejects_invalid_interval(client):
    r = client.patch("/config", json={"periodic_upload_interval_s": 30})
    assert r.status_code == 422


def test_get_upload_stats_empty(client):
    r = client.get("/upload-stats")
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] == 0
    assert data["failed"] == 0
    assert data["last_uploaded_at"] is None
```

- [ ] **Passo 9.2: Rodar — verificar que falham**

```bash
python -m pytest services/clip-api/tests/test_config_api.py -v
```
Esperado: `FAILED` — `/config` não existe

- [ ] **Passo 9.3: Atualizar `services/clip-api/clip_api/settings.py`**

```python
from __future__ import annotations

import os


def index_db_path() -> str:
    return os.environ.get("ORWELL_INDEX_DB", "/var/lib/orwell/data/index.sqlite")


def data_dir() -> str:
    return os.environ.get("ORWELL_DATA_DIR", "/var/lib/orwell/data")


def events_dir() -> str:
    return os.environ.get("ORWELL_EVENTS_DIR", "/var/lib/orwell/events")


def config_path() -> str:
    return os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
```

- [ ] **Passo 9.4: Adicionar endpoints a `services/clip-api/clip_api/main.py`**

Adicionar ao bloco de imports do topo do arquivo apenas o que ainda não existe (`Path` já está importado):
```python
from typing import Any

import yaml
from pydantic import BaseModel, Field
```

Adicionar os modelos Pydantic e os novos endpoints dentro de `create_app()`, antes do `return app`:

```python
    from clip_api.settings import config_path as _config_path

    class ConfigPatch(BaseModel):
        periodic_upload_enabled: bool | None = None
        periodic_upload_interval_s: int | None = Field(None, ge=60, le=86400)

    @app.get("/config")
    def get_config():
        from orwell_shared.config import load_config
        cfg = load_config(_config_path())
        return {
            "periodic_upload_enabled": cfg.conveyor.periodic_upload_enabled,
            "periodic_upload_interval_s": cfg.conveyor.periodic_upload_interval_s,
        }

    @app.patch("/config")
    def patch_config(body: ConfigPatch):
        cfg_path = Path(_config_path())
        raw: dict[str, Any] = yaml.safe_load(cfg_path.read_text()) or {}
        conv = raw.setdefault("conveyor", {})
        if body.periodic_upload_enabled is not None:
            conv["periodic_upload_enabled"] = body.periodic_upload_enabled
        if body.periodic_upload_interval_s is not None:
            conv["periodic_upload_interval_s"] = body.periodic_upload_interval_s
        cfg_path.write_text(yaml.dump(raw))
        from orwell_shared.config import load_config
        cfg = load_config(cfg_path)
        return {
            "periodic_upload_enabled": cfg.conveyor.periodic_upload_enabled,
            "periodic_upload_interval_s": cfg.conveyor.periodic_upload_interval_s,
        }

    @app.get("/upload-stats")
    def upload_stats():
        return event_index.upload_stats()
```

- [ ] **Passo 9.5: Rodar testes da clip-api — verificar que passam**

```bash
python -m pytest services/clip-api/tests/ -v
```
Esperado: todos `PASSED`

- [ ] **Passo 9.6: Commit**

```bash
git add services/clip-api/clip_api/settings.py services/clip-api/clip_api/main.py services/clip-api/tests/test_config_api.py
git commit -m "feat(clip-api): GET/PATCH /config + GET /upload-stats"
```

---

## Task 10: Dashboard — painel de configuração

**Files:**
- Modify: `services/dashboard/dashboard/page.html`

- [ ] **Passo 10.1: Adicionar card de configuração ao `page.html`**

No `page.html`, dentro da `<div class="container">`, adicionar o seguinte card logo antes do fechamento da `</div>` principal do container:

```html
<!-- Config Card -->
<div class="card" id="config-card">
  <div class="card-header">Configuração de Upload</div>
  <div class="card-body" style="display:flex;flex-direction:column;gap:1rem;">
    <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
      <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
        <input type="checkbox" id="periodic-enabled" style="width:1rem;height:1rem;">
        <span style="font-size:0.875rem;">Upload periódico ativo</span>
      </label>
      <div style="display:flex;align-items:center;gap:0.5rem;">
        <span style="font-size:0.8rem;color:#94a3b8;">Intervalo (min):</span>
        <input type="number" id="periodic-interval" min="1" max="1440"
          style="width:80px;background:#0f1117;border:1px solid #1e2a3a;color:#e2e8f0;padding:0.3rem 0.6rem;border-radius:5px;font-size:0.875rem;">
      </div>
      <button class="btn btn-primary" onclick="saveConfig()">Salvar</button>
      <span id="config-status" style="font-size:0.8rem;color:#64748b;"></span>
    </div>
    <div style="display:flex;gap:2rem;font-size:0.8rem;color:#64748b;">
      <span>Pendentes: <strong id="stat-pending" style="color:#f59e0b;">—</strong></span>
      <span>Falhas: <strong id="stat-failed" style="color:#ef4444;">—</strong></span>
      <span>Último envio: <strong id="stat-last" style="color:#10b981;">—</strong></span>
    </div>
  </div>
</div>
```

- [ ] **Passo 10.2: Adicionar JS de configuração ao `page.html`**

Dentro da tag `<script>` existente (ou criar nova antes do `</body>`), adicionar:

```javascript
async function loadConfig() {
  try {
    const [cfgRes, statsRes] = await Promise.all([
      fetch(`${CLIP_API}/config`),
      fetch(`${CLIP_API}/upload-stats`)
    ]);
    if (cfgRes.ok) {
      const cfg = await cfgRes.json();
      document.getElementById('periodic-enabled').checked = cfg.periodic_upload_enabled;
      document.getElementById('periodic-interval').value = Math.round(cfg.periodic_upload_interval_s / 60);
    }
    if (statsRes.ok) {
      const stats = await statsRes.json();
      document.getElementById('stat-pending').textContent = stats.pending;
      document.getElementById('stat-failed').textContent = stats.failed;
      document.getElementById('stat-last').textContent =
        stats.last_uploaded_at
          ? new Date(stats.last_uploaded_at * 1000).toLocaleTimeString('pt-BR')
          : 'nunca';
    }
  } catch (e) { console.warn('loadConfig error', e); }
}

async function saveConfig() {
  const enabled = document.getElementById('periodic-enabled').checked;
  const minutes = parseInt(document.getElementById('periodic-interval').value, 10);
  const status = document.getElementById('config-status');
  status.textContent = 'Salvando...';
  try {
    const r = await fetch(`${CLIP_API}/config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        periodic_upload_enabled: enabled,
        periodic_upload_interval_s: minutes * 60
      })
    });
    if (r.ok) {
      status.textContent = 'Salvo ✓';
      status.style.color = '#10b981';
    } else {
      status.textContent = `Erro ${r.status}`;
      status.style.color = '#ef4444';
    }
  } catch (e) {
    status.textContent = 'Falha de rede';
    status.style.color = '#ef4444';
  }
  setTimeout(() => { status.textContent = ''; }, 3000);
}

// Carrega config e stats ao abrir; atualiza stats a cada 30s
loadConfig();
setInterval(loadConfig, 30000);
```

- [ ] **Passo 10.3: Verificar que `CLIP_API` está disponível no escopo do JS**

Procurar no `page.html` pela variável que recebe a URL da clip-api. Ela deve estar declarada como:
```javascript
const CLIP_API = "__CLIP_API_URL__";
```
`dashboard/main.py` substitui `__CLIP_API_URL__` pelo valor de `CLIP_API_URL` do ambiente ao servir a página.
Se o nome da variável no arquivo for diferente (ex: `clipApiUrl`), ajustar o JS adicionado no Passo 10.2 para usar o mesmo nome.

- [ ] **Passo 10.4: Commit**

```bash
git add services/dashboard/dashboard/page.html
git commit -m "feat(dashboard): painel de configuração de upload periódico"
```

---

## Task 11: config.proto — RemoteConfig

**Files:**
- Create: `shared/proto/remote_config.proto`
- Create: `shared/orwell_shared/remote_config_pb2.py` (gerado)

- [ ] **Passo 11.1: Criar diretório e proto**

```bash
mkdir -p shared/proto
```

Criar `shared/proto/remote_config.proto`:

```protobuf
syntax = "proto3";

package orwell.config.v1;

// Subconjunto de OrwellConfig que pode ser empurrado remotamente pelo Conveyor.
// Campos de hardware (câmeras, codec, sensor IDs) ficam fora — exigem redeploy.
message RemoteConfig {
  bool   periodic_upload_enabled    = 1;
  uint32 periodic_upload_interval_s = 2;
  uint32 buffer_seconds             = 3;

  // Reservado para fase AI:
  // float  confidence_threshold  = 10;
  // string model_path            = 11;
  // uint32 inference_fps         = 12;
}
```

- [ ] **Passo 11.2: Gerar `remote_config_pb2.py`**

```bash
cd /Users/urielabecontardi/Documents/tractian-orwell
python -m grpc_tools.protoc \
  -I shared/proto \
  --python_out=shared/orwell_shared \
  shared/proto/remote_config.proto
```

Verificar que o arquivo foi gerado:
```bash
ls shared/orwell_shared/remote_config_pb2.py
```

- [ ] **Passo 11.3: Verificar que o proto importa**

```bash
PYTHONPATH=shared python -c "from orwell_shared.remote_config_pb2 import RemoteConfig; print('ok')"
```
Esperado: `ok`

- [ ] **Passo 11.4: Commit**

```bash
git add shared/proto/remote_config.proto shared/orwell_shared/remote_config_pb2.py
git commit -m "feat(proto): RemoteConfig — subconjunto de config para push remoto futuro"
```

---

## Task 12: Smoke test final

- [ ] **Passo 12.1: Rodar suite completa**

```bash
python -m pytest shared/tests/ services/clip-api/tests/ services/recorder/tests/ -v
```
Esperado: todos `PASSED`, zero `FAILED`

- [ ] **Passo 12.2: Verificar sintaxe do docker-compose**

```bash
docker compose config --quiet
```
Esperado: sem erros

- [ ] **Passo 12.3: Commit final de verificação (se houver arquivos pendentes)**

```bash
git status
# Se limpo:
echo "Tudo commitado."
```
