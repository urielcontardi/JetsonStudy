# Design: Upload Periódico + Config Remota + Serviço Uploader

**Data:** 2026-06-08
**Status:** Em revisão
**Contexto:** Jetson Orin NX · Conveyor VSTP · K3s futuro

---

## Problema

O Orwell já envia clips quando a IA detecta um evento. Precisa também:
1. **Enviar o buffer circular a cada X minutos** (coleta periódica, independente de IA).
2. **Deixar o operador configurar o intervalo no dashboard** sem rebuild/redeploy.
3. **Preparar o protocolo de config remota** (proto) para que o Conveyor possa empurrar config futuramente (ex: trocar modelo de IA via K3s).

---

## Decisões

| Decisão | Escolha | Motivo |
|---|---|---|
| Upload periódico vs event-triggered | Mesmo pipeline — só `trigger_type` muda | Reutiliza `UploadWorker` e `EventIndex` sem duplicar código |
| Onde roda o timer periódico | `recorder` | Único processo com acesso ao buffer circular em `/dev/shm` |
| Serviço `uploader` | Container separado, sem NVIDIA | Pode reiniciar sem interromper gravação; K3s-friendly |
| Interface recorder↔uploader | SQLite + filesystem (`/events/`) | Zero acoplamento; mesma interface já usada para eventos AI |
| Config management | `GET/PATCH /config` no `clip-api` | Já é o API HTTP do device; evita serviço extra |
| Persistência de config | `orwell.yaml` (HostPath no NVMe) | Source of truth 12-factor; survives container restart |
| Config reload no recorder | Poll `orwell.yaml` a cada 30 s | Sem restart de pipeline; simples e robusto |
| Proto de config remota | `RemoteConfig` mínimo extensível | Proto é non-breaking ao adicionar campos; começa pequeno |
| SQLite WAL | Já habilitado no `EventIndex.__init__` | Resistência a power loss |
| SQLite busy_timeout | Adicionar `PRAGMA busy_timeout=5000` | Evita `OperationalError: database is locked` entre `recorder` e `uploader` |

---

## Arquitetura

```
dashboard ──PATCH /config──→ clip-api ──→ orwell.yaml
                                               ↑ poll 30s
                                          recorder recarrega
                                          upload_interval_s

recorder  ──timer──→ flush buffer → /events/<uuid>_periodic/
recorder  ──AI────→ flush buffer → /events/<uuid>_ai/
                          ↓
                     SQLite events (trigger_type = 'periodic' | 'ai')

uploader  ──poll SQLite──→ /events/<uuid>/ ──→ VSTP → Conveyor

Futuro: Conveyor ──RemoteConfig proto──→ clip-api ──→ orwell.yaml
```

**Regra de isolamento:** `recorder` e `uploader` nunca se chamam diretamente.
A interface entre eles é o SQLite + filesystem — contratos estáveis independentes de
versão de container.

---

## Fluxo de Upload Periódico

```
recorder (timer a cada conveyor.periodic_upload_interval_s)
  1. cria snapshot dos fragments fechados, remuxa e publica
     `/events/<uuid>/clip.mp4` atomicamente para cada câmera configurada
  2. INSERT INTO events (
       id=uuid, camera_id=cam, t_evento=now(),
       label='periodic', trigger_type='periodic',
       confidence=1.0, clip_path=..., uploaded_at=NULL
     )

uploader (poll SQLite a cada 30 s)
  1. SELECT * FROM events WHERE uploaded_at IS NULL ORDER BY t_evento
     — retorna tanto eventos AI quanto periódicos
  2. monta Package (trigger_type = TRIGGER_TYPE_PERIODIC para periódicos)
  3. ConveyorClient.send_dev_sample()
  4. EventIndex.mark_uploaded(event_id)
```

O `uploader` não distingue origem — apenas entrega. O `trigger_type` no payload
informa o Conveyor como categorizar o clip.

---

## `trigger_type` no SQLite

Adicionado à tabela `events` e ao dataclass `Event`:

```sql
ALTER TABLE events ADD COLUMN trigger_type TEXT DEFAULT 'ai';
```

```python
@dataclass
class Event:
    ...
    trigger_type: str = "ai"   # 'ai' | 'periodic'
```

`EventIndex.__init__` aplica a migration via:
```python
conn.execute(
    "ALTER TABLE events ADD COLUMN trigger_type TEXT DEFAULT 'ai'"
)
```
envolto em `try/except OperationalError` (idempotente — SQLite não tem `ADD COLUMN IF NOT EXISTS`).

---

## `config.proto` — RemoteConfig

```protobuf
syntax = "proto3";
package orwell.config.v1;

// Subconjunto configurável remotamente pelo Conveyor.
// Campos de hardware (câmeras, codec) ficam fora — exigem redeploy.
message RemoteConfig {
  bool   periodic_upload_enabled   = 1;
  uint32 periodic_upload_interval_s = 2;  // default: 600 (10 min)
  uint32 buffer_seconds            = 3;   // default: 60

  // Reservado para fase AI:
  // float  confidence_threshold  = 10;
  // string model_path            = 11;
  // uint32 inference_fps         = 12;
}
```

Arquivo: `shared/proto/remote_config.proto`
Gerado: `shared/orwell_shared/remote_config_pb2.py` (commitado, como `samples_pb2.py`).

