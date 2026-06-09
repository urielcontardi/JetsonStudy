from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_HERE = Path(__file__).parent


def _page(name: str) -> str:
    return (_HERE / name).read_text()


def create_app() -> FastAPI:
    app = FastAPI(title="Orwell Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _page("page.html")

    @app.get("/config", response_class=HTMLResponse)
    def config():
        return _page("config.html")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
