# Serviços Orwell — desenvolvimento

## Setup
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Testes
```bash
python -m pytest            # todos (shared + serviços + integração)
python -m pytest shared     # só a lib compartilhada
```
> O teste de integração (`tests/test_integration_clip.py`) faz **skip** se `ffmpeg`/`ffprobe`
> não estiverem instalados.

## Subir localmente (sem Jetson)
```bash
mkdir -p data
docker compose up -d broker clip-api uploader
curl localhost:8080/healthz        # {"status":"ok"}
```
> Sem o `recorder` (Plano 1B), ainda não há segmentos gravados — a Clip API responde, mas
> `GET /clips` retorna 404 até existirem segmentos no índice. Para testar a extração de ponta a
> ponta antes do Jetson, gere segmentos de exemplo com o fixture de `tests/conftest.py`.

## Estrutura
- `shared/orwell_shared/` — lógica pura (config, índice, retenção, clipes, storage, eventos).
- `services/clip-api/clip_api/` — FastAPI: `GET /clips`, `/cameras`, `/segments`, `/healthz`.
- `services/uploader/uploader/` — MQTT → clipe → nuvem (esqueleto; IA no Plano 2).
- `services/recorder/recorder/` — captura/encode/gravação on-device (DeepStream/GStreamer).
  **Implementado** (pipeline + indexer + main); partes puras têm testes; o runtime GStreamer só
  roda no Jetson (ver `DEPLOY.md`). IA (`nvinfer`) fica para a Fase 2.

## Pacotes (nomes únicos por serviço)
Cada serviço expõe um pacote de nome único (`clip_api`, `uploader`) para evitar colisão de import
nos testes. O `pyproject.toml` adiciona `services/clip-api` e `services/uploader` ao `pythonpath`
do pytest.