---

## `ConveyorConfig` — campos adicionados

```python
class ConveyorConfig(BaseModel):
    ...
    periodic_upload_enabled: bool = True
    periodic_upload_interval_s: int = 600   # 10 minutos
```

`upload_interval_s` existente (30 s) é o poll do `UploadWorker` para eventos
pendentes — permanece separado do intervalo periódico.

---

## `clip-api` — endpoints de config

```
GET  /config          → retorna subset de OrwellConfig editável
PATCH /config         → valida + escreve orwell.yaml + retorna config atualizada
```

Payload de `PATCH /config`:
```json
{
  "periodic_upload_enabled": true,
  "periodic_upload_interval_s": 600
}
```

Validação: `periodic_upload_interval_s` entre 60 e 86400.
O `clip-api` lê o `orwell.yaml` existente, mescla apenas os campos enviados, e re-serializa.

Futuramente: `POST /config/remote` aceita `RemoteConfig` serializado em protobuf e
aplica o mesmo fluxo.

---

## `recorder` — Config Watcher

Thread daemon que verifica `mtime` do `orwell.yaml` a cada 30 s. Se mudou, recarrega
e aplica campos sem restart de pipeline:

```python
class ConfigWatcher:
    def __init__(self, config_path: Path, on_change: Callable[[OrwellConfig], None]):
        ...
    def _loop(self):
        while not self._stop.wait(30):
            mtime = config_path.stat().st_mtime
            if mtime != self._last_mtime:
                self._last_mtime = mtime
                cfg = load_config(config_path)
                self._on_change(cfg)
```

Campos aplicáveis sem restart no `recorder`: `periodic_upload_enabled`,
`periodic_upload_interval_s`, `ai.confidence_threshold`.

`conveyor.upload_interval_s` afeta o `uploader` (serviço separado) — mudança exige
restart do `uploader`, que é seguro (gravação não é interrompida).

Campos que exigem restart de pipeline (não recarregados ao vivo): resolução, codec,
câmeras, `event_buffer.buffer_seconds`.

---

## Serviço `uploader` (novo container)

**Responsabilidade:** ler SQLite → enviar via VSTP → marcar uploaded.
Não precisa de GStreamer nem NVIDIA Runtime.

```
services/uploader/
  Dockerfile           — python:3.10-slim, sem nvidia
  uploader/
    __init__.py
    main.py            — instancia EventIndex + ConveyorUploader + UploadWorker.start()
```

`docker-compose.yml`:
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
  depends_on: []   # independente — funciona mesmo sem recorder no ar
```

O `recorder` remove o `UploadWorker` do seu `main.py` — upload passa a ser
responsabilidade exclusiva do `uploader`.

---

## Dashboard — Painel de Configuração

Nova página/seção em `services/dashboard/` com:

- Toggle **Upload periódico ativo**
- Slider/input **Intervalo (minutos)**: 1–1440, default 10
- Botão **Salvar** → `PATCH /config` na clip-api
- Indicador de estado: "Próximo upload em X min" (calculado no frontend com `Date.now`)
- Badge **Uploads pendentes**: via novo endpoint `GET /upload-stats` →
  `{"pending": N, "failed": N, "last_uploaded_at": ISO8601 | null}`

---

## SQLite — Ajustes

1. `PRAGMA journal_mode=WAL` — **já aplicado** em `EventIndex.__init__`.
2. `PRAGMA busy_timeout=5000` — **adicionar** em `EventIndex.__init__` e no `SegmentIndex`
   equivalente.
3. Migration `trigger_type` — **adicionar** em `EventIndex.__init__` (idempotente).

K3s: todos os pods montam `HostPath` no NVMe local do nó.
`index.sqlite` nunca em `emptyDir` nem em NFS.

---

## Fora do Escopo desta Spec

- Treinamento e seleção de modelos de IA (spec separada).
- Push de config pelo Conveyor (infraestrutura Conveyor não existe ainda — proto está pronto).
- Mais de 2 câmeras.
- Compressão/resize do clip periódico antes do envio.
- Limpeza automática de clips periódicos após upload.

---

## Arquivos Criados / Modificados

| Arquivo | Ação |
|---|---|
| `shared/proto/remote_config.proto` | criar |
| `shared/orwell_shared/remote_config_pb2.py` | gerar via protoc + commitar |
| `shared/orwell_shared/config.py` | modificar — adicionar `periodic_upload_enabled`, `periodic_upload_interval_s` em `ConveyorConfig` |
| `shared/orwell_shared/events.py` | modificar — adicionar `trigger_type` em `Event` + migration em `EventIndex.__init__` + `PRAGMA busy_timeout` |
| `shared/orwell_shared/index.py` | modificar — adicionar `PRAGMA busy_timeout=5000` |
| `services/uploader/Dockerfile` | criar |
| `services/uploader/uploader/__init__.py` | criar |
| `services/uploader/uploader/main.py` | criar |
| `services/recorder/recorder/main.py` | modificar — adicionar timer periódico + `ConfigWatcher`; remover `UploadWorker` |
| `services/clip-api/clip_api/main.py` | modificar — adicionar `GET /config`, `PATCH /config`, `GET /upload-stats` |
| `services/dashboard/` | modificar — adicionar painel de configuração |
| `docker-compose.yml` | modificar — adicionar serviço `uploader` |
