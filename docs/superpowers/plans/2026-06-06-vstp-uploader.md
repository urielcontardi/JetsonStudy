# VSTP Uploader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar envio automático de clips de eventos de IA para o Conveyor via VSTP usando as rotas de desenvolvimento (`pdevsample`, `pdevstatus`).

**Architecture:** Background thread daemon faz poll do SQLite (`uploaded_at IS NULL`), serializa cada evento como `samples.v2.Package` protobuf, envia via TCP para o Conveyor, e marca como enviado. O pipeline GStreamer nunca bloqueia — toda a I/O de rede fica no worker thread.

**Tech Stack:** Python 3.10, `protobuf` (google.protobuf), `blake3`, `grpcio-tools` (dev), SQLite, TCP socket.

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `proto/vstp.proto` | criar | RequestHeader / ResponseHeader com field numbers corretos |
| `proto/gateway.proto` | criar | GetTokenResponseBody |
| `shared/orwell_shared/vstp_pb2.py` | gerar + commitar | framing TCP |
| `shared/orwell_shared/gateway_pb2.py` | gerar + commitar | auth token |
| `shared/orwell_shared/samples_pb2.py` | gerar + commitar | envelope Package |
| `shared/orwell_shared/vstp.py` | criar | encode_request_header / decode_response_header |
| `shared/orwell_shared/conveyor_client.py` | criar | auth BLAKE3 + TCP transport |
| `shared/orwell_shared/conveyor_uploader.py` | criar | serializa Package + chama client |
| `shared/orwell_shared/upload_worker.py` | criar | thread daemon de poll + status |
| `shared/orwell_shared/uploader.py` | modificar | remover `async` do Protocol |
| `shared/orwell_shared/config.py` | modificar | adicionar `ConveyorConfig` |
| `shared/orwell_shared/events.py` | modificar | adicionar `pending_uploads()` e `mark_uploaded()` |
| `pyproject.toml` | modificar | adicionar deps |
| `services/recorder/recorder/main.py` | modificar | instanciar e arrancar worker |
| `shared/tests/test_vstp_framing.py` | criar | testes de framing |
| `shared/tests/test_conveyor_client.py` | criar | testes de auth + transport |
| `shared/tests/test_conveyor_uploader.py` | criar | testes de serialização Package |
| `shared/tests/test_upload_worker.py` | criar | testes do worker |

---

## Task 1: Proto files e geração de bindings

**Files:**
- Create: `proto/vstp.proto`
- Create: `proto/gateway.proto`
- Create: `shared/orwell_shared/vstp_pb2.py` (gerado)
- Create: `shared/orwell_shared/gateway_pb2.py` (gerado)
- Create: `shared/orwell_shared/samples_pb2.py` (gerado)
- Modify: `pyproject.toml`

- [ ] **Step 1: Adicionar dependências ao `pyproject.toml`**

Editar `pyproject.toml`:

```toml
[project]
name = "orwell-shared"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "protobuf>=4.25",
    "blake3>=0.3.3",
]

[project.optional-dependencies]
clip-api = ["fastapi>=0.110", "uvicorn>=0.29"]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "grpcio-tools>=1.60",
]
```

- [ ] **Step 2: Criar `proto/vstp.proto`**

Os field numbers foram extraídos do vendor Go do Conveyor (`tractian-iot-proto/gen/go/v4/protocol/vstp/v1`):

```proto
syntax = "proto3";

message VstpRequestHeader {
  string req = 1;
  // field 2 reservado internamente
  uint32 body_length = 3;
  // field 4 = keep_connection (não usado)
  bytes iv = 5;
  // fields 6-11 não usados para dev routes
  bool keep_alive = 12;
}

message VstpResponseHeader {
  string res = 1;
  uint32 body_length = 2;
  bytes iv = 3;
}
```

- [ ] **Step 3: Criar `proto/gateway.proto`**

Fields extraídos do vendor Go (`tractian-iot-proto/gen/go/v4/sensor/gateway/v1`):

```proto
syntax = "proto3";

message GetTokenResponseBody {
  string token = 1;
  uint32 salt = 2;
  uint32 length = 3;
  uint32 num_requests = 4;
}
```

- [ ] **Step 4: Instalar grpcio-tools e gerar os bindings**

```bash
pip install grpcio-tools

# Gerar vstp_pb2.py e gateway_pb2.py
python -m grpc_tools.protoc \
  -I proto/ \
  --python_out=shared/orwell_shared \
  proto/vstp.proto proto/gateway.proto

# Gerar samples_pb2.py (samples.proto está na raiz)
GOOGLE_PROTO=$(python -c "import grpc_tools, os; print(os.path.dirname(grpc_tools.__file__) + '/_proto')")
python -m grpc_tools.protoc \
  -I . \
  -I "$GOOGLE_PROTO" \
  --python_out=shared/orwell_shared \
  samples.proto
```

