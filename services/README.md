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
docker compose up -d
curl localhost/api/healthz             # {"status":"ok"}
```
> Sem o `recorder` (roda só no Jetson), ainda não há segmentos gravados — a Clip API responde,
> mas `GET /clips` retorna 404 até existirem segmentos no índice. Para testar a extração de ponta
> a ponta antes do Jetson, gere segmentos de exemplo com o fixture de `tests/conftest.py`.

## Estrutura
- `shared/orwell_shared/` — lógica pura (config, índice, retenção, publicação atômica de clipes).
- `services/gateway/` — borda HTTP Nginx; replica o contrato do futuro Ingress Traefik.
- `services/clip-api/clip_api/` — FastAPI: `GET /clips`, `/cameras`, `/segments`, `/healthz`.
- `services/recorder/recorder/` — captura/encode/gravação on-device (DeepStream/GStreamer).
  **Implementado** (pipeline + indexer + main); partes puras têm testes; o runtime GStreamer só
  roda no Jetson (ver `DEPLOY.md`). Também finaliza e publica `clip.mp4` antes do SQLite.
- `services/uploader/uploader/` — entrega eventos já finalizados via VSTP; não transforma mídia.
