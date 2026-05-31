# Glossário — Orwell

Vocabulário do projeto em linguagem simples. Quando um termo aparecer em outro doc, ele está
definido aqui.

## Conceito central: onde a performance acontece

Pense em **duas pistas**:
- **Pista rápida (nativa):** capturar, converter, **codificar (encode)** e rodar **IA** — tudo em
  código C/C++/CUDA já compilado. Os frames vivem em memória da GPU e fluem entre blocos **sem
  passar pelo Python**.
- **Pista de controle (Python):** monta o pipeline, liga/desliga e **reage a eventos** (texto leve).

> Analogia: Python é o **maestro** (coordena); GStreamer/DeepStream/TensorRT são a **orquestra**
> (tocam). Você só perde performance se puxar **cada pixel** para o Python (ex.: numpy por frame).

## Captura e vídeo

- **GMSL2** — interface de câmera de alta banda por cabo coaxial (industrial/automotivo). As ZED X
  One usam GMSL2; **não é USB**. Exige placa de captura (ZED Link) e **driver de kernel**.
- **Driver GMSL (Stereolabs)** — driver de **kernel** que faz a câmera ZED **existir** para o
  Jetson. Casado com a versão do JetPack/L4T. **Obrigatório** e vive **no host** (não no container).
- **Argus / Libargus** — API **da NVIDIA** (parte do JetPack) para ler câmeras CSI/GMSL2 no Jetson.
  O bloco GStreamer `nvarguscamerasrc` usa Argus por baixo. **Não é da Stereolabs.**
- **`zedx-one-capture`** — API open-source da Stereolabs para pegar frames da ZED X One **sem** o
  ZED SDK pesado. Alternativa ao Argus se houver necessidade de ajuste fino de ISP.
- **GStreamer** — "Lego de vídeo": você encaixa **elementos** (ler câmera, converter, codificar,
  gravar) formando um **pipeline**. Base de quase tudo em vídeo no Linux.
- **`splitmuxsink`** — elemento que **grava o vídeo em pedacinhos** (ex.: 10 s) e apaga os antigos
  quando o disco enche. **É o buffer circular / DVR pronto.**
- **GOP / keyframe** — vídeo comprimido tem quadros-chave (keyframes/I-frames) e quadros que
  dependem deles. **GOP curto (~1 s)** = keyframes frequentes → dá para **cortar por cópia** (sem
  recomprimir) com boa precisão.
- **Cópia de stream (`-c copy`)** — recortar/concatenar vídeo **sem recomprimir**. Rápido e barato
  (essencial sem NVENC). Corta nas bordas de keyframe.
- **Codec H.264 / H.265** — formatos de compressão. H.265 comprime melhor (~metade do tamanho) mas
  custa mais para codificar; **inviável por software em tempo real para 2 streams** no Orin Nano.
- **Container MP4/MKV** — "embalagem" do vídeo. Usamos **MP4 padrão** (tocável em qualquer lugar),
  não o **SVO** proprietário da Stereolabs.

## Hardware NVIDIA

- **Jetson Orin Nano** — módulo de compute de borda com GPU. ⚠️ **Sem NVENC** (encoder de hardware);
  só **NVDEC** (decoder). Por isso o encode é por **software (CPU)**.
- **NVENC / NVDEC** — blocos de hardware para **codificar** / **decodificar** vídeo. Orin Nano só
  tem NVDEC. **Orin NX e AGX Orin têm NVENC.**
- **Orin NX** — módulo **pino-compatível** com o carrier do Orin Nano, **com NVENC**. Caminho de
  escala para H.265 por hardware **sem reprojetar a placa**.
- **JetPack / L4T** — o "sistema operacional" do Jetson (Ubuntu + drivers NVIDIA). Base sobre a
  qual instalamos o driver GMSL e rodamos os containers.

## IA / DeepStream

- **TensorRT** — **otimizador/motor de inferência** da NVIDIA. "Compila" um modelo de IA para rodar
  o mais rápido possível na GPU do Jetson. É onde a IA realmente roda.