Verificar que os três arquivos foram criados:
```bash
ls shared/orwell_shared/vstp_pb2.py shared/orwell_shared/gateway_pb2.py shared/orwell_shared/samples_pb2.py
```
Expected: todos listados sem erro.

- [ ] **Step 5: Smoke test dos bindings**

```bash
cd shared && python -c "
from orwell_shared.vstp_pb2 import VstpRequestHeader, VstpResponseHeader
from orwell_shared.gateway_pb2 import GetTokenResponseBody
from orwell_shared.samples_pb2 import Package, Parameter, TriggerType

h = VstpRequestHeader()
h.req = 'ping'
h.body_length = 0
h.keep_alive = False
data = h.SerializeToString()
h2 = VstpRequestHeader()
h2.ParseFromString(data)
assert h2.req == 'ping', f'got {h2.req}'

p = Package()
p.format = 'orwell.video-clip.v1'
p.trigger_type = TriggerType.Value('TRIGGER_TYPE_EVENT')
assert p.SerializeToString()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add proto/ shared/orwell_shared/vstp_pb2.py shared/orwell_shared/gateway_pb2.py shared/orwell_shared/samples_pb2.py pyproject.toml
git commit -m "feat(proto): add vstp/gateway/samples proto bindings"
```

---

## Task 2: `vstp.py` — framing TCP

**Files:**
- Create: `shared/orwell_shared/vstp.py`
- Create: `shared/tests/test_vstp_framing.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `shared/tests/test_vstp_framing.py`:

```python
from orwell_shared.vstp import encode_request_header, decode_response_header
from orwell_shared.vstp_pb2 import VstpResponseHeader


def _make_response(res: str, body: bytes = b"") -> bytes:
    """Monta um frame de resposta VSTP válido."""
    h = VstpResponseHeader()
    h.res = res
    h.body_length = len(body)
    h_bytes = h.SerializeToString()
    return bytes([len(h_bytes)]) + h_bytes + body


def test_encode_ping():
    frame = encode_request_header("ping", b"")
    # 1 byte header size + header bytes + 0 body bytes
    assert len(frame) >= 2
    header_size = frame[0]
    assert header_size > 0


def test_encode_with_body():
    body = b"hello world"
    frame = encode_request_header("pdevsample:abc:secret:abc", body)
    header_size = frame[0]
    # frame = [size][header][body]
    assert frame[1 + header_size:] == body


def test_decode_ok_no_body():
    raw = _make_response("OK")
    res, body = decode_response_header(raw)
    assert res == "OK"
    assert body == b""


def test_decode_ok_with_body():
    raw = _make_response("OK", b"\x0a\x05token")
    res, body = decode_response_header(raw)
    assert res == "OK"
    assert body == b"\x0a\x05token"


def test_decode_error_response():
    raw = _make_response("FailToAuth")
    res, body = decode_response_header(raw)
    assert res == "FailToAuth"
    assert body == b""


def test_roundtrip_req_field():
    """O campo req do header deve ser preservado na serialização."""
    from orwell_shared.vstp_pb2 import VstpRequestHeader
    frame = encode_request_header("pdevsample:aabbccdd:mysecret:aabbccdd", b"payload")
    header_size = frame[0]
    h = VstpRequestHeader()
    h.ParseFromString(frame[1:1 + header_size])
    assert h.req == "pdevsample:aabbccdd:mysecret:aabbccdd"
    assert h.body_length == len(b"payload")
    assert h.keep_alive is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd shared && python -m pytest tests/test_vstp_framing.py -v
```
Expected: `ModuleNotFoundError: No module named 'orwell_shared.vstp'`

- [ ] **Step 3: Implementar `shared/orwell_shared/vstp.py`**

```python
from __future__ import annotations

from orwell_shared.vstp_pb2 import VstpRequestHeader, VstpResponseHeader


def encode_request_header(req: str, body: bytes) -> bytes:
    header = VstpRequestHeader()
    header.req = req
    header.body_length = len(body)
    header.keep_alive = False
    header_bytes = header.SerializeToString()
    return bytes([len(header_bytes)]) + header_bytes + body


