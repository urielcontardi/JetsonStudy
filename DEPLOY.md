# Deploy do Orwell — do zero ao ar (Jetson Orin Nano)

Guia ponta-a-ponta. Objetivo: **placa zerada → gravando + acessível remotamente → containers sobem
sozinhos no boot**. Tudo é registrado em `deploy/` (provisionamento como código — ADR-0013).

## TL;DR (resumo)

```bash
# 0. (uma vez, no PC) flashar JetPack via SDK Manager
# no Jetson:
git clone <repo> orwell && cd orwell
nano deploy/00-versions.env            # editar device, storage, driver GMSL, Tailscale
sudo ./deploy/99-bootstrap.sh          # instala tudo (Docker, runtime NV, Tailscale, NTP, driver…)
sudo reboot
sudo ./deploy/host-verify.sh           # checagem de sanidade
docker compose --profile jetson build  # builda as imagens (1ª vez; demora)
sudo systemctl start orwell            # sobe tudo; e passa a subir SOZINHO no boot
curl localhost:8080/healthz            # {"status":"ok"}
```

---

## É fácil? (respostas diretas)

- **Configurar a placa?** Sim — **1 arquivo** (`deploy/00-versions.env`) + **1 comando**
  (`sudo ./deploy/99-bootstrap.sh`). O único item manual é **baixar o `.deb` do driver GMSL**
  certo (depende da sua versão de JetPack) — o passo está guiado abaixo.
- **Deploy?** Sim — `docker compose build` + `systemctl start orwell`.
- **Os dockers sobem sozinhos?** **Sim.** Há um serviço systemd (`orwell.service`) habilitado no
  bootstrap + `restart: unless-stopped` nos containers. Depois do primeiro start, eles voltam
  sozinhos a cada reboot/queda.
- **Está documentado?** Sim — este arquivo + `deploy/README.md` + `docs/`.

---

## Passo 0 — Flashar o JetPack (uma vez, fora dos scripts)

No Jetson **não** se instala "Ubuntu + drivers" como num PC: flasheia-se o **JetPack** (L4T) com o
**NVIDIA SDK Manager** (de um PC host). Isso traz o kernel + CUDA + stack de câmera (Argus). Confirme:

```bash
cat /etc/nv_tegra_release      # deve mostrar a versão L4T (ex.: R36.x)
```

## Passo 1 — Obter o código e configurar

```bash
git clone <repo> orwell && cd orwell
nano deploy/00-versions.env
```

Edite:
- `DEVICE_NAME` (nome no Tailscale, ex.: `orwell-01`)
- `DATA_DIR` (onde gravar; padrão `/var/lib/orwell/data` no NVMe de boot) e `STORAGE_MODE`
- **Driver GMSL** (`GMSL_DRIVER_DEB`): baixe o `.deb` casando **placa + deserializer + L4T** em
  <https://www.stereolabs.com/developers/drivers>, ponha em `deploy/artifacts/` e aponte o nome.
- `TS_AUTHKEY` (opcional; senão o Tailscale pede login interativo)
- Câmeras e perfil de captura: `config/orwell.yaml` (padrão: 2 câmeras, 1080p@15fps, segmento 4s).

## Passo 2 — Provisionar o host (um comando)

```bash
sudo ./deploy/99-bootstrap.sh
```

Roda, idempotente e em ordem: base (apt, ffmpeg, python) → storage → Docker → NVIDIA runtime →
Tailscale → NTP → **habilita o `orwell.service`** → driver GMSL (exige reboot).

## Passo 3 — Reboot e verificação

```bash
sudo reboot
# após reiniciar:
sudo ./deploy/host-verify.sh
```
Confere: L4T, Docker+runtime nvidia, `/dev/video*` (câmeras), Tailscale, NTP, disco.

> Mapeie as câmeras no compose: o serviço `recorder` lista `devices:` (`/dev/video0`, …). Ajuste
> conforme o `host-verify` mostrar.

## Passo 4 — Buildar as imagens (1ª vez)

```bash
docker compose --profile jetson build
```
- `clip-api`, `uploader`, `broker`: leves.
- `recorder`: usa a base **DeepStream/L4T** (grande) — só builda no Jetson. Ajuste a tag em
  `services/recorder/Dockerfile` (`DEEPSTREAM_IMAGE`) para casar seu JetPack (ver `docs/hardware.md`).

## Passo 5 — Subir (e a partir daí, sozinho no boot)

```bash
sudo systemctl start orwell      # sobe broker + clip-api + uploader + recorder
sudo systemctl status orwell
```
A partir daqui, **todo reboot sobe os containers automaticamente** (systemd + restart policy).

Verificar:
```bash
curl localhost:8080/healthz                 # {"status":"ok"}
curl localhost:8080/cameras                 # ["0","1"] quando o recorder já gravou
ls /var/lib/orwell/data/0/                   # init.mp4 + live.m3u8 + segmentos
```

## Passo 6 — Acesso remoto (Tailscale)

De qualquer lugar do seu tailnet:
```bash
curl "http://orwell-01:8080/clips?camera=0&start=2026-05-31T14:00:00Z&end=2026-05-31T14:00:10Z" -o clip.mp4
```

## Operação do dia a dia

```bash
docker compose --profile jetson ps           # estado
docker compose --profile jetson logs -f recorder
sudo systemctl restart orwell                 # reiniciar tudo
git pull && docker compose --profile jetson build && sudo systemctl restart orwell   # atualizar
```

## Onde isso vira frota (futuro)

`docker compose` → **K3s + Rancher Fleet** (GitOps) + **registry** de imagens. O `orwell.service`
e os scripts `deploy/` podem virar imagem base / Rancher Elemental. Ver `docs/operations.md`.

## Limitações conhecidas / a validar no device

- Elementos GStreamer NVIDIA (`nvarguscamerasrc`/`nvvidconv`) e o muxer fragmentado do
  `splitmuxsink` devem ser validados no Jetson (ver `docs/decisions/0006`).
- Tag da imagem DeepStream deve casar com o JetPack instalado.
- `recorder` roda `privileged` com `/tmp/argus_socket` montado (daemon Argus do host).
- IA (`nvinfer`) e o disparo evento→nuvem entram na **Fase 2** (o `uploader` já está pronto p/ receber).
