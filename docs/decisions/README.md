# Decisões de Arquitetura (ADRs) — Orwell

Cada ADR registra **uma decisão**, o **contexto** e as **consequências**. Formato leve inspirado em
Michael Nygard. Atualize o status se uma decisão for revista.

| # | Decisão | Status |
|---|---|---|
| [0001](0001-dvr-borda-no-jetson.md) | Gravar DVR de borda no Jetson com ZED X One S | Aceito |
| [0002](0002-stereolabs-so-driver-gmsl.md) | Da Stereolabs, só o driver GMSL (sem ZED SDK pesado) | Aceito |
| [0003](0003-deepstream-plano-de-midia.md) | DeepStream como plano de mídia/IA | Aceito |
| [0004](0004-stack-tudo-python.md) | Stack: tudo em Python | Aceito |
| [0005](0005-encode-h264-software-perfil-reduzido.md) | Encode H.264 por software + perfil reduzido | Superseded por 0014 |
| [0006](0006-mp4-padrao-splitmuxsink.md) | MP4 padrão via splitmuxsink (não SVO) | Aceito |
| [0007](0007-indice-sqlite.md) | Índice de segmentos em SQLite | Aceito |
| [0008](0008-acesso-remoto-tailscale.md) | Acesso remoto via Tailscale | Aceito |
| [0009](0009-deploy-compose-now-k3s-rancher-later.md) | docker-compose agora → K3s + Rancher Fleet depois | Aceito |
| [0010](0010-storage-nuvem-plugavel-s3.md) | Storage de nuvem plugável (S3 por padrão) | Aceito |
| [0011](0011-sem-yocto-na-poc.md) | Sem Yocto na POC | Aceito |
| [0012](0012-orin-nx-caminho-de-escala.md) | Orin NX como **alvo primário** (NVENC/H.265) | Aceito |
| [0013](0013-provisionamento-como-codigo.md) | Provisionamento do host como código (reproduzível) | Aceito |
| [0014](0014-encoder-configuravel-hw-sw.md) | Encoder selecionável por config (NVENC HW + x264 SW fallback) | Aceito |