def decode_response_header(data: bytes) -> tuple[str, bytes]:
    if not data:
        raise ValueError("empty VSTP response")
    header_size = data[0]
    header = VstpResponseHeader()
    header.ParseFromString(data[1 : 1 + header_size])
    body = data[1 + header_size :]
    return header.res, body
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd shared && python -m pytest tests/test_vstp_framing.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/vstp.py shared/tests/test_vstp_framing.py
git commit -m "feat(vstp): TCP framing encode/decode"
```

---

## Task 3: `ConveyorConfig` e ajuste do `UploaderBackend`

**Files:**
- Modify: `shared/orwell_shared/config.py`
- Modify: `shared/orwell_shared/uploader.py`

- [ ] **Step 1: Adicionar `ConveyorConfig` a `config.py`**

Adicionar ao final de `shared/orwell_shared/config.py`, antes de `OrwellConfig`:

```python
class ConveyorConfig(BaseModel):
    enabled: bool = False
    host: str = "conveyor.tractian.com"
    port: int = 8080
    ext_id: str = ""
    upload_interval_s: int = 30
    status_interval_s: int = 300
```

E adicionar o campo em `OrwellConfig`:

```python
class OrwellConfig(BaseModel):
    device_name: str = "orwell-dev"
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureProfile = Field(default_factory=CaptureProfile)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    event_buffer: EventBufferConfig = Field(default_factory=EventBufferConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
    conveyor: ConveyorConfig = Field(default_factory=ConveyorConfig)
```

- [ ] **Step 2: Tornar `UploaderBackend.upload` síncrono**

Editar `shared/orwell_shared/uploader.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class UploaderBackend(Protocol):
    def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        """Envia o clip do evento para a nuvem. Retorna a URI do clip."""
        ...
```

- [ ] **Step 3: Verificar que os testes existentes continuam passando**

```bash
cd shared && python -m pytest tests/ -v
```
Expected: todos os testes existentes passam.

- [ ] **Step 4: Commit**

```bash
git add shared/orwell_shared/config.py shared/orwell_shared/uploader.py
git commit -m "feat(config): add ConveyorConfig; make UploaderBackend sync"
```

---

## Task 4: `EventIndex.pending_uploads()` e `mark_uploaded()`

**Files:**
- Modify: `shared/orwell_shared/events.py`
- Modify: `shared/tests/test_events.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao final de `shared/tests/test_events.py` (inspecionar o arquivo existente antes para não duplicar fixtures):

```python
import time
from orwell_shared.events import Event, EventIndex


def _make_index(tmp_path):
    return EventIndex(tmp_path / "events.db")


def _add_event(index: EventIndex, event_id: str = "evt-1", camera_id: str = "cam0") -> Event:
    event = Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=time.time(),
        label="pessoa",
        confidence=0.9,
        clip_path="/tmp/events/" + event_id,
    )
    index.add_event(event)
    return event


def test_pending_uploads_returns_events_with_null_uploaded_at(tmp_path):
    index = _make_index(tmp_path)
    evt = _add_event(index)
    pending = index.pending_uploads()
    assert len(pending) == 1
    assert pending[0].id == evt.id


def test_pending_uploads_excludes_already_uploaded(tmp_path):
    index = _make_index(tmp_path)
    evt = _add_event(index)
    index.mark_uploaded(evt.id)
    pending = index.pending_uploads()
    assert len(pending) == 0


def test_pending_uploads_excludes_permanent_failures(tmp_path):
    index = _make_index(tmp_path)
    evt = _add_event(index)
    index.mark_upload_failed(evt.id)
    pending = index.pending_uploads()
    assert len(pending) == 0


def test_mark_uploaded_sets_timestamp(tmp_path):
    index = _make_index(tmp_path)
    evt = _add_event(index)
    before = time.time()
    index.mark_uploaded(evt.id)
    after = time.time()
    updated = index.get(evt.id)
    assert updated.uploaded_at is not None
    assert before <= updated.uploaded_at <= after


def test_pending_uploads_multiple_events(tmp_path):
    index = _make_index(tmp_path)
    _add_event(index, "evt-1")
    _add_event(index, "evt-2")
    _add_event(index, "evt-3")
    index.mark_uploaded("evt-2")
    pending = index.pending_uploads()
    ids = {e.id for e in pending}
    assert ids == {"evt-1", "evt-3"}
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd shared && python -m pytest tests/test_events.py -v -k "pending_uploads or mark_uploaded or mark_upload_failed"
```
Expected: `AttributeError: 'EventIndex' object has no attribute 'pending_uploads'`

- [ ] **Step 3: Implementar os métodos em `shared/orwell_shared/events.py`**

Adicionar ao final da classe `EventIndex`:

```python
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
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd shared && python -m pytest tests/test_events.py -v
```
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/events.py shared/tests/test_events.py
git commit -m "feat(events): add pending_uploads, mark_uploaded, mark_upload_failed"
```

---

## Task 5: `ConveyorClient` — auth BLAKE3 + TCP transport

**Files:**
- Create: `shared/orwell_shared/conveyor_client.py`
- Create: `shared/tests/test_conveyor_client.py`

- [ ] **Step 1: Escrever os testes que falham**

Criar `shared/tests/test_conveyor_client.py`:

```python
import socketserver
import threading
import time

import pytest
from blake3 import blake3

from orwell_shared.vstp import encode_request_header, decode_response_header
from orwell_shared.vstp_pb2 import VstpResponseHeader
from orwell_shared.gateway_pb2 import GetTokenResponseBody
from orwell_shared.conveyor_client import ConveyorClient


def _make_ok_response(body: bytes = b"") -> bytes:
    h = VstpResponseHeader()
    h.res = "OK"
    h.body_length = len(body)
    h_bytes = h.SerializeToString()
    return bytes([len(h_bytes)]) + h_bytes + body


def _make_token_body(token="tok", salt=0, length=10, num_requests=100) -> bytes:
    tb = GetTokenResponseBody()
    tb.token = token
    tb.salt = salt
    tb.length = length
    tb.num_requests = num_requests
    return tb.SerializeToString()


class _MockConveyor(socketserver.BaseRequestHandler):
    """Mock TCP handler: lê um frame VSTP completo (header + body) e responde."""

    responses: list  # lista de bytes para responder em ordem

    def handle(self):
        from orwell_shared.vstp_pb2 import VstpRequestHeader

        # Ler 1 byte de tamanho do header
        size_byte = self.request.recv(1)
        if not size_byte:
            return
        header_size = size_byte[0]

        # Ler bytes do header
        header_data = b""
        while len(header_data) < header_size:
            chunk = self.request.recv(header_size - len(header_data))
            if not chunk:
                return
            header_data += chunk

        # Parse para obter body_length
        req_header = VstpRequestHeader()
        req_header.ParseFromString(header_data)

        # Ler body
        remaining = req_header.body_length
        while remaining > 0:
            chunk = self.request.recv(min(remaining, 4096))
            if not chunk:
                break
            remaining -= len(chunk)

        # Responder
        if _MockConveyor.responses:
            response = _MockConveyor.responses.pop(0)
        else:
            response = _make_ok_response()
        self.request.sendall(response)


def _start_mock_server(responses: list) -> tuple[socketserver.TCPServer, int]:
    _MockConveyor.responses = responses
    server = socketserver.TCPServer(("127.0.0.1", 0), _MockConveyor)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    return server, port


def test_ping_returns_true():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt response
        _make_ok_response(),             # ping response
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        result = client.ping()
        assert result is True
    finally:
        server.shutdown()


def test_send_dev_sample_does_not_raise():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt
        _make_ok_response(),             # pdevsample
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        client.send_dev_sample(b"fake-package-bytes")
    finally:
        server.shutdown()


def test_send_dev_status_does_not_raise():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt
        _make_ok_response(),             # pdevstatus
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        client.send_dev_status(b"fake-status-bytes")
    finally:
        server.shutdown()


def test_secret_derivation_matches_emulator_logic():
    ext_id = "aabbccddee00"
    token = "mytoken123"
    salt = 2
    length = 8

    blake3_hash = blake3(ext_id.encode()).hexdigest()
    hash_input = blake3_hash + token
    expected_secret = blake3(hash_input.encode()).hexdigest()[salt : salt + length]

    token_bytes = _make_token_body(token=token, salt=salt, length=length, num_requests=10)
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),
        _make_ok_response(),
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, ext_id)
        secret = client._get_secret()
        assert secret == expected_secret
    finally:
        server.shutdown()


