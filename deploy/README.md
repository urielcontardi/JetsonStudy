# Provisionamento do host (deploy/)

> **Regra de ouro do projeto:** nada toca o host de forma manual/ad-hoc. **Todo** comando que
> instala ou modifica o ambiente Linux (apt, Docker, drivers, mounts, NTP, Tailscale…) **deve**
> estar registrado num script aqui. Estes scripts **são** o registro reproduzível: pegou uma placa
> zerada → roda o bootstrap → está no ar.

## Objetivo

Sair de uma **placa Jetson com JetPack/L4T recém-flashado** para um host pronto para rodar os
serviços do Orwell, de forma **rápida, repetível e idempotente** (pode re-rodar sem quebrar nada).

## Passo 0 — pré-requisito: JetPack/L4T flashado (fora destes scripts)

No Jetson **não** se instala "Ubuntu + drivers" como num PC. A placa é flashada com o **JetPack**
(= L4T: Ubuntu da NVIDIA com kernel + BSP + CUDA + Argus), via **NVIDIA SDK Manager** num PC host.
O **driver GMSL e o DeepStream exigem** essa base. Confirme que já existe:

```bash
cat /etc/nv_tegra_release   # deve listar a versão L4T (ex.: R36.x)
```

Se este arquivo não existir, a placa está com Ubuntu genérico → flasheie o JetPack primeiro.

## Passo 1 — configurar valores do device

Edite **`00-versions.env`** (fonte única de verdade):
- `DEVICE_NAME` (nome no Tailscale), `DATA_DIR`, `STORAGE_MODE`.
- **Driver GMSL:** baixe o `.deb` correto (casando **placa + deserializer + versão L4T**) em
  <https://www.stereolabs.com/developers/drivers>, coloque em `deploy/artifacts/` e aponte
  `GMSL_DRIVER_DEB` (ou use `GMSL_DRIVER_URL`).
- `TS_AUTHKEY` (opcional, para ingresso não-interativo no Tailscale).

> `deploy/artifacts/` e segredos **não** vão para o git (ver `.gitignore`).

## Passo 2 — rodar o bootstrap

```bash
sudo ./deploy/99-bootstrap.sh
```

Executa, em ordem e idempotente:

| Script | O que faz |
|---|---|
| `10-base.sh` | apt update/upgrade + utilitários (curl, git, jq, ffmpeg, python3, nvme-cli…) |
| `20-storage.sh` | prepara `DATA_DIR` (modo `dir`: diretório no disco existente; `disk`: NVMe dedicado) |
| `40-docker.sh` | instala Docker Engine + habilita serviço + grupo docker |
| `50-nvidia-runtime.sh` | garante NVIDIA Container Runtime + `default-runtime=nvidia` |
| `60-tailscale.sh` | instala e conecta o Tailscale (`--ssh`, hostname = `DEVICE_NAME`) |
| `70-time-ntp.sh` | timezone UTC + NTP (relógio confiável para o índice) |
| `30-gmsl-driver.sh` | instala o driver GMSL da Stereolabs (**exige reboot**) |

## Passo 3 — reboot e verificação

O driver GMSL exige **reboot**:

```bash
sudo reboot
# após reiniciar:
sudo ./deploy/host-verify.sh    # checa L4T, Docker+nvidia, /dev/video*, Tailscale, NTP, disco
```

## Passo 4 — subir os serviços

```bash
docker compose up -d --build    # POC (build local, sem registry)
```

## Idempotência e re-execução

Todos os scripts checam o estado antes de agir — re-rodar o bootstrap é seguro (ex.: não
reinstala Docker se já existe, não reformata disco com filesystem, não recria entrada de fstab).

## Log de provisionamento

- Execuções são registradas em `/var/log/orwell-provisioning.log` (best-effort).
- Desvios manuais ou notas por placa: anote em [`provisioning-log.md`](provisioning-log.md).

## Futuro (frota)

Quando migrar para **K3s + Rancher Fleet**, o provisionamento de **host** (estes scripts) pode
virar uma imagem base / Rancher Elemental, e os **serviços** passam a ser entregues por GitOps.
Ver [`../docs/operations.md`](../docs/operations.md).
