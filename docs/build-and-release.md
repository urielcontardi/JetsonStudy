# Build e distribuição de imagens

## Desenvolvimento em um Jetson

O primeiro build do `recorder` é caro porque baixa a imagem DeepStream e instala dependências do
runtime de mídia. Alterações em Python não invalidam essa camada: as dependências de sistema ficam
antes dos comandos `COPY`.

O Dockerfile usa cache BuildKit para índices e pacotes APT. Se a camada for invalidada, downloads
já presentes no builder podem ser reutilizados. A disponibilidade dos repositórios NVIDIA ainda
afeta builds que realmente precisem atualizar essa camada.

Para builds normais:

```bash
DOCKER_BUILDKIT=1 docker compose --profile jetson build recorder
```

Não use `--no-cache` e não execute limpezas periódicas de cache no device sem necessidade.

## Produção e frota

Devices de produção não devem compilar imagens. O fluxo recomendado é:

1. CI arm64 constrói e testa uma imagem imutável.
2. A imagem é publicada em registry por digest e tag de commit.
3. Compose, K3s ou Rancher Fleet apenas executam/puxam a imagem.
4. O cache BuildKit é exportado para o registry para acelerar o próximo build da CI.

A imagem pesada do recorder deve ser reconstruída somente quando mudar uma destas entradas:

- digest/tag da imagem DeepStream;
- dependências APT;
- dependências Python;
- código do recorder.

Na evolução para K3s, mantenha o recorder como workload específico do Jetson e use imagens arm64
pré-construídas. Fleet deve atualizar a referência da imagem, não disparar builds nos devices.

## Imagem-base interna

Quando houver CI e registry estáveis, separe uma imagem `orwell-recorder-runtime` contendo
DeepStream, FFmpeg, PyGObject e dependências Python. O Dockerfile da aplicação passa a copiar apenas
o código sobre essa base. Essa imagem de runtime deve ser versionada e reconstruída apenas quando
o JetPack, DeepStream ou as dependências mudarem.