def test_raises_on_auth_failure():
    h = VstpResponseHeader()
    h.res = "FailToAuth"
    h_bytes = h.SerializeToString()
    fail_response = bytes([len(h_bytes)]) + h_bytes

    server, port = _start_mock_server([fail_response])
    try:
        with pytest.raises(RuntimeError, match="Auth failed"):
            ConveyorClient("127.0.0.1", port, "aabbccddee00")
    finally:
        server.shutdown()
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd shared && python -m pytest tests/test_conveyor_client.py -v
```
Expected: `ModuleNotFoundError: No module named 'orwell_shared.conveyor_client'`

- [ ] **Step 3: Implementar `shared/orwell_shared/conveyor_client.py`**

```python
from __future__ import annotations

import socket
import threading

from blake3 import blake3

from orwell_shared.gateway_pb2 import GetTokenResponseBody
from orwell_shared.vstp import decode_response_header, encode_request_header


class ConveyorClient:
    def __init__(
        self,
        host: str,
        port: int,
        ext_id: str,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._ext_id = ext_id
        self._timeout = timeout
        self._blake3_hash = blake3(ext_id.encode()).hexdigest()
        self._token: dict | None = None
        self._secret: str = ""
        self._lock = threading.Lock()
        self._get_auth()

    def _send(self, data: bytes) -> bytes:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self._timeout)
            s.connect((self._host, self._port))
            s.sendall(data)
            chunks: list[bytes] = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)

    def _get_auth(self) -> None:
        req = f"ggt:{self._ext_id}"
        response = self._send(encode_request_header(req, b""))
        res, body = decode_response_header(response)
        if res != "OK":
            raise RuntimeError(f"Auth failed: {res}")
        tb = GetTokenResponseBody()
        tb.ParseFromString(body)
        self._token = {
            "token": tb.token,
            "salt": tb.salt,
            "length": tb.length,
            "num_requests": tb.num_requests,
        }
        self._secret = ""

    def _get_secret(self) -> str:
        assert self._token is not None
        if self._token["num_requests"] == 0:
            self._get_auth()
        if not self._secret:
            hash_input = self._blake3_hash + self._token["token"]
            blake_hash = blake3(hash_input.encode()).hexdigest()
            self._secret = blake_hash[
                self._token["salt"] : self._token["salt"] + self._token["length"]
            ]
        self._token["num_requests"] -= 1
        return self._secret

    def ping(self) -> bool:
        response = self._send(encode_request_header("ping", b""))
        res, _ = decode_response_header(response)
        return res == "OK"

    def send_dev_sample(self, body: bytes) -> None:
        with self._lock:
            secret = self._get_secret()
            req = f"pdevsample:{self._ext_id}:{secret}:{self._ext_id}"
            response = self._send(encode_request_header(req, body))
            res, _ = decode_response_header(response)
            if res != "OK":
                raise RuntimeError(f"pdevsample failed: {res}")

    def send_dev_status(self, body: bytes) -> None:
        with self._lock:
            secret = self._get_secret()
            req = f"pdevstatus:{self._ext_id}:{secret}:{self._ext_id}"
            response = self._send(encode_request_header(req, body))
            res, _ = decode_response_header(response)
            if res != "OK":
                raise RuntimeError(f"pdevstatus failed: {res}")
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd shared && python -m pytest tests/test_conveyor_client.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/conveyor_client.py shared/tests/test_conveyor_client.py
git commit -m "feat(conveyor): ConveyorClient — BLAKE3 auth + TCP transport"
```

---

## Task 6: `ConveyorUploader` — serialização Package

**Files:**
- Create: `shared/orwell_shared/conveyor_uploader.py`
- Create: `shared/tests/test_conveyor_uploader.py`

- [ ] **Step 1: Escrever os testes que falham**

Criar `shared/tests/test_conveyor_uploader.py`:

```python
import json
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, call

