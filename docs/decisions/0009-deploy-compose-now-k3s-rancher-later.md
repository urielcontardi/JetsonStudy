# ADR-0009 — docker-compose agora → K3s + Rancher Fleet depois

**Status:** Aceito · 2026-05-31

## Contexto
A POC roda em 1 device; o futuro é uma **frota** gerida por **Rancher**. Começar já em K3s adiciona
complexidade; começar sem containers dificultaria a migração.

## Decisão
- **POC:** **docker-compose** com os 4 serviços, imagens **buildadas localmente** (sem registry).
- **Frota (futuro):** **K3s** (arm64) + **Helm** + **Rancher Fleet** (GitOps); **registry** de
  imagens (GHCR/Harbor) entra nesta fase.
- Serviços escritos **12-factor** desde já para tornar a migração mecânica.

## Consequências
- POC simples e rápida; caminho de escala claro e de baixo atrito.
- Registry deliberadamente adiado (decisão do usuário: "vem depois com o Rancher").
- GPU/câmera no K8s exigirão NVIDIA device plugin + pod privilegiado (registrado em operations.md).
