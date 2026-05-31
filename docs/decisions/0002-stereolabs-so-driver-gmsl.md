# ADR-0002 — Da Stereolabs, só o driver GMSL (sem ZED SDK pesado)

**Status:** Aceito · 2026-05-31

## Contexto
As ZED X One S são **monoculares** e o caso de uso é **RGB + IA 2D** (detecção), **não
profundidade**. A Stereolabs oferece (a) um **driver GMSL** de kernel (obrigatório para a câmera
existir no Jetson) e (b) o **ZED SDK** pesado (CUDA) para profundidade/3D/gravação SVO. As câmeras
GMSL2 também podem ser lidas pelo **Argus (NVIDIA)** sem o SDK.

## Decisão
Usar **apenas o driver GMSL** da Stereolabs. Captura via **Argus** (`nvarguscamerasrc`). **Não**
adotar o ZED SDK pesado nesta fase.

## Consequências
- Menos peso de CPU/GPU competindo com o DeepStream; menos dependências.
- Gravação em **MP4 padrão** (não SVO) — ver ADR-0006.
- Profundidade fica disponível como evolução futura (parear 2 câmeras com o ZED SDK), se um caso
  de uso exigir.
- O driver continua sendo um requisito **de host**, casado com a versão do L4T.
