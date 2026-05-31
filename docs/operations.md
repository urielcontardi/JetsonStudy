# Operação — acesso remoto, atualização e provisionamento

Dois eixos distintos (não confundir):
- **Acesso (alcance de rede):** como você **chega** no device e na Clip API → **Tailscale**.
- **Gestão (orquestração/atualização):** como você **instala/atualiza/monitora** os serviços em
  muitos devices → **Rancher** (futuro).

Ambos operam **de dentro para fora** (o agente sai do device para o servidor) → **nenhuma porta
aberta** no Jetson.

## 1. Acesso remoto — Tailscale

- Instalar o Tailscale **no host** e autenticar o device no seu tailnet.
- **MagicDNS:** cada device ganha um nome (ex.: `orwell-01`).
- A **Clip API** escuta numa porta (ex.: `8080`). Acesso remoto:
  `GET http://orwell-01:8080/clips?camera=0&start=...&end=...` → MP4.
- **ACLs** do Tailscale restringem quem alcança quais devices/portas.
- **Tailscale SSH** para console seguro (operar/depurar sem expor SSH público).

## 2. Atualização dos serviços

### POC (agora) — simples
- Imagens **buildadas localmente** no Jetson (`docker compose build`). **Sem registry.**
- Atualizar = `git pull` + `docker compose up -d --build` via **Tailscale SSH** (ou um script em
  `deploy/`).
- Suficiente para 1–poucos devices durante a POC.

### Frota (futuro) — GitOps com Rancher
1. **K3s** (Kubernetes leve, arm64) substitui o docker-compose no device.
2. Serviços empacotados num **Helm chart** (Deployments/DaemonSets equivalentes aos containers).
3. **Registry** de imagens (GHCR se usar GitHub, ou Harbor on-prem) guarda imagens **arm64**
   versionadas (tag por commit). Ver [ADR-0009](decisions/0009-deploy-compose-now-k3s-rancher-later.md).
4. **Rancher Fleet (GitOps):** push de manifests no Git → Fleet **rola a atualização** para toda a
   frota. Atualizar = mudar a **tag da imagem** no Git.
5. **CI** builda a imagem arm64 → push no registry → Fleet aplica.

### Separação de camadas (regra de ouro)
- **Rancher/K3s atualizam os _containers_** (recorder, clip-api, uploader, broker).
- **Driver GMSL + JetPack + Tailscale vivem no _host_.** Atualizá-los é **outra camada**
  (provisionamento de SO) → Yocto / **Rancher Elemental** no futuro. **Não misturar.**

### Pegadinha: GPU + câmera no Kubernetes (futuro K3s)
- Requer o **NVIDIA device plugin** para expor a GPU aos pods.
- O pod `recorder` roda **privilegiado**, com `/dev/video*` e o **socket do Argus** montados
  (hostPath). O **driver continua no host**.

## 3. Provisionamento de um device (provisionamento como código)

Tudo que toca o host é **script idempotente** em [`deploy/`](../deploy/) — ver
[`deploy/README.md`](../deploy/README.md) e [ADR-0013](decisions/0013-provisionamento-como-codigo.md).
Fluxo "placa zerada → no ar":

0. **Pré-requisito (fora dos scripts):** flashar **JetPack/L4T** via SDK Manager (PC host).
1. Editar [`deploy/00-versions.env`](../deploy/00-versions.env) (device name, storage, driver GMSL,
   Tailscale).
2. `sudo ./deploy/99-bootstrap.sh` — roda em ordem e idempotente:
   `10-base` → `20-storage` → `40-docker` → `50-nvidia-runtime` → `60-tailscale` → `70-time-ntp` →
   `30-gmsl-driver` (driver por último; exige reboot).
3. `sudo reboot` → `sudo ./deploy/host-verify.sh` (sanidade: L4T, Docker+nvidia, `/dev/video*`,
   Tailscale, NTP, disco).
4. `docker compose up -d --build` (POC) ou juntar ao cluster **K3s/Rancher** (frota).

> Versões/valores específicos da placa vivem em `00-versions.env`; desvios manuais em
> `deploy/provisioning-log.md`.

## 4. Backups / nuvem

- Clipes de evento vão para a **nuvem** via `uploader` (backend plugável, **S3 por padrão**).
- O buffer contínuo **não** é enviado para a nuvem (fica no NVMe, rotacionado). Só os recortes
  (eventos ou GET sob demanda) saem do device.
