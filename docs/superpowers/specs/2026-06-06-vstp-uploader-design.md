# Design: VSTP Uploader — envio de eventos de IA para o Conveyor

**Data:** 2026-06-06  
**Status:** aprovado

---

## Contexto

O Orwell detecta eventos de IA (ex: pessoa em área restrita) e grava um clip de ~10 s em tmpfs.
Esses clips precisam ser enviados para o Conveyor (backend Tractian) via VSTP usando as rotas de
desenvolvimento (`pdevsample`, `pdevstatus`).

O dispositivo age como **gateway + sensor** com o mesmo `extId` — sem separação de entidades.

---

## Decisões tomadas

| Decisão | Escolha | Motivo |
|---|---|---|
| Retry strategy | Background thread + SQLite como fila | `uploaded_at IS NULL` já existe no schema; pipeline GStreamer nunca bloqueia |
| Payload format | `samples.v1.Package` serializado | Padrão Tractian; `format` identifica o tipo ao backend |
| Dependência de cliente | Reimplementar inline (~150 linhas) | `tractian-iot-emulator` requer Python ≥3.11; Jetson roda 3.10 |
| Transporte do clip | Concatenar buf-0.m4s + buf-1.m4s num único `pdevsample` | Menos chamadas; fMP4 concatenado é reproduzível |
| Backoff | Intervalo fixo (sem exponential backoff) | Padrão de falha dominante é ausência de rede por horas; complexidade desnecessária |

---

## Arquitetura

```
shared/orwell_shared/
  vstp.py               — framing TCP: encode_request_header / decode_response_header
  conveyor_client.py    — auth BLAKE3 + TCP transport: ping, get_auth, send_dev_sample, send_dev_status
  conveyor_uploader.py  — implementa UploaderBackend usando ConveyorClient + serialização Package
  upload_worker.py      — thread daemon: poll SQLite → chama UploaderBackend → mark_uploaded
  samples_pb2.py        — gerado via protoc a partir de samples.proto; commitado no repo

services/recorder/recorder/main.py  — instancia ConveyorUploader + UploadWorker e arranca no boot

pyproject.toml   — adiciona: protobuf, blake3, tractian-iot-proto
config.py        — adiciona ConveyorConfig
events.py        — adiciona EventIndex.mark_uploaded() + EventIndex.pending_uploads()
```

---

## Fluxo em runtime

```
GStreamer probe → handle_detection()
                      └─ flush_event_buffer()    # copia buf-0/1.m4s → /events/<id>/
                      └─ EventIndex.add_event()  # uploaded_at = None

UploadWorker (thread daemon, poll a cada conveyor.upload_interval_s)
  └─ EventIndex.pending_uploads()               # WHERE uploaded_at IS NULL
  └─ para cada evento:
       ├─ lê clip_path/buf-0.m4s + buf-1.m4s e concatena
       ├─ monta samples.v1.Package (ver abaixo)
       ├─ ConveyorClient.send_dev_sample(ext_id, package_bytes)   → pdevsample
       └─ EventIndex.mark_uploaded(event_id)

UploadWorker (ciclo separado, periódico)
  └─ coleta métricas do host (CPU, memória, disco)
  └─ monta Package com format="orwell.status.v1" e data=JSON
  └─ ConveyorClient.send_dev_status(ext_id, package_bytes)        → pdevstatus
```

---

## Formato do payload — `samples.v1.Package`

### `pdevsample` (evento de IA)

```
Package {
  device_id          = extId.encode()                     # bytes
  hardware_id        = b"orwell-nx-v1"
  data_id            = uuid.uuid4().bytes                 # UUID do evento
  format             = "orwell.video-clip.v1"
  packed_at          = Timestamp(seconds=int(t_evento))
  duration_us        = 10_000_000                         # ~10 s
  trigger_type       = TRIGGER_TYPE_EVENT
  trigger_source     = [camera_id]
  trigger_parameters = [
    Parameter(key="label",      string_value=label),
    Parameter(key="confidence", real_value=confidence),
    Parameter(key="bbox",       string_value=json.dumps(bbox)),
  ]
  package_parameters = [
    Parameter(key="event_id",        string_value=event_id),
    Parameter(key="orwell_version",  string_value="0.1.0"),
  ]
  data = buf_0_bytes + buf_1_bytes                        # fMP4 concatenado
}
```

### `pdevstatus` (heartbeat periódico)

