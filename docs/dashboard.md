# Orwell Operations Portal

O dashboard é a documentação operacional do device. Ele reúne estado da Clip API, câmeras
indexadas, preview HLS, geração de clipes, configuração de upload, catálogo executável de rotas e
o diagrama de arquitetura.

## URLs públicas

- `/` e `/docs`: portal operacional.
- `/api/*`: Clip API, eventos, compatibilidade Friday e configuração.
- `/preview/cam{id}`: preview HLS servido pelo MediaMTX.
- `/architecture.svg`: diagrama renderizado.
- `/architecture.d2`: fonte versionado do diagrama.

O navegador nunca deve acessar diretamente as portas internas `8080` e `8888`. No Compose, Nginx
publica a porta `80`; no K3s, Traefik mantém os mesmos paths.

## Atualização da arquitetura

Edite `docs/diagrams/architecture.d2` e regenere o SVG:

```bash
d2 docs/diagrams/architecture.d2 docs/diagrams/architecture.svg
```

O Dockerfile do dashboard copia ambos os arquivos para a imagem. Assim, o portal sempre mostra o
diagrama correspondente à versão implantada.