from orwell_shared.samples_pb2 import Package, TriggerType
from orwell_shared.conveyor_uploader import ConveyorUploader


def _make_clip_dir(tmp_path: Path) -> Path:
    clip_dir = tmp_path / "events" / "evt-123"
    clip_dir.mkdir(parents=True)
    (clip_dir / "buf-0.m4s").write_bytes(b"SEGMENT_0")
    (clip_dir / "buf-1.m4s").write_bytes(b"SEGMENT_1")
    return clip_dir


def test_upload_calls_send_dev_sample(tmp_path):
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, ext_id="aabbccddee00")
    clip_dir = _make_clip_dir(tmp_path)

    uploader.upload(
        event_id="evt-123",
        clip_path=clip_dir,
        metadata={
            "camera_id": "cam0",
            "label": "pessoa",
            "confidence": 0.92,
            "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8},
            "t_evento": 1748906400.0,
        },
    )

    mock_client.send_dev_sample.assert_called_once()


def test_upload_concatenates_clip_files(tmp_path):
    sent_bytes = []

    mock_client = MagicMock()
    mock_client.send_dev_sample.side_effect = lambda b: sent_bytes.append(b)

    uploader = ConveyorUploader(mock_client, ext_id="aabbccddee00")
    clip_dir = _make_clip_dir(tmp_path)

    uploader.upload("evt-123", clip_dir, {
        "camera_id": "cam0", "label": "foo", "confidence": 0.5,
        "bbox": None, "t_evento": time.time(),
    })

    assert len(sent_bytes) == 1
    pkg = Package()
    pkg.ParseFromString(sent_bytes[0])
    assert pkg.data == b"SEGMENT_0SEGMENT_1"


