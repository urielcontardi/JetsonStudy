# ADR-0003 — DeepStream como plano de mídia/IA

**Status:** Aceito · 2026-05-31

## Contexto
Precisamos de: captura multi-câmera, gravação contínua, inferência futura e recorte de eventos
(~10 s pré/pós). O DeepStream (NVIDIA, sobre GStreamer) já entrega inferência batched multi-stream,
**Smart Record** (cache pré-evento + recorte por trigger) e **`nvmsgbroker`** (eventos para a
nuvem). Alternativa seria montar GStreamer puro + TensorRT manualmente.

## Decisão
Adotar **DeepStream desde o início** como espinha dorsal do plano de mídia/IA.

## Consequências
- Ganhamos Smart Record, inferência multi-stream e mensageria "de fábrica".
- Curva de aprendizado e peso maiores que GStreamer puro — aceitável dado o roadmap de IA.
- Base de container = imagem L4T/DeepStream da NVIDIA (`nvcr.io`).
- ⚠️ Smart Record cacheia frames **já codificados** → ainda depende do encode (software no Orin
  Nano; ver ADR-0005).
- Na Fase 1, `nvinfer` fica **stub/desligado**; o pipeline de gravação já roda.