```
Package {
  device_id    = extId.encode()
  hardware_id  = b"orwell-nx-v1"
  data_id      = uuid.uuid4().bytes
  format       = "orwell.status.v1"
  packed_at    = Timestamp(seconds=now)
  trigger_type = TRIGGER_TYPE_PERIODIC
  data         = json.dumps({cpu, memory, disk, cameras_active}).encode()
}
```

---

## ConveyorClient — auth e transport

Protocolo VSTP: TCP puro, sem TLS. Cada chamada abre um socket, envia, lê resposta, fecha.
Token reutilizado até `num_requests == 0`, depois re-autentica via `ggt` automaticamente.

**Req string format** (separador `:`):
```
ggt:{ext_id}                                   # get token — sem secret
pdevsample:{ext_id}:{secret}:{ext_id}          # gatewayExtId == sensorExtId
pdevstatus:{ext_id}:{secret}:{ext_id}
```

**Secret derivation:**
```python
blake3_hash = blake3(ext_id.encode()).hexdigest()
secret      = blake3((blake3_hash + token).encode()).hexdigest()[salt : salt + length]
```

**Dependências adicionadas:**
- `blake3` — derivação de secret HMAC
- `tractian-iot-proto` — `RequestHeader` / `ResponseHeader` protobuf (VSTP framing)
- `protobuf` — runtime para `samples_pb2.py` gerado a partir de `samples.proto`

Nota: `pycryptodomex` não é necessário — as dev routes não usam criptografia AES.

---

## Config

```python
class ConveyorConfig(BaseModel):
    enabled: bool = False
    host: str = "conveyor.tractian.com"
    port: int = 8080
    ext_id: str = ""                  # gateway + sensor extId (mesmo valor)
    upload_interval_s: int = 30       # poll do worker de eventos
    status_interval_s: int = 300      # heartbeat de status
```

Adicionado em `OrwellConfig` como campo `conveyor: ConveyorConfig`.

---

## Error handling

- Upload falha → `uploaded_at` permanece `None` → worker retenta no próximo ciclo.
- `clip_path` não existe mais (rotação de disco) → worker loga warning, marca como falha permanente (`uploaded_at = -1.0` para distinguir de pendente).
- Token expirado (`FailToAuth`) → `ConveyorClient` re-autentica antes de reenviar.
- Sem limite de retentativas para eventos com clip válido.
- Sem exponential backoff — intervalo fixo é suficiente para o padrão de falha dominante (rede ausente por horas).

---

## Testes

| Arquivo | O que valida |
|---|---|
| `shared/tests/test_vstp_framing.py` | encode/decode do header VSTP sem rede |
| `shared/tests/test_conveyor_client.py` | auth BLAKE3 + `send_dev_sample` com socket mock local |
| `shared/tests/test_upload_worker.py` | poll SQLite → `upload()` chamado → `mark_uploaded` atualizado |
| `shared/tests/test_package_proto.py` | `samples.v1.Package` serializa campos do evento corretamente |

Nenhum teste requer Conveyor real. O mock é um `socketserver` local que responde com frame VSTP `OK`.

---

## Arquivos criados / modificados

| Arquivo | Ação |
|---|---|
| `shared/orwell_shared/vstp.py` | criar |
| `shared/orwell_shared/conveyor_client.py` | criar |
| `shared/orwell_shared/conveyor_uploader.py` | criar — implementa `UploaderBackend` usando `ConveyorClient` + serialização `Package` |
| `shared/orwell_shared/upload_worker.py` | criar — aceita qualquer `UploaderBackend`; testável com mock |
| `shared/orwell_shared/samples_pb2.py` | gerar via `protoc` a partir de `samples.proto` e commitar |
| `shared/orwell_shared/config.py` | modificar — adicionar `ConveyorConfig` |
| `shared/orwell_shared/events.py` | modificar — adicionar `pending_uploads()` e `mark_uploaded()` |
| `shared/orwell_shared/uploader.py` | não muda — `UploaderBackend` Protocol já é a interface correta |
| `pyproject.toml` | modificar — adicionar `protobuf`, `blake3`, `tractian-iot-proto` |
| `services/recorder/recorder/main.py` | modificar — instanciar `ConveyorUploader` + `UploadWorker` no boot |
| `shared/tests/test_vstp_framing.py` | criar |
| `shared/tests/test_conveyor_client.py` | criar |
| `shared/tests/test_upload_worker.py` | criar |
| `shared/tests/test_package_proto.py` | criar |