def test_upload_package_format(tmp_path):
    sent_bytes = []
    mock_client = MagicMock()
    mock_client.send_dev_sample.side_effect = lambda b: sent_bytes.append(b)

    uploader = ConveyorUploader(mock_client, ext_id="aabbccddee00")
    clip_dir = _make_clip_dir(tmp_path)

    uploader.upload("evt-123", clip_dir, {
        "camera_id": "cam0", "label": "pessoa", "confidence": 0.92,
        "bbox": {"x1": 0.1}, "t_evento": 1748906400.0,
    })

    pkg = Package()
    pkg.ParseFromString(sent_bytes[0])

    assert pkg.format == "orwell.video-clip.v1"
    assert pkg.trigger_type == TriggerType.Value("TRIGGER_TYPE_EVENT")
    assert pkg.device_id == b"aabbccddee00"
    assert pkg.started_at.seconds == 1748906400

    param_keys = {p.key: p for p in pkg.trigger_parameters}
    assert param_keys["label"].string_value == "pessoa"
    assert abs(param_keys["confidence"].real_value - 0.92) < 1e-6
    assert json.loads(param_keys["bbox"].string_value) == {"x1": 0.1}

    pkg_param_keys = {p.key: p for p in pkg.package_parameters}
    assert pkg_param_keys["event_id"].string_value == "evt-123"


def test_upload_returns_uri(tmp_path):
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, ext_id="aabbccddee00")
    clip_dir = _make_clip_dir(tmp_path)

    uri = uploader.upload("evt-123", clip_dir, {
        "camera_id": "cam0", "label": "x", "confidence": 0.5,
        "bbox": None, "t_evento": time.time(),
    })

    assert "aabbccddee00" in uri
    assert "evt-123" in uri


def test_upload_status_calls_send_dev_status():
    mock_client = MagicMock()
    uploader = ConveyorUploader(mock_client, ext_id="aabbccddee00")

    uploader.upload_status({"cpu": 10.5, "memory": 45.2, "disk": 60.0})

    mock_client.send_dev_status.assert_called_once()
    sent = mock_client.send_dev_status.call_args[0][0]
    pkg = Package()
    pkg.ParseFromString(sent)
    assert pkg.format == "orwell.status.v1"
    data = json.loads(pkg.data.decode())
    assert data["cpu"] == 10.5
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd shared && python -m pytest tests/test_conveyor_uploader.py -v
```
Expected: `ModuleNotFoundError: No module named 'orwell_shared.conveyor_uploader'`

- [ ] **Step 3: Implementar `shared/orwell_shared/conveyor_uploader.py`**

```python
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from google.protobuf.timestamp_pb2 import Timestamp

from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.samples_pb2 import Package, Parameter, TriggerType


def _param(key: str, **kwargs) -> Parameter:
    p = Parameter()
    p.key = key
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


class ConveyorUploader:
    def __init__(
        self,
        client: ConveyorClient,
        ext_id: str,
        hardware_id: str = "orwell-nx-v1",
    ) -> None:
        self._client = client
        self._ext_id = ext_id
        self._hardware_id = hardware_id

    def upload(self, event_id: str, clip_path: Path, metadata: dict) -> str:
        buf0 = (clip_path / "buf-0.m4s").read_bytes()
        buf1_path = clip_path / "buf-1.m4s"
        buf1 = buf1_path.read_bytes() if buf1_path.exists() else b""

        t_evento = float(metadata.get("t_evento", time.time()))
        ts = Timestamp()
        ts.seconds = int(t_evento)

        pkg = Package()
        pkg.device_id = self._ext_id.encode()
        pkg.hardware_id = self._hardware_id.encode()
        pkg.data_id = uuid.UUID(event_id).bytes if _is_uuid(event_id) else event_id.encode()
        pkg.format = "orwell.video-clip.v1"
        pkg.started_at.CopyFrom(ts)
        pkg.duration_us = 10_000_000
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_EVENT")

        camera_id = metadata.get("camera_id", "cam0")
        camera_index = int(camera_id.replace("cam", "")) if camera_id.startswith("cam") else 0
        pkg.trigger_source.append(camera_index)

        pkg.trigger_parameters.append(_param("label", string_value=str(metadata.get("label", ""))))
        pkg.trigger_parameters.append(_param("confidence", real_value=float(metadata.get("confidence", 0.0))))

        bbox = metadata.get("bbox")
        if bbox is not None:
            pkg.trigger_parameters.append(_param("bbox", string_value=json.dumps(bbox)))

        pkg.package_parameters.append(_param("event_id", string_value=event_id))
        pkg.package_parameters.append(_param("camera_id", string_value=camera_id))

        pkg.data = buf0 + buf1

        self._client.send_dev_sample(pkg.SerializeToString())
        return f"conveyor://{self._ext_id}/samples/{event_id}"

    def upload_status(self, metrics: dict) -> None:
        ts = Timestamp()
        ts.seconds = int(time.time())

        pkg = Package()
        pkg.device_id = self._ext_id.encode()
        pkg.hardware_id = self._hardware_id.encode()
        pkg.data_id = uuid.uuid4().bytes
        pkg.format = "orwell.status.v1"
        pkg.started_at.CopyFrom(ts)
        pkg.trigger_type = TriggerType.Value("TRIGGER_TYPE_PERIODIC")
        pkg.data = json.dumps(metrics).encode()

        self._client.send_dev_status(pkg.SerializeToString())


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd shared && python -m pytest tests/test_conveyor_uploader.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add shared/orwell_shared/conveyor_uploader.py shared/tests/test_conveyor_uploader.py
git commit -m "feat(conveyor): ConveyorUploader — Package serialization"
```

---

## Task 7: `UploadWorker` — thread daemon de poll

**Files:**
- Create: `shared/orwell_shared/upload_worker.py`
- Create: `shared/tests/test_upload_worker.py`

- [ ] **Step 1: Escrever os testes que falham**

Criar `shared/tests/test_upload_worker.py`:

```python
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orwell_shared.events import Event, EventIndex
from orwell_shared.upload_worker import UploadWorker