- **Modelo / engine** — o modelo de IA treinado (ex.: detector de objetos). Convertido para um
  **engine** TensorRT (arquivo `.engine`) específico do hardware.
- **DeepStream** — **GStreamer turbinado pela NVIDIA** para analytics de vídeo: inferência em
  múltiplos streams, rastreamento, e recursos prontos como Smart Record e envio de eventos.
  - **`nvinfer`** — elemento que roda o modelo TensorRT sobre os frames.
  - **`nvstreammux`** — junta várias câmeras num "lote" (batch) para inferência eficiente.
  - **Smart Record (NvDsSR)** — gravador que mantém os últimos ~10 s em cache e, ao receber um
    **evento**, salva um clipe com o **antes e o depois**. Encaixa no "evento → 10 s → nuvem".
  - **`nvmsgbroker`** — envia eventos/metadados para a nuvem (Kafka, MQTT, Azure IoT, AMQP).
  - **`pyds`** — bindings **Python** do DeepStream. Permite escrever o app em Python.

## Mensageria e dados

- **MQTT** — protocolo de **mensageria leve** (publish/subscribe). Um serviço "publica" um evento,
  outro "assina". Desacopla quem detecta (recorder) de quem age (uploader).
- **Mosquitto** — um broker MQTT leve e popular. Rodamos local como o `broker`.
- **SQLite** — banco de dados em um **único arquivo**, sem servidor. Usamos como **índice** dos
  segmentos gravados (a "tabela de conteúdo" do DVR).

## Rede, deploy e operação

- **Tailscale** — **VPN ponto-a-ponto** (sobre WireGuard). Cria uma rede privada entre você e o
  Jetson mesmo atrás de NAT/4G, **sem abrir portas**. Como você alcança a Clip API remotamente.
  - **MagicDNS** — dá um **nome** a cada device (ex.: `orwell-01`).
  - **ACLs** — regras de quem pode acessar o quê.
- **Docker** — **empacota** um serviço (código + dependências) numa **imagem** que roda igual em
  qualquer máquina. Um **container** é uma instância rodando dessa imagem.
- **docker-compose** — descreve e sobe **vários containers** juntos (recorder, clip-api, uploader,
  broker). Usado na POC.
- **Registry** — a **"App Store" das imagens**: onde a imagem buildada **mora** para os devices
  **baixarem** (`pull`). Ex.: GHCR, Harbor, ECR. **Entra na fase de frota (com o Rancher).** Na POC,
  buildamos local (sem registry).
- **NVIDIA Container Runtime** — runtime que dá aos containers acesso à **GPU** e aos dispositivos
  de câmera do Jetson.
- **Kubernetes / K3s** — orquestrador de containers em escala. **K3s** é a versão **leve** que roda
  bem no Jetson (arm64). Substitui o docker-compose quando há muitos devices.
- **Helm** — "gerenciador de pacotes" do Kubernetes; empacota os serviços num **chart**.
- **Rancher** — plataforma de **gestão de frota** de clusters Kubernetes. Onde você administra,
  atualiza e monitora muitos devices.
- **Rancher Fleet** — **GitOps**: você dá `push` em manifests num repositório Git e o Fleet **rola
  a atualização** para toda a frota automaticamente. É o "OTA dos serviços".
- **Rancher Elemental** — gestão do **sistema operacional** dos devices (camada abaixo dos
  containers). Relevante para atualizar host/driver no futuro.
- **Yocto** — ferramenta para **montar uma distribuição Linux sob medida** (imagem mínima,
  read-only, OTA) para produto em escala. **Não usado na POC** (JetPack padrão); entra ao
  industrializar.
- **OTA (Over-The-Air)** — atualização remota. Para **serviços** = Rancher Fleet; para **SO/driver**
  = Yocto/Elemental.
- **12-factor** — conjunto de boas práticas (config externa, logs no stdout, sem estado escondido)
  que torna um serviço fácil de conteinerizar e orquestrar.
