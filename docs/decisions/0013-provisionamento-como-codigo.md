# ADR-0013 — Provisionamento do host como código (reproduzível desde placa zerada)

**Status:** Aceito · 2026-05-31

## Contexto
O SSD chega com apenas o SO base (JetPack/L4T flashado). Tudo o que é feito no host depois —
instalar Docker, NVIDIA Container Runtime, driver GMSL, Tailscale, NTP, preparar storage — precisa
ser **reproduzível e rápido**: pegar uma placa zerada e colocá-la em produção em minutos, sem
depender de memória ou passos manuais.

## Decisão
**Provisionamento como código.** Todo comando que instala/modifica o ambiente Linux vive em
**scripts idempotentes numerados** em `deploy/`, orquestrados por `99-bootstrap.sh`, com um runbook
(`deploy/README.md`) e um log de desvios (`deploy/provisioning-log.md`). **Nada** é feito ad-hoc no
host sem ser registrado. Versões e valores específicos da placa ficam em `00-versions.env`.

Flashar o JetPack/L4T (via SDK Manager num PC host) é o **passo 0**, pré-requisito documentado fora
dos scripts on-device (não é scriptável no próprio Jetson).

## Consequências
- Deploy de uma placa nova = editar `00-versions.env` → `sudo ./deploy/99-bootstrap.sh` → reboot →
  `host-verify.sh` → `docker compose up`.
- Idempotência permite re-execução segura e evolução incremental.
- Driver GMSL (kernel) e SO permanecem **no host** (não conteinerizáveis); a fronteira host×container
  fica explícita (ver ADR-0009).
- Caminho de escala: estes scripts podem virar imagem base / **Rancher Elemental** na fase de frota.
- Segredos (Tailscale authkey) e artefatos (.deb do driver) ficam fora do git (`.gitignore`).