def _make_index(tmp_path):
    return EventIndex(tmp_path / "events.db")


def _make_event(tmp_path, event_id="evt-1", camera_id="cam0") -> tuple[Event, Path]:
    clip_dir = tmp_path / "events" / event_id
    clip_dir.mkdir(parents=True)
    (clip_dir / "buf-0.m4s").write_bytes(b"SEG0")
    (clip_dir / "buf-1.m4s").write_bytes(b"SEG1")
    event = Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=time.time(),
        label="pessoa",
        confidence=0.9,
        clip_path=str(clip_dir),
    )
    return event, clip_dir


def test_worker_uploads_pending_event(tmp_path):
    index = _make_index(tmp_path)
    event, clip_dir = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://dev/samples/evt-1"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    mock_uploader.upload.assert_called_once()
    call_args = mock_uploader.upload.call_args
    assert call_args[1]["event_id"] == "evt-1" or call_args[0][0] == "evt-1"


def test_worker_marks_event_as_uploaded(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://dev/samples/evt-1"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    updated = index.get("evt-1")
    assert updated.uploaded_at is not None
    assert updated.uploaded_at > 0


def test_worker_skips_event_when_clip_not_found(tmp_path):
    index = _make_index(tmp_path)
    event = Event(
        id="evt-missing",
        camera_id="cam0",
        t_evento=time.time(),
        label="x",
        confidence=0.5,
        clip_path="/nonexistent/path/evt-missing",
    )
    index.add_event(event)

    mock_uploader = MagicMock()
    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    mock_uploader.upload.assert_not_called()
    updated = index.get("evt-missing")
    assert updated.uploaded_at == -1.0


def test_worker_retries_failed_upload(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    call_count = [0]

    def flaky_upload(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("network error")
        return "conveyor://dev/samples/evt-1"

    mock_uploader = MagicMock()
    mock_uploader.upload.side_effect = flaky_upload

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.4)
    worker.stop()

    assert call_count[0] >= 2
    updated = index.get("evt-1")
    assert updated.uploaded_at is not None and updated.uploaded_at > 0


def test_worker_does_not_re_upload(tmp_path):
    index = _make_index(tmp_path)
    event, _ = _make_event(tmp_path)
    index.add_event(event)

    mock_uploader = MagicMock()
    mock_uploader.upload.return_value = "conveyor://ok"

    worker = UploadWorker(index, mock_uploader, upload_interval_s=0.05, status_interval_s=9999)
    worker.start()
    time.sleep(0.3)
    worker.stop()

    assert mock_uploader.upload.call_count == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd shared && python -m pytest tests/test_upload_worker.py -v
```
Expected: `ModuleNotFoundError: No module named 'orwell_shared.upload_worker'`

- [ ] **Step 3: Implementar `shared/orwell_shared/upload_worker.py`**

```python
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from orwell_shared.events import EventIndex

logger = logging.getLogger(__name__)


class UploadWorker:
    def __init__(
        self,
        event_index: EventIndex,
        uploader,
        upload_interval_s: float = 30.0,
        status_interval_s: float = 300.0,
    ) -> None:
        self._index = event_index
        self._uploader = uploader
        self._upload_interval = upload_interval_s
        self._status_interval = status_interval_s
        self._stop_event = threading.Event()
        self._upload_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None

    def start(self) -> None:
        self._upload_thread = threading.Thread(
            target=self._upload_loop, daemon=True, name="UploadWorker"
        )
        self._upload_thread.start()
        self._status_thread = threading.Thread(
            target=self._status_loop, daemon=True, name="StatusWorker"
        )
        self._status_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _upload_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_pending()
            except Exception:
                logger.exception("unexpected error in upload loop")
            self._stop_event.wait(self._upload_interval)

    def _status_loop(self) -> None:
        # Espera o intervalo antes do primeiro envio para não disparar no boot imediato.
        while not self._stop_event.wait(self._status_interval):
            try:
                self._send_status()
            except Exception:
                logger.exception("unexpected error in status loop")

    def _process_pending(self) -> None:
        pending = self._index.pending_uploads()
        for event in pending:
            if self._stop_event.is_set():
                break
            clip_path = Path(event.clip_path) if event.clip_path else None
            if clip_path is None or not clip_path.exists():
                logger.warning("clip not found for event %s, marking as failed", event.id)
                self._index.mark_upload_failed(event.id)
                continue
            try:
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
                self._index.mark_uploaded(event.id)
                logger.info("uploaded event %s", event.id)
            except Exception:
                logger.warning("upload failed for event %s, will retry", event.id, exc_info=True)

    def _send_status(self) -> None:
        try:
            import psutil
            metrics = {
                "cpu": psutil.cpu_percent(interval=0.1),
                "memory": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage("/").percent,
            }
        except ImportError:
            metrics = {}
        self._uploader.upload_status(metrics)
```

Nota: `psutil` é opcional — se não estiver instalado, `metrics` fica vazio. Não adicionar ao `pyproject.toml` agora; é um detalhe de implementação do Jetson.

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd shared && python -m pytest tests/test_upload_worker.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Rodar toda a suite**

```bash
cd shared && python -m pytest tests/ -v
```
Expected: todos passam.

- [ ] **Step 6: Commit**

```bash
git add shared/orwell_shared/upload_worker.py shared/tests/test_upload_worker.py
git commit -m "feat(conveyor): UploadWorker — polling daemon thread"
```

---

## Task 8: Wire up em `main.py`

**Files:**
- Modify: `services/recorder/recorder/main.py`

- [ ] **Step 1: Adicionar instanciação condicional do worker em `main.py`**

Localizar o bloco de imports em `services/recorder/recorder/main.py` e adicionar:

```python
from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.conveyor_uploader import ConveyorUploader
from orwell_shared.upload_worker import UploadWorker
```

Localizar onde `event_index` é criado (ou onde a config é carregada) e adicionar, após a criação do `EventIndex`:

```python
_upload_worker: UploadWorker | None = None

if cfg.conveyor.enabled and cfg.conveyor.ext_id:
    _conveyor_client = ConveyorClient(
        host=cfg.conveyor.host,
        port=cfg.conveyor.port,
        ext_id=cfg.conveyor.ext_id,
    )
    _conveyor_uploader = ConveyorUploader(
        client=_conveyor_client,
        ext_id=cfg.conveyor.ext_id,
    )
    _upload_worker = UploadWorker(
        event_index=event_index,
        uploader=_conveyor_uploader,
        upload_interval_s=cfg.conveyor.upload_interval_s,
        status_interval_s=cfg.conveyor.status_interval_s,
    )
    _upload_worker.start()
    logging.info("UploadWorker started (conveyor=%s:%d)", cfg.conveyor.host, cfg.conveyor.port)
```

- [ ] **Step 2: Verificar que o módulo importa sem GStreamer**

```bash
cd services/recorder && python -c "
import sys; sys.path.insert(0, '../../shared')
# Não importar main diretamente (precisa de GStreamer), só verificar as dependências
from orwell_shared.conveyor_client import ConveyorClient
from orwell_shared.conveyor_uploader import ConveyorUploader
from orwell_shared.upload_worker import UploadWorker
print('OK - all imports work')
"
```
Expected: `OK - all imports work`

- [ ] **Step 3: Rodar toda a suite de testes**

```bash
python -m pytest shared/tests/ services/recorder/tests/ -v
```
Expected: todos passam.

- [ ] **Step 4: Commit final**

```bash
git add services/recorder/recorder/main.py
git commit -m "feat(recorder): wire up ConveyorUploader + UploadWorker on boot"
```

---

## Configuração para ativar no `orwell.yaml`

Para habilitar o upload no dispositivo, adicionar ao `orwell.yaml`:

```yaml
conveyor:
  enabled: true
  host: conveyor.tractian.com
  port: 8080
  ext_id: "aabbccddee00"   # extId do dispositivo cadastrado no Conveyor
  upload_interval_s: 30
  status_interval_s: 300
```

Ou via variáveis de ambiente:
```bash
ORWELL_CONVEYOR__ENABLED=true
ORWELL_CONVEYOR__EXT_ID=aabbccddee00
```
